# Scene Director - Reel Batch Pipeline

## When To Use

The `script` artifact exists: every track carries a beat grid and a word-level
transcript, and each planned reel has its hook line and caption line. Your job is
to turn that into **N reel groups of beat-snapped cut slots**, each slot holding a
named segment of the operator's own pool, each reel at or under 10 seconds.

This stage is **gate 2 — the cut-list-plus-hook approval, per reel**, and the last
stage before any paid call. `assets` runs unattended on exactly what is approved here,
so the plan must be executable without a second conversation: every slot already names
its segment, its beat, and its provenance.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/scene_plan.schema.json`, `clip_ledger.schema.json` | Artifact validation (`scenes[]` is `additionalProperties: false`; `metadata` is free) and the claim record every slot writes |
| Schema | `schemas/artifacts/decision_log.schema.json` | The second artifact this stage `produces` — written only when a shortfall forces a ruling; entries are `additionalProperties: false` |
| Prior artifact (required) | `state.artifacts["script"]["script"]` | Per-reel `snap_grid`, `window`, `hook`, `caption`, `track_id`, `cut_policy`; per-track beat grid and transcript for audit |
| Prior artifact (optional in the manifest, binding here) | `state.artifacts["idea"]["brief"]` | `reel_ids`, `cuts_per_reel`, `usable_segments`, `max_reels`, `spare_segments`, `paid_cutaways_armed`, `cutaway_count`, `renderer_family`, `render_runtime` |
| Prior artifact (optional) | `state.artifacts["idea"]["source_media_review"]` | Per-clip exclusion reasons — what a thin pool is thin *because of* |
| Library | `lib/clip_ledger.py` | Segment claims — within-batch uniqueness |
| Library | `lib/corpus.py`, `lib/clip_embedder.py` | The indexed pool and text ranking over it |
| Guard function (from the `cutaway_gen` tool module — a pure check, not a tool call) | `refuse_media_references` | Dry-run the identity guard on a planned prompt |
| Tools | none — `tools_available: []`. This stage plans; it does not call tools or spend | — |

## Mental Model

A reel is **a 10-second window of one track, chopped on that track's own grid**.
You are not choosing durations; the script's `snap_grid` already chose them. You choose
*which grid lines* become edges and *which segment* sits between them. Two constraints do the work, and
they pull against each other:

- **10 seconds, ~5 cuts.** A cut is ~2s. Nothing develops — a slot either reads in
  two seconds or it is the wrong slot.
- **No segment twice in the batch.** Five reels compete for one pool, so plan reels in
  order, expect the last one to be the hard one, and fix a thin pool here — after gate 2
  a shortfall costs money or costs a reel.

## Process

### 1. Load The Grid, The Pool And The Ledger

```python
from pathlib import Path
from lib.checkpoint import PROJECTS_DIR, read_checkpoint
from lib.clip_ledger import ClipLedger
from lib.corpus import Corpus

script_ckpt = read_checkpoint(PROJECTS_DIR, project_id, "script")   # Optional[dict]
idea_ckpt = read_checkpoint(PROJECTS_DIR, project_id, "idea")       # lib/checkpoint.py:766-782
if script_ckpt is None or idea_ckpt is None:
    raise RuntimeError("scene_plan needs both the script and the brief on disk")

script = script_ckpt["artifacts"]["script"]
brief = idea_ckpt["artifacts"]["brief"]
review = idea_ckpt["artifacts"].get("source_media_review")   # carried to the gate-2 close

reel_ids = brief["metadata"]["reel_ids"]        # the only origin of a reel id in this run
cuts_per_reel = brief["metadata"]["cuts_per_reel"]
armed = brief["metadata"]["paid_cutaways_armed"]       # is the paid valve open at all
armed_cutaways = brief["metadata"]["cutaway_count"]    # how many cuts it was opened for

# The index is keyed to the POOL, not this batch — read the path the idea stage
# resolved (brief.metadata.corpus_dir), never rebuild it from project_id.
corpus = Corpus(Path(brief["metadata"]["corpus_dir"]))
corpus.load()                        # __init__ does not read disk (lib/corpus.py:169-174, :209)
pool = [r for r in corpus.records if r.identity_locked]
ledger = ClipLedger.for_project(project_id)    # lib/clip_ledger.py:114-134
```

`identity_locked=True` is set on every row `footage_library` writes and nowhere else
(`tools/video/footage_library.py:473-475`), so that filter *is* the operator's pool.
`ClipLedger.for_project` creates the ledger on first call and re-opens the same file on
every later one — never build a second ledger from a hand-written path.

Take the reel count, the reel ids and the armed/not-armed cutaway verdict from the brief,
not from your own count of the pool: the gate's `usable_segments` / `max_reels` /
`spare_segments` numbers (`tools/video/footage_library.py:487-488`, `:518`) are what the cost gate
in `idea-director.md` priced.

**The brief is `optional_artifacts_in` in the manifest and binding here.** `read_checkpoint`
returns `None` when the stage never ran, so the read is guarded above. Without the brief the
reel count, the reel ids and the armed verdict are all unknown, and a plan built on a guessed
reel count commits `assets` to spend nobody approved — stop and escalate as a structured
blocker rather than planning. `source_media_review` is optional in the ordinary sense: it
carries the per-clip exclusion reasons (too short, too soft, no motion) that explain a thin
pool, and those reasons are what you quote in the gate-2 summary when a reel comes up short.

### 2. Snap Cut Slots To The Grid

The cut policy was resolved at `script`. Each reel there carries a `snap_grid` that is
**reel-local and already offset** (`snap_grid[0] == 0.0`), built from that track's beats,
downbeats or phrases according to the reel's own `cut_policy` — including the demotion to
phrase boundaries when the track measured speech-contaminated. That grid is the only one
you plan against. The analyser's raw `beats_sec` / `downbeats_sec` ride along in
`script.metadata.tracks[]` for audit and for a re-plan; never re-derive slots from them,
and never re-run the analyser here. Slot edges are grid lines — never `total / 5` —
except the one edge a shortfall slot's shrink shares with the neighbour absorbing its
remainder (step 4, decision-log #14): that edge is deliberately not a grid line. On a
reel's last slot, when the neighbour has no source footage left to extend into, it is the
reel's own final edge that moves instead — the shrink shortens the reel rather than
silently overrunning a claim the source cannot back (step 4's fallback), and
`total_seconds` is written to match. Every other edge in the reel still comes from the
grid.

```python
def cut_slots(snap_grid, offset, cuts=5):
    """Slots for one reel, taken from the grid the script already resolved."""
    if len(snap_grid) < cuts + 1:
        raise ValueError(f"{len(snap_grid)} boundaries — too few edges for {cuts} cuts")
    span = len(snap_grid) - 1                      # intervals, not boundaries
    edges = [snap_grid[round(i * span / cuts)] for i in range(cuts + 1)]
    return [{"index": i,
             "beat_seconds": round(edges[i] + offset, 3),   # absolute track time
             "start_seconds": edges[i], "end_seconds": edges[i + 1]}   # reel-local
            for i in range(cuts)]

reel = script["metadata"]["reels"][0]          # one entry per planned reel
reel_id = reel["reel_id"]                      # from brief.metadata.reel_ids — never re-minted
slots = cut_slots(reel["snap_grid"], reel["window"]["offset_seconds"], cuts=cuts_per_reel)
```

`snap_grid` is already bounded by the reel's `window`, so `slots[-1]["end_seconds"] <= 9.8`
holds by construction — script's own step 5 caps the window there, so the 9.8-second
ceiling is structural here too, not a check you remember to run. Spacing the edges across
`span` rather than stepping by a floored stride is what keeps
the last edge on `snap_grid[-1]`: a grid whose interval count is not a multiple of `cuts`
(seven intervals, five cuts) would otherwise stop at boundary 5 and end the reel early
inside its own window, and no upper-bound check would catch it. Store the reel-local
`start_seconds` / `end_seconds` in `scenes[]` and the absolute `beat_seconds` in metadata,
so the operator can hear the cut you are describing. Carry the
reel's `cut_policy` into the plan as a recorded fact: the policy is already baked into
`snap_grid`, so do not re-branch on beats, bars or phrases here.

### 3. Pick The Segment For Each Slot

Rank the pool against the slot's one-line description, then take the first candidate
long enough to fill it.

**Hold segments back for the reels still to plan.** Claiming greedily reel by reel spends
the pool front-to-back, so the whole shortfall lands in the last reel or two — three armed
cutaways stacking into `reel_05`. Gate 1 priced one flash accent *per reel* and step 9
asserts that cap (decision log #6), so a greedy pass fails the gate having already claimed
half the pool. Before ranking, reserve one segment for every remaining reel's minimum:

```python
reels_after = len(reel_ids) - reel_index - 1        # reels not yet planned
floor = reels_after * (cuts_per_reel - 1)           # each still needs cuts-1 of its own
budget = len(available) - floor                     # segments this reel may claim
```

A reel that runs out of `budget` before its slots are full takes its one flash accent and
moves on. That is the same arithmetic gate 1 used, applied per reel instead of per batch.

```python
from lib.clip_embedder import embed_texts       # lib/clip_embedder.py:131

planned_clip_ids: set[str] = set()     # every clip_id this planning pass has taken
shortfall: list[dict] = []             # metadata.shortfall — one entry per shortfall CUT
slot_tail: dict[int, dict] = {}        # slot index -> its claimed segment's tail room,
                                        # for the last-slot shortfall branch (step 4) to
                                        # read. A local dict, not a key on the scene object
                                        # — scenes[] is additionalProperties:false.

slot = slots[0]
cut_id = f"{reel_id}-{slot['index'] + 1:02d}"                   # "reel_02-01" — minted here
slot_description = "rack pull lockout, low angle, side light"   # becomes scenes[].description

query = embed_texts([slot_description])[0]
locked_ids = {r.clip_id for r in pool}         # R5: only the operator's own rows are cuttable
ranked = [(rec, s) for rec, s in
          corpus.rank_by_text(query, k=max(20, len(locked_ids)), kind="video",
                              exclude_ids=planned_clip_ids)   # lib/corpus.py:326-365
          if rec.clip_id in locked_ids][:20]
```

`k` is at least the size of the locked pool because `rank_by_text` truncates *before* the
identity filter runs. On a corpus that also holds stock rows, a fixed `k=20` can come back
with twenty network clips and nothing of the operator's, turning a slot with good candidates
into a false shortfall — the one outcome that costs $0.10 and burns an armed cutaway.

`exclude_ids` keeps one planning pass from proposing the same row twice; it is a
convenience, not the guarantee — the guarantee is the ledger, next. If the description
is generic (a whole reel of "heavy set, low angle") ranking adds nothing: order the
remaining pool by `motion_score`, then by interval length.

### 4. Claim The Segment — The Clip Ledger

Every slot claims its segment before it is written into the plan. A claim is
`(source, [in_seconds, out_seconds))`; two collide when they name the same source and
their intervals **overlap** — touching cuts do not, which is what lets one 40-second set
yield several distinct slots (`lib/clip_ledger.py:83-96`).

```python
from lib.clip_ledger import SegmentAlreadyClaimedError
from tools.video.cutaway_gen import DEFAULT_FLASH_SECONDS, refuse_media_references

length = slot["end_seconds"] - slot["start_seconds"]
for record, score in ranked:
    seg_in, seg_out = record.interval          # lib/corpus.py:126-149
                                               # safe only because the rank above
                                               # passed kind="video": interval RAISES
                                               # on an image row rather than answering (0,0)
    if seg_out - seg_in < length:
        continue                               # too short to fill the slot
    take_out = seg_in + length                 # head of the segment, trimmed to the slot
    if not ledger.is_available(source=record.local_path,
                               in_seconds=seg_in, out_seconds=take_out):
        continue                               # cheap probe, re-reads the file
    try:
        claim_id = ledger.claim(reel_id=reel_id, source=record.local_path,
                                in_seconds=seg_in, out_seconds=take_out,
                                clip_id=record.clip_id)
    except SegmentAlreadyClaimedError:
        continue                               # lost the race — take the next candidate
    planned_clip_ids.add(record.clip_id)
    # Remember this claim's tail room. The LAST-slot shortfall branch below needs to
    # know, for the slot immediately before it, whether its source has any unclaimed
    # footage past `take_out` before it can extend into it. A local dict keyed by
    # slot index — not a key on the scene object, since scenes[] is
    # additionalProperties:false — declared alongside `planned_clip_ids` in step 3.
    slot_tail[slot["index"]] = {"source": record.local_path, "take_out": take_out,
                                "seg_out": seg_out, "clip_id": record.clip_id}
    break
else:
    # Author the prompt BEFORE the entry (step 6's rules and guard): the shortfall
    # entry is the only place the gate-2-approved prompt ever lives.
    prompt = "chalk dust drifting through a hard side light, black background, macro"
    refuse_media_references({"prompts": [prompt]})   # tools/video/cutaway_gen.py:127-178
    shortfall.append({"reel_id": reel_id, "cut_id": cut_id, "prompt": prompt,
                      "why": slot_description, "length_seconds": length})
    # R8: sub-second flash accents, not B-roll. This slot does not keep its own full
    # beat-grid interval — it shrinks to the flash length and the remainder goes to
    # the neighbouring operator clip, which extends to cover it. On a middle slot the
    # flash keeps its own beat (`start_seconds` untouched); only the boundary it shares
    # with that neighbour moves — that neighbour is not yet claimed, so steps 3/4 simply
    # size its source interval to the new span when they run on it next — so
    # `total_seconds` and the reel's outer window edges do not move.
    #
    # On the reel's LAST slot the neighbour is BEHIND it, not ahead, and it is ALREADY
    # claimed: growing its timeline span the same way the middle-slot branch does would
    # claim more timeline than its source actually covers — the defect decision-log #14
    # named and the operator's ruling on it fixes. The fix extends that neighbour's
    # SOURCE too, by claiming the abutting sliver of the same file as a second claim,
    # and only when no footage is left to claim does it fall back to shortening the
    # reel by `remainder` instead of silently overrunning the source.
    flash_length = min(length, DEFAULT_FLASH_SECONDS)
    remainder = round(length - flash_length, 3)
    if slot["index"] + 1 < len(slots):
        slot["end_seconds"] = round(slot["start_seconds"] + flash_length, 3)
        # Not yet claimed — its length simply grows before step 3/4 run on it.
        slots[slot["index"] + 1]["start_seconds"] = round(
            slots[slot["index"] + 1]["start_seconds"] - remainder, 3)
    else:
        # The flash moves to the TAIL — the only neighbour is behind it, not ahead.
        slot["start_seconds"] = round(slot["end_seconds"] - flash_length, 3)
        prev_idx = slot["index"] - 1
        tail = slot_tail.get(prev_idx)
        new_out = round(tail["take_out"] + remainder, 3) if tail else None
        if (tail is not None and new_out <= tail["seg_out"]
                and ledger.is_available(source=tail["source"],
                                        in_seconds=tail["take_out"],
                                        out_seconds=new_out)):
            # HEADROOM: the previous cut's segment has `remainder` more seconds of
            # real footage past its current out-point. Claim the abutting sliver as
            # a SECOND claim on the same source — it does not overlap the existing
            # one, so `is_available` allows it — and grow the timeline span and the
            # source span TOGETHER. The reel keeps its full approved length and grid.
            ledger.claim(reel_id=reel_id, source=tail["source"],
                         in_seconds=tail["take_out"], out_seconds=new_out,
                         clip_id=tail["clip_id"])
            slots[prev_idx]["end_seconds"] = slot["start_seconds"]
            # Record the extended out-point: the cut this stage writes for `prev_idx`
            # in step 8 must carry `new_out`, not the original `take_out`, or the
            # written scene_plan disagrees with what the ledger just claimed and the
            # next stage resolves the shorter, wrong source span.
            slot_tail[prev_idx]["take_out"] = new_out
        else:
            # FALLBACK: no tail left on the previous cut's source (`new_out` would run
            # past `seg_out`), or the sliver is already claimed by another reel. Do
            # NOT move the previous slot — it has no more footage to give, moving it
            # anyway is exactly the ~1.34s-short defect this branch replaces. Leave the
            # flash at the tail of its own shrunk slot and let the reel end `remainder`
            # seconds early instead: pull the flash's own end back by `remainder` too,
            # so it still lands flush against the (unmoved) previous slot with no gap
            # between them. This is the honest degradation — a reel that is
            # `remainder` seconds shorter than approved but still cuts clean on the
            # beat — over silently overrunning a claim the source cannot back. The
            # caller writes this slot's true `end_seconds` into
            # `metadata.reels[].total_seconds` at step 8, so edit and compose plan
            # against the real length rather than the originally-approved 9.8.
            slot["end_seconds"] = round(slot["end_seconds"] - remainder, 3)
            slot["start_seconds"] = round(slot["end_seconds"] - flash_length, 3)
```

**On a collision.** `is_available` is a probe, not a reservation — another reel stage can
claim between the probe and the claim, so `SegmentAlreadyClaimedError` must be caught,
not prevented. The re-pick is always the same move: **advance to the next candidate in
`ranked`; never widen the interval and never shrink it to squeeze past the overlap
test.** A one-frame-shorter cut that dodges the overlap is the exact failure this ledger
exists to stop. If the ranked list is exhausted the slot is a shortfall (step 6) — a
planning outcome, not an error to route around. The error names the holding reel and
claim id (`:158-165`); put that in the plan's notes when a reel ends up with a visibly
second-choice slot.

**Never hand-edit `clip_ledger.json`.** A corrupt ledger raises
`ClipLedgerCorruptedError` carrying its own recovery instruction (`:333-365`): recover
the claims from the reels already cut, or abandon the batch — a reset ledger reports no
claims and the batch ships the same footage in two reels. The **cost** ledger is a
different subject; its corruption and stranded-entry rules live in
`skills/meta/checkpoint-protocol.md` → Cost Ledger Governance.

**Do not reconcile at this gate.** `reconcile_reel` is the shipped record, and
`_settle_reel` only settles claims still in `claimed` (`:268-278`), so a reconciled reel
can never return its segments to the pool. Claims stay `claimed` through gate 2 — they
already hold the segment out of the pool (`:63-65`) — and the stage that renders the
reel reconciles it.

### 5. Declare Provenance In The Plan

Spec R5 is default-deny: **provenance is declared at ingest and never inferred from
pixels.** Every planned cut names its origin in the plan itself, before anything is
generated — `"operator_footage"` for a segment claimed from the pool, `"ai_generated"`
for a shortfall cutaway. There is no third value
(`schemas/artifacts/edit_decisions.schema.json:65-69` closes the enum), and the label
travels from here into each cut.

It is load-bearing downstream: `look_filters` resolves `look["grade"]` against
`FACE_PRESETS` **first**, so a face preset in that slot is fine on a locked cut — what it
refuses on an `operator_footage` cut is a `color_grade` **profile** or any grain, and it
raises `PolishError` rather than dropping either silently (`lib/polish_filters.py:149-181`).
That is what lets the one project-level `batch_look` apply to every cut, locked ones
included. A cut mislabelled here does not fail at gate 2 — it fails at edit, or worse,
grades the operator's face. Write the label as you write the slot, from the source you
claimed; a later pass is inference by another name.

### 6. Itemise Any Shortfall With Its Prompt — Text Only

A shortfall is a slot no unclaimed segment could fill. It is itemised **per cut**, not per
reel: one `metadata.shortfall[]` entry carrying the `reel_id`, the `cut_id` it fills, the
exact `prompt` `assets` will send, `why` nothing covered it, and the slot's own
`length_seconds` (the same `length` step 4 sized the claim to). That entry is the only
place the gate-2-approved prompt exists — `assets` reads the prompt from there and sends it
verbatim — so a shortfall itemised without one leaves the next stage nothing to generate
from. There is no per-reel prompt key: the entry is per cut, because the cut is what gets
filled. **`length_seconds` never sizes the flash** — R8 is explicit that a cutaway is a
sub-second flash accent, not B-roll, so `assets` books a fixed sub-second `flash_seconds`
regardless of the slot. What `length_seconds` sizes is the *shrink*: this stage does not
let a shortfall keep its own full beat-grid interval — back in step 4, the same `else`
branch that itemises the shortfall cuts it down to the flash length, and the seconds it
gives up go to the neighbouring operator clip. On a middle slot, or a last slot whose
neighbour still has source footage past its current out-point, that neighbour's source AND
timeline both extend to cover the remainder, so the reel's `total_seconds` and its beat
grid hold exactly as planned. On a last slot whose neighbour has no footage left, step 4
falls back instead: the neighbour is not touched, and the reel's own `total_seconds` is
shortened by the remainder and written as the true, honest length — see step 4's fallback
for when each applies.

The dry run in step 4 is what keeps gate 2 from approving a prompt the tool will refuse.
The guard walks keys **and** values recursively and raises `MediaReferenceRefusedError`
on raw bytes, a `data:` URI, or any string ending in a media suffix (`:100-124`,
`:136-149`) — renaming the key does not help. A prompt may describe a texture, a light,
an object; it may **never** cite a file, a frame, a still from the pool, or "like the
clip in reel 2". Prompt rules follow from what the tool does with the clip:

- One cutaway per reel at most, trimmed to a sub-second flash
  (`DEFAULT_FLASH_SECONDS = 0.6`, max 2.0 — `:66-68`): **one texture on one beat hit**,
  not a scene.
- No people: the operator must not appear in a generated frame, and a generated stranger
  in a personal-brand reel reads worse than a repeated angle.
- 9:16 and silent — the pin is `kling_video`, 5s (`:59-64`); audio is stripped with `-an`
  at trim and the trimmed clip is re-probed and rejected if it still carries a track
  (`:456-464`, `:405-409`).

**The armed/not-armed check is binding**, and it is arithmetic on the two brief keys read
in step 1: escalate when `shortfall and not armed`, or when
`len(shortfall) > armed_cutaways`. A shortfall the cost gate in `idea-director.md` did not
arm is not something to quietly plan a cutaway for — `assets` cannot book spend that was
never armed. Escalate as a structured blocker (AGENT_GUIDE.md → "Escalate Blockers
Explicitly") with the three real options (drop a reel; cut one reel to four slots with
longer holds; return to the idea gate to arm the valve) and a recommendation.

Log the operator's ruling as a `decision_log` entry. Entries are
`additionalProperties: false` and require all seven fields, so a two-key object fails
validation: `decision_id` (`d-001`, `d-002`, … within this artifact), `stage:
"scene_plan"`, `category` — `"downgrade_approval"` for a shorter reel,
`"fallback_decision"` for a cutaway — `subject: "shortfall fill for <reel_id>"`,
`options_considered` as the three options above (each an object with `option_id`, `label`,
`score` in `[0, 1]` and `reason`), `selected` as **one of those `option_id`s** and not free
text, and `reason` for the ruling.

### 7. Place The Hook

The hook line comes from the script; you place it, at the top of the reel. The bound is
numeric — `hook["end_seconds"] <= snap_grid[2]` — and it is the whole bound: the hook may
run past the first snap boundary, it may not reach the second. Do not tighten it to "inside
the opening beat" or "before the first cut's edge"; a slot can span more than one boundary,
and a hook that clears the real rule would be sent back for nothing. Record it as the
reel's `hook`, the same three-key object the script uses:
`{"text", "start_seconds", "end_seconds"}`, reel-local.
It renders in the text plane as a `hero_title` overlay
(`tools/video/remotion_caption_burn.py:162-166`), so keep the copy to one line inside the
9:16 safe zone the `reel_pop` preset applies (`:115-133`). A hook that needs three lines is
a caption — send it back to the script.

### 8. Record The Scene Plan

`scenes[]` items are `additionalProperties: false`; `metadata` is open. There is **one
`scenes[]` entry per cut**: `scenes[].id` is identical to the cut id,
`scenes[].script_section_id` is the reel id (`script.sections[].id` *is* the reel id), and
`scenes[].description` is the one-line reason for the cut — `edit` copies it verbatim into
`edit_decisions.cuts[].reason`, so write a reason, not a filename. Everything else
reel-shaped lives in `metadata.reels[]`. Build the whole thing as `scene_plan`:

```json
{
  "version": "1.0",
  "scenes": [
    { "id": "reel_02-01", "type": "broll", "narrative_role": "introduce_subject",
      "script_section_id": "reel_02",
      "description": "rack pull lockout, low angle, side light",
      "start_seconds": 0.0, "end_seconds": 1.94,
      "required_assets": [ { "type": "video", "source": "provided",
                             "description": "push_day pool segment [4.20, 6.14)" } ] },
    { "id": "reel_02-03", "type": "generated", "narrative_role": "emotional_beat",
      "script_section_id": "reel_02",
      "description": "chalk dust in hard side light, macro",
      "start_seconds": 3.88, "end_seconds": 4.48,
      "required_assets": [ { "type": "video", "source": "generate",
                             "description": "sub-second AI flash accent, text-prompt only" } ] },
    { "id": "reel_02-04", "type": "broll", "narrative_role": "build",
      "script_section_id": "reel_02",
      "description": "rack pull lockout, low angle, side light — extended to absorb cut 3's shortfall",
      "start_seconds": 4.48, "end_seconds": 7.72,
      "required_assets": [ { "type": "video", "source": "provided",
                             "description": "push_day pool segment [17.26, 20.50)" } ] }
  ],
  "metadata": {
    "pipeline": "reel-batch",
    "renderer_family": "documentary-montage",
    "render_runtime": "ffmpeg",
    "reels": [
      { "reel_id": "reel_02", "track_id": "track_01", "total_seconds": 9.62,
        "grid_source": "snap_grid", "cut_policy": "bar",
        "hook": { "text": "you don't need motivation",
                  "start_seconds": 0.0, "end_seconds": 1.94 },
        "cuts": [
          { "id": "reel_02-01", "provenance": "operator_footage", "beat_seconds": 12.41,
            "source_path": "/pool/rack_pulls_A.mp4",
            "clip_id": "footage_rack_pulls_a_mp4_7c1e9a04_00004200_00006140",
            "in_seconds": 4.20, "out_seconds": 6.14, "claim_id": "3f9c..." },
          { "id": "reel_02-03", "provenance": "ai_generated", "beat_seconds": 16.29 },
          { "id": "reel_02-04", "provenance": "operator_footage", "beat_seconds": 18.23,
            "source_path": "/pool/rack_pulls_A.mp4",
            "clip_id": "footage_rack_pulls_a_mp4_7c1e9a04_00017260_00020500",
            "in_seconds": 17.26, "out_seconds": 20.50, "claim_id": "7b2e..." } ] }
    ],
    "shortfall": [
      { "reel_id": "reel_02", "cut_id": "reel_02-03",
        "prompt": "chalk dust drifting through a hard side light, black background, macro",
        "why": "no unclaimed segment >= 1.94s remained for slot 3", "length_seconds": 1.94 }
    ],
    "pool": { "usable_segments": 24, "claimed": 24, "spare": 0 }
  }
}
```

`renderer_family` and `render_runtime` are copied forward from `brief["metadata"]`, and each
reel entry carries its own `track_id` and `cut_policy`, so `edit` reads them off
`scene_plan.metadata` without reaching back for the brief — edit-director blocks the render
on an empty `scene_meta["renderer_family"]`. `clip_id` is whatever `record.clip_id` holds;
never hand-write one, its shape is `footage_<slug>_<digest>_<in_ms>_<out_ms>`
(`tools/video/footage_library.py:878-890`) and an invented id matches no corpus row.
`reel_02-04`'s `beat_seconds` above is still `18.23` — the grid line step 2 built it
around — even though step 6's shrink pulled its `start_seconds` to `4.48` to absorb cut
3's shortfall: `beat_seconds` records which beat a cut is *for*, not where it now starts,
and only the shrunk cut's own beat has to survive untouched.

This worked example puts the shortfall on a MIDDLE slot (`reel_02-03`, index 2 of 5) —
step 4's `if` branch, where the neighbour it grows into (`reel_02-04`) is not yet claimed,
so its `3.24`s span above already includes the `1.34`s it absorbed. Had the shortfall
instead landed on the reel's LAST slot (`reel_02-05`, originally `7.72`-`9.62`, length
`1.90`) with `reel_02-04` unextended and claimed at its own original `[17.26, 19.16)`,
step 4's `else` branch runs: `flash_length` is still `0.60`, but `remainder` is
`1.90 - 0.60 = 1.30`. If `rack_pulls_A.mp4` has footage past `19.16` out to at least
`20.46`, the headroom check claims `[19.16, 20.46)` as a *second* claim on that same file,
`reel_02-04`'s `out_seconds` becomes `20.46`, the flash sits at `9.02`-`9.62`, and
`total_seconds` stays `9.62` — the approved length and grid survive a last-slot shortfall
exactly as they do a middle-slot one. If the source ends at `19.16` with nothing past it,
`reel_02-04` is left exactly as claimed, the flash moves to `7.72`-`8.32` instead (flush
against `reel_02-04`'s unmoved end — no gap), and `total_seconds` is written as `8.32` —
`1.30`s short of the reel this gate approved, reported honestly rather than silently
overrun.

The cut's `in_seconds` / `out_seconds` are in/out points **inside `source_path`**, the pool
file; the `start_seconds` / `end_seconds` on the matching `scenes[]` entry are reel-local
timeline positions. The key is `source_path` and not `source` on purpose: in
`edit_decisions` `source` means an **asset id** — that schema requires `id`, `source`,
`in_seconds` and `out_seconds` on every cut
(`schemas/artifacts/edit_decisions.schema.json:14`) — and the asset id is minted at `assets`
and read from `asset_manifest.metadata.cut_index[cut_id]["asset_id"]`, never from here. The
`<reel_id>-` id prefix lets the edit stage keep one flat `cuts[]` and still filter it per
reel. A shortfall cut carries **only** `id`, `provenance` and `beat_seconds`: its `scenes[]`
entry sets `"source": "generate"` in `required_assets`, and `assets` fills the file and
reports the resolved geometry in `cut_index`. `why` is free text — the slot's own
description at minimum, the measurement when you have it, as above.

`scene_plan` is one of two artifacts this stage `produces`. When step 6 forced a ruling, the
`decision_log` built there rides in the **same** checkpoint `artifacts` dict —
`{"scene_plan": ..., "decision_log": ...}` — so both are validated on the one write. A
sitting the pool covered end to end has no ruling to log and writes `scene_plan` alone.

### 9. Quality Gate

```python
from collections import Counter

reels = scene_plan["metadata"]["reels"]        # the artifact assembled in step 8
batch_reel_ids = set(reel_ids)

ledger.assert_no_reuse()                       # lib/clip_ledger.py:216-228
claimed = [c for c in ledger.live_claims()     # _HOLDING_STATUSES = {claimed, reconciled}
           if c["status"] == "claimed"         # (:63-65, :197-202), and the ledger is
           and c["reel_id"] in batch_reel_ids] # project-scoped — so scope it both ways
assert len(claimed) == sum(1 for r in reels for c in r["cuts"]
                           if c["provenance"] == "operator_footage")
assert len(shortfall) == sum(1 for r in reels for c in r["cuts"]
                             if c["provenance"] == "ai_generated")
assert len(shortfall) <= armed_cutaways        # brief.metadata.cutaway_count, step 1
# Decision log #6: at most ONE AI flash a reel. The gate-1 ceiling caps the reel COUNT,
# and the line above caps the batch TOTAL — neither stops three armed cutaways stacking
# into one reel, which is the outcome that makes a reel mostly generated footage.
assert max(Counter(sf["reel_id"] for sf in shortfall).values() or [0]) <= 1
scene_by_id = {s["id"]: s for s in scene_plan["scenes"]}
for r in reels:
    assert r["total_seconds"] <= 9.8       # the authoring budget, not compose's 10.0 probe —
                                            # refuse an over-length reel here, before assets spends
    assert all(c.get("beat_seconds") is not None and
               c["provenance"] in ("operator_footage", "ai_generated") for c in r["cuts"])
    for c in r["cuts"]:
        if c["provenance"] != "operator_footage":
            continue
        # The invariant nothing checked before: a cut's TIMELINE span (how long it
        # sits in the reel) must equal its SOURCE span (how much footage backs it),
        # speed-adjusted. A shrink that moves a timeline boundary without moving the
        # matching source in/out — the defect the last-slot fallback in step 4 exists
        # to stop — fails here, at gate 2, instead of shipping ~1.3s short with every
        # cut past it off the beat grid.
        sc = scene_by_id[c["id"]]
        span = round(sc["end_seconds"] - sc["start_seconds"], 3)
        source_span = round((c["out_seconds"] - c["in_seconds"]) / c.get("speed", 1.0), 3)
        assert span == source_span, (
            f"{c['id']}: timeline span {span}s != source span {source_span}s"
        )
```

By eye: one reel group per planned reel; one `scenes[]` entry per cut, ids matching; every
hook ending at or before its reel's `snap_grid[2]`; and every shortfall carrying a `cut_id`
and a prompt that passed `refuse_media_references`.

## Present For Approval — Gate 2

Follow `skills/meta/checkpoint-protocol.md` Step 5 for the checkpoint mechanics. The
artifact summary is **per reel**, and must be enough to approve without opening the
JSON: the ordered cut list with its source segments, the beat each cut snaps to, the
hook, and the running length.

```
### Reel 2 of 5 — "you don't need motivation" — 9.62s — push_day.mp3

| # | reel time | beat (track) | source segment | provenance | run |
|---|-----------|--------------|----------------|------------|-----|
| 1 | 0.00-1.94 | 12.41 | rack_pulls_A.mp4 [4.20, 6.14) | operator_footage | 1.94 |
| 2 | 1.94-3.88 | 14.35 | db_press_B.mp4 [11.00, 12.94) | operator_footage | 3.88 |
| 3 | 3.88-4.48 | 16.29 | (shortfall, sub-second flash) chalk dust in hard side light, macro | ai_generated | 4.48 |
| 4 | 4.48-7.72 | 18.23 | rack_pulls_A.mp4 [17.26, 20.50) | operator_footage | 7.72 |
| 5 | 7.72-9.62 | 20.13 | walkout_C.mp4 [2.10, 4.00) | operator_footage | 9.62 |

Hook: "you don't need motivation" - 0.00-1.94, over cut 1.
Slot 3: no unclaimed segment >= 1.94s remained (R8: sub-second flash, not a full beat
interval) — cut 3 shrinks to 0.60s and cut 4 extends to absorb the other 1.34s (cut 4's
own source grows with it, so 9.62s and the beat grid both hold); one cutaway on the
pinned kling_video route via video_selector, $0.10 for this cut.
```

The shortfall above lands on a middle slot, so the neighbour it grows into (cut 4) is
still unclaimed and simply sizes larger. Had it instead landed on slot 5 — the reel's
last — the summary reads the same way when the source claimed for slot 4 has footage
past its out-point to extend into (its `run` column changes, `9.62s` does not). When it
does not, say so plainly instead: "Slot 5: no unclaimed segment remained and slot 4's
source has no footage past its out-point — reel ends 1.30s early at 8.32s rather than
overrunning the source" is the honest fallback line, and the reel's `total_seconds` in
the header changes to match.

Close with the batch line: reels planned, segments claimed against spare pool, how many
reels carry a cutaway, and the figure the operator is approving — **$0.00 when the pool
covers the batch**, otherwise `len(shortfall)` x $0.10, which is the number of clips
`assets` fires. Price the **cuts**, not the reels: `assets` bills per shortfall cut, and the
two counts coincide on this sitting only because of the one-cutaway-per-reel cap. When a
reel came up short, say *why the pool was thin* from `source_media_review`'s exclusion
reasons: "eleven segments
excluded as too soft" is actionable, "no match found" is not. No money moves here:
pricing happened at the cost gate in `idea-director.md`, spending happens at `assets`.
Then **END YOUR TURN**.

## What A Send-Back Changes

A send-back is per reel, and releasing is the only correct way to give segments back:

```python
released = ledger.release_reel(reel_id)   # lib/clip_ledger.py:204-210
```

`release_reel` settles exactly that reel's live claims and returns them to the pool,
leaving other reels untouched. Then re-plan from step 2, carrying these consequences:

1. **Freed segments can cancel a cutaway.** A released reel returns ~5 segments, so
   re-run the shortfall check for every *later* reel first: a slot that was a shortfall
   may now be fillable for free.
2. **Never clear claims to start clean.** The batch's uniqueness guarantee is the union
   of live claims; a hand-cleared ledger silently permits reuse.
3. **A changed hook is a script change.** Append the new line to the script artifact and
   re-place it — never leave plan and script disagreeing about the copy.
4. **Re-log, do not edit.** If a send-back reverses a decision you logged (a cutaway he
   refuses, a fifth reel he drops), append a **new** `decision_log` entry reusing the
   same `category` **and** `subject` (AGENT_GUIDE.md → "Re-log Changed Decisions").

Approval is per gate: approving reels 1-4 and sending back reel 5 does not advance the
stage. Re-present the whole batch after the re-plan.

## Common Pitfalls

- **Arithmetic slot edges.** `10 / 5 = 2.0s` cuts feel right in a spreadsheet and drift
  audibly against the track. Every edge comes from the reel's `snap_grid`, or nothing.
- **Sizing every reel against the full pool.** Reels claim as they go; planning each
  against `usable_segments` overcommits and turns reel 5 into a pile of shortfalls.
- **A cutaway prompt that cites the footage.** `refuse_media_references` will **not** catch
  a prose citation of the pool: it tests for `data:` URIs, strings ending in a media suffix,
  and media-named dict keys (`tools/video/cutaway_gen.py:107-124`). "Same rack as the second
  cut" passes the guard cleanly, reaches the generator, and generates against the operator's
  own footage — the exact R5 leak. Catching it is your job, here at gate 2.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
