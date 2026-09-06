# Idea Director — Talking Head Pipeline

## When to Use

You are starting a talking-head video project. You have raw footage of a person speaking. Your job is to analyze the footage, understand what it contains, and build a brief that captures the content's essence and production goals.

Unlike the explainer pipeline (which starts from a topic), you start from existing footage. The brief documents what you're working with and what the final video should look like.

## Runtime Selection (MANDATORY — present the constraint, don't silently pick)

Lock `render_runtime = "remotion"` (preferred — uses `TalkingHead` + `remotion_caption_burn`) or `"ffmpeg"` (for source-footage concat with no composition). **HyperFrames is NOT a valid runtime on this pipeline in Phase 1** — the TalkingHead composition and word-level caption burn have no HyperFrames parity yet.

Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)": do NOT silently default to remotion. Tell the user: "HyperFrames is available, but talking-head depends on the Remotion TalkingHead composition, so remotion is the only viable composition choice (or ffmpeg for a raw cut) — OK to proceed?" Record a `render_runtime_selection` decision with hyperframes as a rejected option (`rejected_because: "TalkingHead + caption parity deferred on talking-head"`).

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/brief.schema.json` | Artifact validation |
| Inputs | Raw footage file path | Source material |
| Tools | `ffprobe` (via shell) | Footage metadata extraction |

## Process

### Step 1: Inspect the Footage

Use ffprobe to extract metadata:
- Duration
- Resolution
- Frame rate
- Audio channels and codec
- File size

This tells you what you're working with — quality, length, format.

### Step 2: Quick Content Assessment

Watch/scan the footage mentally (or sample frames if frame_sampler is available):
- What is the person talking about?
- How long is the raw footage?
- What's the intended platform? (Ask the user if unclear)
- Is there good audio? Background noise?

### Step 3: Build the Brief

Create a brief artifact documenting:
- **Title**: Descriptive title based on footage content
- **Hook**: What makes this worth watching?
- **Key points**: Main topics covered in the footage
- **Tone**: Match the speaker's actual tone (casual, professional, educational)
- **Style**: Derive the overlay/look direction from the footage, speaker persona, audience, and platform. `clean-professional` is a safe fallback, not the default answer to every talking-head brief.
- **Target platform**: Where this will be published
- **Target duration**: May be shorter than raw footage (trimmed)

### Step 3b: Compute Budget And Seed The Cost Ledger

This is the approval gate — nothing downstream spends until the user approves it. Compute the default budget cap from the pipeline manifest's `orchestration` block (`pipeline_defs/talking-head.yaml`), not from `config.yaml`'s flat global total — the manifest is what lets budget scale with target duration:

```python
import yaml
from tools.cost_tracker import CostTracker

manifest = yaml.safe_load(open("pipeline_defs/talking-head.yaml"))["orchestration"]
flat_default = manifest["budget_default_usd"]                   # $0.50 floor
per_minute_rate = manifest.get("budget_per_output_minute_usd")  # $0.05/min

target_minutes = target_duration_seconds / 60   # the brief's **Target duration** field, not the raw footage runtime
default_budget_cap_usd = max(flat_default, per_minute_rate * target_minutes)

tracker = CostTracker.for_project(project_id)  # every downstream stage reopens this same ledger
```

Itemize the tools that will actually be called and seed a matching `tracker.estimate(tool, operation, estimated_usd)` for each, so the on-screen figure and `cost_log.json` agree. On this pipeline the only paid tool is optional `image_selector` overlay graphics — price it per unit x the number of overlays the brief plans (one line item for the overlay set). `subtitle_gen` and `audio_mixer` are local/free: seed them at `0.00` so every planned call is on the ledger. If the brief plans no overlays at all, the line items may legitimately total `$0.00` — seed and arm anyway; the armed cap and the honest-$0 ledger are the point. Record the total as `metadata.cost_estimate` and the cap as `metadata.budget_cap_usd`.

**On approval** (once the checkpoint is re-written `status="completed"`, `human_approved=True`): arm the tracker with what was actually approved and clear this step's placeholders.

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
total_estimated_usd = round(sum(li["estimated_usd"] for li in metadata["cost_estimate"]["line_items"]), 4)
min_workable_usd = math.ceil(total_estimated_usd / (1 - tracker.reserve_pct) * 100) / 100 + 0.01  # +1 cent: on an exact-cent division, bare ceil adds zero slack and the final reserve still trips on float dust
tracker.budget_total_usd = approved_budget_usd or max(default_budget_cap_usd, min_workable_usd)
for tool_name in {li["tool"] for li in metadata["cost_estimate"]["line_items"]}:
    tracker.approve_tool(tool_name)
for entry in tracker.entries:
    if entry["status"] == "estimated":
        tracker.refund(entry["id"])
```

> **If the user's named figure is below `min_workable_usd`, say so at this gate** — the reserve holdback guarantees the guard blocks the plan's final approved item. Ask the user to raise the figure or trim the plan. Never silently arm a total the guard is certain to trip on.

Downstream stages must book under these exact names — see `skills/meta/checkpoint-protocol.md` → Cost Ledger Governance.

The asset director creates and reserves its OWN entry at the moment it actually spends, passing `user_approved=True` because that call fulfills a line item approved here. Anything outside this plan still trips `ApprovalRequiredError` — surface it per AGENT_GUIDE.md → "Escalate Blockers Explicitly" rather than reserving around it.

### Step 4: Self-Evaluate

| Criterion | Question |
|-----------|----------|
| **Accuracy** | Does the brief reflect what's actually in the footage? |
| **Completeness** | Are all required brief fields present? |
| **Platform fit** | Is the target platform appropriate for this content? |

### Step 5: Submit

Validate the brief against the schema and persist via checkpoint.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
