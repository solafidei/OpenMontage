import json
import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _director_files(pattern: str, containing: str) -> list[Path]:
    """Every skills/pipelines/*/<pattern> whose text carries `containing`.

    Discovery is dynamic so a pipeline wired later (the Epic-1 rollout of
    screen-demo, talking-head, podcast-repurpose, character-animation,
    localization-dub, clip-factory) is swept automatically — wiring a
    director and dropping the contract lines must fail here with no test
    edit."""
    root = REPO_ROOT / "skills" / "pipelines"
    return sorted(
        p for p in root.glob(f"*/{pattern}")
        if containing in p.read_text(encoding="utf-8")
    )


def test_music_plans_discover_all_music_capabilities() -> None:
    instruction_files = [
        "AGENT_GUIDE.md",
        "skills/pipelines/cinematic/idea-director.md",
        "skills/pipelines/cinematic/proposal-director.md",
        "skills/pipelines/documentary-montage/idea-director.md",
        "skills/pipelines/explainer/proposal-director.md",
    ]

    for relative_path in instruction_files:
        text = _read(relative_path)
        for capability in ("music_library", "music_search", "music_generation"):
            assert f'get_by_capability("{capability}")' in text, (
                f"{relative_path} omits the {capability!r} music source"
            )


def test_explainer_directors_do_not_reference_fictitious_submit_functions() -> None:
    for stage in ("idea", "script", "scene"):
        text = _read(f"skills/pipelines/explainer/{stage}-director.md")
        assert "handle_explainer_" not in text


QUANTITY_GATE_SENTINELS = (
    "skills/pipelines/explainer/proposal-director.md",
    "skills/pipelines/cinematic/proposal-director.md",
    "skills/pipelines/animation/proposal-director.md",
)


def test_every_quantity_priced_proposal_gate_multiplies_unit_price() -> None:
    """estimate_cost prices ONE call. image_selector/video_selector ignore any
    quantity key, so a gate that skips the multiplication under-prices a
    6-clip plan by 6x — on screen and in the seeded cost_log alike.

    Discovery is dynamic: any proposal gate that prices a planned line item
    is swept, so a pipeline wired later cannot ship the un-multiplied form."""
    discovered = _director_files("proposal-director.md", "estimate_cost(planned")
    relative = {str(path.relative_to(REPO_ROOT)) for path in discovered}

    # Sentinel floor — an empty sweep would prove nothing.
    for expected in QUANTITY_GATE_SENTINELS:
        assert expected in relative, (
            f"{expected} no longer prices a planned line item via estimate_cost"
        )

    for path in discovered:
        text = path.read_text(encoding="utf-8")
        name = path.relative_to(REPO_ROOT)
        assert 'unit_usd = tool.estimate_cost(planned["inputs"])' in text, (
            f"{name} must price one unit via estimate_cost"
        )
        assert "estimated_usd = round(unit_usd * quantity, 4)" in text, (
            f"{name} must multiply the unit price by quantity"
        )


LEDGER_WIRED_SPENDING_SENTINELS = tuple(
    f"skills/pipelines/{pipeline}/{stage}-director.md"
    for pipeline in (
        "explainer", "animation", "cinematic",
        "avatar-spokesperson", "hybrid", "documentary-montage",
    )
    for stage in ("asset", "compose")
)


def test_every_ledger_wired_spending_director_reserves_with_gate_approval() -> None:
    """An approved line item over single_action_approval_usd must not deadlock
    at the point of spend — every paid reserve in a spending director waives
    the single-action threshold for its own entry.

    Presence of `CostTracker.for_project` is the definition of ledger-wired on
    this branch, so discovery tracks the rollout for free: a pipeline wired
    later is swept with no test edit."""
    discovered = (
        _director_files("asset-director.md", "CostTracker.for_project")
        + _director_files("compose-director.md", "CostTracker.for_project")
    )
    relative = {str(path.relative_to(REPO_ROOT)) for path in discovered}

    # Sentinel floor — a mass revert that strips the ledger blocks (dropping
    # `CostTracker.for_project` and the reserve line together) must still fail.
    for expected in LEDGER_WIRED_SPENDING_SENTINELS:
        assert expected in relative, f"{expected} no longer opens the project ledger"

    for path in discovered:
        text = path.read_text(encoding="utf-8")
        name = path.relative_to(REPO_ROOT)
        assert "tracker.reserve(entry_id, user_approved=True)" in text, (
            f"{name} never reserves with the gate approval flag"
        )
        for call in re.findall(r"tracker\.reserve\([^)]*\)", text):
            assert "user_approved=True" in call, (
                f"{name} reserves without the gate approval flag: {call}"
            )


# --- Workstream C / D0: the ledger-discipline canon in skills/ -----------------

SKILL_PIPELINES = REPO_ROOT / "skills" / "pipelines"

ARMING_GATE_FILES = (
    "skills/pipelines/explainer/proposal-director.md",
    "skills/pipelines/cinematic/proposal-director.md",
    "skills/pipelines/animation/proposal-director.md",
    "skills/pipelines/documentary-montage/idea-director.md",
    "skills/pipelines/hybrid/idea-director.md",
    "skills/pipelines/avatar-spokesperson/idea-director.md",
)

LEDGER_BOOKING_FILES = (
    "skills/pipelines/explainer/asset-director.md",
    "skills/pipelines/animation/asset-director.md",
    "skills/pipelines/cinematic/asset-director.md",
    "skills/pipelines/avatar-spokesperson/asset-director.md",
    "skills/pipelines/hybrid/asset-director.md",
    "skills/pipelines/documentary-montage/asset-director.md",
    "skills/pipelines/explainer/compose-director.md",
)


def _pipeline_skill_files() -> list[Path]:
    return sorted(SKILL_PIPELINES.rglob("*.md"))


def test_arming_formula_is_canonical_across_proposal_gates() -> None:
    """Arming with the bare estimate leaves zero headroom against the reserve
    holdback, so the plan's FINAL approved reservation always trips the guard.
    Every gate that arms the tracker must gross the estimate up past the
    holdback, and reserve_pct must come from the tracker, never a literal."""
    formula = "math.ceil(total_estimated_usd / (1 - tracker.reserve_pct) * 100) / 100 + 0.01"

    discovered = [
        path for path in _pipeline_skill_files()
        if "tracker.budget_total_usd =" in path.read_text(encoding="utf-8")
    ]
    relative = {str(path.relative_to(REPO_ROOT)) for path in discovered}

    # Sentinel floor — an empty sweep would prove nothing.
    for expected in ARMING_GATE_FILES:
        assert expected in relative, f"{expected} no longer arms the tracker"

    for path in discovered:
        text = path.read_text(encoding="utf-8")
        name = path.relative_to(REPO_ROOT)
        assert formula in text, f"{name} arms the tracker without the reserve gross-up"
        assert "or total_estimated_usd" not in text, (
            f"{name} still arms the bare estimate — zero headroom vs the holdback"
        )
        assert "min_workable_usd" in text, f"{name} omits the min_workable_usd floor"


# --- C2 / finding #5: one ledger name per line of spend, in EVERY pipeline ----
#
# `CostTracker.reserve` raises ApprovalRequiredError on the first PAID use of a
# tool the gate never called `approve_tool` for (`tools/cost_tracker.py`, the
# `require_approval_for_new_paid_tool and estimated > 0` branch). The gate arms
# exactly the tool names it itemised, so a spending director that books the same
# work under a different name — the concrete provider (`openai_tts`) instead of
# the planned selector (`tts_selector`) — deadlocks approved work at the moment
# of spend. That is finding #5, and it is reintroducible in any pipeline.
#
# Discovery is per-pipeline and dynamic: manifests come from `pipeline_defs/`,
# directors from each manifest's own `required_skills`, and the gate is the
# director carrying D0's seed/arm heading. A 13th pipeline is swept with no
# edit here.

PIPELINE_DEFS = REPO_ROOT / "pipeline_defs"
SKILLS_ROOT = REPO_ROOT / "skills"

# framework-smoke is the framework's own test pipeline (`tools_available: []`).
NON_EPISODE_MANIFESTS = frozenset({"framework-smoke.yaml"})

# Sentinel floors — an empty or half-empty sweep would prove nothing.
MIN_EPISODE_PIPELINES = 12
MIN_PAID_RESERVATIONS = 12

GATE_SEED_MARKER = "Compute Budget And Seed The Cost Ledger"
GATE_ARM_MARKER = "On Approval — Arm the Tracker"

# `estimated > 0` is what arms the first-paid-use guard, so a round trip booked
# at a literal zero can never trip it and is not swept.
ZERO_LITERALS = frozenset({"0", "0.0", "0.00", "0.000", "0.0000"})

_ESTIMATE_CALL = re.compile(r'tracker\.estimate\(\s*"([a-z0-9_]+)"')
_BACKTICKED = re.compile(r"`([^`\n]+)`")
# Ledger tool names are snake_case with at least one underscore
# (`tts_selector`, `music_gen`, `talking_head`, `video_compose`).
_LEDGER_NAME = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def _episode_manifests() -> list[Path]:
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


def _resolve_skill(reference: str) -> Path | None:
    flat = SKILLS_ROOT / f"{reference}.md"
    if flat.is_file():
        return flat
    packaged = SKILLS_ROOT / reference / "SKILL.md"
    if packaged.is_file():
        return packaged
    return None


def _own_directors(manifest_data: dict) -> list[Path]:
    """The pipeline's OWN directors — shared `meta/*` skills are excluded so a
    name armed in a shared file can never cover a pipeline that lacks it."""
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
        if resolved is not None and resolved not in files:
            files.append(resolved)
    return files


def _split_top_level_args(argument_text: str) -> list[str]:
    """Split a call's argument text on top-level commas.

    Quotes and bracket nesting are tracked so an f-string operation label
    (`f"clip_bed_{bed['clip_id']}"`) is one argument, not three."""
    args: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    for char in argument_text:
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            current.append(char)
        elif char in "([{":
            depth += 1
            current.append(char)
        elif char in ")]}":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def _estimate_calls(text: str) -> list[tuple[str, list[str]]]:
    """Every `tracker.estimate("<name>", ...)` in the text, as (name, args)."""
    calls: list[tuple[str, list[str]]] = []
    for match in _ESTIMATE_CALL.finditer(text):
        opening = text.index("(", match.start())
        depth = 0
        closing = None
        for index in range(opening, len(text)):
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing is None:
            continue
        calls.append(
            (match.group(1), _split_top_level_args(text[opening + 1 : closing]))
        )
    return calls


def _paid_reserved_names(text: str) -> set[str]:
    """Tool names this director books a NON-zero entry under.

    A third argument that is not a literal zero is treated as paid: the
    variable forms (`estimated_usd`) and the docs' elided form (`...`) both
    stand for real money, and only a literal zero is provably guard-exempt."""
    return {
        name
        for name, args in _estimate_calls(text)
        if len(args) >= 3 and args[2] not in ZERO_LITERALS
    }


def _armed_names(gate_text: str) -> set[str]:
    """Tool names the gate itemises — seeded in code or named in prose.

    Both forms count because the gates split on style: some seed literal
    `tracker.estimate("music_gen", ...)` calls, others loop over the plan's
    line items and itemise the tools in backticked prose. Over-inclusion here
    (a backticked local like `estimated_usd`) only ever makes the sweep more
    permissive; the failure this guards is a name the gate never mentions at
    all."""
    names = {name for name, _ in _estimate_calls(gate_text)}
    names.update(
        token
        for token in (raw.strip() for raw in _BACKTICKED.findall(gate_text))
        if _LEDGER_NAME.match(token)
    )
    return names


def _ledger_vocabulary() -> set[str]:
    """Every name booked as a ledger key anywhere under `skills/pipelines/`.

    Used only to keep the failure message readable — it narrows a gate's armed
    set down to the names that are actually tools."""
    return {
        name
        for path in sorted((SKILLS_ROOT / "pipelines").rglob("*.md"))
        for name, _ in _estimate_calls(path.read_text(encoding="utf-8"))
    }


def test_ledger_keys_match_gate_line_items_in_every_pipeline() -> None:
    """Per pipeline: every tool name a spending director RESERVES as paid must
    be a name the pipeline's own gate director ARMED.

    This is finding #5 swept across the rollout rather than asserted about one
    file: booking narration under `openai_tts` when the gate armed
    `tts_selector` trips the first-paid-use guard on approved work, in any of
    the twelve pipelines."""
    paid_reservations = 0
    vocabulary = _ledger_vocabulary()

    for manifest in _episode_manifests():
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        directors = _own_directors(data)
        assert directors, f"{manifest.name}: no pipeline directors resolved"

        texts = {path: path.read_text(encoding="utf-8") for path in directors}
        gates = [
            path
            for path, text in texts.items()
            if GATE_SEED_MARKER in text or GATE_ARM_MARKER in text
        ]
        assert len(gates) == 1, (
            f"{manifest.name}: expected exactly one gate director carrying "
            f"{GATE_SEED_MARKER!r} or {GATE_ARM_MARKER!r}, found "
            f"{sorted(str(path.relative_to(REPO_ROOT)) for path in gates)}"
        )
        gate = gates[0]
        armed = _armed_names(texts[gate])

        for path, text in texts.items():
            if path == gate:
                continue
            reserved = _paid_reserved_names(text)
            paid_reservations += len(reserved)
            unarmed = sorted(reserved - armed)
            assert not unarmed, (
                f"{manifest.name}: {path.relative_to(REPO_ROOT)} books paid work "
                f"under {unarmed}, which {gate.relative_to(REPO_ROOT)} never "
                "arms — the first-paid-use guard trips on approved work. Tool "
                f"names that gate does arm: {sorted(armed & vocabulary)}"
            )

    assert paid_reservations >= MIN_PAID_RESERVATIONS, (
        f"discovered only {paid_reservations} paid ledger reservations across "
        f"{MIN_EPISODE_PIPELINES}+ pipelines — the extractor is broken, not the "
        "rollout"
    )

    protocol = _read("skills/meta/checkpoint-protocol.md")
    assert "One name per line of spend" in protocol


def test_no_or_estimated_fallback_survives_in_ledger_blocks() -> None:
    """`result.cost_usd or estimated_usd` books the estimate on a FAILED call,
    and budget_spent_usd counts failed entries — phantom spend that can block
    the real retry in cap mode."""
    for path in _pipeline_skill_files():
        text = path.read_text(encoding="utf-8")
        assert "result.cost_usd or estimated_usd" not in text, (
            f"{path.relative_to(REPO_ROOT)} still books phantom spend on failure"
        )

    for relative_path in LEDGER_BOOKING_FILES:
        text = _read(relative_path)
        assert "NEVER substitute the estimate on failure" in text, (
            f"{relative_path} is missing the canonical booking block"
        )


def test_placeholder_refund_rationale_is_truthful() -> None:
    """An `estimated` entry does not consume budget — usable_budget_usd
    subtracts only reserved + spent. The refund loop is ledger hygiene."""
    for path in _pipeline_skill_files():
        text = path.read_text(encoding="utf-8")
        assert "double-counting against tracker.usable_budget_usd" not in text, (
            f"{path.relative_to(REPO_ROOT)} repeats the false double-count rationale"
        )

    for pipeline in ("explainer", "cinematic", "animation"):
        text = _read(f"skills/pipelines/{pipeline}/proposal-director.md")
        assert "does NOT consume budget" in text
        assert "Never RESERVE a placeholder" in text


def test_doc_montage_music_examples_carry_duration_seconds() -> None:
    """music_gen.estimate_cost raises ValueError without duration_seconds, so
    an example that omits it is an instruction to crash."""
    import re

    for relative_path in (
        "skills/pipelines/documentary-montage/asset-director.md",
        "skills/pipelines/documentary-montage/idea-director.md",
    ):
        text = _read(relative_path)
        blocks = [
            block for block in re.findall(r"```python\n(.*?)```", text, re.DOTALL)
            if "music_gen.estimate_cost" in block
        ]
        assert blocks, f"{relative_path} has no music_gen.estimate_cost example"
        for block in blocks:
            dict_literals = re.findall(r"=\s*\{(.*?)\n\}", block, re.DOTALL)
            dict_literals += re.findall(r"=\s*\{([^\n}]*)\}", block)
            assert any('"duration_seconds"' in literal for literal in dict_literals), (
                f"{relative_path}: the music_gen inputs dict omits duration_seconds"
            )


def test_checkpoint_protocol_has_stranded_reservation_recovery() -> None:
    """A crash between reserve() and reconcile() strands budget. Resume must
    sweep for it through the tracker's own API, not a hand-rolled status
    comprehension that would miss `estimated` orphans."""
    protocol = _read("skills/meta/checkpoint-protocol.md")
    assert "### Cost Ledger Governance (shared)" in protocol
    governance = protocol.split("### Cost Ledger Governance (shared)", 1)[1]
    assert "non_terminal_entries()" in governance
    assert "budget_tradeoff" in governance
    assert "CostLogCorruptedError" in governance
    assert "CostTracker.reconstruct_from_snapshot" in governance
    # Never instruct deleting or recreating the ledger.
    assert "never delete the ledger" in governance
    # Step 7 must actually route the agent here.
    assert "**Sweep the ledger**" in protocol


def test_ledger_canon_headings_are_uniform() -> None:
    """D0's markers: Workstream G and the six Wave-3 pipelines discover the
    canonical blocks by heading suffix, so no file may carry a variant."""
    for relative_path in (
        "skills/pipelines/hybrid/idea-director.md",
        "skills/pipelines/avatar-spokesperson/idea-director.md",
        "skills/pipelines/documentary-montage/idea-director.md",
    ):
        assert "Compute Budget And Seed The Cost Ledger" in _read(relative_path)

    for relative_path in (
        "skills/pipelines/explainer/proposal-director.md",
        "skills/pipelines/cinematic/proposal-director.md",
        "skills/pipelines/animation/proposal-director.md",
    ):
        assert "On Approval — Arm the Tracker" in _read(relative_path)

    for relative_path in LEDGER_BOOKING_FILES:
        if relative_path.endswith("asset-director.md"):
            assert "Ledger Discipline For Every Paid Call" in _read(relative_path)

    for pipeline in (
        "explainer", "avatar-spokesperson", "hybrid",
        "cinematic", "animation", "documentary-montage",
    ):
        text = _read(f"skills/pipelines/{pipeline}/compose-director.md")
        assert "Ledger Round-Trip For The Render" in text, (
            f"{pipeline} compose-director lacks the round-trip marker"
        )
        assert "Cost Track The Render" not in text, (
            f"{pipeline} compose-director still carries the pre-normalization heading"
        )


# --- Workstream F: docs/intent/context-cost-spec.md + docs/ARCHITECTURE.md -----
#
# In this repo instruction Markdown is runtime code: an agent reads
# context-cost-spec.md section 2 and does what it says. These five tests make
# the doc executable-verified rather than eyeballed.

CONTEXT_COST_SPEC = "docs/intent/context-cost-spec.md"


def _context_cost_section_two() -> str:
    """The text of `### 2. The judgment note`, up to the next `### ` heading."""
    spec = _read(CONTEXT_COST_SPEC)
    match = re.search(
        r"^### 2\.[^\n]*\n(.*?)(?=^### )", spec, re.DOTALL | re.MULTILINE
    )
    assert match, (
        f"{CONTEXT_COST_SPEC} no longer has a `### 2.` section followed by a "
        "`### 3.` heading — the judgment-note guidance the pipeline depends on"
    )
    return match.group(1)


def test_context_cost_spec_judgment_example_is_schema_valid() -> None:
    """The doc's judgment-note example must validate against the LIVE schema.

    Section 2 tells agents to carry exactly this object as the `decision_log`
    artifact of a gate checkpoint. If the schema tightens (or the example
    drifts), the instruction becomes a recipe for a rejected checkpoint write
    — so the example is parsed and validated here, never merely read."""
    from schemas.artifacts import validate_artifact

    section = _context_cost_section_two()
    fences = re.findall(r"```json\n(.*?)```", section, re.DOTALL)
    assert fences, (
        f"{CONTEXT_COST_SPEC} section 2 no longer carries a ```json example of "
        "the decision_log artifact"
    )
    parsed = json.loads(fences[0])
    validate_artifact("decision_log", parsed)


def test_context_cost_spec_never_instructs_the_artifacts_side_file() -> None:
    """The spec was itself the writer of the ask-jess fork: it told agents to
    hand-append `projects/<id>/artifacts/decision_log.json`, which Backlot
    prefers over the canonical log. Nothing in the codebase writes that file;
    the instruction must never come back."""
    spec = _read(CONTEXT_COST_SPEC)
    forbidden = "append to `projects/<id>/artifacts/decision_log.json`"
    assert forbidden not in spec, (
        f"{CONTEXT_COST_SPEC} instructs hand-appending the artifacts side file "
        "again — that is the fork Rollout step 2 had to backfill"
    )

    section = _context_cost_section_two()
    assert "Never hand-write" in section, (
        f"{CONTEXT_COST_SPEC} section 2 dropped the explicit "
        "`Never hand-write` prohibition on the artifacts side file"
    )
    assert "write_checkpoint()" in section, (
        f"{CONTEXT_COST_SPEC} section 2 no longer routes judgment state "
        "through write_checkpoint() — the only supported write path"
    )


def test_context_cost_spec_status_agrees_with_agent_guide() -> None:
    """Two authoritative-in-conflict instruction files is the defect: the spec
    read `proposed, awaiting go-ahead` / `HELD` while AGENT_GUIDE.md already
    shipped the rule. Both sides of the cross-reference are pinned, so deleting
    either section fails here."""
    spec = _read(CONTEXT_COST_SPEC)
    assert "awaiting go-ahead" not in spec, (
        f"{CONTEXT_COST_SPEC} is marked awaiting go-ahead while AGENT_GUIDE.md "
        "already ships the rule"
    )
    assert "**HELD**" not in spec, (
        f"{CONTEXT_COST_SPEC} still marks a rollout step HELD after it landed"
    )
    assert "Compact at closed gates" in spec, (
        f"{CONTEXT_COST_SPEC} no longer names the AGENT_GUIDE.md section that "
        "carries its rule"
    )

    guide = _read("AGENT_GUIDE.md")
    assert "### Compact at closed gates" in guide, (
        "AGENT_GUIDE.md lost the `### Compact at closed gates` section that "
        f"{CONTEXT_COST_SPEC} rollout step 3 cites as landed"
    )


CHECKPOINT_MODULE = "lib/checkpoint.py"
ANCHORED_SYMBOLS = ("write_checkpoint", "_merge_decision_log")


def _def_span(source_lines: list[str], symbol: str) -> tuple[int, int]:
    """1-indexed (first, last) line of top-level `def <symbol>` in the module.

    The span runs from the `def` line to the line before the next top-level
    `def`/`class`/decorator (or EOF), trailing blank lines trimmed."""
    start = None
    for index, line in enumerate(source_lines, start=1):
        if line.startswith(f"def {symbol}(") or line.startswith(
            f"async def {symbol}("
        ):
            start = index
            break
    assert start is not None, (
        f"{CHECKPOINT_MODULE} no longer defines a top-level `{symbol}` — "
        f"{CONTEXT_COST_SPEC} anchors it"
    )

    end = len(source_lines)
    for index in range(start + 1, len(source_lines) + 1):
        line = source_lines[index - 1]
        if re.match(r"^(def |async def |class |@)", line):
            end = index - 1
            break
    while end > start and not source_lines[end - 1].strip():
        end -= 1
    return start, end


def _spec_checkpoint_anchors() -> dict[str, list[int]]:
    """Every `lib/checkpoint.py:NNN` / `#LNNN` anchor in the spec, attributed
    to the symbol named nearest before it — so the two anchored definitions are
    checked independently even where one paragraph mentions both."""
    spec = _read(CONTEXT_COST_SPEC)
    mentions = [
        (match.start(), symbol)
        for symbol in ANCHORED_SYMBOLS
        for match in re.finditer(re.escape(symbol), spec)
    ]
    mentions.sort()

    found: dict[str, list[int]] = {symbol: [] for symbol in ANCHORED_SYMBOLS}
    for anchor in re.finditer(r"lib/checkpoint\.py[:#]L?(\d+)", spec):
        owner = None
        for position, symbol in mentions:
            if position < anchor.start():
                owner = symbol
            else:
                break
        if owner is not None:
            found[owner].append(int(anchor.group(1)))
    return found


def test_context_cost_spec_checkpoint_anchors_are_fresh() -> None:
    """Drift guard: the spec's line anchors must land INSIDE the symbol named.

    Both sides are computed at test time — the real def spans are re-derived
    from lib/checkpoint.py, the anchors are re-read from the doc. Nothing is
    hardcoded, so an unrelated insertion above these defs cannot fail CI, and
    the failure message hands over the fresh number to paste in.

    Span-checking rather than exact-line pinning is the deliberate middle:
    exact coupling would redden this docs test on every edit to the repo's
    most-churned core module."""
    source_lines = _read(CHECKPOINT_MODULE).splitlines()
    anchors = _spec_checkpoint_anchors()

    for symbol in ANCHORED_SYMBOLS:
        start, end = _def_span(source_lines, symbol)
        cited = anchors[symbol]
        assert cited, (
            f"{CONTEXT_COST_SPEC} no longer anchors {symbol} — it lives at "
            f"{CHECKPOINT_MODULE}:{start} (span :{start}-:{end})"
        )
        for line_number in cited:
            assert start <= line_number <= end, (
                f"{CONTEXT_COST_SPEC} anchors {symbol} at "
                f"{CHECKPOINT_MODULE}:{line_number}, outside its span "
                f"[:{start}, :{end}] — the anchor rotted. Fresh number: "
                f":{start} (link fragment #L{start})"
            )


def test_architecture_doc_budget_matches_config() -> None:
    """ARCHITECTURE.md documented a $10.00 default long after config.yaml moved
    to 15.00. B4 made config the single source, so the expected value is loaded
    live here — no literal in the test, and any future bump reddens this until
    the doc follows."""
    from lib.config_model import OpenMontageConfig

    total = OpenMontageConfig.load().budget.total_usd
    doc = _read("docs/ARCHITECTURE.md")

    assert f"default: ${total:.2f}" in doc, (
        "docs/ARCHITECTURE.md Controls bullet does not document the configured "
        f"default budget — config.yaml budget.total_usd is {total:.2f}, so the "
        f"bullet must read `default: ${total:.2f}`"
    )
    assert f"total_usd: {total:.2f}" in doc, (
        "docs/ARCHITECTURE.md config.yaml excerpt is out of step with the real "
        f"config.yaml — it must read `total_usd: {total:.2f}`"
    )
    assert "budget.total_usd` in `config.yaml`" in doc, (
        "docs/ARCHITECTURE.md states a number without naming config.yaml as its "
        "single source — that is the divergence class B4 closed"
    )


# ----------------------------------------------------------------------
# reel-batch (#49e): per-reel booking, the pinned cutaway route, and the
# one-dict rule that makes the pin stick.
# ----------------------------------------------------------------------


def _python_fences(text: str, containing: str) -> list[str]:
    """Every ```python fence in `text` whose body carries `containing`."""
    return [
        block
        for block in re.findall(r"```python\n(.*?)```", text, re.DOTALL)
        if containing in block
    ]


def _parse_fence(block: str, relative_path: str):
    """`ast.parse` a doc fence with an error that names the file.

    A fence excerpted at an indent raises a bare stdlib IndentationError whose
    line numbers refer to nothing the reader can see.
    """
    import ast
    import textwrap

    try:
        return ast.parse(textwrap.dedent(block))
    except SyntaxError as e:  # IndentationError is a subclass
        raise AssertionError(
            f"{relative_path}: a python fence does not parse ({e.msg} at fence "
            f"line {e.lineno}). Doc examples in this file are policed by ast, "
            f"so they must be complete, valid, top-level Python."
        ) from None


def _call_arg_name(tree, receiver: str, attr: str, relative_path: str) -> str:
    """The single dict-valued name passed to `<receiver>.<attr>(...)`.

    Accepts the positional and keyword spellings; anything that is not a bare
    name — an inline literal, a call, a comprehension — is the defect.
    """
    import ast

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == receiver
    ]
    assert len(calls) == 1, (
        f"{relative_path}: expected exactly one {receiver}.{attr} call in the "
        f"booking fence, found {len(calls)}. Two booking examples in one fence "
        f"cannot both be checked; split them into separate fences."
    )
    args = list(calls[0].args) + [kw.value for kw in calls[0].keywords]
    names = [a for a in args if isinstance(a, ast.Name)]
    assert names, (
        f"{relative_path}: {receiver}.{attr} is passed a literal or an "
        f"expression, not the shared inputs name — an inline dict IS a second "
        f"dict, which is how a pinned estimate becomes an unpinned call."
    )
    return names[0].id


BOOKING_FENCE = "skills/pipelines/reel-batch/asset-director.md"


def test_reel_batch_books_one_ledger_entry_per_reel() -> None:
    """The divergence from the batching rule, policed where it is instructed.

    A batch entry has ONE status, and an aborted batch has two outcomes — so
    no settlement of it is honest (see
    tests/tools/test_cost_tracker_governance.py's
    test_reel_batch_single_entry_cannot_reconcile_a_partial_batch, which proves
    that property). This asserts the instructions actually follow it: the
    booked `operation` must vary per reel, which means an f-string carrying the
    cut or reel id, not a constant naming the whole batch.
    """
    import ast

    text = _read(BOOKING_FENCE)
    blocks = _python_fences(text, "tracker.estimate(")
    assert blocks, f"{BOOKING_FENCE} has no ledger booking example"

    paid, free = [], []
    for block in blocks:
        tree = _parse_fence(block, BOOKING_FENCE)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "estimate"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "tracker"
                and len(node.args) >= 3
            ):
                continue
            amount = node.args[2]
            is_free = isinstance(amount, ast.Constant) and amount.value == 0
            (free if is_free else paid).append(node.args[1])

    assert paid, f"{BOOKING_FENCE}: no paid tracker.estimate(tool, operation, usd) call"

    # A PAID entry must name one reel. This is the divergence from the batching
    # rule, and it is only justified where an entry can actually diverge.
    for operation in paid:
        assert isinstance(operation, ast.JoinedStr), (
            f"{BOOKING_FENCE}: a paid booking's operation is a constant "
            f"({ast.dump(operation)[:80]}), so one entry stands for the whole "
            f"batch. It must interpolate the reel or cut id — a partial batch "
            f"cannot be settled honestly through a single entry."
        )
        interpolated = "".join(
            ast.dump(v) for v in operation.values if isinstance(v, ast.FormattedValue)
        )
        assert "cut_id" in interpolated or "reel_id" in interpolated, (
            f"{BOOKING_FENCE}: a paid booking's operation interpolates "
            f"something, but not the reel or cut id — nothing ties the entry to "
            f"one reel."
        )

    # And a $0 tool must NOT: the batching rule still governs everything that
    # cannot diverge, and five free entries where one belongs is ledger noise.
    # Asserting both halves is what keeps this from reading as "per-reel
    # always", which would be the wrong lesson to teach the next pipeline.
    for operation in free:
        assert not isinstance(operation, ast.JoinedStr) or not any(
            marker in "".join(
                ast.dump(v) for v in operation.values
                if isinstance(v, ast.FormattedValue)
            )
            for marker in ("cut_id", "reel_id")
        ), (
            f"{BOOKING_FENCE}: a $0.00 booking is itemised per reel. The "
            f"batching rule governs anything that cannot diverge — per-reel "
            f"booking is bought by the partial-batch problem, and a free tool "
            f"does not have one."
        )


def test_reel_batch_booking_block_prices_and_executes_one_dict() -> None:
    """The estimate and the call must be the same inputs, by identity.

    This is what stops an estimate divergence: price a pinned route, execute an
    unpinned one, and the ledger records a tenth of what lands on the bill. The
    skill cannot pin the route itself — `CutawayGen` owns that, see below — so
    the ONE thing the instructions must get right is not building, rebinding or
    mutating a second dict between the two calls.

    Parsed with `ast`, not a dict-literal regex. The regex the
    documentary-montage precedent uses (`=\\s*\\{(.*?)\\n\\}` with DOTALL)
    swallows this block's two adjacent dicts into one match, because the first
    closes on the same line as its content — it would pass here for the wrong
    reason.
    """
    import ast

    text = _read(BOOKING_FENCE)
    blocks = _python_fences(text, "cutaway_gen.estimate_cost")
    assert blocks, f"{BOOKING_FENCE} has no cutaway_gen booking block"

    for block in blocks:
        tree = _parse_fence(block, BOOKING_FENCE)
        priced = _call_arg_name(tree, "cutaway_gen", "estimate_cost", BOOKING_FENCE)
        executed = _call_arg_name(tree, "cutaway_gen", "execute", BOOKING_FENCE)
        assert priced == executed, (
            f"{BOOKING_FENCE}: prices {priced!r} and executes {executed!r}. "
            "Two dicts is how a pinned estimate becomes an unpinned call."
        )

        # The window is bounded by THOSE two calls, found by receiver and
        # attribute — not by min() over every `.execute`/`.estimate_cost` in
        # the fence, which an unrelated `tracker.estimate(...)` would move.
        def _lineno(attr: str) -> int:
            return next(
                node.lineno
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == attr
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "cutaway_gen"
            )

        low, high = _lineno("estimate_cost"), _lineno("execute")

        # Rebound, re-keyed, or mutated in place — all three make the executed
        # dict differ from the priced one, and only the first is an ast.Assign
        # to a Name.
        touched: list[int] = []
        for node in ast.walk(tree):
            if not (low < getattr(node, "lineno", 0) < high):
                continue
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    root = target
                    while isinstance(root, (ast.Subscript, ast.Attribute)):
                        root = root.value
                    if isinstance(root, ast.Name) and root.id == priced:
                        touched.append(node.lineno)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"update", "pop", "setdefault", "clear", "popitem"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == priced
            ):
                touched.append(node.lineno)

        assert not touched, (
            f"{BOOKING_FENCE}: {priced!r} is rebound or mutated at fence line(s) "
            f"{touched}, between pricing and execution — the estimate then "
            f"describes a dict that never ran."
        )


def test_reel_batch_booked_flash_seconds_is_always_sub_second() -> None:
    """R8, re-affirmed: the booked flash is SUB-SECOND, and the shortfall
    slot's remainder goes to a neighbouring clip — never to the cutaway.

    W6.2's original defect (`flash_seconds: 0.6` hard-coded against a full
    beat-grid interval) reverts cleanly to a form the two tests above stay
    green on: they only check the estimate and execute payloads are the SAME
    dict, not what value flash_seconds actually holds. This pins the value:
    the expression the fence assigns to `flash_seconds` is extracted and
    evaluated (not merely read as prose) against several shortfall lengths,
    so a regression that sizes the flash off `sf["length_seconds"]` again —
    sub-second for a short shortfall, multi-second for a long one — fails
    here regardless of which length happens to be in the fence's own example.
    """
    import ast

    text = _read(BOOKING_FENCE)
    blocks = _python_fences(text, "cutaway_gen.estimate_cost")
    assert blocks, f"{BOOKING_FENCE} has no cutaway_gen booking block"

    from tools.video.cutaway_gen import DEFAULT_FLASH_SECONDS, MAX_FLASH_SECONDS

    assert MAX_FLASH_SECONDS <= 2.0  # sanity: the tool's own ceiling, not this test's

    checked = 0
    for block in blocks:
        tree = _parse_fence(block, BOOKING_FENCE)
        dict_node = next(
            (
                node for node in ast.walk(tree)
                if isinstance(node, ast.Dict)
                and any(
                    isinstance(key, ast.Constant) and key.value == "flash_seconds"
                    for key in node.keys
                )
            ),
            None,
        )
        if dict_node is None:
            continue  # a fence in this same file with no inputs dict, e.g. the estimate/execute pair
        checked += 1
        value_node = next(
            value
            for key, value in zip(dict_node.keys, dict_node.values)
            if isinstance(key, ast.Constant) and key.value == "flash_seconds"
        )

        # The direct mutant this guards: sizing the flash off the slot length.
        # `sf["length_seconds"]` anywhere in the expression is the shrunk-slot
        # value, and R8 is explicit that value sizes the SHRINK, never the flash.
        dumped = ast.dump(value_node)
        assert "length_seconds" not in dumped, (
            f"{BOOKING_FENCE}: flash_seconds is sized off length_seconds "
            f"({ast.dump(value_node)!r}) — R8 says length_seconds sizes "
            "scene-director's shrink, not this stage's flash"
        )

        expr = ast.fix_missing_locations(ast.Expression(body=value_node))
        code = compile(expr, "<flash_seconds>", "eval")

        for length_seconds in (0.3, 0.6, 1.94, 5.0, 9.8):
            sf = {"length_seconds": length_seconds}
            booked = eval(
                code,
                {
                    "DEFAULT_FLASH_SECONDS": DEFAULT_FLASH_SECONDS,
                    "MAX_FLASH_SECONDS": MAX_FLASH_SECONDS,
                    "sf": sf,
                    "min": min,
                    "max": max,
                },
            )
            assert booked <= 1.0, (
                f"{BOOKING_FENCE}: a {length_seconds}s shortfall slot books "
                f"flash_seconds={booked} — R8 requires sub-second (<= 1.0) "
                "regardless of the slot's own length"
            )

    assert checked, f"{BOOKING_FENCE}: no fence sets flash_seconds — the sweep is broken"


def test_reel_batch_cutaway_prices_and_runs_the_same_pinned_object() -> None:
    """The pin lives in the tool, not in the instructions — deliberately.

    A skill that had to pass `allowed_providers` itself is a skill that can
    forget to, and an absent pin does not raise: `VideoSelector.estimate_cost`
    returns $0.00 and the scorer routes to whatever ranks top. A $0.00 estimate
    is exempt from both approval guards, so the omission would seed an
    unguarded paid line.

    Asserted by RUNNING the path with the selector stubbed, and comparing the
    two payloads by object identity. An earlier version compared the ast Name
    passed to each call, which a `payload.pop("allowed_providers")` between
    them satisfies perfectly.
    """
    import shutil
    import subprocess

    from tools.base_tool import ToolResult
    from tools.video import cutaway_gen as cutaway_module
    from tools.video.cutaway_gen import CUTAWAY_PROVIDER_PIN, CutawayGen

    if shutil.which("ffmpeg") is None:
        import pytest as _pytest
        _pytest.skip("ffmpeg required to stand in for a generated cutaway")

    assert CUTAWAY_PROVIDER_PIN, "the cutaway provider pin is empty — see docstring"

    seen: dict[str, object] = {}

    class _RecordingSelector:
        def estimate_cost(self, payload):
            seen["priced"] = payload
            return 0.10

        def execute(self, payload):
            seen["executed"] = payload
            output = Path(payload["output_path"])
            output.parent.mkdir(parents=True, exist_ok=True)
            # A real clip, because cutaway_gen trims what it gets back.
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", "color=c=black:s=64x114:r=30", "-t", "2",
                 "-pix_fmt", "yuv420p", str(output)],
                check=True, timeout=60,
            )
            return ToolResult(success=True, data={"output_path": str(output)},
                              cost_usd=0.10)

    original = cutaway_module.VideoSelector
    cutaway_module.VideoSelector = _RecordingSelector
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            result = CutawayGen().execute({
                "prompts": ["chalk dust drifting through a hard side light, macro"],
                "flash_seconds": 0.6,
                "cache_dir": f"{temp_dir}/cache",
                "output_dir": f"{temp_dir}/out",
            })
    finally:
        cutaway_module.VideoSelector = original

    assert result.success, result.error
    assert "priced" in seen and "executed" in seen, "the selector was never called"
    assert seen["priced"] is seen["executed"], (
        "the payload priced and the payload executed are different objects — "
        "the selector stamps an estimate divergence when they differ, and here "
        "they can"
    )
    assert seen["executed"]["allowed_providers"] == list(CUTAWAY_PROVIDER_PIN)
    assert seen["executed"]["preferred_provider"] == CUTAWAY_PROVIDER_PIN[0]


# ----------------------------------------------------------------------
# Anchor drift, across every doc — not just the one that had a test
# ----------------------------------------------------------------------
#
# The test above polices context-cost-spec.md alone. Everything else that
# cites `lib/checkpoint.py:NNN` or `lib/corpus.py:NNN` drifted unwatched, and
# a cleanup pass that mechanically added +1 to each stale number produced
# three anchors that were still wrong — the arithmetic was applied to a
# number that had already rotted. A guard that covers one file out of six is
# the same shape as a default-deny check on an optional field.

ANCHOR_MODULES = ("lib/checkpoint.py", "lib/corpus.py")

# The repo's citation convention: the symbol, then the anchor in parens right
# after it — `write_checkpoint` (`lib/checkpoint.py:621`). Only that form
# states, checkably, "you will find this symbol at this line". An anchor that
# merely shares a line with a symbol name is a region reference, and an anchor
# that PRECEDES its symbol is usually a historical quote of a number already
# corrected — epic1-review-fixes-spec.md is full of both. Matching the
# convention rather than the line keeps this guard quiet enough to survive.
_ANCHOR_CITATION = re.compile(
    r"`(?P<symbol>[A-Za-z_]\w*)[^`]*`"          # `symbol` or `symbol(args)`
    r"[^`\n]{0,3}"                               # at most a space or two
    r"\(`(?P<module>[\w/]+\.py):(?P<start>\d+)(?:-:?(?P<end>\d+))?`"
)


def _anchor_docs() -> list[str]:
    """Every tracked doc that cites a line in one of ANCHOR_MODULES."""
    roots = [REPO_ROOT / "docs" / "intent", REPO_ROOT / "skills" / "pipelines"]
    docs = []
    for root in roots:
        for path in sorted(root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            if any(f"{module}:" in text for module in ANCHOR_MODULES):
                docs.append(str(path.relative_to(REPO_ROOT)))
    return docs


# Every `lib/checkpoint.py:NNN` / `lib/corpus.py:NNN` mention, in or out of the
# convention. Used only to count what the convention regex above declines to
# examine — the guard fails on nothing this matches.
_ANY_ANCHOR = re.compile(
    r"(?:" + "|".join(re.escape(module) for module in ANCHOR_MODULES) + r"):\d+"
)


def _top_level_symbols(source_lines: list[str]) -> dict[str, tuple[int, int]]:
    """Every top-level `def`/`class` in a module, mapped to its 1-indexed span.

    The span starts at the first decorator line, not at the `def` — a doc that
    anchors `@dataclass class ClipRecord` at the decorator is citing the
    definition, and failing that would be pedantry rather than drift."""
    starts: list[tuple[int, str]] = []
    for index, line in enumerate(source_lines, start=1):
        match = re.match(r"^(?:async def|def|class)\s+(\w+)", line)
        if not match:
            continue
        first = index
        while first > 1 and source_lines[first - 2].lstrip().startswith("@"):
            first -= 1
        starts.append((first, match.group(1)))

    spans: dict[str, tuple[int, int]] = {}
    for position, (first, name) in enumerate(starts):
        end = starts[position + 1][0] - 1 if position + 1 < len(starts) else len(source_lines)
        while end > first and not source_lines[end - 1].strip():
            end -= 1
        spans.setdefault(name, (first, end))
    return spans


def _scan_anchors() -> tuple[list[str], int, int]:
    """`(rotted, checked, skipped)` over every anchor doc.

    `checked` counts anchors in the citation convention whose symbol resolves in
    the module — the only ones this guard can and does verify. `skipped` counts
    every other `<module>:NNN` mention: region references and historical quotes,
    deliberately not failed, but counted so the caller can say how much of the
    file went unexamined rather than implying it checked all of it.
    """
    sources = {module: _read(module).splitlines() for module in ANCHOR_MODULES}
    symbols = {module: _top_level_symbols(lines) for module, lines in sources.items()}

    rotted: list[str] = []
    checked = 0
    skipped = 0

    for doc in _anchor_docs():
        for line_number, line in enumerate(_read(doc).splitlines(), start=1):
            here = 0
            for match in _ANCHOR_CITATION.finditer(line):
                module = match.group("module")
                symbol = match.group("symbol")
                if module not in symbols or symbol not in symbols[module]:
                    continue
                first, last = symbols[module][symbol]
                checked += 1
                here += 1
                for group in ("start", "end"):
                    cited = match.group(group)
                    if cited is None:
                        continue
                    if not first <= int(cited) <= last:
                        rotted.append(
                            f"{doc}:{line_number} anchors `{symbol}` at "
                            f"{module}:{cited}, outside its span "
                            f"[:{first}, :{last}] — fresh number :{first}"
                        )
            skipped += len(_ANY_ANCHOR.findall(line)) - here

    return rotted, checked, skipped


def _anchor_report(rotted: list[str], checked: int, skipped: int) -> str:
    """The guard's own summary, message and scope in one place.

    The count of what was NOT examined belongs beside the count of what was:
    on its own the checked count reads as coverage of the file, when the
    convention matches only a minority of the anchors these docs carry.
    """
    return (
        f"{len(rotted)} rotted anchor(s) of {checked} checked across "
        f"{len(_anchor_docs())} docs; {skipped} further anchor(s) are outside "
        f"the citation convention and were not examined:\n  "
        + "\n  ".join(rotted)
    )


def test_every_doc_anchor_into_checkpoint_and_corpus_is_fresh() -> None:
    """Drift guard for `lib/checkpoint.py:NNN` anchors in EVERY doc.

    Scoped to the citation convention above, so what it checks is exactly what
    a doc actually promises the reader. Anchors outside that form are counted
    and reported alongside the checked count — never failed, and never left
    out of the tally either: on this repo the convention covers a small
    minority of the anchors present, and a summary that reported only the
    checked ones read as full coverage of the file."""
    rotted, checked, skipped = _scan_anchors()
    assert not rotted, _anchor_report(rotted, checked, skipped)


def test_the_anchor_guard_says_how_many_anchors_it_did_not_examine() -> None:
    """The docstring above promises the skipped anchors are counted and reported.

    They were not: the message named `checked` alone, and `checked` counts only
    the in-convention anchors, so a green run gave no signal that most anchors
    in these docs went unexamined. The narrow scope is deliberate — this test
    pins the disclosure, not a wider check.
    """
    rotted, checked, skipped = _scan_anchors()

    # Recount independently of _scan_anchors' per-line bookkeeping.
    total = sum(len(_ANY_ANCHOR.findall(_read(doc))) for doc in _anchor_docs())
    assert checked + skipped == total, (
        f"the guard's own tally ({checked} checked + {skipped} skipped) does not "
        f"account for the {total} anchors present"
    )

    report = _anchor_report(rotted, checked, skipped)
    assert f"{checked} checked" in report
    assert f"{skipped} further anchor(s)" in report
    assert "not examined" in report


# ----------------------------------------------------------------------
# An instruction may not name a decision category the schema rejects
# ----------------------------------------------------------------------


def test_every_decision_category_the_instructions_name_is_in_the_schema() -> None:
    """AGENT_GUIDE.md told agents to log pre-authorisation as
    `category: "approval_policy"`; the schema's enum did not contain it, so an
    agent that followed the instruction exactly got a
    CheckpointValidationError and could not write the gate at all.

    Both halves read as authoritative and neither mentioned the other, which is
    why it survived: the guide is prose, the enum is data, and nothing compared
    them. Found by running the pipeline end to end rather than by reading
    either file.
    """
    schema = json.loads(_read("schemas/artifacts/decision_log.schema.json"))
    allowed = set(
        schema["properties"]["decisions"]["items"]["properties"]["category"]["enum"]
    )

    # `category: "<name>"` is how every instruction file spells one.
    pattern = re.compile(r'`?category`?\s*:\s*"([a-z_]+)"')
    named: dict[str, list[str]] = {}
    for doc in ["AGENT_GUIDE.md", *sorted(
        str(p.relative_to(REPO_ROOT))
        for p in (REPO_ROOT / "skills").rglob("*.md")
    )]:
        for match in pattern.finditer(_read(doc)):
            named.setdefault(match.group(1), []).append(doc)

    assert named, "no decision categories found in the instructions — regex rotted"
    unknown = {name: docs for name, docs in named.items() if name not in allowed}
    assert not unknown, (
        "instruction files name decision categories the schema rejects, so an "
        "agent following them writes an invalid artifact:\n  "
        + "\n  ".join(f"{name!r} named by {sorted(set(docs))}" for name, docs in unknown.items())
    )


# --- reel-batch: the per-reel caption axes must stay wired ---------------------

def test_reel_batch_compose_still_reads_the_per_reel_motion() -> None:
    """`animation_preset` is declared in a schema and authored by a director.

    Neither of those makes it reach a render. The `batch_look` scar is exactly
    this shape — a property declared, validated and carried, whose consumer was
    never wired, so five reels materialised with `batch_look: None` and nothing
    was invalid enough for a validator to notice. Compose's burn fence is the
    only consumer, so "compose quietly stopped reading it" has to be a red test
    rather than a silent pass.
    """
    compose = REPO_ROOT / "skills" / "pipelines" / "reel-batch" / "compose-director.md"
    text = compose.read_text(encoding="utf-8")

    assert 'entry.get("animation_preset")' in text, (
        "compose-director no longer reads animation_preset off the reel_plan entry"
    )
    assert 'burn_inputs["animation_preset"]' in text, (
        "compose-director reads animation_preset but never passes it to the burn"
    )
    # The default it must NOT acquire: resolution lives in TypeScript, once.
    # Checked inside the code fences only — the prose deliberately quotes the
    # forbidden form in order to forbid it.
    fences = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
    assert fences, "compose-director has no python fences left to check"
    for fence in fences:
        assert 'entry.get("animation_preset", ' not in fence, (
            "compose-director defaults animation_preset in Python — that puts "
            "the preset->motion table in two languages with nothing pinning "
            "them equal"
        )


def test_reel_batch_compose_never_defaults_animation_preset_to_pop() -> None:
    """W13.1: decision #12 puts the preset->motion table in TypeScript ONLY,
    "because a Python copy would put one table in two languages with nothing
    pinning them equal". `entry.get("animation_preset") or "pop"` re-creates
    exactly that table in Python — and it is NOT caught by the neighbouring
    test's `entry.get("animation_preset", ` check, because it never passes a
    default arg to `.get()`; it ORs the return value instead. Once that
    mutant lands, an absent preset silently means "pop" rather than "let the
    preset decide", and this is the only assertion that would notice.
    """
    compose = REPO_ROOT / "skills" / "pipelines" / "reel-batch" / "compose-director.md"
    text = compose.read_text(encoding="utf-8")

    fences = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
    burn_fences = [f for f in fences if 'burn_inputs["animation_preset"]' in f]
    assert burn_fences, "compose-director has no burn fence that sets animation_preset"

    for fence in burn_fences:
        assert 'if entry.get("animation_preset"):' in fence, (
            "compose-director must read animation_preset under an `if`, not "
            "assign it unconditionally with a fallback baked in"
        )
        assert 'or "pop"' not in fence, (
            'compose-director defaults animation_preset to "pop" in Python — '
            "decision #12 puts the preset->motion table in TypeScript only"
        )
        assert 'burn_inputs["animation_preset"] = entry["animation_preset"]' in fence, (
            "compose-director must pass animation_preset through unchanged, by "
            "direct subscript, once the `if` above has confirmed it is present"
        )


def test_reel_batch_directors_only_author_valid_animation_presets() -> None:
    """W13.2: a literal `"animation_preset": "<value>"` in a director's own
    fence is an instruction to author that exact string into reel_plan.
    `"slide"` is not in `RemotionCaptionBurn.ANIMATION_PRESETS`, so an agent
    following the instruction authors an invalid reel_plan entry and only
    fails at runtime schema validation, mid-sitting through the batch.

    Discovery is dynamic: every python fence under skills/pipelines/reel-batch/
    is swept, so a literal added to a director this test does not name is
    still checked.
    """
    from tools.video.remotion_caption_burn import RemotionCaptionBurn

    literal_pattern = re.compile(r'"animation_preset":\s*"([a-zA-Z_]+)"')
    found: list[tuple[Path, str]] = []
    reel_batch = REPO_ROOT / "skills" / "pipelines" / "reel-batch"
    for path in sorted(reel_batch.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for block in re.findall(r"```python\n(.*?)```", text, re.DOTALL):
            for literal in literal_pattern.findall(block):
                found.append((path, literal))

    assert found, (
        f"no literal `\"animation_preset\": \"<value>\"` found under {reel_batch} "
        "— the sweep is broken, not the rollout"
    )

    invalid = [
        (path.relative_to(REPO_ROOT), literal) for path, literal in found
        if literal not in RemotionCaptionBurn.ANIMATION_PRESETS
    ]
    assert not invalid, (
        "reel-batch director(s) author an animation_preset literal outside "
        f"RemotionCaptionBurn.ANIMATION_PRESETS {RemotionCaptionBurn.ANIMATION_PRESETS}: "
        + ", ".join(f"{path}: {literal!r}" for path, literal in invalid)
    )


def test_g6_gate_still_checks_motion_parity() -> None:
    """W13.3: with W13.1, this bullet is the whole hole — edit authors one
    value, compose could silently substitute another, and nothing at the gate
    compares them unless this bullet is actually there. `6578149` hardened the
    compose FENCE (killing the reel_id mutant) but left this GATE unpinned;
    deleting the bullet was a one-line diff that the entire suite let through.
    """
    executive_producer = (
        REPO_ROOT / "skills" / "pipelines" / "reel-batch" / "executive-producer.md"
    )
    text = executive_producer.read_text(encoding="utf-8")
    assert "G6 — after COMPOSE" in text and "G7 — after PUBLISH" in text, (
        f"{executive_producer.relative_to(REPO_ROOT)} no longer has a G6 gate "
        "bounded by a G7 heading — the section split below is invalid"
    )
    g6 = text.split("G6 — after COMPOSE", 1)[1].split("G7 — after PUBLISH", 1)[0]

    assert "caption_animation" in g6, "G6 dropped the motion-parity bullet entirely"
    assert "reel_plan.animation_preset" in g6, (
        "G6 no longer joins outputs[].caption_animation against "
        "reel_plan.animation_preset"
    )
    assert "caption_degraded" in g6, (
        "G6 no longer excuses a mismatch through the caption_degraded escape "
        "hatch — a degraded SRT-fallback render would fail the gate for a "
        "reason the pipeline itself already explains"
    )
    assert "outputs[].reel_id" in g6, "G6 no longer states the join key"


def test_scene_director_reads_corpus_dir_from_brief_metadata() -> None:
    """Regression for W1.1: scene-director used to open
    `Corpus(PROJECTS_DIR / project_id / "corpus")` — a path nothing under
    tools/ or lib/ writes, since `cb4033c` moved the index to
    `projects/_footage_index/<pool>_<digest>` and updated idea- and
    asset-director but not scene. The pool loaded as zero rows and every cut
    became a false shortfall. The fix is the same form asset-director.md
    already uses.
    """
    scene = REPO_ROOT / "skills" / "pipelines" / "reel-batch" / "scene-director.md"
    text = scene.read_text(encoding="utf-8")

    assert 'Corpus(Path(brief["metadata"]["corpus_dir"]))' in text, (
        "scene-director no longer resolves the corpus through "
        "brief.metadata.corpus_dir — a batch will load a zero-row pool again"
    )
    assert 'PROJECTS_DIR / project_id / "corpus"' not in text, (
        "scene-director opens a corpus path nothing under tools/ or lib/ "
        "ever writes"
    )


def test_publish_director_no_longer_claims_reel_id_is_absent() -> None:
    """Regression for W6.1: publish-director asserted outputs[] carries NO
    reel_id field, citing the exact schema range this branch added it to —
    contradicting compose-director's own (already-fixed) claim about the same
    field. The fix states reel_id is schema-declared and reads it before
    falling back to the filename-stem inference.
    """
    publish = REPO_ROOT / "skills" / "pipelines" / "reel-batch" / "publish-director.md"
    text = publish.read_text(encoding="utf-8")

    assert "carries **no** `reel_id` field" not in text, (
        "publish-director still claims outputs[] lacks reel_id, contradicting "
        "the schema and compose-director"
    )
    assert "schema-declared" in text, (
        "publish-director no longer states that reel_id is schema-declared"
    )
    assert 'rid = out.get("reel_id")' in text, (
        "publish-director must read reel_id off the output before falling "
        "back to the filename-stem inference"
    )


def test_reel_batch_compose_still_records_what_it_rendered() -> None:
    """There is no Python builder for `render_report.outputs[]` anywhere in the
    repo — compose-director's fence is the only author of every field in it.

    So deleting the three caption keys from that fence is a silent no-op: every
    report stays schema-valid (all three are optional), publish still works, and
    both new G6 bullets become permanently vacuous. Verified: stripping them left
    1544 tests green before this assertion existed.
    """
    compose = REPO_ROOT / "skills" / "pipelines" / "reel-batch" / "compose-director.md"
    text = compose.read_text(encoding="utf-8")

    for key in ("reel_id", "caption_animation", "caption_degraded"):
        assert f'entry_out["{key}"]' in text, (
            f"compose-director no longer writes {key} into render_report.outputs[]"
        )
        assert f'"{key}"' in text, f"the outputs[] JSON sample dropped {key}"

    # The prose promises a direct subscript; `.get(..., False)` would report an
    # untouched render as clean.
    assert 'burn.data["degraded"]' in text, (
        "compose-director no longer reads degraded as a direct subscript"
    )


def test_reel_batch_edit_still_authors_both_caption_axes() -> None:
    """G5 requires both on every entry; the schema makes both optional."""
    edit = REPO_ROOT / "skills" / "pipelines" / "reel-batch" / "edit-director.md"
    text = edit.read_text(encoding="utf-8")

    assert '"caption_source": sr["caption_source"]' in text, (
        "edit-director no longer carries caption_source from the script artifact"
    )
    assert '"animation_preset":' in text, (
        "edit-director no longer authors animation_preset on the reel_plan entry"
    )


def test_reel_batch_script_declares_the_caption_source_edit_subscripts() -> None:
    """`edit-director` carries caption_source by DIRECT subscript, so if the
    script stage stops declaring it the batch dies at `edit` with a bare
    KeyError. The two directors are separate files with no compiler between
    them; this test is the join."""
    script = REPO_ROOT / "skills" / "pipelines" / "reel-batch" / "script-director.md"
    edit = REPO_ROOT / "skills" / "pipelines" / "reel-batch" / "edit-director.md"

    assert '"caption_source": "music_bed"' in script.read_text(encoding="utf-8"), (
        "script-director no longer declares caption_source on its reel metadata, "
        "which edit-director subscripts directly"
    )
    assert 'sr["caption_source"]' in edit.read_text(encoding="utf-8")


def test_reel_batch_fence_imports_resolve_against_real_modules() -> None:
    """The broader ask behind W1.1 and W6.4: catch a NameError/TypeError-class
    regression automatically rather than by a verifier reading every fence by
    eye.

    Full execution of an arbitrary reel-batch fence is not generally
    possible: these fences are copy-and-run pseudocode over pipeline state
    (`brief`, `scene_plan`, `corpus`, a live `tracker`, ...) that exists only
    once an agent is actually mid-run, and stubbing all of that would hide
    real bugs behind a fabricated success — worse than not checking. What
    every fence's `import` statements ARE is fully, honestly checkable
    without any pipeline state: `ast`-parsed and resolved against the real
    module tree. A renamed or removed export (`DEFAULT_FLASH_SECONDS`, say)
    breaks every fence that imports it, silently, until an agent actually
    runs the pipeline — this is the automatic version of noticing that.
    """
    import ast
    import importlib

    reel_batch = REPO_ROOT / "skills" / "pipelines" / "reel-batch"
    checked = 0
    for path in sorted(reel_batch.glob("*.md")):
        rel = str(path.relative_to(REPO_ROOT))
        text = path.read_text(encoding="utf-8")
        for fence in re.findall(r"```python\n(.*?)```", text, re.DOTALL):
            if "import " not in fence:
                continue
            tree = _parse_fence(fence, rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    module = importlib.import_module(node.module)
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        assert hasattr(module, alias.name), (
                            f"{rel}: `from {node.module} import {alias.name}` "
                            f"— {node.module} has no attribute {alias.name!r}"
                        )
                        checked += 1
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        importlib.import_module(alias.name)
                        checked += 1

    assert checked >= 10, (
        f"only resolved {checked} imports across {reel_batch} — the sweep is "
        "broken, not the rollout"
    )


def _scene_director_shrink_fence() -> str:
    text = _read("skills/pipelines/reel-batch/scene-director.md")
    # Located by the surrounding claim, not by the formula this test polices —
    # a mutant that changes `flash_length`'s own line must not also make the
    # fence unlocatable, or a reversion fails on "found 0 fences" instead of
    # on the invariant that actually broke.
    fences = _python_fences(text, "the neighbouring operator clip, which extends to cover it")
    assert len(fences) == 1, (
        "skills/pipelines/reel-batch/scene-director.md: expected exactly one "
        f"shrink+extend fence, found {len(fences)}"
    )
    return fences[0]


def _run_shrink_fence(
    slots: list[dict],
    shortfall_index: int,
    ledger=None,
    slot_tail: dict[int, dict] | None = None,
) -> dict:
    """Execute the REAL step-4 shrink+extend fence against synthetic slots.

    `ranked = []` forces the for-loop's `else` — the shortfall path — every
    time, which is the only branch this fence's shrink logic lives in. The
    imports inside the fence (`SegmentAlreadyClaimedError`,
    `DEFAULT_FLASH_SECONDS`, `refuse_media_references`) are real; nothing
    about the shrink math itself is stubbed.

    `ledger` and `slot_tail` are optional and exist for the LAST-slot branch,
    the only one that reaches either name (scene-director.md :257-296): it
    probes and claims against `ledger` and reads the previous cut's tail room
    from `slot_tail`. A caller exercising only the middle-slot branch never
    touches either name, so the defaults are inert — that keeps the existing
    middle-slot test working unchanged. Pass a REAL `ClipLedger`, not a
    stand-in, when a test needs to prove the real no-reuse rule permits (or
    refuses) a claim.
    """
    namespace = {
        "ranked": [],
        "slot": slots[shortfall_index],
        "slots": slots,
        "reel_id": "reel_02",
        "cut_id": f"reel_02-{shortfall_index + 1:02d}",
        "slot_description": "test slot",
        "shortfall": [],
        "planned_clip_ids": set(),
        "ledger": ledger,
        "slot_tail": slot_tail if slot_tail is not None else {},
    }
    exec(compile(_scene_director_shrink_fence(), "<scene-director-shrink-fence>", "exec"), namespace)
    return namespace


def test_scene_director_shrink_extend_absorbs_remainder_on_a_middle_slot() -> None:
    """The documented mechanism (scene-director.md step 6): a shortfall does
    not keep its own full beat-grid interval. It shrinks to the flash length
    and 'the seconds it gives up extend the neighbouring operator clip so the
    reel's total_seconds and its beat grid both hold exactly as planned.'

    Run against the REAL fence, not a paraphrase of it, for a shortfall on a
    middle slot: the shortfall's own duration must equal the flash length,
    the following slot's boundary must absorb exactly the remainder (still
    touching, not overlapping), and the reel's overall span must be
    unchanged.
    """
    from tools.video.cutaway_gen import DEFAULT_FLASH_SECONDS

    slots = [
        {"index": 0, "start_seconds": 0.0, "end_seconds": 2.0},
        {"index": 1, "start_seconds": 2.0, "end_seconds": 4.0},
        {"index": 2, "start_seconds": 4.0, "end_seconds": 6.0},  # the shortfall
        {"index": 3, "start_seconds": 6.0, "end_seconds": 8.0},
        {"index": 4, "start_seconds": 8.0, "end_seconds": 9.8},
    ]
    span_before = (slots[0]["start_seconds"], slots[-1]["end_seconds"])
    original_neighbour_start = slots[3]["start_seconds"]

    result = _run_shrink_fence(slots, shortfall_index=2)

    flash_length = result["flash_length"]
    remainder = result["remainder"]
    assert flash_length <= 1.0, f"flash_length={flash_length} is not sub-second (R8)"

    shortfall_slot = slots[2]
    assert round(shortfall_slot["end_seconds"] - shortfall_slot["start_seconds"], 3) == flash_length, (
        "the shortfall's own duration no longer equals the flash length"
    )
    assert round(original_neighbour_start - slots[3]["start_seconds"], 3) == remainder, (
        "the neighbouring slot's boundary did not absorb exactly the remainder"
    )
    assert shortfall_slot["end_seconds"] == slots[3]["start_seconds"], (
        "the shrunk shortfall and its neighbour no longer touch — a gap or "
        "an overlap opened between them"
    )
    span_after = (slots[0]["start_seconds"], slots[-1]["end_seconds"])
    assert span_after == span_before, (
        f"the reel's overall span moved from {span_before} to {span_after} — "
        "only the internal boundary the shortfall shares with its neighbour "
        "may move"
    )


# scene-director.md's own reel_02 grid (step 2's worked example): 5 slots,
# the last spanning 7.72 -> 9.62 (length 1.9s, so remainder == 1.3s once the
# 0.6s flash is carved out). The last-slot shrink tests below build their
# slots from this grid, not ad-hoc numbers, so the tests and the document
# cannot quietly drift apart.
_REEL_02_GRID = [0.0, 1.94, 3.88, 5.82, 7.72, 9.62]


def _reel_02_slots() -> list[dict]:
    return [
        {"index": i, "start_seconds": _REEL_02_GRID[i], "end_seconds": _REEL_02_GRID[i + 1]}
        for i in range(len(_REEL_02_GRID) - 1)
    ]


def test_scene_director_shrink_extend_last_slot_headroom_claims_abutting_sliver(tmp_path) -> None:
    """The step-4 last-slot branch's HEADROOM path (scene-director.md :257-280).

    When the previous (operator) cut's source has `remainder` more seconds of
    real footage past its current out-point, the fence must claim that
    abutting sliver as a SECOND real `ClipLedger` claim and grow the previous
    cut's TIMELINE span and its SOURCE span *together*. Regress to the old
    defect (decision-log #14) — moving the timeline boundary without a
    matching source claim — and the previous cut plays footage nobody
    reserved: the ledger no longer backs what the reel shows, and nothing
    downstream would notice until gate 2's per-cut coverage assert
    (scene-director.md :545-556) — by which point the shortfall's paid prompt
    has already been authored.

    Runs against a REAL `ClipLedger`, not a stub, so this cannot pass on a
    ledger that would rubber-stamp any claim: `claims_for_reel` and
    `assert_no_reuse()` are read back from the same object the fence claimed
    against.
    """
    from lib.clip_ledger import ClipLedger

    slots = _reel_02_slots()
    ledger = ClipLedger(tmp_path / "clip_ledger.json")
    source = "/tmp/openmontage-test-source.mp4"
    prev_in, prev_out = 10.0, 11.9  # 1.9s claimed == slot 3's own 1.9s timeline span
    ledger.claim(reel_id="reel_02", source=source, in_seconds=prev_in, out_seconds=prev_out,
                 clip_id="prev-clip")
    slot_tail = {3: {"source": source, "take_out": prev_out, "seg_out": 13.5, "clip_id": "prev-clip"}}

    result = _run_shrink_fence(slots, shortfall_index=4, ledger=ledger, slot_tail=slot_tail)
    remainder = result["remainder"]

    assert slots[-1]["end_seconds"] == 9.62, (
        "the reel's total_seconds moved even though the previous cut's "
        "source had headroom to cover the shortfall — the headroom path "
        "must keep the reel at its full approved length"
    )
    assert slots[3]["end_seconds"] == slots[4]["start_seconds"], (
        "a gap or overlap opened between the extended previous cut and the flash"
    )
    prev_timeline_span = round(slots[3]["end_seconds"] - slots[3]["start_seconds"], 3)
    prev_source_span = round(slot_tail[3]["take_out"] - prev_in, 3)
    assert prev_timeline_span == prev_source_span, (
        f"previous cut's timeline span ({prev_timeline_span}s) no longer "
        f"equals its source span ({prev_source_span}s) — this is exactly "
        "the coverage gate 2 asserts at scene-director.md :545-556, and it "
        "is the thing the last-slot branch exists to keep true"
    )
    assert slot_tail[3]["take_out"] == round(prev_out + remainder, 3), (
        "slot_tail's take_out was not advanced to the newly-claimed "
        "out-point — step 8 would then write the OLD, shorter source span "
        "for this cut while the ledger holds the claim for the longer one"
    )
    claims = ledger.claims_for_reel("reel_02")
    assert len(claims) == 2, (
        "the abutting sliver was never actually claimed on the real ledger"
    )
    # Read back WHICH footage the ledger actually reserved, not just how many rows
    # it holds. Every assertion above this one compares the timeline against the
    # fence's OWN bookkeeping (`slot_tail`), so a fence that moved the timeline
    # correctly, recorded take_out correctly, and claimed the WRONG seconds would
    # satisfy all of them — decision-log #14's defect (a plan claiming more than
    # the ledger backs) relocated one level down. The claimed intervals must tile
    # the prev cut's source span exactly: [prev_in, prev_out) + [prev_out, new_out).
    spans = sorted((c["in_seconds"], c["out_seconds"]) for c in claims)
    assert spans == [(prev_in, prev_out), (prev_out, round(prev_out + remainder, 3))], (
        f"the ledger reserved {spans} — not the original cut plus the abutting "
        "sliver the timeline was grown to cover; the scene_plan would then "
        "promise footage no claim backs"
    )
    assert round(spans[-1][1] - spans[0][0], 3) == prev_timeline_span, (
        "the claimed footage, end to end, does not cover the previous cut's "
        "grown timeline span"
    )
    ledger.assert_no_reuse()  # must not raise: two abutting claims on one source are not reuse


def test_scene_director_shrink_extend_last_slot_fallback_ends_reel_early_and_records_it(tmp_path) -> None:
    """The step-4 last-slot branch's FALLBACK path (scene-director.md :281-296).

    When the previous cut's source has no footage left past its out-point,
    the fence must NOT move that cut — it has nothing more to give — and must
    instead let the reel end `remainder` seconds early, flush against the
    unmoved previous slot. Per the operator's ruling on decision-log #14: a
    fallback that ends the reel early WITHOUT the caller being able to record
    the true length is worse than the defect it replaces — it would silently
    ship a reel shorter than what step 8 writes into
    `metadata.reels[].total_seconds` (scene-director.md :293). This test pins
    the exact slot geometry step 8 depends on to record that true length
    correctly — the flash slot's own `end_seconds` IS the reel's real end —
    not merely "no overlap".

    Runs against a REAL `ClipLedger` so "no footage left" is proven by the
    ledger's own bookkeeping (`claims_for_reel` stays at one claim), not
    asserted by construction.
    """
    from lib.clip_ledger import ClipLedger

    slots = _reel_02_slots()
    ledger = ClipLedger(tmp_path / "clip_ledger.json")
    source = "/tmp/openmontage-test-source.mp4"
    prev_in, prev_out = 10.0, 11.9  # 1.9s claimed == slot 3's own 1.9s timeline span
    ledger.claim(reel_id="reel_02", source=source, in_seconds=prev_in, out_seconds=prev_out,
                 clip_id="prev-clip")
    # seg_out == take_out: nothing left past the current claim, so the
    # headroom check's `new_out <= seg_out` can never hold.
    slot_tail = {3: {"source": source, "take_out": prev_out, "seg_out": prev_out, "clip_id": "prev-clip"}}

    result = _run_shrink_fence(slots, shortfall_index=4, ledger=ledger, slot_tail=slot_tail)
    remainder = result["remainder"]

    assert slots[3]["end_seconds"] == 7.72, (
        "the previous cut was moved even though its source has no unclaimed "
        "footage to give — this is the silent overrun decision-log #14 forbids"
    )
    assert slots[-1]["end_seconds"] == round(9.62 - remainder, 3) == 8.32, (
        f"the reel did not end early by exactly the shortfall's remainder "
        f"({remainder}s) — step 8 records THIS value as "
        "metadata.reels[].total_seconds (scene-director.md :293), so a wrong "
        "number here is what actually ships as the reel's real length"
    )
    assert slots[4]["start_seconds"] == slots[3]["end_seconds"], (
        "a gap opened between the shrunk flash and the unmoved previous slot"
    )
    assert len(ledger.claims_for_reel("reel_02")) == 1, (
        "the fallback claimed a sliver anyway — there is no footage behind "
        "the previous cut's out-point to back it, so a second claim here "
        "reserves footage the source does not have"
    )
    prev_timeline_span = round(slots[3]["end_seconds"] - slots[3]["start_seconds"], 3)
    prev_source_span = round(slot_tail[3]["take_out"] - prev_in, 3)
    assert prev_timeline_span == prev_source_span, (
        "the previous cut's timeline span no longer equals its (unchanged) "
        "source span — the fallback must not touch this cut at all"
    )


def test_ep_wall_time_table_matches_the_manifest() -> None:
    """No test caught `pipeline_defs/reel-batch.yaml` saying 45 while
    `executive-producer.md`'s Execution Limits table said 20 and named that
    manifest key as its own source — a healthy first sitting was told to stop
    and escalate mid cold-index. Both numbers are re-read live here, so either
    one drifting away from the other fails; nothing is pinned as a literal in
    this test.
    """
    ep = _read("skills/pipelines/reel-batch/executive-producer.md")
    manifest = yaml.safe_load(_read("pipeline_defs/reel-batch.yaml"))
    manifest_minutes = manifest["orchestration"]["max_wall_time_minutes"]

    match = re.search(
        r"\|\s*Max wall time\s*\|\s*(\d+)\s*min\s*\|\s*"
        r"`orchestration\.max_wall_time_minutes`\s*\|",
        ep,
    )
    assert match, (
        "executive-producer.md's Execution Limits table no longer has a Max "
        "wall time row citing orchestration.max_wall_time_minutes as its source"
    )
    table_minutes = int(match.group(1))
    assert table_minutes == manifest_minutes, (
        f"executive-producer.md's Execution Limits table says {table_minutes} "
        "min but pipeline_defs/reel-batch.yaml's "
        f"orchestration.max_wall_time_minutes is {manifest_minutes} — the "
        "table names that key as its own source, so they must agree"
    )


def test_g3_duration_ceiling_agrees_across_ep_scene_and_script() -> None:
    """G3's per-reel duration ceiling is authored in three separate places —
    the EP's checklist, scene-director's step-9 assert, and script-director's
    window cap — with no shared constant pinning them equal. W6.3 pushed the
    cap upstream specifically so an over-length reel is refused before any
    paid stage spends; that only holds if all three name the same number.
    Deleting the G3 bullet, or drifting any ONE of the three back to a
    different figure (10.0, say) while the others stay put, fails here.
    script-director.md itself states the cap twice (prose, then the
    executable fence); every occurrence there is required to agree too, so a
    drift confined to the fence — the copy that is actually run — cannot hide
    behind an unchanged prose figure.
    """
    ep = _read("skills/pipelines/reel-batch/executive-producer.md")
    scene = _read("skills/pipelines/reel-batch/scene-director.md")
    script = _read("skills/pipelines/reel-batch/script-director.md")

    assert "G3 — after SCENE_PLAN" in ep and "G4 — after ASSETS" in ep, (
        "executive-producer.md no longer has a G3 section bounded by a G4 "
        "heading — the section split below is invalid"
    )
    g3 = ep.split("G3 — after SCENE_PLAN", 1)[1].split("G4 — after ASSETS", 1)[0]
    ep_match = re.search(r"Slots per reel total <= (\d+(?:\.\d+)?) seconds", g3)
    assert ep_match, "G3's checklist no longer states a per-reel duration ceiling"

    scene_match = re.search(r'assert r\["total_seconds"\] <= (\d+(?:\.\d+)?)', scene)
    assert scene_match, "scene-director's step-9 gate no longer asserts total_seconds"

    # script-director.md states the cap twice — once in prose, once in the
    # ```python fence that is actually copied and run. `re.search` takes only
    # the FIRST hit (the prose), so a drift confined to the executable fence
    # went unpinned: an agent would author reels straight past the ceiling
    # while this test stayed green. `findall` collects every occurrence and
    # every one must agree with the others before it stands in for "the"
    # script-director value below.
    script_matches = re.findall(
        r"window_end = min\(window_start \+ (\d+(?:\.\d+)?),", script
    )
    assert script_matches, "script-director's window cap no longer bounds window_end"
    assert len(set(script_matches)) == 1, (
        "script-director.md states the window cap more than once and they "
        f"disagree with each other: {script_matches} — the ```python fence is "
        "the copy that actually runs, so a prose/fence mismatch here is "
        "load-bearing, not cosmetic"
    )

    values = {
        "executive-producer.md (G3)": float(ep_match.group(1)),
        "scene-director.md (step 9)": float(scene_match.group(1)),
        "script-director.md (window cap)": float(script_matches[0]),
    }
    assert len(set(values.values())) == 1, (
        "the per-reel duration ceiling disagrees across the three places that "
        f"author it: {values}"
    )
