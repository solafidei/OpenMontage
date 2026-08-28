# Idea Director - Hybrid Pipeline

## When To Use

Use this pipeline when the project combines real source media with support visuals: interviews plus diagrams, footage plus overlays, screen recording plus branded graphics, or source-led edits with generated inserts.

Hybrid is not a catch-all. Your first job is to define what stays primary.

## Runtime Selection (MANDATORY — present both runtimes)

Before locking the production plan, decide `render_runtime` with the user. Hybrid supports BOTH Remotion and HyperFrames; neither is an auto-default. Follow the contract in AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)":

1. Query `video_compose.get_info()["render_engines"]`. If both `remotion` and `hyperframes` are `True`, present both to the user with brief-specific analysis:
   - **Remotion** — fits when source footage dominates and support layers are React scene components (chart, callout, text card). Remotion composes video clips + React overlays in one pass via `<OffthreadVideo>`.
   - **HyperFrames** — fits when support layers are HTML/GSAP-native (kinetic callouts, registry blocks, typographic overlays) and source footage is embedded as `<video class="clip">`.
2. Recommend one with rationale tied to the anchor medium and the shape of the support layer.
3. Wait for explicit user approval.
4. Log the choice in `decision_log` as a `render_runtime_selection` decision with BOTH runtimes in `options_considered`.

A `render_runtime_selection` decision with only one runtime in `options_considered` when both were available is a CRITICAL reviewer finding.

## Reference Inputs

- `docs/hybrid-video-best-practices.md`
- `skills/creative/storytelling.md`
- `skills/creative/video-editing.md`

## Process

### 1. Choose The Anchor Medium

Pick the storytelling anchor:

- `talking_head`
- `broll_footage`
- `screen_recording`
- `still_sequence`
- `narration_led_graphics`

### 2. Define Support Layers

Possible support layers:

- subtitles,
- diagrams,
- code visuals,
- stat cards,
- generated inserts,
- narration,
- music.

Each support layer should solve a specific problem, not just decorate the timeline.

### 3. Decide The Deliverable Mix

Common outputs:

- hero cut,
- vertical cutdown,
- square cutdown,
- chaptered version,
- ad variant.

### 4. Build The Brief

Recommended metadata keys:

- `anchor_medium`
- `source_inventory`
- `support_layers`
- `deliverable_mix`
- `missing_capabilities`
- `fallback_policy`

### 4b. Compute Budget And Seed The Cost Ledger

This is the approval gate — nothing downstream spends until the user approves it. Compute the default budget cap from the pipeline manifest's `orchestration` block (`pipeline_defs/hybrid.yaml`), not from `config.yaml`'s flat global total — the manifest is what lets budget scale with target duration:

```python
import yaml
from tools.cost_tracker import CostTracker

manifest = yaml.safe_load(open("pipeline_defs/hybrid.yaml"))["orchestration"]
flat_default = manifest["budget_default_usd"]                   # $2.00 floor
per_minute_rate = manifest.get("budget_per_output_minute_usd")  # $0.60/min

target_minutes = target_duration_seconds / 60
default_budget_cap_usd = max(flat_default, per_minute_rate * target_minutes)

tracker = CostTracker.for_project(project_id)  # every downstream stage reopens this same ledger
```

Itemize the support-layer tools that will actually be called (`tts_selector`, `image_selector`, `video_selector`, `diagram_gen`, `code_snippet`, `music_gen`, `audio_enhance` — whichever the support-layer plan uses) and seed a matching `tracker.estimate(tool, operation, estimated_usd)` for each, so the on-screen figure and `cost_log.json` agree. Record the total as `metadata.cost_estimate` and the cap as `metadata.budget_cap_usd`.

**On approval** (once the checkpoint is re-written `status="completed"`, `human_approved=True`): arm the tracker with what was actually approved and clear this step's placeholders.

```python
tracker.budget_total_usd = approved_budget_usd or default_budget_cap_usd
for tool_name in {li["tool"] for li in metadata["cost_estimate"]["line_items"]}:
    tracker.approve_tool(tool_name)
for entry in tracker.entries:
    if entry["status"] == "estimated":
        tracker.refund(entry["id"])
```

The asset director creates and reserves its OWN entry at the moment it actually spends, passing `user_approved=True` because that call fulfills a line item approved here. Anything outside this plan still trips `ApprovalRequiredError` — surface it per AGENT_GUIDE.md → "Escalate Blockers Explicitly" rather than reserving around it.

### 5. Quality Gate

- the anchor medium is explicit,
- support layers are justified,
- the deliverable mix fits the source inventory,
- missing capabilities are surfaced early.

## Common Pitfalls

- Calling everything hybrid without defining a primary medium.
- Planning support layers before understanding the source.
- Treating optional generated inserts as guaranteed.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
