# Idea Director - Screen Demo Pipeline

## Runtime Selection (MANDATORY — present all viable runtimes)

Lock `render_runtime` at the idea stage alongside the production mode. Which runtimes are viable depends on the mode:

| Production mode | Viable runtimes |
|-----------------|-----------------|
| `real_capture` (actual screen recording) | `remotion` (preferred — mix capture with overlays), `ffmpeg` (pure concat/trim) |
| `synthetic_terminal` (Remotion `TerminalScene`) | `remotion` only |
| `synthetic_ui` (custom HTML UI demo) | `remotion` OR `hyperframes` — real choice, present both |

Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)": when the mode allows multiple runtimes AND both are available on the machine (check `video_compose.get_info()["render_engines"]`), present both to the user with brief-specific analysis, recommend one, wait for approval. Do NOT silently default. When the mode constrains the choice (e.g. `synthetic_terminal` is Remotion-only), tell the user the constraint explicitly rather than silently locking remotion. Record every choice in `decision_log` under `render_runtime_selection` with all considered options.

## When To Use

Use this pipeline whenever the deliverable is a screen-recording-style demo. There are **two production modes** — pick one in the brief:

| Mode | Source material | Pick when |
|---|---|---|
| **`real_capture`** | An actual screen recording (MP4) captured via `screen_recorder`, `cap_recorder`, or `playwright-recording` | Real app UI, live behavior, browser flows, IDE plugins, user asked for their own screen |
| **`synthetic_terminal`** | None — nothing is captured. You author a `terminal_scene` cut for Remotion | CLI / terminal / install flow / make targets / git clone / API key config — anything scriptable where every command and output is predictable |

**Decision question:** *"Can I predict every command and its output before shooting?"* If yes → synthetic. If no → real capture.

**Record the mode in `brief.metadata.production_mode`.** The asset-director reads this field to choose between capture+overlay assets vs a `steps` list paced with narration.

For `synthetic_terminal`, also read `.agents/skills/synthetic-screen-recording/SKILL.md` before proceeding — it encodes the pacing rule that killed an earlier showcase render (commands burned through in 40% of scene time, then terminal froze for the remaining 60%).

Your job at this stage is to turn the user's request into a clear procedural video plan. The main deliverable is a schema-valid `brief`, with pipeline-specific detail stored in `brief.metadata`.

## Operating Principles

Screen-demo best practices are consistent:

- prioritize procedure over theory,
- keep scope to one workflow or one outcome,
- map narration to visible action,
- plan attention guidance with restraint,
- optimize for legibility before style.

Reference docs:
- `docs/screen-demo-best-practices.md`
- `skills/creative/screen-recording.md`

## Process

### 1. Inspect The Source

Use the available analysis tools before writing the brief:

- `frame_sampler` for representative frames and dense samples around likely key moments
- `scene_detect` for window switches, page changes, and major layout changes
- `transcriber` to determine whether the recording has narration, system audio only, or silence

Identify:

- software and surfaces shown,
- the single workflow being taught,
- critical interactions: click, type, scroll, submit, result,
- moments that obviously need zoom or highlight support,
- dead time: installs, builds, loading, repetitive typing,
- whether `9:16` is even feasible without losing meaning.

### 2. Classify The Demo

Choose one dominant archetype:

- `tutorial`: step-by-step task completion
- `feature_showcase`: show what a feature does
- `troubleshooting`: reproduce and fix a problem
- `walkthrough`: explain a multi-step flow across tools
- `comparison`: compare two approaches or outcomes

If the footage mixes several archetypes, pick the one that should drive pacing and packaging.

### 3. Set Deliverable Intent

Screen demos should stay narrow and outcome-led:

- `30-60s`: quick tip or feature reveal
- `60-120s`: focused product walkthrough or bug fix
- `120-300s`: chaptered tutorial

Default to the shortest duration that still teaches the task cleanly. Do not preserve raw duration unless the user explicitly wants training footage with minimal compression.

### 4. Choose A Viable Output Shape

Plan the platform around readability, not trend pressure:

- use `youtube` or `linkedin` for dense desktop UI,
- use `instagram` or `tiktok` only if the active area can survive a narrow crop,
- prefer `1:1` or `16:9` when the interface has multiple panels or code windows.

### 5. Build The Brief

Use the schema fields for the concise creative contract and store the richer production detail in `metadata`.

Recommended `metadata` keys:

- `source_path`
- `source_duration_seconds`
- `source_resolution`
- `has_voiceover`
- `software_shown`
- `demo_archetype`
- `critical_moments`
- `dead_time_segments`
- `recommended_aspect_ratios`
- `notes_for_scene_planner`

The brief should answer:

- what the viewer will learn,
- who this is for,
- what proof/result the video should land on,
- what the must-show actions are,
- which crop directions are safe.

### 5b. Compute Budget And Seed The Cost Ledger

This is the approval gate — nothing downstream spends until the user approves it. Compute the default budget cap from the pipeline manifest's `orchestration` block (`pipeline_defs/screen-demo.yaml`), not from `config.yaml`'s flat global total — the manifest is what lets budget scale with target duration:

```python
import yaml
from tools.cost_tracker import CostTracker

manifest = yaml.safe_load(open("pipeline_defs/screen-demo.yaml"))["orchestration"]
flat_default = manifest["budget_default_usd"]                   # $1.00 floor
per_minute_rate = manifest.get("budget_per_output_minute_usd")  # $0.25/min

target_minutes = target_duration_seconds / 60   # the brief's target OUTPUT duration, not the raw capture length
default_budget_cap_usd = max(flat_default, per_minute_rate * target_minutes)

tracker = CostTracker.for_project(project_id)  # every downstream stage reopens this same ledger
```

Itemize the tools that will actually be called for the production mode this brief chose, and seed a matching `tracker.estimate(tool, operation, estimated_usd)` for each, so the on-screen figure and `cost_log.json` agree:

- **Synthetic terminal, or real capture with a silent recording** — narration is generated: one `tts_selector` line item (quantity 1, the full narration text) plus `image_selector` opening/transition/outro cards, unit-priced × the planned card count.
- **Real capture that already has a voiceover** — the line items may legitimately all be `$0.00` (`subtitle_gen`, `diagram_gen` and `audio_enhance` are local/free). **Seed and arm anyway.** The armed cap and an honest all-$0 ledger are the point: without arming, the checkpoint's `cost_snapshot()` reports config's global default instead of the cap approved here, and $0 spent is unrecorded rather than proven.

Record the total as `metadata.cost_estimate` and the cap as `metadata.budget_cap_usd`.

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

The asset director creates and reserves its OWN entry at the moment it actually spends, passing `user_approved=True` because that call fulfills a line item approved here. Anything outside this plan still trips `ApprovalRequiredError` — surface it per AGENT_GUIDE.md → "Escalate Blockers Explicitly" rather than reserving around it. **Mode changes are new spend:** if the production mode shifts after this gate (a real capture turning out silent, so narration now has to be generated), that TTS was never in the approved plan — the first-paid-use guard trips by design. Escalate and re-approve; never self-approve around it.

### 6. Quality Gate

Before checkpointing, verify:

- the workflow is narrow enough for the chosen duration,
- the "aha" result is clearly identified,
- the target platform matches the UI density,
- the brief names the actual software rather than describing it vaguely,
- the metadata gives downstream stages enough production truth.

## Common Pitfalls

- Treating a 7-minute recording as a 7-minute deliverable by default.
- Choosing `9:16` for a dense desktop capture just because the user asked for Shorts.
- Writing a concept-heavy brief when the user really needs task completion.
- Failing to note silence; if there is no voiceover, downstream stages must know immediately.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
