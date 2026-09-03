"""Vertical / arbitrary-resolution support for video_compose's FFmpeg compose.

Regression test for a silent-dimension bug: the compose target resolution was
resolved from `profile` (and the documented `metadata.compose_target` hook) but
the per-segment scale/pad filter hardcoded 1920x1080, so vertical profiles like
`tiktok` silently produced landscape output. These tests run the real FFmpeg
path on a tiny lavfi fixture and assert the output dimensions.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tools.video.video_compose import VideoCompose

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)


def _make_clip(path: Path, w: int = 1280, h: int = 720, d: int = 2) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"color=c=teal:s={w}x{h}:d={d}:r=30",
         "-c:v", "libx264", "-crf", "28", "-pix_fmt", "yuv420p",
         "-g", "30", "-keyint_min", "30", str(path)],
        capture_output=True, check=True,
    )


def _dims(path: Path) -> tuple[int, int]:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)]
    ).decode().strip()
    w, h = out.split(",")
    return int(w), int(h)


def _edit_decisions(src: Path, metadata: dict | None = None) -> dict:
    ed = {
        "version": "1.0",
        "render_runtime": "ffmpeg",
        "cuts": [{"id": "c1", "source": str(src), "in_seconds": 0, "out_seconds": 2}],
    }
    if metadata:
        ed["metadata"] = metadata
    return ed


def test_compose_default_is_landscape_hd(tmp_path):
    """No profile / no target → unchanged 1920x1080 default (backward compatible)."""
    src = tmp_path / "in.mp4"
    _make_clip(src)
    out = tmp_path / "out.mp4"
    r = VideoCompose().execute(
        {"operation": "compose", "edit_decisions": _edit_decisions(src), "output_path": str(out)}
    )
    assert r.success, r.error
    assert _dims(out) == (1920, 1080)


def test_compose_vertical_profile(tmp_path):
    """profile='tiktok' → 1080x1920 (the bug: previously stayed 1920x1080)."""
    src = tmp_path / "in.mp4"
    _make_clip(src)
    out = tmp_path / "out.mp4"
    r = VideoCompose().execute(
        {"operation": "compose", "edit_decisions": _edit_decisions(src),
         "profile": "tiktok", "output_path": str(out)}
    )
    assert r.success, r.error
    assert _dims(out) == (1080, 1920)


def test_compose_target_override_cover(tmp_path):
    """metadata.compose_target with fit='cover' → exact requested dims, cropped to fill."""
    src = tmp_path / "in.mp4"
    _make_clip(src)
    out = tmp_path / "out.mp4"
    ed = _edit_decisions(src, metadata={"compose_target": {"width": 720, "height": 1280, "fit": "cover"}})
    r = VideoCompose().execute(
        {"operation": "compose", "edit_decisions": ed, "output_path": str(out)}
    )
    assert r.success, r.error
    assert _dims(out) == (720, 1280)


def _top_strip_max_luma(path: Path, rows: int = 120) -> int:
    """Max luma in the top `rows` of frame 1. ~0 under a letterbox bar."""
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"crop=iw:{rows}:0:0", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
    )
    return max(raw)


def test_portrait_profile_fills_the_frame(tmp_path):
    """D6: a 9:16 profile must scale-to-fill, not letterbox landscape source.

    `profile` overrode resolution but left `fit_mode` at its `pad` default, so
    landscape gym footage arrived in Reels as a black-bar sandwich.
    """
    src = tmp_path / "in.mp4"
    _make_clip(src, w=1280, h=720)
    out = tmp_path / "out.mp4"
    r = VideoCompose().execute(
        {"operation": "compose", "edit_decisions": _edit_decisions(src),
         "profile": "instagram_reels", "output_path": str(out)}
    )
    assert r.success, r.error
    assert _dims(out) == (1080, 1920)
    assert _top_strip_max_luma(out) > 20, "top of frame is black — still letterboxing"


def test_explicit_pad_still_wins_over_a_portrait_profile(tmp_path):
    """A caller who asks for `pad` keeps it — the profile only supplies a default."""
    src = tmp_path / "in.mp4"
    _make_clip(src, w=1280, h=720)
    out = tmp_path / "out.mp4"
    ed = _edit_decisions(src, metadata={"compose_target": {"width": 1080, "height": 1920, "fit": "pad"}})
    r = VideoCompose().execute(
        {"operation": "compose", "edit_decisions": ed,
         "profile": "instagram_reels", "output_path": str(out)}
    )
    assert r.success, r.error
    assert _top_strip_max_luma(out) <= 20


def test_landscape_profile_keeps_padding(tmp_path):
    """The fill default is scoped to portrait: 16:9 targets stay backward compatible."""
    src = tmp_path / "in.mp4"
    _make_clip(src, w=720, h=720)
    out = tmp_path / "out.mp4"
    r = VideoCompose().execute(
        {"operation": "compose", "edit_decisions": _edit_decisions(src),
         "profile": "youtube_landscape", "output_path": str(out)}
    )
    assert r.success, r.error
    assert _dims(out) == (1920, 1080)
    # Square source into 16:9 with pad → black pillars at the left edge.
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(out), "-vf", "crop=200:ih:0:0",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
    )
    assert max(raw) <= 20
