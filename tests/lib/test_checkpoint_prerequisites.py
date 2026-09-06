import json

import pytest
from tests.contracts.test_phase0_contracts import sample_artifact

from lib.checkpoint import (
    CheckpointValidationError,
    init_project,
    read_checkpoint,
    write_checkpoint,
)

# The prerequisite WRITE gate validates predecessors through the SAME shared
# helper the read paths use (_validate_tolerating_legacy_cost_snapshot), so it
# is policed by the same corruption list — imported, never re-copied. A third
# copy is exactly the drift A1's one-definition rule exists to prevent: while
# this test hardcoded only the field=None shape, a widened tolerance let the
# write gate accept a wrong-typed human_approved and stayed green.
from tests.lib.test_checkpoint_cost_snapshot import NON_COST_SNAPSHOT_CORRUPTIONS


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


def test_later_stage_cannot_skip_a_missing_predecessor(tmp_path) -> None:
    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )

    with pytest.raises(CheckpointValidationError, match="PREREQUISITE VIOLATION"):
        write_checkpoint(
            tmp_path,
            "run",
            "script",
            "completed",
            {"script": _script_artifact()},
            pipeline_type="framework-smoke",
            human_approved=True,
        )


def test_later_stage_rejects_unapproved_gated_predecessor(tmp_path) -> None:
    project_dir = init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )
    predecessor_path = write_checkpoint(
        tmp_path,
        "run",
        "research",
        "awaiting_human",
        {"research_brief": sample_artifact("research_brief")},
        pipeline_type="framework-smoke",
    )
    predecessor = json.loads(predecessor_path.read_text(encoding="utf-8"))
    predecessor["status"] = "completed"
    predecessor["human_approved"] = False
    predecessor_path.write_text(json.dumps(predecessor), encoding="utf-8")

    with pytest.raises(CheckpointValidationError, match="completed without required approval"):
        write_checkpoint(
            tmp_path,
            "run",
            "script",
            "completed",
            {"script": _script_artifact()},
            pipeline_type="framework-smoke",
            human_approved=True,
        )


def test_malformed_predecessor_cannot_forge_completion(tmp_path) -> None:
    project_dir = init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )
    (project_dir / "checkpoint_research.json").write_text(
        json.dumps({"status": "completed", "human_approved": True}),
        encoding="utf-8",
    )

    with pytest.raises(CheckpointValidationError, match="incomplete or missing"):
        write_checkpoint(
            tmp_path,
            "run",
            "script",
            "completed",
            {"script": _script_artifact()},
            pipeline_type="framework-smoke",
            human_approved=True,
        )


def test_in_progress_heartbeat_is_not_blocked_by_prerequisites(tmp_path) -> None:
    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )

    path = write_checkpoint(
        tmp_path,
        "run",
        "script",
        "in_progress",
        {},
        pipeline_type="framework-smoke",
    )

    assert path.exists()


def test_unknown_style_playbook_fails_before_project_creation(tmp_path) -> None:
    with pytest.raises(CheckpointValidationError, match="style_playbook"):
        init_project(
            "run",
            title="Run",
            pipeline_type="framework-smoke",
            pipeline_dir=tmp_path,
            style_playbook="does-not-exist",
        )

    assert not (tmp_path / "run").exists()


def test_marker_derived_unknown_playbook_blocks_later_writes(tmp_path) -> None:
    project_dir = tmp_path / "run"
    project_dir.mkdir()
    (project_dir / "project.json").write_text(
        json.dumps({
            "version": "1.0",
            "project_id": "run",
            "pipeline_type": "framework-smoke",
            "style_playbook": "does-not-exist",
        }),
        encoding="utf-8",
    )

    with pytest.raises(CheckpointValidationError, match="style_playbook"):
        write_checkpoint(tmp_path, "run", "research", "in_progress", {})


def _legacy_predecessor(tmp_path, mutate) -> None:
    """Write a research checkpoint, then hand-rewrite it on disk.

    ``mutate`` receives the loaded checkpoint dict and edits it in place.
    """
    init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )
    predecessor_path = write_checkpoint(
        tmp_path,
        "run",
        "research",
        "awaiting_human",
        {"research_brief": sample_artifact("research_brief")},
        pipeline_type="framework-smoke",
    )
    data = json.loads(predecessor_path.read_text(encoding="utf-8"))
    data["status"] = "completed"
    data["human_approved"] = True
    mutate(data)
    predecessor_path.write_text(json.dumps(data), encoding="utf-8")


def test_prerequisites_tolerate_legacy_cost_snapshot_on_predecessor(tmp_path) -> None:
    """A legacy cost_snapshot on a predecessor must not deadlock the pipeline.

    The read paths already tolerate the pre-schema-closure cost_snapshot shape;
    the prerequisite check must agree, or a legacy project reads fine and can
    never advance.
    """
    def _inject(data: dict) -> None:
        data["cost_snapshot"] = {"spent_usd": 0.28, "approved_budget_usd": 2.0}

    _legacy_predecessor(tmp_path, _inject)

    path = write_checkpoint(
        tmp_path,
        "run",
        "script",
        "awaiting_human",
        {"script": _script_artifact()},
        pipeline_type="framework-smoke",
    )

    assert path.exists()

    predecessor = read_checkpoint(tmp_path, "run", "research")
    assert predecessor is not None
    assert predecessor["cost_snapshot"] == {
        "spent_usd": 0.28,
        "approved_budget_usd": 2.0,
    }


@pytest.mark.parametrize("corrupt", NON_COST_SNAPSHOT_CORRUPTIONS)
def test_prerequisites_still_reject_non_cost_snapshot_predecessor_corruption(
    tmp_path, corrupt
) -> None:
    """The tolerance is scoped to the legacy cost_snapshot SHAPE — nothing else.

    Parametrized over the shared list so the write gate is policed identically
    to read_checkpoint and get_latest_checkpoint. Every family matters here:
    the field=None shape (rogue top-level key); the wrong-typed named field
    (human_approved="yes"), which a widened tolerance would wave through as a
    truthy approval — a forged human gate; and a cost_snapshot that is not the
    legacy money object (a bare string, a null, a non-numeric *_usd), which
    the field guard alone cannot tell apart from real history and which would
    otherwise be counted as a COMPLETE predecessor and then handed to the
    Backlot cost meter and CostTracker.reconstruct_from_snapshot as-is.
    """
    _legacy_predecessor(tmp_path, corrupt)

    with pytest.raises(CheckpointValidationError, match="PREREQUISITE VIOLATION") as exc:
        write_checkpoint(
            tmp_path,
            "run",
            "script",
            "awaiting_human",
            {"script": _script_artifact()},
            pipeline_type="framework-smoke",
        )

    assert "research" in str(exc.value)
