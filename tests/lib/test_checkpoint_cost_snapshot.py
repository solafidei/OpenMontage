import json

import pytest
from tests.contracts.test_phase0_contracts import sample_artifact

from lib.checkpoint import (
    CheckpointValidationError,
    get_completed_stages,
    get_latest_checkpoint,
    get_next_stage,
    init_project,
    read_checkpoint,
    write_checkpoint,
)
from tools.cost_tracker import CostTracker

LEGACY_COST_SNAPSHOT = {"spent_usd": 0.28, "approved_budget_usd": 2.0}


def _set_cost_snapshot(value):
    """A corruption that plants `value` at checkpoint["cost_snapshot"]."""
    def _mutate(data: dict) -> None:
        data["cost_snapshot"] = value
    return _mutate


# Every corruption the legacy tolerance must refuse to swallow — i.e. every
# checkpoint that is NOT the genuine legacy cost_snapshot shape. Shared by all
# THREE call sites of _validate_tolerating_legacy_cost_snapshot
# (read_checkpoint, get_latest_checkpoint, _enforce_stage_prerequisites) so a
# drift in one cannot hide; never re-copied.
#
# Two families live here:
#   1. Failures outside cost_snapshot, which the `exc.field != "cost_snapshot"`
#      guard rejects (both branches of it: field=None and a named field).
#   2. Failures AT cost_snapshot whose value is not the legacy shape. The guard
#      alone waves these through — exc.field derives from absolute_path[0], so
#      it says "cost_snapshot" for a bare string, a null, or a non-numeric
#      *_usd figure just as loudly as for the extra-key legacy object. Only
#      _is_legacy_cost_snapshot separates them, and these are the values that
#      reach `cost = cp["cost_snapshot"]` in backlot/state.py and
#      `float(cost_snapshot.get("total_spent_usd", 0.0) or 0.0)` in
#      CostTracker.reconstruct_from_snapshot.
NON_COST_SNAPSHOT_CORRUPTIONS = [
    # --- family 1: the violation is not attributable to cost_snapshot ---
    # additionalProperties violation at the root: absolute_path is empty,
    # so the tolerance sees field=None — must still raise.
    pytest.param(
        lambda d: d.__setitem__("rogue_top_level_key", "smuggled"),
        id="rogue-top-level-key-field-none",
    ),
    # A named property with the wrong type: absolute_path is
    # ['human_approved'], so field == "human_approved" — a violation
    # attributable to a specific non-cost_snapshot property must also
    # still raise.
    pytest.param(
        lambda d: d.__setitem__("human_approved", "yes"),
        id="wrong-typed-named-field",
    ),
    # --- family 2: field == "cost_snapshot", but the value is corruption ---
    # Not an object at all. A bare string lands in the Backlot state dict via
    # `cost = cp["cost_snapshot"]` and has no .get() for the cost meter.
    pytest.param(_set_cost_snapshot("n/a"), id="cost-snapshot-bare-string"),
    # Explicit null — same path, same non-dict landing.
    pytest.param(_set_cost_snapshot(None), id="cost-snapshot-null"),
    # A list is an object-shaped near-miss that still has no money keys.
    pytest.param(_set_cost_snapshot([]), id="cost-snapshot-list"),
    # Money as a numeric-looking string: float() would survive this one, which
    # is exactly why it must not be tolerated silently.
    pytest.param(
        _set_cost_snapshot({"total_spent_usd": "12.50"}),
        id="cost-snapshot-money-numeric-string",
    ),
    # Money as a non-numeric string: float("lots") raises ValueError inside
    # CostTracker.reconstruct_from_snapshot's money-recovery path.
    pytest.param(
        _set_cost_snapshot({"total_spent_usd": "lots"}),
        id="cost-snapshot-money-unparseable-string",
    ),
    # Money as a nested structure.
    pytest.param(
        _set_cost_snapshot({"total_spent_usd": {"deep": [1, 2, 3]}}),
        id="cost-snapshot-money-nested-object",
    ),
    # Booleans are the trap: isinstance(True, int) is True in Python, so a
    # naive numeric check accepts a boolean money figure as 1.0.
    pytest.param(
        _set_cost_snapshot({"spent_usd": True, "approved_budget_usd": 2.0}),
        id="cost-snapshot-boolean-money",
    ),
    # NaN survives json round-tripping and every isinstance check, but it is
    # not a money figure.
    pytest.param(
        _set_cost_snapshot({"spent_usd": float("nan")}),
        id="cost-snapshot-nan-money",
    ),
]


def _script_artifact() -> dict:
    return {
        "version": "1.0",
        "title": "Smoke",
        "total_duration_seconds": 1,
        "sections": [
            {
                "id": "s1",
                "text": "One second.",
                "start_seconds": 0,
                "end_seconds": 1,
            }
        ],
    }


def _write_legacy_research_checkpoint(tmp_path, *, completed: bool = False):
    """Init framework-smoke, write research, then rewrite the file on disk with
    the legacy cost_snapshot shape (bypassing write_checkpoint's correct
    rejection of it). Returns the checkpoint path."""
    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )
    path = write_checkpoint(
        tmp_path,
        "run",
        "research",
        "awaiting_human",
        {"research_brief": sample_artifact("research_brief")},
        pipeline_type="framework-smoke",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cost_snapshot"] = dict(LEGACY_COST_SNAPSHOT)
    if completed:
        data["status"] = "completed"
        data["human_approved"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_rogue_cost_snapshot_key_rejected(tmp_path) -> None:
    """A hand-invented cost_snapshot key (the legacy spent_usd/approved_budget_usd
    shape) must fail schema validation, not pass silently."""
    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )

    with pytest.raises(CheckpointValidationError, match="spent_usd"):
        write_checkpoint(
            tmp_path,
            "run",
            "research",
            "awaiting_human",
            {"research_brief": sample_artifact("research_brief")},
            pipeline_type="framework-smoke",
            cost_snapshot={"spent_usd": 1.0},
        )


def test_tracker_cost_snapshot_validates(tmp_path) -> None:
    """The exact dict CostTracker.cost_snapshot() emits, plus budget_total_usd,
    must validate against the checkpoint schema's cost_snapshot object."""
    tracker = CostTracker(budget_total_usd=15.0)
    tracker.approve_tool("flux_fal")
    entry_id = tracker.estimate("flux_fal", "image_gen", 0.05)
    tracker.reserve(entry_id)
    tracker.reconcile(entry_id, 0.048)

    cost_snapshot = tracker.cost_snapshot()
    cost_snapshot["budget_total_usd"] = tracker.budget_total_usd

    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )
    path = write_checkpoint(
        tmp_path,
        "run",
        "research",
        "awaiting_human",
        {"research_brief": sample_artifact("research_brief")},
        pipeline_type="framework-smoke",
        cost_snapshot=cost_snapshot,
    )
    assert path.exists()


def test_read_checkpoint_tolerates_legacy_cost_snapshot(tmp_path) -> None:
    """A checkpoint written under the old, looser cost_snapshot shape
    (spent_usd/approved_budget_usd, now rejected at write time) must still
    be readable — write-time schema tightening must not break resume or
    inspection of already-finished projects."""
    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )
    path = write_checkpoint(
        tmp_path,
        "run",
        "research",
        "awaiting_human",
        {"research_brief": sample_artifact("research_brief")},
        pipeline_type="framework-smoke",
    )
    # Rewrite the file on disk with the legacy cost_snapshot shape, bypassing
    # write_checkpoint's (correct) rejection of it.
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cost_snapshot"] = {"spent_usd": 0.28, "approved_budget_usd": 2.0}
    path.write_text(json.dumps(data), encoding="utf-8")

    checkpoint = read_checkpoint(tmp_path, "run", "research")
    assert checkpoint["cost_snapshot"] == {
        "spent_usd": 0.28,
        "approved_budget_usd": 2.0,
    }


@pytest.mark.parametrize("corrupt", NON_COST_SNAPSHOT_CORRUPTIONS)
def test_read_checkpoint_still_raises_on_non_cost_snapshot_corruption(
    tmp_path, corrupt
) -> None:
    """The legacy tolerance waives exactly one shape, and nothing else.

    Both branches of the field guard still fail loudly — a violation with no
    attributable field (rogue top-level key => field=None) and one attributed
    to a different named property (wrong-typed human_approved =>
    field="human_approved") — AND so does every cost_snapshot value that is
    not the legacy shape (a non-object, or a *_usd figure that is not a real
    number), even though exc.field says "cost_snapshot" for those too. (A
    forged-but-valid *stage value* is a different animal: the schema types
    stage as a plain string and the Python-side check only rejects names
    outside the pipeline's stage list, so it is not what this test covers.)"""
    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )
    path = write_checkpoint(
        tmp_path,
        "run",
        "research",
        "awaiting_human",
        {"research_brief": sample_artifact("research_brief")},
        pipeline_type="framework-smoke",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    corrupt(data)
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CheckpointValidationError):
        read_checkpoint(tmp_path, "run", "research")


def test_get_latest_checkpoint_tolerates_legacy_cost_snapshot(tmp_path) -> None:
    """The resume/inspect entry point carries its own copy of the legacy
    cost_snapshot tolerance (shared helper since A1). A legacy checkpoint must
    come back as-is, not raise."""
    _write_legacy_research_checkpoint(tmp_path)

    checkpoint = get_latest_checkpoint(tmp_path, "run")

    assert checkpoint is not None
    assert checkpoint["stage"] == "research"
    assert checkpoint["cost_snapshot"] == LEGACY_COST_SNAPSHOT


@pytest.mark.parametrize("corrupt", NON_COST_SNAPSHOT_CORRUPTIONS)
def test_get_latest_checkpoint_still_raises_on_non_cost_snapshot_corruption(
    tmp_path, corrupt
) -> None:
    """get_latest_checkpoint's tolerance is scoped exactly as read_checkpoint's
    — same single helper, same shared list: neither the field=None branch, nor
    the wrong-typed named-field branch, nor a cost_snapshot that is not the
    legacy money-object shape may be swallowed."""
    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )
    path = write_checkpoint(
        tmp_path,
        "run",
        "research",
        "awaiting_human",
        {"research_brief": sample_artifact("research_brief")},
        pipeline_type="framework-smoke",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    corrupt(data)
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CheckpointValidationError):
        get_latest_checkpoint(tmp_path, "run")


def test_legacy_project_resumes_end_to_end(tmp_path) -> None:
    """The MAJOR finding end to end: the read path telling the orchestrator to
    proceed AND the write path then accepting the work, against the *same*
    legacy fixture. Before the shared tolerance reached
    _enforce_stage_prerequisites, these two halves disagreed and a legacy
    project deadlocked at its next stage."""
    _write_legacy_research_checkpoint(tmp_path, completed=True)

    # 2. What the orchestrator reads on resume.
    latest = get_latest_checkpoint(tmp_path, "run")
    assert latest is not None
    assert latest["stage"] == "research"
    assert get_completed_stages(
        tmp_path, "run", pipeline_type="framework-smoke"
    ) == ["research"]
    assert (
        get_next_stage(tmp_path, "run", pipeline_type="framework-smoke") == "script"
    )

    # 3. The write the orchestrator just directed — deadlocked with
    #    PREREQUISITE VIOLATION before the tolerance was shared.
    script_path = write_checkpoint(
        tmp_path,
        "run",
        "script",
        "completed",
        {"script": _script_artifact()},
        pipeline_type="framework-smoke",
        human_approved=True,
    )
    assert script_path.exists()

    # 4. Post-conditions: pipeline complete, history untouched.
    assert get_next_stage(tmp_path, "run", pipeline_type="framework-smoke") is None
    assert (
        read_checkpoint(tmp_path, "run", "research")["cost_snapshot"]
        == LEGACY_COST_SNAPSHOT
    )
