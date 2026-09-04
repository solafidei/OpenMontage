"""Picture-plane polish: punch-in, speed ramp, flash, whip, and the batch look.

Covers reel-batch spec R6 / issue #42:
- the ramp is *continuous* — the setpts expression varies across the cut rather
  than being a constant factor, asserted both on the expression and on the frame
  timestamps ffmpeg actually emits
- the punch-in is eased and, critically, sits BEFORE the speed filter: zoompan
  re-times its own output, so a punch-in placed after setpts silently discards
  the ramp
- one `batch_look` setting stamps the same grade/grain/sharpen on every reel
- only `face_enhance.PRESETS` is reachable on an `operator_footage` cut
- filters splice into the PER-CUT encode, and a cut with no polish still builds
  exactly the filter chain `_compose` built before this module existed

Pure-string assertions run everywhere; the rendering ones follow
tests/tools/test_video_compose_vertical.py and skip without ffmpeg.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib import polish_filters as pf  # noqa: E402
from tools.enhancement.color_grade import PROFILES as GRADE_PROFILES  # noqa: E402
from tools.enhancement.face_enhance import PRESETS as FACE_PRESETS  # noqa: E402
from tools.video.video_compose import VideoCompose  # noqa: E402

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)

# The chain _compose has always built for a plain 1920x1080 pad-fit cut.
BASELINE_VF = (
    "scale=1920:1080:force_original_aspect_ratio=decrease,"
    "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30"
)

LOOK = {"grade": "cinematic_warm", "grain": 6, "sharpen": "sharpen_light"}


def _find(parts: list[str], needle: str) -> int:
    for i, part in enumerate(parts):
        if needle in part:
            return i
    raise AssertionError(f"{needle!r} not in {parts}")


def _eval_setpts(filter_string: str, seconds: float) -> float:
    """Evaluate the emitted setpts expression at input time `seconds`."""
    expr = filter_string[len("setpts="):].strip("'")
    return eval(expr, {"log": math.log, "TB": 1.0, "T": seconds})  # noqa: S307


def _eval_zoom(filter_string: str, frame: int) -> float:
    expr = re.search(r"zoompan=z='([^']+)'", filter_string).group(1)
    return eval(expr, {"pow": pow, "min": min, "on": frame})  # noqa: S307


# ---- backward compatibility ----

def test_a_cut_with_no_polish_adds_nothing(tmp_path):
    assert pf.cut_filters({"id": "c1"}, 3.0, 1920, 1080) == []


def test_constant_speed_still_emits_the_historical_setpts():
    """No polish block → byte-identical to what _compose built before."""
    assert pf.cut_filters({"speed": 2.0}, 3.0, 1920, 1080) == ["setpts=0.5*PTS"]


# ---- punch-in ----

def test_punch_in_is_eased_and_lands_on_the_target_zoom():
    f = pf.punch_in(2.0, 2.0, 1080, 1920)
    last = int(round(2.0 * 30)) - 1
    assert _eval_zoom(f, 0) == pytest.approx(1.0)
    assert _eval_zoom(f, last) == pytest.approx(2.0, abs=1e-3)
    # Curvature, not one sampled point. The old assertion — zoom(last//4) <
    # 1 + delta*0.25 — was satisfied by a purely LINEAR zoom, because
    # 14/59 = 0.2373 is already under 0.25, so it policed nothing. A smoothstep
    # lags the straight line through the whole first half and leads it through
    # the whole second half; a straight line sits on it everywhere and fails.
    line = [1.0 + (2.0 - 1.0) * n / last for n in range(last + 1)]
    curve = [_eval_zoom(f, n) for n in range(last + 1)]
    lag = [c - l for c, l in zip(curve, line)]
    assert all(d < 0 for d in lag[1:last // 2])
    assert all(d > 0 for d in lag[last // 2 + 1:last])
    # And by a margin no rounding could produce: the smoothstep is a tenth of
    # the whole push away from the line at its extremes.
    assert max(abs(d) for d in lag) > (2.0 - 1.0) * 0.09
    assert "s=1080x1920" in f


def test_punch_in_precedes_the_speed_filter():
    """zoompan re-times its output; after setpts it would erase the ramp."""
    cut = {"speed": 1.0, "polish": {"punch_in": 1.5, "speed_ramp": 2.0}}
    parts = pf.cut_filters(cut, 2.0, 1080, 1920)
    assert _find(parts, "zoompan") < _find(parts, "setpts")


def test_punch_in_outside_the_schema_range_is_refused():
    with pytest.raises(pf.PolishError):
        pf.punch_in(9.0, 2.0, 1080, 1920)
    with pytest.raises(pf.PolishError):
        pf.punch_in(0.5, 2.0, 1080, 1920)


# ---- speed ramp ----

def test_speed_ramp_is_continuous_not_a_constant_factor():
    f = pf.speed_ramp_setpts(1.0, 3.0, 2.0)
    assert not re.fullmatch(r"setpts='?[\d.]+\*PTS'?", f)
    # Instantaneous speed = dT/dPTS_out; it must rise from 1x to 3x across
    # the cut rather than sitting on one factor.
    step = 1e-4
    speeds = [
        step / (_eval_setpts(f, t + step) - _eval_setpts(f, t))
        for t in (0.0, 0.5, 1.0, 1.5, 2.0 - step)
    ]
    assert speeds == sorted(speeds)
    assert speeds[0] == pytest.approx(1.0, abs=0.01)
    assert speeds[-1] == pytest.approx(3.0, abs=0.01)


def test_ramp_average_speed_matches_the_curve_it_came_from():
    """atempo gets this, so the segment's audio must be exactly as long."""
    duration = 2.0
    f = pf.speed_ramp_setpts(1.0, 3.0, duration)
    assert pf.output_duration(duration, 1.0, 3.0) == pytest.approx(_eval_setpts(f, duration))


def test_speed_ramp_outside_the_schema_range_is_refused():
    with pytest.raises(pf.PolishError):
        pf.speed_ramp_setpts(1.0, 25.0, 2.0)


# ---- flash and whip ----

def test_flash_fades_the_tail_to_white_and_holds():
    f = pf.flash_out(3.0)
    assert f.startswith(f"fade=t=out:st={3.0 - pf.FLASH_SECONDS:.4f}")
    assert "color=white" in f
    # The ramp ends before the cut does, so the last frames are actually white.
    assert float(re.search(r"d=([\d.]+)", f).group(1)) < pf.FLASH_SECONDS


def test_whip_blurs_horizontally_and_builds_over_the_tail():
    f = pf.whip_out(3.0)
    stages = ["gblur=" + s for s in f.split("gblur=")[1:]]
    assert len(stages) == 2
    assert all("sigmaV=0" in s for s in stages)
    # Second stage is stronger and gates on later — the blur builds.
    assert float(re.search(r"gte\(t,([\d.]+)\)", stages[0]).group(1)) < float(
        re.search(r"gte\(t,([\d.]+)\)", stages[1]).group(1)
    )


def test_accent_is_anchored_in_output_time_after_a_ramp():
    """A 2x-ramped 2s cut is ~1.39s out; the flash must land at ITS end."""
    cut = {"speed": 1.0, "polish": {"speed_ramp": 2.0, "transition_out": "flash"}}
    parts = pf.cut_filters(cut, 2.0, 1080, 1920)
    st = float(re.search(r"st=([\d.]+)", parts[_find(parts, "fade=")]).group(1))
    assert st == pytest.approx(pf.output_duration(2.0, 1.0, 2.0) - pf.FLASH_SECONDS, abs=1e-3)


def test_unknown_accent_is_refused():
    with pytest.raises(pf.PolishError):
        pf.cut_filters({"polish": {"transition_out": "zoom_blur"}}, 2.0, 1080, 1920)


# ---- the batch-wide look ----

def test_look_is_reused_from_color_grade_and_face_enhance():
    parts = pf.look_filters(LOOK)
    assert parts[0] == GRADE_PROFILES["cinematic_warm"]["vf"]
    assert parts[1] == "noise=alls=6:allf=t+u"
    assert parts[2] == FACE_PRESETS["sharpen_light"]["vf"]


# The old test here called one pure function five times with the same look and
# compared the outputs — a tautology that holds for any pure function and
# involved no reels at all. The real claim is about a BATCH, so it is now made
# by composing several reels through the real path; see
# `test_one_setting_stamps_the_same_look_on_every_reel_of_a_batch` below with
# the other render-level tests.


def test_unknown_look_names_are_refused():
    with pytest.raises(pf.PolishError):
        pf.look_filters({"grade": "instagram_2016"})
    with pytest.raises(pf.PolishError):
        pf.look_filters({"sharpen": "cinematic_warm"})  # a grade, not a preset


# ---- identity: operator footage reaches face_enhance and nothing else ----

def test_operator_footage_accepts_a_face_enhance_grade():
    parts = pf.look_filters({"grade": "warm", "sharpen": "sharpen"}, "operator_footage")
    assert parts == [FACE_PRESETS["warm"]["vf"], FACE_PRESETS["sharpen"]["vf"]]


def test_operator_footage_refuses_a_color_grade_profile():
    with pytest.raises(pf.PolishError, match="identity-safe"):
        pf.look_filters({"grade": "cinematic_warm"}, "operator_footage")


def test_operator_footage_refuses_grain():
    with pytest.raises(pf.PolishError, match="grain"):
        pf.look_filters({"grain": 6}, "operator_footage")


def test_ai_generated_cuts_still_take_the_full_look():
    cut = {"provenance": "ai_generated"}
    assert pf.cut_filters(cut, 2.0, 1080, 1920, look=LOOK) == pf.look_filters(LOOK)


# ---- the splice point: the PER-CUT encode ----

def _clip(path: Path, w: int = 640, h: int = 360, d: int = 2, src: str = "testsrc2") -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"{src}=s={w}x{h}:d={d}:r=30",
         "-c:v", "libx264", "-crf", "28", "-pix_fmt", "yuv420p",
         "-g", "30", "-keyint_min", "30", str(path)],
        capture_output=True, check=True,
    )


def _compose(tmp_path, cuts, spine=None, **extra):
    """Run compose, returning (result, every ffmpeg command it issued).

    `spine` merges into the edit_decisions batch spine, which is where the
    shared look lives (spec §4.2); `**extra` goes to the tool inputs.
    """
    seen: list[list[str]] = []
    original = VideoCompose.run_command

    def recording(self, cmd, **kwargs):
        seen.append(list(cmd))
        return original(self, cmd, **kwargs)

    tool = VideoCompose()
    tool.run_command = recording.__get__(tool, VideoCompose)
    result = tool.execute({
        "operation": "compose",
        "edit_decisions": {
            "version": "1.0", "render_runtime": "ffmpeg", "cuts": cuts, **(spine or {})
        },
        "output_path": str(tmp_path / "out.mp4"),
        **extra,
    })
    return result, seen


def _segment_vf(seen: list[list[str]]) -> list[str]:
    return [cmd[cmd.index("-filter:v") + 1] for cmd in seen if "-filter:v" in cmd]


@requires_ffmpeg
def test_two_cut_timeline_carries_per_cut_filters(tmp_path):
    """One encode per cut — polish rides on the cut that asked for it."""
    src = tmp_path / "in.mp4"
    _clip(src)
    result, seen = _compose(tmp_path, [
        {"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 1,
         "polish": {"punch_in": 1.6, "transition_out": "flash"}},
        {"id": "c2", "source": str(src), "in_seconds": 1, "out_seconds": 2},
    ])
    assert result.success, result.error

    vfs = _segment_vf(seen)
    assert len(vfs) == 2
    assert "zoompan" in vfs[0] and "fade=t=out" in vfs[0]
    # The second cut asked for nothing and gets nothing — byte-identical to today.
    assert vfs[1] == BASELINE_VF


@requires_ffmpeg
def test_batch_look_reaches_every_cut(tmp_path):
    src = tmp_path / "in.mp4"
    _clip(src)
    result, seen = _compose(
        tmp_path,
        [{"id": f"c{n}", "source": str(src), "in_seconds": n, "out_seconds": n + 1}
         for n in range(2)],
        batch_look=LOOK,
    )
    assert result.success, result.error
    vfs = _segment_vf(seen)
    assert len(vfs) == 2
    assert vfs[0] == vfs[1] == BASELINE_VF + "," + ",".join(pf.look_filters(LOOK))


@requires_ffmpeg
def test_operator_footage_fails_the_batch_rather_than_grading_a_face(tmp_path):
    src = tmp_path / "in.mp4"
    _clip(src)
    result, _ = _compose(
        tmp_path,
        [{"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 1,
          "provenance": "operator_footage"}],
        batch_look=LOOK,
    )
    assert not result.success
    assert "identity-safe" in result.error


# ---- what ffmpeg actually renders ----

def _mean_luma(path: Path, from_end: float = 0.04) -> float:
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-sseof", f"-{from_end}", "-i", str(path),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
    )
    return sum(raw) / len(raw)


@requires_ffmpeg
def test_ramp_makes_the_frame_timestamps_vary(tmp_path):
    """The rendered curve, not just the string: frame gaps must shrink."""
    src = tmp_path / "in.mp4"
    _clip(src)
    graph = (
        f"movie={src.as_posix()},fps=30,settb=1/90000,"
        + pf.speed_ramp_setpts(1.0, 3.0, 2.0)
    )
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-f", "lavfi",
         "-i", graph, "-show_entries", "frame=pts_time", "-of", "csv=p=0"],
    ).decode()
    times = [float(x) for x in out.split() if "," not in x]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert len(gaps) > 30
    assert gaps == sorted(gaps, reverse=True)
    assert gaps[0] / gaps[-1] == pytest.approx(3.0, abs=0.4)


@requires_ffmpeg
def test_flash_blows_the_last_frame_out_to_white(tmp_path):
    src = tmp_path / "in.mp4"
    _clip(src)
    plain, _ = _compose(tmp_path / "a", [
        {"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 2}])
    flashed, _ = _compose(tmp_path / "b", [
        {"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 2,
         "polish": {"transition_out": "flash"}}])
    assert plain.success and flashed.success, flashed.error
    assert _mean_luma(tmp_path / "b" / "out.mp4") > 240
    assert _mean_luma(tmp_path / "a" / "out.mp4") < 200


@requires_ffmpeg
def test_punch_in_magnifies_the_frame(tmp_path):
    """A centred white box fills more of the frame once punched in."""
    src = tmp_path / "in.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=2:r=30",
         "-vf", "drawbox=x=(iw-80)/2:y=(ih-80)/2:w=80:h=80:color=white:t=fill",
         "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
         "-g", "30", "-keyint_min", "30", str(src)],
        capture_output=True, check=True,
    )
    plain, _ = _compose(tmp_path / "a", [
        {"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 2}])
    punched, _ = _compose(tmp_path / "b", [
        {"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 2,
         "polish": {"punch_in": 2.0}}])
    assert plain.success and punched.success, punched.error
    assert _mean_luma(tmp_path / "b" / "out.mp4") > _mean_luma(tmp_path / "a" / "out.mp4") * 2


# ---- the punch-in's scale headroom ----

def test_scale_headroom_is_one_without_a_punch_in():
    """No punch-in → the geometry stage is untouched and the cut is byte-identical."""
    assert pf.scale_headroom({"id": "c1"}) == 1.0
    assert pf.scale_headroom({"polish": {"transition_out": "flash"}}) == 1.0
    assert pf.scale_headroom({"polish": {"punch_in": 1.0}}) == 1.0


def test_scale_headroom_is_the_punch_in_and_is_capped():
    assert pf.scale_headroom({"polish": {"punch_in": 1.6}}) == pytest.approx(1.6)
    # PUNCH_IN_RANGE allows 4.0 — a 4320x7680 intermediate, 16x the output's
    # pixels — so the headroom stops where the cost stops paying.
    assert pf.scale_headroom({"polish": {"punch_in": 4.0}}) == pf.SCALE_HEADROOM_CAP
    assert pf.SCALE_HEADROOM_CAP < pf.PUNCH_IN_RANGE[1]


def test_scale_headroom_refuses_what_punch_in_refuses():
    with pytest.raises(pf.PolishError):
        pf.scale_headroom({"polish": {"punch_in": 0.5}})
    with pytest.raises(pf.PolishError):
        pf.scale_headroom({"polish": {"punch_in": "big"}})


def test_polish_that_is_not_a_mapping_is_a_polish_error():
    """The module invariant: everything it refuses, it refuses as PolishError.

    `(cut.get("polish") or {}).get("punch_in")` raised a bare AttributeError
    on a non-mapping block, which fails closed but tells the caller a crash
    rather than a diagnosis.
    """
    for bad in ("punch_in", ["punch_in"], 1.6):
        with pytest.raises(pf.PolishError, match="polish must be a mapping"):
            pf.scale_headroom({"id": "c1", "polish": bad})
        with pytest.raises(pf.PolishError, match="polish must be a mapping"):
            pf.cut_filters({"id": "c1", "polish": bad}, 2.0, 1080, 1920)


def test_headroom_never_builds_bigger_than_the_source_can_fill():
    """A source smaller than headroom x target has nothing left to recover.

    The docstring used to justify taking no ffprobe as the reason to apply the
    headroom blind; `_compose` already probes each source, so the ceiling is
    free. `cover` fills then crops, so the SMALLER ratio binds; `pad` fits then
    letterboxes, so the larger one does.
    """
    cut = {"polish": {"punch_in": 1.6}}
    target = (1080, 1920)

    # 640x1138 into 1080x1920 cannot even fill the output: headroom 1.0.
    assert pf.scale_headroom(cut, target=target, source=(640, 1138), fit="cover") == 1.0
    assert pf.scale_headroom(cut, target=target, source=(640, 1138), fit="pad") == 1.0
    # Exactly the headroom canvas → exactly the headroom.
    assert pf.scale_headroom(
        cut, target=target, source=(1728, 3072), fit="cover") == pytest.approx(1.6)
    # Plenty of source → the punch-in's own headroom, unchanged.
    assert pf.scale_headroom(
        cut, target=target, source=(2160, 3840), fit="cover") == pytest.approx(1.6)
    # Partway: 1512x2688 is 1.4x the output, so 1.4x is all it can fill.
    assert pf.scale_headroom(
        cut, target=target, source=(1512, 2688), fit="cover") == pytest.approx(1.4)
    # `pad` letterboxes, so one long edge is enough: 3840 wide covers 1.6x even
    # though the height alone would cap it at 1.125.
    assert pf.scale_headroom(
        cut, target=target, source=(3840, 2160), fit="pad") == pytest.approx(1.6)
    assert pf.scale_headroom(
        cut, target=target, source=(3840, 2160), fit="cover") == pytest.approx(1.125)
    # No source known → the old source-blind answer.
    assert pf.scale_headroom(cut, target=target) == pytest.approx(1.6)


@requires_ffmpeg
def test_a_source_too_small_for_the_headroom_pays_nothing_for_it(tmp_path):
    """End to end: the geometry canvas of an under-sized source stays at target.

    Source-blind, this cut built a 1728x3072 intermediate out of a 640x1138
    clip — interpolation billed at 2.6x the output's area. Measured through
    `_compose` (interleaved, paired, n=9, medians) that cost 0.636s -> 0.748s,
    1.18x, for Laplacian variance 30.8 -> 33.6 on pixels the source never had.
    """
    src = tmp_path / "in.mp4"
    _clip(src, 640, 1138)
    result, seen = _compose(
        tmp_path,
        [{"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 1,
          "polish": {"punch_in": 1.6}}],
        spine={"metadata": {"compose_target":
                            {"width": 1080, "height": 1920, "fit": "cover"}}},
    )
    assert result.success, result.error
    vf = _segment_vf(seen)[0]
    assert "scale=1080:1920" in vf and "crop=1080:1920" in vf
    assert "1728" not in vf
    # The punch-in itself is untouched — only the canvas it crops from moved.
    assert "zoompan" in vf and "s=1080x1920" in vf


@requires_ffmpeg
def test_a_rotated_source_is_measured_by_its_display_size(tmp_path):
    """A phone clip's coded 2160x3840 arrives at the filter graph rotated.

    Capping on the coded size would read this portrait source as landscape and
    cut the headroom to 1.125 on a clip that can fill the whole 1.6x.
    """
    src = tmp_path / "in.mp4"
    _clip(src, 3840, 2160, d=1)
    rotated = tmp_path / "rot.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-display_rotation", "-90", "-i", str(src),
         "-c", "copy", str(rotated)],
        capture_output=True, check=True,
    )
    assert VideoCompose._probe_source(rotated)[1] == (2160, 3840)

    result, seen = _compose(
        tmp_path,
        [{"id": "c1", "source": str(rotated), "in_seconds": 0, "out_seconds": 1,
          "polish": {"punch_in": 1.6}}],
        spine={"metadata": {"compose_target":
                            {"width": 1080, "height": 1920, "fit": "cover"}}},
    )
    assert result.success, result.error
    assert "scale=1728:3072" in _segment_vf(seen)[0]


@requires_ffmpeg
@pytest.mark.parametrize("fit", ["pad", "cover"])
def test_geom_scales_to_the_headroom_so_the_punch_in_crops_real_pixels(tmp_path, fit):
    """The crop must come from a 1728-line frame, not from the 1080-line output.

    zoompan blows a region of its INPUT back up to the output size. Geom scaled
    to 1080x1920 first, the detail the crop wanted was already gone.

    The source is 1728x3072 — exactly the headroom canvas — because the
    headroom is now capped by what the source can fill. On the 1280x720 clip
    this test used to build, the honest answer at 1080x1920 is headroom 1.0,
    and asserting 1728 there was asserting a canvas nothing could fill.
    """
    src = tmp_path / "in.mp4"
    _clip(src, 1728, 3072)
    result, seen = _compose(
        tmp_path,
        [{"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 1,
          "polish": {"punch_in": 1.6}},
         {"id": "c2", "source": str(src), "in_seconds": 0, "out_seconds": 1}],
        spine={"metadata": {"compose_target": {"width": 1080, "height": 1920, "fit": fit}}},
    )
    assert result.success, result.error
    punched, plain = _segment_vf(seen)

    # 1080x1920 * 1.6 = 1728x3072, on both the scale and the crop/pad stage.
    assert "scale=1728:3072" in punched
    assert ("crop=1728:3072" if fit == "cover" else "pad=1728:3072") in punched
    # ...and zoompan still lands on the output size, so nothing downstream moves.
    assert "s=1080x1920" in punched
    # The cut that asked for no punch-in is untouched.
    assert "scale=1080:1920" in plain and "1728" not in plain


@requires_ffmpeg
def test_headroom_dimensions_are_rounded_to_even(tmp_path):
    """libx264 + yuv420p refuses an odd width or height outright."""
    src = tmp_path / "in.mp4"
    # 2560x1440 into the 1920x1080 default: big enough to fill 1.115x headroom,
    # which is what makes the rounding question reachable at all.
    _clip(src, 2560, 1440)
    # 1920 * 1.115 = 2140.8 and 1080 * 1.115 = 1204.2 — the width rounds to an
    # odd 2141 before it is evened off.
    result, seen = _compose(tmp_path, [
        {"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 1,
         "polish": {"punch_in": 1.115}}])
    assert result.success, result.error
    w, h = (int(v) for v in re.search(r"scale=(\d+):(\d+):", _segment_vf(seen)[0]).groups())
    assert w % 2 == 0 and h % 2 == 0
    assert (w, h) == (2140, 1204)


@requires_ffmpeg
def test_headroom_actually_recovers_high_frequency_detail(tmp_path):
    """The point of all of it: a punched frame is sharper than it used to be.

    Laplacian variance of the last (most zoomed) frame, rendered twice through
    the real compose path with only the headroom changed.
    """
    np = pytest.importorskip("numpy")
    src = tmp_path / "in.mp4"
    # Fine detail is the whole subject: a smooth gradient would score the same
    # either way. testsrc2's noise band gives real high-frequency content.
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x3413:d=2:r=30",
         "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(src)],
        capture_output=True, check=True,
    )

    def render(where, headroom):
        original = pf.scale_headroom
        pf.scale_headroom = headroom
        try:
            result, _ = _compose(where, [
                {"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 2,
                 "polish": {"punch_in": 1.6}}],
                spine={"metadata": {"compose_target":
                                    {"width": 1080, "height": 1920, "fit": "cover"}}})
            assert result.success, result.error
        finally:
            pf.scale_headroom = original
        raw = subprocess.check_output(
            ["ffmpeg", "-v", "error", "-sseof", "-0.04", "-i", str(where / "out.mp4"),
             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"])
        a = np.frombuffer(raw, dtype="uint8").reshape(1920, 1080).astype("float64")
        return (-4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1]
                + a[1:-1, :-2] + a[1:-1, 2:]).var()

    # `**kw` because `_compose` now hands scale_headroom the target, the
    # source size and the fit mode; the control ignores all three.
    before = render(tmp_path / "flat", lambda cut, **kw: 1.0)
    after = render(tmp_path / "headroom", pf.scale_headroom)
    assert after > before * 1.2, f"{before=} {after=}"


# ---- the ramp against the CFR grid ----

@requires_ffmpeg
@pytest.mark.parametrize("ramp", [2.0, 3.0, 0.5])
def test_a_ramped_segments_picture_and_audio_end_within_the_quantisation_floor(
    tmp_path, ramp
):
    """The log-mean's real guarantee, measured rather than asserted.

    `ramp_average_speed` used to claim it kept "the audio exactly as long as
    the picture". It does not: `-r 30` requantises the ramped PTS onto the CFR
    grid and AAC ends on a whole 1024-sample packet, so a 2s cut lands 21-57ms
    apart whatever atempo is fed. What the log-mean does buy is that the drift
    stays inside that floor instead of growing with the ramp — the arithmetic
    mean puts 1.0->3.0 at ~100ms.
    """
    src = tmp_path / "in.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=4:r=30",
         "-f", "lavfi", "-i", "sine=f=440:d=4", "-c:v", "libx264", "-crf", "28",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)],
        capture_output=True, check=True,
    )
    result, _ = _compose(tmp_path, [
        {"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 2,
         "polish": {"speed_ramp": ramp}}])
    assert result.success, result.error

    def duration(stream):
        return float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", stream,
             "-show_entries", "stream=duration", "-of", "csv=p=0",
             str(tmp_path / "out.mp4")]).decode().strip().rstrip(","))

    drift = duration("v:0") - duration("a:0")
    # The floor is one video frame (33ms) plus one AAC packet (21ms), and the
    # last 5ms is encoder priming. Measured max across these three ramps: 57ms.
    floor = 1.0 / 30 + 1024 / 48000 + 0.005
    assert abs(drift) <= floor, f"{ramp=} {drift=} {floor=}"


# ---- where the batch look comes from ----

def test_the_batch_look_is_read_off_the_spine():
    """Spec §4.2 puts the shared vocabulary on edit_decisions, not on an argument."""
    ed = {"batch_look": LOOK}
    assert VideoCompose._resolve_batch_look({}, ed) == LOOK
    ed_meta = {"metadata": {"batch_look": LOOK}}
    assert VideoCompose._resolve_batch_look({}, ed_meta) == LOOK
    assert VideoCompose._resolve_batch_look({}, {}) is None


def test_the_tool_input_overrides_the_spine():
    other = {"grade": "cinematic_cool"}
    assert VideoCompose._resolve_batch_look(
        {"batch_look": other}, {"batch_look": LOOK}
    ) == other


@requires_ffmpeg
def test_a_look_on_the_spine_reaches_the_encode(tmp_path):
    src = tmp_path / "in.mp4"
    _clip(src)
    result, seen = _compose(
        tmp_path,
        [{"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 1}],
        spine={"metadata": {"batch_look": LOOK}},
    )
    assert result.success, result.error
    assert _segment_vf(seen)[0] == BASELINE_VF + "," + ",".join(pf.look_filters(LOOK))


@requires_ffmpeg
def test_one_setting_stamps_the_same_look_on_every_reel_of_a_batch(tmp_path):
    """Five REELS, one look — composed through the real path, not one function.

    Each reel is its own compose call with its own cuts and its own punch-in,
    exactly as compose-director materialises them off the spine.
    """
    src = tmp_path / "in.mp4"
    _clip(src, d=3)
    tails = []
    for n in range(5):
        result, seen = _compose(
            tmp_path / f"reel-{n}",
            [{"id": f"reel-{n}-c1", "source": str(src),
              "in_seconds": 0, "out_seconds": 1, "polish": {"punch_in": 1.1 + n / 10}},
             {"id": f"reel-{n}-c2", "source": str(src), "in_seconds": 1, "out_seconds": 2}],
            spine={"metadata": {"batch_look": LOOK}},
        )
        assert result.success, result.error
        for vf in _segment_vf(seen):
            tails.append(vf.split("fps=30,", 1)[1])
    assert len(tails) == 10
    # Every segment of every reel carries the identical look tail, whatever
    # else that particular cut asked for.
    assert {t for t in tails if "zoompan" not in t} == {",".join(pf.look_filters(LOOK))}
    assert all(t.endswith(",".join(pf.look_filters(LOOK))) for t in tails)


# ---- polish cannot survive a runtime that never reads it ----

def _gate(runtime, cuts, look=None):
    ed = {"version": "1.0", "render_runtime": runtime, "cuts": cuts}
    return VideoCompose()._pre_compose_validation(ed, cuts, batch_look=look)


def test_polish_routed_to_remotion_is_refused_not_silently_dropped():
    """Remotion never reads `polish`; a successful render would be the wrong reel."""
    cuts = [{"id": "c1", "source": "a.mp4", "polish": {"punch_in": 1.6}}]
    blocked = _gate("remotion", cuts)
    assert blocked is not None and not blocked.success
    assert "punch_in" in _polish_block(blocked) and "'c1'" in _polish_block(blocked)


def test_a_batch_look_routed_to_hyperframes_is_refused():
    cuts = [{"id": "c1", "source": "a.mp4"}]
    blocked = _gate("hyperframes", cuts, look=LOOK)
    assert "batch_look" in _polish_block(blocked)


def _polish_block(result) -> str:
    """The polish-routing message, or "" — other pre-compose checks also fire."""
    error = "" if result is None else (result.error or "")
    return error if "picture plane" in error else ""


def test_ffmpeg_is_the_runtime_that_may_carry_polish():
    cuts = [{"id": "c1", "source": "a.mp4", "polish": {"punch_in": 1.6}}]
    assert _polish_block(_gate("ffmpeg", cuts, look=LOOK)) == ""
    # ...and a cut with nothing to lose is not blocked on any runtime.
    assert _polish_block(_gate("remotion", [{"id": "c1", "source": "a.mp4"}])) == ""


# ---- bounds and ergonomics ----

def test_grain_is_bounded_like_everything_else_in_this_module():
    """`noise=alls=` is 0-100; 500 was an ffmpeg parse error, -5 a silent zero."""
    with pytest.raises(pf.PolishError, match="grain"):
        pf.look_filters({"grain": 500})
    with pytest.raises(pf.PolishError, match="grain"):
        pf.look_filters({"grain": -5})
    assert pf.look_filters({"grain": 100}) == ["noise=alls=100:allf=t+u"]


def test_non_numeric_polish_values_are_refused_as_polish_errors():
    """Not a bare ValueError — everything this module rejects is a PolishError."""
    for cut in (
        {"polish": {"punch_in": "1.6x"}},
        {"polish": {"speed_ramp": "fast"}},
        {"speed": "slow"},
    ):
        with pytest.raises(pf.PolishError):
            pf.cut_filters(cut, 2.0, 1080, 1920)


def test_a_ramp_that_rounds_away_at_the_emitted_precision_is_not_a_ramp():
    """`k` is written at six decimals; 1e-7 becomes a division by 0.000000."""
    assert not pf.is_ramp(1.0, 1.0000001)
    parts = pf.cut_filters({"speed": 1.0, "polish": {"speed_ramp": 1.0000001}},
                           2.0, 1080, 1920)
    assert parts == []
    with pytest.raises(pf.PolishError, match="not a ramp"):
        pf.speed_ramp_setpts(1.0, 1.0000001, 2.0)
    # A ramp that survives the rounding still ramps.
    assert pf.is_ramp(1.0, 1.001)
    assert "0.000000*T" not in pf.speed_ramp_setpts(1.0, 1.001, 2.0)


def test_a_grade_named_in_both_sets_is_still_gated_on_operator_footage(monkeypatch):
    """The trap: FACE_PRESETS was consulted first, skipping the identity gate.

    The two name sets are disjoint today, so nothing leaks — this pins the
    behaviour for whoever adds a name to both.
    """
    shared = sorted(FACE_PRESETS)[0]
    monkeypatch.setitem(pf.GRADE_PROFILES, shared, {"vf": "eq=contrast=1.4"})
    # Unlocked, the face preset still wins — the resolution order is unchanged.
    assert pf.look_filters({"grade": shared}) == [FACE_PRESETS[shared]["vf"]]
    with pytest.raises(pf.PolishError, match="identity-safe"):
        pf.look_filters({"grade": shared}, "operator_footage")


# ---- the whip, at render level ----

def _axis_detail(path: Path, axis: int, from_end: float = 0.04) -> float:
    """Mean absolute neighbour difference along one axis of the last frame."""
    np = pytest.importorskip("numpy")
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-sseof", f"-{from_end}", "-i", str(path),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
    )
    a = np.frombuffer(raw, dtype="uint8").reshape(1080, 1920).astype("float64")
    return float(np.abs(np.diff(a, axis=axis)).mean())


@requires_ffmpeg
def test_whip_smears_the_last_frame_horizontally_and_only_horizontally(tmp_path):
    """sigmaV=0 is the whole point: a whip-pan blurs across, not down.

    The fixture is a GRID, not vertical bars, and the "only horizontally" half
    is asserted as a floor rather than a tolerance. Both were needed to make
    the test able to fail: on vertical bars there is no vertical detail to
    lose, and `abs=1.0` on a quantity whose whole measured range is ~0.05
    passes whatever the filter does — deleting `sigmaV=0` from `whip_out` left
    the old version green.
    """
    src = tmp_path / "in.mp4"
    # A grid has detail on BOTH axes, so a blur that leaks into the vertical
    # has something to destroy and the second assertion has something to see.
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1920x1080:d=2:r=30",
         "-vf", "drawgrid=w=16:h=16:t=4:color=white",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         "-g", "30", "-keyint_min", "30", str(src)],
        capture_output=True, check=True,
    )
    plain, _ = _compose(tmp_path / "a", [
        {"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 2}])
    whipped, _ = _compose(tmp_path / "b", [
        {"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 2,
         "polish": {"transition_out": "whip"}}])
    assert plain.success and whipped.success, whipped.error

    a, b = tmp_path / "a" / "out.mp4", tmp_path / "b" / "out.mp4"
    # Across the grid: the whip has flattened it.
    assert _axis_detail(b, 1) < _axis_detail(a, 1) * 0.5
    # Down the grid: the horizontal lines survive. Measured on this fixture,
    # 23.36 of 23.74 (98%) with sigmaV=0 and 0.07 of 23.74 without it, so the
    # 0.9 floor sits nowhere near either — it is a wall, not a tolerance.
    assert _axis_detail(b, 0) > _axis_detail(a, 0) * 0.9
