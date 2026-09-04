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


def test_every_doc_anchor_into_checkpoint_and_corpus_is_fresh() -> None:
    """Drift guard for `lib/checkpoint.py:NNN` anchors in EVERY doc.

    Scoped to the citation convention above, so what it checks is exactly what
    a doc actually promises the reader. Anchors outside that form are counted
    and reported in the failure message but never failed."""
    sources = {module: _read(module).splitlines() for module in ANCHOR_MODULES}
    symbols = {module: _top_level_symbols(lines) for module, lines in sources.items()}

    rotted: list[str] = []
    checked = 0

    for doc in _anchor_docs():
        for line_number, line in enumerate(_read(doc).splitlines(), start=1):
            for match in _ANCHOR_CITATION.finditer(line):
                module = match.group("module")
                symbol = match.group("symbol")
                if module not in symbols or symbol not in symbols[module]:
                    continue
                first, last = symbols[module][symbol]
                checked += 1
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

    assert not rotted, (
        f"{len(rotted)} rotted anchor(s) of {checked} checked across "
        f"{len(_anchor_docs())} docs:\n  " + "\n  ".join(rotted)
    )
