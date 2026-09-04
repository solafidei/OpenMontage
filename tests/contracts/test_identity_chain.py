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
came from `footage_library` or `cutaway_gen`, whether the cut names that asset
by its id or by its path, which between them is every asset the reel-batch
pipeline produces — but a hand-placed file with a hand-written provenance has
nothing to be checked against. And `source_tool` is itself written by the same
agent that writes `provenance`: the cross-check catches a downstream rewrite
and an inconsistent pair, not an author who lies in both fields at once.
Default-deny at ingest is what makes the remaining gap small: the whole pool is
locked, so mislabelling takes an active override rather than an omission.

**Omission is closed only where the manifest knows.** A cut with no
`provenance` key falls back to what its asset row implies, so silence is not a
waiver when the asset came from `footage_library` or `cutaway_gen`. It still is
one when nothing in the manifest matches the cut's `source` — an unreferenced
file has no second opinion to fall back on. The schema types `provenance` but
does not require it, deliberately: the field is meaningless for the thirteen
pipelines that never touch operator footage. Omission was how a demo in this
repo once appeared to prove the guard while bypassing it, which is why the
fallback exists.

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

# ffmpeg is the runtime reel-batch locks at proposal and the only one that can
# apply a batch_look, so the negative control has to cover it too — the three
# rejection routes above deliberately do not, they exist to prove the gate
# fires before a renderer is even chosen.
HONEST_ROUTES = [*ROUTES, ("ffmpeg", {"render_runtime": "ffmpeg"})]
HONEST_ROUTE_IDS = [r[0] for r in HONEST_ROUTES]


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


@pytest.mark.parametrize("label,extra", HONEST_ROUTES, ids=HONEST_ROUTE_IDS)
def test_an_honest_identity_locked_plan_is_not_blocked_for_identity(
    tmp_path, monkeypatch, label: str, extra: dict
) -> None:
    """The negative control.

    A gate that blocks everything proves nothing. An operator cut declared
    `operator_footage`, under a `face_enhance` look, must never be refused on
    IDENTITY grounds — on any runtime.

    Only ffmpeg is asserted to actually render, and that asymmetry IS the
    point rather than a weakening. The picture plane lives entirely in the
    per-cut ffmpeg encode (spec R6), so a `batch_look` handed to Remotion or
    HyperFrames would reach the renderer as nothing at all. A second gate
    refuses it for exactly that reason, so the look can never be silently
    dropped. Asserting success on those two routes would have meant deleting
    that refusal — this test used to do so, and was wrong to.
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

    assert "Identity violation" not in (result.error or ""), (
        f"{label}: an honest operator_footage plan under a face_enhance look was "
        f"refused on identity grounds — {result.error}"
    )
    if extra.get("render_runtime") == "ffmpeg":
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


# ----------------------------------------------------------------------
# The three ways round link 4 that an adversarial pass found
# ----------------------------------------------------------------------


def _one_cut_render(tmp_path, cut: dict, *, assets: list[dict], look=None) -> "ToolResult":
    return VideoCompose().execute({
        "operation": "render",
        "edit_decisions": {
            "version": "1.0",
            "renderer_family": "documentary-montage",
            "render_runtime": "ffmpeg",
            "cuts": [cut],
        },
        "asset_manifest": {"version": "1.0", "assets": assets},
        "batch_look": look,
        "output_path": str(tmp_path / "out.mp4"),
    })


POOL_ASSET = {
    "id": "asset_reel_01_01", "type": "video", "path": "/pool/rack_pulls_A.mp4",
    "source_tool": "footage_library", "scene_id": "reel_01-01",
}
UNSAFE_LOOK = {"grade": "high_contrast", "grain": 4}


@pytest.mark.parametrize("source", ["asset_reel_01_01", "/pool/rack_pulls_A.mp4"],
                         ids=["by asset id", "by file path"])
def test_the_cross_check_finds_the_asset_however_the_cut_names_it(
    tmp_path, monkeypatch, source: str
) -> None:
    """`_render` accepts a `source` that is an asset id OR a file path.

    The gate originally indexed the manifest by id alone, so naming the
    operator's clip by its filename walked straight past the cross-check while
    the corroborating row sat in the same manifest — and `_compose` then opened
    the path and graded the face. Both spellings must reach the same row.
    """
    _no_renderer_runs(monkeypatch, source)

    result = _one_cut_render(
        tmp_path,
        {"id": "reel_01-01", "source": source, "in_seconds": 0.0,
         "out_seconds": 1.9, "provenance": "ai_generated"},
        assets=[POOL_ASSET],
    )

    assert not result.success, f"a cut sourced {source!r} skipped the cross-check"
    assert "Identity violation" in (result.error or "")


@pytest.mark.parametrize("source", ["asset_reel_01_01", "/pool/rack_pulls_A.mp4"],
                         ids=["by asset id", "by file path"])
def test_omitting_provenance_is_not_a_waiver_when_the_manifest_knows(
    tmp_path, monkeypatch, source: str
) -> None:
    """Silence used to disarm the look guard even with the answer in hand.

    `look_filters` reads one word; no word meant "not locked", so a cut that
    simply omitted `provenance` took a colour grade and grain — while its own
    asset row said `footage_library`. Omission is the failure mode that
    actually happens, because it needs no intent.
    """
    _no_renderer_runs(monkeypatch, source)

    result = _one_cut_render(
        tmp_path,
        {"id": "reel_01-01", "source": source, "in_seconds": 0.0, "out_seconds": 1.9},
        assets=[POOL_ASSET],
        look=UNSAFE_LOOK,
    )

    assert not result.success, "an unlabelled cut from a known pool asset was graded"
    assert "identity-safe" in (result.error or "")


def test_a_shadow_asset_row_cannot_disarm_the_cross_check(tmp_path, monkeypatch) -> None:
    """Appending a duplicate id with a benign `source_tool` must not win.

    A dict comprehension keyed on id lets the LAST row win, so one appended
    line — same id, `source_tool` outside the map — silently switched the
    check off for that cut. First row wins now.
    """
    _no_renderer_runs(monkeypatch, "shadow")

    result = _one_cut_render(
        tmp_path,
        {"id": "reel_01-01", "source": "asset_reel_01_01", "in_seconds": 0.0,
         "out_seconds": 1.9, "provenance": "ai_generated"},
        assets=[
            POOL_ASSET,
            {**POOL_ASSET, "source_tool": "stock_search", "path": "/elsewhere/x.mp4"},
        ],
    )

    assert not result.success, "a shadow manifest row disarmed the cross-check"


def test_an_unreferenced_source_still_renders(tmp_path, monkeypatch) -> None:
    """The limit, asserted so it stays a limit and does not quietly widen.

    A cut whose `source` matches no manifest row has no second opinion. It
    renders, and the file docstring says so. If this ever starts failing, the
    gate has become a default-deny on every pipeline that hands compose a bare
    path — which is most of them.
    """
    sentinel = ToolResult(success=True, data={})
    for method in ("_render_via_ffmpeg", "_compose", "_remotion_render"):
        monkeypatch.setattr(VideoCompose, method, lambda *a, **k: sentinel)
    monkeypatch.setattr(VideoCompose, "_run_final_review", lambda *a, **k: {})

    result = _one_cut_render(
        tmp_path,
        {"id": "reel_01-01", "source": "/elsewhere/stock.mp4",
         "in_seconds": 0.0, "out_seconds": 1.9},
        assets=[POOL_ASSET],
        look=UNSAFE_LOOK,
    )

    assert result.success, f"an unreferenced source was blocked — {result.error}"


def test_a_typo_in_the_look_is_not_reported_as_an_identity_violation(
    tmp_path, monkeypatch
) -> None:
    """`look_filters` raises for two unrelated reasons, and they read alike.

    An unresolvable preset name is a typo in the batch look; calling that an
    "identity violation" sends whoever hit it hunting a provenance bug that is
    not there. The look is validated unlocked first, which separates them.
    """
    _no_renderer_runs(monkeypatch, "typo")

    result = _one_cut_render(
        tmp_path,
        {"id": "reel_01-01", "source": "flash_01", "in_seconds": 0.0,
         "out_seconds": 0.6, "provenance": "ai_generated"},
        assets=[{"id": "flash_01", "type": "video", "path": "/gen/chalk.mp4",
                 "source_tool": "cutaway_gen", "scene_id": "reel_01-03"}],
        look={"grade": "high_contrst"},
    )

    assert not result.success
    assert "Invalid batch_look" in (result.error or "")
    assert "Identity violation" not in (result.error or "")


def test_one_look_verdict_per_provenance_not_one_per_cut(tmp_path, monkeypatch) -> None:
    """A batch look is one decision, so it is one line — not one per cut.

    Five reels is twenty-five cuts, and the block message repeated the same
    sentence twenty-five times. It names the count and the first few ids
    instead.
    """
    _no_renderer_runs(monkeypatch, "many")

    cuts = [
        {"id": f"reel_01-{n:02d}", "source": "asset_reel_01_01",
         "in_seconds": 0.0, "out_seconds": 1.0, "provenance": "operator_footage"}
        for n in range(1, 26)
    ]
    result = VideoCompose().execute({
        "operation": "render",
        "edit_decisions": {"version": "1.0", "renderer_family": "documentary-montage",
                           "render_runtime": "ffmpeg", "cuts": cuts},
        "asset_manifest": {"version": "1.0", "assets": [POOL_ASSET]},
        "batch_look": UNSAFE_LOOK,
        "output_path": str(tmp_path / "out.mp4"),
    })

    assert not result.success
    violations = [
        line for line in (result.error or "").splitlines()
        if "Identity violation" in line
    ]
    assert len(violations) == 1, f"one look, {len(violations)} verdicts"
    assert "25" in violations[0] and "reel_01-01" in violations[0]
