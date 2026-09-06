# Idea Director - Reel Batch Pipeline

## When To Use

The operator has dropped a folder of his own gym footage and a few tracks in, and wants
**N finished 9:16 reels out of one sitting** (default N = 5, each reel <= 10 seconds).

This stage does not write copy. It **measures the pool** — how many reels are plannable,
whether a single dollar is spent, what the batch look may touch all fall out of that one
number. A brief written before the pool is indexed is a guess.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `brief.schema.json`, `source_media_review.schema.json` | Artifact validation — brief's root is `additionalProperties: false`, so batch detail lives in `metadata` |
| Tool | `footage_library` (`tools/video/footage_library.py`) | Indexes the pool as identity-locked corpus segments |
| Tool | `video_selector` (`tools/video/video_selector.py`) | Prices the pinned cutaway route — the only paid line in this pipeline |
| Preflight | `registry.provider_menu_summary()["composition_runtimes"]` | Which runtimes exist on this machine (`AGENT_GUIDE.md:280`) |
| Meta | `skills/meta/reviewer.md`, `skills/meta/checkpoint-protocol.md` | Self-review; checkpoint shape + Cost Ledger Governance |
| Cost tracker | `tools/cost_tracker.py` — `CostTracker.for_project(project_id)` | Opens the ledger every later stage reopens |

## Process

### 1. Index The Footage Pool

One call probes the pool through the governance gate, splits every file into cut-sized
segments, drops the blurry ones with a reason, and writes one corpus row per segment with
`identity_locked=True` (`tools/video/footage_library.py:343-375`).

```python
from tools.video.footage_library import FootageLibrary

index = FootageLibrary().execute({
    "footage_dir": operator_footage_dir,          # searched recursively
    "corpus_dir": f"projects/{project_id}/corpus",
    "cuts_per_reel": 5,                           # a 10s reel at ~2s a cut
    # Without this the floor defaults to 1.5s, so every segment in [1.5, 2.0) counts
    # toward usable_segments and therefore toward max_reels and cutaway_count — while
    # no 2.0s slot can actually use one. The valve would promise reels the pool cannot
    # fill, and the shortfall would surface two stages later as a false gate-2 stall.
    "min_segment_seconds": 10.0 / 5,              # the planned hold, not the tool default
})
if not index.success:                     # BOTH failure modes still return a full data payload
    raise SystemExit(index.error)         # read index.error first — the two below are not the same failure
pool = index.data       # usable_segments, max_reels, exclusions, source_media_review
```

Re-running is safe: segment ids derive from (path, in-point, out-point)
(`footage_library.py:588-600`), so a second index of the same folder adds nothing.

**Two failures look alike and are not.** Read `index.error` before you speak:
`segments_unembeddable > 0` with `usable_segments == 0` is the **CLIP stack being down**,
not a thin pool (`footage_library.py:419-435`) — never send the operator back to the gym
over that one; `usable_segments == 0` with exclusions is a genuinely unusable pool
(`:437-449`). Either way, stop and escalate per `AGENT_GUIDE.md` → "Escalate Blockers
Explicitly". Never plan reels against a pool that failed to measure.

### 2. The Valve — Measure The Pool Against The Batch (spec R8)

This is the decision the pipeline turns on. **Show the arithmetic on screen**, not the
verdict alone. Every reel needs `cuts_per_reel` slots, no segment is reused inside a
batch, and at most **one** slot per reel may be a sub-second AI flash accent — so a reel
needs at least `cuts_per_reel - 1` of the operator's own segments no matter what.

```python
cuts = pool["cuts_per_reel"]                  # 5
have = pool["usable_segments"]                # measured, never assumed
requested_reels = 5                           # what the operator asked for

max_reels = pool["max_reels"]                 # have // cuts — reels with ZERO paid help
spare_segments = pool["spare_segments"]       # have - max_reels * cuts; carried to the brief
assisted_ceiling = have // (cuts - 1)         # reels with one AI flash accent each
reels = min(requested_reels, assisted_ceiling)
cutaway_count = max(0, reels * cuts - have)   # cut slots the pool cannot fill
paid_cutaways_armed = cutaway_count > 0
planned_reel_ids = [f"reel_{i:02d}" for i in range(1, reels + 1)]   # reel_01 … the ids every later stage uses
shortfall_reel_ids = planned_reel_ids[:cutaway_count]  # one AI flash a reel, so the armed reels are the first N
```

`max_reels` and `spare_segments` are `footage_library`'s own names, read straight off
`pool` (`tools/video/footage_library.py:410-411`) — do not recompute them under a local
alias. `planned_reel_ids` is minted **here and nowhere else**: it goes onto the brief as
`metadata.reel_ids`, and every later stage takes its reel ids from there.

| `have` | `max_reels` | `assisted_ceiling` | reels planned | cutaways | cost |
|---|---|---|---|---|---|
| 25-29 | 5 | 6+ | 5 | 0 | **$0.00** |
| 22 | 4 | 5 | 5 | 3 | $0.30 |
| 20 | 4 | 5 | 5 | 5 | $0.50 (full shortfall) |
| 19 | 3 | 4 | **4** | 1 | $0.10 |

Say it in one line at the gate: *"31 usable segments, 5 reels x 5 cuts = 25 needed — the
pool covers the batch outright, nothing is generated, this sitting costs $0.00."* Or:
*"19 usable segments — 5 reels needs 25, and even with one AI accent each the pool only
supports 4. I can plan 4 reels for $0.10, or you can add footage."* A shortfall is the
operator's call: offer **fewer reels at $0.00** beside the paid fill and recommend one
(`AGENT_GUIDE.md` → "Recommendation Style").

### 3. Present Both Composition Runtimes (HARD RULE)

`AGENT_GUIDE.md` → "Present Both Composition Runtimes (HARD RULE)" is satisfied **once,
here, for the whole batch** — do not re-interview the operator every sitting. Check what
exists on the machine first (`registry.provider_menu_summary()["composition_runtimes"]`
gives booleans for `ffmpeg`, `remotion` and `hyperframes`), then present the split:

- **Picture plane → ffmpeg.** Cuts, punch-in, speed ramp, flash, whip, grade, grain and
  sharpen splice into the per-cut re-encode (`tools/video/video_compose.py:615-627` calling
  `lib/polish_filters.py:194-240`). Tradeoff: ffmpeg cannot do pop captions at all —
  `subtitle_gen` emits srt/vtt/json (`tools/subtitle/subtitle_gen.py:50-54`) and its
  "karaoke" style is an SRT `<b>` on the active word (`:243-244`, `:261`).
- **Text plane → Remotion.** One overlay pass over the finished picture, via
  `remotion_caption_burn` → the `TalkingHead` composition
  (`tools/video/remotion_caption_burn.py:9, :388`). Tradeoff: Remotion's only grading hook
  is a CSS `filter` — no curves, per-channel balance, grain or continuous ramp
  (`scripts/reel_batch_two_plane_demo.py:9-11`), which is why it does not own the picture.
- **hyperframes — rejected, and say why.** `remotion_caption_burn` is Remotion-specific
  with no parity (`skills/core/hyperframes.md:47, :91`). If it is not installed at all,
  say so plainly rather than staying silent.

This is a **capability** split, not a speed one. Measured on the dev machine at
1080x1920, 10s, 5 cuts by `scripts/reel_batch_two_plane_demo.py` (`:18-21`): picture 9.4s
+ text 13.6s = 23.0s for a single reel, and 117.0s for a five-reel sitting — 23.4s a reel,
the extra 0.4s being the probe between planes. That demo locks
`"render_runtime": "ffmpeg"` (`:111`), calls `video_compose` at
`profile: instagram_reels` (`:123-131`), then `remotion_caption_burn` (`:138-153`).

Lock `render_runtime = "ffmpeg"` for the batch — the value `edit_decisions` carries and
`video_compose` routes on (`tools/video/video_compose.py:1701-1727`). The Remotion text
plane is a separate pass, not a runtime swap. Then log it:

```json
{
  "version": "1.0",
  "project_id": "<project-id>",
  "decisions": [
    {
      "decision_id": "d-001",
      "stage": "idea",
      "category": "render_runtime_selection",
      "subject": "Composition runtime for the reel batch",
      "options_considered": [
        {"option_id": "ffmpeg", "label": "ffmpeg picture plane", "score": 1.0,
         "reason": "Owns every polish filter in lib/polish_filters.py; 9.4s a reel measured"},
        {"option_id": "remotion", "label": "Remotion text plane", "score": 0.9,
         "reason": "TalkingHead word-sync captions; the only runtime that can do them",
         "rejected_because": "cannot grade, grain or ramp — the picture stays ffmpeg"},
        {"option_id": "hyperframes", "label": "HyperFrames", "score": 0.2,
         "reason": "A real third runtime video_compose routes to",
         "rejected_because": "no hyperframes parity for remotion_caption_burn"}
      ],
      "selected": "ffmpeg",
      "reason": "A capability ruling: ffmpeg owns the picture plane and Remotion runs one overlay pass over it as the text plane. Neither runtime can do the other's half.",
      "user_visible": true,
      "user_approved": true
    }
  ]
}
```

Write the **whole artifact**, not a bare entry: the root requires `version`, `project_id`
and `decisions`, and each entry requires `decision_id`, `stage`, `category`, `subject`,
`options_considered`, `selected`, `reason`
(`schemas/artifacts/decision_log.schema.json:7`, `:15`). `selected` is an **`option_id`**
(`:73-75`) — free text there validates but resolves to no option, so the two-plane
phrasing belongs in `reason`. An entry with no string `decision_id` is dropped by the
checkpoint merge with a log warning and nothing else
(`lib/checkpoint.py:495-507`), so the stage's `decision_log` success criterion would fail
without an error to read.

Wait for explicit approval before advancing, and re-log with the **same `category` and
`subject`** if it ever changes (`AGENT_GUIDE.md` → "Re-log Changed Decisions").

### 4. Arm The Identity Lock

`footage_library` already set `identity_locked=True` on every row it wrote
(`footage_library.py:369-371`); `pool["identity_locked"]` comes back `True`. Record it on
the brief and say plainly what it forbids — the operator hears this once, in words,
rather than discovering it as a raise at compose:

- A cut whose `provenance` is `operator_footage` accepts **`face_enhance` presets only** in
  the `grade` slot: `look_filters` resolves the name against the face presets FIRST and only
  then against the colour-grade profiles (`lib/polish_filters.py:165-166`), so the one batch
  look still lands on his cuts — there is no per-provenance variant anywhere in the stack.
  What raises `PolishError` is a colour-grade **profile** on such a cut (`:169-173`), and any
  grain (`:180`) — refused, never silently dropped. The look edit-director authors is
  identity-safe by exactly that rule:
  `{"grade": "talking_head_standard", "sharpen": "sharpen_light"}` — a preset in the grade
  slot, a preset sharpen, no grain key, no profile name.
- AI never generates his face or body. Cutaways are **text-prompt only**: any input
  carrying a media reference is refused recursively, so nesting or renaming the key does
  not dodge it (`tools/video/cutaway_gen.py:127-178`).

### 5. Write The Brief And The Source Media Review

Two artifacts. The `source_media_review` is already built: `review_source_media` returned
the schema shape (`lib/source_media_review.py:346-350`) and `footage_library` hands it
back at `pool["source_media_review"]` (`:416`). Persist that — never probe the pool twice.

The brief carries the batch axes in `metadata` (its root is closed):

```json
{
  "version": "1.0",
  "title": "5am gym reels — week 12",
  "hook": "The set nobody films",
  "key_points": ["one lift a reel", "his own footage only", "one look across the batch"],
  "cta": "Save this for your next session.",
  "tone": "relentless",
  "style": "clean-professional",
  "target_platform": "instagram",
  "target_duration_seconds": 10,
  "metadata": {
    "pipeline": "reel-batch",
    "reel_ids": ["reel_01", "reel_02", "reel_03", "reel_04", "reel_05"],
    "reel_count": 5,
    "cuts_per_reel": 5,
    "usable_segments": 31,
    "max_reels": 6,
    "spare_segments": 1,
    "paid_cutaways_armed": false,
    "cutaway_count": 0,
    "shortfall_reel_ids": [],
    "identity_locked": true,
    "renderer_family": "documentary-montage",
    "render_runtime": "ffmpeg",
    "text_plane": "remotion_caption_burn",
    "budget_cap_usd": 2.0,
    "cost_estimate": {"total_estimated_usd": 0.0, "line_items": []},
    "tracks": [
      {"track_id": "track_01", "path": "projects/<id>/audio/push_day.mp3"},
      {"track_id": "track_02", "path": "projects/<id>/audio/pull_day.mp3"},
      {"track_id": "track_03", "path": "projects/<id>/audio/leg_day.mp3"},
      {"track_id": "track_04", "path": "projects/<id>/audio/five_am.mp3"},
      {"track_id": "track_05", "path": "projects/<id>/audio/last_set.mp3"}
    ]
  }
}
```

`target_duration_seconds` is **one reel**, not the sitting. `reel_count`,
`usable_segments` and `paid_cutaways_armed` are what the success criteria check for.
`shortfall_reel_ids` is the list the valve minted in step 2 — the armed reels in reel-id
form, carried so the per-reel ledger entries can be reconciled against the brief without
re-running the valve. It is the one key here no later stage reads by name:
scene-director works from `paid_cutaways_armed` and `cutaway_count`.

These keys exist only because a later stage reads them by name:

- **`reel_ids`** — `planned_reel_ids` from step 2, the single origin of every reel id in
  the run. Script, scene, edit, compose and publish all key on these; **no later stage
  re-mints one.** The format is `reel_NN`, zero-padded, underscore.
- **`tracks[]`** — `{track_id, path}` per audio file, `track_01` upward. Script-director's
  step 0 reads its track list from here rather than re-scanning the audio folder.
- **`renderer_family`** — `documentary-montage`, a member of the `edit_decisions` enum
  (`schemas/artifacts/edit_decisions.schema.json:227`); this is footage cut from real
  material, and edit-director requires the field non-empty.
- **`max_reels` / `spare_segments`** — `footage_library`'s own names and its own numbers,
  copied off `pool`. The tool defines them as `usable // cuts_per_reel` and
  `usable - max_reels * cuts_per_reel` (`tools/video/footage_library.py:383`, `:411`), so at
  31 usable segments and 5 cuts a reel that is `max_reels = 6` and
  `spare_segments = 31 - 6 x 5 = 1` — one spare, **not** the six that `usable - reels x cuts`
  would give. Never recompute either against the number of reels planned, and never a
  locally invented alias.
- **`cta`** — a **typed root field**, not a metadata key (`brief.schema.json:18`);
  publish-director reads `brief["cta"]` when it writes each export's caption.

### 6. Compute Budget And Seed The Cost Ledger

This is the approval gate — nothing downstream spends until the operator approves it. Take
the cap from the manifest's `orchestration` block, **not** `config.yaml`'s flat global
total: the manifest is what lets the cap scale with batch size.

```python
import yaml
from tools.cost_tracker import CostTracker

manifest = yaml.safe_load(open("pipeline_defs/reel-batch.yaml"))["orchestration"]
flat_default = manifest["budget_default_usd"]                   # $2.00 floor
per_minute_rate = manifest["budget_per_output_minute_usd"]       # $0.75/min — declared, like the floor
target_minutes = reels * 0.1667                                 # a reel is <= 10s
default_budget_cap_usd = max(flat_default, per_minute_rate * target_minutes)
```

A five-reel sitting is `max($2.00, $0.75 x 0.8333) = max($2.00, $0.62) = $2.00` — show
that math at the gate, not just the number. The flat floor does the work until about
twenty reels, where the rate takes over (3.333 min → `max(2.00, 2.50) = $2.50`).

Now price the valve. Only the shortfall costs anything, priced through the selector on
the pin the cutaway tool will execute under. **Build the dict once** and carry that same
object forward: pricing a pinned route and executing an unpinned one is a 15x under-price
the selector stamps as `estimate_divergence` (`tools/video/video_selector.py:310-318`).

The four `cutaway_gen` names below are module-level **constants**, not a tool call: this
stage's `tools_available` is `[footage_library, video_selector]` and no `cutaway_gen`
method is invoked. They are read (`tools/video/cutaway_gen.py:61-64`) purely so the
payload priced here mirrors `cutaway_gen._provider_inputs` key for key (`:296-304`) —
that identity is what keeps the estimate and the later execution on one route.

```python
from tools.video.cutaway_gen import (CUTAWAY_ASPECT_RATIO, CUTAWAY_CLIP_SECONDS,
                                     CUTAWAY_MODEL_VARIANT, CUTAWAY_PROVIDER_PIN)
from tools.video.video_selector import VideoSelector

selector = VideoSelector()

# One placeholder line per ARMED reel, straight off `shortfall_reel_ids` as the valve
# minted it in step 2 — a reel needs at most one AI accent, so the armed reels are the
# first `cutaway_count`. The real prompt text is authored at gate 2 by the scene director into
# `scene_plan.metadata.shortfall[].prompt`, after `refuse_media_references` passes it;
# nothing here is ever sent to a provider.
shortfall_prompts = {rid: "<shortfall cutaway — prompt written at gate 2>"
                     for rid in shortfall_reel_ids}

line_items = []
for reel_id, prompt in shortfall_prompts.items():        # empty when the pool suffices
    payload = {                                          # built ONCE, priced and later executed
        "prompt": prompt, "operation": "text_to_video",
        "allowed_providers": list(CUTAWAY_PROVIDER_PIN), # ["kling"] — the pin
        "preferred_provider": CUTAWAY_PROVIDER_PIN[0],
        "model_variant": CUTAWAY_MODEL_VARIANT,          # "v3/standard"
        "duration": CUTAWAY_CLIP_SECONDS, "aspect_ratio": CUTAWAY_ASPECT_RATIO,
    }
    estimated_usd = selector.estimate_cost(payload)      # $0.10 on the pinned route
    line_items.append({"tool": "video_selector", "reel_id": reel_id,
                       "estimated_usd": estimated_usd, "inputs": payload})

brief["metadata"]["cost_estimate"] = {                   # the shape the approval block reads back
    "total_estimated_usd": round(sum(li["estimated_usd"] for li in line_items), 4),
    "line_items": line_items,
}
```

A `ProviderPinUnresolvedError` from `estimate_cost` means the pin resolves to no live
provider (`video_selector.py:336-343`); it raises rather than returning an unguardable
$0.00 that would slip both approval guards. Escalate it, never estimate past it.

**Seed one entry PER REEL, never one batch entry.** A single batch entry has no honest
terminal state after a mid-batch abort: `reconcile()` is one-shot and terminal-guarded
(`tools/cost_tracker.py:314`), `budget_spent_usd` counts failed entries as spend
(`:186-192`), and `refund()` on a partly-executed entry erases real billing (`:323-337`)
— three reels billed and two dead cannot be booked truthfully under one id. Per-reel is
also the only grain matching the gate-2 approval shape, where the operator signs off reel
by reel.

```python
tracker = CostTracker.for_project(project_id)  # every later stage reopens this ledger
for item in line_items:                        # the routed provider goes in the OPERATION
    tracker.estimate("video_selector", f"{item['reel_id']} cutaway flash via kling_video",
                     item["estimated_usd"])
for reel_id in planned_reel_ids:               # proven-$0: full ceremony, batched zero entries
    if reel_id not in shortfall_prompts:
        tracker.estimate("video_selector", f"{reel_id} pool-covered, no generation", 0.0)
```

The pipeline books under `video_selector` because that is the tool that actually charges:
`cutaway_gen.estimate_cost` and `.execute` both route through it with the pin
(`tools/video/cutaway_gen.py:333-343`, `:379-395`). The routed concrete provider goes in
the **operation string**, never in the key (`skills/meta/checkpoint-protocol.md` → Cost
Ledger Governance).

**A sitting where the pool suffices still arms a full ledger of zero entries** — there is
no lite variant. `cost_log.json` then *proves* the $0.00 rather than merely failing to
record it, and the gate presents `TOTAL ESTIMATED $0.00 of $2.00` rather than silence.
The lightening lever here is the data, never a shorter ceremony.

The fence above writes `metadata.cost_estimate` itself — one line per ARMED reel, so it is
`{"total_estimated_usd": 0.0, "line_items": []}` on the headline $0.00 sitting; the per-reel
grain lives in the tracker entries seeded here, not in `line_items`. Record
`metadata.budget_cap_usd` beside it so the on-screen number and `cost_log.json` agree.
Recording the total alone is not enough: the approval block below reads `li["tool"]` off
those line items to clear the first-paid-use guard, and a brief without them leaves
`video_selector` unapproved for the asset director to trip over at spend time.

#### On Approval — Arm the Tracker

Once the checkpoint is re-written `status="completed"`, `human_approved=True` (see
`skills/meta/checkpoint-protocol.md`): arm the tracker with what was actually approved,
and clear the placeholder entries this step seeded.

```python
import math

# 1. The approved budget figure becomes the tracker's budget total.
#    A figure the operator NAMED is used verbatim — his word is the cap.
#    A bare "approve" approves the plan AS PRESENTED at the gate: the
#    estimate within the default cap. Arm with that cap, floored at the
#    estimate grossed up past the reserve holdback. Arming with the bare
#    estimate leaves zero headroom: usable budget tops out at
#    (1 - reserve_pct) x total, so the plan's FINAL reservation would need
#    E_n <= E_n - reserve_pct x total — never true. reserve_pct comes from
#    the tracker (config's budget.reserve_pct via for_project); never
#    hardcode 0.10.
metadata = brief["metadata"]            # the brief written in step 5
approved_budget_usd = None              # a figure the operator NAMED; None for a bare "approve"
total_estimated_usd = round(sum(li["estimated_usd"] for li in metadata["cost_estimate"]["line_items"]), 4)
min_workable_usd = math.ceil(total_estimated_usd / (1 - tracker.reserve_pct) * 100) / 100 + 0.01  # +1 cent: on an exact-cent division, bare ceil adds zero slack and the final reserve still trips on float dust
tracker.budget_total_usd = approved_budget_usd or max(default_budget_cap_usd, min_workable_usd)
for tool_name in {li["tool"] for li in metadata["cost_estimate"]["line_items"]}:
    tracker.approve_tool(tool_name)  # clears the first-paid-use guard for the approved plan
# Snapshot the ids first: refund() re-merges the ledger from disk and rebinds
# tracker.entries to a new list, so iterating it while refunding walks a stale one.
for entry_id in [e["id"] for e in tracker.entries if e["status"] == "estimated"]:
    tracker.refund(entry_id)  # placeholder, never executed
```

On a full five-reel shortfall the arming line reads
`ceil(0.50 / (1 - 0.10) * 100)/100 + 0.01 = $0.57`, well under the $2.00 cap, so `max()`
picks the cap. On a proven-$0 sitting `min_workable_usd` lands at $0.01 and the `max()` is
inert — the line stays verbatim anyway. Uniformity is the drift guard.

An `estimated` placeholder holds no money — it **does NOT consume budget** — but it is not
terminal, and the compose stage's "every entry in a terminal state" criterion fails on it.
Refunding it here keeps that criterion reachable.
**Never RESERVE a placeholder**: a reservation *does* hold budget, and one left behind by
this gate sits against the batch for the rest of the run.

> **If the operator's named figure is below `min_workable_usd`, say so at this gate** —
> the reserve holdback guarantees the guard blocks the plan's final approved item. Ask him
> to raise the figure or trim the batch. Never silently arm a total certain to trip.

Downstream stages must book under these exact names — see
`skills/meta/checkpoint-protocol.md` → Cost Ledger Governance, which also owns
stranded-entry recovery and ledger-corruption handling. Do not restate either here.

The asset director creates and reserves its OWN entry at the moment it spends, passing
`user_approved=True` because that call fulfils a line item approved here. At $0.10 a
per-reel entry sits below `config.yaml`'s `single_action_approval_usd: 0.50`, so the
threshold does not force the flag — carry it anyway, because the operator genuinely does
approve each reel at gate 2. Work outside this plan still trips `ApprovalRequiredError`,
which is the guard working.

### 7. Quality Gate

- `usable_segments` is a **measured** number from a successful `footage_library` run, the
  reel count is `min(requested, assisted_ceiling)`, and the arithmetic was shown on screen.
- `paid_cutaways_armed` follows from the shortfall, not from taste.
- `decision_log` carries a `render_runtime_selection` entry naming both runtimes plus
  ffmpeg in `options_considered`.
- `identity_locked` is `true` on the brief, the operator has been told what it forbids,
  and `source_media_review` covers every clip in the pool without a second probe.
- `cost_log.json` has one entry per planned reel, and the presented total matches it.
- `metadata.reel_ids` is present and is the only place reel ids are minted; `tracks[]`,
  `renderer_family`, `max_reels` and `spare_segments` are on the brief, and `cta` is a
  root field — script, scene, edit and publish each read one of these by name.

## Common Pitfalls

- Writing the brief before indexing — every number in it is then a guess.
- Reading a dead embedding backend as a thin pool and sending the operator to the gym.
- Planning `requested_reels` when the pool supports fewer. Cut the batch or price the
  fill — never quietly reuse a segment.
- Booking the shortfall under the generator's name instead of `video_selector`, which
  trips the first-paid-use guard at spend time, by design.
- Skipping the ledger because the sitting is free — the full ledger is what makes $0.00 provable.
- Re-interviewing the operator about runtimes every batch. Present once, log once, carry.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.

The checkpoint's `cost_snapshot` is closed to four number keys: pass
`tracker.cost_snapshot()` straight through (`tools/cost_tracker.py:204-209` returns three)
and add `budget_total_usd` from `tracker.budget_total_usd`. Never build it from memory.
