# Branch review fixes — `feat/reel-batch` vs `main`

**Status:** specified, not started
**Derived from:** a 16-slice adversarial review of `feat/reel-batch` (193 agents, 46 findings
survived two-lens verification, 26 refuted), plus a four-mutant kill test of the caption axes.
**Scope:** 38 distinct defects. Every item cites `path:line` and was reproduced or read on this
machine. Findings already fixed by `6578149` are listed in §15 so nobody re-does them.

Each item is: **defect** — **fails when** — **fix** — **done when**.
Workstreams are ordered by blocking. One commit per workstream (decision #5).

---

## W1 — The pipeline cannot complete a batch  [CRITICAL]

**1.1 scene-director opens a corpus nothing writes** — `skills/pipelines/reel-batch/scene-director.md:65`
- Defect: `Corpus(PROJECTS_DIR / project_id / "corpus")`. `grep '"corpus"'` across `tools/` and `lib/`
  is empty; `cb4033c` moved the index to `projects/_footage_index/<pool>_<digest>` and updated
  idea- and asset-director but not scene.
- Fails when: any batch. Pool loads as zero rows, `pool = [r for r in corpus.records if
  r.identity_locked]` is `[]`, every cut becomes a false shortfall, step-7 asserts fail, gate 2 stalls.
- Fix: `corpus = Corpus(Path(brief["metadata"]["corpus_dir"]))` — the form `asset-director.md:131`
  already uses. Add the same "never rebuild it from `project_id`" note `idea-director.md:271` carries.
- Done when: a warm-index sitting reaches scene_plan with a non-empty pool, and a mis-resolved
  index raises instead of reading as a thin pool.

---

## W2 — Money and the audit log  [1 CRITICAL, 3 major/minor]

**2.1 An unreadable cost log is reported as corrupt** — `tools/cost_tracker.py:740`  [CRITICAL]
- Defect: `_read_ledger` folds `OSError` into `CostLogCorruptedError`.
- Fails when: permissions, a transient FS error, or an open handle. The prescribed recovery then
  quarantines and reconstructs — destroying an intact money audit log.
- Fix: add `CostLogUnreadableError` (NOT a subclass of `CostLogCorruptedError`), `except OSError`
  ordered before the content clause, message saying the contents were never examined — do not
  quarantine, fix access and retry. Drop `OSError` from the content tuple. Route
  `cost_log_path.exists()` in `__init__`/`_merge_from_disk` the same way, as `ClipLedger._ledger_exists` does.
- Done when: a chmod-000 ledger raises unreadable, not corrupt, and no recovery path runs.

**2.2 Real spend books as $0.00 on failure** — `tools/video/cutaway_gen.py:470`
- Defect: `total_cost += cost` sits after every guard; none of the five failure `ToolResult`s set `cost_usd`.
- Fails when: a clip is paid for on the pinned $0.10 route and a later guard fails. Reports
  `cost_usd=0.0` and a `total_cost_usd` omitting it.
- Fix: move `total_cost += cost` to immediately after `cost`/`provider` are assigned (`cost=0.0`
  for the cached branch); add `cost_usd=round(total_cost,4)` and `data={"cutaways":…, "total_cost_usd":…}`
  to every failure return in the loop.
- Done when: a forced post-payment failure reports the money already spent.

**2.3 A poisoned cache entry is permanent** — `tools/video/cutaway_gen.py:410`
- Defect: `_cached()` accepts any file >1 KB; nothing invalidates an entry the mandatory probe then refuses.
- Fails when: a partially-written clip. Every retry estimates $0.00, never calls the provider, fails forever.
- Fix: when `_probe(source)` fails and `cached` is true, unlink `source` and regenerate (or fail
  naming the discarded entry).
- Done when: a truncated cache file self-heals on the next run.

**2.4 A null money figure escapes shape validation** — `tools/cost_tracker.py:820`
- Defect: `_validate_ledger_shape` skips numeric fields whose value is JSON `null` — the bare
  `TypeError` it exists to prevent still escapes from the budget properties.
- Fix: sentinel, not truthiness — `value = entry.get(field, _MISSING); if value is _MISSING: continue`,
  so present-but-null falls through to the existing isinstance rejection.
- Done when: a `{"reserved_usd": null}` entry is rejected at load.

---

## W3 — The identity chain  [1 CRITICAL, 1 major]

**3.1 The gate judges one file, ffmpeg encodes another** — `tools/video/video_compose.py:1700`  [CRITICAL]
- Defect: the identity gate resolves a cut's asset first-row-wins (`assets_by_ref.setdefault`);
  `_render` resolves last-row-wins (`asset_lookup = {a["id"]: a for a in …}`, `:2000`).
- Fails when: two manifest rows share an asset id. The gate clears row A, ffmpeg grades row B —
  against the binding "his face is never regenerated" constraint.
- Fix: build both lookups from one shared helper, and either consider every matching row (block if
  ANY implies a contradicting provenance) or refuse a manifest with duplicate ids outright.
- Done when: a duplicate-id manifest is refused, or the gate blocks on the row `_render` will use.

**3.2 Implied provenance is last-write-wins** — `tools/video/video_compose.py:1710`
- Defect: `implied[cut.get("id")] = expected`.
- Fails when: two cuts share a cut id; a later `ai_generated` cut overwrites an operator cut's
  implied provenance and disarms the omitted-provenance look guard.
- Fix: resolve each cut's implied provenance inline in the check-5 loop from that cut's own
  `source`; the `implied` map is then unnecessary.
- Done when: duplicate cut ids cannot disarm the guard.

---

## W4 — `final_review` returns `pass` on broken renders  [2 major]

**4.1 A critical marker no emitter writes** — `tools/video/video_compose.py:3204`
- Defect: `"delivery promise violation"` matches no emitted string; the code sets the booleans
  `delivery_promise_honored` (`:3119`) and `runtime_swap_detected`.
- Fails when: either fires. Returns `status: "pass"` / `present_to_user`.
- Fix: branch on the booleans, not prose — `if promise_preservation.get("delivery_promise_honored")
  is False or promise_preservation.get("runtime_swap_detected"): status = "revise"`.
- Done when: a forced promise violation returns `revise`.

**4.2 Total audio loss is not critical, quiet audio is** — `tools/video/video_compose.py:3208`
- Defect: this branch made `programme audio too quiet` critical but left whole-track loss non-critical.
- Fails when: a render loses its audio stream. Returns `pass`; a merely quiet one returns `revise`.
- Fix: branch on `technical_probe.get("valid_container") and not technical_probe.get("has_audio")`,
  and move the loudness bookkeeping (`:2960-2971`) outside the `has_audio` guard.
- Done when: a silent render returns at least `revise`.

---

## W5 — Checkpoints and the decision log  [1 CRITICAL, 2 major/minor]

**5.1 A rejected checkpoint still persists its ruling** — `lib/checkpoint.py:730`  [CRITICAL]
- Defect: `_merge_decision_log` runs at `:730`; `validate_checkpoint` at `:746`.
- Fails when: a gate writes a schema-invalid ruling. The ruling persists to the canonical
  `decision_log.json`, and because the merge skips ids it has seen, the corrected re-write is
  silently dropped — the judgment is lost permanently.
- Fix: move the merge block (`:729-742`) after `validate_checkpoint`, or call
  `validate_artifact("decision_log", …)` at the top of it.
- Done when: a rejected write leaves the canonical log untouched and the corrected re-write lands.

**5.2 The merge is an unsynchronised read-modify-write** — `lib/checkpoint.py:612`
- Defect: the unique-tmp-name fix removed the crash, not the lost update. The regression test's
  assertion is too weak to notice.
- Fails when: two writers overlap; one decision vanishes.
- Fix: `fcntl.flock` (or an `O_CREAT|O_EXCL` lock file with retry) around `json.load(existing)` (`:517`)
  through the `os.replace`. Strengthen the test to assert BOTH decisions survive.
- Done when: a two-process race keeps both decisions.

**5.3 The legacy waiver swallows the whole validation** — `lib/checkpoint.py:258`
- Defect: keys on a single best-match error field, then waives the entire checkpoint validation.
- Fails when: an unrelated schema violation happens to rank below the `cost_snapshot` error — it rides through.
- Fix: waive per-error — re-validate a copy with `cost_snapshot` removed and re-raise if anything
  is still wrong (or use `iter_errors` and waive only matching ones).
- Done when: a legacy snapshot plus an unrelated violation still fails.

---

## W6 — reel-batch director contracts  [4 major, 2 minor]

**6.1 publish refuses the join compose now writes** — `skills/pipelines/reel-batch/publish-director.md:56`
- Defect: asserts `outputs[]` "carries **no** `reel_id` field", citing `render_report.schema.json:13-26`
  — the exact range this branch added it to. `6578149` fixed the same claim in compose-director but
  not here, so the two directors now contradict each other.
- Fails when: always. Publish falls back to filename-stem inference and reports identity as *read*.
- Fix: state that `outputs[].reel_id` is schema-declared, and make it the first fallback in the
  `if not by_reel:` block (`:86-95`): `rid = out.get("reel_id") or (stem match)`.
- Done when: publish joins on `reel_id` and only says "inferred" when it truly inferred.

**6.2 A cutaway renders ~1.3s short** — `skills/pipelines/reel-batch/asset-director.md:55`
- Defect: the booking fence hard-codes `flash_seconds: 0.6` for a slot scene-director sized as a
  full beat-grid interval.
- Fails when: any reel with a cutaway. Every cut after it drifts off the beat; no gate can catch it.
- Fix: carry the slot length (`scene-director.md:211` add `"length_seconds": length`) and use
  `"flash_seconds": min(sf["length_seconds"], MAX_FLASH_SECONDS)`. If sub-second flash is the real
  intent (spec §335), scene-director must not allot a full interval.
- Done when: rendered reel duration matches the planned grid.

**6.3 A 9.8s budget enforced only after the paid stage** — `skills/pipelines/reel-batch/edit-director.md:437`
- Defect: edit enforces 9.8s; script and scene gates bless 10.0s.
- Fails when: a 10.0s reel dies at edit — after `assets` has already spent money.
- Fix: push 9.8 upstream — `script-director` step 5 `window_end = min(window_start + 9.8, …)`,
  `scene-director.md:411` assert `<= 9.8`, G3 `<= 9.8`. Leave edit's guardrail as a backstop.
- Done when: an over-length reel is refused before any paid call.

**6.4 The word-extension breaks its own invariant** — `skills/pipelines/reel-batch/script-director.md:466`
- Defect: step 5 moves `window_end` past the last grid line but never updates `snap_grid`.
- Fails when: the extension fires. Step 9's `snap_grid[-1] == window.end_seconds - window.start_seconds`
  fails, and the cut list still ends on the pulled-back boundary the extension exists to undo.
- Fix: restate the final boundary after the tail loop — `snap_grid[-1] = round(window_end - window_start, 3)`.
  Boundary count is preserved, so the `cuts + 1` guard still holds.
- Done when: an extended reel passes step 9 and ends on the extended boundary.

**6.5 The spine skeleton writes `batch_look` where step 4 forbids** — `skills/pipelines/reel-batch/edit-director.md:102`
- Defect: step 1's copyable skeleton authors `batch_look` inside `metadata`; step 4 and the step-8
  gate both require the spine root and explicitly forbid the metadata spelling.
- Fix: move `"batch_look": {...},  # step 4 — spine ROOT, not metadata` out of `metadata`, beside `subtitles`.
- Done when: the skeleton an agent copies passes G5 unedited.

**6.6 `caption_confidence` is never actually compared** — `skills/pipelines/reel-batch/compose-director.md:423`
- Defect: authored, carried into `reel_plan`, asserted-present by two gates — but the
  approval-vs-render comparison the schema and edit-director both describe is instructed nowhere.
- Fix: add one step-5/6 bullet comparing `burn.data["word_confidence"]` against
  `entry["caption_confidence"]`, recording the pair in `final_review.metadata.per_reel`, and treating
  a drop below the approved `min` as a finding.
- Done when: a degraded transcription fails G6 instead of passing silently.

---

## W7 — The ledger rollout across the other pipelines  [3 major, 1 minor]

**7.1 The arming block reads a key no producer writes** — `skills/pipelines/*/idea-director.md`
(`avatar-spokesperson:103`, `hybrid:110`, and every copy carrying the same block)
- Defect: reads `metadata["cost_estimate"]["line_items"]` (plus `li["tool"]`, `li["estimated_usd"]`,
  a bare `approved_budget_usd`); the seeding instruction two lines earlier records
  `metadata.cost_estimate` as a **scalar total**.
- Fails when: always. The arm step consumes fields nothing writes.
- Fix: port the producing snippet from the proposal-director rollout — build `line_items` as
  `{tool, operation, quantity, estimated_usd}` in the same loop that calls `tracker.estimate(...)`,
  and assign the object form as `reel-batch/idea-director.md:363` does.
- Done when: a contract test asserts every arming block's reads have a producer in the same file.

**7.2 A card set is priced as one card** — `skills/pipelines/podcast-repurpose/idea-director.md:116`
- Defect: passes `count` into `image_selector.estimate_cost()` and books the raw return.
- Fails when: any multi-card run. The approval gate and the seeded ledger both understate spend.
- Fix: multiply outside the call, as the proposal-directors do:
  `unit = image_selector.estimate_cost({...}); tracker.estimate("image_selector", f"quote_cards x {n}", round(unit*n, 4))`.
- Done when: the gate figure matches `n × unit`.

**7.3 A guard claim that is false** — `skills/pipelines/localization-dub/asset-director.md:69`
- Defect: says a mid-run added language is stopped by the first-paid-use guard; that guard keys on
  the tool name (`tts_selector`), already approved at the idea gate.
- Fails when: a language is added mid-run — it reserves and spends, no guard fires.
- Fix: replace the claim with the mechanism: an added language reuses an armed tool name, so the
  agent must return to the idea gate and re-arm before spending.
- Done when: the instruction describes what actually happens.

**7.4 Resume sweeps the ledger after spending** — `skills/meta/checkpoint-protocol.md:214`
- Defect: "Sweep the ledger" is step 5, after step 4 "Continue generation" — contradicting the
  governance section it points at.
- Fix: move the sweep to step 2, right after `get_next_stage`.
- Done when: stranded-entry escalation completes before any further spend.

---

## W8 — The persistent footage index  [3 major, 1 minor]

**8.1 The conflict refusal is default-allow** — `tools/video/footage_library.py:845`
- Defect: `_index_conflict` returns `None` whenever `measurements.json` is unreadable or absent, so
  both refusals it exists to make (re-chunking, a raised sharpness floor) are silently skipped.
- Fails when: the sidecar is missing. The corpus keeps two overlapping chunkings.
- Fix: derive the conflict from the corpus rows (they already carry `start_seconds`/`end_seconds`
  and `sharpness`); move the floor check above the `if not recorded` short-circuit.
- Done when: deleting the sidecar does not disable the refusal.

**8.2 Stale rows survive an in-place re-encode** — `tools/video/footage_library.py:331`
- Defect: nothing invalidates rows when a pool file is re-encoded or trimmed in place. Old segments
  overlap the new ones, stay `identity_locked` and selectable; `dead_source_rows` cannot see them
  because the path still exists.
- Fix: stamp a source fingerprint (size + `mtime_ns`, or duration) on each `ClipRecord`; on load,
  treat mismatched rows as dead and exclude them.
- Done when: re-encoding a pool file drops its old segments.

**8.3 The sharpness normaliser only works at exact multiples** — `tools/video/footage_library.py:732`
- Defect: `_normalise_for_sharpness` quantises to an integer box factor, so it normalises only at
  integer multiples of 1920; off-multiple resolutions keep up to a 3.7x residual bias (10x across a
  bucket boundary), and the fixed floor of 60 still reads resolution rather than focus.
- Fails when: 2560, 2704, 3000-wide footage — the better camera's clips score worse.
- Fix: resample to the exact target long side (`1920/max(h,w)`) instead of an integer factor; extend
  the test to sample between the multiples.
- Done when: sharpness rank is stable across resolutions of the same clip.

**8.4 Two indexers of one pool collide** — `tools/video/footage_library.py:816`
- Defect: `_save_measurements` writes a fixed sibling `measurements.json.tmp`, unlocked.
- Fails when: concurrent indexing — one writer's measurements are lost, the other crashes out of
  `execute` with a raw `FileNotFoundError`.
- Fix: per-writer tmp name as `lib/checkpoint.py:608` does (`f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp"`),
  unlink on failure; add the `flock` `_locked()` idiom if the lost update matters.
- Done when: two concurrent indexes both complete.

---

## W9 — Batch write collisions  [1 major]

**9.1 Two reels swap captions** — `tools/video/remotion_caption_burn.py:493`
- Defect: the ffmpeg fallback writes its scratch SRT to a **whole-second**-resolution filename in a
  directory every reel of the batch shares.
- Fails when: two burns overlap. Captions swap between reels, with no error. Reproduced: two
  concurrent `_render_ffmpeg` calls produced one file with the wrong captions and one gone, both
  returning `success=True`.
- Fix: use the sibling idiom already in this branch (`tools/video/video_compose.py:509`) — key the
  scratch name on the output path AND a nanosecond token.
- Done when: concurrent burns keep their own captions.

---

## W10 — Declared vs returned  [1 major]

**10.1 `beat_grid` declares 10 keys, returns 21** — `tools/analysis/beat_grid.py:224`
- Defect: the 11 undeclared keys include `roll_seconds`, `n_beats`, `n_bars`, `n_events`,
  `n_phrases`, `n_rolls`, `energy_phases`, `proxy_path` — exactly the fields reel-batch's
  script-director branches its cut-policy ladder on.
- Fix: add all eleven to `output_schema["properties"]`; mirror the declared-vs-returned contract
  test `b35c42e` added for the transcriber.
- Done when: a contract test asserts `set(returned) <= set(declared)` for `beat_grid`.

---

## W11 — Backlot board  [4 minor]

**11.1** `backlot/ui/board.js:886` — the Renders header counts an un-captioned `<reel_id>-picture.mp4`
with no finished sibling as a deliverable, and it becomes the hero player. Fix: partition on the
`-picture.<ext>` stem rather than the sibling-conditional `intermediate` flag.

**11.2** `backlot/state.py:695` — `_find_poster` and `summarize_project.render_count` ignore the new
`intermediate` flag, so a five-reel batch shows "10 renders" and posters the picture master. Fix:
`deliverables = [r for r in renders if not r.get("intermediate")]` in both.

**11.3** `backlot/state.py:616` — `_resolve_reel_output` treats a relative `reel_outputs` path as
project-relative; every form compose-director teaches is repo-relative, so the new checkpoint branch
never fires. Fix: retry against `REPO_ROOT` (already imported at `:17`) before giving up.

**11.4** `backlot/ui/board.js:847` — the reel poster `<img>` has no `onerror`, so a video with no
extractable poster frame shows a broken-image icon. Fix: reuse the existing `reel-pending` treatment.

---

## W12 — Renderer and misc  [4 minor]

**12.1** `remotion-composer/src/components/CaptionOverlay.tsx:254` — `safeZone.sides: 0` is discarded
by a truthiness test and renders as the legacy 80% width, the opposite of the declared 0, even though
the tool's validator accepts 0. Fix: `safeZone?.sides !== undefined ? … : "80%"`. Add a
`{"bottom":0.18,"sides":0}` regression case.

**12.2** `lib/source_media_review.py:106` — sampled frames go to a directory keyed only on
`path.stem`, so two pool files sharing a basename overwrite each other's frames and both report the
same wrong `representative_frames`. Fix: key on a hash of the resolved path.

**12.3** `pipeline_defs/reel-batch.yaml:32` — `max_wall_time_minutes: 20` is below this branch's own
measured cold-index time (1171.8s on the operator's 67-file pool, decision #11), and the EP says the
cap covers indexing, so a healthy first sitting is told to stop and escalate. Fix: raise to ~45, or
scope the cap to a warm-index sitting in both the manifest and the EP table.

**12.4** `scripts/reel_batch_gate_dry_run.py:36` — the CLIP dict priced is not the payload
`cutaway_gen` builds; it omits the price-bearing `model_variant`, so the headline $0.50 is right only
because kling's default variant happens to equal the pin. Fix: build CLIP from the exported constants.

---

## W13 — Test gaps the mutants exposed  [3 surviving mutants, 2 minor]

A four-mutant kill test against `6578149` + the full suite: **3 of 4 survived.**

**13.1 Nothing stops compose re-adding a Python-side motion default**
- Mutant: `burn_inputs["animation_preset"] = entry.get("animation_preset") or "pop"` — 183 tests green.
- Why it matters: decision #12 rules the `preset → motion` table lives in TypeScript **only**, because
  "a Python copy would put one table in two languages with nothing pinning them equal". This mutation
  re-creates exactly that, and absence stops meaning "let the preset decide".
- Fix: assert `compose-director.md` reads `entry["animation_preset"]` under an `if` and contains no
  `or "pop"` / `.get(..., "pop")` default — the same shape as
  `test_reel_batch_compose_still_records_what_it_rendered`.

**13.2 Nothing pins a markdown enum literal to the enum**
- Mutant: `"animation_preset": "slide"` in `edit-director.md:385` — 183 tests green. `slide` is not in
  `ANIMATION_PRESETS` (`{none, fade, pop}`, pinned in three places). An agent following the instruction
  authors an invalid `reel_plan` and only fails at runtime schema validation, mid-sitting.
- Fix: one contract test extracting `"animation_preset": "<literal>"` from every reel-batch director
  and asserting membership in `RemotionCaptionBurn.ANIMATION_PRESETS`.

**13.3 Nothing pins the G6 gate bullets**
- Mutant: deleting the G6 motion-parity bullet from `executive-producer.md` — 183 tests green.
- Why it matters: with 13.1, this is the whole hole — edit authors one value, compose silently
  substitutes `pop`, and no gate compares. `6578149` hardened the compose *fence* (killing the
  `reel_id` mutant) but left the *gate* that reads it unpinned.
- Fix: assert each G-gate's load-bearing bullets are present by keyword, as
  `test_agent_instruction_integrity.py` already does for compose's `entry_out` keys.

**13.4** `tests/tools/test_beat_grid.py:278` — `test_wrapper_reproduces_the_analyser_exactly` calls
`execute()` with no `output_dir` and no chdir, writing analysis artifacts into the developer's
checkout at `projects/_analysis/`. Fix: pass the `tmp_path` the test already receives.

**13.5** `tests/tools/test_beat_grid.py:170` — `test_status_degrades_when_a_python_dep_is_missing`
never reaches the librosa probe on a machine without ffmpeg (the exact environment its
"no heavy deps needed" header targets) because it stubs `import_module` but not `shutil.which`.
Fix: `monkeypatch.setattr(beat_grid_module.shutil, "which", lambda n: "/usr/bin/" + n)`.

---

## 14. Not in scope

- Estimate/execute divergence reaching the ledger — ruled out of scope in decision #10.
- `backlot/state.py` bypassing `read_checkpoint` — known and accepted in decision #4.
- Cross-batch clip reuse — ruled processing-cost-only in decision #11.

## 15. Already fixed by `6578149` — do not re-open

- `compose-director.md:376` prose contradicting `outputs[].reel_id` — rewritten.
- G6's motion-parity bullet conditioned on `caption_source` — now unconditional, joins on
  `outputs[].reel_id`, escapes only on `caption_degraded`.
- `render_report.schema.json`'s `caption_animation` enum unpinned — now the third assertion in
  `test_the_motion_enum_is_spelled_the_same_in_the_schema_and_the_tool`.
