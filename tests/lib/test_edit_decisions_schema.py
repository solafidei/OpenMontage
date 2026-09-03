"""Guards for the three additive edit_decisions properties (reel-batch R4/R5).

`provenance` and `polish` are typed on the cut — not side-mapped in
`metadata` — because nothing enforces that a metadata map covers every cut,
and that per-cut correspondence is exactly what the identity guarantee needs.
`metadata.identity_lock` is the deliberate exception: a project-level arming
switch, not a per-clip label.

The extension is a monotone widening, so the first test here pins the property
that matters most: an artifact written before the change still validates after
it. Revert any of the schema additions and the corresponding test below fails.
"""

import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.checkpoint import (  # noqa: E402
    init_project,
    read_checkpoint,
    write_checkpoint,
)
from schemas.artifacts import validate_artifact  # noqa: E402


def _pre_change_artifact() -> dict:
    """An edit_decisions artifact as it could have been written before #39.

    Exercises the full pre-change cut property set (there are no
    edit_decisions fixture files to point at, so the baseline is spelled out
    here) plus the root-level blocks a shipped pipeline carries.
    """
    return {
        "version": "1.0",
        "render_runtime": "ffmpeg",
        "composition_mode": "templated",
        "cuts": [
            {
                "id": "cut-1",
                "source": "asset-1",
                "in_seconds": 0,
                "out_seconds": 4.5,
                "speed": 1.0,
                "layer": "primary",
                "transform": {
                    "scale": 1.0,
                    "position": "center",
                    "animation": "ken-burns-slow-zoom",
                    "crop": {"x": 0, "y": 0, "width": 1080, "height": 1920},
                },
                "transition_in": "fade",
                "transition_out": "dissolve",
                "transition_duration": 0.25,
                "backgroundColor": "#000000",
                "reason": "opening hold on the lift",
            }
        ],
        "metadata": {"compose_target": "instagram_reels"},
    }


def test_pre_change_artifact_still_validates():
    # Backward compatibility: adding optional properties widens the schema,
    # so every artifact valid before the change stays valid after it.
    validate_artifact("edit_decisions", _pre_change_artifact())


def test_render_runtime_stays_required():
    # The one property the existing suite pins on this schema
    # (tests/tools/test_hyperframes_compose.py:504). Widening must not have
    # loosened it.
    artifact = _pre_change_artifact()
    del artifact["render_runtime"]
    with pytest.raises(ValidationError):
        validate_artifact("edit_decisions", artifact)


@pytest.mark.parametrize("declared", ["operator_footage", "ai_generated"])
def test_provenance_accepts_exactly_the_two_declared_origins(declared):
    artifact = _pre_change_artifact()
    artifact["cuts"][0]["provenance"] = declared
    validate_artifact("edit_decisions", artifact)


@pytest.mark.parametrize("misspelled", ["restyled", "OPERATOR_FOOTAGE", "generated", ""])
def test_provenance_enum_rejects_anything_else(misspelled):
    artifact = _pre_change_artifact()
    artifact["cuts"][0]["provenance"] = misspelled
    with pytest.raises(ValidationError):
        validate_artifact("edit_decisions", artifact)


def test_polish_block_validates_on_the_cut():
    artifact = _pre_change_artifact()
    artifact["cuts"][0]["polish"] = {
        "punch_in": 1.12,
        "speed_ramp": 0.85,
        "transition_out": "whip",
    }
    validate_artifact("edit_decisions", artifact)


def test_identity_lock_validates_on_root_metadata():
    artifact = _pre_change_artifact()
    artifact["metadata"]["identity_lock"] = True
    validate_artifact("edit_decisions", artifact)

    artifact["metadata"]["identity_lock"] = "yes"
    with pytest.raises(ValidationError):
        validate_artifact("edit_decisions", artifact)


def _two_cut_reel_artifact() -> dict:
    """The demoable case: one operator cut with a punch-in, one generated."""
    artifact = _pre_change_artifact()
    artifact["metadata"]["identity_lock"] = True
    artifact["cuts"][0]["provenance"] = "operator_footage"
    artifact["cuts"][0]["polish"] = {"punch_in": 1.15}
    artifact["cuts"].append(
        {
            "id": "reel_1-cut-2",
            "source": "asset-2",
            "in_seconds": 0,
            "out_seconds": 0.4,
            "provenance": "ai_generated",
            "polish": {"transition_out": "flash"},
        }
    )
    return artifact


def test_two_cut_mixed_provenance_artifact_validates():
    validate_artifact("edit_decisions", _two_cut_reel_artifact())


def test_two_cut_artifact_rejected_when_a_provenance_is_misspelled():
    artifact = _two_cut_reel_artifact()
    artifact["cuts"][1]["provenance"] = "ai-generated"
    with pytest.raises(ValidationError):
        validate_artifact("edit_decisions", artifact)


def test_polished_cuts_round_trip_through_write_checkpoint(tmp_path):
    # The schema is enforced at checkpoint write time (lib/checkpoint.py), so
    # the new fields must survive the supported persistence path, not just a
    # direct validate_artifact call.
    init_project(
        "reel-run",
        title="Reel Run",
        pipeline_type="cinematic",
        pipeline_dir=tmp_path,
    )

    write_checkpoint(
        tmp_path,
        "reel-run",
        "edit",
        "in_progress",
        {"edit_decisions": _two_cut_reel_artifact()},
        pipeline_type="cinematic",
    )

    stored = read_checkpoint(tmp_path, "reel-run", "edit")
    cuts = stored["artifacts"]["edit_decisions"]["cuts"]
    assert [c["provenance"] for c in cuts] == ["operator_footage", "ai_generated"]
    assert cuts[0]["polish"]["punch_in"] == 1.15
    assert cuts[1]["polish"]["transition_out"] == "flash"
    assert stored["artifacts"]["edit_decisions"]["metadata"]["identity_lock"] is True
