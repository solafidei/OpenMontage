"""Regression guard: final_review must never fabricate a pass it did not verify.

The guards here are **behavioral** — they execute `_run_final_review` on real
renders and assert on the dict it returns, so they hold under any respelling of
the code. (The previous versions walked the AST and grepped the source, which a
respelled revert would have sailed straight through.)

The bug this locks down: burned-in subtitles leave no subtitle stream, and the
review used to respond by asserting subtitles_present=True and coverage_ratio=1.0
purely because a source file existed on disk — turning "not inspected" into a
clean pass. Observed alongside status:"pass" while narration was absent.

Fine-grained per-verdict coverage lives in
`tests/tools/test_final_review_audio_gates.py`; this file keeps exactly the two
honesty invariants its docstring declares — no fabricated subtitle pass, and the
critical gates actually flip status — one real render each.
"""
from tools.video.video_compose import LUFS_DELIVERY_FLOOR, VideoCompose

# Cross-importing test modules is the house pattern (cf.
# `from tests.contracts.test_phase0_contracts import sample_artifact`).
from tests.tools.test_final_review_audio_gates import _make_mp4


def _edit_decisions(**extra):
    ed = {
        "version": "1.0",
        "renderer_family": "animation-first",
        "render_runtime": "ffmpeg",
        "cuts": [{"id": "c1", "source": "x", "in_seconds": 0, "out_seconds": 2}],
    }
    ed.update(extra)
    return ed


def test_burn_in_yields_indeterminate_never_a_fabricated_pass(tmp_path):
    """Burn-in leaves no subtitle stream and nothing inspected the pixels.

    The review must record that as *indeterminate*, not as a pass and not as a
    failure. Asserts read the executed output, so any respelling of the old
    fabrication (`.update({...})`, a helper, re-whitespaced assignments) still
    flips `subtitles_present`/`coverage_ratio` and fails here.
    """
    mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2")
    subs = tmp_path / "subs.srt"
    subs.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello there.\n\n", encoding="utf-8"
    )

    edit_decisions = _edit_decisions(
        subtitles={"enabled": True, "source": str(subs)}
    )

    review = VideoCompose()._run_final_review(mp4, edit_decisions=edit_decisions)
    sc = review["checks"]["subtitle_check"]

    assert sc["subtitles_expected"] is True, sc
    assert sc["subtitles_present"] is False, sc
    assert sc["inspected"] is False, sc
    assert sc["verdict"] == "indeterminate — burned-in, not inspected", sc
    assert sc.get("coverage_ratio") != 1.0, sc
    # Indeterminate is not a failure either — no subtitle issue raised.
    assert not sc["issues"], sc


def test_measured_silence_flips_status_through_both_critical_gates(tmp_path):
    """One render, both critical audio keywords, and the status rule honours them.

    The fixture is a *measured* silence (mean ≈ -78 dB, integrated LUFS far below
    LUFS_DELIVERY_FLOOR), so both negative-only gates are entitled to fire. If a
    refactor renames the `audio.narration.segments` nesting the gate reads,
    `narration_expected` goes False and the gate-fire assert below fails.
    """
    mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2,volume=-75dB")

    edit_decisions = _edit_decisions(
        audio={"narration": {"segments": [{"id": "n1"}]}}
    )
    assert "subtitles" not in edit_decisions

    review = VideoCompose()._run_final_review(mp4, edit_decisions=edit_decisions)

    assert review["status"] == "revise", review["issues_found"]
    assert review["recommended_action"] == "re_render", review
    assert any("narration missing" in i for i in review["issues_found"]), (
        review["issues_found"]
    )
    assert any(
        "programme audio too quiet" in i for i in review["issues_found"]
    ), review["issues_found"]
    assert review["checks"]["audio_spotcheck"]["narration_verdict"].startswith(
        "measured"
    ), review["checks"]["audio_spotcheck"]


def test_loudness_floor_is_conservative():
    # Broadcast targets sit at -16..-23 LUFS. The floor must be well below, so
    # it only trips on genuinely under-level audio and never on a quiet mix.
    assert LUFS_DELIVERY_FLOOR < -30, "floor would false-fire on normal programme audio"


def test_each_new_critical_keyword_alone_flips_status(tmp_path):
    """Each new gate must be *sufficient* on its own to flip status.

    The measured-silence render above trips several critical keywords at once
    (`effectively silent` predates this epic), so it cannot prove that the two
    new keywords reached the critical list. These two renders isolate them:
    each produces exactly one critical-eligible issue. Dropping either keyword
    from the status rule's list leaves the issue recorded and then silently
    ignored — status falls back to "pass" and this test goes red.
    """
    # (a) No audio stream at all, narration promised — "narration missing" is
    #     the only critical-eligible issue ("No audio stream in output" and
    #     "Black frame detected" are not on the list).
    silent = _make_mp4(tmp_path, None, name="no_audio.mp4")
    review = VideoCompose()._run_final_review(
        silent,
        edit_decisions=_edit_decisions(
            audio={"narration": {"segments": [{"id": "n1"}]}}
        ),
    )
    narration_issues = [i for i in review["issues_found"] if "narration missing" in i]
    assert narration_issues, review["issues_found"]
    assert "effectively silent" not in " ".join(review["issues_found"])
    assert review["status"] == "revise", review["issues_found"]
    assert review["recommended_action"] == "re_render", review

    # (b) Audible but under-level: above the -60 dB silence floor (so no
    #     "effectively silent"), below the -40 LUFS delivery floor, narration
    #     never promised — "programme audio too quiet" stands alone.
    quiet = _make_mp4(
        tmp_path, "sine=frequency=440:duration=2,volume=-30dB", name="quiet.mp4"
    )
    review = VideoCompose()._run_final_review(quiet, edit_decisions=_edit_decisions())
    audio = review["checks"]["audio_spotcheck"]
    assert audio["unexpected_silence"] is False, audio
    assert any(
        "programme audio too quiet" in i for i in review["issues_found"]
    ), review["issues_found"]
    assert review["status"] == "revise", review["issues_found"]
    assert review["recommended_action"] == "re_render", review
