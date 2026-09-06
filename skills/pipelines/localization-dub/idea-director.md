# Idea Director - Localization Dub Pipeline

## When To Use

Use this pipeline when the user has a source video and wants translated deliverables: subtitles, dubbed audio, or localized videos in one or more target languages.

Your first responsibility is to define what kind of localization is actually required, because subtitle-only, dubbed-audio, and lip-synced translation are different jobs.

## Runtime Selection (MANDATORY — present the constraint, don't silently pick)

Lock `render_runtime = "remotion"` (composed deliverables with per-locale caption burn / lip-sync) or `"ffmpeg"` (pure subtitle-burn over source with no composition). **HyperFrames is NOT a valid runtime on this pipeline in Phase 1** — localization depends on Remotion's caption stack and, for dubbed-with-lip-sync, on the Remotion TalkingHead pipeline.

Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)": do NOT silently default to remotion. Tell the user: "HyperFrames is available, but localization-dub depends on Remotion caption + TalkingHead parity that isn't there yet in Phase 1 — remotion is the only viable choice". Record a `render_runtime_selection` decision with hyperframes `rejected_because: "caption + lip-sync parity deferred on localization-dub"`.

## Reference Inputs

- `docs/localization-dubbing-best-practices.md`
- `skills/creative/short-form.md`
- `skills/creative/long-form.md`

## Process

### 1. Define The Localization Scope

Capture:

- source language,
- target languages,
- review owner,
- whether glossary or legal review is required,
- whether the user needs subtitles, dubbed audio, lip-sync, or a mix.

### 2. Classify The Source

Record the source mode:

- `single_speaker`
- `multi_speaker`
- `voiceover_led`
- `speaker_led_on_camera`

Also record whether on-screen text or motion graphics will need manual replacement or coverage.

### 3. Pick Deliverables That Match Reality

Possible deliverables:

- subtitle package only,
- dubbed video without lip sync,
- lip-synced localized video,
- per-language export bundle.

### 4. Build The Brief

Recommended metadata keys:

- `source_language`
- `target_languages`
- `deliverable_mode_map`
- `glossary_terms`
- `protected_terms`
- `review_requirements`
- `timing_risks`

### 4b. Compute Budget And Seed The Cost Ledger

Localization spends real money on exactly one axis: dub TTS, which scales with **localized output minutes** — source minutes x target languages. This is the approval gate — nothing downstream spends until the user approves it.

Compute the default budget cap from the pipeline manifest's `orchestration` block (`pipeline_defs/localization-dub.yaml`), not from `config.yaml`'s flat global total — the manifest is what lets budget scale with how much localized audio the run actually produces:

```python
import yaml
from tools.cost_tracker import CostTracker

manifest = yaml.safe_load(open("pipeline_defs/localization-dub.yaml"))["orchestration"]
flat_default = manifest["budget_default_usd"]                   # $3.00 floor
per_minute_rate = manifest.get("budget_per_output_minute_usd")  # $0.40/localized min

target_languages = metadata["target_languages"]
localized_minutes = (source_duration_seconds / 60) * len(target_languages)
default_budget_cap_usd = max(flat_default, per_minute_rate * localized_minutes)
```

A 5-minute source dubbed into 2 languages computes `max($3.00, $0.40/min x 5 min x 2 languages) = max($3.00, $4.00) = $4.00` — show that math, language factor included, at the approval gate, not just the final number. Drop a language at the gate and the cap drops with it.

Open the ledger and seed ONE `tts_selector` line item PER TARGET LANGUAGE — quantity 1, that language's full translated script text as the payload, because TTS is priced on the whole payload. Per-language line items are what make each language's dub cost visible at the gate and in `cost_log.json`, and what makes dropping a language drop its line item. `lip_sync`, `subtitle_gen` and `audio_enhance` are local/free — seed them at `0.0`, one entry per batch, so every planned call starts in a terminal-reachable state:

```python
tracker = CostTracker.for_project(project_id)  # every downstream stage reopens this same ledger

for lang in target_languages:
    estimated_usd = tts_selector.estimate_cost(
        {"text": translated_script_by_language[lang], "language": lang}
    )
    tracker.estimate("tts_selector", f"dub_{lang}", estimated_usd)

tracker.estimate("subtitle_gen", f"subtitles x {len(target_languages)} locales", 0.0)  # local/free
```

Record `metadata.cost_estimate` (itemized — one line per language) and `metadata.budget_cap_usd` on the brief so the on-screen number and `cost_log.json` agree.

**On approval** (once the checkpoint is re-written `status="completed"`, `human_approved=True` — see `skills/meta/checkpoint-protocol.md`): arm the tracker with what was actually approved and clear this step's placeholders.

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

The asset director creates and reserves its OWN entry at the moment it actually spends, passing `user_approved=True` because that call fulfills a line item approved here. A language added after this gate has no line item, so its first dub call trips `ApprovalRequiredError` — that is the guard working. Surface it per AGENT_GUIDE.md → "Escalate Blockers Explicitly" rather than reserving around it.

### 5. Quality Gate

- localization scope is explicit,
- target outputs are realistic,
- glossary and review requirements are captured,
- risk increases from speaker count or visible mouths are surfaced.

## Common Pitfalls

- Calling every translation request a dubbing request.
- Ignoring glossary control until after audio is generated.
- Promising lip sync on visually difficult source footage without warning.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
