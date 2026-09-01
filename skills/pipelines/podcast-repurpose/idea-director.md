# Idea Director - Podcast Repurpose Pipeline

## When To Use

Use this pipeline when the source is a podcast episode, either audio-only or video podcast, and the user wants clips, social assets, or a companion long-form video treatment.

Your first responsibility is to decide what is feasible from the source that actually exists.

## Runtime Selection (MANDATORY — present the constraint, don't silently pick)

Lock `render_runtime = "remotion"` (audiograms and composed outputs) or `"ffmpeg"` (pure-audio-led clip exports). **HyperFrames is NOT a valid runtime on this pipeline in Phase 1** — podcast outputs lean on Remotion's word-level caption stack, which has no HyperFrames parity yet.

Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)": surface the constraint to the user — "HyperFrames is available on your machine, but podcast-repurpose depends on Remotion caption burn, so remotion is the only viable choice here". Record a `render_runtime_selection` decision with hyperframes `rejected_because: "caption-burn parity deferred on podcast-repurpose"`.

## Reference Inputs

- `docs/podcast-repurposing-best-practices.md`
- `skills/creative/short-form.md`
- `skills/creative/long-form.md`

## Process

### 1. Classify The Source

Capture the source mode:

- `audio_only`
- `video_podcast`
- `hybrid` (audio plus stills, cover art, guest photos)

Also capture the conversational format:

- solo
- interview
- panel
- narrative / produced show

### 2. Choose Deliverables That Match Reality

Default deliverables should be feasible with the source and tools on hand.

Safe options:

- short-form highlight clips,
- audiogram or caption-led clips,
- quote-led clips,
- one optional full-episode companion layout.

Do not assume a high-production full-episode YouTube treatment unless the source video, branding assets, and optional imagery actually exist.

### 3. Set A Sensible Deliverable Mix

Typical starting point:

- `3-5` highlight clips
- `1-3` quote-led assets if the episode has strong one-liners
- optional long-form companion if the source justifies it

### 4. Respect Platform Differences

- `9:16` for Shorts, Reels, TikTok
- `1:1` for LinkedIn and safer feed repurposing
- `16:9` for YouTube companion video

If the source is audio-only, make that explicit in the brief. Downstream stages should not plan speaker-framed video that does not exist.

### 5. Build The Brief

Use `brief.metadata` for the richer podcast-specific contract:

- `source_mode`
- `show_name`
- `episode_title`
- `episode_number`
- `speakers`
- `conversation_format`
- `deliverable_mix`
- `brand_assets_available`
- `full_episode_companion_feasible`

### 5b. Compute Budget And Seed The Cost Ledger

This is the approval gate — nothing downstream spends until the user approves it. Compute the default budget cap from the pipeline manifest's `orchestration` block (`pipeline_defs/podcast-repurpose.yaml`), not from `config.yaml`'s flat global total — the manifest is what lets budget scale with how much output the deliverable mix actually produces:

```python
import yaml
from tools.cost_tracker import CostTracker

manifest = yaml.safe_load(open("pipeline_defs/podcast-repurpose.yaml"))["orchestration"]
flat_default = manifest["budget_default_usd"]                   # $1.00 floor
per_minute_rate = manifest.get("budget_per_output_minute_usd")  # $0.30/min

# OUTPUT minutes, summed across the whole deliverable mix — every clip plus
# the full-episode companion if one is planned. NOT the source runtime, and
# NOT any single deliverable: a 60-minute episode cut into six 30-second
# clips is 3 output minutes of clips, not 60.
target_minutes = sum(d["count"] * d["runtime_minutes"] for d in deliverable_mix)
default_budget_cap_usd = max(flat_default, per_minute_rate * target_minutes)

tracker = CostTracker.for_project(project_id)  # every downstream stage reopens this same ledger
```

Six 30-second clips plus a 12-minute companion computes `6 clips x 0.5 min + 12 min companion = 15 output min` → `max($1.00, $0.30 x 15) = max($1.00, $4.50) = $4.50` — show that sum at the approval gate, not just the final number. If the user trims the clip count or drops the companion at the gate, recompute the sum from the APPROVED plan's minutes, never the pitch's.

Seed one entry per planned paid call. The paid profile here is narrow: `music_gen` beds (one line item per planned bed) and `image_selector` quote/speaker cards (unit cost x count). The podcast audio is content already in hand, so there is no TTS and no video generation. `subtitle_gen`, `audio_enhance` and `transcriber` are local/free — they still get a `0.0` entry, one per logical batch, so every entry starts in a terminal-reachable state:

```python
for bed in music_plan["beds"]:  # one line item per planned bed
    bed_inputs = {
        "prompt": bed["prompt_seed"],
        "duration_seconds": bed["duration_seconds"],  # required — music_gen.estimate_cost raises without it
    }
    tracker.estimate("music_gen", f"clip_bed_{bed['clip_id']}", music_gen.estimate_cost(bed_inputs))

card_inputs = {"query": card_style_seed, "count": card_count}   # quote + speaker cards across the mix
tracker.estimate("image_selector", f"quote_cards x {card_count}", image_selector.estimate_cost(card_inputs))
tracker.estimate("subtitle_gen", f"subtitles x {deliverable_count}", 0.0)
```

Record `metadata.cost_estimate` (itemized) and `metadata.budget_cap_usd` on the brief so the on-screen figure and `cost_log.json` agree.

**On approval** (once the checkpoint is re-written `status="completed"`, `human_approved=True` — see `skills/meta/checkpoint-protocol.md`): arm the tracker with what was actually approved, and clear the placeholder entries this step seeded.

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

### 6. Quality Gate

- the deliverable mix matches the actual source,
- clip counts are realistic for the episode length,
- the brief states whether visuals will be source-led, quote-led, or audiogram-led,
- long-form ambitions are scaled to the available assets.

## Common Pitfalls

- Treating audio-only and video-podcast sources as the same production problem.
- Planning too many deliverables from a weak episode.
- Promising a rich full-episode visual treatment without the assets to support it.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
