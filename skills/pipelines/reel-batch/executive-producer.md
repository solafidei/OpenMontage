# Executive Producer — Reel Batch Pipeline

## When To Use

The operator hands you **a folder of his own footage plus a few audio tracks** and wants
**N finished 9:16 reels out of one sitting** — beat-cut, word-synced captions taken from
each track's own speech, a hook card, one grade across the batch, no clip reused, and his
face never regenerated.

Right pipeline when the ask sounds like:

- "five reels out of this week's gym footage",
- "cut these clips to these three tracks",
- "a week of Instagram reels from one sitting",
- "same look across all of them, don't repeat any shots".

Wrong pipeline when: the deliverable is one hero piece (`cinematic`); the source is a
single long recording to be sliced (`clip-factory`); the footage is stock and the point is
juxtaposition (`documentary-montage`); or the ask needs the operator's face *generated*
rather than *filmed* — no pipeline does that, and this one refuses it structurally.

## The Standing Bar

Five rules hold across every stage and every reel. They are not stage-local advice; they
are what a finished sitting is checked against.

1. **One look.** The batch look — `grade` and `sharpen`; leave `grain` out, it is refused
   on every operator cut — is chosen once at `edit` and applied identically to every cut of
   every reel, the identity-locked ones included. `lib/polish_filters.py:149`
   (`look_filters`) is the single place it resolves.
2. **No repeats.** Segment-granular within-batch uniqueness, enforced by
   `lib/clip_ledger.py`. Two claims collide when they name the same source and their
   intervals overlap, so one 40s set legitimately yields several non-overlapping 3s cuts.
3. **Identity is never regenerated.** `cutaway_gen` is text-prompt only and refuses any
   media reference recursively, by substring on key names, so renaming or nesting the key
   does not dodge it (`tools/video/cutaway_gen.py:85`, `:127`). `look_filters` resolves
   `grade` against `FACE_PRESETS` **first** (`lib/polish_filters.py:165-166`), so the batch
   look's `talking_head_standard` lands on a locked cut by design; what **raises** on an
   `operator_footage` cut is a `color_grade` **profile** in that slot, or any grain
   (`lib/polish_filters.py:169-180`) — such a cut takes `face_enhance` presets only.
   **`faceswap`, avatars and video-restyle of operator footage are out of scope for this
   pipeline** — the face is never regenerated. That is doctrine, not enforcement: the
   `faceswap` skill is still one Bash call away and nothing here can stop a human
   reaching for it. What *is* enforced is the compose gate
   (`tools/video/video_compose.py` — `_pre_compose_validation`), which blocks a cut whose
   declared `provenance` contradicts the tool that produced its asset, and blocks an
   unsafe look on a locked cut, on all three render runtimes. See
   `tests/contracts/test_identity_chain.py` for the whole chain and its honest limits.
4. **A reel never exceeds 10 seconds.** ~5 cuts each. A five-reel sitting therefore needs
   ~25 usable segments out of the pool.
5. **Free-first.** AI cutaways are a measured shortfall valve, not a look. A typical
   sitting spends **$0.00**; a full five-reel shortfall is **$0.50**.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Pipeline | `pipeline_defs/reel-batch.yaml` | Stage order, gates, tool grants, success criteria |
| Skills | The 7 director skills + `meta/reviewer` + `meta/checkpoint-protocol` | Stage execution |
| Libraries | `lib/clip_ledger.py`, `lib/polish_filters.py` | Called directly by directors — **not** `tools_available` entries |
| Schemas | `schemas/artifacts/` | Checkpoint-time validation |
| Playbook | `clean-professional` (recommended) | Quality constraints |

**`reel_plan` is schema-validated at the `edit` checkpoint**
(`schemas/artifacts/reel_plan.schema.json`, registered in `ARTIFACT_NAMES`). A malformed one
is a hard `CheckpointValidationError`, not a silent pass. What the schema cannot see is
cross-artifact truth — that `cut_ids` partition the spine exactly, and that each
`music_asset_id` names a real asset. Those are G5's job.

## Run Order

| # | Stage | Director | Produces | Gate |
|---|-------|----------|----------|------|
| 1 | `idea` | `idea-director.md` | `brief`, `source_media_review`, `decision_log` | **Gate 1 — human** |
| 2 | `script` | `script-director.md` | `script` | auto |
| 3 | `scene_plan` | `scene-director.md` | `scene_plan`, `decision_log` | **Gate 2 — human** |
| 4 | `assets` | `asset-director.md` | `asset_manifest`, `cost_log` | auto |
| 5 | `edit` | `edit-director.md` | `edit_decisions`, `reel_plan` | auto |
| 6 | `compose` | `compose-director.md` | `render_report`, `final_review` | auto |
| 7 | `publish` | `publish-director.md` | `publish_log` | **Gate 3 — human** |

Resolve where to start from the checkpoints, and **pass the pipeline type**:

```python
from lib.checkpoint import get_next_stage, read_checkpoint
from lib.paths import PROJECTS_DIR

next_stage = get_next_stage(PROJECTS_DIR, project_id, "reel-batch")
current = read_checkpoint(PROJECTS_DIR, project_id, next_stage) if next_stage else None
```

Omitting the third argument falls back to the canonical nine-stage list
(`lib/checkpoint.py:833` → `:28-29`) and sends you to `research`, a stage this pipeline
does not have. The stage names here are all canonical, which is what buys the artifact
validation in `CANONICAL_STAGE_ARTIFACTS` (`lib/checkpoint.py:31-41`) — never rename one.

## The Three Gates

The manifest gates three stages, and its `human_approval_default` values are **binding** —
never re-judge them. Write `status="awaiting_human"`, present, and **end your turn**; doing
further pipeline work in the same response is a gate violation
(AGENT_GUIDE.md → Human Checkpoint Protocol).

### Gate 1 — `idea`

The pool is *measured*, not assumed. `footage_library` returns `usable_segments`,
`max_reels` and `spare_segments` (`tools/video/footage_library.py:402-411`), and the reel
count has to be plannable against them. It also returns the `source_media_review` payload
(`:416`) and stamps `identity_locked: True` on the whole pool (`:412`).

This gate is also where **both composition runtimes are presented once**, with the measured
two-plane rationale, and logged as a `render_runtime_selection` entry in `decision_log`
with both runtimes in `options_considered` — satisfying AGENT_GUIDE.md's "Present Both
Composition Runtimes (HARD RULE)" for the whole sitting rather than re-interviewing the
operator every batch.

Budget arming lives here too. **The EP never arms the ledger itself** — the cost gate in
`idea-director.md` owns every estimate and every reservation for the run. Your job at this
gate is to confirm the brief states the reel count, the usable-segment count, and whether
any paid cutaway is armed at all.

### Gate 2 — `scene_plan` (the cut list plus the hook, per reel)

**This is the last gate before any paid call, and that is precisely what lets `assets` run
unattended.** Present it **per reel**, not as one batch blob: each reel's beat-snapped cut
slots, its hook line, its track, and — if the pool fell short — the exact cutaway prompt
that would fire for it.

Approve or reject per reel. If the operator rejects one reel's cut list, only that reel's
claims go back to the pool:

```python
from lib.clip_ledger import ClipLedger

ledger = ClipLedger.for_project(project_id)
ledger.release_reel("reel_03")      # only this reel's LIVE claims return to the pool
```

`release_reel` leaves already-reconciled claims untouched — a shipped record is not a
reservation (`lib/clip_ledger.py:204-210`). The other reels keep their segments, so a
single rejection never re-plans the batch.

Approval is per-gate: a "go ahead" at Gate 1 does not cover Gate 2. A genuine full-run
pre-authorisation must be recorded as a `decision_log` entry with
`category: "budget_tradeoff"` to count.

### Gate 3 — `publish`

Per-reel caption copy, hashtag set, track credit and posting slot. One caption pasted
across five reels fails the stage's own `review_focus`.

## Cumulative State

```
EP_STATE:
  pipeline: reel-batch
  playbook: <selected>
  render_runtime: <locked at Gate 1>

  # reel-batch specific
  reel_count_target: 0
  reel_ids: []                # minted at Gate 1 as brief.metadata.reel_ids; reel_01 … reel_NN
  cuts_per_reel: 5
  usable_segments: 0          # from footage_library
  spare_segments: 0           # usable - max_reels * cuts_per_reel
  cutaway_valve: closed       # opens ONLY on a measured shortfall
  tracks: []                  # one per reel, never shared
  batch_look: null            # grade / sharpen — one dict, every cut, locked included
  reels_reconciled: []        # reel_ids whose claims are permanent
  reels_rendered: []

  artifacts: {idea, script, scene_plan, assets, edit, compose, publish}
  revision_counts: {}
  send_backs_used: 0
  issues_log: []
```

`reel_ids` is minted once, at Gate 1, into `brief.metadata.reel_ids`. **No later stage
re-mints them** — every stage reads its ids from there, cut ids are `<reel_id>-<nn>`, and a
stage that invents its own spelling (`reel-01`, `reel01`) is a send-back, not a rename.

## Cross-Stage Checks

Run these after the director finishes and before you checkpoint. They are the EP's own
checks — the manifest's `review_focus` items are run separately by `meta/reviewer`.

```
G1 — after IDEA
  - usable_segments MEASURED (not estimated), and reel_count x cuts_per_reel <= usable_segments?
  - If short: reels capped at the assisted ceiling `usable_segments // (cuts_per_reel - 1)`
    — at most ONE cut per reel may be an AI flash — the shortfall itemised per **cut**, and
    the operator told the cost before Gate 2?
  - decision_log has render_runtime_selection naming BOTH runtimes?
  - source_media_review covers every clip in the pool?

G2 — after SCRIPT
  - One beat grid AND one word-level transcript per track?
  - Speech contamination measured per track (tools/analysis/beat_grid.py:449) — not assumed?
    A grid whose beats are mostly speech is not a grid to cut on.
  - Each reel's spoken line self-contained at <= 10s? `hook["end_seconds"] <= snap_grid[2]`?
  - Each reel's `snap_grid` carries at least `cuts_per_reel + 1` boundaries — six for a
    five-cut reel? Fewer and `scene-director`'s `cut_slots` raises `ValueError`.

G3 — after SCENE_PLAN
  - Every cut slot snapped to a beat from ITS OWN reel's grid (not the batch's first track)?
  - Slots per reel total <= 10 seconds INCLUDING any speed ramp's output duration?
  - Every slot claimed against the clip ledger, and every slot names its provenance?
  - Every reel's hook ends at or before its own `snap_grid[2]` (past the first snap
    boundary is fine, the second is not)?

G4 — after ASSETS
  - Every planned cut slot resolves to a real file on disk?
  - Cutaway count == len(scene_plan["metadata"]["shortfall"]), and every fired cutaway's
    cut_id appears in that list — nothing fired against a slot the shortfall never named?
  - No cutaway prompt carries a media reference (the tool refuses; confirm none was attempted)?
  - cost_log has an entry for every paid call, and no entry names a tool the gate did not arm?

G5 — after EDIT
  - edit_decisions carries ONE flat cuts[] covering every reel, ids <reel_id>-prefixed?
  - reel_plan has exactly one entry per reel, and every cut id appears in exactly one of them?
  - Every reel_plan entry carries reel_id, track_id, music_asset_id, subtitle_source,
    subtitle_srt_source, hook (a string), cut_ids[], corrections, caption_confidence —
    with music_asset_id / subtitle_source / subtitle_srt_source being asset_manifest
    asset ids, NOT paths? The schema types the shape; only this bullet checks the ids resolve.
  - Per-reel axes are in reel_plan, NOT smuggled into edit_decisions.metadata?
  - `edit_decisions.batch_look` (spine root) survives `look_filters(look, "operator_footage")`
    — a `face_enhance` preset in the `grade` slot, no `grain` key, no `color_grade` profile
    name — and it is the SAME single dict for every reel, locked cuts included?

G6 — after COMPOSE
  - One render_report.outputs[] entry per reel, each carrying platform_target?
  - Every file ffprobes at 1080x1920 with an audio stream?
  - Captions clear the lower UI band (remotion_caption_burn safe_zone,
    tools/video/remotion_caption_burn.py:125)?
  - cost_log: every entry terminal (completed/failed/refunded), totals matching real spend?

G7 — after PUBLISH
  - Per-reel caption copy and hashtags — no paste-across?
  - Posting order and spacing stated, so five reels are not dumped in one hour?
```

Before handing `edit` to `compose`, audit the whole batch once:

```python
from lib.clip_ledger import ClipLedger

ClipLedger.for_project(project_id).assert_no_reuse()   # raises ClipReuseError
```

`assert_no_reuse` checks every pair of live claims for an overlap on the same source
(`lib/clip_ledger.py:216-228`). It is cheap; run it even when you are sure.

## Execution Limits

| Limit | Value | Source |
|-------|-------|--------|
| Max revisions per stage | 3 | `orchestration.max_revisions_per_stage` |
| Max total send-backs | 3 | `orchestration.max_send_backs` |
| Max wall time | 20 min | `orchestration.max_wall_time_minutes` |
| Budget cap | `max($2.00, $0.75 x output_minutes)` = **$2.00** for five reels | `orchestration.budget_*` |

**Send-back rules.** A send-back returns work to an *earlier* stage; a revision re-runs the
current one. Legitimate pairs, and nothing else:

- `compose` → `edit` — a look or a cut length that only shows in the render.
- `edit` → `scene_plan` — the cut list cannot be built as approved.
- `assets` → `scene_plan` — a slot has no obtainable asset. **A send-back past Gate 2 re-opens
  a human gate**; never route around it by quietly re-planning the reel in place.
- `script` → `idea` — the pool cannot carry the reel count after all.

Scope the send-back to **the reel that failed**, not the batch, and release only that reel's
claims. When a cap is exhausted, stop and escalate as a structured blocker (AGENT_GUIDE.md →
"Escalate Blockers Explicitly"): what was attempted, what failed, whether it is auth /
provider / tool bug / creative, the options, your recommendation. **Never silently ship four
reels when five were approved** — a short batch is a decision the operator makes, not you.

On wall time: the render itself is small. Measured on the dev machine at 1080x1920, 10s,
5 cuts — picture 9.4s + text 13.6s = **23.0s** for a single reel, and **117.0s for a
five-reel sitting**, i.e. 23.4s a reel, the extra 0.4s being the probe between planes
(`scripts/reel_batch_two_plane_demo.py`). The 20-minute budget is for the whole sitting,
indexing and transcription included, not the render.

## Mid-Batch Failure — The Batch Is Resumable Per Reel

**`compose` owns the only per-reel `in_progress` checkpoint**, and the manifest names it
explicitly: *"a mid-batch abort leaves a resumable checkpoint rather than a half-written
report"*. After each reel's text plane finishes, `compose-director.md` re-writes the compose
checkpoint with `status="in_progress"` and a `metadata.partial_progress` carrying
`completed_reel_ids`, `reel_outputs`, `render_seconds` and `failed_reels`. A reel counts as
complete only once its captioned master exists on disk; on resume compose renders only the
reels absent from `completed_reel_ids` and rebuilds `render_report.outputs[]` from the union
of recorded and new outputs.

**`assets` writes no `partial_progress`, and must not be asked for one.** It is resumable
because it is idempotent, by three mechanisms it already has:

1. the cutaway `cache_dir` — a prompt already generated is a cache hit, `estimate_cost`
   skips it and `execute` stamps `cached: true` with `cost_usd: 0.0`, so a re-run is free
   rather than double-billed;
2. the clip ledger — claims survive the crash, and re-claiming what Gate 2 already claimed
   raises rather than duplicating;
3. every ledger entry reaching a terminal state before the stage ends, so a resume finds
   nothing stranded.

The mechanics — `in_progress` checkpoints, `partial_progress`, and resuming from the middle
of a stage — are in `skills/meta/checkpoint-protocol.md` → Steps 4 and 7. Follow them there.

Two batch-specific consequences:

1. **The clip ledger is a separate file** (`projects/<id>/artifacts/clip_ledger.json`) with
   the same crash-safe persistence as the cost log. Reels already reconciled keep their
   segments permanently; only the aborted reel's live claims come back, via
   `release_reel(reel_id)`. **Never rebuild the ledger by hand and never restart a sitting
   from zero because one reel failed.**
2. **Sweep the money ledger before resuming.** Stranded-entry recovery and corrupt-ledger
   handling are shared rules — see `skills/meta/checkpoint-protocol.md` → **Cost Ledger
   Governance**. Do not improvise a local variant of them here.

Every checkpoint you write carries a `cost_snapshot` closed to exactly four number keys.
Pass the tracker's own snapshot through and add the total — never assemble it from memory,
and never write the legacy `spent_usd` / `approved_budget_usd` keys, which are rejected at
write time:

```python
from tools.cost_tracker import CostTracker

tracker = CostTracker.for_project(project_id)
cost_snapshot = tracker.cost_snapshot()                       # 3 keys, tools/cost_tracker.py:204-209
cost_snapshot["budget_total_usd"] = tracker.budget_total_usd  # the 4th
```

## Definition Of Done For A Sitting

The sitting is done when **all** of these hold:

- **N finished files**, one per approved reel — not N-1, and not one long file to be split.
- **Each reel is <= 10 seconds**, 1080x1920, with an audio stream, verified by ffprobe on
  the file that actually exists.
- **Each reel carries its own track and its own hook.** Two reels sharing a track means the
  batch reads as one video cut into pieces.
- **No clip is reused within the batch** — `assert_no_reuse()` passes on the live ledger.
- **One look across the batch**, and it is identity-safe: a `face_enhance` preset in the
  `grade` slot, no `grain` key, and no `color_grade` profile name anywhere in `batch_look`.
- **`render_report` + `final_review`** produced from the rendered files, and a `cost_log`
  with every entry terminal and totals matching what the run actually spent.
- **`publish_log`** with one entry per reel: output path, caption copy, track credit,
  posting slot.

## Common Pitfalls

- **Planning the reel count before measuring the pool.** Five reels x five cuts is 25 usable
  segments. `footage_library` reports `max_reels` (`usable // cuts_per_reel`) — the ceiling
  with no paid help at all — and `spare_segments`, the remainder, so never negative. The
  plannable count is the *assisted* ceiling, `usable_segments // (cuts_per_reel - 1)`, because
  at most one cut per reel may be an AI flash; the cutaway count that buys it is
  `max(0, reels x cuts_per_reel - usable_segments)`. Both numbers are the operator's choice at
  Gate 1 — fewer reels, or that many priced cutaways.
- **Treating Gate 2 as a formality.** It is the last human checkpoint before money moves.
  Skipping or batching it away removes the only thing that makes an unattended `assets`
  stage safe.
- **Putting a `color_grade` profile (or any grain) in the batch look.** `look_filters`
  raises on the first `operator_footage` cut rather than silently dropping it, so this shows
  up as a hard failure of the whole batch — which is the point. There is one look for the
  whole batch and no per-provenance variant — `cut_filters` takes a single `look` and only
  branches on provenance to raise — so the only workable batch look carries a `face_enhance`
  preset grade and no grain at all.
- **Sharing one track across reels**, or reusing the same hook with the words shuffled.
  Five reels that sound alike perform like one.
- **Stuffing per-reel data into `edit_decisions`.** It structurally cannot hold a batch: one
  `audio.music` object with a single `asset_id` and one `subtitles` object
  (`schemas/artifacts/edit_decisions.schema.json:145-149`, `:185`). Per-reel axes belong in
  `reel_plan`.
- **Rendering both planes in one pass.** Picture is ffmpeg, text is exactly one Remotion
  overlay pass over the finished picture. It is a capability split, not a speed one.
- **Restarting the batch after a mid-render crash.** Resume per reel; the ledger and the
  checkpoints already know which reels are done.
