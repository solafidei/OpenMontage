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
import re
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
        ("unknown_animation", {"animation_preset": "slide"}, "Unknown animation_preset"),
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
        {"animation_preset": "none"},
        # The combination the feature exists for: reel_pop's type treatment,
        # holding still.
        {"preset": "reel_pop", "animation_preset": "none"},
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


def test_execute_refuses_a_bad_animation_before_touching_the_input(tmp_path):
    result = RemotionCaptionBurn().execute({
        "input_path": str(tmp_path / "missing.mp4"),
        "output_path": str(tmp_path / "out.mp4"),
        "animation_preset": "slide",
    })

    assert not result.success
    assert "Unknown animation_preset" in result.error


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


def _burn(tool, tmp_path, src: Path | None = None, **kwargs):
    src = src if src is not None else tmp_path / "master.mp4"
    src.parent.mkdir(parents=True, exist_ok=True)
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

    key = RemotionCaptionBurn._source_key(str(tmp_path / "master.mp4"))
    assert _props(root)["videoSrc"] == f"talking-head/{key}/master.mp4"


def test_default_preset_stages_and_renders_exactly_as_before(render, tmp_path, monkeypatch):
    tool, root, calls = render
    key = RemotionCaptionBurn._source_key(str(tmp_path / "master.mp4"))
    staged = root / "public" / "talking-head" / key / "master.mp4"
    real_run = tool.run_command
    present: list[bool] = []

    def spy(cmd, **kwargs):
        if "render" in cmd:
            present.append(staged.is_file())
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(tool, "run_command", spy)
    result = _burn(tool, tmp_path)

    props = _props(root)
    assert "captionPreset" not in props
    assert "captionSafeZone" not in props
    # An absent animation must leave the props JSON byte-identical: talking-head
    # and avatar-spokesperson render through this same composition.
    assert "captionAnimation" not in props
    # Staged for the render, then swept — asserted at render time, because
    # after the call the dir is gone (see the un-scoped footprint test).
    assert present == [True]
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

    key = RemotionCaptionBurn._source_key(str(tmp_path / "master.mp4"))
    assert _props(root)["videoSrc"] == f"talking-head/reel-03/{key}/master.mp4"
    # Scoped media is transient; the props file is kept for diagnosis.
    assert not (root / "public" / "talking-head" / "reel-03" / key).exists()
    assert (root / "public" / "demo-props" / f"caption-burn-reel-03-{key}.json").is_file()


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

    key = RemotionCaptionBurn._source_key(str(tmp_path / "master.mp4"))
    assert staged == [
        {f"talking-head/reel-01/{key}/master.mp4"},
        {f"talking-head/reel-02/{key}/master.mp4"},
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


def _staged(root: Path) -> list[str]:
    base = root / "public" / "talking-head"
    return sorted(str(p.relative_to(base)) for p in base.rglob("*")) if base.exists() else []


def test_unscoped_staging_does_not_accumulate_a_dir_per_source(render, tmp_path):
    """Without a run_id the footprint stays flat as distinct sources pile up.

    The path digest in ``_source_key`` gave every distinct master its own
    staging dir, and cleanup was gated on ``run_id``, so a pipeline burning
    captions on N un-scoped files left N full copies of them under
    public/talking-head/ forever. Measured on the gated code with the render
    stubbed out: 6 sources -> 6 dirs, 6 more -> 12, and a rerun of the same 6
    added none (they overwrite their own dir, they do not free it).
    """
    tool, root, _ = render

    for i in range(3):
        _burn(tool, tmp_path, src=tmp_path / f"reel{i}" / "master.mp4")
    assert _staged(root) == []

    for i in range(3, 6):
        _burn(tool, tmp_path, src=tmp_path / f"reel{i}" / "master.mp4")
    assert _staged(root) == []


def test_failed_render_still_removes_unscoped_media(render, tmp_path, monkeypatch):
    """The sweep is in ``finally``: a raising render must not strand a copy."""
    tool, root, _ = render

    def boom(cmd, **kwargs):
        if "render" in cmd:
            raise RuntimeError("remotion exploded")
        return subprocess.CompletedProcess(
            cmd, 0, "10.0\n" if "format=duration" in cmd else "1080x1920\n", ""
        )

    monkeypatch.setattr(tool, "run_command", boom)
    with pytest.raises(RuntimeError):
        _burn(tool, tmp_path)

    assert _staged(root) == []


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
    assert "{...(captionAnimation ? { animation: captionAnimation } : {})}" in call
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


# --- issue #52 edge cases --------------------------------------------------

def test_run_id_with_a_trailing_newline_is_rejected():
    """``$`` also matches before a trailing newline.

    "reel\n" therefore passed the whitelist and went on to become a real
    directory under remotion-composer/public/ with a newline in its name.
    """
    error = RemotionCaptionBurn._validate_look({"run_id": "reel\n"})

    assert error is not None, "run_id 'reel\\n' was accepted"
    assert "run_id must match" in error


def test_same_stem_in_different_folders_gets_a_different_staging_dir(render, tmp_path):
    """a/clip.mp4 and b/clip.mp4 in one run must not stage over each other.

    Keyed on the stem alone both copy to public/<run>/clip.mp4 and write the
    same props file, so the second burn wins and one reel renders the other's
    master.
    """
    tool, root, _ = render
    _burn(tool, tmp_path, src=tmp_path / "a" / "clip.mp4", run_id="reel-07")
    first = json.loads(
        sorted((root / "public" / "demo-props").glob("*.json"))[0].read_text("utf-8")
    )["videoSrc"]
    _burn(tool, tmp_path, src=tmp_path / "b" / "clip.mp4", run_id="reel-07")

    props = sorted(
        (root / "public" / "demo-props").glob("caption-burn-reel-07-clip*.json")
    )
    assert len(props) == 2, [p.name for p in props]
    sources = {json.loads(p.read_text("utf-8"))["videoSrc"] for p in props}
    assert len(sources) == 2, sources
    assert first in sources, "the first burn's props were overwritten"


def test_the_staging_key_is_reproducible_for_the_same_input(tmp_path):
    """No clock, no randomness — a re-run must land in the same directory."""
    src = str(tmp_path / "a" / "clip.mp4")

    assert RemotionCaptionBurn._source_key(src) == RemotionCaptionBurn._source_key(src)
    assert RemotionCaptionBurn._source_key(src).startswith("clip-")


def _resolve_caption_background(*cases: tuple[str, str]) -> list:
    """Run the REAL background resolution from TalkingHead.tsx, in node.

    Each case is (background as a JS literal, preset). Source-string
    assertions cannot police this one: `??` and an `=== undefined` check look
    equally plausible in a diff, and only running them tells null from
    undefined.
    """
    source = _read("TalkingHead.tsx")
    start = source.index("  const presetCaptionBackground")
    end = source.index("  return (", start)
    script = (
        "const resolve = (captionBackgroundColor, captionPreset) => {\n"
        + source[start:end]
        + "\n  return resolvedCaptionBackground;\n};\n"
        "console.log(JSON.stringify(["
        + ",".join(f'resolve({bg}, "{preset}")' for bg, preset in cases)
        + "]));"
    )
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_an_explicit_null_caption_background_means_no_pill():
    """null is legal in the props JSON and means "no pill".

    `??` could not tell it from an absent key and rendered the default pill,
    so a caller that had explicitly turned the pill off got one anyway.
    """
    absent, absent_pop, explicit_null, explicit_color = _resolve_caption_background(
        ("undefined", "default"),
        ("undefined", "reel_pop"),
        ("null", "default"),
        ('"#FF0000"', "default"),
    )

    # Unchanged for every existing caller: omitting the prop keeps the pill.
    assert absent == "rgba(0, 0, 0, 0.65)"
    assert absent_pop == "transparent"
    # The fix: an explicit null is not the same request as an absent key.
    assert explicit_null == "transparent", "null must mean no pill"
    assert explicit_color == "#FF0000"


# --- motion, separately from typography ------------------------------------

def test_an_explicit_animation_reaches_the_props(render, tmp_path):
    """The combination no preset value can express: reel_pop type, held still."""
    tool, root, _ = render
    _burn(tool, tmp_path, preset="reel_pop", animation_preset="none")

    props = _props(root)
    assert props["captionPreset"] == "reel_pop"
    assert props["captionAnimation"] == "none"


def test_a_preset_without_an_animation_emits_no_animation_key(render, tmp_path):
    """reel_pop keeps rendering its pop, resolved in TypeScript, not in Python."""
    tool, root, _ = render
    _burn(tool, tmp_path, preset="reel_pop")

    props = _props(root)
    assert props["captionPreset"] == "reel_pop"
    assert "captionAnimation" not in props


def _fallback_burn(tmp_path, monkeypatch, **inputs):
    """execute() over the shipped fake-fallback idiom.

    The real _render_ffmpeg shells out to ffmpeg over a stub file, so the
    degradation block — which is gated only on success and a non-None data —
    is exercised through a fake, exactly as the test above does it.
    """
    tool = RemotionCaptionBurn()

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
    return tool.execute({
        "input_path": str(src),
        "output_path": str(tmp_path / "out.mp4"),
        "segments": [{
            "text": "PULL", "start": 0.0, "end": 0.4,
            "words": [{"word": "PULL", "start": 0.0, "end": 0.4, "probability": 0.9}],
        }],
        "force_ffmpeg": True,
        **inputs,
    })


def test_the_fallback_reports_motion_as_none_and_says_it_dropped_it(tmp_path, monkeypatch):
    """A static SRT burn animates nothing, whatever was asked for."""
    result = _fallback_burn(tmp_path, monkeypatch, animation_preset="pop")

    assert result.data["animation_preset"] == "none"
    assert "animation_preset" in result.data["unhonoured_inputs"]
    assert result.data["degraded"] is True


def test_the_fallback_does_not_flag_an_animation_it_honoured(tmp_path, monkeypatch):
    """Asked for none, got none — nothing was lost. degraded still stands: the
    method downgrade (static SRT, no per-word highlight) is real regardless."""
    result = _fallback_burn(tmp_path, monkeypatch, animation_preset="none")

    assert result.data["animation_preset"] == "none"
    assert "animation_preset" not in result.data["unhonoured_inputs"]
    assert result.data["degraded"] is True


def test_an_all_default_fallback_admits_dropping_nothing(tmp_path, monkeypatch):
    """The guard that stopped `fps` firing on every single fallback render.

    Asserted on the note's "Ignored" clause rather than the absence of a `note`
    key: the fallback sets its own note, and `if dropped` only overwrites it.
    """
    result = _fallback_burn(tmp_path, monkeypatch)

    assert result.data["unhonoured_inputs"] == []
    assert result.data["degraded"] is True
    assert "Ignored" not in result.data["note"]


def test_the_remotion_path_echoes_only_what_it_was_asked_for(tmp_path, monkeypatch):
    """Python never derives motion from the preset — that table lives once, in
    TypeScript. Asked explicitly: echoed. Not asked: no key, no guess."""
    src = tmp_path / "master.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    segments = [{
        "text": "PULL", "start": 0.0, "end": 0.4,
        "words": [{"word": "PULL", "start": 0.0, "end": 0.4, "probability": 0.9}],
    }]

    def run(**extra):
        tool = RemotionCaptionBurn()
        monkeypatch.setattr(tool, "_remotion_available", lambda: True)
        monkeypatch.setattr(
            tool, "_render_remotion",
            lambda *a, **k: ToolResult(success=True, data={"method": "remotion"}),
        )
        return tool.execute({
            "input_path": str(src),
            "output_path": str(tmp_path / "out.mp4"),
            "segments": segments,
            **extra,
        })

    assert run(preset="reel_pop", animation_preset="none").data["animation_preset"] == "none"
    # reel_pop implies pop, and TypeScript is what knows that.
    assert "animation_preset" not in run(preset="reel_pop").data


def _caption_js() -> str:
    """The real motion table, resolver and composition from CaptionOverlay.tsx,
    with the TypeScript annotations stripped — the idiom the pop-pulse harness
    already uses. One copy, because two strippers drift."""
    source = _read("components/CaptionOverlay.tsx")

    def _slice(start_marker: str, end_marker: str) -> str:
        start = source.index(start_marker)
        return source[start : source.index(end_marker, start)]

    js = (
        _slice("const PRESETS", "// The shipped absolute offset")
        + _slice("const MOTIONS", "interface PresetStyle")
    )
    js = js.replace("export ", "")
    js = re.sub(r":\s*Record<[^>]+>", "", js)
    # Both function signatures, single- and multi-line.
    js = js.replace("(preset: string, animation?: string): MotionStyle", "(preset, animation)")
    js = re.sub(
        r"\(\s*preset: string,\s*animation\?: string,\s*safeZone\?: CaptionSafeZone,\s*\)"
        r"\s*:\s*\{[^}]*\}",
        "(preset, animation, safeZone)",
        js,
    )
    js = js.replace("  const presetKey: CaptionPreset =", "  const presetKey =")
    js = re.sub(r"\s+as CaptionPreset", "", js)
    js = re.sub(r"\s+as CaptionAnimation", "", js)
    js = js.replace("const style: PresetStyle = {", "const style = {")
    return js


def _eval_js(fn: str, cases) -> list:
    calls = ",".join(f"{fn}({', '.join(c)})" for c in cases)
    script = _caption_js() + f"\nconsole.log(JSON.stringify([{calls}]));"
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"{out.stderr}\n---SCRIPT---\n{script}"
    return json.loads(out.stdout)


def _resolve_motion(*cases) -> list:
    """Run the REAL resolveMotion from CaptionOverlay.tsx, in node.

    Pins the lookup table: an absent animation must resolve to exactly what each
    preset has always rendered. This is the ONLY copy of that table anywhere —
    Python deliberately holds none.
    """
    return _eval_js("resolveMotion", cases)


def _resolve_style(*cases) -> list:
    """Run the REAL composition — resolveCaptionStyle — in node.

    `_resolve_motion` only proves the table is right. Resolving motion correctly
    and then failing to APPLY it is a defect no table test can see: `popScale:
    base.popScale`, `animateEntrance={true}`, a dead `animation` argument and a
    dropped `Math.max` each left the entire suite green.
    """
    return _eval_js("resolveCaptionStyle", cases)


def test_an_absent_animation_renders_what_the_preset_always_rendered():
    """The byte-identity promise, executed rather than asserted about."""
    default_absent, pop_absent = _resolve_motion(
        ('"default"', "undefined"), ('"reel_pop"', "undefined")
    )

    # default has always been: page entrance, no per-word pop.
    assert default_absent == {"entrance": True, "popScale": 0, "minWordGapRatio": 0}
    # reel_pop has always been: entrance plus the 0.16 impulse.
    assert pop_absent == {"entrance": True, "popScale": 0.16, "minWordGapRatio": 0.4}


def test_an_unvalidated_preset_still_renders_rather_than_throwing():
    """A hand-written props JSON has no Python guard in front of it, and today
    `PRESETS[preset] ?? PRESETS.default` renders it. Resolving the preset key
    second would index the motion table with a bad string and throw."""
    (unknown,) = _resolve_motion(('"tiktok"', "undefined"))

    assert unknown == {"entrance": True, "popScale": 0, "minWordGapRatio": 0}


def test_reel_pop_can_be_asked_for_the_plain_entrance():
    """The fourth resolution case: reel_pop typography, fade motion."""
    (fade_on_pop,) = _resolve_motion(('"reel_pop"', '"fade"'))

    assert fade_on_pop == {"entrance": True, "popScale": 0, "minWordGapRatio": 0}


def test_none_turns_off_both_the_entrance_and_the_pop():
    (none_on_pop,) = _resolve_motion(('"reel_pop"', '"none"'))

    assert none_on_pop["entrance"] is False
    assert none_on_pop["popScale"] == 0


def test_motion_carries_a_word_gap_floor_typography_does_not_supply():
    """{default, pop} is newly reachable and has never rendered: a 0.16 pop
    against a 0 gap makes the growing word touch its neighbour at the peak."""
    (pop_on_default,) = _resolve_motion(('"default"', '"pop"'))

    assert pop_on_default["minWordGapRatio"] == 0.4


def test_the_page_entrance_is_omitted_rather_than_neutralised():
    """Writing opacity: 1, transform: translateY(0px) is not the same as writing
    neither: a bare transform still promotes the div to its own layer and shifts
    rasterization. Same reason the per-word transform is already conditional."""
    source = _read("components/CaptionOverlay.tsx")

    assert "...(animateEntrance" in source
    assert "opacity: entrance," in source
    # The identity values must not appear as an else branch.
    assert "transform: `translateY(0px)`" not in source


def test_both_render_paths_report_whether_they_degraded(tmp_path, monkeypatch):
    """`degraded` was written only on the fallback path, so a caller reading
    `burn.data["degraded"]` raised on every successful Remotion render. A gate
    cannot ask a question the good path refuses to answer."""
    src = tmp_path / "master.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    tool = RemotionCaptionBurn()
    monkeypatch.setattr(tool, "_remotion_available", lambda: True)
    monkeypatch.setattr(
        tool, "_render_remotion",
        lambda *a, **k: ToolResult(success=True, data={"method": "remotion"}),
    )

    result = tool.execute({
        "input_path": str(src),
        "output_path": str(tmp_path / "out.mp4"),
        "segments": [{
            "text": "PULL", "start": 0.0, "end": 0.4,
            "words": [{"word": "PULL", "start": 0.0, "end": 0.4, "probability": 0.9}],
        }],
    })

    assert result.data["degraded"] is False


def test_the_fallback_keeps_what_was_asked_for_alongside_what_rendered(tmp_path, monkeypatch):
    """The echo reports "none" because that is what a static SRT rendered. The
    request has to survive somewhere or the loss is unattributable."""
    result = _fallback_burn(tmp_path, monkeypatch, animation_preset="pop")

    assert result.data["animation_preset"] == "none"
    assert result.data["requested_animation_preset"] == "pop"


def test_the_resolved_motion_actually_reaches_the_style():
    """`popScale: base.popScale` left 62 renderer tests green while inverting
    the feature in both directions. This is the assertion that catches it."""
    pop_on_default, none_on_pop = _resolve_style(
        ('"default"', '"pop"'), ('"reel_pop"', '"none"')
    )

    # Motion asked for, typography that never carried it.
    assert pop_on_default["style"]["popScale"] == 0.16
    assert pop_on_default["style"]["uppercase"] is False, "typography must not follow motion"
    # The combination decision #12 says the feature exists for.
    assert none_on_pop["style"]["popScale"] == 0
    assert none_on_pop["style"]["uppercase"] is True, "motion must not disturb typography"
    assert none_on_pop["style"]["strokeRatio"] == 0.14


def test_the_entrance_flag_is_resolved_not_constant():
    """`animateEntrance={true}` passed the whole 2438-test suite."""
    none_on_pop, absent_on_pop, none_on_default = _resolve_style(
        ('"reel_pop"', '"none"'), ('"reel_pop"', "undefined"), ('"default"', '"none"')
    )

    assert none_on_pop["animateEntrance"] is False
    assert none_on_default["animateEntrance"] is False
    assert absent_on_pop["animateEntrance"] is True


def test_the_word_gap_floor_survives_into_the_composed_style():
    """The floor is the sole engineering justification for keeping motion
    additive, and dropping the Math.max left 1611 tests green."""
    pop_on_default, none_on_pop, absent_on_default = _resolve_style(
        ('"default"', '"pop"'), ('"reel_pop"', '"none"'), ('"default"', "undefined")
    )

    # Newly reachable, never rendered before: a 0.16 pop needs the gap.
    assert pop_on_default["style"]["wordGapRatio"] == 0.4
    # A Math.min typo would drop reel_pop's own typographic 0.4 to 0 here.
    assert none_on_pop["style"]["wordGapRatio"] == 0.4
    # And the floor must not invent a gap where neither side asked for one.
    assert absent_on_default["style"]["wordGapRatio"] == 0


def test_an_explicit_safe_zone_still_outranks_the_presets():
    """The composition took over safeZone resolution; it must not have changed."""
    (explicit,) = _resolve_style(('"default"', "undefined", '{bottom: 0.2}'))

    assert explicit["safeZone"] == {"bottom": 0.2}


def test_the_component_passes_the_resolved_values_rather_than_literals():
    """Catches the constant that the composition harness cannot see: the
    function can be correct and the component still ignore it."""
    source = _read("components/CaptionOverlay.tsx")

    assert "resolveCaptionStyle(preset, animation, safeZone)" in source
    assert "animateEntrance={animateEntrance}" in source
    assert "animateEntrance={true}" not in source
