"""A hand-written artifacts/decision_log.json must never fork the canonical log.

Regression for ask-jess: root held 11 decisions while artifacts/ held 30, for 29
hours, because the agent wrote the artifact copy directly and bypassed the merge.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.checkpoint import _merge_decision_log, _decision_log_path


def _d(i):
    return {"decision_id": f"d-{i:03d}", "stage": "edit", "category": "visual_accuracy_check",
            "subject": f"take {i}", "options_considered": [
                {"option_id": "a", "label": "keep", "score": 0.2, "reason": "mouth drift"},
                {"option_id": "b", "label": "reshoot", "score": 0.9, "reason": "clean"}],
            "selected": "b", "reason": "drift at 0:04"}


def test_orphaned_artifact_decisions_are_absorbed():
    with tempfile.TemporaryDirectory() as tmp:
        pdir, pid = Path(tmp), "proj"
        (pdir / pid / "artifacts").mkdir(parents=True)

        # canonical log gets 1 and 2 through the supported path
        _merge_decision_log(pdir, pid, {"decisions": [_d(1), _d(2)]})

        # someone hand-writes the artifact copy with an extra ruling
        (pdir / pid / "artifacts" / "decision_log.json").write_text(
            json.dumps({"version": "1.0", "project_id": pid,
                        "decisions": [_d(1), _d(2), _d(3)]})
        )

        # the next legitimate merge must absorb the orphan, not ignore it
        _merge_decision_log(pdir, pid, {"decisions": [_d(4)]})

        got = json.load(open(_decision_log_path(pdir, pid)))
        ids = [d["decision_id"] for d in got["decisions"]]
        assert len(ids) == len(set(ids)), f"duplicates introduced: {ids}"
        assert set(ids) == {"d-001", "d-002", "d-003", "d-004"}, (
            f"orphaned d-003 was not absorbed: {ids}"
        )


if __name__ == "__main__":
    test_orphaned_artifact_decisions_are_absorbed()
    print("PASS — decision log cannot silently fork")
