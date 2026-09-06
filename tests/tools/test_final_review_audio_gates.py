"""Behavioral tests for the final_review audio gates (Epic 1, workstream E).

These tests do NOT inspect source text — they build real MP4s with lavfi and
drive `VideoCompose()._run_final_review(...)`, so they observe the gates that
actually ran.

Shared principle under test: *a negative-only gate may only fire on a
measurement that actually happened.* Three verdict paths, always recorded —
measured-present, measured-absent (gate fires), and indeterminate (visible
note, never a critical — and never a silent pass either: it reports
`status: "needs_verification"` so a human looks before the render ships).

`_make_mp4` is exported for reuse by other final_review test modules.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.video.video_compose import SILENCE_FLOOR_DB, VideoCompose


# ------------------------------------------------------------------
# Shared fixtures / helpers
# ------------------------------------------------------------------


def _make_mp4(tmp_path, audio_args: str | None = "sine=frequency=440:duration=2",
              name: str = "out.mp4") -> Path:
    """Build a real 2s 320x240 MP4 under `tmp_path` and return its Path.

    Args:
        tmp_path: directory to write into (a pytest ``tmp_path`` works).
        audio_args: an ffmpeg lavfi audio source description, e.g.
            ``"sine=frequency=440:duration=2,volume=-70dB"``. Pass ``None``
            to build a **video-only** file with no audio stream at all.
        name: output filename inside ``tmp_path`` (lets one test build
            several distinct fixtures).
    """
    mp4 = Path(tmp_path) / name
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=#000000:s=320x240:d=2",
    ]
    if audio_args:
        cmd += ["-f", "lavfi", "-i", audio_args]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio_args:
        cmd += ["-c:a", "aac"]
    cmd += ["-shortest", str(mp4)]
    subprocess.run(cmd, capture_output=True, check=True, timeout=60)
    return mp4


NARRATION_ED: dict[str, Any] = {
    "version": "1.0",
    "render_runtime": "ffmpeg",
    "cuts": [
        {"id": "c1", "source": "x", "in_seconds": 0, "out_seconds": 2},
    ],
    "audio": {"narration": {"segments": [{"id": "n1"}]}},
}


def _patch_run(monkeypatch, predicate, exc_factory):
    """Patch video_compose's subprocess.run so calls matching `predicate`
    (on the argv list) raise, and everything else runs for real."""
    real_run = subprocess.run

    def wrapper(cmd, *args, **kwargs):
        argv = list(cmd) if isinstance(cmd, (list, tuple)) else [str(cmd)]
        if predicate(argv):
            raise exc_factory(argv)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("tools.video.video_compose.subprocess.run", wrapper)
    return real_run


def _audio(review):
    return review["checks"]["audio_spotcheck"]


def _has(review, needle: str) -> bool:
    return any(needle in i for i in review["issues_found"])


# ------------------------------------------------------------------
# E1 — narration gate must measure before it asserts
# ------------------------------------------------------------------


def test_gate_fires_on_measured_silence(tmp_path):
    """Measured digital silence disproves promised narration — gate fires."""
    mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2,volume=-75dB")

    review = VideoCompose()._run_final_review(mp4, edit_decisions=NARRATION_ED)
    audio = _audio(review)

    assert _has(review, "narration missing"), review["issues_found"]
    assert review["status"] == "revise"
    assert review["recommended_action"] == "re_render"
    assert audio["narration_verdict"].startswith("measured"), audio


def test_gate_indeterminate_when_analysis_fails(tmp_path, monkeypatch):
    """volumedetect never ran ⇒ indeterminate, never a 'narration missing'."""
    mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2")

    _patch_run(
        monkeypatch,
        lambda argv: "volumedetect" in " ".join(argv),
        lambda argv: subprocess.TimeoutExpired(argv, 60),
    )

    review = VideoCompose()._run_final_review(mp4, edit_decisions=NARRATION_ED)
    audio = _audio(review)

    assert not _has(review, "narration missing"), review["issues_found"]
    assert audio["narration_verdict"].startswith("indeterminate"), audio
    assert audio["mean_volume_db"] is None
    # Not a critical revise (nothing was disproven) and not a pass either
    # (nothing was verified) — the render needs a human.
    assert review["status"] == "needs_verification", review["issues_found"]
    # E2(b): the two probes live in SEPARATE try blocks, so volumedetect
    # dying must not take the LUFS probe down with it. Merge the ebur128
    # block back into the volumedetect try and these two go red
    # ("indeterminate — integrated loudness not measured...").
    assert "integrated_lufs" in audio, audio
    assert audio["loudness_verdict"].startswith("measured"), audio


def test_gate_indeterminate_on_quiet_mix(tmp_path):
    """Between the silence floor and the narration heuristic, volume alone
    can neither prove nor disprove narration."""
    mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2,volume=-25dB")

    review = VideoCompose()._run_final_review(mp4, edit_decisions=NARRATION_ED)
    audio = _audio(review)

    assert not _has(review, "narration missing"), review["issues_found"]
    assert audio["narration_verdict"].startswith("indeterminate"), audio
    # Overall status deliberately not asserted: the LUFS floor gate may
    # independently (and correctly) flag a ~-47 LUFS master.


def test_silence_floor_boundary_is_consistent(tmp_path, monkeypatch):
    """At exactly SILENCE_FLOOR_DB the two thresholds must not disagree.

    `unexpected_silence` fires on ``mean_vol < SILENCE_FLOOR_DB`` and the
    narration gate's measured-absent branch must use the same strict
    comparison — the constant exists precisely so "the gate's absent-threshold
    and the 'effectively silent' threshold cannot drift apart", and its own
    comment defines silence as *below* the floor.

    volumedetect prints mean_volume to one decimal, so ``-60.0 dB`` is a value
    it really emits; this stubs that exact line rather than chasing it with a
    lavfi gain. With a ``<=`` narration branch the artifact contradicts itself:
    ``unexpected_silence=False`` and no "effectively silent" issue, yet a
    measured-absent verdict and a critical "narration missing" that fails the
    render.
    """
    mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2")

    real_run = subprocess.run
    stub_stderr = (
        "[Parsed_volumedetect_0 @ 0x1] n_samples: 96000\n"
        f"[Parsed_volumedetect_0 @ 0x1] mean_volume: {SILENCE_FLOOR_DB:.1f} dB\n"
        "[Parsed_volumedetect_0 @ 0x1] max_volume: -50.0 dB\n"
    )

    def wrapper(cmd, *args, **kwargs):
        argv = list(cmd) if isinstance(cmd, (list, tuple)) else [str(cmd)]
        if any("volumedetect" in str(a) for a in argv):
            return subprocess.CompletedProcess(argv, 0, "", stub_stderr)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("tools.video.video_compose.subprocess.run", wrapper)

    review = VideoCompose()._run_final_review(mp4, edit_decisions=NARRATION_ED)
    audio = _audio(review)

    assert audio["mean_volume_db"] == SILENCE_FLOOR_DB, audio
    # The silence detector's verdict at the boundary...
    assert audio["unexpected_silence"] is False, audio
    assert not _has(review, "effectively silent"), review["issues_found"]
    # ...and the narration gate's must agree: nothing was disproven here.
    assert not _has(review, "narration missing"), review["issues_found"]
    assert audio["narration_verdict"].startswith("indeterminate"), audio
    assert review["status"] == "needs_verification", review["issues_found"]


def test_gate_fires_when_no_audio_stream(tmp_path):
    """ffprobe measured the absence of any audio stream — gate fires."""
    mp4 = _make_mp4(tmp_path, audio_args=None, name="silent.mp4")

    review = VideoCompose()._run_final_review(mp4, edit_decisions=NARRATION_ED)
    audio = _audio(review)

    assert review["checks"]["technical_probe"]["has_audio"] is False
    assert _has(review, "narration missing"), review["issues_found"]
    assert audio["narration_verdict"] == "measured — output has no audio stream"


def test_verdict_present_on_audible_mix(tmp_path):
    """A full-level mix records a measured-present verdict and no issue."""
    mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2")

    review = VideoCompose()._run_final_review(mp4, edit_decisions=NARRATION_ED)
    audio = _audio(review)

    assert audio["narration_present"] is True
    assert audio["narration_verdict"].startswith("measured"), audio
    assert not _has(review, "narration missing"), review["issues_found"]
    assert not _has(review, "narration presence indeterminate"), review["issues_found"]


# ------------------------------------------------------------------
# E2 — bounded decode, and a skipped LUFS gate that says so
# ------------------------------------------------------------------


def test_audio_probes_run_audio_only(tmp_path, monkeypatch):
    """volumedetect and ebur128 must decode audio only (-vn)."""
    mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2")

    recorded: list[list[str]] = []
    real_run = subprocess.run

    def recorder(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)):
            recorded.append([str(c) for c in cmd])
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("tools.video.video_compose.subprocess.run", recorder)

    VideoCompose()._run_final_review(mp4, edit_decisions=NARRATION_ED)

    probes = [
        argv for argv in recorded
        if any("volumedetect" in a or "ebur128" in a for a in argv)
    ]
    assert len(probes) >= 2, recorded
    for argv in probes:
        assert "-vn" in argv, argv


def test_lufs_timeout_is_indeterminate_not_silent(tmp_path, monkeypatch):
    """An ebur128 timeout yields an indeterminate loudness verdict — never a
    silent skip, never a critical — and leaves volumedetect's result intact."""
    mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2")

    _patch_run(
        monkeypatch,
        lambda argv: "ebur128" in " ".join(argv),
        lambda argv: subprocess.TimeoutExpired(argv, 120),
    )

    review = VideoCompose()._run_final_review(mp4, edit_decisions=NARRATION_ED)
    audio = _audio(review)

    assert "integrated_lufs" not in audio
    assert audio["loudness_verdict"].startswith("indeterminate"), audio
    assert _has(review, "loudness indeterminate"), review["issues_found"]
    assert review["status"] == "needs_verification", review["issues_found"]
    # The split try/except kept the volumedetect measurement alive.
    assert audio["mean_volume_db"] is not None
    assert audio["narration_verdict"].startswith("measured"), audio


def test_lufs_gate_still_fires_when_measured_low(tmp_path):
    """-vn and the try-split did not blunt the LUFS floor gate."""
    mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2,volume=-30dB")

    review = VideoCompose()._run_final_review(mp4, edit_decisions=NARRATION_ED)
    audio = _audio(review)

    assert _has(review, "programme audio too quiet"), review["issues_found"]
    assert review["status"] == "revise"
    assert audio["loudness_verdict"].startswith("measured"), audio


# ------------------------------------------------------------------
# Owner ruling — a render nothing measured is not a pass
# ------------------------------------------------------------------


def test_indeterminate_never_reads_as_a_clean_pass(tmp_path, monkeypatch):
    """An unverified render must not come back presentable.

    volumedetect times out, so narration presence is neither proven nor
    disproven — no critical keyword fires. Before `needs_verification` that
    fell through to ``pass``/``present_to_user`` and a render whose audio was
    never verified read as finished. Drop the indeterminate branch from the
    status rule and this goes red on the first two asserts.
    """
    mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2")

    _patch_run(
        monkeypatch,
        lambda argv: "volumedetect" in " ".join(argv),
        lambda argv: subprocess.TimeoutExpired(argv, 60),
    )

    review = VideoCompose()._run_final_review(mp4, edit_decisions=NARRATION_ED)

    assert review["status"] != "pass", review["issues_found"]
    assert review["recommended_action"] != "present_to_user", review
    assert review["status"] == "needs_verification", review["issues_found"]
    assert review["recommended_action"] == "human_review", review
    # E1's honesty fix is untouched: nothing was disproven, so no critical.
    assert review["status"] != "revise", review["issues_found"]
    assert not _has(review, "narration missing"), review["issues_found"]


def test_critical_and_container_failure_outrank_needs_verification(tmp_path):
    """Precedence: fail > revise > needs_verification.

    A file ffprobe cannot parse produces both a critical issue ("ffprobe
    failed") and an indeterminate one (nothing could be measured). The
    critical branch must win over the new one, and the invalid-container
    override must then win over everything.
    """
    broken = Path(tmp_path) / "broken.mp4"
    broken.write_bytes(b"not a container")

    review = VideoCompose()._run_final_review(broken, edit_decisions=NARRATION_ED)

    assert _has(review, "presence indeterminate"), review["issues_found"]
    assert review["status"] == "fail", review["issues_found"]
    assert review["recommended_action"] == "re_render", review


def test_schema_admits_the_new_status_and_action():
    """The artifact the tool writes must validate against its own schema."""
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "schemas" / "artifacts" / "final_review.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert "needs_verification" in schema["properties"]["status"]["enum"]
    assert "human_review" in schema["properties"]["recommended_action"]["enum"]
    assert "needs_verification" in schema["properties"]["status"]["description"]


def test_needs_verification_reaches_the_render_result_unswallowed(tmp_path):
    """The render paths must carry the new status out, not flatten it.

    Only `fail` downgrades the ToolResult (a needs_verification render did
    complete); the status itself is the gate, and it must arrive in
    `data["final_review_status"]` where the reviewer skill reads it — exactly
    as `revise` does. Swallow it and the caller has no signal at all.
    """
    from unittest import mock

    from tools.base_tool import ToolResult

    out = Path(tmp_path) / "render.mp4"
    out.write_bytes(b"stub")
    review = {"status": "needs_verification", "issues_found": ["x"],
              "recommended_action": "human_review"}

    tool = VideoCompose()
    with mock.patch.object(
        VideoCompose, "_compose",
        return_value=ToolResult(success=True, data={"output": str(out)}),
    ), mock.patch.object(VideoCompose, "_run_final_review", return_value=review):
        result = tool._render_via_ffmpeg(
            inputs={"output_path": str(out)},
            edit_decisions={"version": "1.0", "render_runtime": "ffmpeg"},
            resolved_cuts=[],
            output_path=out,
            profile=None,
        )

    assert result.data["final_review_status"] == "needs_verification"
    assert result.data["final_review"] is review
    assert result.success is True  # parity with `revise`: only `fail` downgrades


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
