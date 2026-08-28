import json

import pytest
from tests.contracts.test_phase0_contracts import sample_artifact

from lib.checkpoint import (
    CheckpointValidationError,
    init_project,
    read_checkpoint,
    write_checkpoint,
)
from tools.cost_tracker import CostTracker


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


def test_read_checkpoint_still_raises_on_non_cost_snapshot_corruption(tmp_path) -> None:
    """The legacy tolerance is scoped to cost_snapshot. Any other invariant —
    here a forged stage — must still fail loudly rather than resume silently."""
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
    data["rogue_top_level_key"] = "smuggled"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CheckpointValidationError):
        read_checkpoint(tmp_path, "run", "research")
