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


# --- Workstream F / F1: the supported write path, end to end ------------------

# The d-041 example carried verbatim by docs/intent/context-cost-spec.md section 2
# ("The judgment note"). Only project_id is bound to this test's project; the
# decision entry itself is the doc's literal. If the doc's example changes shape,
# test_context_cost_spec_judgment_example_is_schema_valid catches the schema side
# and this test keeps the behavioural side honest.
DOC_JUDGMENT_LOG = {
    "version": "1.0",
    "project_id": "run",
    "decisions": [
        {
            "decision_id": "d-041",
            "stage": "render",
            "category": "visual_accuracy_check",
            "subject": "scene 4 take selection",
            "options_considered": [
                {
                    "option_id": "take_3",
                    "label": "take 3",
                    "score": 0.2,
                    "reason": "best pacing",
                    "rejected_because": (
                        "mouth drift @0:04 — evidence: scratchpad/mouth/s4_sheet.png"
                    ),
                },
                {
                    "option_id": "take_5",
                    "label": "take 5",
                    "score": 0.9,
                    "reason": "clean lip sync at the approved pacing",
                },
            ],
            "selected": "take_5",
            "reason": (
                "take 3 vetoed for mouth drift; take 5 clean at the same pacing"
            ),
        }
    ],
}

DOC_LATE_RULING = {
    "decision_id": "d-042",
    "stage": "render",
    "category": "visual_accuracy_check",
    "subject": "scene 2 warm grade",
    "options_considered": [
        {"option_id": "warm", "label": "warm grade", "score": 0.3,
         "reason": "matches the reference stills",
         "rejected_because": "skin tones go orange under the key light"},
        {"option_id": "neutral", "label": "neutral grade", "score": 0.9,
         "reason": "skin reads true at the approved key"},
    ],
    "selected": "neutral",
    "reason": "warm grade vetoed on skin tone; neutral holds the reference",
}


def test_gate_ruling_flows_through_write_checkpoint(tmp_path):
    """The doc's judgment note must be *runnable*, not merely plausible.

    context-cost-spec.md section 2 now instructs carrying rulings on the gate
    write itself. This pins all three claims that instruction makes:

    1. the ruling lands in the canonical projects/<id>/decision_log.json,
    2. the artifacts/ side file the old text told agents to hand-append is
       never created by the supported path, and
    3. re-writing the same stage with extra entries is *additive* — the
       claim the doc makes for a ruling that arrives mid-awaiting_human.
    """
    from lib.checkpoint import init_project, write_checkpoint
    from schemas.artifacts import validate_artifact
    from tests.contracts.test_phase0_contracts import sample_artifact

    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )

    write_checkpoint(
        tmp_path,
        "run",
        "research",
        "awaiting_human",
        {
            "research_brief": sample_artifact("research_brief"),
            "decision_log": DOC_JUDGMENT_LOG,
        },
        pipeline_type="framework-smoke",
        metadata={
            "open": ["scene 2 audio sync unverified"],
            "measured": {"loudness_lufs": -16.2, "fps": 24},
        },
    )

    canonical = _decision_log_path(tmp_path, "run")
    assert canonical.exists(), (
        f"the gate write produced no canonical decision log at {canonical} — "
        "write_checkpoint no longer merges artifacts['decision_log'], so the "
        "instruction in context-cost-spec.md section 2 silently loses rulings"
    )
    root_log = json.loads(canonical.read_text(encoding="utf-8"))
    assert [d["decision_id"] for d in root_log["decisions"]] == ["d-041"], (
        f"the gate write did not land d-041 in {canonical}: {root_log}"
    )

    side_file = tmp_path / "run" / "artifacts" / "decision_log.json"
    assert not side_file.exists(), (
        f"the supported path created the fork-prone side file {side_file} — "
        "context-cost-spec.md section 2 promises nothing writes it"
    )

    # The canonical log is itself a valid decision_log artifact, so the audit
    # trail can be replayed straight back through the schema.
    validate_artifact("decision_log", root_log)

    # A ruling that lands after the gate write: re-write the SAME stage/status
    # carrying the extended log. The merge must append only the new id.
    extended = {
        **DOC_JUDGMENT_LOG,
        "decisions": DOC_JUDGMENT_LOG["decisions"] + [DOC_LATE_RULING],
    }
    write_checkpoint(
        tmp_path,
        "run",
        "research",
        "awaiting_human",
        {
            "research_brief": sample_artifact("research_brief"),
            "decision_log": extended,
        },
        pipeline_type="framework-smoke",
    )

    ids = [d["decision_id"] for d in
           json.loads(canonical.read_text(encoding="utf-8"))["decisions"]]
    assert ids == ["d-041", "d-042"], (
        f"re-writing the gate was not additive — expected d-041 then d-042 "
        f"exactly once each, got {ids}"
    )
    assert not side_file.exists()


if __name__ == "__main__":
    test_orphaned_artifact_decisions_are_absorbed()
    print("PASS — decision log cannot silently fork")
