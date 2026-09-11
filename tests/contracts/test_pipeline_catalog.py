"""Every shipped pipeline manifest must actually load.

`lib.checkpoint` degrades gracefully when a manifest cannot be parsed:
`get_pipeline_stages()` falls back to the canonical STAGES list and
`_stage_requires_approval()` returns None so the caller's own flag wins. That
is the right behaviour for a corrupt user manifest, but it means a manifest
shipped *in this repo* that fails its schema is silently ignored rather than
loudly rejected — the pipeline then runs against the wrong stage order and
without its declared approval gates.

Existing manifest coverage names individual pipelines (talking-head,
framework-smoke, animated-explainer, documentary-montage), so a manifest that
no test happens to name is never loaded. These tests iterate the directory.
"""

from pathlib import Path

import pytest
import yaml

from lib.checkpoint import _stage_requires_approval, get_pipeline_stages
from lib.pipeline_loader import load_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_DEFS = REPO_ROOT / "pipeline_defs"

PIPELINE_NAMES = sorted(p.stem for p in PIPELINE_DEFS.glob("*.yaml"))


def _declared_stages(name: str) -> list[str]:
    raw = yaml.safe_load((PIPELINE_DEFS / f"{name}.yaml").read_text(encoding="utf-8"))
    return [stage["name"] for stage in raw["stages"]]


def test_catalog_is_not_empty() -> None:
    assert PIPELINE_NAMES, "no pipeline manifests found"


@pytest.mark.parametrize("name", PIPELINE_NAMES)
def test_shipped_manifest_validates(name: str) -> None:
    """Regression: screen-demo.yaml carried a `production_modes` block the
    manifest schema did not allow, so the whole manifest failed to load."""
    manifest = load_pipeline(name)
    assert manifest["stages"]


@pytest.mark.parametrize("name", PIPELINE_NAMES)
def test_effective_stage_order_is_the_declared_one(name: str) -> None:
    """A manifest that silently falls back gets the canonical stage list.

    For screen-demo that inserted `research` and `proposal` ahead of its real
    first stage, so the prerequisite check rejected the opening checkpoint of
    every run with PREREQUISITE VIOLATION.
    """
    assert get_pipeline_stages(name) == _declared_stages(name)


@pytest.mark.parametrize("name", PIPELINE_NAMES)
def test_declared_approval_gates_are_enforceable(name: str) -> None:
    """AGENT_GUIDE.md: the manifest's human_approval_default is binding.

    `_stage_requires_approval` returning None means the caller's own flag wins,
    which is exactly the fail-open the gate is supposed to prevent.
    """
    raw = yaml.safe_load((PIPELINE_DEFS / f"{name}.yaml").read_text(encoding="utf-8"))

    for stage in raw["stages"]:
        if "human_approval_default" not in stage:
            continue
        resolved = _stage_requires_approval(name, stage["name"])
        assert resolved == stage["human_approval_default"], (
            f"{name}.{stage['name']}: manifest declares "
            f"{stage['human_approval_default']} but the checkpoint writer "
            f"resolves {resolved}"
        )


def test_reel_batch_wall_time_covers_a_cold_index_sitting() -> None:
    """20 min was below the branch's own measured cold-index time (1171.8s,
    ~19.5 min, decision #11) with zero room left for idea/script/scene/asset/
    edit/compose/publish stacked on top of indexing alone — a healthy first
    sitting was told to stop and escalate. Raised to ~45 so it isn't."""
    raw = yaml.safe_load((PIPELINE_DEFS / "reel-batch.yaml").read_text(encoding="utf-8"))
    cap_minutes = raw["orchestration"]["max_wall_time_minutes"]
    assert cap_minutes >= 45, (
        f"max_wall_time_minutes={cap_minutes} leaves too little headroom over "
        "the measured 1171.8s cold-index time (decision #11) for the rest of "
        "a first sitting"
    )


def test_gate_dry_run_prices_the_payload_cutaway_gen_actually_builds() -> None:
    """`CLIP` must be built from the same exported constants
    `CutawayGen._provider_inputs` uses, or the headline $0.63/$3.15 numbers
    describe a clip cutaway_gen never executes — right only because a
    provider's default happens to match the pin."""
    import importlib

    from tools.video.cutaway_gen import (
        CUTAWAY_ASPECT_RATIO,
        CUTAWAY_CLIP_SECONDS,
        CUTAWAY_MODEL_VARIANT,
        CUTAWAY_PROVIDER_PIN,
    )

    dry_run = importlib.import_module("scripts.reel_batch_gate_dry_run")

    assert dry_run.CLIP["preferred_provider"] == CUTAWAY_PROVIDER_PIN[0]
    assert dry_run.CLIP["model_variant"] == CUTAWAY_MODEL_VARIANT
    assert dry_run.CLIP["duration"] == CUTAWAY_CLIP_SECONDS
    assert dry_run.CLIP["aspect_ratio"] == CUTAWAY_ASPECT_RATIO


def test_source_media_review_frame_dirs_keyed_by_resolved_path() -> None:
    """Two pool files sharing a basename (different folders) must sample into
    different frame directories, or the second overwrites the first's frames
    and both report the same wrong `representative_frames`."""
    from types import SimpleNamespace

    from lib.source_media_review import _probe_video

    class _FrameSampler:
        def __init__(self) -> None:
            self.seen_output_dirs: list[str] = []

        def execute(self, inputs: dict) -> SimpleNamespace:
            self.seen_output_dirs.append(inputs["output_dir"])
            return SimpleNamespace(success=True, data={"frames": []})

    class _Registry:
        def __init__(self, sampler: "_FrameSampler") -> None:
            self._sampler = sampler

        def get(self, name: str):
            return self._sampler if name == "frame_sampler" else None

    sampler = _FrameSampler()
    registry = _Registry(sampler)

    _probe_video(Path("/pool/a/clip.mp4"), registry, frames_dir=Path("/frames"))
    _probe_video(Path("/pool/b/clip.mp4"), registry, frames_dir=Path("/frames"))

    assert sampler.seen_output_dirs[0] != sampler.seen_output_dirs[1], (
        "clip.mp4 in two different pool folders sampled into the same frame "
        f"directory: {sampler.seen_output_dirs}"
    )


# ----------------------------------------------------------------------
# Doc-table sync (#50). Adding a pipeline is a five-artifact job and three
# of those artifacts are hand-maintained Markdown tables.
# ----------------------------------------------------------------------

# (path, table heading). Heading level differs — `##` in two files, `###` in
# the third — so the match below is level-agnostic.
PIPELINE_TABLES = [
    ("AGENT_GUIDE.md", "Available Pipelines"),
    ("PROJECT_CONTEXT.md", "Available Pipelines"),
    ("docs/ARCHITECTURE.md", "Available Pipelines"),
]


def _table_pipelines(relative_path: str, heading: str) -> set[str]:
    """The pipeline names listed in one doc table's first column.

    Terminators differ per file — one table ends at a blockquote, the others
    at a heading — so the walk stops on the first line that is not a table
    row rather than looking for a specific closer.
    """
    import re

    lines = (REPO_ROOT / relative_path).read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, line in enumerate(lines)
         if re.fullmatch(rf"#+\s+{re.escape(heading)}\s*", line)),
        None,
    )
    assert start is not None, f"{relative_path} has no '{heading}' heading"

    names: set[str] = set()
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("|"):
            # Stop at the first prose after the HEADING, not after the first
            # row. AGENT_GUIDE.md carries several other tables; skipping
            # onwards when this section had no table at all would silently
            # report the Layer-3 skills table as the pipeline list, and the
            # sync assertion would then pass against the wrong data.
            break
        # Delimiter rows differ in dash count across the three files.
        if re.fullmatch(r"\|[-\s|:]+\|", stripped):
            continue
        cell = stripped.split("|")[1].strip().strip("`")
        if cell.lower() != "pipeline":
            names.add(cell)
    return names


@pytest.mark.parametrize(
    "relative_path,heading", PIPELINE_TABLES, ids=[t[0] for t in PIPELINE_TABLES]
)
def test_every_manifest_appears_in_every_pipeline_table(
    relative_path: str, heading: str
) -> None:
    """A pipeline that ships without a doc row is a pipeline nobody finds.

    Membership only. The value columns are deliberately NOT synced: `Best For`,
    `Type` and `Description` are hand-written prose with no key in the YAML to
    derive them from, and two `Category` cells in docs/ARCHITECTURE.md already
    disagree with their manifests (avatar-spokesperson and podcast-repurpose
    both read `custom` in YAML). Asserting the columns would either fail on
    arrival or force prose to be generated, which is worse prose. Membership is
    the part that can be checked and the part that actually drifts — this test
    was written because `documentary-montage` had shipped into
    `pipeline_defs/` and one table, and was missing from the other two.

    Discovery globs the directory with no allowlist, so a fourteenth pipeline
    cannot land with stale docs and no test edit is needed when one does.
    """
    documented = _table_pipelines(relative_path, heading)
    missing = sorted(set(PIPELINE_NAMES) - documented)
    assert not missing, (
        f"{relative_path} '{heading}' table is missing {missing}. Adding a "
        "pipeline means five artifacts: the manifest, its director skills, and "
        "a row in each of AGENT_GUIDE.md, PROJECT_CONTEXT.md and "
        "docs/ARCHITECTURE.md."
    )


@pytest.mark.parametrize(
    "relative_path,heading", PIPELINE_TABLES, ids=[t[0] for t in PIPELINE_TABLES]
)
def test_no_pipeline_table_lists_a_manifest_that_does_not_exist(
    relative_path: str, heading: str
) -> None:
    """The other direction: a deleted pipeline must leave its rows behind.

    Without this the sync test above is satisfied by a table that lists
    everything plus three pipelines that were removed two releases ago.
    """
    documented = _table_pipelines(relative_path, heading)
    phantom = sorted(documented - set(PIPELINE_NAMES))
    assert not phantom, (
        f"{relative_path} '{heading}' table lists {phantom}, which have no "
        f"manifest in pipeline_defs/"
    )
