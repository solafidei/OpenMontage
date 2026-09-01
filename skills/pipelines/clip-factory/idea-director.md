# Idea Director - Clip Factory Pipeline

## When To Use

Use this pipeline when the source is long-form footage and the goal is multiple short-form deliverables: webinar clips, interview cuts, livestream highlights, keynote excerpts, or presentation snippets.

You are not planning one video. You are planning a ranked portfolio of clips.

## Runtime Selection (MANDATORY — present the constraint, don't silently pick)

Lock `render_runtime = "remotion"` (for composed clips with word-level captions) or `"ffmpeg"` (for pure concat/trim with no composition). **HyperFrames is NOT a valid runtime on this pipeline in Phase 1** — clip-factory depends on Remotion's word-level caption burn, which has no HyperFrames parity yet.

Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)": do NOT silently lock remotion. Surface the constraint to the user: "HyperFrames is an available runtime on your machine, but clip-factory depends on Remotion caption burn that doesn't have HyperFrames parity yet, so remotion is the only viable choice here — OK to proceed?" Record the decision in `decision_log` with category `render_runtime_selection`, including hyperframes as a rejected option (`rejected_because: "caption-burn parity deferred on clip-factory"`).

## Reference Inputs

- `docs/clip-factory-best-practices.md`
- `skills/creative/short-form.md`
- `skills/creative/video-editing.md`

## Process

### 1. Understand The Source And The Goal

Capture the source shape:

- webinar
- interview
- panel
- keynote
- stream
- customer story

Then capture the business goal:

- awareness
- thought leadership
- lead generation
- product education
- event recap

### 2. Choose A Clip Portfolio Strategy

A good batch mixes clip types instead of extracting the same energy repeatedly.

Common clip families:

- `hook`: surprising claim or strong cold open
- `insight`: useful takeaway or lesson
- `story`: narrative moment with emotional shape
- `proof`: stat, case study, demo result
- `opinion`: hot take, disagreement, contrarian point

Use the brief metadata to define the intended balance across those families.

### 3. Set Yield Targets Realistically

Guideline ranges:

- `15-30 min`: 3-6 strong clips
- `30-60 min`: 5-10 strong clips
- `60+ min`: 8-15 strong clips if the source quality supports it

Do not inflate clip count to satisfy a round number. A smaller strong batch beats a padded weak batch.

### 4. Map Platforms Before Extraction

Plan platform fit early:

- `9:16` for Shorts, Reels, TikTok
- `1:1` for LinkedIn and safer feed repurposing
- `16:9` when slides, demos, or wide context matter

If the source framing clearly will not survive vertical crops, say so in the brief metadata now.

### 5. Build The Brief

Keep the schema-level brief concise and put the richer batch plan in `brief.metadata`.

Recommended metadata keys:

- `source_type`
- `source_duration_seconds`
- `clip_target_range`
- `clip_families`
- `primary_platforms`
- `secondary_platforms`
- `selection_criteria`
- `known_visual_constraints`
- `distribution_goal`

### 5b. Compute Budget And Seed The Cost Ledger

This is the approval gate — nothing downstream spends until the user approves it. Compute the default budget cap from the pipeline manifest's `orchestration` block (`pipeline_defs/clip-factory.yaml`), not from `config.yaml`'s flat global total — the manifest is what the gate's cap must come from:

```python
import yaml
from tools.cost_tracker import CostTracker

manifest = yaml.safe_load(open("pipeline_defs/clip-factory.yaml"))["orchestration"]

# No `budget_per_output_minute_usd` on this manifest, and none is wanted: clip-factory
# exposes zero paid tools (`subtitle_gen`, `audio_enhance`, `video_compose`,
# `video_trimmer`, `audio_mixer`, `color_grade` all price $0.00), so a per-minute rate
# would scale a ceiling for spend that cannot occur. The flat default is pure headroom.
default_budget_cap_usd = manifest["budget_default_usd"]         # $1.00 flat

tracker = CostTracker.for_project(project_id)  # every downstream stage reopens this same ledger
```

Itemize the tool batches that will actually be called (`subtitle_gen` for the per-clip subtitle set, `audio_enhance` for the batch audio normalization pass) and seed a matching `tracker.estimate(tool, operation, estimated_usd)` for each — one entry per tool batch, never one per clip. Every figure here is `0.00`, and that is the point: the gate presents an explicit `TOTAL ESTIMATED $0.00 of $1.00` rather than silence, and `cost_log.json` proves the $0 rather than merely failing to record it. Record the total as `metadata.cost_estimate` and the cap as `metadata.budget_cap_usd`.

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

On an all-$0 clip-factory plan `min_workable_usd` lands at $0.01 and the `max()` is inert — the line stays verbatim anyway. Uniformity with every other pipeline is the drift guard; a "lite" spelling here is how the two versions diverge.

> **If the user's named figure is below `min_workable_usd`, say so at this gate** — the reserve holdback guarantees the guard blocks the plan's final approved item. Ask the user to raise the figure or trim the plan. Never silently arm a total the guard is certain to trip on.

Downstream stages must book under these exact names — see `skills/meta/checkpoint-protocol.md` → Cost Ledger Governance.

The asset director creates and reserves its OWN entry at the moment it actually runs a batch, passing `user_approved=True` because that call fulfills a line item approved here. Anything outside this plan still trips `ApprovalRequiredError` — surface it per AGENT_GUIDE.md → "Escalate Blockers Explicitly" rather than reserving around it.

### 6. Quality Gate

- the clip count target is realistic,
- the platform mix matches the content,
- the brief defines ranking criteria before extraction starts,
- the agent has acknowledged any obvious reframing limits.

## Common Pitfalls

- Planning a batch around quantity before quality.
- Assuming every source can produce vertical clips cleanly.
- Treating all clips as interchangeable instead of intentionally varied.
- Starting extraction without defining what "good" means for this batch.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
