# Proposal Director - Character Animation Pipeline

## Goal

Present character-animation concepts that are honest about local rigged motion,
reuse, cost, and runtime choice.

## Required Proposal Elements

Each option must include:

- characters and roles,
- visual style,
- action complexity,
- rig reuse strategy,
- sample plan,
- audio architecture,
- music plan,
- render runtime options,
- cost estimate,
- honest limitation note.

## Runtime Selection

Read `skills/meta/animation-runtime-selector.md` before recommending a runtime.

When both Remotion and HyperFrames are available:

- Remotion: best when the final composition needs deterministic React-rendered
  video, captions, audio, scene JSON, and final MP4 governance.
- HyperFrames: best when the character scene is HTML/SVG/GSAP-heavy and benefits
  from web-native authoring, lint, validate, and registry blocks.
- FFmpeg: post-processing only. Do not pick FFmpeg as the primary runtime for
  character acting.

Present both Remotion and HyperFrames to the user before recommending one.
Record the alternatives considered in the decision log as
`render_runtime_selection`, including why `hyperframes` was accepted or rejected.
Wait for user approval before locking `render_runtime`.

## Sample-First Rule

Before full production, propose a 10-15 second sample containing:

- one main character,
- one expression change,
- one body action,
- one camera/background treatment,
- one audio/music cue if relevant.

Do not batch-generate all assets until this sample is approved.

## Cost Honesty

Local rigging is cheap at render time but expensive in authoring complexity.
Report the difference:

- asset generation cost,
- TTS/music cost,
- local render cost,
- manual complexity risk.

Rendering is local and free here (`character_rig_renderer`, `video_compose`). The
paid trio is `tts_selector` (narration/dialogue), `image_selector` (character
sheets, backgrounds, props) and `music_gen` (score). Price those three; book the
rest at `$0.00`.

### Compute The Default Budget Cap

Before pricing line items, compute the default budget cap the approval gate will
present. Read it from the pipeline manifest's `orchestration` block
(`pipeline_defs/character-animation.yaml`), not from `config.yaml`'s flat global
total — the manifest is what lets budget scale with THIS concept's duration:

```python
import yaml

manifest = yaml.safe_load(open("pipeline_defs/character-animation.yaml"))["orchestration"]
flat_default = manifest["budget_default_usd"]                    # short-form floor
per_minute_rate = manifest.get("budget_per_output_minute_usd")   # optional duration-aware rate

concept = next(c for c in packet["concept_options"] if c["id"] == packet["selected_concept"]["concept_id"])
target_minutes = concept["target_duration_seconds"] / 60
duration_scaled_usd = (per_minute_rate * target_minutes) if per_minute_rate else 0

default_budget_cap_usd = max(flat_default, duration_scaled_usd)
```

**Show this math at the gate, not just the final number** — e.g.
`max($2.00 flat, $0.60/min × 6 min) = max($2.00, $3.60) = $3.60`.

This computed figure is only the *default* offered at the gate. The user-approved
figure (`approval.approved_budget_usd`) always overrides it — raised, lowered, or
accepted as-is — and the arming step below arms the tracker with whatever the user
actually approved, never the computed default outright. Record it on the artifact
so the number shown at the gate is the number persisted:
`cost_estimate["budget_cap_usd"] = default_budget_cap_usd`.

### Seed The Cost Ledger

**No guessing — every number comes from the tool itself.** For each planned tool
call, ask the tool for its own `estimate_cost` through the registry, and seed the
project's cost tracker with a matching entry in the same pass. The on-screen line
items and `cost_log.json` must never disagree:

```python
from tools.tool_registry import registry
from tools.cost_tracker import CostTracker

registry.discover()
tracker = CostTracker.for_project(project_id)  # same ledger every stage shares

line_items = []
for planned in planned_tool_calls:  # e.g. {"tool": "image_selector", "operation": "character sheets", "inputs": {...}, "quantity": 4}
    tool = registry.get(planned["tool"])
    unit_usd = tool.estimate_cost(planned["inputs"])   # price of ONE call
    quantity = planned.get("quantity", 1)
    estimated_usd = round(unit_usd * quantity, 4)
    tracker.estimate(planned["tool"], planned["operation"], estimated_usd)  # writes an ESTIMATED cost_log entry
    line_items.append({
        "tool": planned["tool"],
        "operation": planned["operation"],
        "quantity": quantity,
        "estimated_usd": estimated_usd,
    })

cost_estimate["line_items"] = line_items
total_estimated_usd = round(sum(li["estimated_usd"] for li in line_items), 4)
```

**Two pricing shapes — get `quantity` right or the gate lies.** `estimate_cost`
prices *one call*. Tools that price the whole payload — `tts_selector` (the entire
narration or dialogue text), `music_gen` (needs `duration_seconds` in `inputs`,
raises without it) — take `quantity: 1` with the complete payload in `inputs`.
Unit-priced tools — `image_selector` — ignore any quantity key you pass them and
return a single-unit price, so `quantity` carries the planned unit count (character
sheets + backgrounds + props) and the multiplication happens here. Get this wrong
and a 6-sheet cast is priced as a single sheet — on screen and in the seeded ledger
alike. Keep `unit_usd` a local variable: `proposal_packet.schema.json` closes line
items to `additionalProperties: false`, so persisting it would fail artifact
validation.

By the time this stage checkpoints, `cost_log.json` already holds one
`estimated`-status entry per line item above — what the user sees and what the
ledger will enforce are the same numbers.

**The budget verdict is computed, not eyeballed.** Compare the total against the
tighter of `tracker.usable_budget_usd` — the tracker's remaining budget after the
reserve holdback — and `default_budget_cap_usd`, never against the raw budget total:

```python
usable = min(tracker.usable_budget_usd, default_budget_cap_usd)
if total_estimated_usd > usable:
    budget_verdict = "over_budget"
elif total_estimated_usd > usable * 0.85:
    budget_verdict = "near_limit"
else:
    budget_verdict = "within_budget"
```

The sample sub-stage spends nothing — `character_spec_generator`, `svg_rig_builder`,
`pose_library_builder`, `action_timeline_compiler`, `character_rig_renderer`,
`character_animation_reviewer` and `video_compose` are all local/free. Book the
whole sample as ONE batched `$0.00` round trip, not one entry per artifact.

## On Approval — Arm the Tracker

When `approval.status` flips to `approved` or `approved_with_changes` (a later turn
— see the Gate Reminder below), before handing off to the Script Director, do the
handshake that turns the approved plan into the tracker's guard configuration:

```python
import math

# 1. The approved budget figure becomes the tracker's budget total.
#    A figure the user NAMED is used verbatim — their word is the cap.
#    A bare "approve" approves the plan AS PRESENTED at the gate: the
#    estimate within the default cap. Arm with that cap, floored at the
#    estimate grossed up past the reserve holdback. Arming with the bare
#    estimate leaves zero headroom: usable budget tops out at
#    (1 - reserve_pct) x total, so the plan's FINAL reservation would need
#    E_n <= E_n - reserve_pct x total — never true. reserve_pct comes from
#    the tracker (config's budget.reserve_pct via for_project); never
#    hardcode 0.10.
total_estimated_usd = round(sum(li["estimated_usd"] for li in cost_estimate["line_items"]), 4)
min_workable_usd = math.ceil(total_estimated_usd / (1 - tracker.reserve_pct) * 100) / 100 + 0.01  # +1 cent: on an exact-cent division, bare ceil adds zero slack and the final reserve still trips on float dust
tracker.budget_total_usd = (
    approval.approved_budget_usd
    or max(cost_estimate["budget_cap_usd"], min_workable_usd)
)

# 2. Approve every tool named in the approved plan. This clears the
#    first-paid-use guard for exactly the tools the user saw and approved.
for tool_name in {li["tool"] for li in cost_estimate["line_items"]}:
    tracker.approve_tool(tool_name)

# 3. This stage's seeded entries were placeholders — created only so the
#    on-screen estimate and cost_log.json agreed at the gate. They are never
#    executed: the stage that actually spends creates and reserves its OWN
#    entry. Refund them so every entry reaches a terminal state before the
#    compose-stage cost_log check. (An `estimated` entry does NOT consume budget
#    — usable_budget_usd subtracts only reserved + spent — so this is ledger
#    hygiene, not a budget fix. Never RESERVE a placeholder: a reservation
#    nothing will ever reconcile WOULD eat usable_budget_usd for the rest of
#    the run.)
for entry in tracker.entries:
    if entry["status"] == "estimated":
        tracker.refund(entry["id"])
```

> **If the user's named figure is below `min_workable_usd`, say so at this gate** — the reserve holdback guarantees the guard blocks the plan's final approved item. Ask the user to raise the figure or trim the plan. Never silently arm a total the guard is certain to trip on.

Downstream stages must book under these exact names — see `skills/meta/checkpoint-protocol.md` → Cost Ledger Governance.

**The single-action threshold is waived at the point of spend, not here.** Do NOT
pre-reserve the line items in this step — a reservation made here is never
reconciled (nothing at this stage executes the call), so it would sit in `reserved`
state for the rest of the run, silently eating budget out of `usable_budget_usd` on
top of whatever the executing stage reserves for real. Every downstream director
(character-design-director, asset-director, compose-director) passes
`user_approved=True` on the `tracker.reserve(entry_id, ...)` call for its OWN entry,
exactly when that entry fulfills a line item the user saw and approved here.

**The guards still fire for anything outside the approved plan**, and that is
correct behavior: a tool with no line item trips the first-paid-use guard
(`ApprovalRequiredError`) the first time a downstream stage reserves against it, and
an unplanned action over the single-action threshold trips that guard too. Never let
a downstream stage silently skip the asset or substitute a cheaper tool when a guard
trips — surface it as a structured blocker per `AGENT_GUIDE.md` → "Escalate Blockers
Explicitly", then wait for the user.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
