"""cutaway_gen — the structural half of the identity guarantee (issue #43).

Spec `docs/intent/reel-batch-spec.md` §3 R5(c), R8, §5. Three properties are load
bearing and each has a test that fails if the code is reverted:

1. **Media references are refused.** Any input carrying a reference image, frame or
   video is rejected before pricing and before sending — under its documented key,
   under an alternate key, or nested inside another structure.
2. **The route is pinned.** One inputs dict is built per cutaway and the identical
   object is handed to ``estimate_cost`` and ``execute``; unpinned the same shortfall
   routes to seedance at $1.52/clip instead of kling at $0.10.
3. **Trimming is mandatory and the output is measured.** The generator's duration is a
   hint, so the flash is cut out of whatever length came back, silent and 9:16, and
   the result is probed rather than assumed.

The provider is stubbed (no paid calls) except for one live-registry pricing check,
which skips when the pin does not resolve on this machine.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.base_tool import ToolResult, ToolStatus
from tools.video.cutaway_gen import (
    CUTAWAY_PROVIDER_PIN,
    CutawayGen,
    MediaReferenceRefusedError,
    ProbeFailedError,
    _SAFE_KEYS,
    _is_media_key,
    _probe as probe_measured_facts,
    refuse_media_references,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)


# ---------------------------------------------------------------------------
# Stub provider: records every dict it is handed, writes a real clip on execute
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.estimated: list[dict[str, Any]] = []
        self.executed: list[dict[str, Any]] = []
        # What the "generator" actually returns — deliberately NOT 5s, NOT 9:16
        # and NOT silent, because no code may depend on getting what it asked for.
        self.clip_seconds = 3.2
        self.clip_size = (1920, 1080)
        self.clip_has_audio = True


@pytest.fixture()
def provider(monkeypatch) -> _Recorder:
    recorder = _Recorder()

    class _FakeSelector:
        def estimate_cost(self, inputs: dict[str, Any]) -> float:
            recorder.estimated.append(inputs)
            return 0.10

        def execute(self, inputs: dict[str, Any]) -> ToolResult:
            recorder.executed.append(inputs)
            out = Path(inputs["output_path"])
            out.parent.mkdir(parents=True, exist_ok=True)
            _make_clip(out, recorder.clip_size, recorder.clip_seconds, recorder.clip_has_audio)
            return ToolResult(
                success=True,
                data={
                    "output_path": str(out),
                    "selected_provider": "kling",
                    "executed_estimate_usd": 0.10,
                },
                cost_usd=0.10,
            )

    monkeypatch.setattr("tools.video.cutaway_gen.VideoSelector", _FakeSelector)
    return recorder


@pytest.fixture()
def forbidden_provider(monkeypatch) -> None:
    """A provider that must never be touched — the pool-suffices path."""

    class _NoCallSelector:
        def estimate_cost(self, inputs: dict[str, Any]) -> float:
            raise AssertionError("provider priced despite no shortfall")

        def execute(self, inputs: dict[str, Any]) -> ToolResult:
            raise AssertionError("provider called despite no shortfall")

    monkeypatch.setattr("tools.video.cutaway_gen.VideoSelector", _NoCallSelector)


def _make_clip(path: Path, size: tuple[int, int], seconds: float, with_audio: bool) -> None:
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           f"color=c=teal:s={size[0]}x{size[1]}:d={seconds}:r=30"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p", "-t", str(seconds), str(path)]
    subprocess.run(cmd, capture_output=True, check=True)


def _probe(path: Path) -> dict[str, Any]:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=width,height,codec_type",
         "-of", "default=noprint_wrappers=1", str(path)]
    ).decode()
    return dict(
        line.split("=", 1) for line in out.strip().splitlines() if "=" in line
    )


def _inputs(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "prompts": ["chalk dust hanging in a shaft of gym light"],
        "cache_dir": str(tmp_path / "cache"),
        "output_dir": str(tmp_path / "out"),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. The refusal — every reference key the generators accept
# ---------------------------------------------------------------------------

# Drawn from the video_selector / kling_video / gemini_omni_video input schemas.
REFERENCE_KEYS = [
    "reference_image_path",
    "reference_image_url",
    "reference_image_urls",
    "reference_image_paths",
    "image_url",
    "init_video",
    "init_image",
    "reference_video_path",
    "reference_video_url",
    "last_image_url",
    "video_path",
    "video_clips",
    "image_list",
    "video_list",
    "element_list",
    "refers",
    "reference_audio_paths",
]


@pytest.mark.parametrize("key", REFERENCE_KEYS)
def test_media_reference_key_is_refused(tmp_path, forbidden_provider, key):
    """Each documented reference key fails closed, in estimate AND in execute."""
    tool = CutawayGen()
    payload = _inputs(tmp_path, **{key: "/pool/gym_set_03.mp4"})

    with pytest.raises(MediaReferenceRefusedError):
        tool.estimate_cost(payload)
    with pytest.raises(MediaReferenceRefusedError):
        tool.execute(payload)


def test_refusal_names_the_offending_key(tmp_path, forbidden_provider):
    tool = CutawayGen()
    with pytest.raises(MediaReferenceRefusedError, match="reference_image_path"):
        tool.execute(_inputs(tmp_path, reference_image_path="/pool/face.png"))


def test_refusal_not_bypassable_by_alternate_key(tmp_path, forbidden_provider):
    """A gym clip smuggled in under a harmless name is still a gym clip."""
    tool = CutawayGen()
    with pytest.raises(MediaReferenceRefusedError):
        tool.execute(_inputs(tmp_path, style_hint="/home/operator/pool/deadlift.mp4"))


def test_refusal_not_bypassable_by_nesting(tmp_path, forbidden_provider):
    """Nested inside a list inside a dict under an innocuous key."""
    tool = CutawayGen()
    nested = {"extras": {"shots": [{"look": "/pool/gym_set_03.mov"}]}}
    with pytest.raises(MediaReferenceRefusedError):
        tool.execute(_inputs(tmp_path, provider_options=nested))


def test_refusal_covers_data_uri_and_raw_bytes(tmp_path, forbidden_provider):
    tool = CutawayGen()
    with pytest.raises(MediaReferenceRefusedError):
        tool.execute(_inputs(tmp_path, seed_hint="data:image/png;base64,iVBORw0KGgo="))
    with pytest.raises(MediaReferenceRefusedError):
        tool.execute(_inputs(tmp_path, seed_hint=b"\x89PNG\r\n\x1a\n"))


def test_refusal_covers_reference_smuggled_into_the_prompt_list(tmp_path, forbidden_provider):
    tool = CutawayGen()
    with pytest.raises(MediaReferenceRefusedError):
        tool.execute(_inputs(tmp_path, prompts=["a rack of dumbbells", "/pool/gym.mp4"]))


def test_prose_prompts_are_not_falsely_refused(tmp_path, provider):
    """The guard must not block ordinary prompts — a refusal that blocks everything
    is not a guarantee, it is an outage."""
    result = CutawayGen().execute(_inputs(
        tmp_path,
        prompts=["barbell knurling in hard side light, shot on 35mm, no people"],
    ))
    assert result.success, result.error


# ---------------------------------------------------------------------------
# 2. The pin, the cost model, and the one-dict rule
# ---------------------------------------------------------------------------


def test_single_cutaway_estimates_ten_cents_on_the_pinned_route(tmp_path, provider):
    assert CutawayGen().estimate_cost(_inputs(tmp_path)) == 0.10
    payload = provider.estimated[0]
    assert payload.get("allowed_providers") == CUTAWAY_PROVIDER_PIN, (
        "the route is no longer pinned — the sitting now prices at whatever the "
        "selector ranks top for this prompt"
    )
    assert payload["duration"] == "5"          # kling's hard floor
    assert payload["aspect_ratio"] == "9:16"
    assert payload["operation"] == "text_to_video"


def test_five_reel_shortfall_estimates_fifty_cents(tmp_path, provider):
    inputs = _inputs(tmp_path, prompts=[f"gym detail {i}" for i in range(5)])
    assert CutawayGen().estimate_cost(inputs) == 0.50


def test_pool_sufficient_sitting_costs_nothing_and_makes_no_call(tmp_path, forbidden_provider):
    """R8: the valve fires only on a measured shortfall. No shortfall, no call."""
    tool = CutawayGen()
    inputs = _inputs(tmp_path, prompts=[])
    assert tool.estimate_cost(inputs) == 0.0
    result = tool.execute(inputs)
    assert result.success
    assert result.cost_usd == 0.0
    assert result.data["cutaways"] == []


def test_estimate_and_execute_receive_the_identical_dict(tmp_path, provider):
    """Defect D3: pricing a pinned route and executing an unpinned one is a 15x
    under-price that slips both approval guards. One dict, built once."""
    tool = CutawayGen()
    inputs = _inputs(tmp_path)

    priced = tool.estimate_cost(inputs)
    result = tool.execute(inputs)
    assert result.success, result.error

    # Inside execute the SAME object is priced and executed.
    assert provider.executed[0] is provider.estimated[-1]
    # And the standalone estimate priced exactly what execute ran.
    assert provider.estimated[0] == provider.executed[0]
    assert priced == result.cost_usd == 0.10


def test_retry_of_a_generated_prompt_is_free(tmp_path, provider):
    tool = CutawayGen()
    inputs = _inputs(tmp_path)

    first = tool.execute(inputs)
    assert first.cost_usd == 0.10
    assert len(provider.executed) == 1

    assert tool.estimate_cost(inputs) == 0.0, "a cached prompt must estimate $0.00"
    second = tool.execute(inputs)
    assert second.success
    assert second.cost_usd == 0.0
    assert second.data["cached_count"] == 1
    assert len(provider.executed) == 1, "cache hit must not call the provider again"


# ---------------------------------------------------------------------------
# 3. Trim, silence, and 9:16 — measured, not assumed
# ---------------------------------------------------------------------------


def test_output_is_a_silent_vertical_subsecond_flash(tmp_path, provider):
    result = CutawayGen().execute(_inputs(tmp_path, flash_seconds=0.6))
    assert result.success, result.error

    cut = result.data["cutaways"][0]
    probed = _probe(Path(cut["output_path"]))
    width, height = int(probed["width"]), int(probed["height"])

    assert "audio" not in probed.get("codec_type", "") and cut["has_audio"] is False
    assert abs(width / height - 9 / 16) < 0.01, f"{width}x{height} is not 9:16"
    assert float(probed["duration"]) == pytest.approx(0.6, abs=0.15)
    assert cut["provenance"] == "ai_generated"


def test_trim_does_not_depend_on_the_requested_duration(tmp_path, provider):
    """The generator returned 3.2s against a requested 5s; the flash is still exact."""
    provider.clip_seconds = 3.2
    result = CutawayGen().execute(_inputs(tmp_path, flash_seconds=0.5))
    cut = result.data["cutaways"][0]

    assert cut["requested_duration_seconds"] == 5.0
    assert cut["actual_duration_seconds"] == pytest.approx(3.2, abs=0.2)
    assert cut["flash_seconds"] == pytest.approx(0.5, abs=0.15)


def test_flash_survives_a_clip_shorter_than_the_flash_window(tmp_path, provider):
    """A route that returns less than asked for must not produce an empty file."""
    provider.clip_seconds = 0.4
    result = CutawayGen().execute(_inputs(tmp_path, flash_seconds=0.6, flash_start_seconds=1.0))
    assert result.success, result.error
    assert result.data["cutaways"][0]["flash_seconds"] > 0.0


# ---------------------------------------------------------------------------
# 4. Live registry — the pin still prices at $0.10 against the real providers
# ---------------------------------------------------------------------------


def test_live_pin_prices_the_sitting_at_fifty_cents(tmp_path):
    from tools.video.video_selector import ProviderPinUnresolvedError

    tool = CutawayGen()
    inputs = _inputs(tmp_path, prompts=[f"gym detail {i}" for i in range(5)])
    try:
        estimate = tool.estimate_cost(inputs)
    except ProviderPinUnresolvedError:
        pytest.skip("pinned kling route is not live on this machine")
    assert estimate == 0.50, "the pinned route must price a five-reel shortfall at $0.50"


# ----------------------------------------------------------------------
# The guard is the identity guarantee. It gets attacked, not sampled.
# ----------------------------------------------------------------------
def _declared_reference_keys() -> set[str]:
    """Every reference-ish input key any live video generator actually accepts.

    Derived from the registry rather than hand-listed: a new provider with a
    new reference key is policed the day it lands, and a key that no tool
    declares cannot quietly pad the count.
    """
    from tools.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.discover()
    keys: set[str] = set()
    for tool in registry.get_by_capability("video_generation"):
        schema = getattr(tool, "input_schema", None) or {}
        for key in (schema.get("properties") or {}):
            if _is_media_key(str(key)) and str(key).lower() not in _SAFE_KEYS:
                keys.add(str(key))
    return keys


def test_every_declared_reference_key_is_refused():
    for key in sorted(_declared_reference_keys()):
        with pytest.raises(MediaReferenceRefusedError):
            refuse_media_references({"prompt": "x", key: "/pool/gym.mp4"})


@pytest.mark.parametrize(
    "label,payload",
    [
        # A frozenset is not a `set` instance, so a type-tuple walk skips it.
        ("frozenset", {"prompt": "x", "extras": frozenset({"/pool/gym.mp4"})}),
        # A key is a value too — the one position a values-only walk never reads.
        ("dict key", {"prompt": "x", "meta": {"/pool/gym.mp4": 1}}),
        ("nested containers", {"prompt": "x", "o": {"a": [{"b": ["/pool/gym.mov"]}]}}),
        ("tuple of dict", {"prompt": "x", "t": ({"deep": "/pool/gym.webm"},)}),
        ("PathLike", {"prompt": "x", "thing": Path("/pool/gym.mp4")}),
        ("data uri", {"prompt": "x", "blob": "data:image/png;base64,AAAA"}),
        ("renamed key", {"prompt": "x", "harmless": "/pool/gym.mp4"}),
        ("raw bytes", {"prompt": "x", "raw": b"\x00\x01"}),
        ("url with query", {"prompt": "x", "u": "https://cdn.x/gym.mp4?sig=abc"}),
    ],
)
def test_media_references_cannot_be_smuggled(label, payload):
    """Wrapping the reference must not decide whether the guarantee applies."""
    with pytest.raises(MediaReferenceRefusedError):
        refuse_media_references(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "empty gym at 5am, cold light", "duration": "5", "output_dir": "/tmp/o"},
        {"prompt": "x", "num_frames": 24, "fps": 30, "generate_audio": False},
        {
            "prompt": "x",
            "preferred_provider": "kling",
            "video_type": "text_to_video",
            "allowed_providers": ["kling"],
            "aspect_ratio": "9:16",
        },
    ],
)
def test_ordinary_generation_inputs_are_not_refused(payload):
    """Substring matching alone rejects num_frames ("frame") and
    preferred_provider ("refer") with an identity-guard message, which is a
    wrong answer delivered alarmingly."""
    refuse_media_references(payload)


# ---------------------------------------------------------------------------
# 5. The probe fails closed — an unmeasurable file is a refusal, not a default
# ---------------------------------------------------------------------------


def _break_ffprobe_for(monkeypatch, marker: str) -> None:
    """Make ffprobe return nothing for paths containing ``marker``.

    Everything else — ffmpeg, and ffprobe on other files — still runs for real,
    so the test isolates ONE unmeasurable file the way a truncated download or a
    codec ffprobe cannot open does.
    """
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "ffprobe" and marker in str(cmd[-1]):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("tools.video.cutaway_gen.subprocess.run", fake_run)


def test_unmeasurable_trimmed_flash_is_refused_not_silently_passed(tmp_path, provider, monkeypatch):
    """The silence check must not pass on a clip nobody measured.

    A swallowed probe returns {}, `.get("has_audio")` is then None, and the
    cutaway is declared silent without anyone having looked — in a tool whose
    contract is that the output is measured, not assumed.
    """
    _break_ffprobe_for(monkeypatch, "_flash")
    result = CutawayGen().execute(_inputs(tmp_path))

    assert not result.success, "an unmeasurable flash must be refused, not accepted"
    assert "could not be measured" in result.error
    assert "_flash" in result.error, "the refusal must name what could not be measured"


def test_unmeasurable_generated_clip_is_refused_before_the_crop_is_skipped(
    tmp_path, provider, monkeypatch
):
    """Unmeasured, the trim skips the 9:16 crop and clamps against a zero duration.

    ffmpeg still succeeds on the source here, so a swallowed probe produces a
    cheerful `success=True` carrying a 16:9 flash.
    """
    _break_ffprobe_for(monkeypatch, "cutaway_")
    result = CutawayGen().execute(_inputs(tmp_path))

    assert not result.success, "an unmeasurable source clip must be refused"
    assert "could not be measured" in result.error


def test_probe_raises_rather_than_reporting_a_file_as_silent_and_sizeless(tmp_path):
    """Directly: a file ffprobe cannot read yields a refusal, not {}."""
    junk = tmp_path / "not_a_video.mp4"
    junk.write_bytes(b"\x00" * 4096)

    with pytest.raises(ProbeFailedError):
        probe_measured_facts(junk)
    with pytest.raises(ProbeFailedError):
        probe_measured_facts(tmp_path / "does_not_exist.mp4")


# ---------------------------------------------------------------------------
# 6. The pin's EFFECT, with no credentials — the guard that used to self-disarm
# ---------------------------------------------------------------------------


@pytest.fixture()
def live_routing(monkeypatch):
    """The real VideoSelector routing over the real kling and seedance tools.

    Only ``get_status`` is faked. The pin check used to be a single test that
    skipped on ProviderPinUnresolvedError, so on every runner without FAL_KEY —
    which is all of CI — the 15x guard was completely unpoliced. Availability is
    the ONLY thing credentials decide here, so forcing it is enough to exercise
    the real filter, the real ranking and the real per-provider pricing.
    """
    from tools.video.kling_video import KlingVideo
    from tools.video.seedance_video import SeedanceVideo
    from tools.video.video_selector import VideoSelector

    live = []
    for cls in (KlingVideo, SeedanceVideo):
        tool = cls()
        monkeypatch.setattr(tool, "get_status", lambda: ToolStatus.AVAILABLE)
        live.append(tool)
    monkeypatch.setattr(VideoSelector, "_providers", lambda self: live)
    return VideoSelector


def test_pin_prices_the_five_reel_sitting_at_fifty_cents_without_credentials(
    tmp_path, live_routing
):
    """The whole point of the pin, priced through the real selector."""
    inputs = _inputs(tmp_path, prompts=[f"gym detail {i}" for i in range(5)])
    assert CutawayGen().estimate_cost(inputs) == 0.50


def test_removing_the_pin_would_route_the_same_sitting_to_the_15x_provider(
    tmp_path, live_routing
):
    """Prove the pin is what makes $0.50 $0.50, not the selector's own preference.

    Price the dict cutaway_gen actually builds, then price the same dict with its
    routing pin dropped. If the second is not multiples of the first, the pin is
    not the thing holding the price down and this test is not policing anything.
    """
    tool = CutawayGen()
    payload = tool._provider_inputs("gym detail 0", tmp_path / "cache")
    assert payload["allowed_providers"] == CUTAWAY_PROVIDER_PIN

    pinned = live_routing().estimate_cost(dict(payload))
    unpinned_payload = {k: v for k, v in payload.items() if k != "allowed_providers"}
    unpinned = live_routing().estimate_cost(unpinned_payload)

    assert pinned == 0.10
    assert unpinned >= 10 * pinned, (
        f"unpinned routing priced {unpinned} against pinned {pinned}: the fixture no "
        "longer contains a materially more expensive alternative, so this test and "
        "the five-cent-sitting test above police nothing"
    )


# ---------------------------------------------------------------------------
# 7. The measurement itself — right stream, plausible values, total refusal
# ---------------------------------------------------------------------------


def _rendered_size(path: Path) -> tuple[int, int]:
    """What ffmpeg's OWN default stream selection decodes from `path`.

    Measured, not asserted: the point of the tests below is that `_probe` agrees
    with the renderer, so the expected value has to come from the renderer.
    """
    out = path.parent / f"{path.stem}_rendered.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-t", "0.2",
         "-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p", str(out)],
        capture_output=True, check=True,
    )
    csv = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)]
    ).decode().strip()
    width, height = csv.split(",")[:2]
    return int(width), int(height)


def _make_two_video_stream_clip(
    path: Path, first: tuple[int, int], second: tuple[int, int]
) -> None:
    """An mp4 whose FIRST video stream is not the one a renderer decodes."""
    a, b = path.parent / "_first.mp4", path.parent / "_second.mp4"
    _make_clip(a, first, 2.0, False)
    _make_clip(b, second, 2.0, False)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(a), "-i", str(b),
         "-map", "0:v", "-map", "1:v", "-c", "copy", str(path)],
        capture_output=True, check=True,
    )


def test_probe_measures_the_stream_a_renderer_decodes(tmp_path):
    """Not `streams[0]` — the stream ffmpeg actually feeds the crop filter.

    The operator's own iPhone .MOV pool clips probe as six streams (one video,
    one audio, four Core Media Metadata), so this is not about that footage; it
    is about the crop being computed from one frame and applied to another the
    moment a container carries more than one video stream. Picking the first
    measured 320x240 on this file while ffmpeg rendered 1920x1080, and the
    resulting crop kept a 134-pixel sliver of a 1080p frame.
    """
    clip = tmp_path / "two_streams.mp4"
    _make_two_video_stream_clip(clip, first=(320, 240), second=(1920, 1080))

    probed = probe_measured_facts(clip)
    assert (probed["width"], probed["height"]) == _rendered_size(clip), (
        "the probe measured a different stream than ffmpeg renders, so the 9:16 "
        "crop is computed for a frame the trim never sees"
    )
    assert (probed["width"], probed["height"]) != (320, 240)


def test_cover_art_is_not_mistaken_for_the_frame(tmp_path):
    """A thumbnail track must lose even when it is the LARGEST video stream.

    Excluding attached_pic is a separate clause from "take the biggest": drop it
    and this 2000x2000 cover out-sizes the real 320x240 video, which ffmpeg
    itself renders as 320x240.
    """
    video, cover = tmp_path / "_v.mp4", tmp_path / "_cover.png"
    clip = tmp_path / "with_cover.mp4"
    _make_clip(video, (320, 240), 2.0, False)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=red:s=2000x2000:d=0.04", "-frames:v", "1", str(cover)],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(cover),
         "-map", "0:v", "-map", "1:v", "-c", "copy",
         "-disposition:v:1", "attached_pic", str(clip)],
        capture_output=True, check=True,
    )

    probed = probe_measured_facts(clip)
    assert (probed["width"], probed["height"]) == _rendered_size(clip)
    assert (probed["width"], probed["height"]) == (320, 240)


def _ffprobe_returns(monkeypatch, payload: str) -> None:
    """Make every ffprobe call inside cutaway_gen succeed with `payload`."""
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("tools.video.cutaway_gen.subprocess.run", fake_run)


def _probe_json(width: Any, height: Any, duration: Any) -> str:
    return json.dumps({
        "streams": [{"codec_type": "video", "width": width, "height": height}],
        "format": {"duration": duration},
    })


@pytest.mark.parametrize(
    "label,payload",
    [
        ("negative width", _probe_json(-100, 1080, "2.0")),
        ("width past the encoder's ceiling", _probe_json(99999, 1080, "2.0")),
        ("a frame too small to crop", _probe_json(3, 3, "2.0")),
        ("negative height", _probe_json(1080, -1, "2.0")),
        ("an hours-long cutaway", _probe_json(1080, 1920, "999999")),
    ],
)
def test_implausible_measurement_is_refused_like_a_missing_one(
    tmp_path, monkeypatch, label, payload
):
    """"Measured" has to mean measured, not merely non-empty.

    Each of these values is recorded into the cutaway dict and the top-level data
    as fact, and each steers the trim. A tool that refuses a MISSING measurement
    but accepts a nonsense one is labelling, not guaranteeing.
    """
    _ffprobe_returns(monkeypatch, payload)
    with pytest.raises(ProbeFailedError):
        probe_measured_facts(tmp_path / "clip.mp4")


def test_an_implausible_width_would_otherwise_silently_skip_the_crop(tmp_path):
    """Why the floor exists: a negative width fails open, it does not fail loudly.

    `_crop_to_vertical` guards `width <= 0` by returning None, which the trim
    reads as "already 9:16" — so an absurd measurement produces a cheerful
    success carrying an uncropped flash.
    """
    from tools.video.cutaway_gen import _crop_to_vertical

    assert _crop_to_vertical(-100, 1080) is None


@pytest.mark.parametrize(
    "label,payload",
    [
        ("json that is not an object", "[]"),
        ("json that is null", "null"),
        ("a non-numeric dimension", _probe_json("wide", 1080, "2.0")),
    ],
)
def test_malformed_probe_output_is_refused_not_raised_as_a_traceback(
    tmp_path, provider, monkeypatch, label, payload
):
    """execute() promises a ToolResult on any probe failure, not only on ours.

    _probe parses whatever ffprobe printed, so malformed-but-valid JSON surfaced
    as AttributeError ("'list' object has no attribute 'get'") or ValueError
    ("invalid literal for int() with base 10: 'wide'"). Guards that caught only
    ProbeFailedError let those escape execute() as a crash.
    """
    _ffprobe_returns(monkeypatch, payload)
    result = CutawayGen().execute(_inputs(tmp_path))

    assert not result.success, "a malformed probe must be refused, not accepted"
    assert "could not be measured" in result.error


@pytest.mark.parametrize(
    "label,payload",
    [
        ("json that is not an object", "[]"),
        ("a non-numeric dimension", _probe_json("wide", 1080, "2.0")),
    ],
)
def test_probe_converts_its_own_parse_failures_into_the_documented_error(
    tmp_path, monkeypatch, label, payload
):
    """Directly: _probe's only failure type is ProbeFailedError."""
    _ffprobe_returns(monkeypatch, payload)
    with pytest.raises(ProbeFailedError):
        probe_measured_facts(tmp_path / "clip.mp4")


@pytest.mark.parametrize("marker", ["cutaway_", "_flash"])
def test_execute_refuses_even_a_probe_failure_of_an_undocumented_type(
    tmp_path, provider, monkeypatch, marker
):
    """Both guards must be total, not just correct for today's failure modes.

    _probe now converts its own parse failures into ProbeFailedError, so this
    injects the escape directly: guards written as `except ProbeFailedError`
    turn any other type into a raw traceback out of execute(), which is a crash
    where the contract promises a refusal. `cutaway_` hits the generated-clip
    guard, `_flash` the trimmed-flash one.
    """
    real_probe = probe_measured_facts

    def flaky(path: Path) -> dict[str, Any]:
        if marker in Path(path).name:
            raise AttributeError("'list' object has no attribute 'get'")
        return real_probe(path)

    monkeypatch.setattr("tools.video.cutaway_gen._probe", flaky)
    result = CutawayGen().execute(_inputs(tmp_path))

    assert not result.success, "an unmeasurable clip must be refused, not accepted"
    assert "could not be measured" in result.error
