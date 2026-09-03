"""The identity chain, end to end — one word, two machine checks, one gate.

Spec `docs/intent/reel-batch-spec.md` §3 R5. The operator's face is never
regenerated, and the guarantee is built out of four links:

1. **Declared at ingest.** `footage_library` stamps `identity_locked=True` on
   every corpus row it writes. It is the only ingest that does, because it is
   the only one that can honestly know whose footage this is.
2. **Carried on the cut.** `edit_decisions.cuts[].provenance` is a closed
   two-value enum, travelling from the corpus row at cut-list time.
3. **Refused at generation.** `cutaway_gen` rejects every media reference,
   recursively, before a byte is priced or sent — a likeness cannot reach a
   generator even by a renamed or nested key.
4. **Gated at compose.** `_pre_compose_validation` blocks a cut whose declared
   provenance contradicts the tool that produced its asset, and a cut marked
   `operator_footage` carrying a look outside the identity-safe set.

Each test below fails when the link it polices is reverted.

WHAT THIS DOES NOT PROVE
------------------------
**Provenance is a declaration, not a detection.** Nothing here inspects pixels.
A director that labels an operator clip `ai_generated` in an `edit_decisions`
with no matching asset-manifest row passes every check in this file. Link 4's
cross-check narrows that gap — it catches the relabelling whenever the asset
came from `footage_library` or `cutaway_gen`, which is every asset the
reel-batch pipeline produces — but a hand-placed file with a hand-written
provenance has nothing to be checked against. Default-deny at ingest is what
makes the remaining gap small: the whole pool is locked, so mislabelling takes
an active override rather than an omission.

**Omission is the softer hole.** A cut with no `provenance` key at all is not
blocked; `look_filters` treats it as unlocked and every grade resolves. The
schema types `provenance` but does not require it. This is deliberate — the
field is meaningless for the twelve pipelines that never touch operator
footage — and it is why the reel-batch edit-director sets it on every cut and
`test_reel_plan.py` asserts the spine carries it. It is a real limit, and it is
how a demo in this repo once appeared to prove the guard while bypassing it.

**`faceswap` remains reachable by hand.** The skill exists in the tree and
nothing stops an operator invoking it outside this pipeline. That is doctrine
(`AGENT_GUIDE.md`), not enforcement, and `test_doctrine_*` below only checks
that the doctrine is written down.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from lib.polish_filters import PolishError, look_filters  # noqa: E402
from tools.base_tool import ToolResult  # noqa: E402
from tools.video.cutaway_gen import (  # noqa: E402
    CutawayGen,
    MediaReferenceRefusedError,
)
from tools.video.video_compose import (  # noqa: E402
    PROVENANCE_BY_SOURCE_TOOL,
    VideoCompose,
)

# One per early-return route out of `_render`. The gate sits above all three;
# an identity check that fires on only one of them is not a guarantee.
ROUTES = [
    ("templated", {"render_runtime": "remotion"}),
    ("atelier", {"render_runtime": "remotion", "composition_mode": "atelier"}),
    ("hyperframes", {"render_runtime": "hyperframes", "composition_mode": "atelier"}),
]
ROUTE_IDS = [r[0] for r in ROUTES]


# ----------------------------------------------------------------------
# Link 1 — declared at ingest
# ----------------------------------------------------------------------


def test_ingest_declares_the_lock_on_every_row() -> None:
    """`footage_library` constructs no `ClipRecord` without `identity_locked=True`.

    An AST assertion rather than a string match, so reformatting the call does
    not break it and deleting the keyword does. The executable proof — index a
    real pool, read the rows back — is `tests/tools/test_footage_library.py`
    `test_every_indexed_row_is_identity_locked`, which needs ffmpeg; this is the
    floor that holds when ffmpeg is absent.
    """
    source = (REPO_ROOT / "tools" / "video" / "footage_library.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    records = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ClipRecord"
    ]
    assert records, "footage_library no longer constructs ClipRecord — chain broken"

    for call in records:
        locked = [kw for kw in call.keywords if kw.arg == "identity_locked"]
        assert locked, (
            f"ClipRecord at line {call.lineno} omits identity_locked. The pool is "
            "the operator's own footage; an unlocked row looks like stock and the "
            "compose gate has nothing to enforce."
        )
        assert isinstance(locked[0].value, ast.Constant) and locked[0].value.value is True, (
            f"ClipRecord at line {call.lineno} does not set identity_locked=True"
        )


def test_ingest_is_the_only_place_the_lock_is_set() -> None:
    """Default-deny: `ClipRecord.identity_locked` defaults to False.

    The guarantee rests on exactly one ingest path opting in. A second writer —
    or a changed default — would let stock rows claim the operator's protection
    and, worse, make an unlocked operator row indistinguishable from an
    unlocked stock one.
    """
    from lib.corpus import ClipRecord

    fields = {f.name: f for f in ClipRecord.__dataclass_fields__.values()}
    assert "identity_locked" in fields
    assert fields["identity_locked"].default is False, (
        "identity_locked must default to False — 17 corpus adapters are network "
        "stock providers and none of them may inherit the lock by accident"
    )


# ----------------------------------------------------------------------
# Link 3 — refused at generation
# ----------------------------------------------------------------------

# Each is a way to hand a generator a likeness. The guard matches on the key
# name and on the value, recursively, so none of these is a way round it.
MEDIA_REFERENCE_SHAPES = [
    ("flat key", {"prompts": ["chalk dust"], "reference_image_path": "/pool/me.jpg"}),
    ("renamed key", {"prompts": ["chalk dust"], "init_video": "/pool/me.mp4"}),
    ("nested in a dict", {"prompts": ["chalk dust"], "extra": {"image_url": "/pool/me.png"}}),
    ("nested in a list", {"prompts": ["chalk dust"], "refs": [{"last_image_url": "/x/me.jpg"}]}),
    ("bare path value", {"prompts": ["chalk dust"], "style": "/pool/me.mp4"}),
    ("base64 upload", {"prompts": ["c"], "seed_frame": "data:image/png;base64,AAAA"}),
]


@pytest.mark.parametrize(
    "label,inputs", MEDIA_REFERENCE_SHAPES, ids=[s[0] for s in MEDIA_REFERENCE_SHAPES]
)
def test_generation_refuses_a_likeness_before_pricing(label: str, inputs: dict) -> None:
    """The refusal lands on `estimate_cost`, not only on `execute`.

    Pricing is where a paid route is chosen. A guard that only fires at execute
    time has already let the operator's face decide which provider to bill.
    """
    with pytest.raises(MediaReferenceRefusedError):
        CutawayGen().estimate_cost(inputs)


@pytest.mark.parametrize(
    "label,inputs", MEDIA_REFERENCE_SHAPES, ids=[s[0] for s in MEDIA_REFERENCE_SHAPES]
)
def test_generation_refuses_a_likeness_before_sending(label: str, inputs: dict) -> None:
    with pytest.raises(MediaReferenceRefusedError):
        CutawayGen().execute(inputs)


def test_a_text_prompt_is_not_mistaken_for_a_reference() -> None:
    """The guard must not be so broad it refuses the only supported input.

    `num_frames` contains "frame" and `preferred_provider` contains "refer";
    a substring rule with no carve-out refuses both and the tool never runs.
    """
    from tools.video.cutaway_gen import refuse_media_references

    refuse_media_references(
        {
            "prompts": ["chalk dust drifting through a hard side light, macro"],
            "num_frames": 24,
            "preferred_provider": "kling",
            "flash_seconds": 0.6,
        }
    )


# ----------------------------------------------------------------------
# Link 4 — gated at compose
# ----------------------------------------------------------------------


def _render_inputs(tmp_path: Path, extra: dict, *, cuts: list[dict],
                   assets: list[dict], **overrides) -> dict:
    return {
        "operation": "render",
        "edit_decisions": {
            "version": "1.0",
            "renderer_family": "documentary-montage",
            "cuts": cuts,
            **extra,
        },
        "asset_manifest": {"version": "1.0", "assets": assets},
        "output_path": str(tmp_path / "out.mp4"),
        **overrides,
    }


def _no_renderer_runs(monkeypatch, label: str) -> None:
    """Every renderer entry point fails the test if it is reached."""
    def boom(*a, **k):
        pytest.fail(f"{label}: a renderer ran past a blocking identity gate")

    for method in ("_render_via_atelier", "_render_via_hyperframes",
                   "_render_via_ffmpeg", "_compose", "_remotion_render"):
        monkeypatch.setattr(VideoCompose, method, boom)


@pytest.mark.parametrize("label,extra", ROUTES, ids=ROUTE_IDS)
def test_operator_clip_relabelled_ai_generated_is_rejected(
    tmp_path, monkeypatch, label: str, extra: dict
) -> None:
    """The headline violation, on every runtime.

    Relabelling an operator clip `ai_generated` is how identity protection gets
    switched off: `look_filters` stops refusing grades and grain the moment the
    word changes. The asset came from `footage_library`, which only ever
    produces the operator's own pool, so the declaration is a contradiction.
    """
    _no_renderer_runs(monkeypatch, label)

    result = VideoCompose().execute(
        _render_inputs(
            tmp_path,
            extra,
            cuts=[{
                "id": "reel_01-01", "source": "pool_01",
                "in_seconds": 0.0, "out_seconds": 1.9,
                "provenance": "ai_generated",
            }],
            assets=[{
                "id": "pool_01", "type": "video",
                "path": str(tmp_path / "rack_pulls.mp4"),
                "source_tool": "footage_library", "scene_id": "reel_01-01",
            }],
        )
    )

    assert not result.success, f"{label}: relabelled operator clip rendered"
    assert "Identity violation" in (result.error or "")
    assert "reel_01-01" in (result.error or "")


@pytest.mark.parametrize("label,extra", ROUTES, ids=ROUTE_IDS)
def test_generated_clip_relabelled_operator_footage_is_rejected(
    tmp_path, monkeypatch, label: str, extra: dict
) -> None:
    """The inverse mislabel, which corrupts the audit trail rather than the face.

    It over-restricts rather than under-restricts, so it is the less dangerous
    direction — but a batch whose provenance column is unreliable in either
    direction cannot answer "was any of this generated?", which is the question
    the field exists for.
    """
    _no_renderer_runs(monkeypatch, label)

    result = VideoCompose().execute(
        _render_inputs(
            tmp_path,
            extra,
            cuts=[{
                "id": "reel_01-03", "source": "flash_01",
                "in_seconds": 0.0, "out_seconds": 0.6,
                "provenance": "operator_footage",
            }],
            assets=[{
                "id": "flash_01", "type": "video",
                "path": str(tmp_path / "chalk.mp4"),
                "source_tool": "cutaway_gen", "scene_id": "reel_01-03",
            }],
        )
    )

    assert not result.success, f"{label}: relabelled AI clip rendered"
    assert "Identity violation" in (result.error or "")


@pytest.mark.parametrize("label,extra", ROUTES, ids=ROUTE_IDS)
def test_unsafe_look_on_an_operator_cut_is_rejected(
    tmp_path, monkeypatch, label: str, extra: dict
) -> None:
    """A colour grade on the operator's face, blocked before any runtime.

    `look_filters` already refuses this, but only where it is called — inside
    the ffmpeg per-segment encode. On the atelier and HyperFrames routes that
    code never runs, so before the gate the same batch look was refused on one
    runtime and applied on two.
    """
    _no_renderer_runs(monkeypatch, label)

    result = VideoCompose().execute(
        _render_inputs(
            tmp_path,
            extra,
            cuts=[{
                "id": "reel_01-01", "source": "pool_01",
                "in_seconds": 0.0, "out_seconds": 1.9,
                "provenance": "operator_footage",
            }],
            assets=[{
                "id": "pool_01", "type": "video",
                "path": str(tmp_path / "rack_pulls.mp4"),
                "source_tool": "footage_library", "scene_id": "reel_01-01",
            }],
            batch_look={"grade": "high_contrast", "grain": 4},
        )
    )

    assert not result.success, f"{label}: an unsafe look reached the renderer"
    assert "Identity violation" in (result.error or "")
    assert "identity-safe" in (result.error or "")


@pytest.mark.parametrize("label,extra", ROUTES, ids=ROUTE_IDS)
def test_an_honest_identity_locked_plan_reaches_the_renderer(
    tmp_path, monkeypatch, label: str, extra: dict
) -> None:
    """The negative control.

    A gate that blocks everything proves nothing. An operator cut declared
    `operator_footage`, under a `face_enhance` look, must render.
    """
    sentinel = ToolResult(success=True, data={"reached": label})
    for method in ("_render_via_atelier", "_render_via_hyperframes",
                   "_render_via_ffmpeg", "_compose"):
        monkeypatch.setattr(VideoCompose, method, lambda *a, **k: sentinel)
    monkeypatch.setattr(VideoCompose, "_needs_remotion", lambda self, cuts: False)
    monkeypatch.setattr(VideoCompose, "_run_final_review", lambda *a, **k: {})

    result = VideoCompose().execute(
        _render_inputs(
            tmp_path,
            extra,
            cuts=[{
                "id": "reel_01-01", "source": "pool_01",
                "in_seconds": 0.0, "out_seconds": 1.9,
                "provenance": "operator_footage",
            }],
            assets=[{
                "id": "pool_01", "type": "video",
                "path": str(tmp_path / "rack_pulls.mp4"),
                "source_tool": "footage_library", "scene_id": "reel_01-01",
            }],
            batch_look={"grade": "talking_head_standard", "sharpen": "sharpen_light"},
        )
    )

    assert result.success, f"{label}: an honest plan was blocked — {result.error}"


def test_the_allowed_filter_set_is_face_enhance_only() -> None:
    """What "identity-safe" means, asserted rather than described.

    Every `face_enhance` preset resolves on a locked cut; every `color_grade`
    profile and any grain raises. If a grade ever becomes reachable this fails,
    which is the point — the set is the guarantee.
    """
    from tools.enhancement.color_grade import PROFILES as GRADE_PROFILES
    from tools.enhancement.face_enhance import PRESETS as FACE_PRESETS

    for preset in FACE_PRESETS:
        assert look_filters({"grade": preset}, "operator_footage"), (
            f"face_enhance preset {preset!r} no longer resolves on a locked cut"
        )

    for profile in GRADE_PROFILES:
        if profile in FACE_PRESETS:
            continue
        with pytest.raises(PolishError, match="identity-safe"):
            look_filters({"grade": profile}, "operator_footage")

    with pytest.raises(PolishError, match="grain"):
        look_filters({"grain": 4}, "operator_footage")

    # And the same look is fine on generated pixels — the restriction is the
    # operator's face, not a house style.
    assert look_filters({"grade": "high_contrast", "grain": 4}, "ai_generated")


def test_the_provenance_map_covers_both_identity_producing_tools() -> None:
    """The gate's cross-check is only as wide as this map.

    `footage_library` is the sole writer of `identity_locked=True`;
    `cutaway_gen` is the sole producer of generated frames. A third tool that
    makes pixels for this pipeline must be added here or its cuts are declared
    with nothing to check them against.
    """
    assert PROVENANCE_BY_SOURCE_TOOL == {
        "footage_library": "operator_footage",
        "cutaway_gen": "ai_generated",
    }


# ----------------------------------------------------------------------
# Doctrine — what the code cannot enforce
# ----------------------------------------------------------------------

DOCTRINE_FILES = [
    "AGENT_GUIDE.md",
    "skills/pipelines/reel-batch/executive-producer.md",
    "skills/pipelines/reel-batch/asset-director.md",
]


@pytest.mark.parametrize("relative", DOCTRINE_FILES)
def test_doctrine_puts_face_regeneration_out_of_scope(relative: str) -> None:
    """`faceswap` is reachable by hand; only doctrine says not to reach for it.

    This asserts the sentence exists, which is all a test can do about a skill
    an operator can invoke directly. It is written down in three places because
    an agent reads whichever one its stage routes it to.
    """
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")

    # Both words in the SAME paragraph. `faceswap` appears in AGENT_GUIDE.md's
    # Layer-3 routing table as a legitimate skill, so asserting the two strings
    # independently passes on a file where the prohibition has been deleted —
    # a revert check caught exactly that.
    paragraphs = [p for p in text.split("\n\n") if "faceswap" in p]
    assert paragraphs, f"{relative} does not name the prohibited skill"
    assert any("out of scope" in p.lower() for p in paragraphs), (
        f"{relative} mentions faceswap but no paragraph puts it out of scope"
    )
