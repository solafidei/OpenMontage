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
    # Smoothstep, not a straight line: a quarter of the way in, the zoom has
    # travelled less than a quarter of the distance.
    quarter = _eval_zoom(f, last // 4)
    assert quarter < 1.0 + (2.0 - 1.0) * 0.25
    assert f"s=1080x1920" in f


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


def test_one_setting_stamps_the_same_look_on_every_reel_of_a_batch():
    reels = [
        {"id": f"reel-{n}", "polish": {"punch_in": 1.0 + n / 10}} for n in range(1, 6)
    ]
    looks = [
        [p for p in pf.cut_filters(c, 2.0, 1080, 1920, look=LOOK)
         if "zoompan" not in p]
        for c in reels
    ]
    assert len({tuple(look) for look in looks}) == 1
    assert looks[0] == pf.look_filters(LOOK)


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


def _compose(tmp_path, cuts, **extra):
    """Run compose, returning (result, every ffmpeg command it issued)."""
    seen: list[list[str]] = []
    original = VideoCompose.run_command

    def recording(self, cmd, **kwargs):
        seen.append(list(cmd))
        return original(self, cmd, **kwargs)

    tool = VideoCompose()
    tool.run_command = recording.__get__(tool, VideoCompose)
    result = tool.execute({
        "operation": "compose",
        "edit_decisions": {"version": "1.0", "render_runtime": "ffmpeg", "cuts": cuts},
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
