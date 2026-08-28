# Idea Director - Avatar Spokesperson Pipeline

## When To Use

Use this pipeline when the deliverable is a presenter-led avatar video: a spokesperson spot, product intro, onboarding message, internal comms update, or short scripted explainer where the speaker remains the visual anchor.

Your first job is to classify the avatar path honestly before anyone writes polished copy for an impossible production setup.

## Runtime Selection (MANDATORY — present the constraint, don't silently pick)

Lock `render_runtime = "remotion"`. **HyperFrames is NOT a valid runtime on this pipeline in Phase 1** — avatar-spokesperson depends on the Remotion `TalkingHead` composition and `remotion_caption_burn`, and neither has HyperFrames parity yet.

Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)": do NOT silently default. Tell the user: "HyperFrames is available on your machine, but avatar-spokesperson depends on the Remotion TalkingHead composition and caption burn, so remotion is the only viable runtime here — OK to proceed?" Record a `render_runtime_selection` decision with hyperframes `rejected_because: "TalkingHead + caption parity deferred on avatar-spokesperson"`.

## Reference Inputs

- `docs/avatar-spokesperson-best-practices.md`
- `skills/creative/storytelling.md`
- `skills/creative/short-form.md`

## Process

### 1. Classify The Avatar Path

Record which production mode the project actually has:

- `platform_avatar`
- `photo_talking_head`
- `presenter_plate_lip_sync`

Also record whether the avatar already exists or still has to be created outside the current run.

### 2. Define The Message Shape

Capture:

- audience,
- core offer or CTA,
- runtime target,
- platform targets,
- whether the video is sales, onboarding, support, or announcement led.

Spokesperson videos work best when they have one clear job.

### 3. Capture Source Reality

The brief should explicitly state:

- whether clean narration is supplied,
- whether TTS is acceptable,
- whether brand backgrounds or overlays exist,
- whether subtitles are required,
- whether multilingual variants are expected.

### 4. Build The Brief

Recommended metadata keys:

- `avatar_path`
- `avatar_exists`
- `narration_source`
- `target_audience`
- `cta_type`
- `background_strategy`
- `deliverable_mix`
- `missing_capabilities`

### 4b. Compute Budget And Seed The Cost Ledger

This is the approval gate — nothing downstream spends until the user approves it. Compute the default budget cap from the pipeline manifest's `orchestration` block (`pipeline_defs/avatar-spokesperson.yaml`), not from `config.yaml`'s flat global total — the manifest is what lets budget scale with target runtime:

```python
import yaml
from tools.cost_tracker import CostTracker

manifest = yaml.safe_load(open("pipeline_defs/avatar-spokesperson.yaml"))["orchestration"]
flat_default = manifest["budget_default_usd"]                   # $2.00 floor
per_minute_rate = manifest.get("budget_per_output_minute_usd")  # $0.60/min

target_minutes = runtime_target_seconds / 60
default_budget_cap_usd = max(flat_default, per_minute_rate * target_minutes)

tracker = CostTracker.for_project(project_id)  # every downstream stage reopens this same ledger
```

Itemize the tools the chosen avatar path will actually call (`talking_head` or `lip_sync` for the avatar, `tts_selector` for narration, `subtitle_gen`/`image_selector`/`audio_enhance` for support) and seed a matching `tracker.estimate(tool, operation, estimated_usd)` for each, so the on-screen figure and `cost_log.json` agree. Record the total as `metadata.cost_estimate` and the cap as `metadata.budget_cap_usd`.

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

- the avatar path is explicit,
- the message is narrow enough for a spokesperson format,
- missing narration or avatar dependencies are visible early,
- deliverables fit the actual source setup.

## Common Pitfalls

- Treating a generic generated-video request as a deterministic avatar workflow.
- Writing the CTA before confirming the avatar and narration path.
- Planning multiple aspect ratios before the hero layout is proven.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
