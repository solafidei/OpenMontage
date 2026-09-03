# Reel Batch — specification

**Status:** specified, ready to implement
**Pipeline name:** `reel-batch`
**Epic:** #35
**Derived from:** a requirements interview with the operator, then a ten-dimension grounding sweep
of this repository, then five adjudications resolving conflicts between the independent slice
designs. Every claim below carries a `path:line` citation or was verified by execution on this
machine. Claims that were asserted by a designer and later **refuted** are recorded as such rather
than quietly dropped.

---

## 1. Confirmed intent

The operator dumps a pool of his own gym footage plus a few motivational audio tracks — music with
a spoken motivational voice baked into the track — and receives **several finished 9:16 Instagram
Reels from one sitting**. **A reel does not exceed 10 seconds.**

Each reel is cut to the beat, carries word-synced captions transcribed from the track's speech, opens
with a hook, weaves in AI-generated cutaway b-roll, and is colour-graded.

| | |
|---|---|
| **Outcome** | ~5 finished 9:16 reels per sitting, **each ≤ 10s**, from one footage pool and a few tracks |
| **User** | The operator alone. Single-operator tool; no multi-user concerns. |
| **Why now** | He posts daily but films in bursts. Today each reel costs a manual CapCut sitting or a generic template. |
| **Success** | One sitting yields ~5 reels he would post as-is. If he still fixes cuts by hand, it failed. |
| **Constraints** | His time. A used-clip ledger — no clip reused across a batch. **Identity is inviolable.** |
| **Approval shape** | He approves a cut list + hook **per reel** before any render. He never touches individual cuts. |

### 1.1 The identity constraint (binding)

**His face is never regenerated.** AI generates only cutaways he does not appear in. Clips he
appears in receive **only** grade / grain / sharpen / lighting / upscale. `faceswap`, avatars, and
video-restyle of his own clips are out of scope entirely — the restyle path may be revisited later
as an explicit opt-in, never inside a batch.

He describes "beautify" as allowed. Under this spec that means colour and light, never identity.

### 1.2 Effects vocabulary

In scope: punch-in zooms on hits, speed ramps, flash/whip cuts on the drop, one consistent colour
grade per sitting. Out of scope: particle overlays, 3D.

### 1.3 Out of scope

- `faceswap`, avatars, video-restyle of operator footage
- Him talking to camera (a future pipeline; captions here come from the track, not from him)
- Auto-posting to Instagram — the pipeline packages an export, a human posts it
- A frame-level timeline editor. Polish beyond the pipeline stays in CapCut.
- The hook/caption **copy research** stage. He owns a web-scraping API key intended for studying
  what holds attention on comparable reels; that is deliberately deferred to its own effort.

---

## 2. Verified baseline

### 2.1 What already exists and is reused

| Capability | Where | Reused how |
|---|---|---|
| Word-synced transcription | `tools/analysis/transcriber.py:165` — faster-whisper, `word_timestamps=True`, local, $0.00 | Caption timing, verbatim |
| Caption burn + overlay | `tools/video/remotion_caption_burn.py`, `remotion-composer/src/components/CaptionOverlay.tsx` | The text plane, extended with a pop preset |
| CLIP retrieval stack | `lib/clip_embedder.py`, `lib/corpus.py`, `tools/video/clip_search.py` | Slot-filling from the operator's own pool |
| Colour grade | `tools/enhancement/color_grade.py:79` — 7 ffmpeg profiles + `.cube` LUT + intensity blend | The batch-wide look |
| Identity-safe beautify | `tools/enhancement/face_enhance.py:71` — smartblur / unsharp / curves / colorbalance / hqdn3d | "Beautify" that cannot regenerate a face |
| Video generation fleet | 24 tools in `tools/video/`, routed by `tools/video/video_selector.py:15` through `lib/scoring.py:373` | AI cutaways |
| Money ledger | `tools/cost_tracker.py` (997 lines) — estimate→reserve→reconcile→persist, file locking, atomic saves | Cost governance, and the persistence pattern the clip ledger copies |
| Beat/energy analyser | `.agents/skills/music-to-video/scripts/analyze-beatgrid.py` — bpm, beats, downbeats, per-onset events, energy phases, rolls, silences, hard_stops, key_moments, phrases | The beat grid — **once it can run** |

Credentials live on this machine: `FAL_KEY`, `FAL_AI_API_KEY`, `GOOGLE_API_KEY`, `ELEVENLABS_API_KEY`.
Five cloud video generators are reachable; `KLING_API_KEY` is **empty**, so `kling_official_video`
and its $0.18/5s classic route are **not** reachable (this refutes a figure in the grounding sweep).
All three render engines report live: `video_compose.get_info()["render_engines"]` →
`{"ffmpeg": true, "remotion": true, "hyperframes": true}` (`tools/video/video_compose.py:277-295`).

### 2.2 What is missing — the actual work

1. **The beat analyser cannot run.** `import librosa` fails; `librosa` and `soundfile` appear in
   none of the three requirements files, while `.agents/skills/music-to-video/SKILL.md:51-55` pushes
   the install onto the agent at run time. The repo's only music-timing analyser is dead code today.
2. **Speech contaminates the beat grid.** The analyser is built for instrumental BGM — its own skill
   states "there is no narration". A spoken voice lands in the snare band (150-900 Hz,
   `analyze-beatgrid.py:79`), and `detect_rolls` accepts any run of ≥4 onsets at mean spacing under
   `0.42 × beat_dur` (`:227`) — normal speech at ~5 syllables/sec reads as a sustained fill.
   `references/planning.md:46` forbids cutting inside a `rolls[]` run, so speech both **blocks
   legitimate cut points** and **falsely promotes a weak grid to trusted**.
3. **No segment-level footage model.** A corpus row is one whole **file** — `ClipRecord` has no
   in/out offsets — so "split a 45s set into three usable pieces and index each" has no
   representation anywhere. Every path into the corpus is hard-wired to remote stock APIs; all 17
   adapters are network providers. There is no local-footage ingest.
4. **No batch data model.** Every artifact schema is single-deliverable and `additionalProperties:
   false`; a checkpoint is one file per (project, stage) with no reel dimension
   (`lib/checkpoint.py:272`). `reel_id` does not exist.
5. **The motion half of the effects vocabulary is absent.** Zero `zoompan` in the entire tree
   (verified). No punch-in is ever applied to a video clip; every speed control is a constant
   per-cut factor, never a ramp; the only transitions are hard cut / crossfade / fade-through-black.
6. **No identity machinery.** `tools/analysis/face_tracker.py:29` detects face *presence*, never
   identity — and it cannot run: neither `mediapipe` nor `cv2` is importable and neither appears in
   any requirements file, so `get_status()` returns UNAVAILABLE. Worse, its
   `dependencies = ["cmd:ffmpeg"]` (`:39`) does not declare them at all, so preflight reports the
   tool satisfied while `execute()` raises on import.

### 2.3 Defects found in shipped code (pre-existing, not caused by this work)

- **D1 — unpinned b-roll routes expensively.** `video_selector.estimate_cost` with no
  `allowed_providers` returns **$1.52** per 5s clip (seedance standard, verified by execution). At
  one cutaway per 10s reel that is **$7.60** a batch against a $1.50 quality route — 5×, for footage
  trimmed to two seconds. `config.yaml:10` is `mode: warn`, which annotates the entry and proceeds
  (`tools/cost_tracker.py:280-282`) rather than stopping it.
- **D2 — a mistyped provider pin estimates $0.00.** Verified: `["kling"] → $0.10`,
  `["gemini_omni"] → $0.50`, but `["fal"] → $0.00` and `["typo_provider"] → $0.00` via the
  no-candidate branch (`tools/video/video_selector.py:295-297`). A $0.00 estimate is exempt from
  **both** approval guards — `estimated > single_action_approval_usd` (`tools/cost_tracker.py:256`)
  and `require_approval_for_new_paid_tool and estimated > 0` (`:264`) — so a typo seeds an
  unguarded line item.
- **D3 — the estimate/execute split.** The sharper variant of D2: a gate that prices with
  `allowed_providers=["kling"]` ($0.10) while the spending director executes **without** it (routing
  to seedance at $1.52) is a 15× under-price that slips both guards because $0.10 < $0.50.
- **D4 — `_pre_compose_validation` is bypassed on two render paths.** Its only call site is
  `tools/video/video_compose.py:1643`, but the atelier path returns at `:1592` and the HyperFrames
  path at `:1610`. A gate placed only there does not run for those runtimes. Verified.
- **D5 — the `edit_decisions` schema is behind the shipped code.** `video_compose.py:797` reads
  `cut["type"]` and `AGENT_GUIDE.md:419-420` documents a whole `cut.type` vocabulary, but a cut
  carrying `type` fails validation: `Additional properties are not allowed ('type' was unexpected)`.
  Verified by execution. This is an under-maintained schema, not a load-bearing frozen contract.
- **D6 — `profile: instagram_reels` letterboxes landscape footage.** `profile` overrides resolution
  but leaves `fit_mode` at its `pad` default (`tools/video/video_compose.py:475-492`), so landscape
  gym clips pillarbox instead of filling the 9:16 frame.

### 2.4 A designer claim this spec refutes

The render adjudication reported that `CaptionOverlay` renders words with no separating space
("word12word13word14"). **This is false as of today's tree.** `wordSeparator` is a typed prop
defaulting to `" "` (`remotion-composer/src/components/CaptionOverlay.tsx:31, :146`) and is applied
per word at `:128`. The CJK caption work already fixed it. No issue is filed for it.

---

## 3. Rulings

Six binding rulings. Each replaces a disagreement between independent designs; each was decided on
evidence read from or executed against the repository.

### R1 — The pipeline is named `reel-batch`

Manifest at `pipeline_defs/reel-batch.yaml` with `name: reel-batch`; directors at
`skills/pipelines/reel-batch/`. All 13 shipped manifests set `name:` equal to the filename stem;
`lib/pipeline_loader.py:60` opens `defs_dir / f"{name}.yaml"` and
`tests/contracts/test_pipeline_catalog.py:27` discovers by `p.stem` — **the stem is the identity**.

`gym-reels` is rejected on a checkable convention: not one of the 13 catalogue names encodes a
subject-matter niche. Every existing name states a deliverable form, a production mode, or a source
type (`clip-factory`, `documentary-montage`, `podcast-repurpose`, `talking-head`). `reel-batch` is
`clip-factory`'s exact formula and distinguishes itself correctly — clip-factory is many clips from
**one** source; reel-batch is N independent reels from a **pool**.

Every `<reel-pipeline>` / `<reels-pipeline>` / `<pipeline>` placeholder in the slice designs
resolves to `reel-batch`.

### R2 — One issue owns the manifest and the whole director set

Five dynamic contract suites sweep `pipeline_defs/*.yaml` with no allowlist, so a half-built rival
manifest fails CI the moment it lands. Exactly one issue creates `pipeline_defs/reel-batch.yaml` and
all eight files under `skills/pipelines/reel-batch/`; it is the only issue permitted to touch either
path. Every other workstream contributes its stage block and its director section as **input** to
that issue and keeps only its tool/lib/schema/test work.

`orchestration.mode: executive-producer`, matching 12 of 12 episode manifests. The ledger-arming gate
lives in `idea-director.md`, as it does in all eight pipelines that carry the marker.

### R3 — Seven stages, eight directors

| Stage | Director | Produces | Approval |
|---|---|---|---|
| `idea` | `idea-director` | `brief`, `source_media_review`, `decision_log` | **true** — gate 1 |
| `script` | `script-director` | `script`, `audio_analysis` | false |
| `scene_plan` | `scene-director` | `scene_plan`, `decision_log` | **true** — gate 2 |
| `assets` | `asset-director` | `asset_manifest`, `cost_log` | false |
| `edit` | `edit-director` | `edit_decisions`, `reel_plan` | false |
| `compose` | `compose-director` | `render_report`, `final_review` | false |
| `publish` | `publish-director` | `publish_log` | **true** |

Plus `executive-producer.md`. The six directors invented across slices (audio-, broll-, caption-,
footage-, polish-, reel-edit-) are **not** created as files; they fold in as sections.
`caption-director` splits three ways: transcript at `script`, style at `edit`, burn at `compose`.

**Gate 2 (`scene_plan`) is the cut-list-plus-hook approval** and the last stage before any paid call
— which is what lets `assets` run unattended.

Stage names stay canonical. `lib/checkpoint.py:31-40` maps only the nine canonical names to a
required artifact, so a custom name (`reel_edit`) silently buys **zero** checkpoint validation —
exactly what happened to character-animation's `character_design` / `rig_plan`.

### R4 — Extend the `edit_decisions` schema; do not hide in `metadata`

`additionalProperties: false` is real at the root (`schemas/artifacts/edit_decisions.schema.json:236`)
and on the cut item (`:66`) — but that constrains **instances**, not the schema file. Adding an
optional property is a monotone widening: every artifact valid before is valid after. Verified by
execution. Only `lib/checkpoint.py:164` validates this artifact; no runtime consumer rejects unknown
keys; no test asserts the cut property set; there are no `edit_decisions` fixtures to re-baseline.
Additive extension is this repo's own practice — `render_runtime`, `composition_mode` and `bespoke`
were all added post-release.

**The dividing rule (binding):** if a value is one-per-cut, or if any gate, reviewer or contract test
must assert on it, it is a **typed schema property**. It must live on the cut and never as a side-map
in `metadata`, because nothing enforces that such a map covers every cut — and that correspondence
invariant is exactly what the identity guarantee needs.

`metadata` remains legitimate for three things only: opaque runtime hints already read as such
(`metadata.compose_target`, `video_compose.py:476-483`), tool-internal telemetry no gate asserts, and
pipeline-private scratch. Under this rule the beat grid — cross-cut, gate-free — correctly stays out
of the cut schema.

### R5 — Identity: default-deny provenance, declared at ingest, never inferred from pixels

One mechanism, one word, two machine checks, one gate, one test file.

**(a) Classification.** Every file entering from the operator's pool is written to the corpus with
`identity_locked=True`, a typed field on `ClipRecord` (`lib/corpus.py:44-71`). There is no
classification step and no per-clip judgement: **the pool is his footage, so the whole pool is
locked.** `face_tracker` is disqualified from every link — it is presence detection, not recognition,
and it cannot run at all (§2.2.6). A gate whose verdict is indeterminate on 100% of runs is not a
gate. The manual flag is not merely more honest here; it is the only mechanism that functions.

**(b) Travel.** `identity_locked` maps at cut-list time to one additive property on the cut:
`provenance`, enum exactly `["operator_footage", "ai_generated"]`. Two names exist in the whole
system and no more: `ClipRecord.identity_locked` and `cut.provenance`. The single exception is
`edit_decisions.metadata.identity_lock: true`, kept as the per-project **arming switch** — a boolean
that turns the check on, not a per-clip label.

**(c) Forbidden, as code.** Two checks at the two seams:
- **Input side** — `cutaway_gen` fails closed: any input carrying a media reference
  (`reference_image_path`, `image_url`, `init_video`, or equivalent) is rejected outright. AI
  cutaways are **text-prompt only**. This is what structurally prevents his likeness from reaching a
  generative model.
- **Output side** — a compose gate asserting every cut marked `operator_footage` was touched only by
  the allowed filter set, and that no cut sourced from an `identity_locked` corpus row carries
  `provenance: "ai_generated"`.

**(d) Where it hard-fails.** Not only in `_pre_compose_validation` — see **D4**; the atelier and
HyperFrames paths return before it. The check must sit where all render paths pass, or be duplicated
onto each.

**(e) Honest limits.** This guarantee is enforceable inside the pipeline's own tools and artifacts.
It does **not** bind a human running `faceswap` by hand, and `provenance` proves **declaration**, not
detection — a director that mislabels an operator clip as `ai_generated` passes every gate. Stated
plainly rather than papered over.

### R6 — Render is a two-plane split; the speed argument is dead

Both render designs assumed wall-clock decided it. Measured, it does not. The measurements were taken
on a 30s 8-cut 1080×1920 reel: **ffmpeg segment encode 4.4s**; **Remotion `CinematicRenderer` 44.8s**
including bundle, producing a verified 1080×1920 / 30fps / 900-frame mp4. At the confirmed 10s reel
length these scale to roughly **1.5s and ~18s** per reel — the Remotion figure is bundle-dominated and
so falls sub-linearly — putting a five-reel sitting near **100 seconds** end to end. Nobody's
hour-long batch exists on either path. **Capability decides.**

**Picture plane → ffmpeg**, inside the per-segment re-encode `video_compose._compose` already runs
(`vf_parts`, `video_compose.py:586`). Punch-in, speed ramp, flash, whip, grade, grain and sharpen are
picture operations and are free there — the identical segment measured 4.380s with an eased `zoompan`
punch-in versus 4.185s without. `color_grade.PROFILES` and `face_enhance.PRESETS` are already plain
`-vf` strings and splice straight in. CSS `filter` — `CinematicRenderer`'s only grading hook
(`CinematicRenderer.tsx:88-92`) — cannot express curves, per-channel colorbalance, grain, or a
continuous ramp at all.

**Text plane → Remotion**, as exactly one overlay pass over the finished picture, via
`remotion_caption_burn` → the `TalkingHead` composition (a clean `OffthreadVideo` passthrough +
overlays, no baked look, `TalkingHead.tsx:328-362`). ffmpeg cannot do pop captions: `subtitle_gen`
emits srt/vtt/json with no ASS, and its "karaoke" style is SRT `<b>` on the active word
(`subtitle_gen.py:52-61, :243-264`) — word-synced but visually dead. That gap is unbridgeable in the
filter graph and is the single reason Remotion stays in the pipeline. Verified end to end: the
overlay pass renders at 1080×1920 with word captions and a `hero_title` hook, and the source audio
survives `OffthreadVideo` — the music bed is not lost.

Net: two invocations per reel — ~50s measured at 30s, roughly **20s at the confirmed 10s length**, so under two minutes for a sitting of five.

**Known cost:** the caption pass re-encodes the master a second time at crf 18
(`remotion_caption_burn.py:336`) on top of the crf 23 segment encode — one generation of loss,
visually near-transparent at these bitrates.

`AGENT_GUIDE.md:123`'s hard rule (present both composition runtimes before locking `render_runtime`)
is satisfied **once, at gate 1**, by the `idea-director` presenting the two-plane split as the
recommendation with its measured rationale — not by re-interviewing the operator every batch.

### R7 — One clip ledger: `lib/clip_ledger.py`

`ClipLedger.for_project(project_id)`, mirroring the idiom directors already use for
`CostTracker.for_project` (`skills/pipelines/documentary-montage/compose-director.md:31`). Persists to
`projects/<id>/artifacts/clip_ledger.json`, copying `CostTracker`'s persistence **verbatim, not by
abstraction**: `_locked()` flocking a sibling `.lock` with merge-from-disk inside the critical section
and warn-and-continue when `fcntl` is absent (`tools/cost_tracker.py:669-702`), `_save()` via tmp +
`os.replace` (`:704-728`), `_merge_from_disk()` union-by-id where a terminal state never regresses
(`:872-905`), and a `ClipLedgerCorruptedError` that raises on a malformed file and **never silently
resets** (`:54-57, :730-740`).

It does **not** live in `tools/video/clip_search.py`: that tool declares `determinism = DETERMINISTIC`
(`:61`), `side_effects = []` (`:164`), `tier = ANALYZE` (`:56`) and a docstring promising "The corpus
is loaded fresh on every call. This keeps the tool stateless" (`:27-31`). A `mark_used` op would make
an analysis tool a hidden-state writer. `lib/reel_batch.py` is not created; its function folds into
`ClipLedger.assert_no_reuse()`.

**Granularity is a segment**, keyed `(source, in_seconds, out_seconds)` with `clip_id` alongside;
"whole file" is the interval `[0, duration]`. Two claims collide when they name the same source and
their intervals **overlap** — so one 40s set legitimately yields two non-overlapping 3s cuts.
Selection-time filtering is id-based, because `Corpus.rank_by_text` tests `rec.clip_id in exclude`
(`lib/corpus.py:271-274`) and nothing else — which works only if the corpus **row** is already a
segment. Hence segment rows are a prerequisite, not an optimisation.

Registered in `ARTIFACT_NAMES` (`schemas/artifacts/__init__.py:13-34`) and added to
`SUPPLEMENTARY_ARTIFACTS` (`lib/checkpoint.py:44-49`) — but **the ledger validates itself on every
read**, because `_validate_artifacts_for_stage` only touches dicts passed inside a
`write_checkpoint(artifacts=...)` call (`lib/checkpoint.py:156-169`) and never sees the live side file.

**Partial batch:** reels 1-3 approved and 4-5 abandoned releases reel 4's and 5's claims back to the
pool. **Across sittings:** the ledger is per-project and does **not** persist across projects. A new
sitting starts a new project and may legitimately reuse a clip from a previous batch. This is a
deliberate choice, stated explicitly: cross-sitting memory is a different feature with a different
storage location, and the operator films in bursts, so within-batch uniqueness is the guarantee that
matters for "five reels that don't look like each other".

---

## 4. Architecture

### 4.1 Data flow

```
footage pool ──► footage_library ──► corpus (segment rows, identity_locked=True)
                                          │
tracks ──► beat_grid ──────► audio_analysis (beat grid + speech contamination)
       └─► transcriber ────► word timestamps
                                          │
                            scene-director │ gate 2: cut list + hook, per reel
                                          ▼
                        scene_plan (N reel groups, beat-snapped slots)
                                          │
                        asset-director ────┤ cutaway_gen (text-prompt only)
                                          ▼
                        edit_decisions (spine) + reel_plan (per-reel axes)
                                          │
                        compose-director ──┤ per reel:
                                          │   1. ffmpeg picture plane (cuts, polish, grade)
                                          │   2. Remotion caption overlay (pop captions + hook)
                                          ▼
                        render_report.outputs[] — one entry per reel
```

### 4.2 The batch artifact split

`edit_decisions` **cannot** hold N reels: it carries exactly one `audio.music` object with a single
`asset_id` and exactly one `subtitles` object
(`schemas/artifacts/edit_decisions.schema.json:116-119, :156-171`). Five reels means five tracks and
five subtitle sources. The pipeline-anatomy design's "all N cut lists fit in one `edit_decisions`" is
factually wrong and is rejected.

The `edit` stage therefore emits **two** artifacts:

- **`edit_decisions` — the batch spine.** Shared `renderer_family`, `render_runtime`, grade, effect
  vocabulary, and one flat `cuts[]` whose ids are `<reel_id>-` prefixed, each cut carrying
  `provenance` and its `polish` block. This satisfies `CANONICAL_STAGE_ARTIFACTS["edit"]` and keeps
  the validated cut schema.
- **`reel_plan` — a new registered artifact.** Carries exactly the axes the spine structurally cannot
  hold: per-reel `reel_id`, `music_asset_id`, `subtitle_source`, `hook`, and `cut_ids[]`.

`compose-director` materialises each reel's `edit_decisions` **in memory** by filtering the spine's
cuts on `reel_id` and merging that reel's `reel_plan` entry, then calls `video_compose.execute()`
once per reel at `profile: instagram_reels`, writing one `render_report.outputs[]` entry per reel
with `platform_target`.

### 4.3 Schema changes

Three additive, optional, backward-compatible changes to
`schemas/artifacts/edit_decisions.schema.json`:

| Field | Location | Type | Why typed rather than `metadata` |
|---|---|---|---|
| `provenance` | cut item | enum `["operator_footage","ai_generated"]` | A gate asserts on it per cut; the correspondence invariant is the guarantee |
| `polish` | cut item | object — `punch_in`, `speed_ramp`, `transition_out` | One value per cut; the renderer reads it per cut |
| `identity_lock` | root `metadata` | boolean | Per-project arming switch, not a per-clip label — correctly opaque |

Plus two new registered artifacts: `reel_plan` and `clip_ledger`, both added to `ARTIFACT_NAMES`
(`schemas/artifacts/__init__.py:13-34`); `clip_ledger` also to `SUPPLEMENTARY_ARTIFACTS`
(`lib/checkpoint.py:44-49`).

And on `ClipRecord` (`lib/corpus.py:44-71`): `start_seconds`, `end_seconds`, `sharpness`,
`identity_locked`.

**Not fixed here:** the `cut.type` divergence (**D5**). The schema rejects a key the shipped code
reads and the guide documents. It is recorded as a known defect and left to its own issue rather than
smuggled into this epic — reel-batch does not use `cut.type`.

---

## 5. Cost model

### 5.1 Assumptions (stated so they can be argued with)

1. One sitting = 5 reels **× 10s = 50s = 0.8333 output minutes**, summed across deliverables
   following `skills/pipelines/podcast-repurpose/idea-director.md:93-103`.
2. **One AI cutaway per reel**, trimmed in the edit to roughly 1-2s of screen time. At 10 seconds
   there is room for exactly one; the hero-plus-fillers blend that suited a 30s reel has no room to
   exist.
3. Everything else is $0.00, verified live: `transcriber`, `subtitle_gen`, `audio_energy`,
   `audio_probe`, `scene_detect`, `auto_reframe`, `color_grade`, `face_enhance`, `video_trimmer`,
   `audio_mixer`, `video_compose`, `clip_search`. No `music_gen` line — he supplies the tracks.

### 5.2 The clip floor is the governing constraint

Generators bill per clip against a **minimum duration**, and a 10s reel is short enough that the
floor, not the reel, sets the price. Verified live:

| Tool | Shortest clip | Price at that length | Note |
|---|---|---|---|
| `kling_video` (standard, via fal) | **5s** — enum `["5","10"]`, hard floor | **$0.10** | `tools/video/kling_video.py:75-77, :107-114` |
| `gemini_omni_video` | **3s** — a *hint*; "the model chooses the actual length" | **$0.30** | `_COST_PER_SECOND = 0.10`, `:43, :123-126, :200-201` |
| `minimax_fal_video` | 5s | $0.95 | `minimum: 5`, `:66, :97-98` |
| `seedance_video` (unpinned default) | 5s | $1.52 | `:225-229` |
| `veo_video` | 5s | $2.00 | `:205-207` |
| `wan_video`, `ltx_video_local`, `cogvideo_video`, `hunyuan_video` | local | $0.00 | slow |

Two consequences that did not exist at 30s:

- **The cheapest cutaway is the longer one.** `kling_video` at 5s costs $0.10; `gemini_omni_video` at
  3s costs $0.30. Generate 5s, trim to the 1-2s the reel uses, discard the rest. Paying for unused
  footage is correct here — the alternative costs 3×.
- **`gemini_omni_video` is the only credentialed route that can go below 5s at all**, and its duration
  is a hint rather than a guarantee, so a 10s reel cannot depend on getting exactly 3s back. Trimming
  is mandatory on every route, which makes the floor a pricing question rather than a fit question.

### 5.3 The route choice and the derived caps

Two defensible routes; the operator picks. The manifest ships the **quality** default, consistent with
his stated preference for paying overhead rather than risking worse output, and the gate presents both.

```
quality default — gemini_omni_video @ 3s hint
  per reel   = $0.30
  per batch  = 5 × $0.30                     = $1.50
  per minute = $1.50 / 0.8333                = $1.80
  + 20% regeneration headroom                = $2.16 → round to $2.20

thrift route — kling_video @ 5s, trimmed
  per reel   = $0.10
  per batch  = 5 × $0.10                     = $0.50
  per minute = $0.50 / 0.8333                = $0.60   (exactly in family with the generative rate)
```

Unpinned, the same five-reel batch routes to seedance at $1.52/clip = **$7.60**. That is no longer
above the configured `total_usd: 15.00`, but it is 5× the quality route and 15× the thrift route for
footage that gets trimmed to two seconds. Pinning still matters; it is simply no longer catastrophic.

**Derived manifest values:** `budget_default_usd: 2.00`, `budget_per_output_minute_usd: 2.20`.

**Gate arithmetic for the canonical sitting:**

```
target_minutes         = 5 × 0.1667                                 = 0.8333
default_budget_cap_usd = max($2.00, $2.20 × 0.8333) = max($2.00, $1.83) = $2.00
total_estimated_usd    = 5 × $0.30                                  = $1.50
min_workable_usd       = ceil(1.50 / (1 − 0.10) × 100)/100 + 0.01   = $1.68
tracker.budget_total_usd = max($2.00, $1.68)                        = $2.00
```

$2.00 > $1.68, so a bare "approve" never triggers the below-minimum conversation.

**The flat floor now does the work, and the rate is the guard for larger batches.** At five reels the
$2.00 default wins the `max()`; the rate only binds past ~9 reels (10 reels → cap $3.67 against a
$3.00 estimate and a $3.34 minimum). This is the reverse of the 30s case, where the rate did the work
and the floor was dead weight — and it is why the rate is derived per sitting rather than copied.

### 5.4 Per-reel booking (a deliberate divergence)

The explainer batching rule (`skills/pipelines/explainer/asset-director.md:109`) permits one batched
entry per tool. Reel-batch books **one ledger entry per reel** for cutaway generation instead.

The rule is permissive ("is acceptable"), not mandatory, and a single batch entry has **no honest
terminal state after a mid-batch abort**: `reconcile()` is one-shot and terminal-guarded
(`tools/cost_tracker.py:314`), `budget_spent_usd` counts failed entries as spend (`:186-192`), and
`refund()` on a partly-executed entry erases real billing (`:323-337`). Reconciling at the full
estimate books money that was never spent; reconciling at $0.00 hides money that was. Per-reel is
also the only granularity matching the approval shape — he approves **per reel**.

**One consequence of the shorter reel:** at $0.30 (or $0.10) a per-reel entry now sits **below**
`single_action_approval_usd: 0.50` (`config.yaml:13`), where at 30s it sat above. The
`user_approved=True` flag is therefore no longer forced by the threshold — but
`tests/contracts/test_agent_instruction_integrity.py:105-125` requires **every** `tracker.reserve(...)`
in an asset or compose director to carry it regardless. Carry it. The honest reading is that the
operator does approve each reel at gate 2, so the flag states something true.

Everything free books as two batched `0.0` round-trips.

## 6. CI compliance checklist

Enforcement is **dynamic**: `tests/contracts/test_pipeline_ledger_rollout.py:62-73`,
`test_agent_instruction_integrity.py:222-232`, `test_pipeline_catalog.py:27` and
`test_runtime_presentation_contract.py:72` all glob `pipeline_defs/*.yaml` with no allowlist. A 13th
manifest is swept by four whole-suite tests plus five parametrised cases **the moment it lands**.
Baseline verified green before this work: 70 passed.

### Manifest — `pipeline_defs/reel-batch.yaml`

1. Validates against `schemas/pipelines/pipeline_manifest.schema.json`. `orchestration` is
   `additionalProperties: false` — only `mode`, `skill`, `budget_default_usd`,
   `budget_per_output_minute_usd`, `max_revisions_per_stage`, `max_send_backs`,
   `max_wall_time_minutes`.
2. `category: hybrid` — real footage plus generated b-roll; in the schema enum.
3. A stage literally named **`compose`** (`test_pipeline_ledger_rollout.py:138`). Not `render`.
4. A stage named **`idea`** or **`proposal`** (`test_runtime_presentation_contract.py:92-95`).
5. Declared stage order equals `get_pipeline_stages()`; every `human_approval_default` resolves
   identically (`test_pipeline_catalog.py:47-75`).
6. **Compose criterion**, verbatim on the `compose` stage:
   > `Schema-valid cost_log with every entry in a terminal state (completed/failed/refunded) and totals matching what the run actually spent`
7. **Paid-stage criterion**, verbatim, on a stage **strictly before** `compose` — here `assets`:
   > `Schema-valid cost_log persisted to projects/<id>/artifacts/cost_log.json with an entry for every paid tool call made in this stage`
8. `required_skills` lists the pipeline's own directors under `pipelines/reel-batch/…` and includes
   `meta/checkpoint-protocol` and `meta/reviewer`.

### Skillset — `skills/pipelines/reel-batch/*.md`

9. **Exactly ONE** own director carries the gate marker — asserted twice, the second time as a plain
   substring match over the whole file (`test_pipeline_ledger_rollout.py:178-188`;
   `test_agent_instruction_integrity.py:382-391`). **Merely mentioning either phrase in
   cross-reference prose in a second director fails the pipeline.** Heading text must *end with*
   `Compute Budget And Seed The Cost Ledger` or `On Approval — Arm the Tracker` (em dash U+2014).
   **Designated gate file: `idea-director.md`.**
10. The gate carries the arming formula **verbatim**:
    > `math.ceil(total_estimated_usd / (1 - tracker.reserve_pct) * 100) / 100 + 0.01`
11. The gate contains the literal `min_workable_usd` and must **not** contain `or total_estimated_usd`.
12. **Tree-wide:** `or total_estimated_usd` appears in no `skills/pipelines/**/*.md`.
13. **Tree-wide:** `result.cost_usd or estimated_usd` appears nowhere. Use the two-branch block from
    `skills/pipelines/cinematic/asset-director.md:100-116`.
14. **Tree-wide:** `double-counting against tracker.usable_budget_usd` appears nowhere; the
    replacement must contain `does NOT consume budget` and `Never RESERVE a placeholder`.
15. ≥1 own director carries a heading ending `Ledger Discipline For Every Paid Call` **and**, in the
    same file, the literal `NEVER substitute the estimate on failure`.
16. ≥1 own director carries a heading ending `Ledger Round-Trip For The Render` **and** the literal
    `tracker.estimate("video_compose", "render`.
17. Any `asset-director.md` / `compose-director.md` containing `CostTracker.for_project` must contain
    `tracker.reserve(entry_id, user_approved=True)`, and **every** `tracker.reserve(...)` in it must
    carry `user_approved=True` (`test_agent_instruction_integrity.py:105-125`).
18. **One name per line of spend:** every tool booked with a non-zero third argument must also be
    armed by the gate. So the gate arms **`video_selector`** and the asset director books b-roll under
    `video_selector`, recording the routed provider in the `operation` string.
19. `idea-director.md` contains `render_runtime`, `hyperframes`, and one of
    `present both` / `Present Both` / `PRESENT BOTH` / `render_runtime_selection`.
20. `compose-director.md` contains `render_runtime` and matches `hyperframes|HyperFrames`.
21. `cost_snapshot` may contain only `total_spent_usd`, `total_reserved_usd`, `budget_remaining_usd`,
    `budget_total_usd`.
22. Do **not** restate stranded-entry recovery or corruption handling — point at
    `skills/meta/checkpoint-protocol.md:221-259`.
23. **No lite variant.** Full ceremony even on all-$0 stages; the lightening lever is data (batched
    entries), never a shorter protocol.
24. Sentinel floors `MIN_EPISODE_PIPELINES = 12` and `MIN_PAID_RESERVATIONS = 12` are satisfied by a
    13th pipeline without test edits.

**The estimate/execute rule (from D3):** the gate and the spending director must build the inputs
dict **once** and pass the identical dict to `estimate_cost` and `execute`.

---

## 7. Workstreams

Fifteen issues in four waves. Dependencies are by title.

### Wave 1 — foundations (independent, parallelisable)

| # | Title | Effort |
|---|---|---|
| W1.1 (#36) | Make the beat analyser runnable: pin librosa, add the `beat_grid` tool | M |
| W1.2 (#37) | Segment-level corpus rows: offsets, sharpness, `identity_locked` on `ClipRecord` | M |
| W1.3 (#38) | `lib/clip_ledger.py` — durable, segment-granular used-clip ledger | M |
| W1.4 (#39) | Extend `edit_decisions` with `provenance`, `polish` and the identity arming switch | S |
| W1.5 (#40) | Harden `video_selector` estimate integrity (D1, D2, D3) | M |

### Wave 2 — capability

| # | Title | Depends on | Effort |
|---|---|---|---|
| W2.1 (#41) | `footage_library` — index a local clip pool as corpus segments | #37 | L |
| W2.2 (#42) | `lib/polish_filters.py` — punch-in, speed ramp, flash/whip in the ffmpeg picture plane | #39 | M |
| W2.3 (#43) | `cutaway_gen` — identity-guarded, silent, 9:16, text-prompt-only b-roll | #40 | M |
| W2.4 (#44) | Pop caption preset and 9:16 safe zone for `CaptionOverlay` | — | M |

### Wave 3 — assembly

| # | Title | Depends on | Effort |
|---|---|---|---|
| W3.1 (#45) | Two-plane render: ffmpeg picture pass + Remotion caption overlay (fixes D4, D6) | #42, #44 | L |
| W3.2 (#46) | Add the `reel-batch` manifest and its eight director skills | all of wave 1 and 2, plus #45 | L |
| W3.3 (#47) | `reel_plan` artifact and per-reel compose fan-out | #46 | M |

### Wave 4 — guarantees and surface

| # | Title | Depends on | Effort |
|---|---|---|---|
| W4.1 (#48) | Close the identity chain end-to-end with one contract test file | #39, #43, #45 | M |
| W4.2 (#49) | Behavioural tests: partial-batch reconcile, route-pinned pricing, no-reuse | #46, #47 | M |
| W4.3 (#50) | Backlot board shows a batch as reels, and sync the three pipeline doc tables | #47 | S |

---

## 8. Risks and open questions

### Open questions for the operator

1. **Quality route or thrift route?** `gemini_omni_video` at 3s is **$1.50** a batch;
   `kling_video` at 5s trimmed is **$0.50**. The manifest ships gemini as the default on the stated
   quality-over-cost preference, but that is an inference. The whole spread is one pound fifty, so
   this is a taste decision rather than a budget one.
2. **Is one cutaway per reel right — or none?** Ten seconds is short enough that a 1-2s cutaway is
   ~15-20% of the reel. If the lift should simply carry all ten seconds, the paid surface drops to
   **$0.00** and the pipeline becomes entirely local. Worth deciding before #46 fixes the rate.
3. **Offer local `wan_video` as a free-but-slow lane at the gate?** Free and available; at five clips
   rather than fifteen the runtime objection is much weaker than it was.

### Risks

- **Pool sufficiency — much reduced by the 10s length, still real.** At ~2s per cut a 10s reel is
  roughly **five cuts**, one of which is the AI cutaway, so a five-reel batch needs about **twenty
  distinct usable operator segments** rather than the sixty a 30s reel would have demanded. That is a
  far more achievable pool, and it is the single biggest benefit of the shorter format. Nobody has
  still measured a real pool, so the guarantee can still degrade reels 4 and 5 silently. **#41 must
  report segment count at ingest and the `idea` gate must refuse to plan N reels the pool cannot
  support.**
- **Provenance proves declaration, not detection.** A director that mislabels an operator clip as
  `ai_generated` passes every gate. Mitigated by default-deny at ingest (the whole pool is locked, so
  mislabelling requires actively overriding), not eliminated.
- **The faceswap skill remains one Bash call away.** Out of pipeline scope; doctrine only.
- **Second-generation encode loss** from the caption overlay pass (crf 18 over crf 23).
- **Context cost dwarfs tool cost.** `docs/intent/context-cost.md:41` models the real bill as
  `0.5 × peak × n_calls`, 84-86% from accumulation. A five-reel sitting with five per-reel approvals
  is the maximal-accumulation shape. `cost_snapshot()` will honestly report ~$1.50 of tool spend while
  the session's actual cost is elsewhere. Anyone reading `budget_remaining_usd` as "what this batch
  cost me" is materially wrong.
- **Per-reel cost attribution has no schema carrier.** `operation` is a free string and
  `cost_log.schema.json` is closed at entry level, so `"reel_3 hero cutaway via gemini_omni_video"` is
  the only place reel identity can live, and nothing parses it. A real per-reel readout in Backlot is
  a schema change and belongs to its own issue.
