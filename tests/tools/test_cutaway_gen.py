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

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.base_tool import ToolResult
from tools.video.cutaway_gen import (
    CUTAWAY_PROVIDER_PIN,
    CutawayGen,
    MediaReferenceRefusedError,
    _SAFE_KEYS,
    _is_media_key,
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
    assert payload["allowed_providers"] == CUTAWAY_PROVIDER_PIN
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
