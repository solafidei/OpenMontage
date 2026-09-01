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
