# Animation Preset — specification

**Status:** partly landed. Wave 1 — the renderer and the tool — shipped in `ff04355`; the artifact, director and gate halves are unbuilt, and the echo contract the gate reads is half-written (§2.2.1).
**Pipeline name:** `reel-batch`
**Feature:** `animation_preset` — caption motion as a declared, per-reel, gate-checkable value
**Epic:** unfiled — this spec precedes its issues
**Sibling spec:** [`docs/intent/caption-source-spec.md`](caption-source-spec.md). Five files and one decision-log row are shared surfaces; §1.4 is the binding contract between the two, and it is binding on both.
**Derived from:** verified research into the Instories app, whose help centre documents an Animations section that changes motion "without changing its appearance — the font, stroke, shadow and other settings will remain exactly as you set them", chosen from a small enumerated set with an explicit remove control. That research is the **motivation only**; nothing below rests on it. Every claim carries a `path:line` citation into this repository or was verified by execution.

**All line numbers are against commit `ff04355`** (2026-09-08, `feat(captions): motion was fused into preset, and "no animation" was unreachable`), which is `HEAD` of `feat/reel-batch`. The previous revision of this spec cited `c7d1285`; `ff04355` added ~28 lines to `tools/video/remotion_caption_burn.py` and rewrote `remotion-composer/src/components/CaptionOverlay.tsx`, so **every burn-tool and renderer citation in that revision was stale by the time it was written**, including **D8**, the defect about stale citations. All of them are re-derived here.

The working tree carries exactly one modified file — `skills/pipelines/reel-batch/script-director.md`, an unrelated window-extension change that replaces `:276` with 27 lines and therefore offsets every citation below `:276` in that file by **+26**. This spec cites that file only above the hunk (`:99-114`), so it is unaffected; the sibling spec is not (§1.4).

Claims asserted during this spec's own research and later **refuted** are corrected in place rather than deleted (§2.4). That now includes claims this spec itself made in its previous revision and the tree then contradicted (§2.4(h)-(k)).

---

## 1. Confirmed intent

| | |
|---|---|
| **Outcome** | Caption **motion** is a declared, validated, per-reel value, separate from caption typography and layout, with "no animation" a first-class setting |
| **User** | The operator running a five-reel sitting who wants one brand type style across the batch and different energy per reel |
| **Why now** | Half of it is shipped and inert. `animation_preset` validates, reaches the props and renders (`tools/video/remotion_caption_burn.py:133-147`, `remotion-composer/src/components/CaptionOverlay.tsx:74-78`), and **no artifact authors it and no gate reads it** — the `batch_look` failure shape this repo has already shipped once (`docs/intent/reel-batch-spec.md:453-457`) |
| **Success** | Every reel's rendered motion is readable off `render_report`, joined to its reel, and comparable to what `reel_plan` asked for — without opening a file |
| **Constraints** | Free-first, $0.00 (`skills/pipelines/reel-batch/executive-producer.md:51-52`). Every existing render stays byte-identical — already true and pinned (`tests/tools/test_remotion_caption_burn.py:253`, `:842-851`). Identity lock, the clip ledger and the batch look are untouched |
| **Approval shape** | None new. Motion is authored at `edit`, which is `checkpoint_required: true` / `human_approval_default: false` (`pipeline_defs/reel-batch.yaml:186-187`); it reaches the operator at gate 3 (`publish`) through `render_report` |

### 1.1 The motion inventory (binding scope of the split)

Every visual parameter of `CaptionOverlay.tsx`, plus the one pill decision `TalkingHead.tsx` keys off the preset. The overlay plane is not in this table and is not in this feature (§1.3). Line numbers re-derived against `ff04355`.

| Concern | Parameters | Settable from Python today |
|---|---|---|
| **Motion** | `popScale` (`MotionStyle.popScale` at `CaptionOverlay.tsx:47`, values `:56-58`, resolved onto the style at `:315`, gated at `:250`, emitted `:267-268`), `POP_DURATION_FRAMES = 5` (`:120`), the `popPulse` sine (`:126-128`), the page entrance `spring({damping: 18, stiffness: 120})` (`:196-200`), its `opacity` (`:220`) and `translateY(20 → 0)` (`:221`), both now gated by `animateEntrance` (`:218`) | **`popScale` and the entrance, both, by name** — `animation_preset` (`remotion_caption_burn.py:133-147`) |
| **Typography** | `strokeRatio` (`:82`, `:275-283`), `uppercase` (`:83`, `:240`), `fontSize` (`:299`), `fontFamily` (`:303`), `wordSeparator` (`:304`), stroke colour hardcoded `"#000"` (`:278`) | `font_size` |
| **Layout** | `wordGapRatio` (`:90`, `:272-273`, floored at `:320`), `safeZone.bottom`/`.sides` (`:91`, `:207-209`, `:227-229`), `LEGACY_PADDING_BOTTOM = 80` (`:115`), `wordsPerPage` (`:134`, `:298`) | `words_per_page`, `safe_zone` |
| **Colour** | `color`, `highlightColor`, `backgroundColor` (`:300-302`), and the pill decision `captionPreset === "reel_pop" ? "transparent" : "rgba(0, 0, 0, 0.65)"` (`remotion-composer/src/TalkingHead.tsx:355`) | `highlight_color` |

The right-hand column is the one thing `ff04355` changed. Before it, six motion parameters existed and exactly one was reachable, as a side effect of a typography choice. **The renderer half of this feature is done. Nothing above moves again.** `strokeRatio`, `uppercase`, the preset's `safeZone` and the pill stay under `preset`; `wordGapRatio` is the one shared parameter, and R3 records why.

### 1.2 The motion vocabulary — as shipped

Three values. This table describes **what `ff04355` renders**, verified by executing the real `resolveMotion` in node (`tests/tools/test_remotion_caption_burn.py:802-839`), not what the previous revision of this spec ruled (§2.4(h)).

| Value | Page entrance | Per-word pop | Word-gap floor | Is today's |
|---|---|---|---|---|
| `none` | off | off | 0 | nothing — unreachable before `ff04355` |
| `fade` | on | 0 | 0 | what `preset: "default"` renders |
| `pop` | on | **0.16, fixed** | **0.4** | what `preset: "reel_pop"` renders |

`MOTIONS` is a record of three `MotionStyle` objects (`CaptionOverlay.tsx:45-59`); `PRESET_MOTION` maps each preset to the member it has always rendered (`:64-67`); `resolveMotion(preset, animation)` resolves the preset key first and falls back to `MOTIONS[PRESET_MOTION[presetKey]]` (`:74-78`). `CaptionOverlay` then builds the render style by spreading the preset and overriding two fields: `popScale: motion.popScale` and `wordGapRatio: Math.max(base.wordGapRatio, motion.minWordGapRatio)` (`:313-321`), and passes `animateEntrance={motion.entrance}` to `PageRenderer` (`:346`).

Two consequences, both correct and both the opposite of what this spec's previous revision said:

- **`pop` is a fixed 0.16, not "this preset's pop".** `{preset: "default", animation: "pop"}` is a newly reachable combination that renders a real pop, and the 0.4 gap floor travels with it so the growing word does not touch its neighbour at the peak — the collision `CaptionOverlay.tsx:103-105` records `reel_pop`'s 0.4 was tuned to survive. Pinned by `test_motion_carries_a_word_gap_floor_typography_does_not_supply` (`tests/tools/test_remotion_caption_burn.py:870-876`).
- **An absent animation is byte-identical to before.** `PRESET_MOTION` restates each preset's existing behaviour, and the identity is asserted by execution rather than by reading source (`:842-851`).

A fourth value needs a new curve, a new tuning pass on a real 1080×1920 render, and a requester. Shipping an enum member with no code path behind it is the guards-bypassed-by-omission failure in a new coat.

### 1.3 Out of scope

- The sung-vocals VAD fix (`skills/pipelines/reel-batch/script-director.md:99-114`) — a transcript-content defect on a different stage; motion neither causes nor cures it.
- `caption_source` (Feature A, [`docs/intent/caption-source-spec.md`](caption-source-spec.md)) — decided at `script`, this is decided at `edit`; the two touch no common **field**. They touch five common **files**, and §1.4 governs that.
- `Explainer.tsx`'s hero_title prop forwarding (**D9**) — reel-batch renders `"TalkingHead"` (`tools/video/remotion_caption_burn.py:423`), never `Explainer`. Recorded, not fixed.
- Computing `hero_title`'s `fontSize` / `staggerFrames` — ruled out with evidence in **R10**, together with **D10**.
- A b-roll suggestion pass.
- Identity lock, the clip ledger and `batch_look`. The batch look is `grade` and `sharpen` (`executive-producer.md:27-30`), its schema block is closed to three keys (`schemas/artifacts/edit_decisions.schema.json:263-271`), and no line of this change reaches `lib/polish_filters.py` or `lib/clip_ledger.py`.
- Moving `caption_style` to a typed property (**D12**) — ruled out in **R7**, blocked by **D6**, left to its own issue.
- The four look inputs the ffmpeg fallback drops without naming (**D2**) — **R9** repairs only what this feature adds.
- `lib/reel_plan.py:63-64`'s discard of the authored `subtitles` block (**D6**) — its own issue.
- `G2`'s stale `beat_grid.py:449` citation (`executive-producer.md:198`) — a real defect inside a block only the sibling spec rewrites; assigned there, not here.
- Any paid dependency. Both planes are local; the sitting stays at $0.00.

### 1.4 Shared surfaces with `caption-source-spec.md` — binding on both specs

Five files and one decision-log row are edited by both epics. Neither spec's workstreams mentioned the other before this revision; that is how two green branches produce one broken merge. The following is binding, and the identical paragraph appears in the sibling.

| Shared site | This epic writes | `caption-source-spec.md` writes |
|---|---|---|
| `schemas/artifacts/reel_plan.schema.json`, `reels.items.properties` | `animation_preset` (W2.1) | `caption_source` (its W1.1) |
| `tests/lib/test_reel_plan.py`, around `_plan()` (`:55-69`) | three schema tests (§6.21) | six schema tests (its §6.4-6.9) |
| `skills/pipelines/reel-batch/edit-director.md`, the five entry-key enumerations | W2.1 | its W2.2 |
| `skills/pipelines/reel-batch/executive-producer.md:221-224` (G5's key sentence) | W3.1 | its W2.3 |
| `docs/decision-log.md` | one row | one row |

**1. One branch at a time on `reels.items.properties`.** The preferred shape is a **single commit widening `reel_plan.schema.json` with both optional properties**, landed by whichever epic reaches the file first — under §7's ordering, this one — with the sibling's property text copied verbatim from `caption-source-spec.md` §4.3 and its acceptance tests landing with the sibling. The one escape hatch is the sibling's §8 Q1/Q2 still being open at that moment, which could still change its enum membership: in that case this epic lands `animation_preset` alone and **the sibling rebases onto the committed properties block rather than re-deriving it**, and says so in its PR body. What is forbidden in both shapes is two branches independently editing that block.

**2. `_plan()` is not modified by either epic.** The fixture at `tests/lib/test_reel_plan.py:55-69` carries neither property and stays that way. Each test that needs one sets it on a copy inside the test body. A fixture edited by two branches is a merge conflict in the one file both epics' acceptance rests on, and a fixture carrying both properties makes every other test in the file assert against a shape no director produces.

**3. One `materialise`-is-untouched test, parametrised, owned by the second epic.** This spec's §6.23 says this epic adds no `materialise` test, and the reason stands (`materialise` reads four entry keys and copies no others, so such a test asserts only that Python did not mutate a dict it never touched). The sibling's §6.9 wants one, for a reason that is also good (it pins that the field reaches no renderer). **Reconciliation:** the sibling authors exactly one test, parametrised over both property names, and §6.23 is not to be read as forbidding it. Two separate tests asserting the same invariant about two properties is the drift generator both specs otherwise argue against.

**4. One G5 landing order.** `executive-producer.md:221-224` is a single hand-enumerated sentence. This epic's W3.1 lands `animation_preset` **and** the `audio_offset_seconds` correction (**D15**) in one edit; the sibling's W2.3 rebases onto that text and adds `caption_source`. Not the reverse, and never both at once.

**5. One decision-log number, assigned at merge.** `docs/decision-log.md` ends at `| 11 |` (`:19`) under the header at `:7-8`. This spec's row is **#12 if this epic lands first** — which §7's ordering says it does — and **#13 otherwise**. The date is **2026-09-08** for anything landing today; `ff04355` and `b06a035` are both dated 2026-09-08. The sibling's row takes the other number. Two commits claiming `| 12 |` is a silent corruption of the log, because nothing validates it.

---

## 2. Verified baseline

### 2.0 Half of this feature is already committed

`ff04355` is `HEAD`. It landed, in one commit (+375/−9, 15 new tests):

- `remotion-composer/src/components/CaptionOverlay.tsx` — `CaptionAnimation`, `MotionStyle`, `MOTIONS`, `PRESET_MOTION`, `resolveMotion`, the `animation?` prop, the resolved style, and `animateEntrance` threaded into `PageRenderer`.
- `remotion-composer/src/TalkingHead.tsx` — `captionAnimation?: CaptionAnimation` (`:330`), destructured (`:347`), forwarded by truthy spread (`:402`).
- `tools/video/remotion_caption_burn.py` — `ANIMATION_PRESETS` (`:80`), the schema property (`:133-147`), the `_validate_look` branch (`:596-604`), the `_render_remotion` parameter (`:341`) and conditional props key (`:406-407`), the fallback's dropped-list entry (`:726-731`), the `fps` guard (`:737`), and the convergence-point echo (`:756-761`).
- `tests/tools/test_remotion_caption_burn.py` — now 887 lines, 41 test functions.

`b06a035`, the sibling spec's premise, is likewise committed. `git status --short` shows one modified file (the `script-director.md` window-extension change described in the header).

**What this costs this spec.** Three rulings and one whole checklist section described work that is done, and one of them — **R3** — ruled *against* the design that shipped. Those are corrected below rather than deleted: a spec that quietly agrees with whatever landed teaches nobody why the reversal was right.

**What it does not change.** The artifact, the director and the gate are exactly as absent as they were. The half that shipped is the half that cannot be checked.

### 2.1 What already exists and is reused

| Capability | Where | Reused how |
|---|---|---|
| **The whole renderer axis** | `CaptionOverlay.tsx:43-78`, `:145-147`, `:188-189`, `:218-223`, `:250`, `:267-268`, `:312-321`, `:346` | Nothing further to build. W1.1 is closed by `ff04355` |
| **The whole tool input** | `remotion_caption_burn.py:80`, `:133-147`, `:341`, `:406-407`, `:596-604`, `:661` | Nothing further to build. W1.2 is closed by `ff04355` |
| **The prop thread** | `TalkingHead.tsx:330`, `:347`, `:402` — `{...(captionAnimation ? { animation: captionAnimation } : {})}` | W1.3 is closed by `ff04355`. Note `:401` is deliberately `!== undefined`-shaped for `wordSeparator: ""`; the motion spread correctly is not |
| Conditional look prop | `remotion_caption_burn.py:401-409` — `captionPreset` only when `!= "default"`, `captionAnimation` only when not `None`, `captionSafeZone` only when truthy | An unset animation produces a byte-identical props JSON, pinned at `tests/tools/test_remotion_caption_burn.py:249-253` |
| Look validation ahead of side effects | `_validate_look` at `:590`, called at `:666`, before the input-file check at `:670-671`; the animation branch sits at `:596-604`, **above** the `safe_zone` early return at `:619-621` | The placement §6.4 demanded; pinned by `test_execute_refuses_a_bad_animation_before_touching_the_input` (`tests/tools/test_remotion_caption_burn.py:157-165`) and by a bad-input row with no `safe_zone` (`:119`) |
| A written reason for closing a look input | `:626-627` — "an unknown key on the TS side is silently ignored and the caption then renders in the wrong place with no error" | The same argument governs the animation enum: `CaptionOverlay.tsx:311` still resolves `PRESETS[preset] ?? PRESETS.default`, silently |
| Caller-prop-beats-preset-field | `CaptionOverlay.tsx:322` — `safeZone ?? base.safeZone` | Layout was already split out of the preset this way; motion followed the shipped idiom |
| Degradation contract | `remotion_caption_burn.py:717-751` — `preset`, `requested_preset`, `degraded`, `unhonoured_inputs`, `note`; `animation_preset` joins the dropped tuple at `:726-731`, guarded on the raw input | Shipped. Its two remaining holes are §2.2.1, not §2.3 |
| The `fps` saturation fix (**D1**) | `:737` — `("fps", fps if fps != 30 else None)`, pinned by `test_an_all_default_fallback_admits_dropping_nothing` (`tests/tools/test_remotion_caption_burn.py:764-773`) | Shipped in `ff04355`. R9's remaining scope is one line |
| Optional prop needs no registration | `remotion-composer/src/Root.tsx:178-193` — `TalkingHead`'s `defaultProps` (`:185-192`) carry none of `captionPreset`, `captionAnimation`, `captionSafeZone` | Confirmed unchanged by `ff04355`; the standalone `CaptionOverlayOnly` registration (`:256-270`) likewise |
| Per-reel typed artifact | `schemas/artifacts/reel_plan.schema.json:13`, item closed at `:62`, root at `:67` | `animation_preset` is a typed sibling of `caption_confidence` (`:50-60`) |
| Per-reel entry read directly at compose | `compose-director.md:245-246` — `if entry.get("corrections"): burn_inputs["corrections"] = ...` | `entry["animation_preset"]` is one more read in the same fence; it never passes through `materialise` |
| Parametrised look-input tables | `tests/tools/test_remotion_caption_burn.py:103-120` (bad, including `:119`), `:128-141` (good, including `:136` and `:139`) | The enum's rows are already there |
| Node-executing TSX tests | `_eval_pop_pulse` (`:435-459`), `_resolve_caption_background` (`:633-658`), `_resolve_motion` (`:802-839`) — "Source-string assertions cannot police this one" (`:805`) | The motion resolution is executed, not read: `:842-887` |
| Schema-widening template | `tests/lib/test_edit_decisions_schema.py:67-70` (a pre-change artifact that must still validate), `:73-80` (a required-property pin), `:83-87` / `:90-95` (enum accepts / enum rejects) | Both schema changes copy this shape, in `tests/lib/`, where reel-batch's schema tests live |

**The shipped tests that must stay green, by name.** These are the acceptance of Wave 1 and the regression floor of everything below: `test_bad_look_inputs_are_rejected[unknown_animation]` (`:119`), `test_good_look_inputs_pass` (`:136`, `:139`), `test_execute_refuses_a_bad_animation_before_touching_the_input` (`:157`), `test_default_preset_stages_and_renders_exactly_as_before` (`:233`, with `assert "captionAnimation" not in props` at `:253`), `test_an_explicit_animation_reaches_the_props` (`:683`), `test_a_preset_without_an_animation_emits_no_animation_key` (`:693`), `test_the_fallback_reports_motion_as_none_and_says_it_dropped_it` (`:741`), `test_the_fallback_does_not_flag_an_animation_it_honoured` (`:750`), `test_an_all_default_fallback_admits_dropping_nothing` (`:764`), `test_the_remotion_path_echoes_only_what_it_was_asked_for` (`:773`), `test_an_absent_animation_renders_what_the_preset_always_rendered` (`:842`), `test_an_unvalidated_preset_still_renders_rather_than_throwing` (`:854`), `test_none_turns_off_both_the_entrance_and_the_pop` (`:863`), `test_motion_carries_a_word_gap_floor_typography_does_not_supply` (`:870`), `test_the_page_entrance_is_omitted_rather_than_neutralised` (`:878`).

### 2.2 What is missing — the actual work

1. **The echo contract the gate reads is half-written, and its two holes are `KeyError`s.** This is the highest-priority remaining item and it is in the tool, not the artifact.
   - **`degraded` is never set on the Remotion path.** `_render_remotion`'s success return is `{method, output, duration_seconds, total_frames, caption_count, overlay_count, words_per_page, preset, fps}` (`:463-475`). `degraded` is written only inside the fallback branch (`:743`). R8(b) sources `render_report.outputs[].caption_degraded` from `burn.data["degraded"]`, which raises on **every successful Remotion render** — that is, on every normal sitting — and G6's second bullet ("or `caption_degraded` is true") then cannot be answered at all.
   - **`requested_animation_preset` does not exist.** The fallback writes `result.data["requested_preset"] = preset` (`:742`) and the resolved `animation_preset` at the convergence point (`:756-761`), but never the request. R5's "by exact symmetry with `requested_preset`" describes a symmetry that was not built.
   Both are fixed by W1.4, which blocks W2.2.
2. **No artifact records what motion a reel asked for, or got.** `render_report.outputs[]` items are closed at `schemas/artifacts/render_report.schema.json:26` and carry no look field and **no reel identity**; `compose-director.md:348-351` states in as many words that the reel↔output join lives in the untyped `metadata.reels[]` (`render_report.schema.json:60`). G6 (`executive-producer.md:230-235`) can assert nothing about motion and has nothing typed to join on.
3. **Motion still cannot vary per reel, because nothing per-reel carries it.** The caption look is one dict on the spine root's `metadata` (`edit-director.md:312-315`), read once at compose (`compose-director.md:223`). There is exactly one, batch-wide. The tool would honour five different values; no artifact can express them.
4. **The caption look is a metadata side-map.** `caption_style` appears in exactly two files repo-wide — `edit-director.md:102`, `:312`, `:322` and `compose-director.md:217`, `:223`, `:232`, `:233`, `:259`, `:436` — and in no schema, library, tool or test. A misspelled key is a `KeyError` at compose, not a validation failure at edit.
5. **A new input gets nothing for free.** `input_schema` is a declarative class attribute (`tools/base_tool.py:255`) echoed by `get_info()` (`:348`) and validated by nothing — no jsonschema call, no default application, no unknown-key rejection. Every guarantee in `ff04355` is hand-written, and every guarantee below will be too.

Items 1 and 2 were previously written as "there is no way to turn caption motion off" and "motion cannot vary without typography varying with it". Both are now false: `ff04355` fixed them. They are replaced rather than kept.

### 2.3 Defects found in shipped code (pre-existing, not caused by this work)

- **D1 — `fps` was reported unhonoured on every fallback render. FIXED in `ff04355`.** The tuple entry was a bare `("fps", fps)` under an `if value` filter, and 30 is truthy; a `force_ffmpeg=True` render passing nothing but the required fields returned `unhonoured_inputs: ['fps']`. It is now `("fps", fps if fps != 30 else None)` (`:737`), guarded like `preset` at `:722`, and pinned at `tests/tools/test_remotion_caption_burn.py:764-773`. The honest limit is stated in the code (`:733-736`): an explicit 30 is indistinguishable from no request and is told nothing was dropped. Recorded, not re-fixed.
- **D2 — the fallback drops four look inputs and names none of them.** `_render_ffmpeg`'s signature is `(input_path, output_path, captions)` (`:483-488`), called at `:704`; it hardcodes `page_size = 4` (`:497`) and `FontSize=24` (`:521`). `font_size`, `words_per_page`, `highlight_color` and `overlays` never reach it, appear in no result field, and are absent from the `dropped` tuple (`:717-741`); `overlay_count` is emitted only on the Remotion path (`:471`). A whole hook overlay vanishes with `success=True` and nothing listed as dropped. Recorded; **not fixed here** (§1.3, R9).
- **D3 — the Remotion echo is incomplete.** `:463-475` returns `preset`, `fps`, `words_per_page`, `caption_count`, `overlay_count` — not `font_size`, `highlight_color` or `safe_zone`, and (§2.2.1) not `degraded`. A gate that wants to confirm the batch's safe zone was applied cannot read it back.
- **D4 — enums and patterns are spelled twice, derived from neither.** `PRESETS = ("default", "reel_pop")` at `:581` and the `preset` enum at `:125` are independent literals; `_RUN_ID_RE` at `:586` enforces a pattern the schema never declares (`:162-171` has no `pattern` key). `ANIMATION_PRESETS` deliberately broke the habit — `"enum": list(ANIMATION_PRESETS)` at `:135`, with the reason written at `:77-79` — and `PRESETS` was left alone, so the defect survives in the older half of the same schema.
- **D5 — TypeScript catches nothing on this path.** `TalkingHeadProps` opens `[key: string]: unknown` (`TalkingHead.tsx:313`), so a misspelled or unforwarded prop typechecks and is dropped at runtime; `CaptionOverlay.tsx:311` resolves `PRESETS[preset] ?? PRESETS.default`, and `resolveMotion` (`:74-78`) deliberately degrades the same way rather than throwing (`:69-73`, pinned at `tests/tools/test_remotion_caption_burn.py:854-860`). Python is the only rejection surface that exists.
- **D6 — `materialise` discards the authored `subtitles` block.** `lib/reel_plan.py:63-64` rebuilds `subtitles` from three hardcoded keys and never reads the spine's own object, while copying `metadata` wholesale at `:65`. Everything `edit-director.md:306-311` writes into the typed block — `position`, `max_words_per_line` — is dropped before compose sees it. `tests/lib/test_reel_plan.py:168` pins only `subtitles["source"]`, which is why it is invisible. This is why `caption_style` had to live in `metadata`, and why `compose-director.md:234` re-types `"words_per_page": 3` as a literal (**D11**).
- **D7 — `subtitles.style` is an unvalidated string whose consumer sniffs its type at runtime.** `schemas/artifacts/edit_decisions.schema.json:189` types it as a bare `string` documented in prose as "sentence, word-by-word, karaoke", with no enum; `tools/video/video_compose.py:3468-3477` reads it and branches `isinstance(ed_style, str)` / `isinstance(ed_style, dict)`. The typed schema has an unvalidated motion-ish axis and its consumer defends against the schema-valid form.
- **D8 — the three skills this epic edits cite the burn tool at line numbers that no longer resolve. Re-derived against `ff04355`; the drift is now ~+74 lines, not ~+46.** The previous revision's "actual" column was itself computed against `c7d1285` and is wrong by ~28.

  | Citation site | Cites | Actual at `ff04355` |
  |---|---|---|
  | `edit-director.md:326` | preset block `:115-124`; `PRESETS` at `:507` | `:123-132`; `PRESETS` at `:581` |
  | `edit-director.md:328` | `:120-123` | `:126-131` |
  | `edit-director.md:329` | `_SAFE_ZONE_KEYS` at `:511`; enforcement `:538-545` | `:587`; `:624-631` |
  | `edit-director.md:332` | `bottom` required at `:546-547` | `:632-633` |
  | `edit-director.md:333` | `[0, 0.5)` at `:556-557` | `:642-643` |
  | `edit-director.md:334` | safe-zone description `:125-133` | `:148-156` |
  | `edit-director.md:345` | degradation block `:614-640` | `:717-751` |
  | `compose-director.md:262` | corrections `:148-155` | `:172-179` |
  | `compose-director.md:269` | `run_id` `:139-146`, `:350-358`, `:398-401` | `:162-171`, `:378-386`, `:426-429` |
  | `compose-director.md:271` | `run_id` regex at `:510`, **quoted `$`-anchored** | `:586`, and the shipped pattern is `\Z` — the doc still documents the trailing-newline bug the code comment records as fixed, and `test_run_id_with_a_trailing_newline_is_rejected` (`tests/tools/test_remotion_caption_burn.py:590`) pins the fix |
  | `compose-director.md:273-275` | preset `:115-124`; safe zone `:125-132` | `:123-132`; `:148-156` |
  | `executive-producer.md:234` | `safe_zone` at `:125` | `:148-156` |

- **D9 — `TalkingHead` and `Explainer` forward disjoint halves of `HeroTitle`'s props.** `HeroTitle` declares one required prop and seven optional ones (`remotion-composer/src/components/HeroTitle.tsx:9-38`). `TalkingHead.tsx:228-236` reaches three (`subtitle`, `fontSize`, `staggerFrames`); `Explainer.tsx:807-816` reaches four others plus `subtitle` (`accentColor`, `textColor`, `subtitleColor`, `scrimBackground`), and `Explainer`'s own `Overlay` interface (`:273-285`) declares neither `fontSize` nor `staggerFrames`. Neither reaches all seven; the sets overlap only on `subtitle`. From reel-batch a hero title's accent colour is unreachable. Recorded; not fixed (§1.3).
- **D10 — `HeroTitle`'s docstring is stale on both ceilings and its documented remedy does not work.** `HeroTitle.tsx:12-16` says a long title is "clipped at the box edge with no warning" at "roughly 19 characters per line in the 1080-wide reel frame". The title now **wraps** between words (`:58-68` regroups characters into word spans, `:88` sets `flexWrap: "wrap"`); horizontal clipping survives only for a single unbreakable token, because each word span is `whiteSpace: "pre"` (`:93`). The width basis is not 1080px: the inner box is `maxWidth: "85%"` (`:78`) of a `POSITION_STYLES` box already inset 40px per side (`TalkingHead.tsx:88-89`) — about 850px. And `:18-25` tells callers to lower `staggerFrames` for a long title, while `:129` hardcodes `titleChars.length * 1.2` for the subtitle's entrance, so lowering it does not move the subtitle. The binding ceiling is **vertical**: `PositionedOverlay` sets `overflow: "hidden"` (`TalkingHead.tsx:293`) on a `height: 480` box (`:84`, `:91`).
- **D11 — `words_per_page: 3` is a hardcoded literal in the fence that forbids hardcoded literals.** `compose-director.md:234` types it inline; `:257-259` says "**Never re-type `safe_zone` as a literal**"; `edit-director.md:318-320` calls 3 "the batch's one caption density … three names for one figure, and they must not drift apart". The typed spelling (`max_words_per_line`, `edit_decisions.schema.json:197`) is discarded by **D6**, so compose has no honest alternative.
- **D12 — the caption look is an untyped side-map that a gate asserts on.** `edit_decisions.metadata` declares only `identity_lock` and is **not** closed (`edit_decisions.schema.json:273-282`; `:283` closes the root only), so `caption_style` is typo-silent — while G6 asserts on the safe zone by name (`executive-producer.md:233-234`). `edit-director.md:255-259` already records the same argument for `batch_look`. Recorded; **not fixed here** (R7).
- **D13 — `idempotency_key_fields` excludes every look input, and nothing computes the key.** `remotion_caption_burn.py:202` is `["input_path", "segments", "srt_path"]`; two burns of the same source differing in preset, animation, safe zone, fps or overlays hash identically (`tools/base_tool.py:386-390`). It is inert today: across `lib/`, `tools/` and `scripts/` the only non-test call of `idempotency_key(` is `tools/audio/fish_audio_tts.py:278`, a `super()` override. Recorded; **not fixed here** (R8, §8).
- **D14 — `backlot/state.py`'s docstring states as a fact the thing R8 changes.** `:513-514` reads "`reel_plan` entries are `additionalProperties: false`, so the join between a reel and its finished file cannot be stored in the artifact", and `:534-543` implements a compose-checkpoint `metadata.partial_progress.reel_outputs` lookup plus a filename-stem fallback for exactly that. The first clause is about `reel_plan`, not `render_report`, so it stays true — but the sentence is the repo's second written statement that reel identity has no typed home, and after W2.2 it needs one clause saying `render_report.outputs[].reel_id` is now the typed join for finished files. Comment-only; folded into W2.2 rather than deferred, because `docs/PR_REVIEW_GUIDE.md:426-427` is explicit that documentation which teaches agents the wrong behaviour is a regression.
- **D15 — G5 enumerates nine of the ten entry keys the director authors.** `executive-producer.md:221-224` names `reel_id`, `track_id`, `music_asset_id`, `subtitle_source`, `subtitle_srt_source`, `hook`, `cut_ids`, `corrections`, `caption_confidence`. `edit-director.md:358-372` authors ten: `audio_offset_seconds` (`:367`) is authored, schema-typed (`reel_plan.schema.json:31-35`) and **gate-unchecked**. A reel missing it opens on the wrong seconds of its bed — precisely the failure the schema description at `:34` was written to prevent. Recorded here because this epic edits that sentence anyway; **fixed in W3.1**, in the same edit (§1.4 rule 4).

### 2.4 Claims this spec refutes

**(a) "`preset: 'default'` already means no animation."** **False when written, and now moot.** `default` sets `popScale: 0`, which suppressed only the per-word transform; the page-level `spring` was unconditional under both presets and drove `opacity` and a 20px rise with nothing gating it. `ff04355` gated it: `animateEntrance` (`CaptionOverlay.tsx:188-189`, `:218-223`, `:346`), asserted by `test_the_page_entrance_is_omitted_rather_than_neutralised` (`tests/tools/test_remotion_caption_burn.py:878-887`) on the rendered style object rather than on source text. The claim's consequence — that the TypeScript change had to be part of this feature and not a follow-up — was right, and is why W1.1 was Wave 1.

**(b) "`position` is ignored by the `hero_title` branch."** Asserted as orchestrator ground truth; **refuted**, and corrected here rather than deleted. The branch at `TalkingHead.tsx:228-236` forwards only `title`, `subtitle`, `fontSize`, `staggerFrames` — but every overlay renders through `PositionedOverlay` (`:386`), which reads `overlay.position || "lower_third"` (`:284`), looks it up in `POSITION_STYLES` (`:285`) and spreads the result onto the wrapping div (`:288-299`). `upper_third` is a real style — `{top: 80, left: 40, right: 40, height: 480}` (`:86-92`). So `scripts/reel_batch_two_plane_demo.py:196`'s `"position": "upper_third"` **is** honoured. No issue is filed. This matters here: **layout is already a working, separately-declared axis for overlays**, which is in-repo evidence for splitting layout from motion rather than an argument this spec must make from scratch. The real finding underneath is **D10**'s vertical clip.

**(c) "Twelve pipelines call `remotion_caption_burn`."** Recorded during this spec's research; **false**. Exactly two manifests grant the tool: `pipeline_defs/reel-batch.yaml:211`, `:218` and `pipeline_defs/talking-head.yaml`. Verified by `grep -rl remotion_caption_burn pipeline_defs/`. The blast-radius argument for byte-identity therefore rests on the shipped tests, not on caller count. **The same arithmetic was not done for `render_report`, and should have been: thirteen manifests produce it** (§4.3).

**(d) "No test in this repo asserts `idempotency_key`."** **False.** `tests/tools/test_fish_audio_tts.py:286-325` is the house template — equal key for an irrelevant field, different key for a keyed field — and `tests/contracts/test_jimeng_video.py:148-167` does the same. What is true is narrower and is recorded as **D13**.

**(e) "`identity_lock` is precedent for adding an optional property to a closed object."** **False.** `identity_lock` is declared inside `edit_decisions.metadata`, which has no `additionalProperties: false` (`edit_decisions.schema.json:273-282`) — it is the counter-example, not an instance. The monotone widening this repo has landed on **closed** objects is three: `provenance`, `polish`, `batch_look` (`docs/intent/reel-batch-spec.md:437-451`).

**(f) "The ffmpeg fallback's no-silent-degradation contract is complete and deliberate."** Asserted as orchestrator ground truth. It is deliberate and it is stated in the code (`remotion_caption_burn.py:733-736`, `:745-751`), but it is **not complete**: **D2** omits four inputs including the entire overlay plane, and **D1** saturated it until `ff04355`. A spec that says a new input "must join the contract" must also say the contract still lies by omission about four older ones.

**(g) "An all-default fallback render should report `degraded: False`."** Recorded during this spec's research; **false and dangerous**. `degraded` is set unconditionally at `:743`, outside the `if dropped:` guard at `:745`, and that is correct: `_render_ffmpeg` (`:483-538`) burns a static SRT at `FontSize=24` (`:521`) with no per-word highlight, no pill, no safe zone and no entrance. An all-default fallback **is** a motion-led → still-led downgrade, which `docs/PR_REVIEW_GUIDE.md:277-278` names a review finding and `AGENT_GUIDE.md:747` forbids hiding. `degraded` names the **path**; `unhonoured_inputs` names the **diff**. Pinned at `tests/tools/test_remotion_caption_burn.py:772`.

**(h) "The renderer resolves motion subtractively from the preset it already holds; `popScale` stays in `PresetStyle`, and the `MOTIONS` relocation is rejected."** **This spec's own previous ruling, R3, and the tree refuted it.** `ff04355` shipped the rejected design: `MotionStyle` with `entrance`, `popScale` and `minWordGapRatio` (`CaptionOverlay.tsx:45-53`), a `MOTIONS` record carrying `pop: { entrance: true, popScale: 0.16, minWordGapRatio: 0.4 }` (`:58`), and `wordGapRatio: Math.max(base.wordGapRatio, motion.minWordGapRatio)` (`:320`) — the floor and all. Corrected in place: §1.2 now describes the shipped semantics and R3 records the reversal and why it was right.

**(i) "Relocating `popScale` reddens five source-string assertions in three shipped tests."** **False, and it is the load-bearing half of R3's rejected argument.** The shipped design kept `style.popScale` as the *read* site and changed only what fills it (`:250`, `:267-268`, `:315`), so every one of those assertions survived untouched: `"popScale: 0." in _preset_block("reel_pop")` (`tests/tools/test_remotion_caption_burn.py:393`), `"popScale: 0," in _preset_block("default")` (`:402`), `"...(style.popScale" in source` (`:412`), `"const pop = style.popScale ? popPulse(wordFrame) : 0;"` (`:432`), and both gap literals (`:495`, `:502`). The previous revision also predicted `:393`/`:413` **would** change; neither did. A test-churn count is not an argument about correctness, and this is the evidence.

**(j) "`result.data['degraded']` is set on both paths" and "`requested_animation_preset` mirrors `requested_preset`."** **Both false.** Stated in this spec's own R5 and R8(a), and neither is in the tree: the Remotion success return is `:463-475` with no `degraded`, and `requested_animation_preset` appears nowhere. They are the two `KeyError`s R8's gate would have hit on every normal sitting, they are §2.2.1, and W1.4 is what closes them. Corrected rather than deleted, because the gate design that assumed them is the gate design this spec still ships.

**(k) "The reel↔output join lives only in the untyped `metadata.reels[]`."** **False, and this spec asserted it in R8(b).** There is a second join and this spec cited the file that implements it: `backlot/state.py:539-543` reads `checkpoints["compose"]["metadata"]["partial_progress"]["reel_outputs"]`, with a filename-stem fallback below it, and its comment (`:531-537`) records that reading the join off `render_report` "was a branch that could never fire". So the join exists in two untyped places, neither of them the artifact a gate validates. That strengthens R8 rather than weakening it, and the sentence is corrected.

**(l) "`validate_artifact` is called at `lib/checkpoint.py:164`."** **False; this spec's `:165` is correct and is retained.** Verified: `:164` is `try:` and `:165` is `validate_artifact(artifact_name, artifact_data)`, inside the loop that skips unregistered names at `:158-159`. `docs/intent/reel-batch-spec.md:201` cites `:165` too. Recorded because the correction was proposed in review and refused (§8).

---

## 3. Rulings

Eleven binding rulings. R3 is superseded by the tree and is kept, with the reversal recorded.

### R1 — Motion is a separate input, `animation_preset`; `preset` keeps its spelling and both its values

A third `preset` value cannot express the product. Motion and typography are independent axes; folding a third value in gives three points on one line when the requirement is a grid — "one brand type style holds across the sitting while motion varies per reel" is exactly the combination `preset` cannot name, and every future typography preset would need a static twin.

`preset` is not renamed, not deprecated, not decomposed. Its values stay `("default", "reel_pop")` (`remotion_caption_burn.py:581`), its enum stays `["default", "reel_pop"]` (`:125`), and every field it controls — including the pill at `TalkingHead.tsx:355` — stays under it. **Shipped as ruled** in `ff04355`; `test_talking_head_passes_the_preset_and_safe_zone_through` (`tests/tools/test_remotion_caption_burn.py:505-516`) still pins the pill decision on `captionPreset` at `:516`, which is the assertion that proves motion did not steal a colour decision.

**Rejected: `preset: ["default", "reel_pop", "reel_pop_static"]`.** It multiplies out, and it breaks the default-omission contract in a way nothing catches: `test_default_preset_stages_and_renders_exactly_as_before` (`:233-258`) only asserts on the `default` case.

**Rejected: renaming `preset` to `type_preset`.** Three tests exercise the Python input by name (`:136`, `:258`, `:531-585`) and both director skills spell it; the rename buys nothing.

### R2 — Three values — `none`, `fade`, `pop` — and every `reel_plan` entry carries one explicitly

`ANIMATION_PRESETS = ("none", "fade", "pop")` (`remotion_caption_burn.py:80`), with the schema enum written `list(ANIMATION_PRESETS)` (`:135`). Two of the three are names for behaviour that already shipped (§1.2); only `none` was new code.

**All three are settable, and the reel-batch director authors one on every entry.** This is not decoration: R8's gate compares the rendered value against the planned one, and a reel whose plan omits the field gives the gate nothing to bite on. A default-deny check on an optional field is default-allow. The schema property stays optional so the widening is monotone (R6); the **director contract** makes it always present, and G5 asserts that (§6.24).

**Rejected: a boolean `animate`, or `null` for off.** `lib/reel_plan.py:88` guards its carry-down with `if spine.get(carried)` — truthiness, not presence — so a falsy-but-meaningful value is silently dropped even when correctly registered. `"none"` is a truthy string; `False`, `0`, `null` and `""` are not. The enum-with-`none` design is mechanical, not stylistic.

**Rejected: dropping `fade` (two values, `none` and `pop`).** Under one batch typography — and reel-batch's is always `reel_pop` (`edit-director.md:313`) — dropping `fade` makes per-reel energy binary and removes the only middle setting, which is the stated outcome.

**Rejected: dropping `pop` and leaving it resolvable-but-not-requestable.** Then a reel that wants the batch's shipped motion must leave the field absent, and R8's comparison has no left-hand side on the common case.

**Rejected: a fourth value (`slide`, `typewriter`).** The levers that exist are `popScale`, `POP_DURATION_FRAMES` (`CaptionOverlay.tsx:120`) and the spring config (`:196-200`), and only the first is a `MotionStyle` field. Its own issue.

### R3 — **Superseded.** The subtractive design was specified; the additive `MOTIONS` design shipped in `ff04355`, and the reversal was correct

This ruling is kept rather than rewritten, because the disagreement it recorded is real and the tree settled it against this spec.

**What was ruled.** `PRESETS` untouched; `CaptionOverlay` resolves two locals — `entrance` and a possibly-zeroed `popScale` — from the preset it already holds, so `pop` means "*this* preset's pop", the tuned 0.4 gap always travels with the pop it was tuned for, and no floor is needed. `{preset: "default", animation: "pop"}` would then render identically to `{default, fade}`, since `default`'s `popScale` is 0.

**What shipped.** `MotionStyle {entrance, popScale, minWordGapRatio}` (`CaptionOverlay.tsx:45-53`), `MOTIONS` with `pop: {entrance: true, popScale: 0.16, minWordGapRatio: 0.4}` (`:58`), `resolveMotion` (`:74-78`), and a render style that overrides `popScale` from the motion and floors `wordGapRatio` at `Math.max(base.wordGapRatio, motion.minWordGapRatio)` (`:315-320`).

**Why the reversal was right, on the subtractive design's own evidence.** The subtractive design's stated advantage was that it never creates `{default, pop}` — a 0.16 pop against a 0 gap — and therefore needs no floor. It achieved that by making `{default, pop}` render *as `fade`*: an enum value that validates, reaches the props, and does nothing. That is the failure mode both this spec and the parent spec name repeatedly — a setting the renderer cannot honour — dressed as a defined semantics. The additive design makes the combination real and defends it with the floor, and the floor is not a patch on an invented collision: the collision is a fact about a 0.16 pop at any gap below 0.4, recorded at `CaptionOverlay.tsx:103-105` from a real 1080×1920 render. The comment at `:48-52` states the principle the reversal turns on — the 0.4 "was never an independent typographic choice — it was tuned to survive the peak of the pop" — so the gap belongs to the motion, and a feature whose thesis is that motion and layout stop travelling together is exactly the feature that must move it.

**And the test-churn argument was empirically false** (§2.4(i)): the shipped design changed no source-string assertion in any of the three tests, because it kept `style.popScale` as the read site.

**What survives the reversal, unchanged:** the preset key is resolved first, and an unknown preset degrades rather than throwing (`:69-78`, pinned at `tests/tools/test_remotion_caption_burn.py:854-860`) — the one clause of the specified design that was load-bearing and is in the shipped code verbatim.

**Consequence for the rest of this spec:** §1.2's table, §6.13-17 and W1.1 are baseline description, not work. Anyone implementing from this document implements Wave 1 by doing nothing.

### R4 — Absent means "the preset's own motion"; there is no default literal and no props key

`animation_preset` has **no** `default` in `input_schema` (`:133-147`, and the description says so in as many words at `:141-143`) and no literal in `execute()`'s default block. It is read as `inputs.get("animation_preset")` (`:661`); `None` means "resolve from `preset`", and **only an explicitly passed value emits `props["captionAnimation"]`** (`:406-407`, comment at `:403-405`).

This is what keeps every existing render byte-identical, and it is the shipped idiom rather than a new one (`:401-409`; `CaptionOverlay.tsx:322`). `test_default_preset_stages_and_renders_exactly_as_before` asserts `"captionPreset" not in props`, `"captionSafeZone" not in props` and `"captionAnimation" not in props` (`tests/tools/test_remotion_caption_burn.py:249-253`). `pipeline_defs/talking-head.yaml`, which passes no look inputs, renders exactly as today. **Shipped as ruled.**

**Rejected: `"default": "fade"` in the input schema.** Because `input_schema` is never validated (`tools/base_tool.py:255`, `:348`), the schema default and `execute()`'s literal would be two independent spellings — D4 again — and a `preset: "reel_pop"` call with no animation would resolve to `fade`, silently removing the pop from every reel-batch sitting and from `scripts/reel_batch_two_plane_demo.py:184-199`.

### R5 — One resolution table, in TypeScript. Python echoes what it sent, and says so

`MOTIONS` and `PRESET_MOTION` exist **once**, in `CaptionOverlay.tsx:55-67`, and the code says so (`:61-63`: "the ONLY copy of this table — Python deliberately holds none"). Python holds no copy.

`result.data["animation_preset"]` is therefore the value that went into the props — and **when nothing was asked for, no key is written at all**. `execute()` writes it at the one point both render paths converge (`:756-761`, comment at `:758-759`), guarded `if rendered_animation is not None`. On the fallback path the resolved value is `"none"` whenever anything was asked (`:711`). Pinned by `test_the_remotion_path_echoes_only_what_it_was_asked_for` (`tests/tools/test_remotion_caption_burn.py:773-799`): `run(preset="reel_pop", animation_preset="none").data["animation_preset"] == "none"`, and `"animation_preset" not in run(preset="reel_pop").data`.

**Corrected from the previous revision:** that revision said the value "stays `None`" for an unasked render. It does not — the key is absent, and `.data["animation_preset"]` raises. Any consumer must use `.get(...)` or test membership. §6.7 is corrected accordingly.

**Two symmetries were specified and not built, and W1.4 builds them** (§2.2.1): `result.data["degraded"]` on the Remotion path, so compose reads one key rather than choosing between `.get("degraded", False)` and `"degraded" in data`; and `requested_animation_preset` on the fallback, beside `requested_preset` (`:742`).

**Honest limit.** On the Remotion path this is a report of what the tool **sent**, not an observation of pixels. Nothing in Python watches the render, and nothing can: `TalkingHeadProps` opens `[key: string]: unknown` (`TalkingHead.tsx:313`), so a prop that is never destructured is dropped silently (**D5**). What actually polices the Python→TS boundary is the props-file assertion (`tests/tools/test_remotion_caption_burn.py:683-700`) and the node-executing resolution test (`:842-887`) — stated plainly rather than papered over.

**Rejected: a Python `_PRESET_MOTION` mirroring the TS table so `execute()` can echo a resolved value for an absent input.** It is a second spelling of a look decision, in the language `AGENT_GUIDE.md:80` reserves for tools and persistence ("No orchestration logic, creative decisions, review logic … in Python code"), and its only beneficiary is a caller that passed nothing — which under R2 is never reel-batch. It also creates drift a green CI cannot see: Python would report `"pop"` for a render TypeScript decided to fade.

### R6 — The value is per-reel and typed on `reel_plan.reels[]` — the dividing rule applied

`docs/intent/reel-batch-spec.md:206-209` is binding: "if a value is one-per-cut, or if any gate, reviewer or contract test must assert on it, it is a **typed schema property**. It must live on the cut and never as a side-map in `metadata`, because nothing enforces that such a map covers every cut." `metadata` stays legitimate for the three things `:211-213` names — opaque runtime hints already read as such, tool-internal telemetry no gate asserts, pipeline-private scratch. `animation_preset` is one-per-reel and G6 asserts on it (R8); it is none of the three.

**(a) The "one look" rule does not cover it.** Standing Bar rule 1 scopes the batch look to `grade` and `sharpen` (`executive-producer.md:27-30`); `batch_look`'s schema block is closed to `grade`, `grain`, `sharpen` (`edit_decisions.schema.json:263-271`). Captions appear in neither. And the *reason* the look is one-per-sitting does not generalise: "`cut_filters` takes a single `look` and only branches on provenance to raise" (`executive-producer.md:363-366`) — a picture-plane identity constraint with no counterpart in the text plane.

**(b) An existing gate already forbids the easy placement.** G5 asks, in as many words, "Per-reel axes are in reel_plan, NOT smuggled into edit_decisions.metadata?" (`executive-producer.md:225`), and the manifest repeats it as a `review_focus` line (`pipeline_defs/reel-batch.yaml:190`). A per-reel value beside `preset`/`safe_zone` in `metadata.caption_style` fails a gate on day one.

**(c) At reel granularity there is no side-map available anyway.** The entry object is `additionalProperties: false` (`reel_plan.schema.json:62`) and the only `metadata` is at the artifact root (`:65`). `backlot/state.py:513-514` hit the same wall independently.

**(d) The per-reel home dodges the `batch_look` trap by construction, and that is why `lib/reel_plan.py` is not edited.** `materialise` copies a fixed five-name tuple of **root** properties (`:81-89`), and `:70-75` records that omitting `batch_look` from it materialised five reels with `batch_look: None`, schema-valid and ungraded. It reads exactly four **entry** keys — `cut_ids` (`:52`, `:61`), `reel_id` (`:55`, `:65`), `music_asset_id` (`:62`), `subtitle_source` (`:64`) — and copies no others. A `reel_plan` entry property therefore never passes through the carry tuple. Compose already reads `entry["hook"]` (`compose-director.md:242`) and `entry.get("corrections")` (`:245-246`) straight off the entry; this ruling adds a reader (R7), not a carry. **A diff that touches `lib/reel_plan.py:81-89` for this feature is a design error.**

**Rejected: `edit_decisions.metadata.caption_style.animation_preset`.** It is the free path — `materialise` copies `metadata` wholesale (`lib/reel_plan.py:65`) while typed root properties need a hand-maintained edit — and that inverted incentive is what produced both shipped defects on this path (**D6**, **D12**). It also fails G5.

### R7 — One authoring site, one reader; `caption_style` is left exactly where it is

`animation_preset` is authored once, at `edit`, in the `reel_plan` emission (`edit-director.md:358-372`), and read once, at `compose`, off the entry, by the conditional-add idiom already used for `corrections` (`compose-director.md:245-246`) — i.e. **after** the `burn_inputs` literal that closes at `:244`, at `:247`, before the `execute` call at `:248`:

```python
if entry.get("animation_preset"):
    burn_inputs["animation_preset"] = entry["animation_preset"]
```

One name, one place. `edit-director.md:318-320` records the cost of the alternative — 3 is simultaneously `max_words_per_line`, `max_words_per_cue` and `words_per_page`, "three names for one figure, and they must not drift apart" (**D11**).

**`caption_style` does not move, and this feature does not make it typed.** Moving the per-sitting half onto a declared `edit_decisions.caption_look` root property is a genuine improvement and a genuine defect fix (**D12**) — and it is a different change. It requires a schema widening, a sixth name in the highest-blast-radius line in the pipeline (`lib/reel_plan.py:81-89`), a parametrised per-reel carry test, and a wholesale rewrite of `edit-director.md` §5 — and **no part of this feature's guarantee chain touches it**: the motion value lives on the reel entry and is read off the entry. Bundling it would put the change that can silently unstyle five reels into an epic that otherwise cannot. **D12** stays recorded, with its own issue.

**Rejected: a typed home on `subtitles`.** Dead on arrival — `materialise` rebuilds the block from three hardcoded keys and never reads the authored object (**D6**), so nothing written there reaches compose.

**Rejected: a batch-wide default in `caption_style` plus a per-reel override.** Two spellings of one figure, in exchange for saving four characters per reel.

### R8 — The rendered fact is recorded on typed `render_report.outputs[]` properties, joined to its reel

**(a) The tool.** `_render_remotion` already takes `animation_preset: str | None = None` (`:341`) and emits `props["captionAnimation"]` only when it is not `None` (`:406-407`); `execute()` echoes the sent value at the convergence point (`:756-761`) and the fallback resolves it to `"none"` (`:711`). W1.4 adds the two missing halves: `result.data.setdefault("degraded", False)` at that same convergence point, and `result.data["requested_animation_preset"] = animation_preset` beside `result.data["requested_preset"] = preset` (`:742`).

**(b) The artifact.** `schemas/artifacts/render_report.schema.json`'s `outputs[]` item (`:12-27`, closed at `:26`) gains three optional properties:

- `reel_id` — because a gate cannot compare "its reel's" plan without one. Today the join lives in **two** untyped places and neither is the validated artifact: `metadata.reels[]` (`:60`), which `compose-director.md:348-351` names authoritative, and the compose checkpoint's `metadata.partial_progress.reel_outputs`, which `backlot/state.py:539-543` reads with a filename-stem fallback below it (§2.4(k)). A gate asserting through an unenforced map is the shape R6 forbids; one optional string in the object already being widened closes it. `metadata.reels[]` stays as it is — it carries four other fields publish reads (`compose-director.md:333-338`, `:353-355`).
- `caption_animation` — the enum, from `burn.data.get("animation_preset")`.
- `caption_degraded` — the boolean, from `burn.data["degraded"]`, which W1.4 makes present on both paths.

**(c) The carve-out, stated rather than implied.** `compose-director.md:314-315` requires "every field probed from the file rather than copied from the plan". Motion is not recoverable by ffprobe from an mp4, and the burn tool is the only witness to which render path ran. These are the first non-probed fields in `outputs[]`, they come from the tool's result and not from the plan, and `:314-315` is amended in this change to say so. **And the paragraph that says the opposite is rewritten in the same commit:** `:348-351` currently states "`outputs[]` items are `additionalProperties: false` and carry no `reel_id`, so **reel identity cannot live there**". After W2.2 that is false; it becomes "`outputs[].reel_id` is the typed join; `metadata.reels[]` stays authoritative for the four fields publish reads". `backlot/state.py:513-514` gets the same one-clause correction (**D14**).

Declaring the property is not the same as writing it: there is **no Python builder for `outputs[]` anywhere** in `lib/` or `tools/` — the only author is the JSON fence at `compose-director.md:317-343` — so §6.22 sweeps that fence and §6.25 makes presence its own gate bullet, separate from correctness.

**(d) The gate.** G6 (`executive-producer.md:230-235`) gains two bullets:

> - Every `outputs[]` entry carries `reel_id`, `caption_animation` and `caption_degraded`?
> - Each entry's `caption_animation` matches that reel's `reel_plan.animation_preset` — or `caption_degraded` is true and a `warnings` line names the fallback?

That comparison is the point of the feature. Everything above exists so it can be answered without opening a file.

**Rejected: `render_report.metadata.reels[].animation_preset`.** It is `caption_style`'s mistake at the far end of the pipeline — a gate asserting on an unenforced map — and R6 forbids it.

**Rejected: extending `idempotency_key_fields` (`:202`).** Nothing computes the key for this tool (**D13**), so the cache hit it would prevent cannot occur; adding one look input while `preset`, `safe_zone` and `fps` stay out makes the list less coherent, and it changes shared tool metadata for both callers on the strength of a mechanism that does not exist.

### R9 — The new input joins the degradation contract; only the saturation it would inherit is repaired. **Landed**

The fallback burns a static SRT (`:483-538`) and can express no motion, so `animation_preset` is in the `dropped` tuple (`:726-731`) — **guarded on the explicit input**, not on a resolved value:

```python
(
    "animation_preset",
    animation_preset if animation_preset and animation_preset != "none" else None,
),
```

Guarding on a resolved value would put `"animation_preset"` in the list on every all-default fallback render, which is D1's bug in a new coat; the code says so at `:723-725`. `fps` was corrected in the same commit — `("fps", fps if fps != 30 else None)` (`:737`), matching the `preset` guard at `:722` — because a new entry is only legible in a list that is empty when nothing was dropped (**D1**).

`degraded` is **not** touched on the fallback path. It is set unconditionally at `:743` and that is correct (§2.4(g)). W1.4 adds it to the *Remotion* path, where its value is `False`; that is completing the report, not weakening the contract. `degraded` names the path; `unhonoured_inputs` names the diff.

**Rejected: repairing the whole contract in this epic** — guarding `font_size`, `words_per_page`, `highlight_color` and adding `overlays` (**D2**). It is a real defect, it is severable, and no assertion this feature makes reads `unhonoured_inputs`: G6 reads `caption_animation` and `caption_degraded`. It is also more subtle than a default guard, because `font_size` defaults to 52 while `_render_ffmpeg` hardcodes 24 (`:521`) — guarding against the tool default would report nothing precisely when the render dropped from 52 to 24. Its own issue, with its own predicate.

**Rejected: failing hard when Remotion is unavailable.** It converts a documented downgrade (`edit-director.md:343-346`; the operator escalation at `compose-director.md:455-457`) into a hard failure for both callers, for the benefit of one.

### R10 — `hero_title`'s `fontSize` and `staggerFrames` are not set here

They are reachable — `TalkingHead.tsx:228-236` forwards both — and `scripts/reel_batch_two_plane_demo.py:192-198` sets neither. This spec does not start, on four pieces of evidence:

1. **The width basis a computation would need is wrong where it is written down.** `HeroTitle.tsx:12-16` claims ~19 characters at 1080px; the real box is ~850px (**D10**). A constant derived from the docstring ships optimistic.
2. **The binding ceiling is vertical and belongs to another component.** `PositionedOverlay` sets `overflow: "hidden"` (`TalkingHead.tsx:293`) on a `height: 480` box (`:84`, `:91`). Any fontSize computation must budget 480px of height — a `TalkingHead` fact, not a `HeroTitle` one.
3. **The documented remedy does not work.** `HeroTitle.tsx:129` hardcodes `titleChars.length * 1.2` for the subtitle instead of using the prop (**D10**).
4. **It would land in the least-validated input class in the tool.** `overlays` are read raw at `:695` into the props at `:396`; `_validate_look` never mentions them, and the fallback drops them with nothing in `unhonoured_inputs` (**D2**). A computed `fontSize` that silently does not arrive is worse than a default that visibly does.

Sizing belongs to its own issue, with **D10**.

### R11 — `reel_id` keeps its name on an artifact thirteen pipelines produce

`grep -rln render_report pipeline_defs/` returns **13**: `screen-demo`, `character-animation`, `documentary-montage`, `reel-batch`, `hybrid`, `animation`, `talking-head`, `clip-factory`, `cinematic`, `animated-explainer`, `avatar-spokesperson`, `podcast-repurpose`, `localization-dub`. `lib/checkpoint.py:39` makes `render_report` the canonical `compose` artifact for every one of them. §2.4(c) did this arithmetic carefully for the *tool* and refuted a twelve-pipeline claim; it was not done for the *artifact*, and three new properties land on all thirteen.

**Ruling: the three properties keep their names, and twelve pipelines simply never write them.** `reel_id` is not spelled `deliverable_id`, and `caption_animation` / `caption_degraded` are not spelled generically.

The argument for a generic `deliverable_id` is real and is on record in this repo: `backlot/state.py:515-521` says per-reel cost is unreadable precisely because `cost_log` entries carry no `deliverable_id`. The argument against it wins here on two counts. First, this property is a **join key**, and a join key must spell the identifier it joins to: the only artifact that mints these values is `reel_plan.reels[].reel_id` (`reel_plan.schema.json:17-19`), and `metadata.reels[].reel_id` (`compose-director.md:333`) already spells it that way. A key named `deliverable_id` holding a `reel_id` in one pipeline and something else in another is the untyped side-map problem with a schema wrapper around it. Second, `caption_animation` and `caption_degraded` describe the **caption plane**, which twelve of the thirteen pipelines do not have; a generic name would invite them to fill it with something else.

The cost is stated, not hidden: three optional properties that are permanently absent for twelve pipelines. That is what optional means here, and no consumer breaks — `lib/checkpoint.py:733-741` reads `render_report` only to stamp `decision_log_ref`, and `tools/publishers/export_bundle.py:77` reads `outputs[].path` by name. A later pipeline that wants the same join adds its own property or renames this one deliberately; neither is blocked.

**Rejected: putting all three under a `caption` sub-object on the output item.** It buys nothing — the item is already closed, so the properties are already enumerable — and it puts `reel_id`, which is not caption-specific, inside a caption namespace.

---

## 4. Architecture

### 4.1 Data flow

Boxes marked **[shipped ff04355]** exist. Everything else is this epic's remaining work.

```
  edit-director  ────► edit_decisions.metadata.caption_style   { preset, safe_zone }
   (step 5)             one per sitting — typography + layout, UNCHANGED (R7)
        │
        └──────────► reel_plan.reels[].animation_preset      "none" | "fade" | "pop"
   (step 6)           one per reel, typed, on every entry (R2, R6)          W2.1
                                    │
                                    │  edit checkpoint: validate_artifact("reel_plan", …)
                                    │  lib/checkpoint.py:158-165 — the only validation there is
                                    ▼
  compose-director ──► burn_inputs["animation_preset"]  ◄── entry["animation_preset"]
   (step 3, :247)       conditional add AFTER the literal, beside corrections (:245-246)   W2.1
                                    │
      _validate_look ──► unknown value rejected before any side effect (:596-604, :666-671)
                                    │                                      [shipped ff04355]
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
             Remotion available              no Remotion / force_ffmpeg
                    │                               │
     props["captionAnimation"]              static SRT burn
       only when explicitly passed                  │
       (:406-407)  [shipped]                animation_preset      = "none"      [shipped]
                    │                       requested_animation_… = <asked>     W1.4
     TalkingHead :402 ─► CaptionOverlay      degraded              = True        [shipped]
       resolveMotion → entrance, popScale,   unhonoured_inputs    += "animation_preset"
       wordGapRatio floor  [shipped]                              [shipped]
                    │                               │
       animation_preset = <sent>, or NO KEY  [shipped]
       degraded         = False              W1.4
                    └───────────────┬───────────────┘
                                    ▼
  compose-director ──► render_report.outputs[]  { reel_id, caption_animation, caption_degraded }
   (step 5, :317-343)               │                                            W2.2
                                    ▼
                    G6 │ gate 3: publish — every entry carries the three fields,
                       │           and caption_animation matches its reel's plan
                       │           unless caption_degraded says why not          W3.1
```

### 4.2 Where each concern is authored

| Concern | Value | Scope | Home | Why there |
|---|---|---|---|---|
| Motion | `animation_preset` | per reel | `reel_plan.reels[]`, typed | G5 forbids per-reel axes in `edit_decisions.metadata` (`executive-producer.md:225`); the entry is the only per-reel typed object in the repo, and it has no side-map (`reel_plan.schema.json:62`, `:65`) |
| Typography | `preset` | per sitting | `edit_decisions.metadata.caption_style`, unchanged | Not widened here. A known side-map (**D12**), blocked by **D6**, its own issue (R7) |
| Layout | `safe_zone` | per sitting | `edit_decisions.metadata.caption_style`, unchanged | Already split from the preset in the renderer (`CaptionOverlay.tsx:322`); authored here and only here (`edit-director.md:321-323`) |
| Word gap | `wordGapRatio` | resolved | neither — `Math.max(preset, motion floor)` (`CaptionOverlay.tsx:320`) | The one parameter the split could not cleanly assign. It is typography's choice and motion's constraint, and the renderer takes the larger. Named, not claimed away (§8) |
| Rendered fact | `reel_id`, `caption_animation`, `caption_degraded` | per output | `render_report.outputs[]`, typed | R6 — a gate asserts on it, and cannot join on it today |

The asymmetry is deliberate: this spec puts the **new** value in the right place and leaves two **existing** ones where they are, rather than making a motion feature carry a look migration.

### 4.3 Schema changes

| Field | Location | Type | Why typed rather than `metadata` |
|---|---|---|---|
| `animation_preset` | `reel_plan` reel item (`reel_plan.schema.json:13-62`) | enum `["none","fade","pop"]`, optional in the schema, always authored by the director (R2) | One per reel, and G6 asserts on it. The entry is `additionalProperties: false` (`:62`) with no per-entry `metadata` — at reel granularity there is no side-map, so the dividing rule is not a preference here but the only shape the artifact can hold |
| `reel_id` | `render_report` output item (`render_report.schema.json:12-27`) | string, optional | Without it "its reel's plan" has no referent. Both joins that exist today are untyped (`:60`; `backlot/state.py:539-543`), and a gate cannot rely on either under R6 |
| `caption_animation` | `render_report` output item | enum `["none","fade","pop"]`, optional | The rendered fact the gate compares against the plan |
| `caption_degraded` | `render_report` output item | boolean, optional | The one bit that separates a downgrade from a defect. A `warnings` string (`:31-34`) cannot be joined to a reel |
| `animation_preset` | `remotion_caption_burn.input_schema` (`:133-147`) | enum built from `ANIMATION_PRESETS`, **no `default`** | **Shipped.** Not an artifact property; listed because its absence is meaningful (R4) and because `input_schema` is documentation only (`tools/base_tool.py:255`, `:348`) — the enum is enforced in `_validate_look` (`:596-604`), never by the schema |

All four artifact properties are optional additions to closed objects — the monotone widening this repo has landed **three** times (`provenance`, `polish`, `batch_look`; `docs/intent/reel-batch-spec.md:437-451`; `identity_lock` is not a fourth, §2.4(e)). Every artifact valid before stays valid after. Only `lib/checkpoint.py:165` validates them, reached through `_validate_artifacts_for_stage` at `:157`, which skips any name not in `ARTIFACT_NAMES` (`schemas/artifacts/__init__.py:13-36`; `reel_plan` at `:35`, `render_report` at `:25`). No runtime consumer rejects unknown keys, no test in this repo asserts an exhaustive property set on any artifact schema — the two exhaustive `set(...keys()) ==` assertions are both on tool-registry output (`tests/tools/test_hyperframes_compose.py:321`, `tests/tools/test_documentary_governance.py:119`) — the schema sweep is shallow and additive-safe (`tests/contracts/test_phase0_contracts.py:270-275` loads every schema and asserts `$schema`), and there are no fixtures to re-baseline.

**Blast radius of the `render_report` widening, counted rather than assumed.** Thirteen manifests produce `render_report` (R11 lists them); `lib/checkpoint.py:39` makes it the canonical `compose` artifact for all of them. The widening is monotone and no consumer rejects unknown keys: `lib/checkpoint.py:733-741` reads it only to stamp `decision_log_ref`, and `tools/publishers/export_bundle.py:77` documents its input as `render_report.outputs[].path`. The three properties are deliberately named for the caption plane and the reel (R11), so for twelve of the thirteen they are permanently absent — which is what optional means, and which is stated here rather than discovered by the next author.

Enforcement points, precisely: `reel_plan` is produced at `edit` (`pipeline_defs/reel-batch.yaml:182-184`), so its new property is first validated at the **edit** checkpoint. `render_report` is produced at `compose` (`:206-208`). `optional_artifacts_in` (`:203-205`) polices nothing — no Python reads it, and `_enforce_stage_prerequisites` gates on predecessor checkpoints; `compose-director.md:60` already documents that reel_plan is "functionally required" there despite the manifest. `SUPPLEMENTARY_ARTIFACTS` is not touched: it lives at `lib/checkpoint.py:45-51` and its only consumer repo-wide is one test assertion (`tests/lib/test_clip_ledger.py:245`).

**Declaring is not carrying.** `reel_plan` avoids the `batch_look` scar by construction (R6(d)) — but `render_report` inherits it in a new place: three declared properties with no Python builder behind them are three fields a schema-valid report can omit while looking correct. §6.22 and §6.25 are what close that, and they are load-bearing, not housekeeping.

The two JSON schemas cannot import `ANIMATION_PRESETS`, so this change ships two more hardcoded copies of the value set. §6.3 pins all three against the class constant; without that test, R4's single-sourcing is a claim rather than a mechanism.

---

## 5. Cost model

**A sitting costs $0.00 typical and $0.50 worst case, both unchanged.** This feature adds no call to any provider — and Wave 1 already landed at that price. It is priced rather than omitted, because an unpriced feature reads as an unexamined one.

### 5.1 Assumptions

1. Transcription is local faster-whisper and books nothing (`script-director.md:26-29`).
2. Both planes are local — ffmpeg for picture, Remotion for text (`compose-director.md:21-24`).
3. `animation_preset` is one props key, one lookup and two resolved fields. It changes no encode setting, no frame count and no codec: the render command at `remotion_caption_burn.py:421-429` is identical apart from the props file's contents.
4. No enum value routes to a different tool, provider or renderer. A look value must never imply a provider, or free-first reopens.

### 5.2 Derived figures

```
paid calls added                                = 0
typical sitting            ($0.00)   delta      = $0.00
worst case (5 AI flashes)  ($0.50)   delta      = $0.00
per-output-minute cap      ($0.75)   delta      = $0.00
render wall clock, animation = pop              = 0        (same curves, same frames)
render wall clock, animation = none             < 0        (one spring call fewer per page)
```

**Derived manifest values:** none. No `estimated_cost_usd`, no reservation, no ledger entry — `edit` has `tools_available: []` (`pipeline_defs/reel-batch.yaml:185`) and books nothing, and compose's ledger round-trip is unchanged because no new paid call is made.

### 5.3 The costs that are not money

Re-burns. `idempotency_key_fields` excludes every look input (**D13**), so a motion change neither reuses the wrong render nor skips the right one — the text plane simply re-encodes. Free either way; stated so §6.11 is not read as a caching claim.

Context. `docs/intent/context-cost.md:43-45` models the real bill as `total context-tokens ≈ 0.5 × peak × n_calls`, with accumulation at 84-86% of it (`:37`). One more per-reel field authored at edit, read at compose and asserted at G6 is a small addition to per-reel turns, in the maximal-accumulation shape. The ledger will honestly report $0.00 while the session's cost is elsewhere.

---

## 6. CI compliance checklist

Enforcement for the tool half is concentrated in `tests/tools/test_remotion_caption_burn.py` — now **887 lines, 41 test functions**, six sections (banners at `:43`, `:101`, `:168`, `:382`, `:588`, `:681`), three of which execute real TSX in node (`:435`, `:633`, `:802`). The artifact half is enforced by `tests/lib/`, where reel-batch's schema tests already live, with `tests/lib/test_edit_decisions_schema.py:67-95` as the widening template.

**Baseline must be captured green before the change**, and at `ff04355` it is: every item below that says "shipped" is a test that exists and passes today. Nothing in this checklist is an intended red. If anything below is red on the first run, the cause is the merge, not the design.

### Tool — `tools/video/remotion_caption_burn.py`

1. **Shipped.** `ANIMATION_PRESETS = ("none", "fade", "pop")` is declared at `:80`, **above** `input_schema` (`:82`) inside a class body that opens at `:53`, and the schema enum is written `"enum": list(ANIMATION_PRESETS)` (`:135`). A constant declared beside `PRESETS` at `:581` — later in the same class body — would raise `NameError` at import and take the tool registry down with it. `PRESETS` was **not** moved; **D4** stays recorded.
2. **Shipped.** The schema property's `description` (`:136-146`) states that absent means "whatever preset implies" and emits no prop. It should gain one clause when W1.4 lands, naming `pop` as a fixed 0.16 with a 0.4 gap floor rather than "the preset's own pop" — the description predates §1.2's correction.
3. A contract test asserts three-way agreement: `input_schema["properties"]["animation_preset"]["enum"]`, the `animation_preset` enum in `schemas/artifacts/reel_plan.schema.json`, and the `caption_animation` enum in `schemas/artifacts/render_report.schema.json` all equal `list(RemotionCaptionBurn.ANIMATION_PRESETS)`. **Not shipped** — the two schema enums do not exist yet. Lands with W3.2.
4. **Shipped.** `_validate_look` rejects any value outside the enum (`:596-604`), and the branch sits **above** the `safe_zone` early return at `:619-621` — `_validate_look` returns `None` there for every call that omits a safe zone, so a check appended after it would be dead for reel-batch's `{"animation_preset": "none"}` case. The placement is pinned by a bad-input row carrying no `safe_zone` (`tests/tools/test_remotion_caption_burn.py:119`) and acceptance by `:136` and `:139`.
5. **Shipped.** Rejection happens before the input-file check: `test_execute_refuses_a_bad_animation_before_touching_the_input` (`:157-165`) passes a bad `animation_preset` and a deliberately missing path.
6. **Shipped and load-bearing.** `test_default_preset_stages_and_renders_exactly_as_before` (`:233-258`) carries `assert "captionAnimation" not in props` at `:253`. This is the hard constraint on the whole feature; it must not be weakened by any later item.
7. **Shipped, and the previous revision of this item was wrong.** A `preset: "reel_pop"` call with no `animation_preset` emits no `captionAnimation` key and **writes no `animation_preset` key in `result.data` at all** — not `None`. The correct assertion is `assert "animation_preset" not in result.data`; asserting `result.data["animation_preset"] is None` raises `KeyError`. Already green as `test_the_remotion_path_echoes_only_what_it_was_asked_for` (`:773-799`), whose `:799` is exactly that assertion, and as `test_a_preset_without_an_animation_emits_no_animation_key` (`:693-700`) on the props side.
8. **NEW (W1.4).** An explicit `animation_preset` reaches `props["captionAnimation"]` (shipped, `:683-690`), is echoed in `result.data` (shipped, `:797`), **and `result.data["degraded"] is False` on the Remotion path** — which no shipped test asserts, because no shipped code sets it. Written as `result.data.setdefault("degraded", False)` at the convergence point beside `:756-761`, so both paths write the key and neither overwrites the other.
9. **NEW (W1.4).** The fallback writes `result.data["requested_animation_preset"] = animation_preset` beside `result.data["requested_preset"] = preset` (`:742`), and a test asserts it round-trips for a request the fallback could not honour. Place both tests in the `# --- motion` section (banner at `:681`), beside `:741-762` and `:773-799`.
10. **Shipped — moved out of this checklist.** `test_the_ffmpeg_fallback_admits_what_it_dropped` is now at `:531-585`, its dropped-set assertion at `:583` reads `{"preset", "safe_zone", "fps"}`, and that is **correct as written**, because that call passes no `animation_preset`. The previous revision instructed changing it to a four-element set, which would turn a green test red. Do not.
11. **Shipped — moved out of this checklist.** A fallback render with no look inputs reports `unhonoured_inputs == []` and `degraded is True`: `test_an_all_default_fallback_admits_dropping_nothing` (`:764-773`). **D1** is fixed, not "fixed here".
12. **Shipped — moved out of this checklist.** `animation_preset: "none"` on the fallback is not listed as dropped (`test_the_fallback_does_not_flag_an_animation_it_honoured`, `:750-762`); `animation_preset: "pop"` is (`test_the_fallback_reports_motion_as_none_and_says_it_dropped_it`, `:741-748`).

### Renderer — `remotion-composer/src/` — **all shipped in `ff04355`; verify, do not rebuild**

13. `CaptionAnimation` (`CaptionOverlay.tsx:43`), `MotionStyle` (`:45-53`), `MOTIONS` (`:55-59`), `PRESET_MOTION` (`:64-67`) and `resolveMotion` (`:74-78`) exist; `PRESETS` and `PresetStyle` are structurally unchanged (`:80-112`); `CaptionOverlayProps` carries `animation?: CaptionAnimation` (`:147`).
14. `PageRenderer` is where the change landed: its inline prop type takes `animateEntrance: boolean` (`:188`), `CaptionOverlay` resolves `base`, `motion`, `style` and `resolvedSafeZone` at `:311-322` and passes them at `:336-347`. The entrance `spring` stayed inside `PageRenderer` (`:196-200`), seeded off the per-`Sequence` frame; hoisting it into `CaptionOverlay` would break it.
15. The node-executing resolution test is `_resolve_motion` (`:802-839`) plus four tests (`:842-887`), used because "Source-string assertions cannot police this one" (`:805`) and because only running them tells `null` from `undefined`. Cases covered: `("default", undefined) → fade`, `("reel_pop", undefined) → pop` (`:842-851`), `("tiktok", undefined)` resolves rather than throwing (`:854-860`), `(reel_pop, "none") → entrance off, popScale 0` (`:863-867`), `("default", "pop") → minWordGapRatio 0.4` (`:870-876`). The `("reel_pop", "fade")` case is **not** covered and should be added with W3.2 — it is the only combination in §1.2's table with no executed assertion.
16. Under `none`, neither `opacity` nor `transform` is emitted on the page div — asserted on the source's conditional spread and on the absence of an identity-value else branch (`test_the_page_entrance_is_omitted_rather_than_neutralised`, `:878-887`), for the reason `CaptionOverlay.tsx:214-217` gives: an inert property still promotes the element to its own layer and shifts rasterization.
17. **No shipped assertion changed.** `:393`, `:402`, `:412`, `:432`, `:495` and `:502` are all still green against the shipped design (§2.4(i)). Verify, do not assume — and do not "update" them.
18. `test_talking_head_passes_the_preset_and_safe_zone_through` (`:505-516`) carries `assert "{...(captionAnimation ? { animation: captionAnimation } : {})}" in call` at `:512` — the truthy-spread idiom at `TalkingHead.tsx:402`, not the `!== undefined` idiom at `:401`. Its pill assertion at `:516` is untouched, pinning that motion did not steal the colour decision (R1).
19. `TalkingHeadProps` carries `captionAnimation?: CaptionAnimation` (`:330`), destructured at `:347`, forwarded at `:402`. Without the destructure the index signature at `:313` would swallow it silently with a green build (**D5**).
20. **`Root.tsx` is unchanged**, confirmed: `TalkingHead`'s registration and `defaultProps` (`:178-193`) carry none of the three look props, and the standalone `CaptionOverlayOnly` registration (`:256-270`) passes no preset. The other `CaptionOverlay` consumers are unaffected because `animation` is optional and `PRESET_MOTION` reproduces today's behaviour: `Explainer.tsx:877` and `CinematicRenderer.tsx:518`, neither of which passes a preset.

### Artifacts and libraries

21. `reel_plan.schema.json` accepts an entry with `animation_preset: "none"`, rejects `"slide"` (and `"Pop"`, `""`, `None`), and still validates a pre-change entry with the field absent — the three-part shape of `tests/lib/test_edit_decisions_schema.py:67-95`, in `tests/lib/`, **on a copy of `_plan()` rather than an edited fixture** (§1.4 rule 2). The invalid half is the one specs usually miss (`docs/PR_REVIEW_GUIDE.md:400-402`).
22. `render_report.schema.json` accepts an `outputs[]` item carrying `reel_id`, `caption_animation` and `caption_degraded`, rejects an out-of-enum `caption_animation`, and still validates the pre-change report built from `_output()` at `tests/lib/test_reel_plan.py:219-226` and validated at `:229-237`.
23. **`lib/reel_plan.py` is not modified.** Stating this is part of the checklist: a diff touching the carry tuple at `:81-89` for this feature is a design error (R6(d)). **This epic adds no `materialise` test** — `materialise` reads four entry keys (`:52`, `:55`, `:61-65`) and copies no others, so a test asserting the value survives the call would assert only that Python did not mutate a dict it never touched. Per §1.4 rule 3, this item does **not** forbid the sibling epic's single parametrised `materialise`-is-untouched test, which covers both per-entry properties at once.

### Skills, gates and manifest

24. `edit-director.md` authors `animation_preset` **on every entry**, and the entry-key set is enumerated in **five** places in that file — all five move together, or the file contradicts itself:
    - `:43-45` — the "`reel_plan` = the per-reel axes" list.
    - `:358-372` — the `reel_plan["reels"].append({...})` literal (add the property with the defaulted-vs-overridden citation the neighbouring fences carry; `script-director.md:84-86` is the model).
    - `:378-393` — the bullets that name each key's source and reader.
    - `:437-440` — the step-8 self-audit.
    - `:19` — the script-inputs row. **Excluded**: it enumerates what comes *from `script`*, and motion does not.
    Plus one cross-reference line in step 5 (`:299-323`) explaining why motion is per-reel while `preset` and `safe_zone` are per-sitting.
25. `compose-director.md` step 3 adds the conditional read **at `:247`** — after the corrections block at `:245-246`, before `burn = RemotionCaptionBurn().execute(burn_inputs)` at `:248`. Step 5's JSON fence (`:317-343`) carries `reel_id`, `caption_animation` and `caption_degraded` on every `outputs[]` entry; `:314-315` gains the carve-out from R8(c); and **`:348-351` is rewritten**, because it currently states that reel identity cannot live in `outputs[]`. A director-text assertion sweeps the fence for the three keys, in the style of the existing sweeps in `tests/contracts/test_agent_instruction_integrity.py:116-125`.
26. `executive-producer.md` G5's hand-enumerated key list (`:221-224`) gains `animation_preset` **and** `audio_offset_seconds` (**D15**) — the first truthful only because R2 makes the director author it on every entry, the second because the director already authors it (`edit-director.md:367`) and no gate checks it. G6 (`:230-235`) gains the two bullets from R8(d), and its stale `safe_zone` citation is corrected from `:125` to `:148-156` (**D8**).
27. **The citations in every fence this change rewrites are re-derived against the merged tree, last** (W3.3). W1.4 moves lines in `remotion_caption_burn.py`; a sweep run earlier writes fresh rot under a commit message that claims to remove it. The full inventory is in **D8**, itself already re-derived once against `ff04355`; a reviewer greps each cited symbol rather than trusting the diff.
28. **Neither edited director may contain `Compute Budget And Seed The Cost Ledger` or `On Approval — Arm the Tracker`** (em dash U+2014). `tests/contracts/test_pipeline_ledger_rollout.py:178-188` matches these as a heading suffix via `_has_heading_ending` (`:118-123`), but `tests/contracts/test_agent_instruction_integrity.py:382-391` matches them **anywhere in the file** — so a bare cross-reference in prose fails the whole pipeline's CI.
29. Any `tracker.reserve(` written into an example fence in an edited director must carry `user_approved=True`, swept by regex over the file text (`tests/contracts/test_agent_instruction_integrity.py:116-125`, the per-call loop at `:122-125`). This feature adds no reservation; the safe move is to add no such fence.
30. `pipeline_defs/reel-batch.yaml` — one `success_criteria` line on `compose` (`:229-233`) naming the comparison. No new stage key: stage objects are `additionalProperties: false` (`schemas/pipelines/pipeline_manifest.schema.json:151`), the root at `:196`, validated on every load (`lib/pipeline_loader.py:67-68`); and `required_artifacts_in` / `optional_artifacts_in` are inert prose (`compose-director.md:60` already documents that for `reel_plan`).
31. No new paid tool, no new provider, no `estimate_cost()` change. The BaseTool field changed is `input_schema` only, and that already landed; `idempotency_key_fields` (`:202`) is deliberately unchanged (R8, **D13**). Both are named in the PR body — tool metadata is user-facing (`docs/PR_REVIEW_GUIDE.md:139-162`).

### Acceptance — runnable

```bash
# baseline, before any edit — green at ff04355
python -m pytest tests/contracts tests/tools tests/lib -q

# tool half (W1.4)
python -m py_compile tools/video/remotion_caption_burn.py
python -m pytest tests/tools/test_remotion_caption_burn.py -q
python -m pytest tests/tools/test_remotion_caption_burn.py -q -k \
  "default_preset_stages_and_renders_exactly_as_before or bad_look_inputs or good_look_inputs"

# renderer half — regression only, nothing to build (node harness, no bundler)
python -m pytest tests/tools/test_remotion_caption_burn.py -q -k "motion or animation or pop or gap or entrance"

# artifact half
python -m pytest tests/lib/test_reel_plan.py tests/lib/test_edit_decisions_schema.py -q
python -m pytest tests/lib -q -k "animation or render_report"

# enum parity + director text
python -m pytest tests/contracts -q -k "animation_enum or agent_instruction or pipeline_ledger"

# whole-suite sweeps that see a director or schema edit the moment it lands
python -m pytest tests/contracts -q
python -m pytest tests/qa -q
```

---

## 7. Workstreams

Six remaining issues in three waves, plus a closed Wave 0. Dependencies are by title.

### Wave 0 — **closed by `ff04355`**

| # | Title | Status |
|---|---|---|
| W1.1 | `CaptionOverlay`: motion resolution, gated entrance spring, `PageRenderer` prop, `CaptionAnimation` type | Shipped `ff04355`, as the additive `MOTIONS` design (R3, §2.4(h)) |
| W1.2 | `remotion_caption_burn`: `ANIMATION_PRESETS` above `input_schema`, `_validate_look` branch above the safe-zone early return, `_render_remotion` parameter, conditional props key, fallback echo, `fps` guard, new dropped-list entry | Shipped `ff04355` (R1, R4, R9, **D1**) |
| W1.3 | Thread `captionAnimation` through `TalkingHead` to `CaptionOverlay`; confirm `Root.tsx` and the three other consumers need no change | Shipped `ff04355` (§6.19-20) |

### Wave 1 — the echo contract

| # | Title | Depends on | Effort |
|---|---|---|---|
| W1.4 | **Finish the echo contract.** `result.data.setdefault("degraded", False)` at the convergence point (`remotion_caption_burn.py:756-761`), so both paths write the key; `result.data["requested_animation_preset"] = animation_preset` in the fallback beside `:742`; two tests in the `# --- motion` section (`:681`). One clause added to the schema description (`:136-146`) naming `pop` as a fixed 0.16 with a 0.4 floor | — | S |

**W1.4 blocks W2.2.** Without it, `burn.data["degraded"]` raises on every successful render and G6's downgrade branch is unanswerable (§2.2.1). The alternative — writing `burn.data.get("degraded", False)` in the compose fence — is the guess R5 rejects by name, and it hides the difference between "not degraded" and "the tool did not say"; it is refused, and this line records that the choice was made rather than defaulted into.

### Wave 2 — the carriers

| # | Title | Depends on | Effort |
|---|---|---|---|
| W2.1 | `reel_plan.schema.json` gains `animation_preset` (§1.4 rule 1); `edit-director.md` authors it on every entry, updating **all five** enumeration sites (§6.24); `compose-director.md` reads it at `:247`; accept/reject tests on a `_plan()` copy (R2, R6, R7) | — | M |
| W2.2 | `render_report.schema.json` `outputs[]` gains `reel_id`, `caption_animation`, `caption_degraded`; `compose-director.md` step 5 records them; the `:314-315` carve-out; **the `:348-351` rewrite**; the `backlot/state.py:513-514` docstring clause (**D14**); director-text sweep (R8, R11) | W1.4 | M |

### Wave 3 — the gate

| # | Title | Depends on | Effort |
|---|---|---|---|
| W3.1 | G5's key list gains `animation_preset` **and** `audio_offset_seconds` (**D15**); the two G6 bullets; G6's `safe_zone` citation corrected (**D8**); the compose `success_criteria` line (R8(d), §1.4 rule 4) | W2.1, W2.2 | S |
| W3.2 | The three-way enum-parity contract test (§6.3) and the one missing resolution case, `("reel_pop", "fade")` (§6.15) | W2.1, W2.2 | S |
| W3.3 | Decision-log row in its own commit, number assigned at merge (§1.4 rule 5); re-derive every `remotion_caption_burn.py:` citation in the fences this epic rewrote, against the merged tree (**D8**) | all | S |

W3.1 is the issue that closes the feature. Until it lands, the value is declared, carried and rendered but nothing checks it — the state §2.2 describes, and the state this spec exists to leave.

**W3.3 must be last.** W1.4 moves lines in the file both directors cite; a citation sweep run in Wave 1 commits fresh drift under a message claiming to remove it. This has already happened once: the previous revision of this spec re-derived D8 against `c7d1285` while `ff04355` was landing, and every "actual" line number in that column was wrong by ~28 the moment it was written.

### Cross-spec ordering — binding, and identical in `caption-source-spec.md`

**This epic's remaining waves ship first; `caption-source-spec.md` ships second.** There is no data dependency between the two features — one decides at `script`, the other at `edit`, and they share no field — so the ordering is decided on state of tree:

1. **This feature is half-landed and currently inert.** `animation_preset` validates, reaches the props and renders, and no artifact authors it and no gate reads it. That is exactly the `batch_look` failure shape both specs cite (`docs/intent/reel-batch-spec.md:453-457`). Leaving it half-landed while a second epic churns the same five files is the higher risk.
2. **`caption-source-spec.md` has two unanswered operator questions** (its §8 Q1/Q2) that could still change its enum membership. This spec has none open.
3. **The better enumeration should land second.** `caption-source-spec.md`'s W2.2 already identifies all five `edit-director.md` enumeration sites; going second, it rebases onto this epic's edits and fixes both fields' entries in one pass.
4. **`caption-source-spec.md`'s W1.2 is fully independent** (`transcriber.output_schema` plus its parity test) and can land now, in parallel, ahead of everything here.
5. **Caveat, and it belongs to the sibling:** its W2.1 edits `skills/pipelines/reel-batch/script-director.md`, which carries an uncommitted 27-line insertion at `:276` that offsets every citation below it by +26. That change must be committed or discarded before its W2.1 is authored, or nine of its citations rot at once. Nothing in this epic touches that file.

---

## 8. Risks and open questions

### Resolved

1. **Does the "one look" rule forbid per-reel caption motion?** No. It names `grade` and `sharpen` (`executive-producer.md:27-30`), `batch_look`'s schema is closed to three keys (`edit_decisions.schema.json:263-271`), and the mechanism that forces one look — `cut_filters` taking a single look and branching on provenance only to raise (`executive-producer.md:363-366`) — has no counterpart in the text plane. R6(a).
2. **Can motion live beside `preset` in `caption_style`?** No, if it is per reel: G5 rejects that shape by name (`executive-producer.md:225`) and the manifest repeats it (`pipeline_defs/reel-batch.yaml:190`). R6(b).
3. **Is `none` configuration or code?** Code — and it is now written. The page entrance was ungated by any preset field; `ff04355` gated it (§2.4(a)).
4. **How many values, and how many are settable?** Three, all settable, all authored. R2.
5. **Does this need a new gate or a new approval?** No. It attaches to G5 and G6, which already exist; `edit` has no human gate (`pipeline_defs/reel-batch.yaml:186-187`), and reel-batch's three gates are fixed by decision #7.
6. **Subtractive or additive motion resolution?** Additive, decided by the tree rather than by this spec, and the reversal is right on the specified design's own evidence. R3, §2.4(h)-(i).
7. **Does `render_report` need a generic identifier?** No. `reel_id` keeps its name; twelve pipelines leave all three properties absent. R11.

No open questions remain against the operator.

### Review findings adopted, and the one refused

| Finding | Disposition |
|---|---|
| R3 contradicts shipped code; `MOTIONS` with a `minWordGapRatio` floor is what landed | **Adopted.** §1.2 rewritten as shipped behaviour; R3 marked superseded and kept with the reason the reversal was correct; §6.13-17 and W1.1-1.3 moved to baseline (§2.1, Wave 0) |
| `degraded` is never set on the Remotion path and `requested_animation_preset` does not exist; R8(b) would `KeyError` on every normal sitting | **Adopted.** §2.2.1, §2.4(j), W1.4 blocking W2.2, checklist items 8 and 9. The `.get("degraded", False)` alternative is named and refused in W1.4 |
| §6.7 asserts `result.data["animation_preset"] is None`, which raises | **Adopted.** Corrected to `not in result.data`, with the green pin at `:773-799` cited; R5's "stays None" sentence corrected |
| Both specs claim decision-log row #12 | **Adopted.** §1.4 rule 5: conditional #12/#13, assigned at merge, dated 2026-09-08 |
| Four (five) files edited by both specs with no order stated | **Adopted.** §1.4 in full, plus the cross-spec ordering paragraph in §7 |
| §6.9 / §6.23 contradict each other on a `materialise` test | **Adopted.** §1.4 rule 3: one parametrised test, owned by the second epic; §6.23 says so explicitly |
| Ordering: this epic's remaining waves first, then `caption-source-spec.md` | **Adopted**, with all five reasons and the `script-director.md` caveat recorded in §7 |
| Every burn-file citation is two commits stale, D8 included | **Adopted.** Header re-pinned to `ff04355`; every citation in this document re-derived and re-read; D8's "actual" column rebuilt |
| §6.10-6.12 describe work already done, at wrong lines, one of which would redden a green test | **Adopted.** Moved to §2.1 with shipped test names; item 10 now says explicitly *do not* change `:583` |
| `reel_id` on `outputs[]` contradicts `compose-director.md:348-351` and `backlot/state.py:513-514`, which W2.2 did not cover | **Adopted.** Both rewrites folded into W2.2; **D14** recorded; R8(b)'s "only" corrected to name the checkpoint join (§2.4(k)) |
| `render_report` is produced by 13 pipelines and the blast radius was never stated | **Adopted**, and ruled: R11 keeps the caption-scoped names and states the cost; §4.3 carries the count and the consumers |
| W2.1 named one of five `edit-director.md` enumeration sites | **Adopted.** All five listed in §6.24, with `:19` excluded and the exclusion justified |
| G5 enumerates nine of ten authored entry keys; `audio_offset_seconds` is ungated | **Adopted.** Recorded as **D15** and fixed in W3.1, in the same edit, since this epic ships first |
| `validate_artifact` is at `lib/checkpoint.py:164`, not `:165` | **Refused.** Verified by reading the file: `:164` is `try:`, `:165` is `validate_artifact(artifact_name, artifact_data)`, inside the loop whose `ARTIFACT_NAMES` skip is at `:158-159`. `docs/intent/reel-batch-spec.md:201` cites `:165` for the same call. The spec's citation is correct and is retained; recorded as §2.4(l) so the correction is not proposed a third time |
| `SUPPLEMENTARY_ARTIFACTS` is mislocated | **Not this spec's.** This spec cites it at `lib/checkpoint.py:45-51`, which is where it is; the mislocation is in `caption-source-spec.md` §6.3 and belongs to that spec's repair |
| `executive-producer.md:198`'s stale `beat_grid.py:449` citation | **Not this spec's.** It sits inside G2, a block only `caption-source-spec.md`'s W2.3 rewrites; assigned there, and §1.3 records the assignment so neither epic assumes the other did it |

### Objections raised in review and deliberately rejected

- **"Move `caption_style` to a typed `edit_decisions.caption_look` root property in the same change."** Rejected in R7. It is a real defect (**D12**) and a good change; it also requires a sixth name in `lib/reel_plan.py:81-89` — the line whose omission once materialised five ungraded reels (`:70-75`) — and a wholesale rewrite of `edit-director.md` §5, neither of which any guarantee here depends on. Bundled, it would put the change that can silently unstyle a batch into an epic that otherwise cannot.
- **"Repair the whole fallback dropped list — `font_size`, `words_per_page`, `highlight_color`, `overlays`."** Rejected in R9. Severable, no assertion here reads `unhonoured_inputs`, and the correct predicate is capability rather than default (`font_size` defaults to 52 while the fallback hardcodes 24, `:521`) — a different design question. Recorded as **D2** with its own issue.
- **"Extend `idempotency_key_fields` so a re-burn with different motion is distinguishable."** Rejected in R8. Nothing computes this tool's key (**D13**), so the cache hit it prevents cannot occur, and the change would alter shared metadata for both callers on the strength of a mechanism that does not exist.
- **"Drop `caption_degraded` — the bit is available from `burn.data['method']` and from `warnings`."** Rejected. `method` lives only in the compose agent's transient context and `warnings` is a free-text array that cannot be joined to a reel; without the boolean, a `caption_animation` mismatch reads as a defect when it is a downgrade, and G6 cannot tell them apart.
- **"Make an all-default fallback report `degraded: False`."** Rejected and refuted in §2.4(g). `degraded` names the render path.
- **"Have compose read `burn.data.get('degraded', False)` instead of adding W1.4."** Rejected in W1.4. It is the guess R5 rejects by name, and it collapses "the render was not degraded" into "the tool said nothing" — which is precisely the distinction G6's second bullet depends on.

### Risks

- **The half that shipped is inert until Wave 3 lands, and it is inert in the exact shape this repo has already been burned by.** `animation_preset` renders correctly today and no artifact can express it and no gate reads it. If this epic stalls after `ff04355`, the tree carries a validated, tested, documented input that nothing uses — `batch_look` before `lib/reel_plan.py` learned to carry it. Mitigated only by shipping W2.1 through W3.1.
- **`render_report`'s three new properties have no Python builder.** The only author of `outputs[]` is the JSON fence at `compose-director.md:317-343`; a report that omits all three is schema-valid, G6-blind and indistinguishable from a correct one. Mitigated by the director-text sweep (§6.25) and by G6's presence bullet being separate from its comparison bullet (R8(d)). Not eliminated: nothing in Python constructs the artifact.
- **Three caption-scoped properties now live on an artifact thirteen pipelines produce.** R11 rules the names stay; the cost is twelve pipelines whose `outputs[]` items carry three permanently-absent properties, and a future author who wants a generic join key inherits a rename rather than a blank slate. Named, not eliminated.
- **Nothing validates the materialised per-reel `edit_decisions` in production.** `validate_artifact` appears in exactly one reel-batch director (`publish-director.md:380`, `:402`); `compose-director.md:141-144` materialises and renders. The only validation of a materialised reel is a test (`tests/lib/test_reel_plan.py:159-172`). This feature's value does not travel through `materialise`, so it is not exposed to that gap — but a reader should not infer from this spec that compose validates.
- **The Python echo is a report of what was sent, not of what rendered.** R5 states the limit; `TalkingHeadProps`' index signature (`TalkingHead.tsx:313`) means a prop that is never destructured is dropped with a green build (**D5**). The props-file assertion (`:683-700`) and the node test (`:842-887`) are the only things standing between the two sides. Doctrine plus two tests, not a guarantee.
- **`materialise`'s carry guard is truthiness, not presence** (`lib/reel_plan.py:88`). `"none"` is safe because it is a non-empty string. Any future spelling of "off" as `False`, `0`, `null` or `""` is silently dropped. A trap set for the next person, not for this change.
- **The split narrows the fusion; it does not make the axes orthogonal, and `wordGapRatio` is where they still touch.** The shipped design resolves the gap as `Math.max(base.wordGapRatio, motion.minWordGapRatio)` (`CaptionOverlay.tsx:320`), so choosing `pop` on a preset with a tight gap silently widens that preset's spacing. That is correct — the gap was tuned for the pop (`:103-105`) — and it means "one brand type style holds across the sitting while motion varies" is true of stroke, case and face, and *not* of inter-word spacing. It is also only true at a fixed `fontSize`: `strokeRatio` and `wordGapRatio` are both fontSize-relative (`:273`, `:277`), so the ratios are the invariant and the pixels are not. And the pill stays keyed on `preset` (`TalkingHead.tsx:355`), so a colour decision is still made by a typography enum. Named rather than claimed away.
- **The overlay plane keeps a second, undeclared motion axis.** `staggerFrames` is forwarded (`TalkingHead.tsx:228-236`) and nothing computes it; its subtitle delay hardcodes `1.2` (**D10**). After this change the caption plane has a declared motion axis and the overlay plane does not. Deliberate asymmetry (R10).
- **The two planes use different coordinate systems and nothing reconciles them.** Captions position by frame fraction, validated to `[0, 0.5)` (`remotion_caption_burn.py:642-643`); overlays position by hardcoded pixels on a 1080×1920 assumption (`TalkingHead.tsx:78-101`), with `lower_third`'s `bottom: 320` commented "Above caption area (~1600px)" (`:80`) — hand-tuned against a caption position `safe_zone` can move. Not this feature's axis.
- **A doc-only half-landing is the worst outcome.** `docs/PR_REVIEW_GUIDE.md:426-427` notes that docs-only changes "can still create regressions by teaching users or agents the wrong behavior." A director rewritten to author `animation_preset` before the schema lands produces a plan that validates and a burn call that renders the requested motion but nothing that checks it; a compose fence rewritten to read `burn.data["degraded"]` before W1.4 lands raises on every reel. W2.2 depends on W1.4 for exactly that reason, and §6.25's `:348-351` rewrite exists because leaving a paragraph that says the opposite is itself the regression.
- **This spec's citations are not swept by CI.** Only `docs/intent/context-cost-spec.md` is pinned by name (`tests/contracts/test_agent_instruction_integrity.py`); `docs/intent/` is not swept wholesale. Every anchor above was read against `ff04355` on 2026-09-08, and the fact that the previous revision's entire burn-file citation base went stale in two commits — while that same revision was filing **D8**, the citation-rot defect — is the measure of how fast this rots.
- **Context cost dwarfs tool cost.** `docs/intent/context-cost.md:43-45` models the bill as `0.5 × peak × n_calls`, 84-86% from accumulation (`:37`). One more per-reel field and two more gate bullets is a small but non-zero addition, in the maximal-accumulation shape. Anyone reading `budget_remaining_usd` as "what this batch cost me" is materially wrong.

---

## Appendix — decision-log row

Appended to `docs/decision-log.md` after entry 11 (`:19`, dated 2026-09-04), in its own commit, under the existing header at `:7-8` (`| # | Date | Decision | Options considered | Ruling |`).

**Number assigned at merge — `12` if this epic lands first, `13` if `caption-source-spec.md` does; see §1.4 rule 5 and §7's cross-spec ordering, which puts this epic first.** Date is 2026-09-08.

| # | Date | Decision | Options considered | Ruling |
|---|------|----------|--------------------|--------|
| 12 | 2026-09-08 | **Where caption motion lives, and how the axes split** ([animation-preset-spec](intent/animation-preset-spec.md)) — `preset` fused five parameters into two values, only one of them motion, and "no animation" was unreachable: the page entrance spring drove `opacity` and `translateY` under both presets with nothing gating it (`remotion-composer/src/components/CaptionOverlay.tsx`, pre-`ff04355`) | a third `preset` value (`reel_pop_static`) vs a per-sitting `animation_preset` beside `preset`/`safe_zone` in `edit_decisions.metadata.caption_style` vs resolving motion **subtractively** from the preset the renderer already holds, leaving `popScale` in `PresetStyle` vs **a per-reel `animation_preset` typed on `reel_plan.reels[]`, resolved from a parallel `MOTIONS` record carrying its own scale and a word-gap floor** *(chose)* | **Motion is a per-reel typed property; typography and layout do not move.** `["none","fade","pop"]`, authored on every `reel_plan` entry at `edit`, read off the entry at `compose`, rendered by `resolveMotion(preset, animation)` (`CaptionOverlay.tsx:74-78`), which resolves the preset key first — an unvalidated preset degrades rather than throwing — and returns `{entrance, popScale, minWordGapRatio}`. `pop` is a fixed 0.16 with a 0.4 gap floor, so the newly-reachable `{default, pop}` cannot put a pop against a gap too tight to survive it (`:103-105`). **The subtractive design was specified and reversed:** it avoided the floor only by rendering `{default, pop}` as `fade` — an enum value that validates and does nothing — and its case rested on five source-string assertions it claimed would redden, none of which did (`tests/tools/test_remotion_caption_burn.py:393, :402, :412, :432, :495, :502`). The reversal is recorded in the spec rather than deleted. The metadata placement was refused by an existing gate (`executive-producer.md:225`). What rendered is recorded as typed `render_report.outputs[]` properties — `reel_id`, `caption_animation`, `caption_degraded` — because G6 must join a reel to its output and both joins that exist today are untyped (`render_report.schema.json:60`; `backlot/state.py:539-543`). `caption_style` stays an untyped side-map, recorded as a defect with its own issue. Renderer and tool shipped in `ff04355`; the artifact, director and gate follow. $0.00. |