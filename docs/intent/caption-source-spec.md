# Caption source — specification

**Status:** specified, not started
**Pipeline name:** `reel-batch`
**Feature:** `caption_source`
**Derived from:** the tree at commit **`ff04355`** (2026-09-08), the current `HEAD` of `feat/reel-batch`, read together with the one uncommitted file in the working tree — see §2.0, which replaces an earlier draft's wrong account of that tree. Every claim below carries a `path:line` citation verified against `ff04355` on 2026-09-08, or was verified by execution on this machine. The motivation is external: Instories ships a selector letting a user choose which audio its captions are transcribed from. The motivation is not the argument. The argument is this repository's evidence, and where the external framing suggests a value this repo cannot produce, the value is refused and the refusal is recorded (§3 **R2**). Claims that were asserted during design and are **false** are recorded as refuted rather than quietly dropped (§2.4).

**Sibling epic:** `docs/intent/animation-preset-spec.md` edits four of the same files. The binding shared-surface contract is §1.4 and the ordering ruling is §7; neither spec is safe to implement without reading both.

---

## 1. Confirmed intent

The audio reel-batch transcribes its captions from is chosen in exactly one place: a hardcoded Python fence inside a markdown director skill (`skills/pipelines/reel-batch/script-director.md:82-88`). No artifact declares it, no schema types it, no gate asserts it. The intent is to make that choice an explicit, per-reel, typed, gate-checkable declaration — and to be exact about which failures that does and does not close.

| | |
|---|---|
| **Outcome** | Every reel declares which audio its captions came from, in a typed property a validator and a gate can read |
| **User** | The operator at G5, and any reviewer holding a finished sitting who has to tell a transcript from a hallucination |
| **Why now** | The transcription intent lives only in prose whose own citations have already drifted four ways on this exact path (**D4**), while the transcript on disk now records what was *done* (`tools/analysis/transcriber.py:264`, shipped in `b06a035`) with nothing anywhere recording what was *intended* |
| **Success** | A reel whose declared source is not a source this repo can produce fails `validate_artifact`; a track transcribed against its declared kind's wrong VAD setting fails at G2; a reel that reaches `edit` with no declaration fails at G5 |
| **Constraints** | Free-first (`skills/pipelines/reel-batch/executive-producer.md:51-52`). Additive, optional, backward-compatible schema change only. No new artifact. The field records; it never selects (**R5**) |
| **Approval shape** | Nothing new is put to the operator. reel-batch's three gates are fixed by decision #7 (`docs/decision-log.md:15`) and this spec does not reopen them |

### 1.1 The failure ledger — what can go wrong with the caption audio, and what this field does about it

Seven failure modes, each named by what the operator sees in a finished reel. Six get a verdict of "nothing" or "not reachable". That count is the honest one, and the spec is written around it rather than against it.

| # | Failure | What the reel looks like | Verdict |
|---|---|---|---|
| **F1** | VAD strips sung vocals off a correctly-targeted music bed | 2-3 caption words, or none; no hook line buildable | **Not closed.** The declaration makes the pairing assertable at G2 (**R7a**); it does not change what the VAD does |
| **F2** | The footage's own audio is transcribed | Caption words invented over plate clangs | **Not reachable.** `tools/video/footage_library.py:323` passes `"transcribe": False` for the whole pool |
| **F3** | An instrumental track with no vocal | Invented low-probability words, or a dead reel | **Not closed here.** `none` is refused (**R2**); the step-7 ladder's last rung still rejects the reel (`script-director.md:364`) |
| **F4** | Right words, wrong window | A caption starting mid-sentence | **Nothing.** Window selection is `script-director.md:273-306`, gated at G3 |
| **F5** | A reel captioned from another reel's track | Plausible captions that do not match the bed | **Nothing.** That is `track_id`, and the gate/schema disagreement about it is **D5** |
| **F6** | VAD-off hallucinations counted as speech by the beat grid | Flashes hung on nothing audible | **Nothing.** `beat_grid` reads no confidence at all (`tools/analysis/beat_grid.py:463-467`, inside `_load_words` at `:428`) |
| **F7** | Two transcripts of one track collide on one filename | An unreproducible transcript | **Nothing.** That is **D1**, and §3 **R3** explains why the surviving G2 assertion is immune to it |

**F1, in full, because it is the failure the feature will be mis-sold on.** Measured in the director itself: `"small"` with the VAD on returned 10 and 11 words on two operator tracks; `"medium"` with `vad_filter: False` returned 282 and 319 on the same audio (`script-director.md:104-105`). The audio source was *already* the music track and had been since the pipeline shipped. The loss was an orthogonal boolean. What the declaration buys is a pairing a reviewer can assert — a reel declaring `music_bed` whose track was transcribed with the VAD on is a contradiction the gate can name — and that only works because the transcript now records `vad_filter` (`transcriber.py:264`, shipped in `b06a035`). Conceded here, refuted in §2.4, and repeated as a risk in §8.

### 1.2 What "checkable" means here, precisely

Three assertions become possible that are impossible today. They are listed with the mechanism that enforces each, because two of the three are prose and saying otherwise would be a lie.

1. **The declared source is one this repo can produce.** Enforced by `jsonschema`, at the `edit` checkpoint write (`lib/checkpoint.py:158-159` skips any name not in `ARTIFACT_NAMES`; `:165` is the `validate_artifact` call). This is the only machine check the feature adds.
2. **Every reel carries a declaration.** Enforced by a G5 reviewer bullet, not by the schema — the property stays optional, because `required` is a narrowing and four shipped artifacts would fail it (§4.3).
3. **The declared kind and the transcript agree on `vad_filter`.** Enforced by a G2 reviewer bullet reading the transcript file named by `script.metadata.tracks[].transcript_path` (`script-director.md:393`).

### 1.3 Out of scope

- The sung-vocals VAD fix itself — landed on a separate axis; this composes with it (§2.4).
- The `Explainer.tsx` hero_title prop-forwarding inconsistency — recorded in the sibling `animation_preset` spec's baseline as its **D9**, not here.
- The caption **look** — motion, typography, layout, `preset`, `animation_preset`, `safe_zone`, `words_per_page`. Script owns the transcript, `edit` owns the style, `compose` owns the burn (`script-director.md:12-14`). This spec touches none of the second or third, and shares no field with the sibling epic (§1.4).
- A b-roll or cutaway suggestion pass.
- Identity lock, `lib/clip_ledger.py`, and the batch look.
- Any paid dependency, and any change letting `caption_source` select a transcription provider (**R8**).
- Stem separation, and therefore a `speech_stem` member (**R2**).
- Captionless reels — the `none` member and every consumer it would need (**R2**, and §8 open question 1).
- Making `track_id` required on the reel_plan entry (**D5**) — non-monotone; its own issue.
- The transcript filename collision (**D1**) — its own issue; **R3** shows the surviving assertion does not depend on it.
- Re-anchoring `script-director.md`'s citations into `tools/video/remotion_caption_burn.py` (**D4(c)**) — the sibling epic is still inserting lines above them; see §2.3 **D4** for why a sweep run now ships stale.

### 1.4 The shared-surface contract with `docs/intent/animation-preset-spec.md` (binding)

Both epics widen the same per-reel artifact and edit the same four files. Neither spec's §7 could see the other when it was drafted, and a hand-enumerated gate sentence is not a file two branches can edit independently. This section is binding on both epics and is written identically in both specs.

**The five shared sites.**

| Site | This spec | `animation-preset-spec.md` |
|---|---|---|
| `schemas/artifacts/reel_plan.schema.json`, `reels.items.properties` | W1.1 adds `caption_source` | W2.1 adds `animation_preset` |
| `tests/lib/test_reel_plan.py`, the `_plan()` fixture at `:55` | §6.4-6.9, six tests | its §6.21, three tests |
| `skills/pipelines/reel-batch/edit-director.md:358-372` (the emission fence) | W2.2 | its W2.1 |
| `skills/pipelines/reel-batch/executive-producer.md:221-224` (G5's key list) | W2.3 | its W3.1 |
| `pipeline_defs/reel-batch.yaml` `success_criteria` | `script` `:111-114`, `edit` `:195` | `compose` `:229-232` |

**Rule 1 — one commit per epic for the schema widening.** Each epic's edit to `reel_plan.schema.json` is a single commit that touches the schema and its tests and nothing else. The second epic to reach the file **rebases** onto the first; it does not merge, and it does not resolve the two-line conflict by dropping the other epic's property. *Rejected:* a shared "widening" commit owned by neither epic — it belongs to no issue, no gate and no test, and it is exactly the artifact that lands declared-but-uncarried.

**Rule 2 — `_plan()` is not modified.** The fixture at `tests/lib/test_reel_plan.py:55` carries neither `caption_source` nor `animation_preset`, and neither epic adds one to it. Each test that needs a declaration sets it **on a copy** — `plan = _plan(); for r in plan["reels"]: r["caption_source"] = "music_bed"` — the idiom the file already uses at `:131-135`. Two reasons: `test_reel_plan_is_a_registered_artifact` (`:99-101`) is the pre-change-artifact pin for *both* features and stops being one the moment the fixture carries either property; and a fixture mutated by two branches is a merge conflict in the one file both epics' tests import.

**Rule 3 — one `materialise`-is-untouched test, parametrised, not two.** This spec's §6.9 and the sibling's §6.23 reached opposite conclusions from identical evidence (`materialise` reads four entry keys and copies no others — `lib/reel_plan.py:52`, `:55`, `:61-65`). Reconciled: **one** test asserting that `materialise()`'s output is byte-identical with and without the per-entry property, parametrised over the property names. The first epic to land writes it with one parameter; the second **adds its name to the parametrisation** rather than adding a second test. A reviewer of the second PR must not read the first's test as violating the second's checklist.

**Rule 4 — one G5 landing order.** `executive-producer.md:221-224` is a single hand-enumerated sentence. The epic that lands second appends its key to the sentence the first left, and re-reads it before editing. Whichever lands first also adds `audio_offset_seconds` (**D9**); the second must check whether that has already happened rather than adding it twice.

**Rule 5 — the decision-log number is assigned at merge.** `docs/decision-log.md` ends at `| 11 |` (`:19`). Both epics drafted their row as `| 12 |`. This spec's row is **#12 if it lands first and #13 otherwise**, dated **2026-09-08** (the date of `ff04355` and `b06a035`); the sibling's row takes the other number. See the Decision-log row section at the end, and §7 for the ordering that decides it.

**Rule 6 — the sibling's remaining waves land first, and this epic depends on none of its result keys.** The ordering argument is in §7. Two consequences bind here: (a) the sibling's Wave 1 is already committed as `ff04355`, and its remaining work includes a **W1.4** that finishes the burn tool's echo contract (`degraded` on the Remotion path, `requested_animation_preset` on the fallback) — lines inserted around `tools/video/remotion_caption_burn.py:742` and `:758-761`, i.e. *above* `LOW_CONFIDENCE` at `:767`, which is why **D4(c)** is not re-anchored here; (b) nothing in this spec reads `burn.data` at all — `caption_source` never reaches the renderer (§4.3) — so this epic is unaffected by whether that contract is finished, and must not be scheduled as if it were.

---

## 2. Verified baseline

### 2.0 The baseline is `ff04355`, and two of this spec's premises are already committed

An earlier draft of this spec said *"`git status --short` shows seven modified, uncommitted files, of which two matter here."* That is **false** and is corrected here rather than deleted, because two of its rulings were reasoned from it.

The verified state on 2026-09-08:

- **`ff04355`** — *"feat(captions): motion was fused into preset, and 'no animation' was unreachable"* — is `HEAD`. It landed the sibling epic's entire Wave 1: `ANIMATION_PRESETS = ("none", "fade", "pop")` at `tools/video/remotion_caption_burn.py:80`, the enum at `:135`, the `_validate_look` branch at `:600-603`, and the renderer changes. It added roughly 28 lines to that file, moving **every** symbol below `:80`: `PRESETS` is now at `:581`, `_validate_look` at `:590`, `_render_remotion` at `:331`, `_render_ffmpeg` at `:483`, `LOW_CONFIDENCE` at `:767`, `_confidence_stats` at `:770`. This spec cites that file by symbol wherever it must cite it at all.
- **`b06a035`** — *"fix(transcriber): the VAD setting keyed idempotency but never reached the transcript"* — landed `"vad_filter": vad_filter` in `result_data` at `tools/analysis/transcriber.py:264`, with a comment at `:258-263` recording exactly why: two transcripts of one track, one VAD-stripped and one whole, were indistinguishable after the fact. `tests/tools/test_transcriber_device_selection.py:177-188` asserts the value round-trips into the written JSON for both `True` and `False`.
- **The working tree carries exactly one modified file:** `skills/pipelines/reel-batch/script-director.md`, `+27 −1`. The change is unrelated to captions-source: it extends a reel's last window boundary to the end of the word the line finishes on, replacing `HEAD`'s `:276` with a new `:276-302`. **Every citation into that file at or below `:276` is therefore +26 against `HEAD`.** All `script-director.md` line numbers in this spec are against the **working tree**, and **W2.1 must be authored after that change is committed or discarded** — if it is discarded, nine of this spec's citations rot at once (`:303-306`, `:313-340`, `:342-368`, `:355-357`, `:364`, `:372-374`, `:393`, `:404-412`, `:457`). Citations above `:276` — `:12-14`, `:26-29`, `:37-40`, `:56-58`, `:65-68`, `:73`, `:82-94`, `:101-114`, `:187-194` — are stable either way and were each re-verified.

**Consequence:** the defect an earlier draft filed as its highest-value finding — "the transcript does not record the setting that shapes it" — is **fixed and committed**. It is not this spec's work and is not claimed as such. What remains of it is `output_schema` (**D2**).

### 2.1 What already exists and is reused

| Capability | Where | Reused how |
|---|---|---|
| Local word-level transcription, $0.00 | `tools/analysis/transcriber.py:29`; `network_required=False` at `:96` | Unchanged. The field describes the run; it does not change it |
| The record of how a transcript was made | `transcriber.py:257` (`model_size`) and `:264` (`vad_filter`, `b06a035`), both written to disk at `:271-272` and returned as `artifacts[0]` at `:277` | The measurement G2 compares the declaration against |
| The tool's own statement that the right VAD setting depends on the kind of audio | `transcriber.py:65-75` — *"Set False for SUNG vocals under a music bed … fatal for reel-batch"* | The dependency `caption_source` finally names |
| The transcript's address, per track | `script-director.md:90` (`tx.artifacts[0]`), carried at `:393` as `tracks[].transcript_path` | The chain `reel_plan.track_id → tracks[].transcript_path → transcript.vad_filter` that makes G2's bullet performable |
| A typed, closed, per-reel artifact | `schemas/artifacts/reel_plan.schema.json:62` (entry closed), `:67` (root closed) | The typed home |
| The exact carry-forward precedent | `reel_plan.schema.json:50-52` — `caption_confidence`, *"Carried verbatim from `script.metadata.reels[].caption_confidence`"* | The channel `caption_source` copies, verbatim, including the direct-subscript spelling at `edit-director.md:371` |
| Single-point validation, already on for `reel_plan` | `schemas/artifacts/__init__.py:35` (registered), `lib/checkpoint.py:158-159`, `:165` | No registration step; the widening is live the moment the schema lands |
| Gates that already enumerate reel_plan keys by hand | `executive-producer.md:221-224` (G5), `:196-202` (G2) | Each gains one name and one bullet — the readers that make the field non-decorative |
| The reel_plan fixture and its test file | `tests/lib/test_reel_plan.py:55` (`_plan()`), acceptance at `:99-101`, rejection idiom at `:131-135`, per-reel parametrised pin at `:291-292` | Extended in place, on copies (§1.4 Rule 2). No new fixture is minted |
| The house schema-widening template | `tests/lib/test_edit_decisions_schema.py:67` (pre-change artifact still validates), `:73` (required set pinned), `:84`/`:91` (enum accepts / enum rejects) | Copied as the shape, into the reel_plan file |
| A shipped test that already documents **D1** | `tests/tools/test_transcriber_device_selection.py:171-173` — *"Both calls share `input_path`, so both write `tmp_path/track_transcript.json` and the second overwrites the first"* | Cited as evidence, not extended; the collision is left to its own issue |

### 2.2 What is missing — the actual work

1. **The caption audio source is declared nowhere.** `script-director.md:82-88` passes `track` to `Transcriber().execute`; the brief binding is prose at `:56-58` (*"`path` is what you hand `transcriber` and `beat_grid`"*), and `:80` is a placeholder literal inside the fence. A repo-wide search for `caption_source`, `transcribe_from` and `source_audio` returns **no hit anywhere in the tree** — re-run and confirmed on `ff04355`.
2. **The artifact that names the audio does not classify it.** `brief.metadata.tracks[]` is `{track_id, path}` (`skills/pipelines/reel-batch/idea-director.md:258-263`, documented at `:288-289`). There is no field to widen; the property is genuinely new.
3. **The VAD ruling is stated as an unqualified constant.** *"**Reel-batch passes `False`, always.**"* (`script-director.md:101`). It is correct for every track this pipeline has ever carried, and nothing in any artifact says which kind of track that ruling was made for.
4. **`script.metadata` cannot host an enforceable declaration.** `schemas/artifacts/script.schema.json:101` is `"metadata": { "type": "object" }` under a root closed at `:103`. `jsonschema` never descends into it; the director says so itself at `:372-374`.
5. **No gate, schema or contract test records or asserts which audio was transcribed.** G2 asserts existence only — *"One beat grid AND one word-level transcript per track?"* (`executive-producer.md:197`). G5 enumerates nine entry keys and names no audio source (`:221-224`). G6 checks geometry, audio stream and safe zone (`:230-235`).
6. **`transcriber.output_schema` under-declares its own output.** It declares four keys (`transcriber.py:81-89`) against the nine `result_data` emits (`:252-268`). **D2.**

### 2.3 Defects found in shipped code (pre-existing, not caused by this work)

- **D1 — Two transcripts of one track collide on one filename.** `output_path = output_dir / f"{input_path.stem}_transcript.json"` (`transcriber.py:271`). `model_size` and `vad_filter` are both in `idempotency_key_fields` (`:101`) and neither reaches the path, so the step-7 ladder's rung 1 — *"Re-transcribe the track at a larger `model_size`"* (`script-director.md:355-357`) — silently overwrites the transcript the batch was planned against. Verified by execution, and independently documented in a shipped test's own comment (`tests/tools/test_transcriber_device_selection.py:171-173`). **Not fixed here** (§1.3); **R3** shows why the G2 assertion is immune to it.
- **D2 — `output_schema` declares four of nine emitted keys.** `transcriber.py:81-89` lists `segments`, `word_timestamps`, `language`, `duration_seconds`; `result_data` at `:252-268` also emits `model_size`, `vad_filter`, `device`, `compute_type`, `gpu_fallback_reason`. Nothing validates `output_schema` — it is declared at `tools/base_tool.py:256` and read only into a summary dict at `:349` — so this is a documentation defect, not an enforcement one. **Fixed here** (W1.2), as documentation, and pinned so it cannot drift again.
- **D3 — `script-director`'s own account of the transcript payload is stale as of `b06a035`.** `:90` cites `transcriber.py:264, :270` for the written path (now `:271`, returned at `:277`), and `:93` cites `:252-261` for a payload that runs `:252-268`, listing it as *"`model_size` / `device` / `compute_type` / `gpu_fallback_reason`"* (`:93-94`) — omitting the `vad_filter` key the tool now writes, which is the exact key **R7a**'s gate bullet reads. **Fixed here** (W2.1), because W2.1 edits that paragraph.
- **D4 — Stale citations on this path, in four directions.**
  (a) `script-director.md:73` and `:457` cite `beat_grid.py:320` for the `if words else None` speech-report gate; the gate is at `beat_grid.py:355`, and `:320` is blank.
  (b) `script-director.md:27` cites `beat_grid.py:232-233` for `BeatGrid.estimate_cost`; those lines are `output_schema` entries and the method is `:262-263`.
  (c) `script-director.md`'s citations into `tools/video/remotion_caption_burn.py` are all stale by ~28 lines since `ff04355`: `:38` cites `:240-242` for the no-stem-separation comment (actual `:263-266`); `:344-345` cites `:243-244` for `probability` → `confidence` (actual `:267-268`); `:346-347` cites `:651-652` / `:655-666` for `LOW_CONFIDENCE` and the confidence report (actual `LOW_CONFIDENCE` at `:767`, `_confidence_stats` at `:770`).
  (d) `executive-producer.md:198` — inside the exact G2 block **W2.3** rewrites — cites `tools/analysis/beat_grid.py:449` for "speech contamination measured per track"; `:449` is `shadowed = str(inputs["transcript_path"]) …`. The measurement is `_speech_report` at `beat_grid.py:571`, called at `:355`.
  All four verified. **(a), (b) and (d) fixed here** (W2.1, W2.3) — stable anchors in paragraphs this work already edits. **(c) not fixed:** the sibling epic's remaining **W1.4** inserts lines at `remotion_caption_burn.py:742` and `:758-761`, above every symbol (c) would re-anchor to, so a sweep written now is stale on arrival. The verified current positions are recorded above so the next person does not re-derive them, and the sweep belongs to an issue that runs *after* the sibling's Wave 1 remainder — note that the sibling's own citation sweep (its W3.3) covers `edit-director.md`, `compose-director.md` and `executive-producer.md` and **not** `script-director.md`, so this is genuinely unowned and needs filing.
- **D5 — The gate requires a field the schema does not.** G5 requires `track_id` on every reel_plan entry (`executive-producer.md:221-222`); `reel_plan.schema.json:15` omits it from `required` (which is `["reel_id", "music_asset_id", "subtitle_source", "hook", "cut_ids"]`). A plan with no `track_id` is schema-valid and gate-failing. It matters here because G2's assertion resolves a reel's transcript through `track_id`. **Not fixed** — making it required is non-monotone.
- **D6 — `source_media_review`'s transcription helper reads a key the transcriber never emits.** `lib/source_media_review.py:225` reads `result.data.get("text", "")`; `result_data` (`transcriber.py:252-268`) has no top-level `text` — it exists only per segment. The whisper pass runs and its result is discarded. **Not reachable from reel-batch**: `footage_library.py:318-325` passes `"transcribe": False`. Live for any caller leaving `want_transcript = context.get("transcribe", True)` (`source_media_review.py:270`). **Not fixed.**
- **D7 — Three call sites, three transcriber configurations, none declared.** `script-director.md:84-86` (`medium` / `False`); `tools/analysis/video_analyzer.py:332-343` (`base` at `:334`, `vad_filter` left at the `True` default); `lib/source_media_review.py:223` (all defaults). The coupling is invisible repo-wide, not only in reel-batch. **Not fixed** beyond reel-batch's own path.
- **D8 — Manifest artifact lists are inert.** `required_artifacts_in` / `optional_artifacts_in` are declared only in `schemas/pipelines/pipeline_manifest.schema.json:85, :90` and read by no Python; `_enforce_stage_prerequisites` (`lib/checkpoint.py:376`) checks predecessor checkpoint existence, validity, identity match, completion and approval — never artifact presence. `compose-director.md:60` already documents the resulting lie about `reel_plan`. Recorded so no workstream proposes a manifest list as a gate.
- **D9 — G5 enumerates nine of the ten entry keys `edit-director` authors.** `edit-director.md:358-372` writes ten: `reel_id`, `track_id`, `music_asset_id`, `subtitle_source`, `subtitle_srt_source`, `audio_offset_seconds` (`:367`), `hook`, `cut_ids`, `corrections`, `caption_confidence`. G5's key list (`executive-producer.md:221-224`) names nine — **`audio_offset_seconds` is authored and never gate-checked** — and the director's own per-reel axes list repeats the omission (`:43-45`). A reel missing it opens on the wrong seconds of its bed; the schema types it as optional (`reel_plan.schema.json:31-35`) and its own comment at `edit-director.md:364-366` says a batch cut from one track then opens five times on the same audio, none of them the seconds the captions match. **Fixed here** in W2.3, as one word in the sentence this work already rewrites — *unless the sibling epic has already added it under §1.4 Rule 4*, in which case W2.3 adds only `caption_source`.

### 2.4 Claims this spec refutes

Seven, including two the shared research brief asserted and two this spec's own drafts asserted.

1. **"A declared caption source would have prevented the sung-vocals bug."** False. reel-batch has transcribed the music track since it shipped; the operator's audio is *"music with a spoken motivational voice baked into the track"* (`docs/intent/reel-batch-spec.md:16-17`), and there is no stem separation anywhere in the repo (`script-director.md:37-40`). What emptied the captions was `vad_filter`, which the tool's schema already documents correctly (`transcriber.py:65-75`) and the director already sets correctly (`:86`). Naming the audio does not change what the VAD does to it.
2. **"The four candidate values `{speech_stem, video_sound, music_bed, none}` are the right set."** False. Three have no producer in this tree and one is unreachable without work this spec puts out of scope. **R2** kills them individually, with evidence and re-entry conditions.
3. **"The two-plane demo proves two kinds of caption audio already flow through `tracks[]`."** False. `scripts/reel_batch_two_plane_demo.py` never transcribes anything: its caption words are a hardcoded `LINE` at `:71-74`, whose comment says *"hard-coded here so the demo has no ASR dependency"*, and `DEFAULT_TRACKS` (`:85-91`) is five audio files borrowed from two unrelated projects so five reels have five beds. A render demo's file picks are not a pipeline producer. This claim was load-bearing for a `voice_over` member and its withdrawal is why that member is refused.
4. **"The script artifact carries per-reel `caption.segments` and `caption_confidence`."** True of instances, false of contracts. `script.schema.json` declares neither; the root is closed at `:103` and the only open door is `:101`. Anything declared in `script.metadata` is invisible to every validator, at every stage.
5. **"The transcript does not record `vad_filter`."** True at `c7d1285`, false since `b06a035` (`transcriber.py:264`, test at `tests/tools/test_transcriber_device_selection.py:177-188`). Corrected in place rather than deleted, because the design that assumed it is the design this spec replaces.
6. **Inherited from the shared brief, and corrected: "`position` appears to be ignored by the hero_title branch."** False. The branch does not forward it (`remotion-composer/src/TalkingHead.tsx:227-235`), but `PositionedOverlay` resolves `overlay.position || "lower_third"` and applies `POSITION_STYLES` to the wrapping div, and `upper_third` is a real preset. Recorded here only because it came from the same brief; it belongs to the sibling spec (its §2.4(b)) and is not this spec's subject.
7. **This spec's own earlier claim: "the baseline is a working tree with seven modified files, two of which matter here."** False, and it is the claim that most changed the document. The tree has **one** modified file, and it is the one the earlier draft did not mention; both premises the draft called "uncommitted" are committed, in `b06a035` and `ff04355`. §2.0 carries the corrected account, and the corrections it forces — a `+26` offset on nine citations, a `ff04355` re-derivation of every `remotion_caption_burn.py` anchor, and the removal of "fixed here" from the transcriber's `vad_filter` — are made in place.

---

## 3. Rulings

Eight binding rulings.

### R1 — The field is `caption_source`, a noun naming which audio

It collides with nothing on the pipeline path — `caption_source` returns zero hits repo-wide — and it sits beside the two properties it most resembles on the same object: `subtitle_source` and `subtitle_srt_source` (`reel_plan.schema.json:26-30`).

`audio_source` is **rejected on collision**: it is already in use with an unrelated meaning in the avatar tools (`tools/avatar/kling_avatar.py:210`, `tools/avatar/kling_lip_sync.py:330`, three sites each) and in two further files, `tools/analysis/video_analyzer.py` and `tools/video/green_screen_composite.py`. `transcribe_from` is **rejected on convention**: every property on the reel_plan entry is a noun or noun phrase — `reel_id`, `music_asset_id`, `subtitle_source`, `audio_offset_seconds`, `cut_ids`, `caption_confidence` — and none is a verb phrase.

### R2 — One member ships: `music_bed`. Four candidates are named, refused, and given re-entry conditions

An enum member with no producer is a guard bypassed by omission wearing a new coat: `validate_artifact` would **accept** the value and only prose would refuse it.

| Candidate | Verdict | Evidence |
|---|---|---|
| `music_bed` | **Ships** | The only behaviour reel-batch has ever had. `script-director.md:82-88` transcribes the track; `:101-106` records the measured VAD behaviour on operator music tracks; the intent is stated in the parent spec at `docs/intent/reel-batch-spec.md:16-17, :20` |
| `voice_over` | **Refused** | No producer. Every reel-batch track is minted at idea as `{track_id, path}` from the operator's audio folder (`idea-director.md:258-263`), and every one of them is music with baked-in vocals. The only artefact ever offered as evidence for a spoken-word track is the two-plane demo, which never transcribes (§2.4.3). **Re-entry:** an operator-supplied spoken track routed through `brief.metadata.tracks[]`, plus the kind→`vad_filter` rule **R5** currently refuses to write |
| `speech_stem` | **Refused** | No stem separation exists anywhere in the tree, asserted independently in three files written without reference to each other: `script-director.md:37-38`, `tools/video/remotion_caption_burn.py:263-266` (the `confidence` comment inside `_segments_to_word_captions`'s per-word branch, `:239`), and `remotion-composer/src/components/CaptionOverlay.tsx:18-22`. **Re-entry:** a stem-separation tool in the registry, granted to the `script` stage |
| `video_sound` | **Refused** | Not a typing problem — a routing one. The pool's audio *is* already typed: `lib/source_media_review.py:296` stores `technical_probe` (declared at `schemas/artifacts/source_media_review.schema.json:27-40`, `audio_codec` at `:35`) and `:319`/`:401-402` fold it into the typed `usable_for` array as `"source audio"`. What does not exist is a path from a pool clip to the transcriber: `footage_library.py:323` passes `"transcribe": False` for the whole pool, and `transcriber` is granted to `script` alone (`pipeline_defs/reel-batch.yaml:96, :101`), which never sees the pool. The caption timeline is also one reel-local window rebased off the track (`script-director.md:313-340`), where pool audio would be ~5 discontiguous cut-local sources. **Re-entry:** that routing path, plus a per-cut caption timeline |
| `none` | **Refused** | Five consumers would have to change, and two operator questions are unanswered (§8). `hook` is required on every entry (`reel_plan.schema.json:15`) and its text is rebased off transcribed words (`script-director.md:303-306`); `asset-director.md:325-326` subscripts `reel["caption"]["segments"]` and then `segs[0]["start"]` unguarded, inside a loop already armed against the cost ledger at `:318-319`; the burn refuses an empty caption list (`remotion_caption_burn.py:690-691`) **before** it reads `overlays` at `:693`, so skipping it also drops the hook card that rides the same pass (`compose-director.md:209-249`); compose's completion and resume rules key on the captioned master existing (`compose-director.md:290-305`) and `outputs[]` may not list the picture intermediate (`:357-359`); G6 asserts one `outputs[]` entry per reel and that captions clear the lower band (`executive-producer.md:231-234`). **Re-entry:** §8 Q1 answered yes, plus a source of operator-authored hook copy — a stage the parent spec has already deferred (`docs/intent/reel-batch-spec.md:52-53`) |

**Rejected: ship the researched four and let three be aspirational.** A one-member enum is smaller than the brief and it is what the tree supports. Its shipped work is threefold and none of it is decoration: it closes the vocabulary, so a director cannot spell the same intent three ways; it makes the four refusals *machine-checkable*, so a reel declaring `none` or `video_sound` fails validation instead of relying on a reviewer to know it is unavailable; and it is the widening point when a producer appears. What it does **not** buy is any per-reel information today — stated plainly in §8 rather than dressed up here.

### R3 — The declaration is the whole property. `vad_filter` and `model_size` stay on the transcription run

`caption_source` is a **string enum**, not an object. The two settings it is checked against are already recorded where they belong: `model_size` at `transcriber.py:257` and `vad_filter` at `:264`, both written to the transcript at `:271-272` and reachable per track through `script.metadata.tracks[].transcript_path` (`script-director.md:393`).

**Rejected: a closed object `{kind, vad_filter, model_size}` on the reel.** Three reasons, in ascending order of severity.

1. It is a per-run value replicated per reel. Decision #9 (`docs/decision-log.md:17`) shipped five reels from five non-overlapping windows of one track, knowingly amending the one-track-per-reel rule (`script-director.md:65-68`). Five entries would carry five copies of one fact, and a closed schema cannot require them equal.
2. Two records that can silently disagree are worse than one. The parent spec's R4 rejects the idempotency key as a record on the grounds that *a cache key is not a record*; a second copy that no validator reconciles is the same defect with a friendlier face.
3. **Carrying `model_size` manufactures false gate failures.** Rung 1 of the confidence ladder re-transcribes a *track* at `large-v3` (`script-director.md:355-357`) and, under **D1**, overwrites the medium transcript at the same path (`transcriber.py:271`). Four reels off that track legitimately declare `medium` while the only file on disk says `large-v3`. A "declaration agrees with the transcript" check on `model_size` fails four correct reels.

`vad_filter` survives as the one thing G2 asserts on precisely because it is the one setting the ladder never touches: the ladder changes `model_size` only (`:355-357`), and `script-director.md:101` fixes `vad_filter` batch-wide. The assertion is therefore immune to **D1** by construction, not by luck, and §8 records that it stops being immune the day a member with a different VAD requirement ships.

**`track_id` is likewise excluded** — it is already declared on the entry (`reel_plan.schema.json:21`) and a second spelling of one identifier is the caption-density failure in miniature, which `edit-director.md:318-320` names in writing.

### R4 — Typed on `reel_plan.reels[]`; authored, unenforced, on `script.metadata.reels[]`; the three-stage gap is stated, not closed

The binding rule, from `docs/intent/reel-batch-spec.md:206-209`, quoted with its full second clause: *"if a value is one-per-cut, or if any gate, reviewer or contract test must assert on it, it is a **typed schema property**. It must live on the cut and never as a side-map in `metadata`, because nothing enforces that such a map covers every cut — and that correspondence invariant is exactly what the identity guarantee needs."* `metadata` stays legitimate for three things only (`:211-213`): opaque runtime hints already read as such, tool-internal telemetry no gate asserts, and pipeline-private scratch.

**Where the decision is made:** only `script`. `transcriber` is granted to that stage and no other (`pipeline_defs/reel-batch.yaml:96, :101`); `scene_plan` and `edit` carry `tools_available: []` (`:126`, `:185`).

**Where it is enforceable:** only `reel_plan`. Its entry is `additionalProperties: false` (`reel_plan.schema.json:62`) with no per-entry `metadata` (the only `metadata` is at the artifact root, `:65`), so at reel granularity there is no side-map option even if the rule allowed one. `backlot/state.py:513-514` records an independent author hitting the same wall from the other side: *"`reel_plan` entries are `additionalProperties: false`, so the join between a reel and its finished file cannot be stored in the artifact."*

**The gap is three stages wide and is stated.** `reel_plan` is produced at `edit` (`pipeline_defs/reel-batch.yaml:182-184`), so the first moment `caption_source` is schema-enforced is three stages after the transcription it describes. Between `script` and `edit` the value is carried by director discipline plus G2's reviewer bullet. That is already true of `caption_confidence` and `corrections`, so it is the pipeline's existing practice rather than a new compromise — and it is named again in §8.

**The `script.metadata` copy is not claimed as an R4-permitted metadata use.** It is an authoring buffer in an artifact whose per-reel structure is untyped by an existing ruling (`script-director.md:372-374`), and **no gate asserts on it**: G2's bullet reads the transcript file, G5's reads the typed `reel_plan` entry and compares it to the buffer. The R4 obligation is discharged at the contract site. Naming the exemption is cheaper than pretending the rule covers it.

**Rejected: type it on `script` instead.** `script.schema.json` is the shared artifact of thirteen pipelines and its vocabulary is `sections[]` / `text` / `source_ref`. reel-batch already solved per-reel typing by minting its own artifact.

**Rejected: declare it at `idea` on `brief.metadata.tracks[]`.** The strongest alternative, and it fails on two of three legs. The track inventory is minted there under a human gate (`idea-director.md:258-263`), which is a real advantage; but `brief.metadata` is untyped exactly as `script.metadata` is, so it enforces nothing, and the setting the declaration is checked against is chosen at `script`, not at `idea`. (The third leg — that a per-track declaration is not per-reel — does **not** hold: under the standing rule one track is one reel. It is withdrawn rather than used.)

### R5 — The field records the choice. It never selects it

`script-director.md:101` — *"**Reel-batch passes `False`, always.**"* — stands, unchanged, unqualified.

Making `vad_filter` conditional on a director-authored label is a behaviour change to the VAD policy, and §1.3 puts that out of scope. It is also the regression path back into the bug this feature disclaims: one misclassification of a music-with-baked-vocals track would flip `vad_filter` to `True` on a pipeline whose only real audio kind is music with baked vocals, reproducing a loss measured at 282→10 words (`script-director.md:104-105`). It would additionally invalidate director prose written around VAD-off noise — the hallucination budget at `:108-114`, step 5's hook selection, step 7's ladder, and the contamination numbers the cut-policy ladder branches on at `:187-194`.

Therefore: `caption_source` is written **after** the transcription it describes, from the settings that were used, and no code or prose reads it to choose a setting. The kind→`vad_filter` rule that would replace the constant is named as the re-entry condition for `voice_over` in **R2** and belongs to that issue.

### R6 — Carried by direct subscript. Absence means undeclared, never `music_bed`

The reel_plan entry is built by a literal dict at `edit-director.md:358-372`, where two idioms are already live: `"corrections": sr.get("corrections", {})` at `:370` and `"caption_confidence": sr["caption_confidence"]` at `:371`. `caption_source` takes the **`caption_confidence` spelling** — `"caption_source": sr["caption_source"]`.

Why the strict one: `edit-director.md:19` already documents the consequence and blesses it — *"Step 6 subscripts `sr["hook"]["text"]` and `sr["caption_confidence"]` directly, so a run without `script` raises rather than degrading."* A `.get()` with a `music_bed` default would manufacture a declaration nobody made, on a schema-valid artifact, caught by nothing — a default-deny check on an optional field becoming default-allow, which this repo has already shipped once. A script artifact written before W2.1 lands cannot produce a declaration, and failing loudly at `edit` is the correct outcome: the declaration is not retro-fittable.

**Absence carries no meaning.** The schema property stays optional (§4.3) and a missing `caption_source` is *undeclared*, not `music_bed`. G5 requires presence; the schema does not. That asymmetry is the same shape as **D5** and **D9** and is accepted knowingly here for a reason that does not apply there: with one enum member a default would be a value the operator never chose, on a reel nobody declared.

### R7 — Two gate assertions, and an honest account of what they cannot do

**(a) G2 — after `script`,** two bullets added to `executive-producer.md:196-202`:
> - Every reel names its `caption_source`, and it is a source this tree can produce?
> - For every track, the transcript at `script.metadata.tracks[].transcript_path` records `"vad_filter": false` — read off the file, not assumed from the skill?

The same edit re-anchors **D4(d)**: the block's existing contamination bullet at `:198` cites `beat_grid.py:449`, and the measurement is `_speech_report` at `beat_grid.py:571`, called at `:355`.

**(b) G5 — after `edit`,** `caption_source` is added to the hand-enumerated key list at `executive-producer.md:221-224` — together with `audio_offset_seconds` (**D9**), unless the sibling epic has already added it under §1.4 Rule 4 — plus one bullet:
> - Every reel_plan entry's `caption_source` equals `script.metadata.reels[].caption_source` for the same `reel_id`? If `script` is not in scope at this gate the check fails closed — a carried-verbatim property whose source cannot be produced is an unverified carry, not a pass.

The fail-closed clause exists because `script` is only `optional_artifacts_in` at `edit` (`pipeline_defs/reel-batch.yaml:180-181`) and, per **D8**, that list is inert.

**(c) Honest limits.** These gates enforce consistency between a declaration, a vocabulary and a measurement. They do not detect truth. A director that writes `caption_source: "music_bed"` over an instrumental passage, and gets a transcript full of confident-looking invented words, passes every check added here — the step-7 confidence gate (`script-director.md:342-368`) is what stands between that reel and the export, and this work does not touch it. Provenance proves declaration, not detection, exactly as `docs/intent/reel-batch-spec.md:254-257` records for identity. G2's second bullet is also, today, a check on a batch-wide constant: it can only fail if someone edits the fence, which is a real failure mode and a small one.

### R8 — `caption_source` names audio, never a provider

`transcriber` is local faster-whisper (`transcriber.py:29`, `network_required=False` at `:96`) and the script stage books nothing (`script-director.md:26-29`). The repo carries two API-runtime alternates advertising themselves as drop-in: `tools/analysis/azure_stt.py:184-185` (`fallback = "transcriber"`, `fallback_tools = ["transcriber"]`) and `tools/analysis/dashscope_asr.py:52-53`. Neither exposes `vad_filter` — `azure_stt`'s `idempotency_key_fields` is `["input_path", "language", "diarize"]` (`:182`). If the field were ever allowed to imply a provider, a substitution would reopen the cost gate and silently drop the setting this pipeline's captions depend on, in one move. `AGENT_GUIDE.md:169-179` already forbids executing a fallback tool without approval; this ruling makes the field structurally incapable of requesting one.

**Rejected: a `provider` key alongside the enum.** Provider selection is governed by the announce-before-execution contract (`AGENT_GUIDE.md:94-102`) and the cost ledger. Keeping the two vocabularies apart is what keeps free-first checkable.

---

## 4. Architecture

### 4.1 Data flow

```
  idea ──► brief.metadata.tracks[]  {track_id, path}                    gate 1
             │                       (no kind, no classification — §2.2.2)
             ▼
  script ──► Transcriber().execute({input_path: track,
             │                      model_size: "medium",
             │                      vad_filter: False})     ── unchanged (R5)
             │        │
             │        └──► <stem>_transcript.json   (transcriber.py:271)
             │               model_size  (:257)
             │               vad_filter  (:264, shipped b06a035)   ── the MEASUREMENT
             │
             ├──► script.metadata.tracks[].transcript_path        (:393) — the address
             └──► script.metadata.reels[].caption_source  ◄── NEW, authored, untyped by design (R4)
                        │
                        │   G2: declaration is producible + transcript says vad_filter false  ◄── R7a
                        ▼
  scene_plan ─ passes through untouched ──────────────────────────────── gate 2
                        │
                        ▼
  edit ──► reel_plan.reels[].caption_source     ◄── NEW: TYPED, closed, enforced (R4)
             │   carried by direct subscript, edit-director.md:371 idiom (R6)
             │   validate_artifact @ lib/checkpoint.py:165 (skip test at :158-159)
             │
             │   G5: present on every entry + equals the script copy  ◄── R7b
             ▼
  compose ─► lib/reel_plan.materialise  —  UNCHANGED. Reads four entry keys
             (cut_ids :52/:61, reel_id :55/:65, music_asset_id :62,
              subtitle_source :64). caption_source is not one, by design (R3).
                        │
                        ▼
  publish ────────────────────────────────────────────────────────────── gate 3
```

### 4.2 Two records, one field, and why one is not enough

| | `script.metadata.reels[]` | `reel_plan.reels[]` |
|---|---|---|
| Stage | `script` — the only stage granted `transcriber` (`pipeline_defs/reel-batch.yaml:96, :101`) | `edit` (`:182-184`) |
| Typed? | **No.** `script.schema.json:101` is open under a root closed at `:103` | **Yes.** Entry closed at `reel_plan.schema.json:62`, root at `:67` |
| Enforced by | Nothing. A reviewer reads it at G2. | `validate_artifact` at `lib/checkpoint.py:165`, at the `edit` checkpoint write |
| Failure if wrong | Silent | `CheckpointValidationError` (`lib/checkpoint.py:97`), raised from the `validate_artifact` call at `:165` |
| Why it exists anyway | It is the only record at the moment the decision is acted on, three stages before anything can validate it | It is the only record anything can assert on |

### 4.3 Schema changes

| Field | Location | Type | Why typed rather than `metadata` |
|---|---|---|---|
| `caption_source` | `reel_plan` `reels[]` item | string, `enum: ["music_bed"]`, **optional** | One value per reel and two gates assert on it — R4's dividing rule, both halves. The entry is `additionalProperties: false` (`reel_plan.schema.json:62`) with no per-entry `metadata`, so there is no side-map to hide in even if the rule allowed one |
| `caption_source` | `script` `metadata.reels[]` item | same string, unenforced | **Deliberately untyped**, and deliberately not asserted on. `script.schema.json:101` types nothing under it, and `script-director.md:372-374` already rules that the batch structure lives there. Authoring buffer, not contract (**R4**) |
| the five emitted keys | `transcriber` `output_schema` (`transcriber.py:81-89`) | `model_size`, `vad_filter`, `device`, `compute_type`, `gpu_fallback_reason` | Not an artifact schema and not enforcement: `output_schema` is declared at `tools/base_tool.py:256` and read only into a summary at `:349`. Documentation, fixed in one pass so it is not wrong in four other places (**D2**) |

`required` on the reel item (`reel_plan.schema.json:15`) is **unchanged**. Every reel_plan valid before this change is valid after it, including the four artifacts already on disk (`projects/gym-reels-w36|w37|w37b/artifacts/reel_plan.json`, `projects/reel-batch-board-demo/artifacts/reel_plan.json`, all confirmed present) and the fixture at `tests/lib/test_reel_plan.py:55`.

**Declaring is not carrying, and carrying is not consuming — and this field deliberately stops at carrying.** `materialise` copies a fixed five-name tuple of *spine root* properties down to each reel (`lib/reel_plan.py:81-89`) under a truthiness guard at `:88`, and `batch_look`'s absence from that tuple once materialised five reels with `batch_look: None`, schema-valid, rendered with no grade at all (`:70-75`; recorded at `docs/intent/reel-batch-spec.md:453-457`). `caption_source` is a per-**entry** property, so it never touches that tuple. It also never reaches the renderer: the burn takes word timings and confidences and nothing about their origin (`compose-director.md:228-244`). Its readers are the schema and two gate bullets, and W2.3 is what makes it non-decorative — which is why W2.3 blocks the feature rather than following it (§7).

**Backward compatibility, pre-answered against `docs/PR_REVIEW_GUIDE.md:228-242` and `:395-403`:** one producer (`edit-director`); consumers are `lib/reel_plan.py` (reads four entry keys, untouched), `compose-director` and `publish-director` (read named keys, ignore unknown ones), and `backlot/state.py:523-545` (read-time only, and defensive about the whole artifact by design — `:511-514`); checkpoints need no migration because `reel_plan` is already in `ARTIFACT_NAMES` (`schemas/artifacts/__init__.py:35`); invalid-data coverage is required and specified in §6.

---

## 5. Cost model

**This feature costs $0.00 and cannot cost anything else.**

| Path | Tool | Cost |
|---|---|---|
| Transcription | `transcriber`, local faster-whisper, `network_required=False` (`transcriber.py:96`) | $0.00 |
| Beat grid | `BeatGrid.estimate_cost` returns `0.0` (`beat_grid.py:262-263`) | $0.00 |
| Schema validation | `jsonschema`, in-process | $0.00 |
| Render | untouched — no burn input, no compose branch, no materialise change | $0.00 |

The script stage books nothing today and books nothing after this change (`script-director.md:26-29`). `Transcriber` overrides no `estimate_cost`; its only cost-adjacent override is `estimate_runtime` at `:123`, unchanged.

**The one way this could cost money, and why it cannot.** If the enum were allowed to imply a provider, `azure_stt` and `dashscope_asr` would become reachable from a per-reel artifact field. **R8** forbids it structurally. No line item is added to `cost_log`; no `tracker.reserve(` call appears in any director text this spec touches.

**Wall time, not dollars.** A G2 rejection whose remedy is a re-transcription is a local `medium`-model run inside the 20-minute budget for the whole sitting, indexing and transcription included (`executive-producer.md:280-281`). The real cost is conversation turns at two gates, priced as a risk in §8, not as spend.

**Derived manifest values:** none. `budget_default_usd`, `budget_per_output_minute_usd` and the cutaway valve figures in `pipeline_defs/reel-batch.yaml` are untouched.

---

## 6. CI compliance checklist

No existing test asserts an exhaustive property set on any artifact schema — the two exhaustive `set(...keys()) ==` assertions in the suite (`tests/tools/test_hyperframes_compose.py:321`, `tests/tools/test_documentary_governance.py:119`) are both on tool-registry output. An additive optional property therefore breaks nothing; the CI cost is new tests, not re-baselined ones.

### Schema — `schemas/artifacts/reel_plan.schema.json`

1. `caption_source` added under `reels.items.properties` with `"enum": ["music_bed"]`; `items.additionalProperties` stays `false` (`:62`); root stays `false` (`:67`); `required` (`:15`) **unchanged**. One commit, this file and its tests only (§1.4 Rule 1).
2. Its `description` states that it is carried verbatim from `script.metadata.reels[].caption_source`, matching the idiom `caption_confidence` already uses at `:52`, so the carry contract survives without the spec.
3. No change to `schemas/artifacts/__init__.py` — `reel_plan` is registered at `:35`, and that registration is the whole guard (`lib/checkpoint.py:158-159`). **Do not** add anything to `SUPPLEMENTARY_ARTIFACTS`, which lives at `lib/checkpoint.py:45-51` (**not** in `schemas/artifacts/__init__.py`, as an earlier draft of this checklist implied): its only consumer in the repo is one assertion in `tests/lib/test_clip_ledger.py:245`.

### Acceptance tests — extend `tests/lib/test_reel_plan.py`, reusing `_plan()` at `:55`

Do **not** mint a new fixture or a new module; a second reel_plan fixture is a drift generator. Do **not** modify `_plan()` either — it carries no `caption_confidence`, no `corrections`, no `subtitle_srt_source` and no `audio_offset_seconds`, and it is the pre-change-artifact pin for both epics (§1.4 Rule 2). Every test below sets the property on a copy, in the shape of `:131-135`.

4. `test_a_plan_declaring_music_bed_validates` — a `_plan()` copy with `caption_source: "music_bed"` on every entry passes `validate_artifact("reel_plan", ...)`. Shape: `tests/lib/test_edit_decisions_schema.py:84`.
5. `test_caption_source_rejects_a_source_this_repo_cannot_produce` — parametrised over `["voice_over", "video_sound", "speech_stem", "none", "music bed", "Music_Bed", "", None]`, each rejected. The rejection half is the half a new enum usually skips (`docs/PR_REVIEW_GUIDE.md:395-403`), and the four refused candidates are in this list deliberately: **R2**'s refusals are only real if a validator enforces them. Shape: `test_edit_decisions_schema.py:91`.
6. `test_a_plan_with_no_caption_source_still_validates` — the pre-change artifact, i.e. `_plan()` unmodified. Shape: `test_edit_decisions_schema.py:67`; already implied by `test_reel_plan_is_a_registered_artifact` (`:99-101`), asserted explicitly here.
7. `test_the_required_entry_keys_are_unchanged` — the five names at `reel_plan.schema.json:15` (`reel_id`, `music_asset_id`, `subtitle_source`, `hook`, `cut_ids`). Shape: `test_edit_decisions_schema.py:73`.
8. `test_caption_source_survives_the_edit_checkpoint` — extend `test_five_reel_spine_and_plan_round_trip_through_the_edit_checkpoint` (`:141`) so the declaration passes `write_checkpoint` → `validate_checkpoint`.
9. `test_materialise_ignores_the_per_entry_declaration` — `materialise()` output is identical with and without the property, for every reel. **Parametrised over the property name**, per §1.4 Rule 3: this epic lands it with `caption_source`; the sibling adds `animation_preset` to the same parametrisation rather than writing a second test or deleting this one. This pins **R3**/§4.3: the field reaches no renderer and needs no fifth entry read. Per-`reel_id` parametrisation in the shape of `:291-292`.

### Acceptance test — extend `tests/tools/test_transcriber_device_selection.py`

10. `test_output_schema_declares_every_key_result_data_emits` — run the existing `FakeWhisperModel` harness (`:137-193`, which already monkeypatches `faster_whisper` and `ctranslate2` into `sys.modules` and writes into `tmp_path`, so no audio and no model download) and assert `set(Transcriber.output_schema["properties"]) == set(result.data)`. The equality is exactly the nine keys and is **not** fragile under `diarize=True`: `_apply_diarization` (`transcriber.py:245-248`) mutates `segments` in place before `result_data` is built at `:252`, so it adds no key. Fixes **D2** and prevents its recurrence.
11. `idempotency_key_fields` (`transcriber.py:101`) is **unchanged** — `vad_filter` and `model_size` are already in it, and adding to it would defeat the cache reuse the escalation rung at `script-director.md:355-357` depends on. If a pin is wanted, follow the house membership idiom (`tests/contracts/test_dashscope_tools.py:490-493`, `tests/contracts/test_jimeng_video.py:135-143`), never exact-list equality.

### Manifest — `pipeline_defs/reel-batch.yaml`

12. Only free-text lines change: one `success_criteria` line on `script` (`:111-114`) naming the declared caption source per reel, and the `edit` line at `:195` extended to name it. No new stage key — stage objects are `additionalProperties: false` (`schemas/pipelines/pipeline_manifest.schema.json:151`), the root at `:196`, validated on every load (`lib/pipeline_loader.py:67-68`). The sibling epic edits the `compose` block (`:229-232`) and nothing else in this file.
13. **Do not** add anything to `required_artifacts_in` / `optional_artifacts_in` expecting enforcement (**D8**).
14. The dynamic sweeps re-run the moment the manifest or a director changes: `tests/contracts/test_pipeline_catalog.py`, `test_pipeline_ledger_rollout.py`, `test_agent_instruction_integrity.py`, `test_runtime_presentation_contract.py` all glob `pipeline_defs/*.yaml` with no allowlist.

### Skills — `skills/pipelines/reel-batch/*.md`

15. **Landmine.** No director edited by this work may gain either of the two gate markers defined as `GATE_SEED_MARKER` / `GATE_ARM_MARKER` at `tests/contracts/test_pipeline_ledger_rollout.py:43-44`. Exactly one own director may carry each, asserted as a heading-suffix match at `:178-188` and again as a whole-file substring match at `tests/contracts/test_agent_instruction_integrity.py:382-391` — a cross-reference in prose fails the whole pipeline.
16. No `tracker.reserve(` appears in any example this spec adds; one that did would need `user_approved=True`, enforced by regex over the file text (`test_agent_instruction_integrity.py:116-125`).
17. New fence lines follow the house convention: an input departing from a tool default carries a trailing comment naming the tool file and the line range that establishes the default (`script-director.md:84-86` is the model). This work adds no such input — **R5** — so the convention applies only to the prose.
18. **D3**, **D4(a)(b)** and **D4(d)** are fixed in the paragraphs this work already edits: `script-director.md:90` re-anchored to `transcriber.py:271`/`:277`; `:93-94` re-anchored to `:252-268` and re-listed to include `vad_filter`; `:73` and `:457` re-anchored from `beat_grid.py:320` to `:355`; `:27` re-anchored from `beat_grid.py:232-233` to `:262-263`; `executive-producer.md:198` re-anchored from `beat_grid.py:449` to `_speech_report` at `:571`, called at `:355`. **D4(c)** is left alone and cited by symbol — the sibling's remaining W1.4 inserts lines above every anchor it would move (§1.4 Rule 6), so a sweep run now ships stale; it needs its own issue because the sibling's own citation sweep does not cover `script-director.md`.
19. **Author `script-director.md` only after the working tree's uncommitted window-extension change is committed or discarded** (§2.0). Nine of this spec's citations into that file shift by 26 lines depending on the answer.

### Commands

20. `python -m pytest tests/contracts -q`, `python -m pytest tests/tools -q`, `python -m pytest tests/qa -q`, `python -m py_compile tools/analysis/transcriber.py` — the four the guide names (`docs/PR_REVIEW_GUIDE.md:437-440`), plus `python -m pytest tests/lib -q`, which the guide does not name and which is where every test above lives. Record the green baseline before touching anything; if any cannot be run, say why and what risk remains.

---

## 7. Workstreams

Five issues in two waves. Dependencies are by title. Every item is S except W2.1. A spec that inflated this would be lying about the change it describes.

### Cross-spec ordering (binding — read with §1.4)

**`docs/intent/animation-preset-spec.md`'s remaining waves land first; this epic lands second.** There is no data dependency between the two features — `caption_source` is decided at `script`, `animation_preset` at `edit`, and they share no field — so the ordering is decided on state-of-tree, on four grounds:

1. **The sibling is half-landed and currently inert.** `ff04355` shipped its entire Wave 1: `animation_preset` validates, reaches the props and renders, and *no artifact authors it and no gate reads it*. That is precisely the `batch_look` failure shape both specs cite (`docs/intent/reel-batch-spec.md:453-457`). Leaving it half-landed while a second epic churns the same four files is the higher risk.
2. **This spec has two unanswered operator questions** (§8 Q1/Q2) that could still change its enum membership. The sibling has none open.
3. **This spec's enumeration work is better and should absorb both keys.** W2.2 identifies **five** places `edit-director.md` enumerates the reel_plan entry-key set — `:19`, `:43-45`, `:358-372`, `:378-393`, `:437-440` — where the sibling's W2.1 names two. Going second, W2.2 fixes all five for both properties at once, and W2.3 fixes G5 for both plus **D9**.
4. **W1.2 is fully independent of everything, in both epics.** `transcriber.output_schema` plus its parity test touches no shared file. Land it now, in parallel, ahead of both epics' remaining work.

Two hard prerequisites before W2.1 is authored: the working tree's uncommitted `script-director.md` change is committed or discarded (§2.0, §6.19), and the sibling's G5 edit is checked for whether it already added `audio_offset_seconds` (§1.4 Rule 4).

### Wave 1 — declarations (independent, parallelisable)

| # | Title | Effort |
|---|---|---|
| W1.1 | `caption_source` on the `reel_plan` reel item, plus the six acceptance tests in `tests/lib/test_reel_plan.py` (§6.4-6.9), on copies of an unmodified `_plan()` | S |
| W1.2 | `transcriber.output_schema` declares every key `result_data` emits, plus the parity test (**D2**, §6.10). Independent of both epics — land first | S |

### Wave 2 — author, carry, assert

| # | Title | Depends on | Effort |
|---|---|---|---|
| W2.1 | `script-director` authors `caption_source` per reel in `metadata.reels[]` and in the artifact sample at `:404-412`; re-anchors **D3** and **D4(a)(b)** in the paragraphs it edits. Blocked on the uncommitted window-extension change being resolved (§6.19) | W1.1 | M |
| W2.2 | `edit-director` carries it by direct subscript at `:371`'s idiom, and the four other enumerations of the entry key set move with it: `:19` (the script-inputs row), `:43-45` (the per-reel axes list), `:378-393` (the bullets), `:437-440` (the step-8 self-audit). Manifest `success_criteria` lines at `pipeline_defs/reel-batch.yaml:111-114` and `:195` | W1.1 | S |
| W2.3 | `executive-producer`: two G2 bullets (`:196-202`) and the **D4(d)** re-anchor at `:198`; `caption_source` added to G5's key list (`:221-224`) together with `audio_offset_seconds` (**D9**, unless already added); G5's verbatim bullet with its fail-closed clause | W2.1, W2.2 | S |

**W2.3 blocks release.** Without it the field validates, carries, and is read by nobody — the `batch_look` failure in a different key (`docs/intent/reel-batch-spec.md:453-457`). It is not a follow-up.

**Not in any wave, deliberately:** **D1** (colliding transcript filenames), **D4(c)** (`script-director`'s burn-tool anchors — unowned, needs filing after the sibling's W1.4), **D5** (`track_id` required by the gate and not the schema), **D6** (`source_media_review`'s dead `text` read), **D7** (three undeclared call sites), **D8** (inert manifest lists). All are recorded in §2.3 and left to their own issues rather than smuggled into this one.

---

## 8. Risks and open questions

### Open, for the operator

Both block enum members, not this spec's waves.

1. **Would you ever post a reel with no captions?** If yes, `none` re-enters under **R2**'s conditions, and its cost is the five consumers named there plus a source of operator-authored hook copy. If no, F3 stays closed by the step-7 ladder rejecting the reel, and the enum stays at one member indefinitely.
2. **Would you ever supply a spoken-word track — a voiceover rather than music with vocals baked in?** If yes, `voice_over` re-enters, and with it the kind→`vad_filter` rule **R5** currently refuses to write, which is a behaviour change with its own contamination evidence to gather.

No question is open against the tree.

### Objections raised in review, and their disposition

Every high-or-critical objection raised against the drafts and against this spec's baseline, adopted or refused with a reason.

| Objection | Disposition |
|---|---|
| The enum accepts `voice_over` on evidence that fails its own producer test (the demo never transcribes) | **Adopted.** Refused with a re-entry condition (**R2**); the demo claim is refuted at §2.4.3 |
| `none` cannot be delivered: burn refuses empty captions before reading overlays, asset-director crashes on `segs[0]`, the hook is required and word-derived, compose's completion/resume and G6 key on the captioned master | **Adopted.** `none` refused (**R2**), with all five consumers named |
| `none` is unrequested work gated behind two unanswered operator questions, and it breaches the out-of-scope line on the deferred copy stage | **Adopted.** Refused, and the questions are §8 Q1/Q2 rather than a wave dependency |
| A G5 check of `model_size` against the transcript produces false failures on any sitting that walks the confidence ladder (shared track, overwritten path) | **Adopted.** `model_size` is not carried (**R3**); the surviving assertion is `vad_filter`, which the ladder never changes |
| The carry spelling is undecided — `.get()` silently drops, direct subscript raises | **Adopted.** Ruled: direct subscript (**R6**), with the raising behaviour named as correct |
| The reel_plan entry-key set is enumerated in five places in `edit-director.md` and only one was named | **Adopted.** All five are in W2.2 |
| The spec contradicts itself on whether transcription behaviour changes; the conditional-VAD version is a regression path | **Adopted.** **R5** rules the field records and never selects; `"always False"` stands untouched |
| A gate asserting on `script.metadata` violates the R4 dividing rule the spec is bound by | **Adopted.** G2 reads the transcript file and the enum; G5 reads the typed entry. The `script.metadata` copy is an authoring buffer nothing asserts on, and **R4** says so rather than claiming an exemption |
| `subtitles.enabled` derived from `caption_source` is unconsumed on the reel-batch caption path — the burn is a separate pass and `video_compose`'s only reader is a QA string | **Adopted.** Verified: the burn reads `subtitle_source` through the asset manifest (`compose-director.md:214-248`), and `subtitles.enabled` is set unconditionally by `materialise` (`lib/reel_plan.py:63-64`). That workstream is deleted; `lib/reel_plan.py` is untouched |
| The whole object is deletable — the transcript plus one G2 bullet delivers the measurement | **Partly adopted, partly refused.** Adopted: the object is gone (**R3**), the transcriber's `result_data` change is not claimed as this spec's work (§2.0), the materialise change, the new contract-test file and the unrelated defect riders are all cut. **Refused:** the declaration itself. A transcript records what happened and cannot record whether it was intended; a measurement alone can never be wrong. The declaration is what makes the setting falsifiable *as a choice*, and the closed enum is what stops a director declaring an intent nothing in the tree can satisfy |
| A one-member enum shipped as a multi-value contract | **Adopted.** **R2** ships one member, names four refusals, and concedes in the ruling and in the first risk below that the member carries no per-reel information today |
| §2.0 is factually wrong: the tree is `ff04355`, both "uncommitted" premises are committed, and the one modified file is the one §2.0 does not mention | **Adopted in full.** §2.0 rewritten, the false claim refuted in place at §2.4.7, the `+26` offset stated, `remotion_caption_burn.py` cited by symbol, **D4(c)** re-derived, and the transcriber fix no longer claimed as this spec's work |
| Both specs claim decision-log row `#12` | **Adopted.** §1.4 Rule 5: the number is assigned at merge — `#12` if this lands first, `#13` otherwise — and the date is `2026-09-08` |
| Four files are edited by both specs with no stated order | **Adopted.** §1.4 names five shared sites and six binding rules; §7 carries the ordering with its four grounds |
| §6.9 (a `materialise` test) contradicts the sibling's §6.23 (no `materialise` test) | **Adopted.** Reconciled in §1.4 Rule 3 and §6.9 into one parametrised test the second epic extends |
| G5 enumerates nine of the ten authored entry keys — `audio_offset_seconds` is unchecked | **Adopted.** Recorded as **D9**, fixed in W2.3 in the sentence this work already rewrites, and guarded against double-application by §1.4 Rule 4 |
| `executive-producer.md:198`'s `beat_grid.py:449` citation is stale, inside the G2 block W2.3 rewrites | **Adopted.** **D4(d)**, fixed in W2.3, same justification as D4(a)(b) |
| `SUPPLEMENTARY_ARTIFACTS` is mislocated — it is in `lib/checkpoint.py`, not `schemas/artifacts/__init__.py` | **Adopted.** Verified at `lib/checkpoint.py:45-51`; §6.3 corrected |
| The `_plan()` fixture carries neither `caption_confidence` nor `corrections`, and §6.4 must add to a fixture that carries neither — unstated | **Adopted.** Stated in §6 and turned into a binding rule: `_plan()` is not modified at all, and every test sets the property on a copy (§1.4 Rule 2) |
| The `output_schema` parity test's equality may be fragile under `diarize=True` | **Adopted.** Verified and stated in §6.10: `_apply_diarization` (`transcriber.py:245-248`) mutates `segments` before `result_data` is built at `:252` and adds no key |
| **"Both specs cite `validate_artifact` at `lib/checkpoint.py:165`; it is at `:164`."** | **Refused, and the review's own claim is refuted.** Read at `ff04355`: `:164` is `try:`, and `validate_artifact(artifact_name, artifact_data)` is at **`:165`**. `:158-159` (the `ARTIFACT_NAMES` skip) is correct as cited, and the `except` / `raise` block runs `:166-169`. The spec's existing citations stand unchanged; correcting them to `:164` would have introduced the drift the review was hunting |

### Risks

- **The field carries no per-reel information today.** Every reel of every sitting declares `music_bed`. What ships is a closed vocabulary, four machine-enforced refusals, and a declaration a gate can check against a measurement. If §8 Q1 and Q2 both come back "no", it stays that way, and the honest description of the feature is "the pipeline now says out loud, in a typed field, the one thing it has always silently done."
- **It would not have prevented the sung-vocals bug.** F1's verdict is *not closed*. Stated in §1.1, refuted in §2.4, and repeated here because a limit stated only inside a ruling reads as a caveat and this one is a boundary.
- **G2's VAD assertion is immune to D1 only while one member exists.** The immunity is structural — the ladder changes `model_size`, never `vad_filter` (`script-director.md:355-357` vs `:101`) — and it ends the day a member with a different VAD requirement ships. Whoever lands `voice_over` inherits **D1** as a blocker, not as a footnote.
- **`caption_source` proves declaration, not detection.** A director that mislabels passes every check the schema and both gates can make (**R7c**). Same limit as `provenance` (`docs/intent/reel-batch-spec.md:254-257`), named for the same reason.
- **It does not protect the cut-policy verdict.** `beat_grid` never reads word confidence — `_load_words` (`beat_grid.py:428`) keeps every entry with a numeric `start`/`end` (`:463-467`) — and the director already states the consequence: with `vad_filter=False` the model's invented words land in the four numbers the cut-policy ladder branches on (`script-director.md:187-194`). The contamination path bypasses confidence entirely, so declaring the source changes nothing about it.
- **Presence is gate-enforced, not schema-enforced.** An entry with no `caption_source` validates. Mitigated by G5's bullet and by **R6**'s refusal to default; not eliminated, because `required` is a narrowing and four shipped artifacts plus the fixture would fail it. Same shape as **D5** and **D9**, knowingly.
- **The typed record lands three stages after the decision.** Between `script` and `edit` the value is carried by discipline plus a reviewer bullet. Not eliminated: `script.metadata` cannot be typed without widening a thirteen-pipeline shared schema (**R4**).
- **Two epics are editing four of the same files.** §1.4 is the mitigation and it is doctrine, not a mechanism: nothing in CI notices if the second epic resolves the schema conflict by dropping the first epic's property, or mutates `_plan()` and quietly destroys the pre-change pin both features rely on. The review of the second PR has to check it by hand.
- **Nine citations in this spec are hostage to an uncommitted change.** Every `script-director.md` anchor at or below `:276` is `+26` against `HEAD` (§2.0). W2.1 is blocked on that change being committed or discarded, and if it is discarded the anchors must be re-derived before, not during, the edit.
- **Context cost dwarfs tool cost.** `docs/intent/context-cost.md:43` models the bill as `total context-tokens ≈ 0.5 × peak × n_calls`, with 84-86% from accumulation (`:37`). This adds two G2 bullets and one G5 bullet to a sitting that already runs seven gates. The tool cost is $0.00 (§5); the session cost is not, and `budget_remaining_usd` will not show the difference.
- **This spec's own citations are not swept by CI.** Only `docs/intent/context-cost-spec.md` is pinned by name (`tests/contracts/test_agent_instruction_integrity.py:530`); `docs/intent/` is not swept wholesale. The anchors above were read on 2026-09-08 against `ff04355`, and **D3** and **D4(c)** — citations made stale within days by one commit in a neighbouring file — are the evidence of how fast they rot. A spec whose baseline was three days old was wrong about the tree in both directions; assume this one is too within a week.

---

## Decision-log row

Appended to `docs/decision-log.md` (header `| # | Date | Decision | Options considered | Ruling |` at `:7-8`, newest at the bottom, current highest is 11 at `:19`), in its own commit.

**Number assigned at merge — `12` if this epic lands before `docs/intent/animation-preset-spec.md`'s row, `13` if after; see §1.4 Rule 5 and §7's ordering, which expects `13`.** The date is 2026-09-08 either way.

> | 12 *(or 13)* | 2026-09-08 | **What declares the caption audio source for [reel-batch](intent/caption-source-spec.md)** — `script-director.md:82-88` hardcodes the transcriber call in prose and no artifact says which audio a reel's captions came from or what kind of audio the `vad_filter: False` ruling (`:101`) was made for; since `b06a035` the transcript records what was done (`transcriber.py:257`, `:264`) and nothing records what was intended | a closed `{kind, vad_filter, model_size}` object on the reel (duplicates a per-track value onto five reels, and a `model_size` check fails four correct reels after an escalation re-transcribe overwrites the transcript at `transcriber.py:271`) vs a declaration on `brief.metadata.tracks[]` at idea (untyped, and the setting is chosen at script) vs an enum in `script.metadata` alone (unenforceable — `script.schema.json:101`) vs **a `caption_source` string enum typed on `reel_plan.reels[]`, one member** *(chose)* | **Typed on `reel_plan`, one member: `music_bed`.** `voice_over`, `video_sound`, `speech_stem` and `none` have no producer in this tree and are refused with named re-entry conditions rather than shipped as validating-but-unhonoured values. Authored at `script` in metadata, carried verbatim at `edit` by direct subscript, asserted at G2 (declaration producible; the transcript says `vad_filter: false`) and G5 (present, and equal to the script copy). The field records the choice and never selects it — `"Reel-batch passes False, always"` stands. It would not have prevented the sung-vocals loss and is not claimed to. Shares `reel_plan.schema.json`, `test_reel_plan.py`, `edit-director.md` and G5 with [animation-preset](intent/animation-preset-spec.md), which lands its remaining waves first under the contract in §1.4. |