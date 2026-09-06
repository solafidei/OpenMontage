"""Workstream D acceptance — the ledger rollout must cover EVERY episode pipeline.

These tests are deliberately dynamic: they discover pipelines from
`pipeline_defs/*.yaml` and directors from each manifest's own `required_skills`.
There is no allowlist and no hardcoded pipeline roster, so a 13th episode
pipeline added later FAILS here until its manifest criteria and its four
canonical ledger blocks are wired.

Scope note: the tree-wide `result.cost_usd or estimated_usd` guard lives in
`tests/contracts/test_agent_instruction_integrity.py`
(`test_no_or_estimated_fallback_survives_in_ledger_blocks`) and is not repeated
here. This file owns the other half of the drift guard: the pre-fix arming
formula.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_DEFS = REPO_ROOT / "pipeline_defs"
SKILLS_ROOT = REPO_ROOT / "skills"

# framework-smoke is the framework's own test pipeline (`tools_available: []`),
# deliberately excluded from the rollout.
NON_EPISODE_MANIFESTS = frozenset({"framework-smoke.yaml"})

# Sentinel floor — an empty or half-empty sweep would prove nothing. Raise this
# only alongside a manifest actually being deleted.
MIN_EPISODE_PIPELINES = 12

PAID_STAGE_CRITERION = (
    "an entry for every paid tool call made in this stage"
)
COMPOSE_CRITERION = "every entry in a terminal state"

# D0's four heading markers. The heading LEVEL and any section NUMBER follow
# each file's local style; only the SUFFIX is invariant, so every match below
# is a suffix match against the heading text.
GATE_SEED_MARKER = "Compute Budget And Seed The Cost Ledger"
GATE_ARM_MARKER = "On Approval — Arm the Tracker"
ASSET_MARKER = "Ledger Discipline For Every Paid Call"
COMPOSE_MARKER = "Ledger Round-Trip For The Render"

# C1's canonical arming formula, C3's booking marker, D0's compose entry.
ARMING_FORMULA = (
    "math.ceil(total_estimated_usd / (1 - tracker.reserve_pct) * 100) / 100 + 0.01"
)
BOOKING_MARKER = "NEVER substitute the estimate on failure"
COMPOSE_ENTRY = 'tracker.estimate("video_compose", "render'

# The pre-fix arming expression C1 replaced: arming the bare estimate leaves
# zero headroom against the reserve holdback.
PRE_FIX_ARMING = "or total_estimated_usd"

_HEADING = re.compile(r"^#{1,6}\s+(?P<text>.+?)\s*$")


def _episode_manifests() -> list[Path]:
    """Every episode pipeline manifest, discovered — never enumerated."""
    manifests = sorted(
        path
        for path in PIPELINE_DEFS.glob("*.yaml")
        if path.name not in NON_EPISODE_MANIFESTS
    )
    assert len(manifests) >= MIN_EPISODE_PIPELINES, (
        f"discovered only {len(manifests)} episode manifests in {PIPELINE_DEFS} — "
        "the sweep is broken, not the rollout"
    )
    return manifests


def _load(manifest: Path) -> dict:
    return yaml.safe_load(manifest.read_text(encoding="utf-8"))


def _stage_criteria(manifest_data: dict) -> list[tuple[str, list[str]]]:
    """Stage name -> success_criteria, in manifest (execution) order."""
    return [
        (stage["name"], list(stage.get("success_criteria") or []))
        for stage in manifest_data.get("stages", [])
    ]


def _resolve_skill(reference: str) -> Path | None:
    """`pipelines/foo/idea-director` -> the markdown file that carries it."""
    flat = SKILLS_ROOT / f"{reference}.md"
    if flat.is_file():
        return flat
    packaged = SKILLS_ROOT / reference / "SKILL.md"
    if packaged.is_file():
        return packaged
    return None


def _own_director_files(manifest_data: dict) -> list[Path]:
    """The pipeline's OWN directors — shared `meta/*` skills are excluded so a
    marker parked in a shared file can never satisfy a pipeline that lacks it."""
    references = list(manifest_data.get("required_skills") or [])
    own_dirs = {
        reference.rsplit("/", 1)[0]
        for reference in references
        if reference.startswith("pipelines/")
    }
    files: list[Path] = []
    for reference in references:
        if not any(reference.startswith(f"{own_dir}/") for own_dir in own_dirs):
            continue
        resolved = _resolve_skill(reference)
        if resolved is not None:
            files.append(resolved)
    return files


def _has_heading_ending(text: str, marker: str) -> bool:
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match and match.group("text").endswith(marker):
            return True
    return False


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def test_every_episode_pipeline_manifest_carries_cost_log_criteria() -> None:
    """`meta/checkpoint-protocol` Step 2 pulls `cost_snapshot()` in EVERY
    pipeline. A pipeline whose stages never require a schema-valid cost_log
    checkpoints `$0.00` against the config default for money actually spent."""
    for manifest in _episode_manifests():
        data = _load(manifest)
        stages = _stage_criteria(data)
        names = [name for name, _ in stages]
        assert "compose" in names, f"{manifest.name} has no compose stage"

        compose_index = names.index("compose")
        compose_criteria = stages[compose_index][1]
        assert any(COMPOSE_CRITERION in criterion for criterion in compose_criteria), (
            f"{manifest.name}: compose stage has no terminal-state cost_log "
            f"criterion (looking for {COMPOSE_CRITERION!r})"
        )

        paid_stages = [
            name
            for name, criteria in stages[:compose_index]
            if any(PAID_STAGE_CRITERION in criterion for criterion in criteria)
        ]
        assert paid_stages, (
            f"{manifest.name}: no pre-compose stage requires a cost_log entry "
            f"for every paid tool call (looking for {PAID_STAGE_CRITERION!r})"
        )

        if manifest.name == "character-animation.yaml":
            # Character design is a paid generative stage in its own right, and
            # it runs long before `assets` — both must book.
            for required in ("character_design", "assets"):
                assert required in paid_stages, (
                    f"{manifest.name}: the paid-stage cost_log criterion is "
                    f"missing from the {required!r} stage"
                )


def test_every_episode_pipeline_skillset_carries_the_four_ledger_markers() -> None:
    """D0's canon, per pipeline: one gate arms the tracker with C1's grossed-up
    formula, an asset director carries C3's booking block, and compose closes
    the round trip. Discovered through each manifest's own required_skills."""
    for manifest in _episode_manifests():
        data = _load(manifest)
        directors = _own_director_files(data)
        assert directors, f"{manifest.name}: no pipeline directors resolved"

        texts = {path: path.read_text(encoding="utf-8") for path in directors}

        gate_files = [
            path
            for path, text in texts.items()
            if _has_heading_ending(text, GATE_SEED_MARKER)
            or _has_heading_ending(text, GATE_ARM_MARKER)
        ]
        assert len(gate_files) == 1, (
            f"{manifest.name}: expected exactly one gate file carrying "
            f"{GATE_SEED_MARKER!r} or {GATE_ARM_MARKER!r}, found "
            f"{sorted(_rel(path) for path in gate_files)}"
        )
        gate = gate_files[0]
        assert ARMING_FORMULA in texts[gate], (
            f"{_rel(gate)} arms the tracker without C1's reserve gross-up"
        )

        asset_files = [
            path
            for path, text in texts.items()
            if _has_heading_ending(text, ASSET_MARKER)
            and BOOKING_MARKER in text
        ]
        assert asset_files, (
            f"{manifest.name}: no director carries a heading ending "
            f"{ASSET_MARKER!r} together with C3's {BOOKING_MARKER!r}"
        )

        compose_files = [
            path
            for path, text in texts.items()
            if _has_heading_ending(text, COMPOSE_MARKER) and COMPOSE_ENTRY in text
        ]
        assert compose_files, (
            f"{manifest.name}: no compose director carries a heading ending "
            f"{COMPOSE_MARKER!r} together with a {COMPOSE_ENTRY!r} entry"
        )


def test_no_pre_fix_arming_formula_anywhere() -> None:
    """C1's guard, extended tree-wide: `... or total_estimated_usd` arms the
    bare estimate, so the plan's final approved reservation always trips the
    budget guard. D's six new copies are the reason this sweeps every file."""
    offenders = [
        _rel(path)
        for path in sorted((SKILLS_ROOT / "pipelines").rglob("*.md"))
        if PRE_FIX_ARMING in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "pre-fix arming formula "
        f"({PRE_FIX_ARMING!r}) survives in: {offenders}"
    )
