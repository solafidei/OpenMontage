"""Identity-guarded AI cutaway generation for reel-batch.

The structural half of the identity guarantee (spec `docs/intent/reel-batch-spec.md`
§3 R5(c), R8, §5). Two properties carry the whole tool:

**It fails closed.** Any input carrying a media reference — ``reference_image_path``,
``image_url``, ``init_video``, or any equivalent the underlying generators accept — is
refused with :class:`MediaReferenceRefusedError` before a byte is priced or sent. AI
cutaways are TEXT-PROMPT ONLY. This is what structurally prevents the operator's
likeness from reaching a generative model; it is a refusal in code, not a sentence in a
skill file. The scan walks the whole input structure and looks at values as well as
keys, so the refusal cannot be dodged by renaming the key or nesting the reference
inside a list or dict.

**It is a pool relief valve, not the default path.** Under R8 flash cuts come from the
operator's own footage; this tool fires only for the shortfall the ``idea`` gate
measured, at most one cutaway per reel, trimmed to a sub-second flash accent. Called
with no prompts it costs $0.00 and makes no provider call at all.

Route: ``kling_video``, PINNED via ``allowed_providers`` — 5s at $0.10 (its duration
enum ``["5", "10"]`` is a hard floor). Unpinned the same shortfall routes to seedance at
$1.52/clip, 15x, for footage trimmed to half a second. The pinned inputs dict is built
ONCE per prompt and the identical dict is handed to ``estimate_cost`` and ``execute``
(spec §6, defect D3); an unresolvable pin raises ``ProviderPinUnresolvedError`` from
Wave 1 rather than estimating an unguardable $0.00.

Trimming is MANDATORY on every route: generator durations are hints on some routes and
the model chooses the actual length, so no code here depends on getting 5 seconds back.
The trim also strips audio (the music bed comes from the operator's track) and crops to
9:16, and the result is probed rather than assumed. When the probe cannot measure, the
sitting is refused (:class:`ProbeFailedError`): an unmeasurable clip passed the silence
check vacuously and skipped the crop, which is failing open in a fail-closed tool. An
implausible measurement is refused on the same grounds, and the probe measures the
stream a renderer would decode rather than whichever video stream happens to be first.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbcSet
import subprocess
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)
from tools.video.video_selector import VideoSelector

# The pin. Spec §5: kling standard is $0.10 for its 5s floor; the alternatives are
# 3x the price (gemini_omni) or minutes of dead time per clip (the local routes).
CUTAWAY_PROVIDER_PIN = ["kling"]
CUTAWAY_MODEL_VARIANT = "v3/standard"
CUTAWAY_CLIP_SECONDS = "5"
CUTAWAY_ASPECT_RATIO = "9:16"

DEFAULT_FLASH_SECONDS = 0.6
MAX_FLASH_SECONDS = 2.0
DEFAULT_FLASH_START_SECONDS = 1.0

# A generated clip smaller than this is a failed download, not a cache hit.
_MIN_USABLE_BYTES = 1024

# Plausibility bounds on the facts `_probe` calls "measured". A fail-closed tool has
# to refuse an absurd measurement as readily as a missing one, or "measured" is a
# label rather than a guarantee: every one of these values is recorded into the
# cutaway dict and the top-level data as fact, and every one of them steers the trim.
#
# Floor: one H.264 macroblock edge. Nothing smaller is a real generated frame, and
# below it `_crop_to_vertical`'s 9:16 inset collapses to zero — measured this session,
# `_crop_to_vertical(3, 3)` returns "crop=0:2:1:0", which ffmpeg then refuses with
# "Invalid too big or non positive size for width '0'" (ffmpeg -i real.mp4 -vf
# crop=0:100:0:0). A refusal here names the bad measurement instead.
_MIN_PLAUSIBLE_DIMENSION = 16
# Ceiling: libx264's own limit — the encoder `_trim_to_flash` re-encodes with — so
# anything above it could not be trimmed anyway. Measured this session: `ffmpeg -f
# lavfi -i color=c=red:s=16386x16:d=0.1 -frames:v 1 -c:v libx264 -pix_fmt yuv420p`
# fails with "invalid width x height (16386x16)", while s=16384x16 encodes.
_MAX_PLAUSIBLE_DIMENSION = 16384
# One hour. Every generative video route returns clips measured in seconds — this
# tool asks the pinned route for CUTAWAY_CLIP_SECONDS of them — so an hour-long
# "cutaway" is a probe that read a container/playlist duration, or the wrong file
# entirely. Far enough above any real return that a long clip is never refused.
_MAX_PLAUSIBLE_DURATION_SECONDS = 3600.0


class MediaReferenceRefusedError(ValueError):
    """An input carried a media reference. AI cutaways are text-prompt only.

    Raised by both :meth:`CutawayGen.estimate_cost` and :meth:`CutawayGen.execute`
    so the refusal lands before pricing, not only before sending.
    """


class ProbeFailedError(RuntimeError):
    """ffprobe could not measure a file, so nothing about it may be assumed.

    Raised by :func:`_probe` instead of returning an empty dict. Swallowing the
    failure made the 9:16 crop silently optional and the silence check vacuous —
    the two things this tool promises to have measured.
    """


# Any key naming a media reference the video generators accept. Substring matching,
# because the point is to catch equivalents nobody enumerated: image_url,
# reference_image_path, init_video, last_image_url, refers, element_list, video_clips.
_MEDIA_KEY_TOKENS = (
    "image", "video", "audio", "frame", "reference", "refer", "init", "media",
    "asset", "photo", "picture", "clip", "mask", "element", "face", "avatar",
)
# Keys that name where WE write, not what the model reads.
_OUTPUT_KEYS = frozenset({"output_dir", "cache_dir"})

# Routing and generation parameters that contain a media token by coincidence.
# Substring matching alone refuses `num_frames` ("frame") and `preferred_provider`
# ("refer"), which is a wrong answer with a misleading message.
_SAFE_KEYS = frozenset({
    "num_frames", "frame_rate", "fps", "video_type", "preferred_provider",
    "preferred_quality", "generate_audio", "aspect_ratio", "allowed_providers",
})

_MEDIA_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".tiff",
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v",
    ".mp3", ".wav", ".m4a", ".aac", ".flac",
)


def _is_media_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in _MEDIA_KEY_TOKENS)


def _looks_like_media(value: str) -> bool:
    """Whether a bare string is a media reference rather than prose.

    Catches the alternate-key bypass: a gym clip smuggled in under a harmless name
    still ends in ``.mp4``, and a base64 upload still starts ``data:image``.
    """
    text = value.strip().lower()
    if text.startswith(("data:image", "data:video", "data:audio")):
        return True
    # Drop a query string / fragment before looking at the extension.
    for sep in ("?", "#"):
        text = text.split(sep, 1)[0]
    return text.endswith(_MEDIA_SUFFIXES)


def refuse_media_references(value: Any, path: str = "inputs") -> None:
    """Walk an input structure and raise on anything that could carry a likeness.

    Recursive by design: the guarantee is worthless if wrapping the reference in a
    list, a frozenset, or a dict under a key the schema never mentioned gets it
    through. Order matters below — ``str`` is itself a ``Sequence``, so the leaf
    checks must be reached before the container walk.
    """
    # bytes first: also a Sequence, and an upload needs no filename to be a face.
    if isinstance(value, (bytes, bytearray)):
        raise MediaReferenceRefusedError(
            f"{path} carries raw bytes. AI cutaways are text-prompt only (spec R5(c))."
        )
    if isinstance(value, os.PathLike):
        refuse_media_references(os.fspath(value), path)
        return
    if isinstance(value, str):
        if _looks_like_media(value):
            raise MediaReferenceRefusedError(
                f"{path} points at a media file ({value!r}). AI cutaways are "
                "text-prompt only — renaming the key does not make a reference "
                "image safe to send (spec R5(c)). Pass a text prompt instead."
            )
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key)
            # A likeness travels as a path, URL, data-URI or bytes. A bool or a
            # number under a media-named key cannot carry one, and refusing it
            # would reject `num_frames: 24` with an identity-guard message.
            referencable = not isinstance(child, (bool, int, float, type(None)))
            if _is_media_key(name) and name.lower() not in _SAFE_KEYS and referencable:
                raise MediaReferenceRefusedError(
                    f"{path}.{name} names a media reference. AI cutaways are "
                    "text-prompt only — a reference image, frame or video is how the "
                    "operator's likeness would reach a generative model, so it is "
                    "refused outright (spec R5(c)). Pass a text prompt instead."
                )
            # A key is a value too: {"/pool/gym.mp4": 1} puts a path in the one
            # position a values-only walk never inspects.
            refuse_media_references(key, f"{path}.<key {name}>")
            if path == "inputs" and name in _OUTPUT_KEYS:
                continue  # where we write, not what the model reads
            refuse_media_references(child, f"{path}.{name}")
        return
    if isinstance(value, (Sequence, AbcSet)):
        # Not (list, tuple, set): a frozenset is not a `set` instance, and a
        # caller's own Sequence subclass is not a list. The container type must
        # not decide whether the guarantee is enforced.
        for index, child in enumerate(value):
            refuse_media_references(child, f"{path}[{index}]")
        return


class CutawayGen(BaseTool):
    """Generate silent, 9:16, sub-second AI cutaways from text prompts only."""

    name = "cutaway_gen"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    # Deliberately NOT "video_generation": that capability is what video_selector
    # discovers as a provider, and this tool routes THROUGH the selector.
    capability = "cutaway_generation"
    provider = "kling"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = (
        "Install FFmpeg (ffmpeg + ffprobe): https://ffmpeg.org/download.html\n"
        "Set FAL_KEY to your fal.ai API key for the pinned kling route."
    )
    agent_skills = ["ai-video-gen", "ffmpeg"]

    capabilities = ["text_to_video", "cutaway_generation"]
    supports = {
        "text_to_video": True,
        "image_to_video": False,  # refused, structurally — see MediaReferenceRefusedError
        "reference_image": False,
        "native_audio": False,
        "caching": True,
    }
    best_for = [
        "sub-second flash accents when the operator's footage pool falls short",
        "identity-safe b-roll the operator does not appear in",
    ]
    not_good_for = [
        "anything the operator should appear in",
        "cutaways longer than a beat hit",
    ]
    fallback_tools = []

    input_schema = {
        "type": "object",
        "properties": {
            "prompts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "One text prompt per reel that the footage pool cannot cover. "
                    "Empty (the pool suffices) costs $0.00 and makes no call."
                ),
            },
            "prompt": {
                "type": "string",
                "description": "Convenience form of prompts=[...] for a single cutaway.",
            },
            "flash_seconds": {
                "type": "number",
                "minimum": 0.1,
                "maximum": MAX_FLASH_SECONDS,
                "default": DEFAULT_FLASH_SECONDS,
                "description": "Length of the flash accent kept from the generated clip.",
            },
            "flash_start_seconds": {
                "type": "number",
                "minimum": 0,
                "default": DEFAULT_FLASH_START_SECONDS,
                "description": "Where in the generated clip the flash is taken from.",
            },
            "output_dir": {"type": "string", "description": "Where trimmed flashes are written."},
            "cache_dir": {
                "type": "string",
                "description": (
                    "Where generated 5s clips are kept. A prompt already generated "
                    "here is reused and costs $0.00."
                ),
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=500, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompts", "prompt", "flash_seconds", "flash_start_seconds"]
    side_effects = [
        "calls the pinned video provider (paid)",
        "writes generated clips to cache_dir and trimmed flashes to output_dir",
    ]
    user_visible_verification = [
        "Watch the flash in context — it must read as an accent, not a departure",
        "Confirm the operator does not appear in the generated cutaway",
    ]

    # ---- Inputs -------------------------------------------------------------

    @staticmethod
    def _prompts(inputs: dict[str, Any]) -> list[str]:
        prompts = list(inputs.get("prompts") or [])
        if inputs.get("prompt"):
            prompts.append(str(inputs["prompt"]))
        return [str(p) for p in prompts]

    @staticmethod
    def _cache_dir(inputs: dict[str, Any]) -> Path:
        raw = inputs.get("cache_dir")
        base = Path(raw).expanduser() if raw else Path.home() / ".openmontage" / "cutaway_cache"
        return base

    def _provider_inputs(self, prompt: str, cache_dir: Path) -> dict[str, Any]:
        """The pinned inputs dict for one cutaway — built ONCE, priced and executed.

        Deterministic in (prompt, cache_dir) so ``estimate_cost`` and ``execute``
        cannot construct different dicts: pricing a pinned route and then executing
        an unpinned one is a 15x under-price that slips both approval guards.
        """
        payload: dict[str, Any] = {
            "prompt": prompt,
            "operation": "text_to_video",
            "allowed_providers": list(CUTAWAY_PROVIDER_PIN),
            "preferred_provider": CUTAWAY_PROVIDER_PIN[0],
            "model_variant": CUTAWAY_MODEL_VARIANT,
            "duration": CUTAWAY_CLIP_SECONDS,
            "aspect_ratio": CUTAWAY_ASPECT_RATIO,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        payload["output_path"] = str(cache_dir / f"cutaway_{digest}.mp4")
        return payload

    @staticmethod
    def _cached(payload: dict[str, Any]) -> bool:
        path = Path(payload["output_path"])
        return path.is_file() and path.stat().st_size > _MIN_USABLE_BYTES

    # ---- Status / estimates -------------------------------------------------

    def get_status(self) -> ToolStatus:
        status = super().get_status()
        if status != ToolStatus.AVAILABLE:
            return status
        # ffmpeg is here but the paid valve may not be reachable. Say so rather than
        # letting a director plan a shortfall fill that only fails at execute time.
        from tools.tool_registry import registry

        registry.ensure_discovered()
        live = any(
            tool.provider in CUTAWAY_PROVIDER_PIN and tool.get_status() == ToolStatus.AVAILABLE
            for tool in registry.get_by_capability("video_generation")
        )
        return ToolStatus.AVAILABLE if live else ToolStatus.DEGRADED

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        refuse_media_references(inputs)
        cache_dir = self._cache_dir(inputs)
        selector = VideoSelector()
        total = 0.0
        for prompt in self._prompts(inputs):
            payload = self._provider_inputs(prompt, cache_dir)
            if self._cached(payload):
                continue  # a retry of an already-generated prompt is free
            total += selector.estimate_cost(payload)
        return round(total, 4)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        cache_dir = self._cache_dir(inputs)
        uncached = [
            p for p in self._prompts(inputs)
            if not self._cached(self._provider_inputs(p, cache_dir))
        ]
        return 60.0 * len(uncached)  # ~1 min/clip on the pinned route; the trim is free

    # ---- Execution ----------------------------------------------------------

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        refuse_media_references(inputs)
        start = time.time()

        prompts = self._prompts(inputs)
        flash = min(float(inputs.get("flash_seconds", DEFAULT_FLASH_SECONDS)), MAX_FLASH_SECONDS)
        if flash <= 0:
            return ToolResult(success=False, error="flash_seconds must be positive")
        flash_start = max(float(inputs.get("flash_start_seconds", DEFAULT_FLASH_START_SECONDS)), 0.0)

        cache_dir = self._cache_dir(inputs)
        output_dir = Path(inputs["output_dir"]).expanduser() if inputs.get("output_dir") else cache_dir

        cutaways: list[dict[str, Any]] = []
        total_cost = 0.0
        selector = VideoSelector()

        for index, prompt in enumerate(prompts):
            payload = self._provider_inputs(prompt, cache_dir)
            source = Path(payload["output_path"])
            cached = self._cached(payload)
            cost = 0.0
            provider = "cache"

            if not cached:
                cache_dir.mkdir(parents=True, exist_ok=True)
                # ONE dict, priced and executed. The selector stamps
                # estimate_divergence when these differ; they cannot.
                priced = selector.estimate_cost(payload)
                result = selector.execute(payload)
                if not result.success:
                    return ToolResult(
                        success=False,
                        error=f"Cutaway {index + 1}/{len(prompts)} failed: {result.error}",
                        data={"cutaways": cutaways, "total_cost_usd": round(total_cost, 4)},
                    )
                produced = Path(result.data.get("output_path") or result.data.get("output") or source)
                if produced != source:
                    produced.replace(source)
                cost = float(result.data.get("executed_estimate_usd") or result.cost_usd or priced)
                provider = str(result.data.get("selected_provider") or CUTAWAY_PROVIDER_PIN[0])

            try:
                probed = _probe(source)
            except Exception as exc:
                # Fail closed: unmeasured, the trim below would skip the 9:16 crop
                # and clamp against a duration of zero. Refuse the sitting instead.
                # Not just ProbeFailedError: _probe parses whatever ffprobe printed,
                # so malformed output surfaced as AttributeError ('list' object has
                # no attribute 'get') or ValueError (int('wide')) and escaped as a
                # raw traceback — a crash where the contract promises a ToolResult.
                return ToolResult(
                    success=False,
                    error=f"Cutaway {index + 1}/{len(prompts)} could not be measured: {exc}",
                    data={"cutaways": cutaways, "total_cost_usd": round(total_cost, 4)},
                )
            output_dir.mkdir(parents=True, exist_ok=True)
            trimmed = output_dir / f"{source.stem}_flash.mp4"
            try:
                self._trim_to_flash(source, trimmed, probed, flash_start, flash)
            except Exception as exc:  # ffmpeg failure is not silently a cutaway
                return ToolResult(success=False, error=f"Cutaway trim failed: {exc}")

            try:
                trimmed_probe = _probe(trimmed)
            except Exception as exc:  # any probe failure, not only ProbeFailedError
                # An unmeasurable trim cannot be declared silent. Passing the audio
                # check on a missing measurement is how a cutaway with the model's
                # own soundtrack would reach the operator's music bed.
                return ToolResult(
                    success=False,
                    error=f"Trimmed cutaway {trimmed} could not be measured: {exc}",
                    data={"cutaways": cutaways, "total_cost_usd": round(total_cost, 4)},
                )
            if trimmed_probe.get("has_audio"):
                return ToolResult(
                    success=False,
                    error=f"Trimmed cutaway {trimmed} carries an audio track; cutaways must be silent.",
                )

            total_cost += cost
            cutaways.append({
                "prompt": prompt,
                "provider": provider,
                "cached": cached,
                "cost_usd": round(cost, 4),
                "source_path": str(source),
                "output_path": str(trimmed),
                "requested_duration_seconds": float(CUTAWAY_CLIP_SECONDS),
                "actual_duration_seconds": probed.get("duration_seconds"),
                "flash_seconds": trimmed_probe.get("duration_seconds"),
                "width": trimmed_probe.get("width"),
                "height": trimmed_probe.get("height"),
                "has_audio": trimmed_probe.get("has_audio"),
                "provenance": "ai_generated",
            })

        return ToolResult(
            success=True,
            data={
                "cutaways": cutaways,
                "count": len(cutaways),
                "cached_count": sum(1 for c in cutaways if c["cached"]),
                "total_cost_usd": round(total_cost, 4),
                "provenance": "ai_generated",
                "identity_guard": "text_prompt_only",
                "aspect_ratio": CUTAWAY_ASPECT_RATIO,
            },
            artifacts=[c["output_path"] for c in cutaways],
            cost_usd=round(total_cost, 4),
            duration_seconds=round(time.time() - start, 2),
        )

    def _trim_to_flash(
        self,
        source: Path,
        dest: Path,
        probed: dict[str, Any],
        flash_start: float,
        flash: float,
    ) -> None:
        """Cut the flash accent out of whatever length the generator actually returned.

        Mandatory on every route: duration is a hint on some of them, so the clip may
        be shorter or longer than the 5s asked for. Audio is stripped (-an) and the
        frame is centre-cropped to 9:16 from the probed dimensions.
        """
        duration = float(probed.get("duration_seconds") or 0.0)
        if duration:
            flash = min(flash, duration)
            flash_start = min(flash_start, max(duration - flash, 0.0))

        cmd = ["ffmpeg", "-y", "-i", str(source), "-ss", f"{flash_start:.3f}", "-t", f"{flash:.3f}", "-an"]
        crop = _crop_to_vertical(probed.get("width") or 0, probed.get("height") or 0)
        if crop:
            cmd += ["-vf", crop]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(dest)]
        self.run_command(cmd, timeout=180)


def _crop_to_vertical(width: int, height: int) -> str | None:
    """Centre-crop filter forcing 9:16, or None when the frame already is 9:16."""
    if width <= 0 or height <= 0:
        return None
    target_w = min(width, int(height * 9 / 16)) // 2 * 2
    target_h = min(height, int(width * 16 / 9)) // 2 * 2
    if (target_w, target_h) == (width, height):
        return None
    return f"crop={target_w}:{target_h}:{(width - target_w) // 2}:{(height - target_h) // 2}"


def _probe(path: Path) -> dict[str, Any]:
    """Measured facts about a file: duration, dimensions, whether it has audio.

    Raises rather than returning ``{}`` when the measurement fails. Every caller
    reads this dict with ``.get()`` and treats a missing fact as a benign default:
    no width means no 9:16 crop, no duration means no clamp against a short clip,
    and a missing ``has_audio`` reads as False — so an empty probe made the silence
    check pass VACUOUSLY on a clip nobody had measured. In a tool whose contract is
    that the output is measured and not assumed, an unmeasurable file is a refusal.
    """
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except Exception as exc:  # ffprobe missing, killed, or timed out
        raise ProbeFailedError(f"ffprobe could not run on {path}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise ProbeFailedError(
            f"ffprobe exited {proc.returncode} on {path}: "
            f"{detail[-1] if detail else 'no diagnostic'}"
        )
    try:
        data = json.loads(proc.stdout or "")
    except ValueError as exc:
        raise ProbeFailedError(
            f"ffprobe returned no readable measurement for {path}"
        ) from exc

    if not isinstance(data, Mapping):
        # ffprobe's JSON is normally an object, but a truncated or wrapped payload
        # parses to a list or a scalar and every `.get` below is an AttributeError
        # escaping execute() as a traceback where the contract promises a refusal.
        raise ProbeFailedError(
            f"ffprobe returned no readable measurement for {path} "
            f"(got {type(data).__name__}, not an object)"
        )

    streams = data.get("streams") or []
    video = _render_stream(streams)
    fmt = data.get("format")
    duration = fmt.get("duration") if isinstance(fmt, Mapping) else None
    # Name the fact that is missing: "could not be measured" is actionable only if
    # the operator learns whether ffprobe saw no video, or saw one of unknown size.
    try:
        seconds = float(duration)
    except (TypeError, ValueError):
        # Some containers report "N/A" rather than omitting the field.
        seconds = 0.0
    if seconds <= 0:
        raise ProbeFailedError(f"ffprobe measured no duration for {path} ({duration!r})")
    if seconds > _MAX_PLAUSIBLE_DURATION_SECONDS:
        raise ProbeFailedError(
            f"ffprobe measured an implausible duration for {path}: {seconds}s "
            f"exceeds {_MAX_PLAUSIBLE_DURATION_SECONDS}s"
        )
    if not video.get("width") or not video.get("height"):
        raise ProbeFailedError(f"ffprobe measured no video stream dimensions for {path}")

    try:
        width, height = int(video["width"]), int(video["height"])
    except (TypeError, ValueError) as exc:
        # A non-numeric dimension used to escape as a raw ValueError from int().
        raise ProbeFailedError(
            f"ffprobe reported unreadable dimensions for {path}: "
            f"{video.get('width')!r}x{video.get('height')!r}"
        ) from exc
    for label, value in (("width", width), ("height", height)):
        if not _MIN_PLAUSIBLE_DIMENSION <= value <= _MAX_PLAUSIBLE_DIMENSION:
            raise ProbeFailedError(
                f"ffprobe measured an implausible {label} for {path}: {value} is "
                f"outside {_MIN_PLAUSIBLE_DIMENSION}..{_MAX_PLAUSIBLE_DIMENSION}"
            )

    return {
        "duration_seconds": round(seconds, 3),
        "width": width,
        "height": height,
        "has_audio": any(
            isinstance(s, Mapping) and s.get("codec_type") == "audio" for s in streams
        ),
    }


def _render_stream(streams: Any) -> dict[str, Any]:
    """The video stream a renderer would actually decode — not merely the first one.

    ffmpeg's default selection (no ``-map``) is not "the first video stream": it
    skips cover-art/thumbnail streams and then takes the largest by pixel area.
    Taking ``streams[0]`` measures the wrong frame, and since those dimensions are
    what `_crop_to_vertical` builds the 9:16 crop from, the crop is then computed
    for one frame and applied to another.

    Measured this session on a two-video-stream mp4 (320x240 at index 0, 1920x1080
    at index 1): ffmpeg renders 1920x1080, the old first-stream pick measured
    320x240, and the resulting `crop=134:240:93:0` cut a 134-pixel sliver out of a
    1080p frame instead of the correct 606x1080. Cover art is excluded rather than
    just out-sized because it can be the larger stream — also measured, on an mp4
    carrying a 2000x2000 attached_pic beside a 320x240 video, which ffmpeg renders
    as 320x240.
    """
    if not isinstance(streams, Sequence) or isinstance(streams, (str, bytes)):
        return {}

    def pixels(stream: Mapping[str, Any]) -> int:
        try:
            return int(stream["width"]) * int(stream["height"])
        except (KeyError, TypeError, ValueError):
            return 0

    candidates = [
        s for s in streams
        if isinstance(s, Mapping)
        and s.get("codec_type") == "video"
        and not (s.get("disposition") or {}).get("attached_pic")
    ]
    if not candidates:
        return {}
    # max() keeps the earliest of equal keys, matching ffmpeg's strict-greater
    # comparison — so single-video-stream files (all of the operator's own
    # footage) measure exactly as they did before.
    return dict(max(candidates, key=pixels))
