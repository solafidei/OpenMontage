"""The batch data model: a spine plus a reel_plan, recombined per reel.

`edit_decisions` carries exactly one `audio.music` object with a single `asset_id`
and exactly one `subtitles` object, so it structurally cannot hold five reels. The
`edit` stage therefore emits two artifacts and `compose` recombines them in memory,
once per reel. These tests police the recombination and the registration that makes
`reel_plan` a validated artifact rather than an unchecked blob.
"""

from __future__ import annotations

import pytest
from tests.contracts.test_phase0_contracts import sample_artifact

from lib.checkpoint import init_project, read_checkpoint, write_checkpoint
from lib.reel_plan import (
    ReelPlanError,
    entry_for,
    materialise,
    partition_is_total,
    reel_ids,
)
from schemas.artifacts import ARTIFACT_NAMES, validate_artifact

REELS = 5
CUTS = 5


def _spine() -> dict:
    """A five-reel batch spine: shared look, one flat cuts[] with prefixed ids."""
    cuts = []
    for r in range(1, REELS + 1):
        for c in range(1, CUTS + 1):
            cuts.append({
                "id": f"reel_{r:02d}-{c:02d}",
                "source": f"asset_reel_{r:02d}_{c:02d}",
                "in_seconds": 0.0,
                "out_seconds": 2.0,
                "provenance": "operator_footage",
                "polish": {"punch_in": 1.12},
            })
    return {
        "version": "1.0",
        "render_runtime": "ffmpeg",
        "renderer_family": "documentary-montage",
        "cuts": cuts,
        "metadata": {
            "pipeline": "reel-batch",
            "identity_lock": True,
            "batch_look": {"grade": "talking_head_standard", "sharpen": "sharpen_light"},
        },
    }


def _plan() -> dict:
    return {
        "version": "1.0",
        "reels": [
            {
                "reel_id": f"reel_{r:02d}",
                "track_id": f"track_{r:02d}",
                "music_asset_id": f"asset_track_{r:02d}",
                "subtitle_source": f"asset_reel_{r:02d}_captions_json",
                "hook": f"HOOK {r}",
                "cut_ids": [f"reel_{r:02d}-{c:02d}" for c in range(1, CUTS + 1)],
            }
            for r in range(1, REELS + 1)
        ],
    }


# The manifest gates `idea` and `scene_plan`, and `write_checkpoint` enforces the
# prerequisite chain, so a test that writes straight to `edit` is refused. Walk the
# four upstream stages first — cheaply, with sample artifacts.
_UPSTREAM = [
    ("idea", "brief", True),
    ("script", "script", False),
    ("scene_plan", "scene_plan", True),
    ("assets", "asset_manifest", False),
]


def _project(tmp_path):
    init_project("b", title="B", pipeline_type="reel-batch", pipeline_dir=tmp_path)
    for stage, artifact, gated in _UPSTREAM:
        write_checkpoint(
            tmp_path, "b", stage, "completed",
            {artifact: sample_artifact(artifact)},
            pipeline_type="reel-batch",
            human_approval_required=gated,
            human_approved=gated,
        )
    return tmp_path


# --- registration -------------------------------------------------------


def test_reel_plan_is_a_registered_artifact() -> None:
    assert "reel_plan" in ARTIFACT_NAMES
    validate_artifact("reel_plan", _plan())


def test_an_unregistered_artifact_name_is_silently_unvalidated(tmp_path) -> None:
    """Why registration is the thing that makes an artifact real.

    `_validate_artifacts_for_stage` does `if artifact_name not in ARTIFACT_NAMES:
    continue`, so an unregistered name is skipped rather than rejected. This test
    fails the day someone removes `reel_plan` from ARTIFACT_NAMES believing the
    checkpoint would still catch a malformed one — it would not.
    """
    _project(tmp_path)
    garbage = {"total": "nonsense"}

    # An unknown name rides straight through.
    write_checkpoint(
        tmp_path, "b", "edit", "completed",
        {"edit_decisions": _spine(), "not_a_registered_artifact": garbage},
        pipeline_type="reel-batch",
    )

    # The registered name does not.
    with pytest.raises(Exception):
        write_checkpoint(
            tmp_path, "b", "edit", "completed",
            {"edit_decisions": _spine(), "reel_plan": garbage},
            pipeline_type="reel-batch",
        )


def test_reel_plan_rejects_an_entry_missing_its_track(tmp_path) -> None:
    plan = _plan()
    del plan["reels"][2]["music_asset_id"]
    with pytest.raises(Exception):
        validate_artifact("reel_plan", plan)


# --- round trip ---------------------------------------------------------


def test_five_reel_spine_and_plan_round_trip_through_the_edit_checkpoint(tmp_path) -> None:
    _project(tmp_path)
    write_checkpoint(
        tmp_path, "b", "edit", "completed",
        {"edit_decisions": _spine(), "reel_plan": _plan()},
        pipeline_type="reel-batch",
    )
    restored = read_checkpoint(tmp_path, "b", "edit")
    assert reel_ids(restored["artifacts"]["reel_plan"]) == [
        "reel_01", "reel_02", "reel_03", "reel_04", "reel_05"
    ]
    assert len(restored["artifacts"]["edit_decisions"]["cuts"]) == REELS * CUTS


# --- materialisation ----------------------------------------------------


@pytest.mark.parametrize("reel_id", [f"reel_{r:02d}" for r in range(1, REELS + 1)])
def test_each_reel_materialises_into_valid_edit_decisions(reel_id: str) -> None:
    spine, plan = _spine(), _plan()
    reel = materialise(spine, entry_for(plan, reel_id))

    validate_artifact("edit_decisions", reel)
    assert len(reel["cuts"]) == CUTS
    assert all(c["id"].startswith(f"{reel_id}-") for c in reel["cuts"])
    # The single-valued fields the spine could not hold, now filled per reel.
    assert reel["audio"]["music"]["asset_id"] == f"asset_track_{reel_id[-2:]}"
    assert reel["subtitles"]["source"] == f"asset_{reel_id}_captions_json"
    # The shared look survives the filter.
    assert reel["metadata"]["batch_look"] == spine["metadata"]["batch_look"]
    assert reel["renderer_family"] == "documentary-montage"


def test_cuts_come_out_in_reel_order_not_spine_order() -> None:
    spine, plan = _spine(), _plan()
    entry = entry_for(plan, "reel_02")
    entry["cut_ids"] = list(reversed(entry["cut_ids"]))
    reel = materialise(spine, entry)
    assert [c["id"] for c in reel["cuts"]] == entry["cut_ids"]


def test_a_plan_naming_a_cut_the_spine_lacks_raises() -> None:
    """Rendering a short reel silently is the failure this prevents."""
    spine, plan = _spine(), _plan()
    entry = entry_for(plan, "reel_03")
    entry["cut_ids"].append("reel_03-99")
    with pytest.raises(ReelPlanError, match="reel_03-99"):
        materialise(spine, entry)


def test_provenance_survives_materialisation() -> None:
    """The identity gate reads cut['provenance'], not metadata.identity_lock."""
    reel = materialise(_spine(), entry_for(_plan(), "reel_01"))
    assert all(c["provenance"] == "operator_footage" for c in reel["cuts"])
    assert all("polish" in c for c in reel["cuts"])


def test_partition_catches_a_cut_claimed_twice() -> None:
    spine, plan = _spine(), _plan()
    plan["reels"][1]["cut_ids"][0] = "reel_01-01"
    with pytest.raises(ReelPlanError, match="more than one reel"):
        partition_is_total(spine, plan)


def test_partition_catches_a_cut_in_no_reel() -> None:
    spine, plan = _spine(), _plan()
    plan["reels"][4]["cut_ids"].pop()
    with pytest.raises(ReelPlanError, match="no reel_plan entry"):
        partition_is_total(spine, plan)


def test_a_clean_batch_partitions() -> None:
    partition_is_total(_spine(), _plan())


# --- render_report and resume ------------------------------------------


def _output(reel_id: str) -> dict:
    return {
        "path": f"projects/b/renders/{reel_id}.mp4",
        "format": "mp4",
        "resolution": "1080x1920",
        "duration_seconds": 9.88,
        "platform_target": "instagram_reels",
    }


def test_render_report_carries_one_output_per_reel_with_platform_target() -> None:
    report = {
        "version": "1.0",
        "outputs": [_output(r) for r in reel_ids(_plan())],
    }
    validate_artifact("render_report", report)
    assert len(report["outputs"]) == REELS
    assert all(o["platform_target"] == "instagram_reels" for o in report["outputs"])
    assert all(o["resolution"] == "1080x1920" for o in report["outputs"])


def test_aborting_after_reel_three_resumes_on_four_and_five(tmp_path) -> None:
    """A mid-batch abort must cost the two remaining reels, not the three done."""
    _project(tmp_path)
    plan = _plan()
    done = ["reel_01", "reel_02", "reel_03"]

    write_checkpoint(
        tmp_path, "b", "compose", "in_progress",
        {"edit_decisions": _spine(), "reel_plan": plan},
        pipeline_type="reel-batch",
        metadata={"partial_progress": {
            "completed_reel_ids": done,
            "outputs": [_output(r) for r in done],
        }},
    )

    latest = read_checkpoint(tmp_path, "b", "compose")
    progress = latest["metadata"]["partial_progress"]
    remaining = [r for r in reel_ids(plan) if r not in progress["completed_reel_ids"]]

    assert remaining == ["reel_04", "reel_05"]
    # The resumed run rebuilds outputs[] from recorded plus new, not from new alone.
    rebuilt = progress["outputs"] + [_output(r) for r in remaining]
    validate_artifact("render_report", {"version": "1.0", "outputs": rebuilt})
    assert [o["path"].rsplit("/", 1)[-1] for o in rebuilt] == [
        f"{r}.mp4" for r in reel_ids(plan)
    ]
