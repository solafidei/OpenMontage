"""Regression guard: final_review must never fabricate a pass it did not verify.

The bug this locks down: burned-in subtitles leave no subtitle stream, and the
review used to respond by asserting subtitles_present=True and coverage_ratio=1.0
purely because a source file existed on disk — turning "not inspected" into a
clean pass. Observed alongside status:"pass" while narration was absent.
"""
import ast
import inspect
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "tools" / "video" / "video_compose.py"


def test_burn_in_does_not_assert_presence():
    src = SRC.read_text()
    assert 'subtitle_check["coverage_ratio"] = 1.0' not in src, (
        "coverage_ratio=1.0 is fabricated — the pixels were never inspected"
    )
    assert 'subtitle_check["subtitles_present"] = True' not in src, (
        "subtitles_present=True on the burn-in path asserts an unverified pass"
    )
    assert "indeterminate — burned-in, not inspected" in src


def test_negative_only_gates_flip_status():
    """Both new gates must appear in the critical-issue keyword list, or they
    are recorded as issues and then silently ignored by the status rule."""
    src = SRC.read_text()
    tree = ast.parse(src)
    keywords = {
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "narration missing" in keywords
    assert "programme audio too quiet" in keywords
    # and the phrases the gates actually emit must contain those keywords
    assert "— narration missing" in src
    assert "— programme audio too quiet" in src


def test_loudness_floor_is_conservative():
    import sys
    sys.path.insert(0, str(SRC.parents[2]))
    from tools.video.video_compose import LUFS_DELIVERY_FLOOR
    # Broadcast targets sit at -16..-23 LUFS. The floor must be well below, so
    # it only trips on genuinely under-level audio and never on a quiet mix.
    assert LUFS_DELIVERY_FLOOR < -30, "floor would false-fire on normal programme audio"


if __name__ == "__main__":
    test_burn_in_does_not_assert_presence()
    test_negative_only_gates_flip_status()
    test_loudness_floor_is_conservative()
    print("PASS — final_review honesty guards hold")
