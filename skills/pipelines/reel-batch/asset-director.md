# Asset Director - Reel Batch Pipeline

## When To Use

Gate 2 (`scene_plan`) is approved. Every reel has a beat-snapped cut list, every cut slot
names the pool segment that fills it, and any slot the pool could not cover has its own
entry in `scene_plan.metadata.shortfall` — reel id, cut id, and the cutaway prompt that
fills it. This stage turns that plan into files on disk and writes the `asset_manifest`
that `edit` and `compose` read.

It is also **the only stage in this pipeline that can spend money**, and on a typical
sitting it spends **$0.00**. Cutaways are free-first: sub-second flash accents come out of
the operator's own indexed pool, and the paid valve opens only against the shortfall the
`idea` gate measured and gate 2 approved — one clip per shortfall cut at $0.10 on the pinned
`kling_video` route, so a five-cut shortfall is $0.50. This pipeline has three human gates —
`idea`, `scene_plan`, `publish` — and gate 2 is the last of them **before any paid call**, which
is exactly what lets `assets` run unattended (`human_approval_default: false`). Nothing here
re-opens a creative decision; it executes the one that was approved.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/asset_manifest.schema.json` | Artifact validation. Every asset object is `additionalProperties: false` — see Step 7 |
| Prior artifacts | `state.artifacts[...]` — `["scene_plan"]["scene_plan"]`, `["script"]["script"]`, `["idea"]["brief"]` | Reel groups, cut slots and the per-cut `metadata.shortfall` entries; per-reel `window`, `caption`, `track_id`; reel count, usable-segment count, whether a paid cutaway is armed |
| Corpus | `lib/corpus.py` — `Corpus(corpus_dir)` | The indexed pool. Rows are **segments**, not files (`lib/corpus.py:52-57`) |
| Clip ledger | `lib/clip_ledger.py` — `ClipLedger.for_project(project_id)` | No clip reused within a batch |
| Look guard | `lib/polish_filters.py` — `look_filters`, `PolishError` | Refuses an unsafe look on identity-locked footage rather than dropping it |
| Tools | `cutaway_gen` (the paid valve), `subtitle_gen`, `audio_mixer`, `face_enhance` | Everything but `cutaway_gen` is local ffmpeg/pure-python and prices $0.00 — none of the three overrides `BaseTool.estimate_cost` (`tools/base_tool.py:376-378`) |
| Cost tracker | `tools/cost_tracker.py` — `CostTracker.for_project(project_id)` | Reopens the same `projects/<project_id>/artifacts/cost_log.json` the cost gate in `idea-director.md` seeded |

## Ledger Discipline For Every Paid Call

Open the project's tracker once — `tracker = CostTracker.for_project(project_id)` reopens
the same ledger every other stage shares. The one paid line in this pipeline is a cutaway,
and it books under **`video_selector`**, not under `cutaway_gen`: both
`CutawayGen.estimate_cost` (`tools/video/cutaway_gen.py:333-343`) and `CutawayGen.execute`
(`:383-384`) hand the same pinned payload to `VideoSelector`, so the selector is what
prices and bills. The routed concrete provider goes in the **operation string** — the house
rule for a selector-fronted line (`skills/meta/checkpoint-protocol.md` → Cost Ledger
Governance, "One name per line of spend").

Book **one entry per cutaway** — one shortfall cut, one prompt, one clip, one entry. That is
the grain the operator approved at gate 2, where the shortfall was itemised per cut. A single
batch entry has no honest terminal state after a mid-batch abort: `reconcile` is one-shot and
terminal-guarded (`tools/cost_tracker.py:314`), `budget_spent_usd` counts failed entries as
spend (`:186-192`), and `refund` on a partly-executed entry erases real billing (`:323-337`).

```python
# One iteration of step 3's loop: `sf` is that entry of scene_plan["metadata"]["shortfall"].
sf = {"reel_id": "reel_02", "cut_id": "reel_02-03",
      "prompt": "chalk dust drifting through a hard side light, black background, macro"}
inputs = {
    "prompts": [sf["prompt"]],                  # ONE prompt = ONE clip = ONE shortfall cut
    "flash_seconds": 0.6,
    "cache_dir": f"projects/{project_id}/assets/cutaway_cache",
    "output_dir": f"projects/{project_id}/assets/cutaway",
}
estimated_usd = cutaway_gen.estimate_cost(inputs)      # $0.10 on the pin; $0.00 if cached
entry_id = tracker.estimate("video_selector", f"cutaway_{sf['cut_id']}_kling_video", estimated_usd)
tracker.reserve(entry_id, user_approved=True)  # this cut's fill was approved at gate 2

result = cutaway_gen.execute(inputs)

# Book what actually happened, never what was hoped.
reported = result.cost_usd or 0.0   # ToolResult defaults cost_usd to 0.0
if result.success:
    # A positive report is authoritative. 0.0 on success is ambiguous
    # (unreported vs genuinely free), so for an entry ESTIMATED as paid,
    # book the estimate as the best available record — and say so when you
    # present the stage's cost snapshot.
    actual_usd = reported if reported > 0 else estimated_usd
else:
    # A failed call books only what the tool says was charged — almost
    # always $0.00. NEVER substitute the estimate on failure:
    # budget_spent_usd counts FAILED entries as well as completed ones
    # (CostTracker.budget_spent_usd), so a substituted estimate is phantom
    # spend that shrinks usable budget and can block the real retry in cap
    # mode.
    actual_usd = reported
tracker.reconcile(entry_id, actual_usd, success=result.success)
```

**Known-free routes book $0.00.** A prompt already generated into `cache_dir` is a cache hit:
`estimate_cost` skips it (`tools/video/cutaway_gen.py:340-341`) and `execute` stamps
`cached: true` with `cost_usd: 0.0` on that cutaway (`:416-417`). Estimate and actual
therefore agree at `0.00` with no special case — a re-run of an interrupted sitting is free,
not double-billed. See `skills/meta/checkpoint-protocol.md` → Cost Ledger Governance for the
shared rules, including stranded entries and a corrupt ledger; do not re-derive them here.

`user_approved=True` rides on every reservation in this stage because gate 2 approved each
reel's cut list, cutaway included. It is not a threshold dodge: at $0.10 a per-cutaway entry
sits well under `single_action_approval_usd: 0.50`, so that guard would not have fired
anyway (`tools/cost_tracker.py:256-262`). It does **not** waive the first-paid-use guard —
`video_selector` must already be armed via `approve_tool` (`:264-270`, `:291-295`). If that
trips, surface it as a structured blocker per AGENT_GUIDE.md → "Escalate Blockers
Explicitly"; never self-`approve_tool` around it, and never rename the line to a tool that
happens to be armed. If a reservation is made and the call never runs (reel dropped, budget
stopped the batch), call `tracker.refund(entry_id)`.

## Mental Model

The pool is the b-roll library; AI is a relief valve on it. Three rules follow.
**Free first** — resolve every slot against the corpus before considering a generator;
`cutaway_gen` with no prompts costs $0.00 and makes no provider call. **Spend only what was
measured** — the shortfall was measured at gate 1 as
`cutaway_count = max(0, reels * cuts_per_reel - usable_segments)` and itemised per **cut** at
gate 2 as `scene_plan.metadata.shortfall`. The number you fire is
`len(scene_plan["metadata"]["shortfall"])` — never a number you derive here.
`usable_segments // cuts_per_reel` is a different quantity: it is the pool's *capacity*,
which `footage_library` computes as `max_reels` (`tools/video/footage_library.py:382-383`,
surfaced at `:410`). Reading capacity as shortfall fires a cutaway for every reel the pool
could have carried — unapproved spend, and it fails this file's own quality gate.
**Provenance is declared, never inferred** — a row is identity-locked because
`footage_library` wrote it that way at ingest (`:371`, `:412`), and nothing downstream
re-decides it from pixels. **`faceswap`, avatars and video-restyle of
operator footage are out of scope** — the face is never regenerated, and no shortfall is
a reason to reach for a tool that would. The compose gate cross-checks what you write
here: a cut whose `provenance` disagrees with its asset's `source_tool`
(`footage_library` ⇒ `operator_footage`, `cutaway_gen` ⇒ `ai_generated`) blocks the whole
render on every runtime. Write the truth per cut; a plausible-looking guess fails at
compose, after the money is spent.

## Process

### 1. Reopen Both Ledgers Before Touching Anything

```python
corpus = Corpus(Path(f"projects/{project_id}/corpus")); corpus.load()
clips = ClipLedger.for_project(project_id)      # lib/clip_ledger.py:115-134
tracker = CostTracker.for_project(project_id)   # the ledger the idea stage seeded
```

Two ledgers, two jobs: `clips` guarantees no segment ships in two reels, `tracker` that no
dollar is unaccounted for. Neither is rebuilt here — both are reopened.

**Resume is idempotence, not a checkpoint.** This stage writes no `in_progress` checkpoint and
no `metadata.partial_progress` — compose owns that mechanism, and nothing here may claim a
`completed_reel_ids` list of its own. On resume, re-run steps 2-3 unchanged: the cutaway
`cache_dir` turns an already-generated prompt into a $0.00 cache hit, the clip ledger's claims
survived the crash, and every ledger entry this stage opened was driven to a terminal state
before the stage ended. If an abort left one non-terminal anyway, sweep it per
`skills/meta/checkpoint-protocol.md` → Cost Ledger Governance rather than inventing a recovery
rule here.

### 2. Resolve Every Cut Slot From The Pool

Every slot gate 2 filled names a corpus `clip_id`, and a corpus row is a segment carrying
its own in/out points inside the source file:

```python
resolved, unfilled = [], []
for reel in scene_plan["metadata"]["reels"]:
    for slot in reel["cuts"]:
        rec = corpus.get(slot["clip_id"]) if slot.get("clip_id") else None
        if rec is None:
            # Inside a cut object the id field is `id`; `cut_id` is how a cut is
            # named from outside one. `slot["cut_id"]` is a KeyError.
            unfilled.append((reel["reel_id"], slot["id"]))
            continue
        # Gate 2 beat-snapped this cut and the clip ledger claimed exactly these
        # seconds, so the SLOT is the geometry. `rec.interval` is the whole indexed
        # segment (1.5-6.0s, tools/video/footage_library.py), which is longer than the
        # ~2.0s hold the beat grid planned — writing it here renders a reel that
        # overruns its own budget and drifts off every beat after the first cut.
        start, end = slot["in_seconds"], slot["out_seconds"]
        # local_path is ABSOLUTE for operator rows — the pool lives outside the corpus
        # and is never copied (tools/video/footage_library.py:349-352); the join still
        # resolves, because an absolute right-hand side wins.
        path = (corpus.corpus_dir / rec.local_path).as_posix()
        resolved.append({
            "reel_id": reel["reel_id"],
            "cut_id": slot["id"],                        # "<reel_id>-<nn>"
            "path": path,
            "in_seconds": start,
            "out_seconds": end,
            # The enum is closed to two values (edit_decisions.schema.json:65-68), and a
            # pool row that is not identity-locked has no business in a reel: stop rather
            # than stamping a third value edit-director would escalate on.
            "provenance": _locked_or_stop(rec, slot["id"]),
            "identity_locked": rec.identity_locked,
            "license": rec.license,                      # "operator_owned" for the pool
        })
```

`_locked_or_stop` is two lines and exists so the failure is loud:

```python
def _locked_or_stop(rec, cut_id):
    if not rec.identity_locked:
        raise SystemExit(
            f"{cut_id}: corpus row {rec.clip_id} is not identity-locked. The pool is "
            f"indexed by footage_library with identity_locked=True; an unlocked row here "
            f"means the scene plan ranked a stock clip into the operator's batch."
        )
    return "operator_footage"
```

**Reconcile `unfilled` against the approved shortfall before going further.** An
`ai_generated` slot carries only `id`, `provenance` and `beat_seconds` — no `clip_id` — so it
lands in `unfilled` by construction, and gate 2 must already have itemised it:

```python
approved = {(sf["reel_id"], sf["cut_id"]) for sf in scene_plan["metadata"]["shortfall"]}
unapproved = [pair for pair in unfilled if pair not in approved]
```

`unapproved` non-empty is a blocker, never a licence to generate: a slot with no `clip_id` and
no matching `metadata.shortfall` entry means the plan and the pool disagree. Escalate it per
AGENT_GUIDE.md → "Escalate Blockers Explicitly", naming the cut ids. The reverse mismatch — a
`shortfall` entry whose cut resolved from the pool after all — is also a blocker, because
firing its prompt would be spend nobody approved for a slot that is already full.

**Do not re-claim what gate 2 already claimed.** `ClipLedger.claim` raises
`SegmentAlreadyClaimedError` on any overlap with a live claim — including the reel's own,
because `_holder_of` does not exempt the claiming reel (`lib/clip_ledger.py:261-266`).
Claim only a **substitute** pick, and check first:

```python
# Same loop body, and only when `rec` is a substitute for the row gate 2 named.
# `path`, `start`, `end` are the ones just bound above.
if clips.is_available(source=path, in_seconds=start, out_seconds=end):
    clips.claim(reel_id=reel["reel_id"], source=path, in_seconds=start,
                out_seconds=end, clip_id=rec.clip_id)
```

Close the step with `clips.assert_no_reuse()` (`:216-228`). It raises `ClipReuseError`
naming both reels — a batch-integrity failure, not a warning to note and pass. If a slot's
file has vanished off disk since indexing, that is a blocker too, not a reason to reach for
a generator: substituting AI for missing operator footage is a provenance change and needs
approval (AGENT_GUIDE.md → "No Unilateral Substitutions").

### 3. Fire Cutaways Only Against The Measured Shortfall

One prompt, one clip, one cut, one ledger entry. The list to iterate is
`scene_plan["metadata"]["shortfall"]` — one entry per cutaway, each carrying `reel_id`,
`cut_id` and the `prompt` that passed `refuse_media_references` at gate 2:

```python
generated, dropped = {}, []
for sf in scene_plan["metadata"]["shortfall"]:
    # sf = {"reel_id": "reel_02", "cut_id": "reel_02-03", "prompt": "...", "why": "..."}
    # Run the paid booking block above verbatim, with sf["prompt"] as the single
    # element of inputs["prompts"] and f"cutaway_{sf['cut_id']}_kling_video" as the
    # ledger operation. It leaves `result` bound to the ToolResult:
    if not result.success:
        # cutaway_gen returns success=False with a partial `data` payload rather than
        # raising (tools/video/cutaway_gen.py). Binding [0] blind turns a recoverable
        # failure into an IndexError and takes the whole sitting down with one clip.
        dropped.append((sf["reel_id"], sf["cut_id"], result.error))
        continue
    generated[sf["cut_id"]] = result.data["cutaways"][0]   # one prompt in, one row out
```

A `dropped` entry is not a stage failure. Reconcile its ledger entry `success=False`,
then either retry it once or drop that reel — `ClipLedger.for_project(project_id)
.release_reel(reel_id)` returns its segments to the pool so the remaining reels can use
them — and say which you did. A four-reel sitting delivered is worth more than a
five-reel sitting that died on one clip.

Each row carries `output_path`, `flash_seconds`, `cost_usd`, `cached` and
`provenance: "ai_generated"` (`tools/video/cutaway_gen.py:413-427`). `sf["cut_id"]` is what
the generated asset's `scene_id` and its `cut_index` key must both carry — that is the only
join edit has back to the slot this clip fills. Cuts with no `shortfall` entry are not in
the loop at all, and there is no other list to loop over: a per-reel `shortfall_prompt`
exists in no artifact this pipeline writes.

**The prompt is text and only text.** `cutaway_gen` refuses any input carrying a media
reference — a path, URL, data-URI or raw bytes, at any depth, under any key name — with
`MediaReferenceRefusedError` (`tools/video/cutaway_gen.py:74-79`), raised by the recursive
walker `refuse_media_references` (`:127-178`) from both `estimate_cost` (`:334`) and
`execute` (`:356`), so the refusal lands before pricing as well as before sending. That
refusal is the structural half of the identity guarantee. Never hand it a pool path "for
style reference".

**Why the pin is load-bearing.** `_provider_inputs` builds one dict per prompt with
`allowed_providers=["kling"]` and `preferred_provider="kling"`
(`tools/video/cutaway_gen.py:296-302`), and the *identical* dict is priced and executed
(`:383-384`), so `VideoSelector` cannot stamp an estimate divergence. Unpinned, the same
shortfall routes to whatever the scorer ranks top — currently seedance at **$1.52/clip,
$7.60 a sitting**, 15x, for footage trimmed to six-tenths of a second. And a pin that
resolves to nothing **raises** `ProviderPinUnresolvedError` rather than returning an
unguardable $0.00 (`tools/video/video_selector.py:336-343`) — a $0.00 estimate is exempt
from both approval guards, so the raise is what stops a typo seeding an unguarded paid
line. `python scripts/reel_batch_route_cost.py` prints all three numbers and the bad-pin
behaviour; run it before asserting any of them to the operator.

Announce the first call per AGENT_GUIDE.md → "Announce Before Execution": tool `cutaway_gen`,
provider `kling`, variant `v3/standard`, reason "pool shortfall of N cuts measured at
`idea`", batch run of N clips at $0.10 each, where N is `len(scene_plan["metadata"]["shortfall"])`.
If a cutaway fails, reconcile it `success=False` (the block does this), then retry once or
drop that reel and `clips.release_reel(sf["reel_id"])` to return its segments to the pool
(`lib/clip_ledger.py:204-210`). A four-reel sitting that ships beats a five-reel one that
stalls — say which you did.

### 4. The Proven-$0 Sitting Runs The Same Ceremony

When the pool covers the whole batch, `scene_plan.metadata.shortfall` is empty, no provider
call is made, and no `video_selector` entry exists. The free tools still get the full
estimate → reserve → reconcile round trip — batched, **one entry per tool across the whole
sitting**, never one per reel. The lightening lever is the data, not a shorter protocol.

One entry wraps the whole per-reel loop, and the loop calls `subtitle_gen.execute` **twice
per reel** — `json` first, then `srt` — because one `subtitle_gen` inputs dict names one
`format` and one `output_path` (`tools/subtitle/subtitle_gen.py:42-73`):

```python
reels = script["metadata"]["reels"]
entry_id = tracker.estimate("subtitle_gen", f"captions x {len(reels)} reels", 0.0)
tracker.reserve(entry_id, user_approved=True)  # the caption plan approved at gate 2

caption_paths, spent, ok = {}, 0.0, True
for reel in reels:
    reel_id = reel["reel_id"]
    off = reel["window"]["offset_seconds"]
    segs = reel["caption"]["segments"]
    shift = off if segs[0]["start"] >= off else 0.0   # already reel-local? shift nothing
    rebased = [                                       # step 6 explains the rule
        {**s, "start": s["start"] - shift, "end": s["end"] - shift,
         "words": [{**w, "start": w["start"] - shift, "end": w["end"] - shift}
                   for w in s.get("words", []) if w["end"] > shift]}
        for s in segs if s["end"] > shift
    ]
    for fmt in ("json", "srt"):
        inputs = {
            "segments": rebased,
            "format": fmt,
            "output_path": f"projects/{project_id}/assets/subtitles/{reel_id}.{fmt}",
            "max_words_per_cue": 3,
            "corrections": reel.get("corrections") or {},
        }
        if subtitle_gen.estimate_cost(inputs):
            raise RuntimeError(f"subtitle_gen priced {reel_id}/{fmt} above $0.00")
        result = subtitle_gen.execute(inputs)
        ok = ok and result.success
        spent += result.cost_usd or 0.0
        caption_paths[(reel_id, fmt)] = inputs["output_path"]

tracker.reconcile(entry_id, spent, success=ok)   # one reconcile, after the loop
```

A local tool that starts pricing is a **route change**, not a cost to absorb: `subtitle_gen`
inherits `BaseTool.estimate_cost` and returns `0.0` (`tools/base_tool.py:376-378`), so a
non-zero here means the tool was re-tiered under you. Stop and escalate it as a structured
blocker per AGENT_GUIDE.md → "Escalate Blockers Explicitly"; do not book it silently under a
$0.00 entry.

Same shape for `audio_mixer` (`"beds x N tracks"`) and, if you run it, `face_enhance`. Every
entry reaches a terminal state here, so compose's ledger criterion finds nothing to clean up.

### 5. Identity Discipline — Default Deny

The pool is identity-locked at ingest and nothing in this stage may loosen that.

- **Never send operator footage to a generator.** Not as a reference, not as a first frame,
  not as a style hint. Step 3's refusal enforces it in code; do not route around it.
- **`face_enhance` presets are the only enhancement an `operator_footage` cut accepts.**
  `look_filters` resolves `look["grade"]` against `FACE_PRESETS` **first** and only then
  against `GRADE_PROFILES` (`lib/polish_filters.py:163-175`), so a face preset sitting in the
  `grade` slot is permitted on a locked cut. What **raises** is a `color_grade` profile
  (`:169-173`) or any grain (`:177-181`) — a `PolishError`, not a silent drop, so a look that
  is not identity-safe fails the batch instead of applying to four fifths of it. The allowlist
  is `tools/enhancement/face_enhance.py:26-67`.
- **Do not bake the batch look here.** The grade is spliced into the per-segment re-encode
  at compose (`lib/polish_filters.py:228`). The one thing worth baking now is a
  `face_enhance` preset on a genuinely soft pool file — local ffmpeg, $0.00, identity-safe
  by construction. A `color_grade` profile baked onto a locked file is the same defect
  `look_filters` would have raised for, except unrecoverable.
- **The stamp is the enforcement point.** `look_filters` takes provenance as its second
  positional argument (`lib/polish_filters.py:149`); the function that reads it off the cut
  dict is `cut_filters` (`:194`), which passes `cut.get("provenance")` through at `:228`. So
  a cut whose provenance is missing or wrong reads as unlocked and gets graded. The stamp
  that reaches that call is `edit_decisions.cuts[].provenance`, which edit copies forward
  from the scene slot — not from anything this stage writes. What step 7's `cut_index` gives
  edit is the **cross-check** that the copy is right; get that right here.

**One look, every cut, locked ones included.** `batch_look` is a single project-level dict; there
is no per-provenance variant and no stage can put one look on cutaways and another on pool cuts.
No artifact readable at this stage carries it — edit-director authors it later onto the spine
root as `edit_decisions.batch_look` — so the value to check here is the pipeline's canonical
one, unless the operator named something else at this sitting:

```python
# Both names are face_enhance presets, so the canonical look resolves on locked
# and unlocked cuts alike and this loop cannot raise for it. The check earns its
# place only when the operator asks for a different look — substitute theirs.
CANONICAL_LOOK = {"grade": "talking_head_standard", "sharpen": "sharpen_light"}
operator_look = None                  # whatever the operator named this sitting, else None
proposed_look = operator_look or CANONICAL_LOOK
for cut in resolved:
    look_filters(proposed_look, cut["provenance"])   # lib/polish_filters.py:149
```

Dry-running it here costs nothing and fails before compose spends the 117 seconds a five-reel
sitting takes. A `PolishError` out of that loop is a blocker, not a look to quietly drop: report
it as a structured blocker per AGENT_GUIDE.md → "Escalate Blockers Explicitly", naming the cut id
and the offending key, and let the operator pick a different batch look — narrowing the look to
the unlocked cuts is not an option the stack offers.

### 6. Caption And Audio Prep

**Captions — rebase, then write both forms.** Each reel's spoken line is a window into its
track's transcript. Reel time starts at 0; track time does not. Subtract
`script.metadata.reels[].window.offset_seconds` before anything else —
`{**w, "start": w["start"] - shift, "end": w["end"] - shift}` over the words whose `end`
falls after the shift, exactly as step 4's fence does it. Subtract **once**: if the first
segment already starts before `offset_seconds`, script rebased them and a second subtraction
drives the whole reel negative, which is why step 4 computes `shift` rather than assuming it.

Write two files per reel from the rebased words (`subtitle_gen` format enum `srt|vtt|json`,
`tools/subtitle/subtitle_gen.py:50-54`). Both are inputs to the **same** Remotion burn, which
has no JSON-file parameter at all: its schema takes `segments`, an inline array
(`tools/video/remotion_caption_burn.py:86-92`), or `srt_path`, a path used as the alternative
when `segments` is absent (`:93-99`). So the `json` is the one compose **loads** and passes
as `segments`, and the `srt` is the one it passes as `srt_path` — the path taken when
Remotion itself is unavailable and the tool falls back to ffmpeg's `subtitles` filter
(`:13-14`). Keep `max_words_per_cue` at 3 — 9:16 has no room for eight. Do **not** try to
produce the pop look here: `subtitle_gen`'s `karaoke` style is an SRT `<b>` on the active
word (`tools/subtitle/subtitle_gen.py:243`, `:261`), and the animated word-by-word treatment
is the Remotion plane's job at compose.

**Audio — normalise the track, not the reel.** One pass per *track*, to the platform
target, so every reel of the batch shares one loudness:

```python
audio_mixer.execute({
    "operation": "full_mix",
    "tracks": [{"path": track_path, "role": "music", "volume": 1.0}],
    "normalize": True,
    "loudnorm_target": -14,      # IG/TikTok per sound-design.md (tools/audio/audio_mixer.py:134-147)
    "output_path": f"projects/{project_id}/assets/audio/{track_id}_norm.m4a",
})
```

`start_seconds` on a track is an **output delay** (`adelay`, `tools/audio/audio_mixer.py:234`,
`:253`), not a seek into the source — it cannot window into the middle of a track. The reel's
in-point and its trim to `<= 10s` are a `reel_plan` axis compose applies.

### 7. Write The Asset Manifest

The asset schema is **closed** (`additionalProperties: false` on each asset object,
`schemas/artifacts/asset_manifest.schema.json:55`, and on the root at `:61`; `metadata` at
`:59` is the one open object) and has no `provenance`, `in_seconds`,
`out_seconds` or `reel_id` field. Carry provenance in `subtype`, the schema's own
sub-classification slot, and put the per-cut geometry in the open `metadata`. The per-reel
caption files and normalised beds are ordinary `type: "subtitle"` / `"music"` assets in the
same list, because `reel_plan` resolves its `music_asset_id` and `subtitle_source` against
`assets[].id` and publish filters `assets[]` on `type == "music"` for the credit line.

Ids join or they are useless. Reel ids are `reel_NN`, cut ids `<reel_id>-<nn>`, asset ids
`asset_<reel_id>_<nn>` for a cut, `asset_<track_id>` for a bed, and
`asset_<reel_id>_captions_json` / `_srt` for captions. `scene_id` holds the **cut id** for a
cut asset and the **reel id** for a track or caption asset.

```json
{
  "version": "1.0",
  "assets": [
    {"id": "asset_reel_02_01", "type": "video", "path": "/pool/rack_pulls_A.mp4",
     "source_tool": "footage_library", "scene_id": "reel_02-01", "subtype": "operator_footage",
     "duration_seconds": 1.94, "resolution": "1080x1920", "provider": "operator",
     "license": "operator_owned", "cost_usd": 0,
     "generation_summary": "Pool segment [4.20, 6.14) — identity-locked, claimed by reel_02. Absolute path: the pool lives outside the project and is never copied."},
    {"id": "asset_reel_02_03", "type": "video", "subtype": "ai_generated",
     "path": "projects/<id>/assets/cutaway/cutaway_9f2c_flash.mp4",
     "source_tool": "cutaway_gen", "scene_id": "reel_02-03", "provider": "kling",
     "model": "v3/standard", "cost_usd": 0.1, "duration_seconds": 0.6,
     "prompt": "chalk dust drifting through a hard side light, black background, macro",
     "generation_summary": "Shortfall fill for reel_02-03, pinned kling_video via video_selector; silent, 9:16."},
    {"id": "asset_track_01", "type": "music",
     "path": "projects/<id>/assets/audio/track_01_norm.m4a",
     "source_tool": "audio_mixer", "scene_id": "reel_02",
     "provider": "operator", "license": "operator_owned", "cost_usd": 0,
     "generation_summary": "push_day.mp3 normalised to -14 LUFS, one pass per track."},
    {"id": "asset_reel_02_captions_json", "type": "subtitle",
     "path": "projects/<id>/assets/subtitles/reel_02.json",
     "source_tool": "subtitle_gen", "scene_id": "reel_02", "format": "json", "cost_usd": 0,
     "generation_summary": "Word-level, rebased to reel time; loaded by compose and passed as remotion_caption_burn `segments`."},
    {"id": "asset_reel_02_captions_srt", "type": "subtitle",
     "path": "projects/<id>/assets/subtitles/reel_02.srt",
     "source_tool": "subtitle_gen", "scene_id": "reel_02", "format": "srt", "cost_usd": 0,
     "generation_summary": "Fallback for remotion_caption_burn's `srt_path` when Remotion is unavailable."}
  ],
  "total_cost_usd": 0.1,
  "metadata": {
    "pipeline": "reel-batch",
    "corpus_dir": "projects/<id>/corpus",
    "cut_index": {
      "reel_02-01": {"asset_id": "asset_reel_02_01", "in_seconds": 4.20, "out_seconds": 6.14,
                     "provenance": "operator_footage", "identity_locked": true,
                     "source_tool": "footage_library"},
      "reel_02-03": {"asset_id": "asset_reel_02_03", "in_seconds": 0.0, "out_seconds": 0.6,
                     "provenance": "ai_generated", "identity_locked": false,
                     "source_tool": "cutaway_gen"}
    },
    "reel_index": {
      "reel_02": {"track_id": "track_01",
                  "music_asset_id": "asset_track_01",
                  "subtitle_json_asset_id": "asset_reel_02_captions_json",
                  "subtitle_srt_asset_id": "asset_reel_02_captions_srt",
                  "cut_ids": ["reel_02-01", "reel_02-02", "reel_02-03",
                              "reel_02-04", "reel_02-05"]}
    },
    "shortfall": {"measured_cuts": 1, "filled_by_cutaway": 1,
                  "reel_ids": ["reel_02"], "cut_ids": ["reel_02-03"]},
    "identity": {"locked_assets": 24, "generated_assets": 1, "guard": "text_prompt_only"}
  }
}
```

**What `cut_index` is, and is not.** It is the asset↔cut join plus the *resolved* geometry —
the only place the actual in/out points live after a substitute pick, and the only place an
AI cut's in/out exist at all, since an `ai_generated` scene slot carries no `in_seconds` or
`out_seconds`. edit-director reads `asset_id`, `in_seconds` and `out_seconds` from it to fill
`edit_decisions.cuts[].{source, in_seconds, out_seconds}`. It is **not** where
`edit_decisions.cuts[].provenance` comes from: per R5 that value is copied forward from the
scene slot, and `cut_index[cut_id]["provenance"]` plus `source_tool` are the cross-check
(`cutaway_gen` ⇒ `ai_generated`, `footage_library` ⇒ `operator_footage`). A mismatch escalates;
it is never reconciled silently. The `polish` block is edit's own work and appears nowhere here.

**What `reel_index` is.** `reel_index[reel_id]` is
`{track_id, music_asset_id, subtitle_json_asset_id, subtitle_srt_asset_id, cut_ids[]}`, and it
is the sole source edit-director builds `reel_plan` from: `music_asset_id` and
`subtitle_source` / `subtitle_srt_source` on a `reel_plan` entry are these asset ids, and
`cut_ids` is this list in reel order. Write it for every reel, including reels with no
cutaway.

**About `path`.** It is project-relative for everything this pipeline wrote — cutaways,
normalised beds, caption files. For an identity-locked pool row it is the **absolute** source
path, because the pool lives outside the project and `footage_library` never copies it
(`tools/video/footage_library.py:349-352`), even though the schema's own description reads
"Relative path within the pipeline project directory"
(`schemas/artifacts/asset_manifest.schema.json:21`; nothing validates the shape). Say so in
that asset's `generation_summary`, as above, so a reader is not left to guess which rule
applies.

A generated cutaway is `subtype: "ai_generated"`. `cutaway_gen` returns that string under the
key **`provenance`** on each of its result rows (`tools/video/cutaway_gen.py:426`); because
the asset schema is closed and has no `provenance` field, carry the value into `subtype` here
— and into `cut_index[cut_id]["provenance"]`, which is what edit cross-checks. Never write
`operator_footage` on something a model produced, and never the reverse.

### 8. Quality Gate

- Every cut slot resolves to a file that exists on disk, and `clips.assert_no_reuse()` passes.
- `metadata.cut_index` has an entry for every cut id, each carrying `asset_id`, `in_seconds`,
  `out_seconds`, `provenance` and `source_tool`, and every `provenance` agrees with the scene
  slot's declared value.
- `metadata.reel_index` has an entry for every reel id, each naming a `track_id`, a
  `music_asset_id`, both caption asset ids, and `cut_ids` in reel order — every id resolving
  to a row in `assets[]`.
- Cutaway count equals `len(scene_plan["metadata"]["shortfall"])` — not more, not fewer, not
  "one extra for safety". Every cutaway asset has `subtype: "ai_generated"`, a text-only
  `prompt`, and a `scene_id` equal to its shortfall entry's `cut_id`.
- Every reel has a rebased caption pair — one `json`, one `srt` — whose last word ends before
  the reel does.
- Every ledger entry from this stage is terminal, and `total_cost_usd` matches
  `tracker.cost_snapshot()["total_spent_usd"]` to the cent.
- No `color_grade` profile and no grain has been baked into any identity-locked file.

## Common Pitfalls

- **Booking the cutaway under `cutaway_gen` or `kling_video`.** The selector prices and bills;
  the concrete provider belongs in the operation string. A new tool name at spend time trips
  the first-paid-use guard by design.
- **One batch entry for all five cutaways.** After a mid-batch abort it has no honest
  terminal state — reconcile is one-shot, refund erases real billing.
- **Generating because the pool "feels thin".** The shortfall is measured at gate 1 and
  itemised per cut at gate 2; widening it here is unapproved spend. Reading the pool's
  capacity (`usable_segments // cuts_per_reel`) as the shortfall is the same mistake with a
  formula attached.
- **Reading a cut's own id as `cut_id`.** Inside a scene-plan or edit-decision cut object the
  field is `id`; `cut_id` is the name a cut carries when something *outside* it points back.
  `slot["cut_id"]` is a KeyError on the first slot.
- **Re-claiming a slot gate 2 already claimed.** `claim` raises on the reel's own live claim
  too — claim substitutes only.
- **Unrebased captions.** Track-time words on a reel-time timeline land seconds late and
  read as a render bug rather than a data bug.
- **Baking the grade at assets.** The picture plane is ffmpeg's at compose; baked here it
  bypasses the identity guard that would have refused it.
- **Treating a five-reel batch as five unrelated projects.** One loudness, one caption
  treatment, one look — decided once, applied identically.
