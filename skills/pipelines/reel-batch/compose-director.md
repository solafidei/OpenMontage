# Compose Director - Reel Batch Pipeline

## When To Use

The batch spine is locked. `edit_decisions` holds one flat `cuts[]` covering every
reel of the sitting — ids reel-prefixed, each cut carrying its `provenance` and its
`polish` block — and `reel_plan` holds the per-reel axes (`music_asset_id`,
`subtitle_source`, `hook`, `cut_ids[]`). Nothing has been rendered.

Your job is N finished 9:16 masters, one per reel, plus a `render_report` and a
`final_review` measured on those files. **You render; you do not edit.** Nudging an
in-point or a punch-in value here means going back to `edit` and re-emitting the spine.

## Runtime Routing (HARD CONSTRAINT — two runtimes, one reel)

Every other pipeline in this tree locks one `render_runtime` and renders once.
reel-batch runs **two planes in a fixed order**, because neither engine can do the
other's half. This is a **capability** ruling, not a speed one — never "simplify" it
into a single pass.

| Plane | Runtime | Why it cannot be the other engine |
|---|---|---|
| Picture (cuts, punch-in, speed ramp, flash, whip, grade, grain, sharpen) | **ffmpeg** | The polish splices into the per-cut re-encode's `vf_parts` (`tools/video/video_compose.py:625-639` → `lib/polish_filters.py:194-240`). Remotion's only grading hook is a CSS `filter`: no curves, no per-channel balance, no grain, no continuous ramp. |
| Text (word captions + hook overlay) | **remotion** | `remotion_caption_burn` is Remotion-only by its own module docstring (`tools/video/remotion_caption_burn.py:18-30`) — the `TalkingHead` composition id and the `WordCaption` prop shape are welded to the React stack in `remotion-composer/`. ffmpeg cannot do pop captions at all. |

`edit_decisions.render_runtime` governs the **picture** plane and MUST read
`"ffmpeg"`. `video_compose` refuses to guess: an empty or unknown value is a hard
failure carrying the "locked at proposal stage" error
(`tools/video/video_compose.py:1600-1623`), and `"ffmpeg"` is what routes to
`_render_via_ffmpeg` → `_compose` (`:1706-1714`, `:1973`) — the only path that honours
`batch_look`.

If it reads anything else: **stop**, render nothing, and surface it as a structured
blocker (AGENT_GUIDE.md → "Escalate Blockers Explicitly") — what the spine says, what
the picture plane requires, why. Route the decision back to `idea` to re-lock `ffmpeg`
and log a `render_runtime_selection` correction in `decision_log`. **Never silently
rewrite `edit_decisions.render_runtime`**: the two-plane split is what the operator
approved at gate 1, and rewriting it here forges that approval.

**HyperFrames, honestly.** `hyperframes` is a real third runtime `video_compose` routes
to, and for 9:16 kinetic typography it would be a fair candidate for the text plane. It
is not available here: word-level caption-burn parity on HyperFrames is explicitly
deferred (`tools/video/remotion_caption_burn.py:19-22`). The operator was shown both
runtimes once, at gate 1, with the measured rationale — recorded as
`render_runtime_selection` in `decision_log`, HyperFrames marked
`rejected_because: "caption-burn parity deferred"`. Do not re-open that conversation
every batch; do not pretend the option never existed.

reel-batch has no `proposal_packet` artifact, so `video_compose`'s in-tool swap check
reads its baseline from `edit_decisions.metadata.proposal_render_runtime`
(`tools/video/video_compose.py:2811-2818`). Confirm the edit stage carried that key —
without it the check returns `runtime_swap_check: "skipped — …"` (`:2710-2715`) and
the reviewer, not the tool, owns the comparison.

## Prerequisites

| Layer | Resource | Purpose |
|---|---|---|
| Schemas | `render_report.schema.json`, `final_review.schema.json` | `outputs[]` items and `checks` are both `additionalProperties: false` |
| Prior artifacts | `state.artifacts["edit"]["edit_decisions"]` + `["reel_plan"]` | Batch spine, then per-reel track/hook/subtitle source/cut ids. The manifest files `reel_plan` under compose's `optional_artifacts_in`; **here it is functionally required** — Steps 0-5 read `entry["cut_ids"]`, `entry["music_asset_id"]`, `entry["subtitle_source"]` and `entry["hook"]`, and none of them exist anywhere else |
| Prior artifact | `state.artifacts["assets"]["asset_manifest"]` | `asset_id` → real file path |
| Tool | `video_compose` | Picture plane, `profile: instagram_reels` |
| Tool | `remotion_caption_burn` | Text plane, one pass per reel |
| Library | `lib/polish_filters.py` | Raises `PolishError` on an identity-unsafe look |
| Cost tracker | `tools/cost_tracker.py` — `CostTracker.for_project(project_id)` | Reopens the ledger the idea and asset directors already wrote |

## Mental Model

A reel is **picture, then text**. The picture plane produces a graded, cut,
audio-carrying 1080x1920 master; the text plane takes that master as a plain video
input and burns one caption/overlay layer over it. No third pass, no round trip.

What the batch shares — grade, grain, sharpen — is one `batch_look` dict passed
identically to every reel (`tools/video/video_compose.py:225-239`). What differs per
reel — track, hook, caption line, cut list — comes out of `reel_plan`.

## Process

### 0. Pre-Flight

- Re-read the manifest's compose `review_focus`. Those are the review axes.
- Confirm `edit_decisions.render_runtime == "ffmpeg"` (Runtime Routing above).
- **`reel_plan` is functionally required**, whatever the manifest's `optional_artifacts_in`
  says. If it is absent: render nothing, and escalate a structured blocker back to `edit`
  (AGENT_GUIDE.md → "Escalate Blockers Explicitly") naming the four keys compose cannot
  synthesise. Do **not** reconstruct reels by splitting cut ids on their `reel_NN-` prefix
  — that recovers the grouping and invents the track, the hook and the subtitle source,
  none of which the spine carries.
- Confirm every `reel_plan["reels"][].cut_ids` id exists in the spine and appears in
  exactly one entry. A cut id in two reels is a batch-integrity failure, not a render bug.
- Build the asset lookup once and resolve every id through it, checking each file exists.
  One missing track fails one reel; finding it now costs nothing.
- Do **not** re-derive the look. `batch_look` comes from the spine, unchanged.

```python
spine = edit_decisions                                         # the batch spine, read-only from here on
asset_by_id = {a["id"]: a for a in asset_manifest["assets"]}   # asset id -> asset row
reels = reel_plan["reels"]                                     # Steps 1-4 run once per `entry` in this list
```

`music_asset_id`, `subtitle_source` and `subtitle_srt_source` on a `reel_plan` entry are
**asset ids**, not paths — `asset_by_id[...]["path"]` is the only way to a file.

### 0b. Ledger Round-Trip For The Render

Both planes are local, $0-API-cost operations. They still round-trip through the same
ledger so `cost_log.json` leaves no entry in `estimated`/`reserved` state. **One batched
entry covers the whole sitting** — every reel, both planes:

```python
from tools.cost_tracker import CostTracker

tracker = CostTracker.for_project(project_id)
entry_id = tracker.estimate("video_compose", "render x 5 reels, two planes", 0.0)
tracker.reserve(entry_id, user_approved=True)
...                                              # Steps 1-4: every reel, picture then text
tracker.reconcile(entry_id, 0.0, success=True)   # success=False only if the whole sitting is abandoned
```

The `0.0` is load-bearing: a local render is not a paid line and must not be armed like
one by the cost gate in `idea-director.md`. `user_approved=True` is carried on every
reservation this pipeline makes. A reel that fails to render does **not** flip the batch
entry — record it in `render_report.metadata.failed_reels` and reconcile `success=True`;
the money is $0.00 either way. Never open a second entry for a retried reel.

On resume, sweep the ledger for entries left non-terminal by an abort **before**
re-rendering anything. Do not improvise the recovery — follow
`skills/meta/checkpoint-protocol.md` → **Cost Ledger Governance** exactly, including
the corrupt-ledger path. It is the authority; this file does not restate it.

### 1. Materialise One Reel's `edit_decisions` — In Memory

`edit_decisions` structurally cannot hold five reels: it carries exactly one
`audio.music` object with a single `asset_id`
(`schemas/artifacts/edit_decisions.schema.json:145-148`) and exactly one `subtitles`
object (`:185-200`). So build each reel's decisions in memory by filtering the spine
and merging that reel's `reel_plan` entry. **Nothing here is written to disk** — the
spine stays the artifact of record.

```python
from lib.reel_plan import entry_for, materialise

reel = materialise(spine, entry_for(reel_plan, reel_id))
```

`lib/reel_plan.py` owns the filter rather than this file because a reel that renders
short because a cut was dropped is a silent defect, and an instruction cannot be tested.
`materialise` raises `ReelPlanError` when a `reel_plan` names a cut the spine does not
have — failing loudly is the feature. It takes cuts in `entry["cut_ids"]` order, which
is reel order, not spine order.

`materialise` carries `spine["metadata"]` forward, which keeps
`proposal_render_runtime` in front of the tool's runtime-swap check (`tools/video/video_compose.py:2811-2818`) and preserves the
project-level `identity_lock` arming flag for the record. **`identity_lock` is not what
the identity gate reads.** The gate that actually fires is per cut:
`lib/polish_filters.py:160` computes `locked = provenance == OPERATOR_FOOTAGE` from
`cut["provenance"]`, and the schema says so outright — "Gates assert on it per cut, which
is why it is typed here rather than side-mapped in metadata"
(`schemas/artifacts/edit_decisions.schema.json:68`; the metadata flag itself is declared
at `:266` as "a per-project arming switch … not a per-clip label"). So a cut that lost its
`provenance` renders an unsafe look no matter what `metadata.identity_lock` says — which
is why Step 1 copies whole cut objects rather than rebuilding them.

### 2. Picture Plane — `video_compose` At `instagram_reels`

One call per reel. `profile: "instagram_reels"` resolves 1080x1920 @ 30fps and, being
portrait, flips the fit mode to `cover` so landscape source fills the frame instead of
letterboxing into black bars (`tools/video/video_compose.py:517-528`).

```python
from tools.video.video_compose import VideoCompose

picture = VideoCompose().execute({
    "operation": "render",
    "edit_decisions": materialise(spine, entry),
    "asset_manifest": asset_manifest,
    "profile": "instagram_reels",
    "audio_path": asset_by_id[entry["music_asset_id"]]["path"],
    # The bed starts at the reel's window, not at t=0 — `video_compose` seeks the
    # audio input with -ss. The normalised track is whole; the reel is a slice of it.
    "audio_start_seconds": entry.get("audio_offset_seconds", 0.0),
    "batch_look": spine["metadata"]["batch_look"],   # {"grade": "talking_head_standard", "sharpen": "sharpen_light"}
    "output_path": f"projects/{project_id}/renders/{entry['reel_id']}-picture.mp4",
})
```

That look is the canonical one for this pipeline, and its shape is load-bearing:
`talking_head_standard` and `sharpen_light` are both `face_enhance` presets, and there is
**no `grain` key**. A `color_grade.PROFILES` name (`high_contrast`, `moody_dark`,
`cinematic_cool`, …) or any non-zero `grain` raises `PolishError` on the first
`operator_footage` cut (`lib/polish_filters.py:169-180`) — and in this pipeline almost
every cut is operator footage, so such a look kills the render outright rather than
degrading it.

Cuts, `punch_in`, `speed_ramp`, `transition_out: flash|whip`, grade, grain and sharpen
all land inside the per-segment re-encode — there is no separate polish step. A
`PolishError` naming `operator_footage` (`lib/polish_filters.py:169-180`) means the
**edit** stage put a colour-grade profile or grain on an identity-locked cut — the face
presets in the canonical look are fine there. Route it back to `edit`, and never strip a
cut's `provenance` to make the render pass.

`video_compose` runs its own `final_review` after the render and downgrades the
`ToolResult` to `success=False` when it says `fail` — in the ffmpeg branch this pipeline
locks, that block is `tools/video/video_compose.py:1975-1997`. Read
`picture.data["final_review"]`, but remember it describes `<reel_id>-picture.mp4`, the
*pre-caption* file. It is not the stage's `final_review`.

### 3. Text Plane — Exactly One `remotion_caption_burn` Pass

One pass over the finished picture master, carrying both the word captions and the hook
overlay. Two passes would mean a third encode generation for nothing.

`entry["subtitle_source"]` is an **asset id**, and the tool has no "load this JSON file"
input — so resolve it, load it, and pass its cues under the tool's `segments` input. The
caption look is likewise not re-typed here: `preset` and `safe_zone` were authored once by
edit-director in `edit_decisions.metadata.caption_style`, and compose reads them from there.

```python
import json
from tools.video.remotion_caption_burn import RemotionCaptionBurn

caption_style = spine["metadata"]["caption_style"]   # {"preset": "reel_pop", "safe_zone": {...}}
caption_path = asset_by_id[entry["subtitle_source"]]["path"]
with open(caption_path) as fh:
    word_segments = json.load(fh)["cues"]            # the file's key is "cues"; the burn tool's input is "segments"

burn_inputs = {
    "input_path":  f"projects/{project_id}/renders/{entry['reel_id']}-picture.mp4",
    "output_path": f"projects/{project_id}/renders/{entry['reel_id']}.mp4",
    "segments": word_segments,
    "preset": caption_style["preset"],
    "safe_zone": caption_style["safe_zone"],         # {"bottom": 0.18, "sides": 0.08}
    "words_per_page": 3,
    "fps": 30,
    "run_id": entry["reel_id"],
    "overlays": [{
        "type": "hero_title",
        "in_seconds": 0.0,
        "out_seconds": 2.5,
        "position": "upper_third",
        "text": entry["hook"],                       # a string, from script.metadata.reels[].hook.text
    }],
}
if entry.get("corrections"):
    burn_inputs["corrections"] = entry["corrections"]   # {wrong: right}, carried from script

burn = RemotionCaptionBurn().execute(burn_inputs)
```

- **The on-disk key is `cues`; the tool's input parameter is `segments`.** `subtitle_gen`'s
  JSON writes `{"cues": [...], "highlight_style": ...}`
  (`tools/subtitle/subtitle_gen.py:107`), and each cue already carries the `words[]` the
  burn reads (`tools/video/remotion_caption_burn.py:222-226`). There is no top-level
  `segments` key in that file — reaching for one raises `KeyError` before a single caption
  is drawn.
- **Never re-type `safe_zone` as a literal.** `sides` is `0.08` in the authored style; a
  hand-typed `0.06` here silently ships captions 2% of frame width wider than the batch
  agreed. Read `spine["metadata"]["caption_style"]`, whole.
- `corrections` only goes in when non-empty — the script stage's `{wrong: right}` map is
  the last chance to fix a misrecognised word before it is burned into pixels
  (`tools/video/remotion_caption_burn.py:148-155`).
- If the JSON caption asset is missing but the SRT one is not, fall back to
  `srt_path=asset_by_id[entry["subtitle_srt_source"]]["path"]` **instead of** `segments`.
  It is a downgrade, not an equivalent: SRT has no word timings, so `reel_pop`'s per-word
  pop degrades to line-at-a-time. Surface it before shipping.
- **`run_id` is mandatory in a batch.** Without it every render stages into the same
  shared `public/talking-head/` directory, so masters sharing a filename overwrite
  each other mid-flight (`tools/video/remotion_caption_burn.py:139-146`, `:350-358`);
  the run-scoped directory is also the only one the tool is allowed to delete
  afterwards (`:398-401`). It must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` (`:510`)
  — a plain `reel_id` does.
- `preset: "reel_pop"` is the 9:16 look: per-word scale pop, heavy stroke, uppercase,
  no pill (`:115-124`). `bottom: 0.18` is what clears Instagram's own lower UI band
  (`:125-132`).
- `fps` must match the input; the picture plane pins `-r 30` in the per-segment encode
  (`tools/video/video_compose.py:667`; whole flag block `:662-670`), so 30 it is.

### 4. Checkpoint After Every Reel

**This stage owns the ONLY per-reel `in_progress` checkpoint in the pipeline.** It lives
on the compose **checkpoint's** `metadata.partial_progress` — not on any artifact — and
carries `completed_reel_ids`, `reel_outputs`, `render_seconds` and `failed_reels`. No
other stage has one: `assets` is resumable by **idempotence** (the cutaway `cache_dir`
makes a re-run of an already-generated prompt free, the clip ledger raises rather than
double-claiming, and every ledger entry reaches a terminal state before the stage ends),
not by a partial-progress record. If any document claims `assets` writes
`metadata.partial_progress.completed_reel_ids`, that document is wrong.

A mid-batch abort must leave a resumable checkpoint, never a half-written report. After
**each** reel finishes its text plane, re-write the `compose` checkpoint with
`status="in_progress"` and, in `metadata.partial_progress`:

- `completed_reel_ids: [...]` — reels whose **final captioned master exists on disk**;
- `reel_outputs: {reel_id: path}` and `render_seconds: {reel_id: {picture, text}}`;
- `failed_reels: [{reel_id, plane, error}]`.

Attach `cost_snapshot` as `CostTracker.cost_snapshot()` plus `budget_total_usd` from
`tracker.budget_total_usd` — four number keys, the closed set the checkpoint schema
accepts. Never assemble that dict by hand.

On resume, read `completed_reel_ids` and render **only the reels not in it**, then
rebuild `render_report.outputs[]` from the union of recorded and new outputs. A reel
counts as complete only when the captioned master exists — a `<reel_id>-picture.mp4`
with no `<reel_id>.mp4` beside it is unfinished, and re-running its text plane is cheap.

Compose claims nothing from `lib/clip_ledger.py`; the cut list was claimed upstream. One
exception: if the operator **drops** a reel rather than resuming it,
`ClipLedger.for_project(project_id).release_reel(reel_id)` returns exactly that reel's
live claims to the pool (`lib/clip_ledger.py:204-210`). Otherwise leave it alone.

### 5. Assemble The Render Report

One `outputs[]` entry per reel, each with `platform_target`, every field probed from
the file rather than copied from the plan:

```json
{
  "version": "1.0",
  "outputs": [
    { "path": "projects/<id>/renders/reel_01.mp4", "format": "mp4", "codec": "h264",
      "audio_codec": "aac", "resolution": "1080x1920", "fps": 30,
      "duration_seconds": 9.8, "file_size_bytes": 4812344,
      "platform_target": "instagram_reels" }
  ],
  "render_time_seconds": 117.0,
  "warnings": ["caption pass re-encodes the master once at crf 18"],
  "verification_notes": ["reel_01: 1080x1920, audio present, captions visible at 1.0s"],
  "render_grammar": "documentary-montage",
  "metadata": {
    "pipeline": "reel-batch",
    "reels": [
      { "reel_id": "reel_01",
        "path": "projects/<id>/renders/reel_01.mp4",
        "hook": "You don't need motivation. You need a schedule.",
        "track_asset_id": "asset_track_01",
        "cut_ids": ["reel_01-01", "reel_01-02", "reel_01-03",
                    "reel_01-04", "reel_01-05"] }
    ],
    "batch_look": { "grade": "talking_head_standard", "sharpen": "sharpen_light" },
    "picture_seconds": 47.0, "text_seconds": 68.0, "failed_reels": [] }
}
```

`render_time_seconds` is the sitting's wall clock, so it sits a little above
`picture_seconds + text_seconds` — the probe between the two planes lives in that gap.

`outputs[]` items are `additionalProperties: false` and carry no `reel_id`, so **reel
identity cannot live there** — it goes in `metadata.reels[]`. **That array is the
authoritative reel↔output join publish-director uses**; the filename-stem heuristic is
only a fallback for a report that lacks it, so every reel that rendered must appear here.

Each entry carries `track_asset_id` — an **asset id**, resolvable through
`asset_manifest.assets[].id` — not a free-text track name that publish cannot resolve to
anything. `cut_ids` travels too, because publish needs it to describe what a reel shows.

**Only the final captioned master appears in `outputs[]`.** The picture intermediate
`renders/<reel_id>-picture.mp4` is never listed: it is a working file, it has no captions,
and listing it would put a non-deliverable in front of the operator.

`render_grammar` is a closed enum, and this pipeline's `renderer_family` —
`documentary-montage` — is a member of it, so carry the spine's value straight through.
Omit the field only if the spine has none; never invent a value to fill it.

### 6. Final Review Over The Actual Rendered Files

The stage's `final_review` must be measured on the **captioned masters** — not the
picture intermediates, and not `video_compose`'s own returned review.

Per reel, probe the final `<reel_id>.mp4`: 1080x1920, 30fps, audio stream present,
duration ≤ 10s. Then extract at least four frames — one inside the hook window (≈1.0s),
one mid-reel, one at a `flash`/`whip` accent, one at the tail — and look at them.
Captions and hook must be visible in the pixels and clear of the bottom 18%. A render
that "succeeded" but burned no captions is the loudest failure mode here, and only a
frame proves it.

The schema takes one `output_path` and one `status`, so aggregate honestly:
`status` is the **worst** per-reel verdict, `output_path` names the reel that produced
it, `issues_found[]` entries are prefixed with their reel id, and the full per-reel
table goes in `metadata.per_reel` (`checks` is `additionalProperties: false` — do not
add a key there). `recommended_action: "re_render"` for a fixable reel,
`"revise_edit"` when the cut list is at fault.

`checks` requires **all five** of `technical_probe`, `visual_spotcheck`, `audio_spotcheck`,
`promise_preservation` and `subtitle_check` — omitting any one fails `write_checkpoint`
*after* the whole sitting has already rendered, which is the most expensive place to
discover it. Four you measure on the masters. `promise_preservation` is the delivery-promise
check, and this pipeline's promise is the two-plane split itself: every reel is real
operator footage cut to its own track, no still-image substitution and no runtime swap. Pass
it when `edit_decisions.render_runtime` came through as `ffmpeg`, every cut resolved to a
video file, and `runtime_swap_detected` is false; fail it the moment any of those slipped.

### 7. Quality Gate

- One `outputs[]` entry per planned reel, each with `platform_target`; every output
  exists and passes ffprobe at 1080x1920 with an audio stream.
- Every reel carries its own track and its own hook — nothing pasted across the batch.
- Captions burned and inside the safe zone, verified in frames.
- `final_review` produced from the captioned masters, `status` = worst reel.
- `cost_log` has every entry in a terminal state (completed/failed/refunded) and totals
  matching what the run actually spent.
- `render_report.warnings` names every substitution and every failed reel.

## Wall Clock To Expect

Measured on the dev machine at 1080x1920, 10s, 5 cuts
(`scripts/reel_batch_two_plane_demo.py:18-21`): picture **9.4s** + text **13.6s** =
**23.0s** for a single reel, and **117.0s for a five-reel sitting** — **23.4s a reel**, the
extra 0.4s being the probe between planes. The text plane is the slower half and always
will be — the price of the capability, not a tuning problem. Materially past that means
something is re-encoding twice or Remotion is cold-starting per reel; investigate
before adding reels. `max_wall_time_minutes: 20` gives five reels ten times the room.

## Known And Accepted

**The caption pass re-encodes the master a second time.** The picture plane encodes
segments at the `crf` default of 23 (`tools/video/video_compose.py:221`, `:644`); the
caption pass re-encodes the whole master at `--crf=18`
(`tools/video/remotion_caption_burn.py:392`). One generation of loss, applied to
already-encoded pixels at a higher quality target — visually near-transparent at these
bitrates on a 10s 9:16 deliverable. Record it once in `render_report.warnings` and move
on. **Do not chase it**: the only ways out are burning captions in ffmpeg (impossible —
see Runtime Routing) or rendering the picture lossless first, which costs disk and wall
clock for a difference nobody watching on a phone can see.

## Common Pitfalls

- **Rendering the batch as one timeline.** Five reels are five renders. The spine is a
  spine, not a sequence.
- **Keeping spine order when filtering cuts.** Order by `reel_plan["reels"][].cut_ids`; the
  spine's order is batch order, not reel order.
- **Omitting `run_id`.** Silent, and it corrupts the batch rather than failing it.
- **Treating `subtitle_source` or `music_asset_id` as a path.** They are asset ids;
  resolve through `asset_by_id[...]["path"]` before opening anything.
- **Re-typing the caption style here.** `preset` and `safe_zone` are read whole from
  `spine["metadata"]["caption_style"]` — a literal typed at the burn call is how the
  batch drifts out of the look edit-director authored.
- **Two caption passes.** Captions and the hook go in one call; `overlays` exists for
  exactly this.
- **Treating `video_compose`'s returned `final_review` as the stage artifact.** It
  reviewed the picture plane; its `subtitle_check` cannot have seen a caption.
- **Writing `render_report` only at the end.** An abort at reel four loses four
  finished reels. Checkpoint after each one.
- **Fixing a bad cut here**, or **letting one reel's failure stop the batch.**

## When A Reel Fails

1. Categorise per the Decision Communication Contract (auth / provider / tool bug / plan
   quality). A local two-plane render has no auth or provider failures — it is almost
   always a path or a plan-quality error.
2. **Picture plane, `PolishError`** → the edit stage requested an identity-unsafe look.
   Route back to `edit`. Never strip `provenance` to force it through.
3. **Picture plane, missing source** → re-check `asset_id` → path resolution in
   `asset_manifest`. One unresolved id fails that reel only.
4. **Text plane, Remotion unavailable** → the tool has an ffmpeg subtitle fallback, but
   it is not `reel_pop` and it is not the approved look. Surface the downgrade and get
   approval before shipping a reel that burned it; `burn.data["method"]` says which ran.
5. Continue the remaining reels either way, then present the batch with the failures
   named. A four-of-five sitting delivered honestly beats a stalled batch.
