"""Coverage for the reel_pop caption preset, the 9:16 safe zone, and the
run-scoped staging that lets five reels burn captions in one sitting.

What this locks down:

1. The default look is opt-out-proof: with no ``preset`` the props file and the
   render argv are exactly what they were, so the twelve shipped pipelines that
   call this tool render unchanged.
2. ``videoSrc`` never carries a ``public/`` prefix. ``staticFile()`` *throws* on
   one (``remotion/dist/cjs/static-file.js:92``), so the prefix the tool used to
   emit killed the render before a frame was drawn.
3. Staged media is scoped to a run when asked, and that scoped dir is removed
   even when the render raises — a batch whose masters are all named the same
   otherwise overwrites itself mid-flight.
4. Per-word ASR confidence survives transcriber -> burn. Reel speech is
   transcribed off a mixed music track (no stem separation exists in this repo),
   so a caption stage has to be able to gate on it.

The .tsx assertions follow the source-text idiom already used by
tests/contracts/test_theme_text_contrast_contract.py — there is no JS test
runner in this repo.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.base_tool import ToolResult

from tools.video.remotion_caption_burn import RemotionCaptionBurn

COMPOSER = Path(__file__).resolve().parents[2] / "remotion-composer" / "src"


def _read(name: str) -> str:
    return (COMPOSER / name).read_text(encoding="utf-8")


# --- per-word confidence ---------------------------------------------------

def _segments(*probabilities: float) -> list[dict]:
    return [
        {
            "start": 0.0,
            "end": float(len(probabilities)),
            "text": "no excuses today",
            "words": [
                {"word": f"w{i}", "start": float(i), "end": float(i + 1), "probability": p}
                for i, p in enumerate(probabilities)
            ],
        }
    ]


def test_word_confidence_survives_segment_conversion():
    captions = RemotionCaptionBurn()._segments_to_word_captions(_segments(0.91, 0.42))

    assert [c["confidence"] for c in captions] == [0.91, 0.42]


def test_word_confidence_survives_a_correction():
    """A corrected word keeps the confidence the model reported for it."""
    segments = _segments(0.77)
    segments[0]["words"][0]["word"] = "cloud"
    captions = RemotionCaptionBurn()._segments_to_word_captions(
        segments, {"cloud": "Claude"}
    )

    assert captions[0] == {
        "word": "Claude",
        "startMs": 0,
        "endMs": 1000,
        "confidence": 0.77,
    }


def test_confidence_stats_report_the_mean_and_the_words_to_gate_on():
    stats = RemotionCaptionBurn._confidence_stats(
        RemotionCaptionBurn()._segments_to_word_captions(_segments(0.9, 0.8, 0.4, 0.5))
    )

    assert stats["word_confidence"] == {
        "mean": 0.65,
        "min": 0.4,
        "counted": 4,
        "low_confidence_words": 2,
    }


def test_confidence_stats_are_none_when_the_source_carried_none():
    """SRT input has no per-word probability — report absence, don't fake 1.0."""
    captions = [{"word": "go", "startMs": 0, "endMs": 500}]

    assert RemotionCaptionBurn._confidence_stats(captions) == {"word_confidence": None}


# --- look / staging input validation ---------------------------------------

@pytest.mark.parametrize(
    ("label", "inputs", "expect"),
    [
        ("unknown_preset", {"preset": "tiktok"}, "Unknown preset"),
        ("fps_zero", {"fps": 0}, "positive integer"),
        ("fps_float", {"fps": 29.97}, "positive integer"),
        ("fps_bool", {"fps": True}, "positive integer"),
        ("run_id_traversal", {"run_id": "../../etc"}, "run_id must match"),
        ("run_id_separator", {"run_id": "reel/1"}, "run_id must match"),
        ("run_id_empty", {"run_id": ""}, "run_id must match"),
        ("safe_zone_scalar", {"safe_zone": 0.18}, "must be an object"),
        ("safe_zone_typo", {"safe_zone": {"bottom": 0.1, "botom": 0.2}}, "Unknown safe_zone keys"),
        ("safe_zone_no_bottom", {"safe_zone": {"sides": 0.1}}, "requires 'bottom'"),
        ("safe_zone_half", {"safe_zone": {"bottom": 0.5}}, "fraction in [0, 0.5)"),
        ("safe_zone_negative", {"safe_zone": {"bottom": -0.1}}, "fraction in [0, 0.5)"),
        ("safe_zone_pixels", {"safe_zone": {"bottom": 80}}, "fraction in [0, 0.5)"),
    ],
)
def test_bad_look_inputs_are_rejected(label, inputs, expect):
    error = RemotionCaptionBurn._validate_look(inputs)

    assert error is not None, f"{label} was accepted"
    assert expect in error


@pytest.mark.parametrize(
    "inputs",
    [
        {},
        {"preset": "default"},
        {"preset": "reel_pop", "fps": 30, "run_id": "reel-03_v2", "safe_zone": {"bottom": 0.18, "sides": 0.08}},
        {"safe_zone": {"bottom": 0.0}},
    ],
)
def test_good_look_inputs_pass(inputs):
    assert RemotionCaptionBurn._validate_look(inputs) is None


def test_execute_refuses_a_bad_preset_before_touching_the_input(tmp_path):
    result = RemotionCaptionBurn().execute({
        "input_path": str(tmp_path / "missing.mp4"),
        "output_path": str(tmp_path / "out.mp4"),
        "preset": "tiktok",
    })

    assert not result.success
    assert "Unknown preset" in result.error


# --- Remotion staging ------------------------------------------------------

@pytest.fixture
def render(tmp_path, monkeypatch):
    """Drive _render_remotion with ffprobe and the Remotion CLI stubbed out.

    Returns (tool, root, calls); the fake render writes the output file so the
    success path is reached.
    """
    root = tmp_path / "remotion-composer"
    (root / "node_modules").mkdir(parents=True)
    (root / "package.json").write_text("{}", encoding="utf-8")

    tool = RemotionCaptionBurn()
    monkeypatch.setattr(tool, "_find_remotion_root", lambda: root)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[0] == "ffprobe":
            stdout = "10.0\n" if "format=duration" in cmd else "1080x1920\n"
            return subprocess.CompletedProcess(cmd, 0, stdout, "")
        for arg in cmd:
            if arg.startswith("--output="):
                out = Path(arg.split("=", 1)[1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tool, "run_command", fake_run)
    return tool, root, calls


def _props(root: Path) -> dict:
    files = list((root / "public" / "demo-props").glob("caption-burn-*.json"))
    assert len(files) == 1, files
    return json.loads(files[0].read_text(encoding="utf-8"))


def _argv(calls: list[list[str]]) -> list[str]:
    return next(c for c in calls if "render" in c)


def _burn(tool, tmp_path, **kwargs):
    src = tmp_path / "master.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    return tool._render_remotion(
        str(src),
        str(tmp_path / "renders" / "captioned.mp4"),
        [{"word": "GO", "startMs": 0, "endMs": 400, "confidence": 0.9}],
        4, 52, "#22D3EE",
        **kwargs,
    )


def test_video_src_has_no_public_prefix(render, tmp_path):
    """staticFile() raises TypeError on a "public/" prefix — the render dies."""
    tool, root, _ = render
    _burn(tool, tmp_path)

    assert _props(root)["videoSrc"] == "talking-head/master.mp4"


def test_default_preset_stages_and_renders_exactly_as_before(render, tmp_path):
    tool, root, calls = render
    result = _burn(tool, tmp_path)

    props = _props(root)
    assert "captionPreset" not in props
    assert "captionSafeZone" not in props
    assert (root / "public" / "talking-head" / "master.mp4").is_file()
    assert "--fps=30" in _argv(calls)
    assert result.data["preset"] == "default"


def test_reel_pop_and_safe_zone_reach_the_props(render, tmp_path):
    tool, root, _ = render
    _burn(
        tool, tmp_path,
        preset="reel_pop",
        safe_zone={"bottom": 0.18, "sides": 0.08},
    )

    props = _props(root)
    assert props["captionPreset"] == "reel_pop"
    assert props["captionSafeZone"] == {"bottom": 0.18, "sides": 0.08}


def test_fps_reaches_the_render_and_the_frame_count(render, tmp_path):
    tool, root, calls = render
    result = _burn(tool, tmp_path, fps=60)

    argv = _argv(calls)
    assert "--fps=60" in argv
    # 10s at 60fps, zero-indexed.
    assert "--frames=0-599" in argv
    assert result.data["total_frames"] == 600


def test_run_id_scopes_staging_and_cleans_it_up(render, tmp_path):
    tool, root, _ = render
    _burn(tool, tmp_path, run_id="reel-03")

    assert _props(root)["videoSrc"] == "talking-head/reel-03/master.mp4"
    # Scoped media is transient; the props file is kept for diagnosis.
    assert not (root / "public" / "talking-head" / "reel-03").exists()
    assert (root / "public" / "demo-props" / "caption-burn-reel-03-master.json").is_file()


def test_two_runs_do_not_share_a_staging_dir(render, tmp_path, monkeypatch):
    """The whole point: five reels named master.mp4 must not collide."""
    tool, root, _ = render
    staged: list[set[str]] = []
    real_run = tool.run_command

    def spy(cmd, **kwargs):
        if "render" in cmd:
            staged.append({
                str(p.relative_to(root / "public"))
                for p in (root / "public").rglob("master.mp4")
            })
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(tool, "run_command", spy)
    _burn(tool, tmp_path, run_id="reel-01")
    _burn(tool, tmp_path, run_id="reel-02")

    assert staged == [
        {"talking-head/reel-01/master.mp4"},
        {"talking-head/reel-02/master.mp4"},
    ]


def test_failed_render_still_removes_run_scoped_media(render, tmp_path, monkeypatch):
    tool, root, _ = render

    def boom(cmd, **kwargs):
        if "render" in cmd:
            raise RuntimeError("remotion exploded")
        return subprocess.CompletedProcess(
            cmd, 0, "10.0\n" if "format=duration" in cmd else "1080x1920\n", ""
        )

    monkeypatch.setattr(tool, "run_command", boom)
    with pytest.raises(RuntimeError):
        _burn(tool, tmp_path, run_id="reel-04")

    assert not (root / "public" / "talking-head" / "reel-04").exists()


# --- CaptionOverlay.tsx / TalkingHead.tsx wiring ---------------------------

def _preset_block(name: str) -> str:
    source = _read("components/CaptionOverlay.tsx")
    block = source[source.index(f"  {name}: {{") :]
    return block[: block.index("\n  }")]


def test_reel_pop_preset_defines_pop_stroke_uppercase_and_a_safe_zone():
    block = _preset_block("reel_pop")

    assert "popScale: 0." in block
    assert "strokeRatio: 0." in block
    assert "uppercase: true" in block
    assert "safeZone: { bottom: 0." in block


def test_default_preset_carries_none_of_the_new_style():
    """Opt-in means the default branch emits nothing new at all."""
    block = _preset_block("default")
    assert "popScale: 0," in block
    assert "strokeRatio: 0," in block
    assert "uppercase: false" in block
    assert "wordGapRatio: 0," in block
    assert "safeZone: null" in block

    # Every new style is spread in conditionally: an unconditional scale(1)
    # still promotes the span to its own layer and shifts rasterization, and a
    # 0px margin would change nothing but is not worth emitting either.
    source = _read("components/CaptionOverlay.tsx")
    assert "...(style.popScale" in source
    assert "...(style.strokeRatio" in source
    assert "...(style.uppercase" in source
    assert "...(style.wordGapRatio" in source


def test_caption_position_is_a_safe_zone_fraction_not_a_pixel_offset():
    source = _read("components/CaptionOverlay.tsx")

    assert "Math.round(height * safeZone.bottom)" in source
    # The shipped 80px offset survives only as the no-safe-zone fallback.
    assert "const LEGACY_PADDING_BOTTOM = 80;" in source
    assert "paddingBottom: 80" not in source


def test_pop_is_seeded_at_each_words_own_start():
    """A page-relative pop would only ever fire on the first word of a page."""
    source = _read("components/CaptionOverlay.tsx")

    assert "frame - Math.round(((w.startMs - page.startMs) / 1000) * fps)" in source
    assert "const pop = style.popScale ? popPulse(wordFrame) : 0;" in source


def _eval_pop_pulse(frames: list[int]) -> list[float]:
    """Run the REAL popPulse from the TSX, in node, over the given frames.

    Asserting on source strings cannot police this: substituting
    POP_DURATION_FRAMES = 600 leaves every literal in place and a
    string-matching test green, while the pop never returns to rest.
    """
    source = _read("components/CaptionOverlay.tsx")
    start = source.index("const POP_DURATION_FRAMES")
    end = source.index("type CaptionOverlayProps")
    # The impulse is self-contained arithmetic — no Remotion imports needed.
    snippet = source[start:end].replace(": number", "").replace("function popPulse(wordFrame)", "function popPulse(wordFrame)")
    script = (
        snippet
        + "\nconsole.log(JSON.stringify(["
        + ",".join(f"popPulse({f})" for f in frames)
        + "]));"
    )
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_pop_returns_to_rest():
    """The impulse must start at rest, peak, and come back to rest.

    A pop that *stays* enlarged for the word's whole active span grows the
    word about its centre and closes the gap to its neighbour, so
    "-REVIEWED PAPERS" reads as one word for ~300ms.

    This runs the real function rather than grepping for it: with
    POP_DURATION_FRAMES raised to 600 every source literal is unchanged and a
    string-matching assertion stays green while the behaviour is broken.
    """
    frames = [0, 1, 2, 3, 4, 5, 6, 12, 40]
    values = _eval_pop_pulse(frames)
    by_frame = dict(zip(frames, values))

    assert by_frame[0] == pytest.approx(0.0, abs=1e-9), "must start at rest"
    assert by_frame[5] == pytest.approx(0.0, abs=1e-9), "must be back at rest by frame 5"
    assert by_frame[6] == pytest.approx(0.0, abs=1e-9), "and stay there"
    assert by_frame[40] == pytest.approx(0.0, abs=1e-9), "no drift late in a long word"
    assert max(values) > 0.9, "must actually peak"
    assert all(0.0 <= v <= 1.0 for v in values), "impulse stays bounded"
    # Transient, not a plateau: the peak is a single-frame neighbourhood.
    assert by_frame[2] > by_frame[4], "must be falling by the tail of the pulse"


def test_reel_pop_puts_a_real_gap_between_words():
    """wordSeparator alone does not survive.

    Each word is an inline-block with white-space: nowrap, and CSS drops a
    trailing space at the end of such a box — verified in a real 1080x1920
    render, which produced "TWOPEER-REVIEWEDPAPERS". The default preset keeps
    that behavior deliberately (byte-identical output for existing callers);
    the new preset opts into a margin instead.
    """
    assert "wordGapRatio: 0.4," in _preset_block("reel_pop")

    source = _read("components/CaptionOverlay.tsx")
    assert (
        "...(style.wordGapRatio && wordSeparator && i < page.words.length - 1"
        in source
    )
    assert "{ marginRight: fontSize * style.wordGapRatio }" in source


def test_talking_head_passes_the_preset_and_safe_zone_through():
    source = _read("TalkingHead.tsx")

    call = source[source.index("<CaptionOverlay") :]
    call = call[: call.index("/>")]

    assert "preset={captionPreset}" in call
    assert "{...(captionSafeZone ? { safeZone: captionSafeZone } : {})}" in call
    # reel_pop supplies its own stroke, so the pill is dropped unless asked for.
    assert "backgroundColor={resolvedCaptionBackground}" in call
    assert 'captionPreset === "reel_pop" ? "transparent" : "rgba(0, 0, 0, 0.65)"' in source


def test_word_separator_is_left_alone():
    """Guard against a well-meaning "words are jammed together" fix.

    They are not: wordSeparator is a typed prop defaulting to a single space,
    applied per word. The CJK caption work already handled this.
    """
    source = _read("components/CaptionOverlay.tsx")

    assert 'wordSeparator = " ",' in source
    assert "{w.word}{i < page.words.length - 1 ? wordSeparator : \"\"}" in source


def test_the_ffmpeg_fallback_admits_what_it_dropped(tmp_path, monkeypatch):
    """A downgrade that reports success with no signal is a silent lie.

    The fallback burns static SRT and cannot express the per-word pop, the
    safe zone, or a custom fps. A caller that asked for reel_pop and got plain
    subtitles has to be able to tell the difference.
    """
    tool = RemotionCaptionBurn()
    out = tmp_path / "out.mp4"

    def fake_ffmpeg(input_path, output_path, captions):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return ToolResult(
            success=True,
            data={
                "method": "ffmpeg_fallback",
                "output": str(output_path),
                "caption_count": len(captions),
                "note": "Used FFmpeg fallback. Install Remotion for animated captions.",
            },
            artifacts=[str(output_path)],
        )

    monkeypatch.setattr(tool, "_render_ffmpeg", fake_ffmpeg)
    src = tmp_path / "master.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    result = tool.execute(
        {
            "input_path": str(src),
            "output_path": str(out),
            "segments": [
                {
                    "text": "PULL",
                    "start": 0.0,
                    "end": 0.4,
                    "words": [
                        {"word": "PULL", "start": 0.0, "end": 0.4, "probability": 0.9}
                    ],
                }
            ],
            "preset": "reel_pop",
            "safe_zone": {"bottom": 0.18, "sides": 0.08},
            "fps": 60,
            "force_ffmpeg": True,
        }
    )

    assert result.success
    assert result.data["degraded"] is True
    assert result.data["requested_preset"] == "reel_pop"
    assert result.data["preset"] == "default"
    assert set(result.data["unhonoured_inputs"]) == {"preset", "safe_zone", "fps"}
    assert "Ignored" in result.data["note"]
