# Epic 1 Review — Fix Specification

Status: **specified, ready to implement** (2026-09-01).
Source: adversarial multi-agent review of branch `feat/epic1-cost-governance` vs `main`
— 28 confirmed findings (every one survived 3-vote refutation panels; 0 refuted; the two
worst reproduced empirically, one against `projects/how-neural-networks-learn` on this
machine). Fix specs drafted per workstream, then design-reviewed through three lenses
(coherence, completeness, adversarial design-soundness); all 22 panel issues are
resolved inline in the sections below, marked "panel ruling/fix/addition/extension".

The full test suite is green today (1854 passed) — several findings exist *because*
the guarding tests are lexical. Every spec item names its red-check: the edit that
must turn the new test red.

## How to read this document

Seven workstreams (A–G) plus one housekeeping item (H1). Each item carries **Fix**
(exact file/function/change), **Why this design** (with the losing alternative),
**Acceptance** (behavioral tests, file + name + arrange/assert), and **Risk**.
Line anchors were verified against the branch working tree at spec time; workstreams
A and B reshuffle `lib/checkpoint.py` and `tools/cost_tracker.py`, so re-read anchors
off the tree at implementation time — the specs cite by symbol wherever an anchor
would rot.

## Finding → fix map (traceability)

| # | Finding (severity) | Fix item |
|---|---|---|
| 1 | Legacy cost_snapshot tolerance missing from prerequisite check — legacy projects deadlock (MAJOR ×2) | A1 (+G3, G8a) |
| 2 | decision_log self-heal KeyError / AttributeError / double-absorption (MAJOR ×2) | A2 |
| 3 | Ledger wired into only 6 of 12 episode pipelines (MAJOR) | D0–D1.6 |
| 4 | context-cost-spec §2 instructs the exact decision-log fork the branch outlaws (MAJOR) | F1 |
| 5 | Compose books narration as `openai_tts`, proposal armed `tts_selector` — guard trips on approved work (MAJOR) | C2 |
| 6 | No test that `user_approved=True` doesn't waive cap/first-use guards (MAJOR) | G1 |
| 7 | Ledger `_save` non-atomic, `_load` crashes on corruption (MAJOR) | B1 |
| 8 | No locking/reload — concurrent trackers erase each other's spend (MAJOR) | B2 |
| 9 | Arming fallback leaves zero headroom vs the 10% holdback — final approved reserve always trips (MAJOR, critic) | C1 |
| 10 | `narration missing` critical fires on unmeasured/quiet audio (MINOR ×2) | E1 |
| 11 | ebur128/volumedetect decode full video; timeout silently skips the LUFS gate (MINOR) | E2 |
| 12 | Phantom spend: `result.cost_usd or estimated_usd` books estimates on failed calls (MINOR) | C3 |
| 13 | Stranded reservations after a crash — no recovery path (MINOR) | B3 + C6 |
| 14 | doc-montage `music_gen.estimate_cost` examples omit required `duration_seconds` (MINOR) | C4 |
| 15 | context-cost-spec stale `#L435` anchor (MINOR) | F3 |
| 16 | final_review honesty tests are lexical, never execute the gates (MINOR ×2) | G2 (+E acceptance) |
| 17 | `get_latest_checkpoint` tolerance copy untested (MINOR) | G3 (+A1 helper) |
| 18 | Reserve-flag/quantity contract guards cover explainer only (MINOR) | G4 |
| 19 | `resolve_playbook_path` custom branch untested on clean checkout (MINOR) | G5 (+H1) |
| 20 | `reconcile(success=False)` untested (MINOR) | G6 (+B3, C3) |
| 21 | context-cost-spec still says proposed/HELD while the branch ships the rule (MINOR, critic) | F2 |
| 22 | $10 vs $15 divergence: ARCHITECTURE.md text + CostTracker constructor default (MINOR, critic) | F4 + B4 |
| 23 | False "placeholders double-count" rationale (NIT) | C5 |
| 24 | Scoping-test docstring overstates coverage (NIT) | G7 |
| 25 | Untracked `styles/custom/` — neither committed nor ignored (housekeeping) | H1 |

## Implementation order

Wave boundaries are hard where marked; items inside a wave are independent.

1. **Wave 1 — code, independent:** A (`lib/checkpoint.py`), B (`tools/cost_tracker.py`,
   B1+B2 land together), E (`tools/video/video_compose.py`). H1 anytime.
2. **Wave 2 — skill canon:** C. Lands with or after B (C6 names B3's
   `non_terminal_entries()` and B1's `CostLogCorruptedError`).
3. **Wave 3 — rollout:** D. Hard dependency on the panel-extended C1/C2/C3/C6 —
   landing D first would propagate the pre-fix wording.
4. **Wave 4 — docs & tests:** F (F3 after A; F4 with/after B4; F1/F2 anytime) and G
   (G2 after E; G8a rides A's PR; the rest anytime).

## H1. Housekeeping — untracked `styles/custom/`

`styles/custom/` (currently `backward-pass.yaml`, `evidence-room.yaml`) is the output
directory of `lib/playbook_generator.save_playbook()` — generated content. **Fix:** add
`styles/custom/` to `.gitignore` alongside the other generated-output entries
(`projects/`, `output/`). This also makes permanent what G5 fixes structurally: tests
must never depend on locally-generated playbooks existing.
**Open question (the one user decision in this spec):** if `backward-pass` and
`evidence-room` are meant to be *shared* styles rather than run-local output, commit
them deliberately instead — say which, and the .gitignore entry then carries an
exception comment or the files move to `styles/`.

## Consolidated dependencies (from all workstreams)

- B1 and B2 are one change — never land separately.
- C6 lands with or after B; D lands with or after C (extended C1 included).
- G2 lands after E; G8a rides A; F3's anchors finalize after A; F4 lands with/after B4.
- D's explainer round-trip subsection lands as one edit with C2/C3's changes to the
  same file (C owns the TTS text, D owns the heading+render block).

---


---

# Fix spec — Workstream A: `lib/checkpoint.py`

Status: **spec for confirmed review findings** on `feat/epic1-cost-governance`.
Scope: Python only, both findings in `lib/checkpoint.py`. No schema changes, no new
dependencies. Workstream B is independent (it only *copies* write_checkpoint's tmp+`os.replace`
idiom — cited by **symbol**, not line: A's own insertions shift every line number in
this file, so sibling specs' line anchors are re-read off the final tree after A lands).

---

## A1. Legacy cost_snapshot tolerance missing from `_enforce_stage_prerequisites` (`lib/checkpoint.py:330`, MAJOR ×2 — python-correctness + schema-contract)

The branch defined the read-side tolerance twice (read_checkpoint:625-638,
get_latest_checkpoint:660-673) and forgot the third validator of already-written
checkpoints. Result: legacy projects read fine, `get_next_stage` says proceed, and
`write_checkpoint` of the next stage deadlocks with PREREQUISITE VIOLATION. The fix is
to make the tolerance have exactly ONE definition and use it at all three sites — a
fourth copy-paste would recreate this bug at the next validator someone adds.

### Fix

`lib/checkpoint.py`. Extract the tolerance into a module-level helper, placed directly
after `validate_checkpoint` (after line 204):

```python
def _validate_tolerating_legacy_cost_snapshot(
    checkpoint: dict[str, Any], source: Path
) -> None:
    """validate_checkpoint(), tolerating exactly the legacy cost_snapshot shape.

    The single definition of the read-side tolerance, used by EVERY path that
    validates an already-written checkpoint (read_checkpoint,
    get_latest_checkpoint, _enforce_stage_prerequisites). cost_snapshot was
    closed to extra keys after legacy files were written; the schema gates
    new writes, so legacy files must stay both readable AND advanceable —
    a predecessor a read path accepts, the prerequisite check must accept.
    Every other invariant still fails loudly.
    """
    try:
        validate_checkpoint(checkpoint)
    except CheckpointValidationError as exc:
        if exc.field != "cost_snapshot":
            raise
        import logging
        logging.getLogger(__name__).warning(
            "Checkpoint %s carries a legacy cost_snapshot (%s) — accepting it "
            "as-is; the schema only gates new writes.", source, exc,
        )
```

> **SUPERSEDED by owner ruling (Epic 25, Ruling 2) — "Narrow the tolerance to the
> legacy shape."** The `if exc.field != "cost_snapshot": raise` predicate above is
> too wide: `exc.field` derives from `exc.absolute_path[0]`, so it waives EVERY
> schema failure anywhere under `cost_snapshot`, not just the
> `additionalProperties` violation it is named for. `cost_snapshot = "n/a"`,
> `= None`, `= {"total_spent_usd": "lots"}` were all tolerated — read paths
> returned them and `_enforce_stage_prerequisites` counted them as a complete
> predecessor — and then reached `cost = cp["cost_snapshot"]` in
> `backlot/state.py` and `float(cost_snapshot.get("total_spent_usd", 0.0) or 0.0)`
> in `CostTracker.reconstruct_from_snapshot`. As shipped, the guard is
> `exc.field == "cost_snapshot" AND _is_legacy_cost_snapshot(value)`, where the
> legacy shape is an OBJECT whose `*_usd` figures are real, finite numbers
> (booleans excluded — `isinstance(True, int)` is True). No key allowlist: the
> money-key convention is the `_usd` suffix. The single-definition property and
> all three call sites are unchanged.

Three call sites, all becoming one-line calls:

1. `_enforce_stage_prerequisites` (line 330): replace `validate_checkpoint(checkpoint)`
   with `_validate_tolerating_legacy_cost_snapshot(checkpoint, path)`. The broad
   `except (OSError, json.JSONDecodeError, CheckpointValidationError)` at line 331 stays
   unchanged — any *re-raised* (non-cost_snapshot) validation error still correctly
   classifies the predecessor as incomplete.
2. `read_checkpoint` (lines 625-638): replace the whole try/except block with
   `_validate_tolerating_legacy_cost_snapshot(checkpoint, path)`.
3. `get_latest_checkpoint` (lines 660-673): replace the whole try/except block with
   `_validate_tolerating_legacy_cost_snapshot(checkpoint, checkpoints[0])`.

`write_checkpoint`'s own `validate_checkpoint(checkpoint)` at line 590 is untouched —
write time is where the schema is enforced; new checkpoints must never carry the legacy
shape (guarded by the existing `test_rogue_cost_snapshot_key_rejected`).

### Why this design

A shared helper makes the three sites agree *by construction* — the failure mode was
divergent copies, so a third copy is disqualified. It also collapses the two existing
duplicated blocks, which mitigates the review's separate MINOR finding that
`get_latest_checkpoint`'s untested copy could drift (drift is now impossible; workstream
G still adds direct `get_latest_checkpoint` coverage). Alternative — special-casing
`exc.field == "cost_snapshot"` inside `_enforce_stage_prerequisites`'s except clause —
lost: it is the third copy-paste, and the except there also catches OSError/JSONDecodeError
so the carve-out logic would be tangled into unrelated corruption handling.

### Acceptance

`tests/lib/test_checkpoint_cost_snapshot.py` (existing file — it already owns the
tolerance tests and the disk-rewrite pattern), two new tests. Both are behavioral: they
execute `write_checkpoint` end-to-end on framework-smoke, the finding's own repro
pipeline.

- `test_prerequisites_tolerate_legacy_cost_snapshot_on_predecessor` — the finding's
  exact deadlock, currently failing:
  - Arrange: `init_project("run", pipeline_type="framework-smoke", pipeline_dir=tmp_path)`;
    `write_checkpoint(..., "research", "awaiting_human", {"research_brief": sample_artifact("research_brief")}, ...)`;
    then rewrite `checkpoint_research.json` on disk (the pattern from
    `test_later_stage_rejects_unapproved_gated_predecessor`,
    tests/lib/test_checkpoint_prerequisites.py:63-66): set `status="completed"`,
    `human_approved=True`, and inject
    `cost_snapshot={"spent_usd": 0.28, "approved_budget_usd": 2.0}`.
  - Act/assert: `write_checkpoint(tmp_path, "run", "script", "awaiting_human",
    {"script": <schema-valid script artifact, reuse the `_script_artifact()` shape from
    test_checkpoint_prerequisites.py:13-26>}, pipeline_type="framework-smoke")`
    **succeeds** and the returned path exists. Additionally assert
    `read_checkpoint(tmp_path, "run", "research")` still returns the legacy snapshot —
    read path and write path now agree on the same file.
- `test_prerequisites_still_reject_non_cost_snapshot_predecessor_corruption` — the
  scope guard: same arrange, but inject `data["rogue_top_level_key"] = "smuggled"`
  instead of the legacy cost_snapshot. Assert the script write raises
  `CheckpointValidationError` matching `"PREREQUISITE VIOLATION"` and naming
  `research`. Proves the helper did not widen the tolerance in the prerequisite path.

### Risk

- The tolerance now runs on every predecessor at every gating write, so the warning can
  log once per predecessor per write — noisy but honest for a legacy project; identical
  wording to the existing read-path warning, no new message class.
- Refactoring the two existing sites into the helper could change behavior if the copies
  had silently diverged — they have not (verified identical except for the `path` /
  `checkpoints[0]` argument, which becomes the `source` parameter). The two existing
  tolerance tests (`test_read_checkpoint_tolerates_legacy_cost_snapshot`,
  `test_read_checkpoint_still_raises_on_non_cost_snapshot_corruption`) pin
  `read_checkpoint`'s behavior across the refactor.
- Workstream G note: `get_latest_checkpoint` remains untested after this change; the
  helper makes a single tolerance test sufficient per entry point rather than per copy.

---

## A2. decision_log orphan-absorption self-heal crashes on the malformed side files it exists to tolerate (`lib/checkpoint.py:458`, MAJOR ×2 — python-correctness + robustness)

Three verified defects in `_merge_decision_log` (lines 405-462): (a) a side entry with
no `decision_id` passes the `.get()` filter (line 445-446, `None not in existing_ids`)
then KeyErrors at line 458's bracket access; (b) `side["decisions"]` that is not a list
of dicts raises AttributeError in the comprehension; (c) duplicate-id side entries are
BOTH absorbed because `orphans` is pre-filtered against a stale `existing_ids`. The same
bracket-access pattern exists in the main merge loop (lines 425, 429) and in the
`existing_ids` set-build (line 425) — `_merge_decision_log` runs from `write_checkpoint`
(line 574) *before* `validate_checkpoint` (line 590), so a malformed entry in the
checkpoint's own `decision_log` artifact also KeyErrors before schema validation can
produce its proper message.

**Policy ruling — malformed side entries are skipped with a warning: not silent, not
quarantined.** Rationale: the merge never rewrites or deletes
`artifacts/decision_log.json`, so the side file *is already the quarantine* — a skipped
entry stays in place, byte-for-byte, and the warning re-fires on every subsequent
checkpoint write until it is repaired (a deliberate nag; in this repo agents read logs
and act on them). Silent drop hides the Rule Zero violation the self-heal exists to
surface. A separate quarantine file adds lifecycle machinery and a *third* fork of the
decision trail — the exact disease being cured.

### Fix

`lib/checkpoint.py`. One new helper (place before `_merge_decision_log`, after line 403)
plus a rewrite of the merge body. No signature changes.

```python
def _usable_decisions(payload: Any, source: str) -> list[dict[str, Any]]:
    """The decisions[] entries in ``payload`` carrying a usable decision_id.

    An entry is usable when it is a dict whose "decision_id" is a non-empty
    string. Anything else — non-dict entries, a decisions value that is not
    a list, a payload that is not a dict — is skipped with a warning, never
    raised: decision-log merging must not be able to abort a checkpoint
    write. Skipped entries are left untouched in their source file (this
    function never writes), so nothing is destroyed: repair the entry and
    the next checkpoint write absorbs it.
    """
    import logging
    log = logging.getLogger(__name__)
    decisions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(decisions, list):
        if payload is not None:
            log.warning(
                "decision_log merge: %s has no decisions[] list — nothing "
                "merged from it. Write decision_log through write_checkpoint, "
                "not by hand.", source,
            )
        return []
    kept: list[dict[str, Any]] = []
    malformed = 0
    for d in decisions:
        did = d.get("decision_id") if isinstance(d, dict) else None
        if isinstance(did, str) and did:
            kept.append(d)
        else:
            malformed += 1
    if malformed:
        log.warning(
            "decision_log merge: skipped %d malformed entrie(s) in %s (each "
            "needs a string decision_id). They were left in place — repair "
            "them and the next checkpoint write absorbs them.",
            malformed, source,
        )
    return kept
```

`_merge_decision_log` body, lines 425-462, becomes:

```python
    # Canonical entries are kept verbatim (a hand-broken entry here is
    # preserved, not dropped) — only the id set is built defensively.
    existing_ids = {
        d.get("decision_id")
        for d in existing.get("decisions", [])
        if isinstance(d, dict)
    }
    existing_ids.discard(None)
    for decision in _usable_decisions(new_log, "artifacts['decision_log']"):
        did = decision["decision_id"]
        if did not in existing_ids:
            existing["decisions"].append(decision)
            existing_ids.add(did)

    # Self-heal a forked audit trail. Nothing in the codebase writes
    # <project>/artifacts/decision_log.json, but an agent hand-writing it
    # bypasses this merge entirely — which is how ask-jess ended up with 11
    # decisions here and 30 there for 29 hours. Absorb any well-formed
    # orphans (exactly once each) rather than letting the canonical log
    # silently disagree with the artifact. This file is by definition
    # hand-written and never schema-validated: it must not be able to
    # crash a checkpoint write, no matter what it contains.
    artifact_copy = pipeline_dir / project_id / "artifacts" / "decision_log.json"
    if artifact_copy.exists():
        try:
            with open(artifact_copy, encoding="utf-8") as f:
                side = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            side = None
            import logging
            logging.getLogger(__name__).warning(
                "artifacts/decision_log.json is unreadable (%s) — orphan "
                "absorption skipped. Write decision_log through "
                "write_checkpoint, not by hand.", exc,
            )
        absorbed = 0
        for d in _usable_decisions(side, str(artifact_copy)):
            did = d["decision_id"]
            if did in existing_ids:
                continue          # membership re-checked per entry: a
            existing["decisions"].append(d)   # duplicate side id absorbs once
            existing_ids.add(did)
            absorbed += 1
        if absorbed:
            import logging
            logging.getLogger(__name__).warning(
                "decision_log fork: %d decision(s) existed only in "
                "artifacts/decision_log.json and were absorbed. Write "
                "decision_log through write_checkpoint, not by hand.",
                absorbed,
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    # tmp + os.replace: the canonical audit log gets the same crash safety
    # as the checkpoint itself (write_checkpoint's idiom, this file)
    # — a truncated decision_log.json would brick every later merge's
    # json.load and with it every checkpoint write.
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    import os
    os.replace(tmp_path, path)
```

Notes:

- The `isinstance(side, dict)` gate and the precomputed `orphans` list are gone; the
  helper subsumes both (a non-dict `side`, including the `None` from a failed read,
  yields `[]`).
- Duplicate side ids: membership is checked *inside* the absorption loop against an
  `existing_ids` updated per absorption — first occurrence wins, later ones skip.
  "Absorb well-formed orphans exactly once."
- Line-429 path: a malformed entry in the checkpoint's *own* `decision_log` artifact is
  now skipped by the helper (with a warning) instead of KeyError-ing; `write_checkpoint`
  then still hard-fails that checkpoint at `validate_checkpoint` (line 590 —
  `decision_log` is in `ARTIFACT_NAMES`, and decision_log.schema.json requires
  `decision_id` with `additionalProperties: false`), so the supported write path keeps
  its loud, correctly-worded schema error. Tolerance is only for the *side* file, which
  no schema governs.
- **Canonical-container guard** (panel addition): before the set-build, one shape check
  on the canonical file just loaded at line 416 —
  `if not isinstance(existing, dict) or not isinstance(existing.get("decisions"), list):`
  raise `CheckpointValidationError` naming the file and the repair
  (`"projects/<id>/decision_log.json is hand-damaged: expected {\"decisions\": [...]} — restore the container shape; entries inside it are preserved verbatim"`).
  A code-written file only reaches this state by hand-editing; entry-level damage is
  tolerated (kept verbatim), container-level damage gets a pointed error instead of a
  bare AttributeError/KeyError.
- No blanket `except Exception` around the self-heal: with the container guard above,
  every input-derived crash vector is closed (JSON-loaded data is always
  dict/list/str/num/bool/None; `decision_id` is isinstance-checked `str`, so hashable;
  re-serialization of JSON-loaded values cannot fail), and a blanket except would mask
  real bugs in our own merge code.

### Why this design

One helper applied to both untrusted decision sources (the checkpoint artifact
pre-validation, and the schema-less side file) closes every identified crash vector with
a single well-formedness definition, mirroring A1's one-definition principle. The
skip-and-warn policy is argued above. Alternative — wrapping the whole self-heal in a
swallow-everything guard like `_archive_superseded_checkpoint`'s (line 394-398) — lost:
that idiom is right for best-effort I/O, but here it would also swallow logic bugs in
the merge itself and give no per-entry repair signal.

### Acceptance

New file `tests/lib/test_decision_log_merge.py`, pytest style matching its siblings in
`tests/lib/` (import `sample_artifact` from `tests.contracts.test_phase0_contracts`;
reuse the `_script_artifact()` shape only if a second stage is needed — it is not). All
tests are behavioral: they run `write_checkpoint` on framework-smoke and read the
resulting files. Local helpers:

```python
def _decision(did: str) -> dict:
    return {
        "decision_id": did, "stage": "research",
        "category": "provider_selection", "subject": "tts provider",
        "options_considered": [
            {"option_id": "a", "label": "A", "score": 0.9, "reason": "fits"},
        ],
        "selected": "a", "reason": "best fit",
    }

def _log(*decisions: dict) -> dict:
    return {"version": "1.0", "project_id": "run", "decisions": list(decisions)}
```

- `test_side_entry_without_decision_id_does_not_crash_write` — the finding's exact
  scenario. Arrange: init framework-smoke project; hand-write
  `<project>/artifacts/decision_log.json` containing
  `_log({"id": "d-031", "note": "wrong key"}, _decision("d-9"))` (one malformed, one
  well-formed orphan); snapshot the side file's bytes. Act:
  `write_checkpoint(..., "research", "awaiting_human", {"research_brief": ...,
  "decision_log": _log(_decision("d-1"))}, pipeline_type="framework-smoke")`.
  Assert: the write succeeds (this KeyErrors today); canonical
  `<project>/decision_log.json` contains exactly ids `{"d-1", "d-9"}`; the malformed
  entry is absent from the canonical log; the side file is byte-identical to the
  snapshot; `caplog` contains "skipped 1" and the fork-absorption warning.
- `test_duplicate_side_ids_absorbed_exactly_once` — side file
  `_log(_decision("d-9"), {**_decision("d-9"), "reason": "second copy"})`; after the
  same write, the canonical log contains exactly one entry with id `d-9`, and its
  `reason` is `"best fit"` (first occurrence won). Fails today: both are absorbed.
- `test_side_decisions_wrong_container_degrades` — parametrize the side-file content
  over `{"decisions": {"a": 1}}`, `{"decisions": ["not-a-dict"]}`, and a top-level
  JSON list `[...]`; each case: the checkpoint write succeeds, nothing is absorbed,
  a warning is logged. (The list-of-strings case AttributeErrors today.)
- `test_corrupt_side_file_skips_absorption` — side file containing `'{"decisions": ['`
  (truncated JSON): write succeeds, canonical log carries only the checkpoint's own
  decisions, "unreadable" warning logged, side file untouched.
- `test_checkpoint_decision_missing_id_reports_schema_error_not_keyerror` — no side
  file; artifacts carry `_log({k: v for k, v in _decision("d-1").items() if k != "decision_id"})`.
  Assert `pytest.raises(CheckpointValidationError)` (currently a bare KeyError) and
  that the canonical `decision_log.json` does not contain the malformed entry.
- `test_canonical_entry_without_id_survives_merge_untouched` — pre-seed the canonical
  `<project>/decision_log.json` with `_log({"note": "hand-edited, no id"})` (simulated
  hand edit); a checkpoint write carrying `_log(_decision("d-2"))` succeeds
  (line-425 set-build KeyErrors today), and afterwards the canonical file contains BOTH
  the malformed entry (preserved verbatim) and `d-2`.
- `test_canonical_container_corruption_raises_pointed_error` — pre-seed the canonical
  `decision_log.json` with a top-level JSON list (and, parametrized, with
  `{"decisions": {"a": 1}}`); a checkpoint write carrying a valid decision_log raises
  `CheckpointValidationError` naming the file (today: bare AttributeError/KeyError).

### Risk

- The canonical-file write becomes tmp+`os.replace`. Same-directory tmp name
  `decision_log.json.tmp` cannot collide with `write_checkpoint`'s
  `checkpoint_<stage>.json.tmp`. Windows note from `_archive_superseded_checkpoint`
  applies to renames of *open* files — the Backlot watcher reads `decision_log.json`
  but the existing plain `open("w")` rewrite had the same exposure; `os.replace` is
  what `write_checkpoint` already ships for the checkpoint files themselves.
- Pre-existing, deliberately untouched: (1) merge-before-validate order in
  `write_checkpoint` (574 vs 590) means a checkpoint that later fails validation has
  already merged its *well-formed* decisions into the canonical log — unchanged
  behavior, now minus the crash; (2) a canonical `decision_log.json` that fails
  `json.load` (line 416) still raises out of `write_checkpoint` — code-written file,
  same crash-with-signal class as B1's `CostLogCorruptedError` policy, and now
  unreachable via our own writes thanks to the atomic replace.
- Warning nag repeats on every checkpoint write while a malformed side entry exists —
  deliberate (see policy ruling); if it proves too noisy the fix is repairing the side
  file, not muting the merge.


**Open questions:** none
**Dependencies:** Workstream G (tests): builds directly on the acceptance tests specced here — tests/lib/test_checkpoint_cost_snapshot.py additions (A1) and the new tests/lib/test_decision_log_merge.py (A2). G also owns direct get_latest_checkpoint tolerance coverage, which A1's helper extraction makes a one-test job. | Workstream B (cost_tracker): no code dependency, but B1's spec cites the tmp+os.replace idiom at lib/checkpoint.py:598-605 — A does not move that block, so B's anchor stays valid. A2 additionally applies the same idiom to the canonical decision_log.json write, consistent with B1's precedent. | Workstream C / doc specs touching docs/intent/context-cost-spec.md section 2: when the judgment-note instructions are redirected to the supported write_checkpoint path, they should note A2's semantics — malformed decisions in a hand-written artifacts/decision_log.json are skipped with a warning and left in place, never absorbed and never fatal.


---

# Fix spec — Workstream B: `tools/cost_tracker.py` runtime hardening

Status: **spec for confirmed review findings** on `feat/epic1-cost-governance`.
Scope: Python only. Skill-text changes that these fixes imply are contracts handed to
workstream C (see Dependencies), not written here.

All four items land as **one change** to `tools/cost_tracker.py` plus one new test file.
B1 and B2 rewrite the same two functions (`_save`, `_load`) and B2 is only safe on top of
B1's atomic replace — do not land them separately.

---

## B1. `_save` is non-atomic, `_load` has no corruption handling (`tools/cost_tracker.py:540`, MAJOR)

### Fix

`tools/cost_tracker.py`. Adopt the house atomic-write idiom from `write_checkpoint`
([`lib/checkpoint.py:598-605`](lib/checkpoint.py#L598)). Add `import os` at module top.

`_save` (currently lines 525–541) — replace the final `open("w") + json.dump` with:

```python
self.cost_log_path.parent.mkdir(parents=True, exist_ok=True)
# tmp + os.replace: a mid-dump crash can never leave a truncated ledger
# (write_checkpoint's idiom — cited by symbol; A's edits shift its line numbers).
tmp_path = self.cost_log_path.with_suffix(".json.tmp")
with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
os.replace(tmp_path, self.cost_log_path)
```

`_load` (currently lines 543–548) — wrap the `json.load` and the shape access:

```python
class CostLogCorruptedError(Exception):
    """cost_log.json exists but cannot be parsed. Never silently reset."""

def _load(self) -> None:
    try:
        with open(self.cost_log_path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"top-level JSON is {type(data).__name__}, expected object")
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        raise CostLogCorruptedError(
            f"Cost ledger {self.cost_log_path} is corrupt ({exc}). "
            "This is the money audit log — do NOT delete it or start fresh, "
            "a reset ledger reports $0 spent and the budget guard would "
            "re-authorize money already spent. Recovery: call "
            "CostTracker.reconstruct_from_snapshot(...) with the latest "
            "checkpoint's cost_snapshot and the approved plan's tool names — "
            "it quarantines this file and rebuilds an honest ledger. See its "
            "docstring."
        ) from exc
    self.entries = data.get("entries", [])
    ...
```

**Corrupt-file policy: crash with a pointed error. No auto-quarantine, no silent reset.**
Rationale: this is a money audit log; an auto-reset ledger reports `budget_spent_usd == 0`
and `reserve()` (line 179) then re-authorizes spend that already happened — the guard
inverts into an overspend enabler. Auto-quarantine-then-fresh is the same reset with one
extra crash in between (the *next* `for_project` sees no file and silently starts at $0).
With B1's atomic write, corruption can no longer be self-inflicted; a corrupt file means
external damage, which is exactly when a human/agent decision is required. In this repo
agents read error text and act on it, so the recovery instructions live in the message.

Export `CostLogCorruptedError` next to `BudgetExceededError`/`ApprovalRequiredError`
(lines 31–38).

**Reconstruction helper (panel addition — closes the quarantine→fresh-start hole).**
A bare `mv cost_log.json cost_log.json.corrupt` leaves the next `for_project` seeing
no file, silently starting a fresh ledger at $0 spent — the exact reset the policy
above forbids. So the recovery is one supported call, referenced by the error message:

```python
@classmethod
def reconstruct_from_snapshot(
    cls, cost_log_path, cost_snapshot, approved_tools=(), budget_total_usd=None,
) -> "CostTracker":
    """Rebuild a quarantined ledger from the last checkpoint's cost_snapshot.

    Renames the corrupt file to cost_log.json.corrupt-<n> (kept for audit,
    never deleted), then writes a fresh ledger seeded with ONE completed
    entry — tool "ledger_reconstruction", operation "prior spend per
    checkpoint cost_snapshot", actual_usd = cost_snapshot["total_spent_usd"]
    — so budget_spent_usd is honest immediately and the budget guard cannot
    re-authorize money already spent. Re-arms budget_total_usd (the
    snapshot's approved figure unless overridden) and re-approves the given
    tool names. Line-item detail from before the corruption is lost and NOT
    invented; the seed entry's operation string says so. Returns the new
    tracker.
    """
```

The estimate→reconcile seed bypasses `reserve()`'s guards by design — it records past
spend, it does not authorize new spend.

### Why this design

Reuses the exact idiom this branch already added for checkpoints — the reviewer's point is
that the money ledger got less protection than the checkpoint on the same branch.
Alternative (auto-quarantine + fresh start with a warning) lost because silent spend reset
is worse than a blocked pipeline for an audit log; see policy rationale above.

### Acceptance

New file `tests/tools/test_cost_tracker_persistence.py` (unittest style, matching
`test_cost_tracker_governance.py`):

- `test_failed_save_leaves_previous_ledger_intact` — arrange: tracker on a tmp
  `cost_log.json`, one `estimate()` so a valid file exists; snapshot file bytes;
  monkeypatch `json.dump` to raise `RuntimeError` mid-write; act: `approve_tool("x")`
  → assert it raises, then assert `cost_log.json` still parses and equals the snapshot
  (the mutation was lost, the ledger was not).
- `test_load_corrupt_ledger_raises_pointed_error_and_leaves_file` — arrange: write
  `'{"version": "1.0", "entries": [{"id": "ab'` (truncated) to `cost_log.json`; act:
  `CostTracker(cost_log_path=path)` → `assertRaises(CostLogCorruptedError)`; assert the
  message contains the path and the word "quarantine"; assert the corrupt file still
  exists byte-identical (constructor must not touch it).
- `test_save_replaces_not_appends` — after two mutations, no `*.json.tmp` remains and
  the file parses.
- `test_reconstruct_from_snapshot_restores_spend_and_quarantines` — arrange: corrupt
  bytes at `cost_log.json`; act: `CostTracker.reconstruct_from_snapshot(path,
  {"total_spent_usd": 1.20, "budget_total_usd": 2.0}, approved_tools=["tts_selector"])`;
  assert `cost_log.json.corrupt-1` exists byte-identical to the corrupt original, the
  new ledger passes `validate_artifact("cost_log", ...)`, `budget_spent_usd == 1.20`,
  `budget_total_usd == 2.0`, `"tts_selector"` is approved, and a subsequent
  over-budget `estimate`+`reserve` still raises (the guard works against reconstructed
  spend).

### Risk

Constructor can now raise a new exception type where it previously raised bare
`JSONDecodeError` — any caller catching the old type breaks. Verified: the only
constructor callers are `for_project` and tests, none catch it. Mitigated further by the
error message being actionable. The fixed tmp filename is safe against concurrent writers
only once B2's lock serializes saves — another reason the two land together.

---

## B2. No locking / reload-before-save — two live instances are last-writer-wins (`tools/cost_tracker.py:525`, MINOR-titled MAJOR)

### Fix

`tools/cost_tracker.py`. Add a guarded import at module top (panel ruling — the sibling
module `lib/checkpoint.py` carries explicit Windows accommodations, and an
un-importable money module is a worse portability break than an advisory-lockless one):

```python
try:
    import fcntl
except ImportError:      # non-POSIX (native Windows)
    fcntl = None
```

`_locked()` checks `fcntl is None` and, when so, logs ONE warning per process
("cost ledger file locking unavailable on this platform — concurrent stages may
race") then proceeds lockless. Reload-merge-save still runs, which alone removes most
lost-update windows. Every mutator — `estimate` (:130), `reserve` (:146),
`approve_tool` (:197), `reconcile` (:202), `refund` (:211) — runs its body inside a
lock–reload–merge–mutate–save critical section:

```python
from contextlib import contextmanager

@contextmanager
def _locked(self):
    """Serialize load-merge-save across processes. No-op when in-memory only."""
    if self.cost_log_path is None:
        yield
        return
    self.cost_log_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = self.cost_log_path.with_suffix(".json.lock")
    with open(lock_path, "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            self._merge_from_disk()
            yield
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)
```

Lock a **separate `.lock` file**, never the data file: B1's `os.replace` swaps the data
file's inode, so a flock held on it would stop excluding the next opener.

`_merge_from_disk()` — re-read the ledger (via the B1-hardened `_load` path, refactored so
both `__init__` and the merge share one parse helper) and merge into memory with
deterministic rules:

- **entries**: union by `id`. Same `id` on both sides: higher lifecycle rank wins
  (`completed`/`failed`/`refunded` = 2, `reserved` = 1, `estimated` = 0); tie → later
  `timestamp`; tie → local. Disk order preserved, local-only entries appended — stable
  output for the audit trail.
- **approved_tools**: set union.
- **budget_total_usd**: local wins iff it was explicitly assigned on this instance after
  construction (the proposal-gate arming flow, `tracker.budget_total_usd = ...`);
  otherwise disk wins. Implement by making `budget_total_usd` a property whose setter
  flips `self._budget_dirty = True`; `__init__` sets the backing field directly.
- Header totals (`budget_reserved_usd`/`budget_spent_usd`) are already recomputed by
  `_save` from entries — no merge needed.

Mutator shape (e.g. `reserve`):

```python
def reserve(self, entry_id, *, user_approved=False) -> None:
    with self._locked():
        entry = self._find(entry_id)
        ...all existing checks and mutation unchanged...
        self._save()
```

The budget check at line 179 now runs **after** the reload-merge, so it compares against
every other process's persisted spend, not this instance's stale construction-time view.

### Why this design

The writer profile is single-machine, multi-process, low-frequency (a handful of writes
per stage): one advisory `flock` around a whole-file load-merge-save is the simplest
design that is actually correct for it, and it changes no file format, no schema, and no
skill-visible API. Alternatives:

- **Append-only journal** (one JSON line per event): lock-free lost-update immunity, but
  it replaces the document format that `cost_log.schema.json`, `validate_artifact`, the
  compose-stage "schema-valid cost_log" criteria in six manifests, and Backlot all read —
  a format migration plus a compaction reader to fix a low-frequency race. Lost.
- **Per-stage/per-process files** merged at read: no write contention, but `reserve()`
  needs a global spend view, so every budget check becomes glob-and-merge and the
  check-then-write race merely moves to the merge. Lost.
- **flock on the data file itself**: broken by `os.replace` (inode swap defeats the
  exclusion). Lost on correctness.

### Acceptance

Same new file `tests/tools/test_cost_tracker_persistence.py`:

- `test_two_instances_do_not_erase_each_others_entries` — the finding's exact scenario,
  single-threaded interleaving: open tracker A and tracker B on the same path (B before
  A writes anything); A runs estimate→reserve→reconcile($0.40); B runs its own
  estimate→reserve→reconcile($0.30); open fresh tracker C → assert both entries present
  and `C.budget_spent_usd == 0.70`. (Fails on current code: B's save deletes A's entry.)
- `test_cap_mode_reserve_sees_other_instances_spend` — cap mode, `budget_total_usd=1.0`,
  `reserve_pct=0.0`: instance A reconciles $0.80 of completed spend; stale instance B
  (opened when the file was empty) estimates $0.50 and calls
  `reserve(user_approved=True)` → `assertRaises(BudgetExceededError)`. Behavioral proof
  the guard reads merged state, and (with the flag passed) that `user_approved` does not
  waive the budget check.
- `test_merge_never_regresses_terminal_status` — A and B share one entry (B constructed
  from the file after A's `reserve`); A `reconcile`s it (terminal on disk); B calls
  `approve_tool("t")` (any mutator) → reload the file, assert the entry is still
  `completed`, not regressed to B's in-memory `reserved`.
- `test_armed_budget_survives_merge` — instance sets `tracker.budget_total_usd = 1.52`
  then `estimate(...)`; fresh tracker on the file reports `budget_total_usd == 1.52`.
- `test_parallel_processes_lose_no_entries` — `multiprocessing`: 4 processes × 5
  estimate→reserve(user_approved=True)→reconcile round trips against one path (ample
  budget, approvals pre-seeded); parent then opens the ledger and asserts exactly 20
  entries, all `completed`, `budget_spent_usd` equal to the sum, and
  `validate_artifact("cost_log", ...)` passes. This is the only test that exercises
  `flock` under real contention; keep N small so it runs in <5s.

### Risk

- `flock` is advisory: a hand-edit or non-tracker writer still races. Acceptable — the
  branch's own rule is that all writes go through `CostTracker`; document in the class
  docstring.
- Reload-merge means `self.entries` can grow inside any mutator call; code that captured
  an index into `entries` across a mutator would see shifted rows. Verified no such
  caller exists (tests index only after their last mutation).
- Residual header edge: an instance constructed *before* arming that mutates *after* will
  write the disk (armed) header because its own is not dirty — correct under the rule.
  The inverse (two instances arming different budgets) is not a blessed flow; the
  dirty-local-wins rule makes the outcome deterministic (last armer's save wins).
- Deadlock: single non-reentrant lock — ensure no mutator calls another mutator inside
  `_locked()` (none does today; note it in `_locked`'s docstring).

---

## B3. Crash between `reserve()` and `reconcile()` strands the reservation forever (`tools/cost_tracker.py:146`, MINOR)

### Fix

`tools/cost_tracker.py`. Add one read-only helper (no sweep, no auto-expiry):

```python
def non_terminal_entries(self) -> list[dict[str, Any]]:
    """Entries still holding or awaiting budget: status estimated or reserved.

    A `reserved` entry with no live owner (a crash between reserve and
    reconcile) consumes usable_budget_usd until resolved. NEVER resolve
    one automatically — the ledger cannot know whether the interrupted
    call was billed. Resolution rules for the agent:
      - output exists on disk / provider confirmed the charge:
          reconcile(id, estimated_or_known_actual, success=True|False)
      - provider confirmed no charge, or the call never fired:
          refund(id)
      - unknowable: reconcile at the estimate with success=False —
        overstating spend is the safe direction for a budget guard.
    """
    return [
        e for e in self.entries
        if e["status"] in (EntryStatus.ESTIMATED.value, EntryStatus.RESERVED.value)
    ]
```

No timestamp-based auto-sweep. With B2, a `reserved` entry may belong to a parallel
script whose paid call is in flight *right now*; any age heuristic that auto-refunds it
frees budget for money the provider may bill, and auto-reconciling it books spend that may
not exist. Both mis-state the audit log in a direction the tracker cannot verify, so
resolution stays a judgment call, made where judgment lives in this repo: the skill text.

The compose-stage criterion ("every entry in a terminal state") already *detects* the
orphan; what the criterion-failure text must *instruct* is workstream C's block. The
contract this fix hands them (see Dependencies): on a compose-stage cost_log criterion
failure, call `tracker.non_terminal_entries()`, resolve each entry by the three rules in
the docstring above, and never hand-edit `cost_log.json`.

### Why this design

A lister plus explicit resolution keeps the tracker mechanism-only and puts the
bill-or-not judgment with the agent, which is the only party that can check whether the
asset exists. Alternative — TTL-based auto-refund sweep in `for_project` — lost because it
double-spends when the provider billed the interrupted call, and B2 makes "old reserved
entry" indistinguishable from "parallel script mid-call".

### Acceptance

`tests/tools/test_cost_tracker_persistence.py`:

- `test_non_terminal_entries_surfaces_crash_orphan` — tracker A: estimate + reserve, no
  reconcile (simulated crash: drop A); fresh tracker B on the file:
  `non_terminal_entries()` returns exactly that entry and `usable_budget_usd` reflects
  the held reservation; after `B.reconcile(id, est, success=False)` the list is empty.
- `test_orphan_resolutions_keep_totals_honest` — two reserved orphans on one ledger:
  reconcile one at estimate with `success=False` → it counts in `budget_spent_usd`;
  refund the other → it does not; assert `budget_reserved_usd == 0.0` and
  `validate_artifact("cost_log", persisted)` passes. (Also closes the review's
  "no test drives `reconcile(success=False)`" gap for the tracker side.)

### Risk

An agent could still refund a billed orphan; the fix bounds this by putting the decision
rules in the docstring *and* (via workstream C) in the criterion-failure text the agent
actually reads at that moment. Helper is read-only, so it can break nothing.

---

## B4. Constructor default `budget_total_usd=10.0` silently diverged from config's 15.0 (critic, `tools/cost_tracker.py:46`)

### Fix

`tools/cost_tracker.py:44-53`. Remove the duplicated constant; the config becomes the
single source of the default:

```python
def __init__(
    self,
    budget_total_usd: Optional[float] = None,
    ...
) -> None:
    if budget_total_usd is None:
        budget_total_usd = OpenMontageConfig.load().budget.total_usd
    self._budget_total_usd = budget_total_usd   # backing field per B2's property
    ...
```

`for_project` (lines 65–91) keeps passing `cfg.budget.total_usd` explicitly — unchanged
behavior, one config load. `_load`'s header override (`data.get("budget_total_usd", ...)`)
still runs after this, so a persisted armed ledger keeps its armed budget. Note this
interacts with B2: `__init__` writes the backing field directly and leaves
`_budget_dirty = False`, so a defaulted budget correctly yields to the disk header on
merge.

### Why this design

`None → resolve from config` deletes the divergence class instead of policing it: the
next budget bump touches `config.yaml`/`BudgetConfig` only. Alternatives: hard-coding
`15.0` (re-diverges on the next bump) and a contract test pinning `10.0 == config`
(institutionalizes the duplication and only complains after the fact) both lost.
`OpenMontageConfig` is already imported at line 19 — no new dependency.

### Acceptance

`tests/tools/test_cost_tracker_persistence.py`:

- `test_default_budget_resolves_from_config` — `CostTracker().budget_total_usd ==
  OpenMontageConfig.load().budget.total_usd` (equality to the loaded config, no literal
  `15.0` — the test must survive the next bump), and
  `CostTracker(budget_total_usd=3.0).budget_total_usd == 3.0`.

### Risk

Bare `CostTracker()` now reads `config.yaml`; an environment without a config would fail
at construction where it previously got a silent wrong default — that is the desired
failure. Existing tests always pass explicit budgets or tolerate the config value
(`test_approved_tools_persist_across_tracker_restarts` uses the default but asserts
nothing about its value). `docs/ARCHITECTURE.md`'s stale `$10.00` text is workstream F's.

---

## Test-file note

All acceptance tests above live in one new file,
`tests/tools/test_cost_tracker_persistence.py`, mirroring the unittest +
`tempfile.TemporaryDirectory` + `validate_artifact` pattern of
`tests/tools/test_cost_tracker_governance.py:17-43`. The governance file is untouched
(its gaps — `user_approved` non-waiver, cap-mode coverage — belong to workstream G;
`test_cap_mode_reserve_sees_other_instances_spend` above incidentally covers the
budget-check half).


**Open questions:** none
**Dependencies:** Workstream C (skill-block text): the compose-stage cost_log criterion-failure guidance and the checkpoint-protocol/compose-director blocks must instruct: call tracker.non_terminal_entries(), resolve each orphan by the reconcile-vs-refund rules in its docstring (billed or unknowable -> reconcile at estimate with success=False; confirmed unbilled -> refund), never hand-edit cost_log.json. B3's helper is the API those blocks must reference — land B before or with C. | Workstream C (skill-block text): skills that read a corrupt-ledger failure will now see CostLogCorruptedError with recovery text in the message; no skill block should instruct deleting/recreating cost_log.json, which would contradict B1's no-silent-reset policy. | Workstream F (docs): ARCHITECTURE.md $10.00 -> $15.00 text; after B4 it should describe the default as 'from config.yaml budget.total_usd' rather than a hard-coded constructor constant. | Workstream G (tests): the reconcile(success=False) coverage gap is partially closed by B3's acceptance tests (tracker side); G still owns the pipeline-level and user_approved-non-waiver suites and should build on, not duplicate, tests/tools/test_cost_tracker_persistence.py. | Workstream A (checkpoint.py): no code dependency — B1 only copies the tmp+os.replace idiom from lib/checkpoint.py:598-605; if A relocates that block, B1's comment anchor should follow.


---

# Fix Spec — Workstream C: ledger-discipline blocks in `skills/`

Scope: the Markdown instruction blocks that ARE the cost-governance runtime. Every change below is a doc edit, but binding — agents execute this text verbatim. All line numbers verified against the current branch working tree.

Shared ground truth (verified in source):

- `CostTracker.usable_budget_usd = max(0, budget_total − spent − reserved − reserve_pct×budget_total)` (`tools/cost_tracker.py:111-119`). `reserve()` compares `estimated > usable_budget_usd` strictly (`:179`) and `user_approved=True` never waives the budget check or the first-paid-use guard (`:146-176`).
- `for_project` always sources `reserve_pct` from config (`lib/config_model.py:38`, `BudgetConfig.reserve_pct = 0.10`); `_load` restores `budget_total_usd` from the file but NOT `reserve_pct` — so `tracker.reserve_pct` is always the live config value. Never hardcode 0.10 in skill text.
- `budget_spent_usd` counts FAILED entries (`tools/cost_tracker.py:103-109`).
- `ToolResult.cost_usd: float = 0.0` (`tools/base_tool.py:135`) — never None today; failed results (e.g. `tools/audio/music_gen.py:116-126`) return with `cost_usd` left at 0.0; success paths often set it to the tool's own estimate (`music_gen.py:129`, `openai_tts.py:140`).
- `approve_tool`/`reserve`'s first-paid-use guard compares raw tool-name strings (`tools/cost_tracker.py:171-176, 197-199`).

---

## C1. [MAJOR/critic] Arming fallback `budget_total_usd = approved_budget_usd or total_estimated_usd` leaves zero headroom against the reserve holdback

**Files (all SIX arming gates — panel extension):** `skills/pipelines/explainer/proposal-director.md:527-548` (Step 9), `skills/pipelines/cinematic/proposal-director.md:329-345` (Step 10), `skills/pipelines/animation/proposal-director.md:487-503` (Step 10); plus the three same-class `default_budget_cap_usd` fallbacks (they trap whenever the estimate exceeds `(1−reserve_pct)×cap`): `skills/pipelines/documentary-montage/idea-director.md:225-232`, `skills/pipelines/hybrid/idea-director.md:98`, and `skills/pipelines/avatar-spokesperson/idea-director.md:91`. The last two carry the byte-identical `approved_budget_usd or default_budget_cap_usd` fallback and take the doc-montage substitution shape below verbatim.

### Fix

Replace point 1 of the arming code block with this canonical block, **verbatim-identical in all three proposal-directors** (doc-montage substitutes its local names, see below):

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
total_estimated_usd = round(sum(li["estimated_usd"] for li in cost_estimate["line_items"]), 4)
min_workable_usd = math.ceil(total_estimated_usd / (1 - tracker.reserve_pct) * 100) / 100 + 0.01  # +1 cent: on an exact-cent division, bare ceil adds zero slack and the final reserve still trips on float dust
tracker.budget_total_usd = (
    approval.approved_budget_usd
    or max(cost_estimate["budget_cap_usd"], min_workable_usd)
)
```

Immediately after the code block, add one prose rule (all three files):

> **If the user's named figure is below `min_workable_usd`, say so at this gate** — the reserve holdback guarantees the guard blocks the plan's final approved item. Ask the user to raise the figure or trim the plan. Never silently arm a total the guard is certain to trip on.

Notes baked into the design:

- `total_estimated_usd` is re-derived from the persisted `cost_estimate["line_items"]`, not a Python local — Step 9/10 runs "a later turn", so locals cannot be assumed live. `cost_estimate["budget_cap_usd"]` is schema'd (`schemas/artifacts/proposal_packet.schema.json:301`) and recorded by Step 5c in all three files (explainer:429, cinematic:274, animation:406).
- `math.ceil(... * 100) / 100 + 0.01` rounds UP to the cent **plus one designed cent of slack** (panel ruling): when `total/(1−r)` lands on an exact cent — e.g. two $0.27 items → $0.60 — bare ceil adds nothing and the final reservation still trips the strict `>` on float dust (verified: 205 failing plans in a small search). The extra cent makes `(1−r)×total ≥ estimate` hold with real margin at every boundary; the prose rule below inherits it, so a user figure of exactly the old `min_workable` no longer arms the same trap.
- Assignment to `budget_total_usd` alone does not persist; the `approve_tool` loop that follows calls `_save`, so keep the existing order (assignment first).

**documentary-montage/idea-director.md:226** becomes:

```python
total_estimated_usd = round(sum(li["estimated_usd"] for li in metadata["cost_estimate"]["line_items"]), 4)
min_workable_usd = math.ceil(total_estimated_usd / (1 - tracker.reserve_pct) * 100) / 100 + 0.01  # +1 cent: on an exact-cent division, bare ceil adds zero slack and the final reserve still trips on float dust
tracker.budget_total_usd = approved_budget_usd or max(default_budget_cap_usd, min_workable_usd)
```

with the same prose rule.

### Why this design

A bare "approve" at the gate approves the *presentation* — "Estimated cost: $X of $[default_budget_cap_usd] budget" (explainer Step 7:508) — so the default cap, not the raw estimate, is the faithful fallback; the gross-up floor covers the pathological case where the estimate itself exceeds `(1−r)×cap`. Alternative considered: set `tracker.reserve_pct = 0` at arming (kill the holdback). Lost because the holdback is the revision/regeneration headroom every proposal explicitly promises the user ("Headroom: $1.48 for revisions", Step 6:445) — disabling it trades a false guard-trip for genuinely unguarded overspend.

### Acceptance

`tests/tools/test_cost_tracker_governance.py::test_documented_arming_formula_reserves_full_plan_in_cap_mode` — **behavioral**: build a `CostTracker(mode=CAP, cost_log_path=tmp)` with config-default `reserve_pct`; seed 3 line items ($0.60/$0.60/$0.32 — the critic's own scenario); execute the documented formula (`approved = None` → `max(cap, ceil-gross-up)`, with `budget_cap_usd` set below the estimate to force the gross-up branch); `approve_tool` each name; then `estimate`+`reserve(user_approved=True)` all three sequentially, reconciling each at its estimate. Assert: no `BudgetExceededError`, no `budget_warning` key on any entry. Companion test with `approved_budget_usd=1.52` named by the user asserts the guard DOES trip (verbatim-figure semantics preserved) — proving the fix is scoped to the fallback.

Add an exact-boundary case to `test_documented_arming_formula_reserves_full_plan_in_cap_mode`: two $0.27 items (`total/(1−r)` lands on the exact cent $0.60) — the final reserve must succeed; bare ceil fails this case.

`tests/contracts/test_agent_instruction_integrity.py::test_arming_formula_is_canonical_across_proposal_gates` — **dynamic sweep** (panel ruling, keeps D's no-allowlist marker test satisfiable): every file under `skills/pipelines/` containing `tracker.budget_total_usd =` must contain `math.ceil(total_estimated_usd / (1 - tracker.reserve_pct) * 100) / 100 + 0.01`, and the string `or total_estimated_usd` must appear in ZERO of them. Sentinel floor: the discovered set contains all six gate files named above (an empty sweep proves nothing).

### Risk

Arming at the cap when the user silently approves grants more spend ceiling than the old formula (up to cap − estimate). Mitigated: the cap is exactly the number the gate displayed and the user approved; per-item guards (single-action threshold, first-paid-use) still apply unchanged. The `min_workable_usd` floor can exceed the displayed cap only when the estimate already busted the cap — a state Step 6's `budget_verdict = "over_budget"` forces the agent to surface before the gate anyway.

---

## C2. [MAJOR] Compose reserves narration under `openai_tts` but the proposal armed `tts_selector`

**Files:** `skills/pipelines/explainer/compose-director.md:87-110`; canonical rule added to `skills/meta/checkpoint-protocol.md` (new shared section, see C6 placement).

### Fix

**Canonical rule** — add to `skills/meta/checkpoint-protocol.md` under the new `### Cost Ledger Governance (shared)` section (C6):

> **One name per line of spend, end to end.** Every `tracker.estimate` / `approve_tool` / `reserve` for the same line of work uses the tool name **exactly as it appears in the approved plan's `cost_estimate` line items** — that is what the gate's `approve_tool` loop armed, and the first-paid-use guard compares raw strings (`tools/cost_tracker.py:171-176`). If the plan named a selector (`tts_selector`), the executing stage books under the selector name even when it invokes a concrete provider directly or the selector routes to one — record the concrete provider in the `operation` string (e.g. `"narration via openai_tts"`) and in the run's `decision_log` `provider_selection` entry. If the plan named a concrete tool (`talking_head`), book under that name. Introducing a new tool name at spend time trips the guard **by design** — that is a structured blocker to escalate, never a cue to rename or self-`approve_tool` around it.

**Text change** — `explainer/compose-director.md:100`:

Before:
```python
   estimated_usd = OpenAITTS().estimate_cost(tts_inputs)
   entry_id = tracker.estimate("openai_tts", "narration", estimated_usd)
```
After:
```python
   estimated_usd = OpenAITTS().estimate_cost(tts_inputs)  # price from the concrete tool
   # Ledger keys on the PLAN's line-item name: proposal Step 6 plans narration
   # as "tts_selector", and that is the name Step 9's approve_tool armed. The
   # concrete provider lives in the operation string and the decision_log
   # provider_selection entry — see checkpoint-protocol.md, Cost Ledger
   # Governance.
   entry_id = tracker.estimate("tts_selector", "narration via openai_tts", estimated_usd)
```

Add a one-line pointer to the shared rule in `explainer/proposal-director.md` Step 9 (after the approve_tool loop, ~line 535): "Downstream stages must book under these exact names — see `skills/meta/checkpoint-protocol.md` → Cost Ledger Governance."

### Why this design

The guard's documented semantics (proposal Step 9:554-556) are plan-membership: "a tool with no line item from Step 6 trips the first-paid-use guard." The plan is expressed in selector terms whenever routing is deferred, so plan-name keying completes the existing design with zero code change. Alternative — concrete-name keying, with the executing stage calling `approve_tool("openai_tts")` when the user confirms the audio setup — lost because it puts the arming call in the hands of the same agent about to spend (self-approval at the point of spend hollows the guard, contradicting this branch's own "not waived at spend time" contract) and forks the rule per pipeline. Provider provenance is not lost: it lands in `operation` and in the `decision_log` entry AGENT_GUIDE already mandates before any paid call.

### Acceptance

`tests/tools/test_cost_tracker_governance.py::test_plan_name_keyed_reserve_passes_first_paid_use_guard` — **behavioral**: tracker with `require_approval_for_new_paid_tool=True`; `approve_tool("tts_selector")`; `estimate("tts_selector", "narration via openai_tts", 0.18)`; `reserve(entry_id, user_approved=True)` succeeds. Then `estimate("openai_tts", ...)` + reserve raises `ApprovalRequiredError` — the exact failure the old doc text instructed.

`tests/contracts/test_agent_instruction_integrity.py::test_compose_ledger_keys_match_proposal_line_items` — asserts `explainer/compose-director.md` contains `tracker.estimate("tts_selector"` and does NOT contain `tracker.estimate("openai_tts"`; asserts `skills/meta/checkpoint-protocol.md` contains "One name per line of spend".

### Risk

An expensive concrete provider hiding under an approved selector name no longer trips the first-paid-use guard. Mitigated: the estimate still comes from the concrete tool (real dollars), and the single-action threshold + budget check still apply per entry; the decision-log `provider_selection` entry keeps the human-visible audit of which provider was routed.

---

## C3. [MINOR] `actual_usd = result.cost_usd or estimated_usd` books phantom spend on failed calls

**Files (all seven sites):** `skills/pipelines/explainer/asset-director.md:83-89`, `animation/asset-director.md:110-112`, `cinematic/asset-director.md:~97-100`, `avatar-spokesperson/asset-director.md:48-50`, `hybrid/asset-director.md:48-50`, `documentary-montage/asset-director.md:77-79`, `explainer/compose-director.md:87,109`.

### Fix

One canonical booking block replaces `result = <tool>.execute(inputs)` through `tracker.reconcile(...)` at all seven sites (tool/inputs names stay per-site):

```python
result = image_selector.execute(inputs)

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
    # budget_spent_usd counts FAILED entries (tools/cost_tracker.py:103-109),
    # so a substituted estimate is phantom spend that shrinks usable budget
    # and can block the real retry in cap mode.
    actual_usd = reported
tracker.reconcile(entry_id, actual_usd, success=result.success)
```

Plus one prose bullet after the block (all seven sites, or once in the shared section with a pointer):

> **Known-free routes book $0.00.** When the result itself shows the routed provider is free/local (e.g. the selector's `result.data` names a $0 route, or the entry was estimated at $0), a success reporting 0.0 IS the actual cost — book 0.0, not the estimate.

In `explainer/compose-director.md:87`, change the prose "(fall back to the estimate if the tool reports zero)" to "(reconcile per the booking rule below — estimates never substitute for failed-call costs)", and expand the inline `tracker.reconcile(entry_id, result.cost_usd or estimated_usd, ...)` at :109 into the canonical block.

`reported = result.cost_usd or 0.0` is deliberately None-tolerant so the block survives a future `Optional[float]` migration of `ToolResult.cost_usd` (see Dependencies).

### Why this design

Failure-books-reported fixes the verified money bug (phantom spend counted by `budget_spent_usd`, blocking retries in cap mode); success-with-zero-books-estimate stays deliberately conservative — under-reporting spend is the worse governance failure, and this repo's owner explicitly pays overhead over risk. The alternative — booking 0.0 on unreported success — lost because today's `ToolResult` cannot distinguish "unreported" from "free" (float default 0.0), and silently zeroing paid work would make the compose-stage "totals match actual spend" criterion unverifiable in the common direction. The flag for the substituted-estimate case is the chat/cost-snapshot disclosure — `reconcile()` has no note parameter and adding one is out of scope for a doc workstream.

### Acceptance

`tests/tools/test_cost_tracker_governance.py::test_documented_booking_rule_failed_call_books_no_phantom_spend` — **behavioral**: tracker in CAP mode, budget armed per C1; estimate+reserve $0.60; execute the documented block against a stub `ToolResult(success=False, cost_usd=0.0)`; assert entry status `failed`, `actual_usd == 0.0`, `budget_spent_usd == 0.0`, and a subsequent $0.60 retry reserve succeeds (the critic's stall scenario, inverted). Sibling asserts: success + `cost_usd=0.0` + `estimated_usd=0.60` books 0.60; success + `cost_usd=0.55` books 0.55.

`tests/contracts/test_agent_instruction_integrity.py::test_no_or_estimated_fallback_survives_in_ledger_blocks` — asserts the string `result.cost_usd or estimated_usd` appears in ZERO files under `skills/pipelines/`, and that all seven named files contain `NEVER substitute the estimate on failure` (canonical-block presence, all seven — closes the explainer-only coverage gap flagged in the test-quality findings for this block).

### Risk

A truly-free routed success with a paid estimate still over-books (the ambiguity is structural in `ToolResult`). Mitigated by the known-free-route bullet; fully fixed only by the Optional `cost_usd` change noted in Dependencies. The block is ~10 lines longer per site — acceptable, these lines are the money path.

---

## C4. [MINOR] `music_gen.estimate_cost` examples omit required `duration_seconds`

**Files:** `skills/pipelines/documentary-montage/asset-director.md:72`, `skills/pipelines/documentary-montage/idea-director.md:216-218`.

### Fix

`music_gen.estimate_cost` raises `ValueError` without `duration_seconds` (`tools/audio/music_gen.py:101-109`: "Derive it from the approved target runtime… Silent defaults are not permitted"). The doc-montage brief carries top-level `duration_seconds` (idea-director:167).

`asset-director.md:72` — before: `inputs = {"prompt": brief["music_plan"]["prompt_seed"]}`. After:

```python
inputs = {
    "prompt": brief["music_plan"]["prompt_seed"],
    "duration_seconds": brief["duration_seconds"],  # required — estimate_cost raises without it
    "output_path": f"projects/{project_id}/assets/music/score_bed.mp3",
}
```

(`output_path` added because the same `inputs` dict feeds `music_gen.execute(inputs)` at :77, and the workspace contract requires an explicit path under `projects/<id>/`.)

`idea-director.md:216-218` — define the previously-undefined `music_plan_inputs`:

```python
tracker = CostTracker.for_project(project_id)  # every downstream stage reopens this same ledger
music_plan_inputs = {
    "prompt": music_plan["prompt_seed"],
    "duration_seconds": duration_seconds,  # required — music_gen.estimate_cost raises without it
}
estimated_usd = music_gen.estimate_cost(music_plan_inputs) if music_plan["source"] == "generated" else 0.0
tracker.estimate("music_gen", "score_bed", estimated_usd)
```

(`duration_seconds` is already in scope — used at :207.)

### Why this design

Matches the contract the branch's own sibling docs state ("music_gen (needs `duration_seconds` in inputs, raises without it)", explainer proposal-director:475). Score-bed duration = episode duration is what the ValueError's own message prescribes.

### Acceptance

`tests/contracts/test_agent_instruction_integrity.py::test_doc_montage_music_examples_carry_duration_seconds` — for both files, extract the fenced Python blocks containing `music_gen.estimate_cost` and assert `"duration_seconds"` appears inside the same `inputs` dict literal. **Behavioral leg**: `tests/tools/test_cost_tracker_governance.py::test_music_gen_estimate_contract` executes `MusicGen().estimate_cost({"prompt": "x", "duration_seconds": 90})` → returns `0.15`, and asserts the **duration-less** call (`{"prompt": "x"}`) raises `ValueError` (panel wording fix — the raise keys on missing `duration_seconds`, not on a missing prompt; a promptless dict carrying `duration_seconds` returns normally).

### Risk

Near zero — example-only correction. If a future brief drops top-level `duration_seconds`, the example dangles; the schema quality-gate ("Duration… concrete numbers", idea-director:240) guards that upstream.

---

## C5. [NIT] False rationale: "estimated placeholders double-count against usable_budget_usd"

**Files:** `skills/pipelines/animation/proposal-director.md:496-499`, `skills/pipelines/cinematic/proposal-director.md:338-341`; align `skills/pipelines/explainer/proposal-director.md:537-544` to the same wording (C1 already demands identical arming blocks across the three).

### Fix

Replace point 3's comment (instruction — the refund loop — unchanged) in all three files:

```python
# 3. This stage's seeded entries were placeholders — created only so the
#    on-screen estimate and cost_log.json agreed at the gate. They are never
#    executed: the stage that actually spends creates and reserves its OWN
#    entry. Refund them so every entry reaches a terminal state before the
#    compose-stage cost_log check. (An `estimated` entry does NOT consume
#    budget — usable_budget_usd subtracts only reserved + spent — so this is
#    ledger hygiene, not a budget fix. Never RESERVE a placeholder: a
#    reservation nothing will ever reconcile WOULD eat usable_budget_usd
#    for the rest of the run.)
for entry in tracker.entries:
    if entry["status"] == "estimated":
        tracker.refund(entry["id"])
```

### Why this design

States the true mechanics (`budget_reserved_usd` sums only RESERVED entries, `tools/cost_tracker.py:95-101`; `estimate()` writes `reserved_usd: 0.0`, `:139`), keeps the correct instruction, and preserves the genuinely important warning (never reserve a placeholder) that the false rationale was gesturing at.

### Acceptance

`tests/contracts/test_agent_instruction_integrity.py::test_placeholder_refund_rationale_is_truthful` — asserts the string `double-counting against tracker.usable_budget_usd` appears in ZERO files under `skills/pipelines/`, and all three proposal-directors contain `does NOT consume budget`.

### Risk

None functional — comment-only. Keeping all three verbatim-identical is itself the mitigation against future drift.

---

## C6. Home + draft text for B's stranded-`reserved` recovery protocol (DEPENDENT ON B)

**File:** `skills/meta/checkpoint-protocol.md` — two additions.

### Where, and why there

1. New top-level section `### Cost Ledger Governance (shared)` inserted after `### Step 7: Resume Protocol` (:197-218). It holds: (a) C2's naming rule, (b) a pointer to C3's canonical booking rule, (c) the recovery protocol below, (d) one sentence on ledger corruption (pointer only, never a restated protocol — panel ruling): "A corrupt `cost_log.json` raises `CostLogCorruptedError`; its message carries the full recovery call (`CostTracker.reconstruct_from_snapshot`) — follow it, and never delete the ledger or start a fresh one by hand."
2. One new numbered item appended to Step 7's resume checklist: "**Sweep the ledger** — see Cost Ledger Governance below."

Why here and not a new `skills/meta/cost-governance.md`: checkpoint-protocol.md is already on the mandatory per-stage path (AGENT_GUIDE Orchestrator step 6) and already carries the cost_snapshot wiring (Step 2 item 4, :35-48); stranded reservations are discovered exactly at resume, which is this skill's Step 7. A new file guarantees nothing reads it.

### Draft text (placeholders ⟨…⟩ are B's to fill — do not land before B's design is fixed)

> **Stranded entries.** A crash between `reserve()` and `reconcile()` leaves an entry in `reserved` with no owner — it silently eats `usable_budget_usd` for the rest of the run. A crash between `estimate()` and `reserve()` leaves an `estimated` orphan — it holds no budget, but both shapes guarantee the compose-stage "every entry in a terminal state" criterion fails. On resume (Step 7), after determining `next_stage`, open the tracker and check:
>
> ```python
> stranded = tracker.non_terminal_entries()   # B3's API — estimated AND reserved orphans
> ```
>
> For each stranded entry:
> 1. **Escalate, don't guess** — surface a structured blocker (AGENT_GUIDE → "Escalate Blockers Explicitly"): tool, operation, reserved amount, timestamp.
> 2. **Establish billing truth**: check the call's declared `output_path` on disk (a finished artifact usually means the charge landed), the interrupted stage's `metadata.partial_progress`, and — if the user can — the provider dashboard.
> 3. **Resolve** (the rules in `non_terminal_entries()`'s docstring are the authority): a `reserved` orphan with output on disk / known billed → `tracker.reconcile(entry_id, ⟨known cost or the entry's estimated_usd⟩, success=⟨output usable⟩)`; confirmed unbilled → `tracker.refund(entry_id)`; unknowable → reconcile at the estimate with `success=False` — overstating spend is the safe direction for a budget guard. An `estimated` orphan was never executed → `tracker.refund(entry_id)` (placeholder hygiene, same rule as C5), then re-plan the work as a fresh estimate → reserve → reconcile round trip if still wanted.
> 4. **Log the ruling** as a `decision_log` entry — `category: "budget_tradeoff"` (schema'd enum), `subject: "stranded reservation ⟨entry_id⟩"` — so the audit trail records who decided the stranded money's fate and why.
>
> Never leave a `reserved` entry in place "to be safe": it mis-states both budget and the terminal-state criterion in one move.

### Acceptance

Deferred to B's mechanism landing; the doc leg: `tests/contracts/test_agent_instruction_integrity.py::test_checkpoint_protocol_has_stranded_reservation_recovery` — asserts checkpoint-protocol.md contains `non_terminal_entries()` and `budget_tradeoff` in the governance section (panel fix — pinning the raw status-comprehension would institutionalize bypassing B3's API and miss `estimated` orphans). Behavioral coverage of the resolution calls belongs to B/G.

### Risk

If B ships a sweep API with different semantics (e.g. auto-expiry), this text must be updated in the same PR — mark the section with a `<!-- SYNC: tools/cost_tracker.py recovery API -->` comment so B's change greps its way here.

---

## Dependencies

- **C6 blocks on Workstream B**: the recovery steps name today's `refund`/`reconcile` API; B's stranded-reservation design (sweep API, reload-before-save, atomic `_save`) may rename or replace the resolution call. Land C6's section in the same PR as B's mechanism, or after it.
- **C3 constraint on A/B**: the root ambiguity (reported-$0 vs unreported) is `ToolResult.cost_usd: float = 0.0` (`tools/base_tool.py:135`). If A/B migrates it to `Optional[float] = None`, C3's block already tolerates None (`result.cost_usd or 0.0`) but the success-with-None branch should then book 0-reported as genuinely free — one comment edit at the seven sites. Flag in whichever workstream touches `base_tool.py`.
- **Workstream G overlap**: the acceptance tests above extend `tests/contracts/test_agent_instruction_integrity.py` and `tests/tools/test_cost_tracker_governance.py`, the same files G's findings target (explainer-only coverage, missing `reconcile(success=False)` coverage). C3/C1's behavioral tests satisfy part of G's gap — coordinate to avoid duplicate tests with different names.
- **Workstream D constraint**: when D wires the six unwired pipelines (screen-demo, talking-head, podcast-repurpose, character-animation, localization-dub, clip-factory), their new ledger blocks MUST copy the C1 arming block, C2 naming rule, and C3 booking block verbatim — not the pre-fix wording from the six already-wired pipelines' git history.


**Open questions:** none
**Dependencies:** Workstream B — C6's recovery text names refund/reconcile as the resolution calls; if B ships a sweep/expiry API or reload-before-save semantics, C6 must land with or after B's design and use its API names | Workstream A/B (whichever touches tools/base_tool.py) — C3's success-with-$0 ambiguity is structural in ToolResult.cost_usd: float = 0.0; an Optional[float] migration would let C3 book reported-$0 as genuinely free (one comment edit across seven sites) | Workstream G — C1/C2/C3 acceptance tests extend the same two test files G's coverage findings target; coordinate names to avoid duplicates | Workstream D — the six pipelines D wires must copy the post-fix canonical blocks (C1 arming, C2 naming, C3 booking), not the pre-fix wording


---

# Fix Spec — Workstream D: finish the ledger rollout (6 remaining pipelines)

Finding owned: **[MAJOR] pipeline_defs/screen-demo.yaml:46 (schema-contract) — Ledger wired into only 6 of 12 episode pipelines; unwired paid pipelines will checkpoint $0 cost snapshots.**

Scope: manifest additions in `pipeline_defs/` and ledger blocks in `skills/pipelines/` for screen-demo, talking-head, podcast-repurpose, character-animation, localization-dub, clip-factory. framework-smoke stays excluded (test pipeline, `tools_available: []`). Every block below is **C's canonical text with per-pipeline substitutions** — C1 arming, C2 naming, C3 booking (`/tmp/.../spec-draft-C-ledger-skills.md`). Never copy the pre-fix wording out of the six already-wired pipelines' git history.

Why this is a real bug and not just incompleteness: `skills/meta/checkpoint-protocol.md` Step 2 item 4 (:34-48) now instructs **every** pipeline's checkpoint to embed `cost_snapshot = tracker.cost_snapshot()`. In an unwired pipeline the tracker is never armed and never written, so a paid screen-demo run checkpoints `total_spent_usd: 0.0` against config's $15 default — the Backlot cost meter and reconciliation report zero for money actually spent. All paid-tool claims below verified in source: `tts_selector`/`image_selector`/`music_gen` are paid (selectors delegate `estimate_cost` to the routed provider; `music_gen` = $0.05/30s, `tools/audio/music_gen.py:110-111`); `talking_head`, `lip_sync`, `subtitle_gen`, `audio_enhance`, `color_grade`, `face_enhance`, `eye_enhance`, `diagram_gen`, `code_snippet` and all compose/trim/mix tools are local/free (`tools/avatar/talking_head.py:131-132`, `tools/avatar/lip_sync.py:126-127`; the rest inherit `base_tool.py:376-378`'s `return 0.0`).

---

## D0. Shared canon (applies to every pipeline below)

### The four blocks and their markers

Uniform heading markers, so Workstream G's contract tests can discover block-carrying skills by suffix match on heading text (heading LEVEL and NUMBER follow each file's local style; the SUFFIX is the invariant):

| Block | Heading suffix (exact) | Canonical source |
|---|---|---|
| Gate seeding + cap math (idea-led) | `Compute Budget And Seed The Cost Ledger` | `skills/pipelines/hybrid/idea-director.md:75-106`, with **C1's** corrected arming (doc-montage substitution shape, C spec :56-62) |
| Gate arming (proposal-led) | `On Approval — Arm the Tracker` | `skills/pipelines/explainer/proposal-director.md:523-558`, Step 9 point 1 replaced by **C1's** canonical block |
| Asset-stage discipline | `Ledger Discipline For Every Paid Call` | `skills/pipelines/avatar-spokesperson/asset-director.md:38-53`, booking replaced by **C3's** canonical block, naming per **C2** |
| Compose close-out | `Ledger Round-Trip For The Render` | `skills/pipelines/avatar-spokesperson/compose-director.md:29` paragraph, promoted under this new heading |

Three normalizations of already-wired files land with this workstream so the markers hold repo-wide (G's discovery then needs zero exceptions):

1. `skills/pipelines/explainer/asset-director.md:69` — insert `### Ledger Discipline For Every Paid Call` above the bold `**Ledger discipline for every paid call.**` paragraph (the only wired asset block with no heading; hybrid/avatar/cinematic/animation/doc-montage already carry it).
2. **Rename** the round-trip paragraphs' existing headings to end with the marker suffix (panel fix — avatar's paragraph already sits under `### 0b. Cost Track The Render`; inserting a second heading would stack a stray duplicate): avatar-spokesperson's becomes `### 0b. Ledger Round-Trip For The Render`, and likewise at `hybrid/compose-director.md:33`, `cinematic/compose-director.md:60`, `animation/compose-director.md:153`, `documentary-montage/compose-director.md:72` — rename where a heading exists, insert only where the paragraph is genuinely unheaded; never stack a second heading.
3. `explainer/compose-director.md` (panel fix — this marker was previously owned by nobody): add `### Ledger Round-Trip For The Render` as a new subsection after its paid-TTS/music steps, carrying the avatar round-trip paragraph adapted to a batched `tracker.estimate("video_compose", "render", 0.0)` $0 entry. Lands as one edit with C2/C3's changes to the same file — C owns the TTS text, this heading+block is D's.

### No lighter variant — one protocol, batching does the lightening

Ruling on the near-zero-spend question (screen-demo real-capture, talking-head, clip-factory): **full ceremony everywhere, no "lite" block.** Justification: (1) checkpoint-protocol Step 2 item 4 pulls `cost_snapshot()` unconditionally in every pipeline — even an all-free run needs an armed `budget_total_usd` (else the snapshot reports config's $15 instead of the gate-approved cap) and a seeded ledger (else $0-spent is unrecorded rather than proven); (2) a second block spelling forks the canonical text C just fixed and doubles G's discovery surface; (3) repo owner explicitly pays overhead over output risk (memory: pipeline-quality-over-cost). The lightening is data, not protocol: the explainer batching rule (`explainer/asset-director.md:94` — one entry per same-tool batch) applies verbatim, so an all-free stage books ONE `$0.00` round-trip entry per logical batch (e.g. `estimate("subtitle_gen", "subtitles x 8 clips", 0.0)`), not one per artifact.

### Recovery and corruption

No per-pipeline text. All six manifests already require `meta/checkpoint-protocol` (verified: screen-demo:67, talking-head:27, podcast-repurpose:37, character-animation:42, localization-dub:35, clip-factory:36), so C6's shared `Cost Ledger Governance` section (stranded-entry recovery via B3's `non_terminal_entries()`, C2's one-name rule, C3 booking pointer) reaches them for free. Ledger **corruption** handling is deliberately NOT skill text (panel fix): it is carried entirely by B1's `CostLogCorruptedError` message — agents read and act on it — and C6 carries only a one-sentence pointer; a D implementer must not add per-pipeline corruption text. New blocks below reference the shared section by pointer only — never restate it.

### Manifest criteria (copied verbatim from `animated-explainer.yaml:198,252`)

- Paid-stage criterion: `Schema-valid cost_log persisted to projects/<id>/artifacts/cost_log.json with an entry for every paid tool call made in this stage`
- Compose criterion: `Schema-valid cost_log with every entry in a terminal state (completed/failed/refunded) and totals matching what the run actually spent`

---

## D1.1 screen-demo (`pipeline_defs/screen-demo.yaml`, skills/pipelines/screen-demo/)

**Manifest.** In `orchestration` (after `budget_default_usd: 1.00`, :46): `budget_per_output_minute_usd: 0.25`. Justification: the only duration-scaled paid cost is synthetic/silent-capture narration via `tts_selector` (~$0.01/min on the openai_tts route at $0.000015/char, up to ~$0.24/min on elevenlabs-class routes); image/diagram cards are a fixed handful (opening/transition/outro, `asset-director.md:90-100`) covered by the $1.00 floor. 0.25 covers the priciest TTS route with retry headroom; a 4-min synthetic demo meets the floor, a 10-min tutorial scales to $2.50. Well below the generative 0.60 because the screen capture IS the visual track. Add paid-stage criterion to `assets` success_criteria (:170-172); compose criterion to `compose` (:224-226).

**Skills.**
- `idea-director.md`: insert `### 5b. Compute Budget And Seed The Cost Ledger` between `### 5. Build The Brief` (:95) and `### 6. Quality Gate` (:120). Hybrid :77-106 text with substitutions: manifest path `pipeline_defs/screen-demo.yaml`, comments `# $1.00 floor` / `# $0.25/min`, `target_minutes` from the brief's target output duration. Itemize per production mode: synthetic/silent-capture → `tts_selector` (quantity 1, full narration text) + `image_selector` cards (unit-priced × planned count, per the quantity rule at explainer proposal-director:475); real capture with voiceover → line items may legitimately all be $0.00 — **seed and arm anyway** (the armed cap and honest-$0 ledger are the point). Arming uses C1's doc-montage-shaped block (`approved_budget_usd or max(default_budget_cap_usd, min_workable_usd)`) plus C1's prose rule verbatim.
- `asset-director.md`: insert `### 1c. Ledger Discipline For Every Paid Call` between `### 1b. Hero Scene Sample (Mandatory)` (:45) and `### 2. Generate Subtitles First` (:55) — placed before the paid sites so the hero sample's TTS/image calls (its first paid spend) are covered. Avatar :40-53 text with C3's booking block; example entry `tracker.estimate("tts_selector", "narration via openai_tts", estimated_usd)` (C2: plan-name key, provider in operation). Free-tool list for the $0 round-trip: `subtitle_gen`, `diagram_gen`, `audio_enhance`.
- `compose-director.md`: add the Cost tracker row to `## Prerequisites` (:20-28) as in avatar compose :22, and append `### Ledger Round-Trip For The Render` as the last Process subsection (after `### 5. Verify Every Output`, before `## Common Pitfalls` :95) — avatar :29 paragraph verbatim.

**Wrinkle.** Mode-dependent spend: the gate presents whichever mode the brief chose; if the mode changes after the gate (real→synthetic adds narration), that is new spend outside the approved plan — the first-paid-use guard trips by design; escalate per C2, never self-approve.

---

## D1.2 talking-head (`pipeline_defs/talking-head.yaml`, skills/pipelines/talking-head/)

**Manifest.** After `budget_default_usd: 0.50` (:32): `budget_per_output_minute_usd: 0.05`. Justification: the only paid tool anywhere in the manifest is optional `image_selector` overlay graphics (~$0.04–0.08/unit; density well under 1 per output minute per `asset-director.md` Step 4) — `talking_head`/`lip_sync` are local/free. A rate is still warranted: a 20–30-min overlay-rich edit plausibly exceeds the $0.50 flat cap (12 overlays ≈ $0.50–1.00); 0.05/min gives a 20-min edit a $1.00 default cap while shorts keep the $0.50 floor. Add paid-stage criterion to `assets` (:132-134); compose criterion to `compose` (:209-211).

**Skills.**
- `idea-director.md`: insert `### Step 3b: Compute Budget And Seed The Cost Ledger` between Step 3 (:44) and Step 4 (:55) (this file numbers `Step N:`). Substitutions: manifest path, `# $0.50 floor` / `# $0.05/min`, target minutes from the brief's **Target duration** field. Itemize `image_selector` overlays (unit × planned count); `subtitle_gen`/`audio_mixer` $0. C1 arming + prose rule.
- `asset-director.md`: insert `### Step 0b: Ledger Discipline For Every Paid Call` between Step 0 (:19) and Step 1 (:29). Example entry `tracker.estimate("image_selector", "overlay_graphics x 4", estimated_usd)`; C3 booking; batching rule for the overlay set. Free round-trip: `subtitle_gen`, `audio_mixer`.
- `compose-director.md`: Cost tracker row in `## Prerequisites` (:15-23); insert `### Step 6b: Ledger Round-Trip For The Render` between `### Step 6: Final Encode — MANDATORY` (:391) and `### Step 7: Visual QA` (:420) — reconcile once the final encode lands. All enhancement-chain tools (`face_enhance`, `eye_enhance`, `color_grade`, `auto_reframe`, …) are local: fold them into the render's batched $0 entry (cinematic compose :60 precedent: "Do the same for any color_grade/audio_enhance passes actually run").

**Wrinkle.** None beyond the tiny rate — this is deliberately the smallest honest wiring, not a variant protocol.

---

## D1.3 podcast-repurpose (`pipeline_defs/podcast-repurpose.yaml`, skills/pipelines/podcast-repurpose/)

**Manifest.** After `budget_default_usd: 1.00` (:16): `budget_per_output_minute_usd: 0.30`. Justification: paid profile is `music_gen` beds ($0.10/min generated, `music_gen.py:111`) plus `image_selector` quote/speaker cards (a few cents per deliverable); no TTS, no video gen — the podcast audio is content already in hand. 0.30 = music rate + amortized graphics + retry headroom. Add paid-stage criterion to `assets` (:139-141); compose criterion to `compose` (:190-192).

**Skills.**
- `idea-director.md`: insert `### 5b. Compute Budget And Seed The Cost Ledger` between `### 5. Build The Brief` (:67) and `### 6. Quality Gate` (:81). **Output-minutes substitution** (first of the two multi-deliverable pipelines): `target_minutes` is the SUM of planned output minutes across the `deliverable_mix` — every clip plus the full-episode companion if planned — not the source runtime and not any single deliverable. Show the sum in the gate math line (e.g. `6 clips × 0.5 min + 12 min companion = 15 output min → max($1.00, $0.30 × 15) = $4.50`). Itemize: `music_gen` (**with `duration_seconds` in inputs, per C4 — raises without it**; one line item per planned bed), `image_selector` cards (unit × count); `subtitle_gen`/`audio_enhance` $0. C1 arming + prose rule.
- `asset-director.md`: insert `### 1c. Ledger Discipline For Every Paid Call` between `### 1b. Hero Scene Sample (Mandatory)` (:27) and `### 2. Treat Topic Graphics As Optional` (:37). Example entries: `tracker.estimate("music_gen", "clip_bed_hook_1", estimated_usd)` with the C4-compliant inputs dict shown, and `tracker.estimate("image_selector", "quote_cards x 6", ...)`. C3 booking block.
- `compose-director.md`: Cost tracker row in `## Prerequisites` (:15-23); append `### Ledger Round-Trip For The Render` before `## Common Pitfalls` (:67). One batched $0 entry covering all deliverable renders: `tracker.estimate("video_compose", "render x 6 clips + companion", 0.0)`.

**Wrinkle.** The output-minutes sum is recomputed if the user trims the clip count at the gate — the approved plan's minutes, not the pitch's.

---

## D1.4 character-animation (`pipeline_defs/character-animation.yaml`, skills/pipelines/character-animation/) — the one proposal-led pipeline

**Manifest.** After `budget_default_usd: 2.00` (:48): `budget_per_output_minute_usd: 0.60`. Justification: identical paid trio to animated-explainer — `tts_selector` narration/dialogue + `image_selector` character sheets/backgrounds/props + `music_gen` score — with rendering local (`character_rig_renderer` free). Two pipelines with the same paid profile must price the same minute the same way; 0.60 matches explainer/animation exactly. Criteria on **three** stages: paid-stage criterion on `character_design` success_criteria (:150-152) **and** `assets` (:221-224) — `character_design` has `image_selector` in `tools_available` (:141-143), so paid calls legally happen there, a placement no other pipeline needs; compose criterion on `compose` (:277-281).

**Skills** (this pipeline's files are terse and use `##` headings — keep that register; the heading-suffix markers still hold):
- `proposal-director.md`: extend `## Cost Honesty` (:53-62) with the gate machinery in the file's terse style: (a) cap math per explainer Step 5c (:405-429) — manifest path `pipeline_defs/character-animation.yaml`, selected concept's `target_duration_seconds`, show the max() math at the gate; (b) seeding per explainer Step 6 (:448-477) — registry `estimate_cost` per line item, the two-pricing-shapes rule verbatim (`tts_selector`/`music_gen` quantity 1 with full payload and `duration_seconds`; `image_selector` unit × count), computed budget verdict; then a new `## On Approval — Arm the Tracker` section before `## Gate Reminder (Binding)` (:65) carrying C1's canonical arming block + prose rule and the C2 pointer line ("Downstream stages must book under these exact names — see `skills/meta/checkpoint-protocol.md` → Cost Ledger Governance"). The sample sub-stage's tools (:102-109) are all local/free — book the sample as one batched $0 round-trip.
- `character-design-director.md`: append to `## Tool Use` (:25-29): "`image_selector` calls here are paid spend under the approved plan — run the full Ledger Discipline round trip (see asset-director → Ledger Discipline For Every Paid Call) before generating character sheets; this stage's manifest criterion requires a ledger entry for every paid call made here." Pointer, not a duplicate block — the asset-director's block is the pipeline's single canonical copy.
- `asset-director.md`: insert `## Ledger Discipline For Every Paid Call` between `## Layer 3 Gate` (:8) and `## Asset Organization` (:24). Avatar text + C3 booking; example entries `tracker.estimate("tts_selector", "dialogue via openai_tts", ...)`, `tracker.estimate("image_selector", "backgrounds x 5", ...)`, `tracker.estimate("music_gen", "score_bed", ...)` with the C4 `duration_seconds` inputs dict shown. Free round-trip: `character_rig_renderer`.
- `compose-director.md`: insert `## Ledger Round-Trip For The Render` before `## Quality Bar` (:46). `character_rig_renderer` + `video_compose` + `character_animation_reviewer` passes fold into one batched $0 entry.

**Wrinkle.** The `character_design` criterion is the novel placement — spec'd above; nothing else diverges from the explainer reference.

---

## D1.5 localization-dub (`pipeline_defs/localization-dub.yaml`, skills/pipelines/localization-dub/)

**Manifest.** After `budget_default_usd: 3.00` (:14): `budget_per_output_minute_usd: 0.40`. Justification: the dominant (near-only) paid cost is dub TTS, which scales linearly with **localized output minutes** — source minutes × target languages (up to ~$0.24/min on elevenlabs-class routes, plus pronunciation-retake headroom); `lip_sync` is local/free, subtitles free. 0.40 covers the priciest route with retake margin; below the generative 0.60 because no visual/music generation exists here. The $3.00 default — largest in the repo — already encodes multi-language intent: 5-min source × 2 languages → max($3.00, 0.40 × 10) = $4.00, so scaling engages exactly when a second language is added. Add paid-stage criterion to `assets` (:133-135); compose criterion to `compose` (:184-186).

**Skills.**
- `idea-director.md`: insert `### 4b. Compute Budget And Seed The Cost Ledger` between `### 4. Build The Brief` (:53) and `### 5. Quality Gate` (:65). **Localized-minutes substitution** (the pipeline's defining wrinkle):

  ```python
  target_languages = metadata["target_languages"]
  localized_minutes = (source_duration_seconds / 60) * len(target_languages)
  default_budget_cap_usd = max(flat_default, per_minute_rate * localized_minutes)
  ```

  Show the language factor in the gate math (`max($3.00, $0.40/min × 5 min × 2 languages) = $4.00`). Itemize ONE `tts_selector` line item PER LANGUAGE (quantity 1, that language's full translated script text as the payload — the whole-payload pricing shape), so the gate and the ledger both show per-language dub costs, and dropping a language at the gate drops its line item. `lip_sync`/`subtitle_gen`/`audio_enhance` seed at $0. C1 arming + prose rule.
- `asset-director.md`: insert `### 1c. Ledger Discipline For Every Paid Call` between `### 1b. Hero Scene Sample (Mandatory)` (:22) and `### 2. Generate Dubbed Audio Per Language` (:32). C2 naming made concrete for the per-language shape: one entry per language, plan-name key, provider + locale in the operation string — `tracker.estimate("tts_selector", "dub_es via azure_tts", estimated_usd)` — matching the per-language line items armed at the gate. A language added mid-run has no line item → the guard trips by design → escalate. C3 booking; `lip_sync` runs get the $0 round-trip.
- `compose-director.md`: Cost tracker row in `## Prerequisites` (:15-23); append `### Ledger Round-Trip For The Render` before `## Common Pitfalls` (:61). One batched $0 entry per locale render set (`"render x 2 locales"`).

---

## D1.6 clip-factory (`pipeline_defs/clip-factory.yaml`, skills/pipelines/clip-factory/)

**Manifest.** **Omit `budget_per_output_minute_usd`** (the key is optional, `schemas/pipelines/pipeline_manifest.schema.json:177`). Justification: clip-factory exposes ZERO paid tools anywhere — `subtitle_gen`, `audio_enhance`, `video_compose`, `video_trimmer`, `audio_mixer`, `color_grade` all price $0 (base_tool default; verified none override `estimate_cost`). A duration rate would scale a spend ceiling for spend that cannot occur through any tool the manifest offers; the flat $1.00 stays as pure headroom. Add a YAML comment on the `budget_default_usd: 1.00` line (:15): `# no per-minute rate: no paid tools in this manifest — re-add budget_per_output_minute_usd if a paid tool is ever added`. Add paid-stage criterion to `assets` (:131-133) and compose criterion to `compose` (:184-186) anyway — with zero paid calls they are satisfied by the seeded, armed, all-$0 ledger, and they are what makes the checkpoint's `$0` snapshot *proven* rather than merely unrecorded (and what G's dynamic discovery keys on).

**Skills.**
- `idea-director.md`: insert `### 5b. Compute Budget And Seed The Cost Ledger` between `### 5. Build The Brief` (:76) and `### 6. Quality Gate` (:92). Substitution: no per-minute lines — `default_budget_cap_usd = manifest["budget_default_usd"]` with a comment stating why (no paid tools). Seed one $0 line item per planned tool batch (`subtitle_gen`, `audio_enhance`) so the gate presents an explicit `TOTAL ESTIMATED $0.00 of $1.00` rather than silence. C1 arming still runs (`min_workable_usd` is $0.00; the max() is inert but the canonical line stays verbatim — uniformity is the drift guard).
- `asset-director.md`: insert `### 1c. Ledger Discipline For Every Paid Call` between `### 1b. Hero Scene Sample (Mandatory)` (:28) and `### 2. Generate Per-Clip Subtitles` (:38). The many-outputs shape is pure batching: ONE $0 entry per tool-batch across all clips (`tracker.estimate("subtitle_gen", "subtitles x 12 clips", 0.0)`), never per clip — the explainer batching rule verbatim. C3 booking block retained unchanged (its failure branch is what keeps a failed batch honest).
- `compose-director.md`: Cost tracker row in `## Prerequisites` (:15-23); append `### Ledger Round-Trip For The Render` before `## Common Pitfalls` (:65). One batched $0 entry for the clip render set; `### 3. Fail Softly` (:37) interplay — a clip that fails to render reconciles its batch entry with `success=False` only if the whole batch is abandoned; otherwise book the batch `success=True` and record the failed clip in `render_report`, since $0 entries carry no money either way.

**Wrinkle.** This is the boundary case that motivated the lighter-variant question — answered by D0: same blocks, all-$0 data, one batch entry per tool.

---

## Why this design (workstream-level)

Six pipelines inherit the exact contract the six wired ones already run — same criteria strings, same block anatomy, C's corrected canonical text — so there is one ledger protocol in the repo, not two generations of it. Rates are set from each pipeline's verified paid-tool profile rather than copying 0.60 everywhere: a cap far above reachable spend weakens the guard (talking-head, clip-factory), and a cap blind to the language/deliverable multiplier under-funds approved work (localization-dub, podcast-repurpose). Alternative considered — 0.60 uniformly, matching all six wired manifests: lost because the wired six are all generative/TTS+visual pipelines where 0.60 reflects real per-minute spend; these six are mostly repurpose/local pipelines where it would triple-to-infinitely overstate the reachable ceiling. All rates are only the *default* gate cap; the user's figure always overrides (explainer :427).

## Acceptance

New file `tests/contracts/test_pipeline_ledger_rollout.py` (dynamic discovery — this is the shape Workstream G extends; coordinate names with G to avoid duplicates):

- `test_every_episode_pipeline_manifest_carries_cost_log_criteria` — iterate `pipeline_defs/*.yaml` excluding `framework-smoke.yaml`; for each, assert the compose stage's `success_criteria` contains a criterion with `every entry in a terminal state`, and at least one pre-compose stage contains `an entry for every paid tool call made in this stage`. For `character-animation.yaml` additionally assert the criterion sits on BOTH `character_design` and `assets`. Dynamic: a 13th pipeline added later fails until wired.
- `test_every_episode_pipeline_skillset_carries_the_four_ledger_markers` — for each manifest (excluding framework-smoke), resolve `required_skills` to files under `skills/`; assert across that pipeline's own directors: exactly one gate file has a heading ending `Compute Budget And Seed The Cost Ledger` or `On Approval — Arm the Tracker` AND contains C1's canonical line `math.ceil(total_estimated_usd / (1 - tracker.reserve_pct) * 100) / 100 + 0.01`; ≥1 file has a heading ending `Ledger Discipline For Every Paid Call` and contains `NEVER substitute the estimate on failure` (C3 marker); ≥1 compose file has a heading ending `Ledger Round-Trip For The Render` and contains `tracker.estimate("video_compose", "render`. (Passes for the wired six only once the panel-extended C1 lands in hybrid and avatar-spokesperson AND the D0 normalizations — including explainer's new round-trip subsection — are in; hard dependency, no allowlist.)
- `test_no_pre_fix_arming_formula_anywhere` — assert `or total_estimated_usd` appears in ZERO files under `skills/pipelines/` (extends C1's guard tree-wide, which is what protects D's six new copies). The `result.cost_usd or estimated_usd` tree-wide guard already lives in C3's `test_no_or_estimated_fallback_survives_in_ledger_blocks` — do not duplicate it (panel fix).

Behavioral (extend `tests/tools/test_cost_tracker_governance.py` — arithmetic the docs mandate, executed not grepped):

- `test_localization_dub_cap_scales_per_localized_minute` — load `budget_default_usd` and `budget_per_output_minute_usd` from `pipeline_defs/localization-dub.yaml` at test time (panel fix — no literals, so a manifest rate edit flips the test) and execute the documented math: 5-min source × 2 languages → cap `max(flat, rate × 10)`; × 1 language → the flat floor wins at today's values. Locks the language-multiplier semantics against the live manifest.
- `test_podcast_output_minutes_sum_across_deliverables` — same live-load from `pipeline_defs/podcast-repurpose.yaml`; `6 clips × 0.5 min + 12-min companion = 15 output min` → cap `max(flat, rate × 15)`. Locks the sum-over-deliverables semantics against the live manifest.
- `test_zero_estimate_plan_arms_and_reconciles_clean` — CAP-mode tracker on a tmp ledger, budget armed via C1's formula with an all-$0 three-item plan (clip-factory shape); `approve_tool` each, batch-style `estimate(0.0)` → `reserve(user_approved=True)` → `reconcile(0.0, success=True)`; assert no exception, `cost_snapshot()["total_spent_usd"] == 0.0`, every entry terminal, and `validate_artifact("cost_log", persisted)` passes — behavioral proof the full ceremony is safe on a $0 pipeline (the D0 ruling's load-bearing assumption).

## Risk

- **Behavior change at six gates**: users of these pipelines now see cap math and approval arming where none existed; localization-dub multi-language runs get larger default caps ($4.00 for 5min×2 vs flat $3.00). Mitigated: the cap is presented, never spent, and the user's named figure always overrides; guards (single-action, first-paid-use, budget) all still apply per entry.
- **Under-capping**: talking-head 0.05 and podcast 0.30 are judgment defaults; an overlay-heavy short or a music-heavy batch could exceed them. Mitigated: `budget_verdict` computation surfaces `over_budget` before the gate, and C1's `min_workable_usd` floor plus the prose rule force the conversation instead of a silent guard-trip mid-run.
- **Doc drift between the seven copies of the gate/asset blocks**: mitigated by the tree-wide drift-guard test and by using C's canonical text verbatim (the same mitigation C chose).
- **clip-factory omitting the rate** could strand a future paid clip-factory: mitigated by the manifest comment naming the re-add condition, and the dynamic manifest test will flag the paid-stage criterion the moment paid tools appear without ledger wiring.
- **Landing order**: if D lands before C, the six new pipelines would copy the buggy pre-C1/C3 text — the exact failure the finding's CRITICAL note warns about. Hard dependency, below.

## Dependencies

- **Workstream C first (hard)**: every block above is C's canonical text (C1 arming, C2 naming, C3 booking, C6 shared governance section) with substitutions; D must land after or with C, never before. This includes the panel-extended C1 (hybrid + avatar-spokesperson idea-directors): D's marker test cannot land before those two files carry the canonical line.
- **Workstream B (soft)**: recovery/corruption behavior reaches these pipelines via checkpoint-protocol's shared section (C6), which names B3's `non_terminal_entries()` — no D text changes if B's API shifts, only C6's.
- **Workstream G (coordination)**: `test_pipeline_ledger_rollout.py`'s dynamic-discovery tests are the substrate G's contract suite extends; the D0 heading normalizations exist so G needs no per-pipeline allowlists. Coordinate test names to avoid duplicates with G's coverage of the wired six.


**Open questions:** none
**Dependencies:** Workstream C (canonical ledger skill blocks) — every new pipeline block is spec'd as C's canonical C1/C2/C3/C6 text with per-pipeline substitutions; landing D before C would propagate the pre-fix buggy wording the finding explicitly warns against | Workstream B (cost_tracker runtime hardening) — soft: stranded-reservation recovery and corrupt-ledger policy reach the six new pipelines only through checkpoint-protocol's shared Cost Ledger Governance section (C6), which names B3's non_terminal_entries(); land B before or with C6 | Workstream G (contract tests) — coordination, not ordering: D's tests/contracts/test_pipeline_ledger_rollout.py dynamic-discovery tests and the D0 heading normalizations are the substrate G's suite builds on; coordinate test names to avoid duplicates


---

# Workstream E — final_review audio gates in `tools/video/video_compose.py`

Status: fix spec for confirmed findings E1 (narration gate, MINOR x2 merged) and E2 (ebur128/volumedetect full-frame decode, MINOR). Branch `feat/epic1-cost-governance`.

All line anchors are against the current branch head of `/home/solafidei/OpenMontage/tools/video/video_compose.py` unless a path is given.

## Shared principle

The branch already established the honest treatment for the subtitle burn-in path (lines 2666–2683): when nothing was inspected, record `inspected: False` + a `verdict` string reading `indeterminate — …`, and never assert a pass **or a failure**. Both fixes below extend that exact treatment to the audio gates: **a negative-only gate may only fire on a measurement that actually happened.** Three verdict paths, always recorded: *measured-present*, *measured-absent* (gate fires), *indeterminate* (visible note, never critical).

---

## E1. `narration missing` critical gate fires without a measurement (video_compose.py:2528–2537)

### Fix

**File:** `tools/video/video_compose.py`, function `_run_final_review`. Plus one additive schema edit.

**(a) One constant.** Next to `LUFS_DELIVERY_FLOOR` (line 60), add:

```python
# Digital-silence floor. Below this the mix provably carries no audible
# programme audio; between this and the -40 dB narration heuristic, volume
# alone cannot distinguish quiet narration from a bed — indeterminate.
SILENCE_FLOOR_DB = -60.0
```

Replace the literal `-60` in the `unexpected_silence` check (line 2482: `if mean_vol < -60:`) with `SILENCE_FLOOR_DB`, so the gate's absent-threshold and the "effectively silent" threshold cannot drift apart.

**(b) Persist the measurement.** Add `"mean_volume_db": None` to the `audio_spotcheck` dict initializer (lines 2447–2454). Immediately after the parse loop (after line 2479, before the `if mean_vol is not None:` block), add:

```python
audio_spotcheck["mean_volume_db"] = mean_vol  # None ⇒ not measured
```

This puts the fact-of-measurement on the artifact (visible to the reviewer skill and the board) and removes the gate's dependence on a try-block local.

**(c) Rewrite the gate** (replace lines 2525–2537 wholesale):

```python
        # Narration was promised. Volume alone cannot PROVE narration, but a
        # measured silence disproves it — so this gate may only fire on a
        # measurement that actually happened. Analysis failure or a quiet-but-
        # nonsilent mix is INDETERMINATE, mirroring the subtitle burn-in
        # treatment: never assert a verdict nothing measured.
        if edit_decisions:
            narration_expected = bool(
                ((edit_decisions.get("audio") or {}).get("narration") or {})
                .get("segments")
            )
            if narration_expected:
                mv = audio_spotcheck.get("mean_volume_db")
                if audio_spotcheck["narration_present"]:
                    audio_spotcheck["narration_verdict"] = (
                        f"measured — narration-level audio present "
                        f"(mean {mv:.1f} dB)"
                    )
                elif (technical_probe.get("valid_container")
                        and not technical_probe.get("has_audio")):
                    # ffprobe measured: no audio stream exists at all.
                    audio_spotcheck["narration_verdict"] = (
                        "measured — output has no audio stream"
                    )
                    audio_spotcheck["issues"].append(
                        "Narration expected in edit_decisions but not detected "
                        "in the output — narration missing"
                    )
                elif mv is None:
                    audio_spotcheck["narration_verdict"] = (
                        "indeterminate — audio was not measured "
                        "(volumedetect failed, timed out, or did not run)"
                    )
                    audio_spotcheck["issues"].append(
                        "Narration expected but audio analysis did not "
                        "complete — narration presence indeterminate, "
                        "not verified"
                    )
                elif mv <= SILENCE_FLOOR_DB:
                    audio_spotcheck["narration_verdict"] = (
                        f"measured — no audible programme audio "
                        f"(mean {mv:.1f} dB)"
                    )
                    audio_spotcheck["issues"].append(
                        "Narration expected in edit_decisions but not detected "
                        "in the output — narration missing"
                    )
                else:
                    audio_spotcheck["narration_verdict"] = (
                        f"indeterminate — mix level {mv:.1f} dB is too low to "
                        "distinguish narration from a bed; presence neither "
                        "proven nor disproven (transcript comparison is the "
                        "authoritative narration check)"
                    )
                    audio_spotcheck["issues"].append(
                        f"Narration expected but mean level {mv:.1f} dB cannot "
                        "confirm or refute it — narration presence "
                        "indeterminate"
                    )
```

Wording constraints (load-bearing against the critical-keyword promotion at lines 2699–2708): the two *measured-absent* messages keep the exact `— narration missing` suffix; the indeterminate messages must contain **none** of the keywords in the `critical_issues` list (`narration missing`, `programme audio too quiet`, `effectively silent`, …) — the sketches above comply. The `-40 dB` measured-present heuristic (line 2488) is **unchanged**; it was never the false-critical source — the bug was treating "not > -40" as "absent".

**(d) Schema.** In `schemas/artifacts/final_review.schema.json` under `checks.audio_spotcheck.properties` (the `checks` object is `additionalProperties: false` but the per-section objects are open, so this is documentation, not a validity fix — same as the branch's own `subtitle_check.inspected`/`verdict` additions):

```json
"mean_volume_db": {"type": ["number", "null"], "description": "volumedetect mean_volume in dB; null when not measured"},
"narration_verdict": {"type": "string", "description": "measured/indeterminate narration verdict when narration was expected"}
```

### Why this design

Mirrors the branch's own subtitle honesty pattern (`inspected` + `verdict`, lines 2666–2683) instead of inventing a new shape, and keeps the gate negative-only: it now fires exactly when absence was *measured* (no audio stream, or mean ≤ −60 dB digital silence) — the only two states volume evidence can actually disprove narration from. The alternative — a narration-band measurement (`highpass=200,lowpass=4000,volumedetect`) — lost because a music bed also carries speech-band energy, so it cannot separate "quiet narration" from "bed only" either; it adds a decode pass without adding proof, while the transcript comparison (section 6, `_compare_transcript_to_script`) is already the content-level narration check.

### Acceptance

New file `tests/tools/test_final_review_audio_gates.py` (kept out of `tests/test_final_review_honesty.py`, which workstream G owns). Follow the house pattern from `tests/tools/test_hyperframes_compose.py:822` — build a real MP4 with lavfi and drive `VideoCompose()._run_final_review(...)`. Shared helper:

```python
def _make_mp4(tmp_path, audio_args):  # audio_args e.g. "sine=frequency=440:duration=2,volume=-70dB"
    mp4 = tmp_path / "out.mp4"
    subprocess.run(["ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=#000000:s=320x240:d=2",
        "-f", "lavfi", "-i", audio_args,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(mp4)], capture_output=True, check=True, timeout=30)
    return mp4
```

`NARRATION_ED = {"version": "1.0", "render_runtime": "ffmpeg", "cuts": [...one cut...], "audio": {"narration": {"segments": [{"id": "n1"}]}}}`.

1. **`test_gate_fires_on_measured_silence`** — audio `sine=frequency=440:duration=2,volume=-75dB` (mean ≈ −78 dB, below −60). Assert: some issue contains `"narration missing"`; `review["status"] == "revise"`; `review["recommended_action"] == "re_render"`; `audio_spotcheck["narration_verdict"].startswith("measured")`. This is the behavioral gate-flip test the lexical honesty tests never had.
2. **`test_gate_indeterminate_when_analysis_fails`** — audible audio (`sine=frequency=440:duration=2`), but monkeypatch `tools.video.video_compose.subprocess.run` with a wrapper that raises `subprocess.TimeoutExpired(cmd, 60)` when `"volumedetect"` is in the argv and delegates to the real `subprocess.run` otherwise. Assert: no issue contains `"narration missing"`; `narration_verdict` startswith `"indeterminate"`; `audio_spotcheck["mean_volume_db"] is None`; `review["status"] != "revise"` (the transient probe failure no longer prescribes a re-render).
3. **`test_gate_indeterminate_on_quiet_mix`** — audio `sine=frequency=440:duration=2,volume=-45dB` (mean between −60 and −40). Assert: no issue contains `"narration missing"`; `narration_verdict` startswith `"indeterminate"`. Do **not** assert overall status — the (intended) LUFS floor gate may independently flag a ~−45 LUFS master.
4. **`test_gate_fires_when_no_audio_stream`** — build the MP4 with no `-i sine` input (video only). Assert: issue contains `"narration missing"`; `narration_verdict == "measured — output has no audio stream"`.
5. **`test_verdict_present_on_audible_mix`** — full-level sine, narration expected. Assert `audio_spotcheck["narration_present"] is True` and `narration_verdict.startswith("measured")`, and no narration issue.

### Risk

- **Detection regression for the true-positive "bed only, narration dropped" mix** sitting between −60 and −40 dB: previously a (lucky) critical, now indeterminate. Accepted deliberately — the old gate could not tell that case from quiet valid narration (same measurement), and `_compare_transcript_to_script` is the check built for content-level narration loss. The indeterminate verdict text names that check so the reviewer skill escalates instead of ignoring it, and the issue string still lands in `issues_found` (visible, non-silent).
- **Workstream G interaction**: `tests/test_final_review_honesty.py::test_negative_only_gates_flip_status` asserts `"— narration missing"` appears in source — preserved verbatim by the sketch. G's behavioral rewrite must use a *measured-absent* fixture (silent or audio-less MP4, per tests 1/4 above), not an analysis-failure fixture, or its gate-fires assertion will (correctly) fail. See Dependencies.
- Schema edit is additive under an open per-section object; no existing artifact can become invalid.

---

## E2. ebur128 (and volumedetect) decode the full video stream (video_compose.py:2503, 2458)

### Fix

**File:** `tools/video/video_compose.py`, function `_run_final_review`. Three edits.

**(a) Audio-only volumedetect** (line 2458–2461) — in scope because this branch made its result load-bearing for the critical gate:

```python
                cmd = [
                    "ffmpeg", "-i", str(output_path),
                    "-vn", "-af", "volumedetect", "-f", "null", "-",
                ]
```

**(b) Audio-only ebur128 in its own try/except.** Move the ebur128 block (current lines 2500–2521) *out* of the volumedetect try into a sibling `try` directly after the existing `except` at 2522–2523, still inside the `if technical_probe.get("has_audio") and duration > 0:` guard, and add `-vn`:

```python
            try:
                # mean_volume is an RMS average a loud music bed satisfies on
                # its own. Integrated LUFS is the programme-level figure
                # delivery actually cares about. Negative-only gate.
                lufs_proc = subprocess.run(
                    ["ffmpeg", "-i", str(output_path), "-vn", "-af", "ebur128",
                     "-f", "null", "-"],
                    capture_output=True, text=True, timeout=120,
                )
                # ... existing I:/LUFS parse loop and floor gate, unchanged ...
            except Exception as e:
                audio_spotcheck["issues"].append(f"Loudness analysis error: {e}")
```

Two effects: a volumedetect failure no longer silently skips the LUFS probe (and vice versa), and `-vn` makes both passes audio-only (~10–50x faster), putting the 60s/120s timeouts far out of reach on long episodes. Keep the timeouts as-is — they are now genuine anomaly guards.

**(c) Make the skipped gate visible (indeterminate, per E1's principle).** After the ebur128 try/except, still inside the has-audio guard:

```python
            if "integrated_lufs" not in audio_spotcheck:
                audio_spotcheck["loudness_verdict"] = (
                    "indeterminate — integrated loudness not measured; "
                    "LUFS floor gate did not run"
                )
                audio_spotcheck["issues"].append(
                    "Integrated loudness could not be measured — LUFS floor "
                    "gate skipped, loudness indeterminate"
                )
            else:
                audio_spotcheck["loudness_verdict"] = (
                    f"measured — {audio_spotcheck['integrated_lufs']:.1f} LUFS"
                )
```

The indeterminate message must not contain the phrase `programme audio too quiet` (critical keyword) — sketch complies. Add `"loudness_verdict": {"type": "string"}` to `checks.audio_spotcheck.properties` in `schemas/artifacts/final_review.schema.json` alongside E1(d).

### Why this design

`-vn` is the minimal, standard ffmpeg idiom for skipping video decode on a null-muxed analysis pass (`-map a` lost: it hard-fails on an audio-less file, where `-vn` degrades gracefully, and the has-audio guard already screens the common case). Splitting the try blocks costs four lines and removes a real coupled-failure path the finding's scenario walks through; raising the timeout instead lost because it treats the symptom while still paying a full second decode of every finished render.

### Acceptance

Same file `tests/tools/test_final_review_audio_gates.py`:

1. **`test_audio_probes_run_audio_only`** — monkeypatch `tools.video.video_compose.subprocess.run` with a recorder that appends each argv then delegates to the real `subprocess.run`; run `_run_final_review` on an audible MP4. Assert: for every recorded ffmpeg argv containing `"volumedetect"` or `"ebur128"`, `"-vn"` is in that argv. Behavioral, not lexical — it inspects the command the code actually executed.
2. **`test_lufs_timeout_is_indeterminate_not_silent`** — wrapper raises `subprocess.TimeoutExpired(cmd, 120)` only when `"ebur128"` is in argv, delegates otherwise; audible MP4, narration expected. Assert: `"integrated_lufs" not in audio_spotcheck`; `audio_spotcheck["loudness_verdict"].startswith("indeterminate")`; some issue contains `"loudness indeterminate"`; `review["status"] != "revise"`; **and** `audio_spotcheck["mean_volume_db"] is not None` with `narration_verdict.startswith("measured")` — proving the split try preserved the volumedetect result (the E1 gate stays measured even when the LUFS pass dies).
3. **`test_lufs_gate_still_fires_when_measured_low`** — MP4 with `volume=-50dB` audio (integrated ≈ −53 LUFS < −40 floor). Assert: some issue contains `"programme audio too quiet"`; `review["status"] == "revise"`; `loudness_verdict.startswith("measured")`. Confirms `-vn` and the restructure did not blunt the gate E2's pass exists to feed.

### Risk

- `-vn` changes probe behavior only if a stream-mapping edge case exists (e.g. audio in an attachment stream); none of the render paths in this file produce such a container, and test 3 pins the measured-low path end-to-end.
- The try-split changes exception attribution: a volumedetect failure now yields `Audio analysis error: …` *and* (via E2c) a loudness-indeterminate note if ebur128 also fails — two issues where there was one. Both are non-critical; `issues_found` is an open list; no consumer counts issue entries (verified: only keyword matching at 2699–2708 consumes them).
- New tests spawn real ffmpeg — same as the existing `_run_final_review` tests in `tests/tools/test_hyperframes_compose.py`, so no new CI requirement.

---

## Out of scope (other workstreams)

- Rewriting `tests/test_final_review_honesty.py`'s lexical guards into behavioral ones (workstream G). E's new `tests/tools/test_final_review_audio_gates.py` provides the behavioral gate-flip coverage G's findings say is missing; G should build on it rather than duplicate fixtures.


**Open questions:** none
**Dependencies:** Workstream G (honesty-test hardening): G's behavioral rewrite of test_negative_only_gates_flip_status must arrange a MEASURED-absent fixture (silent-audio or audio-less MP4), not an analysis-failure or quiet-mix fixture — after E1 those paths are indeterminate and the gate correctly does not fire. G's lexical assertion on the literal '— narration missing' substring stays satisfied (E1 keeps the message verbatim), but G should land after E (or coordinate on the fixture helper in tests/tools/test_final_review_audio_gates.py) to avoid asserting the old always-False-fires behavior.


---

# Fix Spec — Workstream F: documentation coherence

Scope: doc-only edits, but binding — in this repo instruction Markdown is runtime code.
All line numbers verified against the current branch working tree (`feat/epic1-cost-governance`).

Shared ground truth (verified in source):

- Canonical log: `projects/<id>/decision_log.json` (`lib/checkpoint.py:_decision_log_path`, :401), written only by `_merge_decision_log()` (def :405) from the `decision_log` artifact passed to `write_checkpoint()` (def :465, merge call :573-574).
- `schemas/artifacts/decision_log.schema.json`: entries require `decision_id/stage/category/subject/options_considered/selected/reason`, `additionalProperties: false`, category enum includes `visual_accuracy_check`. No evidence field.
- Checkpoint schema (`schemas/checkpoints/checkpoint.schema.json`): `metadata` is a free-form `{"type": "object"}` — a legal home for non-decision judgment residue.
- `_merge_decision_log` **silently skips** any entry whose `decision_id` already exists (:426-429) — a reused id drops the ruling.
- Backlot reads `artifacts/decision_log.json` first and falls back to project-root `decision_log.json` (`backlot/state.py:242-258`) — a hand-written artifacts copy *shadows* the canonical log on the board.
- AGENT_GUIDE.md: "Re-log Changed Decisions (Binding)" (:117-121, append-only, identity = (category, subject) pair) and "Compact at closed gates" (:596-613, "the checkpoint holds pipeline state and `decision_log.json` holds judgment state. Log the rulings before compacting").
- `config.yaml` `budget.total_usd: 15.00`; `lib/config_model.py:37` `total_usd: float = 15.0`.

---

## F1. [MAJOR] `docs/intent/context-cost-spec.md:71` — section 2 instructs hand-appending a non-schema note to `artifacts/decision_log.json`, the exact fork the branch's self-heal outlaws

### Fix

Rewrite section 2 (lines 64–84, `### 2. The judgment note` through the `Rules:` paragraph). Keep the opening paragraph (66–69: why judgment state needs a durable home) verbatim. Replace everything from line 71 ("Before each fire, append to…") through line 84 with:

> Judgment state goes through the **supported decision-log path**: schema-valid entries in
> the `decision_log` artifact of the gate checkpoint, which `write_checkpoint()` merges
> into the canonical `projects/<id>/decision_log.json` via `_merge_decision_log()`
> ([`lib/checkpoint.py:405`](../../lib/checkpoint.py#L405)). **Never hand-write
> `projects/<id>/artifacts/decision_log.json`** — nothing in the codebase writes that
> file, Backlot prefers it over the canonical log when both exist
> ([`backlot/state.py`](../../backlot/state.py), artifact-first fallback), and
> hand-writing it is exactly the fork Rollout step 2 had to backfill. The self-heal in
> `_merge_decision_log()` absorbs residual forks, but it is a repair path, not a write path.
>
> One entry per verdict, valid against
> [`schemas/artifacts/decision_log.schema.json`](../../schemas/artifacts/decision_log.schema.json):
>
> ```json
> { "version": "1.0", "project_id": "<id>", "decisions": [
>   { "decision_id": "d-041", "stage": "render",
>     "category": "visual_accuracy_check",
>     "subject": "scene 4 take selection",
>     "options_considered": [
>       { "option_id": "take_3", "label": "take 3", "score": 0.2,
>         "reason": "best pacing",
>         "rejected_because": "mouth drift @0:04 — evidence: scratchpad/mouth/s4_sheet.png" },
>       { "option_id": "take_5", "label": "take 5", "score": 0.9,
>         "reason": "clean lip sync at the approved pacing" } ],
>     "selected": "take_5",
>     "reason": "take 3 vetoed for mouth drift; take 5 clean at the same pacing" } ] }
> ```
>
> carried on the gate write itself:
>
> ```python
> write_checkpoint(pipeline_dir, project_id, stage, status,
>     artifacts={..., "decision_log": judgment_log},   # the object above
>     metadata={"open": ["scene 2 audio sync unverified"],
>               "measured": {"loudness_lufs": -16.2, "fps": 24}})
> ```
>
> Mapping the note's old fields:
>
> - **rejections / rulings** → one decision each. QA verdicts use
>   `category: "visual_accuracy_check"`. A ruling that overturns a logged choice
>   ("warm grade vetoed") reuses the superseded decision's **(category, subject)** pair —
>   AGENT_GUIDE → "Re-log Changed Decisions". Evidence is a path inside
>   `reason`/`rejected_because`: the schema is `additionalProperties: false`, so there is
>   no evidence field to invent.
> - **open / measured** → the checkpoint's free-form `metadata` object — pipeline state,
>   not judgment. Values already durable in a stage artifact (`render_report`, `review`)
>   are not duplicated.
>
> `decision_id` must be **new**: read `projects/<id>/decision_log.json` and take the next
> `d-NNN`. The merge silently drops an entry whose id already exists — a reused id loses
> the ruling.
>
> A ruling that lands *after* the gate write (mid-`awaiting_human` conversation) is made
> durable the same way: re-write the same stage checkpoint carrying the extra entries —
> the merge appends only new ids, so re-writes are additive, never a rewrite.
>
> Rules: verdicts and their **reasons**, never a narrative retelling. Evidence by path,
> never by re-embedding the image. Append, never rewrite — supersede with a new entry on
> the same (category, subject).

This drops the line-73 citation of `scripts/backlot_screenshot_stage.py` — that script is a screenshot-staging fixture that itself hand-writes the artifacts copy (`:198`); it was evidence *for the wrong path*.

Companion edit, Rollout step 2 (line 140): replace "**The writer is still unfixed — this will recur.**" with:

> **The writer was section 2 of this spec** — it instructed the hand-append; now corrected
> to route through `write_checkpoint()`. `_merge_decision_log()` additionally absorbs any
> residual fork as a repair path.

### Why this design

Gate-write-carried entries are the only path that satisfies all three authorities at once: `_merge_decision_log` (merge-by-`decision_id` into the root log), the decision_log schema (entries validate), and AGENT_GUIDE's "Compact at closed gates" ("log the rulings before compacting" — the rulings ride the very checkpoint whose write *is* the compaction trigger). Alternative — keep a free-form side note but move it to a new schema'd artifact — lost: it invents a second judgment store when the audit trail, the board's Decisions rail, and the reviewer all already read `decision_log`, and the `open`/`measured` residue fits checkpoint `metadata` with zero new schema.

### Acceptance

- `tests/test_decision_log_fork.py::test_gate_ruling_flows_through_write_checkpoint` — **behavioral**, harness copied from `tests/lib/test_checkpoint_cost_snapshot.py:48-66`: `init_project` on `tmp_path` (framework-smoke), `write_checkpoint(..., "research", "awaiting_human", {"research_brief": sample_artifact(...), "decision_log": <the d-041 object from the doc, as a literal>}, metadata={"open": [...], "measured": {...}})`. Assert: `projects/run/decision_log.json` contains `d-041`; `projects/run/artifacts/decision_log.json` does **not exist**; `validate_artifact("decision_log", <root log contents>)` passes. Then re-write the same stage/status with the log extended by `d-042` → assert both ids present exactly once (the additive-re-write claim).
- `tests/contracts/test_agent_instruction_integrity.py::test_context_cost_spec_judgment_example_is_schema_valid` — extract the first ```json fence between the `### 2.` and `### 3.` headings of `docs/intent/context-cost-spec.md`, `json.loads` it, run `validate_artifact("decision_log", parsed)`. The doc's example is thereby executable-verified against the live schema, not eyeballed.
- Same file, `test_context_cost_spec_never_instructs_the_artifacts_side_file` — assert the string `` append to `projects/<id>/artifacts/decision_log.json` `` appears nowhere in the spec, and `Never hand-write` + `write_checkpoint()` appear in section 2.

### Risk

Agents that already internalized the old note shape lose the free-form `open`/`measured` bucket in the decision log — mitigated by giving both an explicit schema-legal home (`metadata`) in the same section. The example's `stage: "render"` is illustrative; the behavioral test uses a real framework-smoke stage so it exercises the true write path. Workstream A is hardening `_merge_decision_log`'s orphan absorption — F1's text references the self-heal only generically ("repair path, not a write path"), so A's changes cannot invalidate it.

---

## F2. [MINOR/critic] `context-cost-spec.md:3` + rollout step 3 (:141-142) — still "proposed, awaiting go-ahead" / "HELD" while this branch ships the rule

### Fix

Line 3: replace `Status: **proposed, awaiting go-ahead**.` with:

> Status: **shipped** — rollout steps 1–3 landed; step 4 (measurement) open.

(The `Intent confirmed in context-cost.md` sentence on lines 3–4 stays.)

Rollout step 3 (lines 141–142): replace the whole item with:

> 3. **DONE** — landed as `AGENT_GUIDE.md` → "Compact at closed gates" (under Human
>    Checkpoint Protocol), which cites this spec as its authority.

Cite the AGENT_GUIDE **section name, not a line number** — that file churns constantly. Leave the closing paragraph (146–147) and step 4 untouched: step 4 is genuinely open and the paragraph reads correctly as history.

### Why this design

Two authoritative-in-conflict instruction files is the defect; the smallest edit that makes them agree is flipping the two stale markers to point at the section that now exists. Rewriting the rollout narrative would erase useful history (the HELD decision and its later reversal are audit trail).

### Acceptance

`tests/contracts/test_agent_instruction_integrity.py::test_context_cost_spec_status_agrees_with_agent_guide` — assert `docs/intent/context-cost-spec.md` contains neither `awaiting go-ahead` nor `**HELD**`; assert it contains `Compact at closed gates`; assert `AGENT_GUIDE.md` contains the heading `### Compact at closed gates` (both sides of the cross-reference pinned, so deleting either section breaks the test).

### Risk

Near zero — status-text only. The scenario the finding warns about (a future session "finishing the rollout" by duplicating or removing the guide rule) is closed by the DONE marker naming the exact section.

---

## F3. [MINOR] `context-cost-spec.md:58` — stale `lib/checkpoint.py#L435` anchor for `write_checkpoint`

### Fix

Line 58: `[`lib/checkpoint.py:435`](../../lib/checkpoint.py#L435)` → `lib/checkpoint.py:465` / `#L465` — `def write_checkpoint(` sits at :465 on the current branch tree. **Final number is set after workstream A lands** (A refactors `lib/checkpoint.py` again; every insertion above :465 shifts it) — see Dependencies.

Full anchor sweep of the spec, current status:

| spec line | anchor | status |
|---|---|---|
| 4 | `context-cost.md` | correct (file exists) |
| 58 | `lib/checkpoint.py#L435` | **stale** → :465 today; finalize after A |
| 73 | `scripts/backlot_screenshot_stage.py` | **removed by F1's rewrite** (it justified the wrong path — the script hand-writes the artifacts copy at :198) |
| 130 | `lib/checkpoint.py#L405` (`_merge_decision_log`) | correct today (def at :405); re-verify after A |
| 132 | `schemas/artifacts/decision_log.schema.json` | correct (file-level) |

F1's rewritten section 2 re-introduces the `#L405` anchor — same re-verification applies.

Add a drift guard so these two anchors can never rot silently again — `tests/contracts/test_agent_instruction_integrity.py::test_context_cost_spec_checkpoint_anchors_are_fresh`:

```python
def test_context_cost_spec_checkpoint_anchors_are_fresh() -> None:
    """Anchors must land INSIDE the symbol they name — span check, not exact line.

    Exact-line pinning would fail CI on every future insertion above these
    defs in the repo's most-edited core module; the span check catches real
    rot (an anchor pointing into some other function) without that friction.
    (Panel ruling.)"""
    src = _read("lib/checkpoint.py").splitlines()
    spec = _read("docs/intent/context-cost-spec.md")
    for symbol in ("write_checkpoint", "_merge_decision_log"):
        start, end = _def_span(src, symbol)  # def line .. last line of the function
        anchors = [int(n) for n in re.findall(
            rf"{symbol}[^\n]*?lib/checkpoint\.py[:#L]+(\d+)|"
            rf"lib/checkpoint\.py[:#L]+(\d+)[^\n]*?{symbol}", spec,
        ) for n in n if n]
        assert anchors, f"context-cost-spec.md no longer anchors {symbol}"
        for n in anchors:
            assert start <= n <= end, (
                f"context-cost-spec.md anchors {symbol} at :{n}, outside its "
                f"span :{start}-:{end} — update the anchor"
            )
```

(`_def_span` walks from `def {symbol}(` to the next top-level `def`; the regex scopes
each anchor to the line naming its symbol so the two are checked independently.) The
guard computes the true span at test time: green across unrelated insertions, red only
when an anchor actually points outside its symbol.

### Why this design

The finding is precisely "line anchors go stale silently"; a computed-at-test-time guard deletes the failure class, where a one-time number bump only resets the clock. Alternative — drop line anchors for symbol-only links — lost: it gives up jump-to-line for the two most load-bearing definitions in the repo's core module, against house style. Span-checking rather than exact-line pinning is the panel-ruled middle: exact-line coupling would fail an unrelated docs test on every future insertion above :405 — friction disproportionate to two links.

### Acceptance

The drift-guard test above (fails on the current tree against :435, passes after the edit), plus a one-time manual sweep record: the table above is the sweep; only line 58 is stale today.

### Risk

An anchor can drift within a long function's span without detection — acceptable: it still lands the reader inside the right symbol. Landing before workstream A would mean re-verifying twice; the dependency ordering below avoids that.

---

## F4. [MINOR/critic] `docs/ARCHITECTURE.md:312`+`:356` — still documents the $10.00 default budget; config is 15.00

### Fix

Line 313, before:

```
- **Total budget** (default: $10.00)
```

after (wording matches workstream B's B4 mechanism — constructor default `None` → resolved from `config.yaml`):

```
- **Total budget** (default: $15.00 — `budget.total_usd` in `config.yaml`, the single
  source; `CostTracker` resolves it from config when constructed without an explicit budget)
```

Line 356 (config.yaml excerpt): `  total_usd: 10.00` → `  total_usd: 15.00`.

Sweep result: these are the only two stale `$10`/`10.00` budget references in `docs/`, `AGENT_GUIDE.md`, and `README.md` (verified by grep).

### Why this design

B4 makes config the single source of the default; the doc should describe the *mechanism* ("from `config.yaml`") plus the current value, so the next bump needs only the number touched — and the acceptance test below makes even that impossible to forget. Hard-coding only "$15.00" with no source attribution re-creates today's divergence class in prose.

### Acceptance

`tests/contracts/test_agent_instruction_integrity.py::test_architecture_doc_budget_matches_config` — no literal `15.0` in the test (same philosophy as B4's `test_default_budget_resolves_from_config`):

```python
def test_architecture_doc_budget_matches_config() -> None:
    from lib.config_model import OpenMontageConfig
    total = OpenMontageConfig.load().budget.total_usd
    doc = _read("docs/ARCHITECTURE.md")
    assert f"default: ${total:.2f}" in doc      # Controls bullet, line ~313
    assert f"total_usd: {total:.2f}" in doc     # config.yaml excerpt, line ~356
```

Fails on the current tree ($10.00 vs 15.0), passes after the edit, and fails again on any future bump until the doc follows — the drift guard the critic's scenario needs.

### Risk

If F4's text lands before B4's code, the "resolves it from config" clause is ahead of reality (bare `CostTracker()` still hard-codes 10.0 until B4). Mitigated by the dependency ordering below; even mis-ordered, the new text is strictly less wrong than "$10.00".

---

## Dependencies

- **Workstream A (`lib/checkpoint.py` refactor) → F3**: A shifts `write_checkpoint`/`_merge_decision_log` def lines. Land F3's anchor numbers and drift-guard test **after A**, with numbers read off A's final tree (the test's assertion message hands over the fresh numbers). F1 is *not* blocked on A — its `#L405` anchor is covered by the same post-A re-verify.
- **Workstream B (B4, `tools/cost_tracker.py` constructor default) → F4**: F4's "resolves it from config" sentence describes B4's `None → OpenMontageConfig.load().budget.total_usd` mechanism. Land F4 with or after B4.
- **Workstream C**: no file overlap (C touches `skills/`, F touches `docs/` + the spec). F1's decision-log guidance and C6's "log the ruling as a `decision_log` entry" recovery step both route through `write_checkpoint` — consistent by construction; no ordering constraint.
- All four F acceptance tests extend `tests/contracts/test_agent_instruction_integrity.py` (plus one behavioral test in `tests/test_decision_log_fork.py`), the same files workstreams C and G extend — coordinate test names to avoid duplicates.

**Open questions:** none.


**Open questions:** none
**Dependencies:** Workstream A (lib/checkpoint.py refactor): F3's anchor line numbers and drift-guard test must be finalized after A lands — A shifts the def lines of write_checkpoint (:465 today) and _merge_decision_log (:405 today). | Workstream B (B4 constructor-default fix): F4's ARCHITECTURE.md wording describes B4's resolve-from-config mechanism; land F4 with or after B4 so the doc sentence is true.


---

# Fix spec — Workstream G: test hardening

Status: **spec for confirmed test-quality findings** on `feat/epic1-cost-governance`.
Scope: tests only — no production code. Every item below is a test that goes RED under
the revert its finding describes and stays green on the fixed branch. All source
anchors verified against the current branch working tree. Sibling-spec alignment:
B (`tests/tools/test_cost_tracker_persistence.py`, new), C (extends
`test_cost_tracker_governance.py` + `test_agent_instruction_integrity.py`),
E (`tests/tools/test_final_review_audio_gates.py`, new). Names below collide with none
of theirs.

---

## G1. No test that `user_approved=True` does NOT waive the budget cap or the first-paid-use guard (`tests/tools/test_cost_tracker_governance.py:148`, MAJOR)

`reserve()`'s contract (tools/cost_tracker.py:152-157) has three clauses; only the
waiver clause is tested. The two non-waiver clauses are what every skill on this branch
leans on (`user_approved=True` on essentially every reserve), so a refactor that makes
either check symmetric with the threshold check (`... and not user_approved`) turns cap
mode off repo-wide with a green suite.

### Fix

`tests/tools/test_cost_tracker_governance.py`, two new tests, same unittest +
`tempfile` + `validate_artifact` pattern as the file's existing tests. Each isolates
exactly one guard by disarming the other two.

- `test_user_approved_does_not_waive_budget_cap` — tracker:
  `budget_total_usd=1.0, reserve_pct=0.0, single_action_approval_usd=99.0,
  require_approval_for_new_paid_tool=False, mode=BudgetMode.CAP, cost_log_path=tmp`.
  `entry_id = estimate("paid_video", "generate", 2.0)`; then
  `assertRaises(BudgetExceededError): reserve(entry_id, user_approved=True)`.
  Afterwards assert the entry is still `"estimated"` with `reserved_usd == 0.0` both in
  memory and in the persisted file (the raise at tools/cost_tracker.py:185 happens
  before the status mutation at :190 — pin that ordering), and
  `validate_artifact("cost_log", persisted)` passes. Add `BudgetExceededError` to the
  file's imports.
- `test_user_approved_does_not_waive_first_paid_use_guard` — tracker:
  `budget_total_usd=10.0, reserve_pct=0.0, single_action_approval_usd=0.50,
  require_approval_for_new_paid_tool=True, mode=BudgetMode.WARN, cost_log_path=tmp`.
  Tool NOT approved. `entry_id = estimate("elevenlabs_tts", "narration", 0.18)` —
  under the $0.50 threshold, so the threshold clause cannot be the actor.
  `assertRaises(ApprovalRequiredError): reserve(entry_id, user_approved=True)`; assert
  the message contains `"First paid use"` (distinguishes it from the threshold error's
  `"exceeds single-action threshold"`). Then `approve_tool("elevenlabs_tts")` and the
  same `reserve(entry_id, user_approved=True)` succeeds — proving the guard, and only
  the guard, was the blocker.

### Why this design

One test per clause, each with the other clauses provably disarmed — the finding's
failure scenario is a *single* clause silently gaining `and not user_approved`, so a
combined test that trips any-of-three would not localize the revert. B's
`test_cap_mode_reserve_sees_other_instances_spend` overlaps the budget half but only
via B2's two-instance merge machinery; these run on one instance and stay valid even
if B's merge design shifts.

### Acceptance

Both tests green on the current branch (they pin existing behavior). Red check: edit
`reserve()`'s budget check to `if estimated > self.usable_budget_usd and not
user_approved` → test 1 fails; edit the guard at :171 to
`if ... and not user_approved` → test 2 fails. Perform both red checks once locally
before landing.

### Risk

None to production. If B4 lands (`budget_total_usd: Optional`), both tests pass
explicit budgets, so no interaction.

---

## G2. All three final_review honesty guards are lexical and never execute `_run_final_review` (`tests/test_final_review_honesty.py:26` + `:15`, MINOR ×2)

**Lands after workstream E** — expected verdicts below are E1/E2's redesigned shapes
(measured / indeterminate), and the fixture helper is E's.

### Fix

Rewrite `tests/test_final_review_honesty.py`: delete the AST walk and both
source-substring bodies (`test_burn_in_does_not_assert_presence`,
`test_negative_only_gates_flip_status`); keep the module docstring (updated: "guards
are behavioral — they execute _run_final_review on real renders") and keep
`test_loudness_floor_is_conservative` unchanged (it imports and checks the live
constant; not lexical in the vulnerable sense). Import the fixture builder from E's
file — cross-importing test modules is the house pattern
(`from tests.contracts.test_phase0_contracts import sample_artifact`):

```python
from tests.tools.test_final_review_audio_gates import _make_mp4
```

Two behavioral replacements:

- `test_burn_in_yields_indeterminate_never_a_fabricated_pass(tmp_path)` — the
  respelled-revert killer. Arrange: `mp4 = _make_mp4(tmp_path, "sine=frequency=440:duration=2")`
  (no subtitle stream — mux adds none); a real file `subs = tmp_path / "subs.srt"`
  with one cue. `edit_decisions = {"version": "1.0", "renderer_family":
  "animation-first", "render_runtime": "ffmpeg", "cuts": [{"id": "c1", "source": "x",
  "in_seconds": 0, "out_seconds": 2}], "subtitles": {"enabled": True, "source":
  str(subs)}}` (shape copied from
  `tests/tools/test_hyperframes_compose.py::test_run_final_review_includes_transcript_comparison_section`).
  Act: `review = VideoCompose()._run_final_review(mp4, edit_decisions=edit_decisions)`.
  Assert on `sc = review["checks"]["subtitle_check"]`:
  `sc["subtitles_expected"] is True`; `sc["subtitles_present"] is False`;
  `sc["inspected"] is False`; `sc["verdict"] == "indeterminate — burned-in, not inspected"`;
  `sc.get("coverage_ratio") != 1.0`; and no subtitle issue was raised
  (`not sc["issues"]`) — the burn-in path is indeterminate, not a failure. Any
  respelling of the old fabrication (`.update({...})`, a helper, re-whitespaced
  assignments) flips `subtitles_present`/`coverage_ratio` and fails these asserts,
  because the assertions read the executed output, not the source text.
- `test_measured_silence_flips_status_through_both_critical_gates(tmp_path)` — the
  behavioral status-flip test the lexical one pretended to be. One render exercises
  both new critical keywords: `mp4 = _make_mp4(tmp_path,
  "sine=frequency=440:duration=2,volume=-75dB")` (mean_volume ≈ −78 dB: below the
  −60 silence floor AND integrated LUFS far below the −40 `LUFS_DELIVERY_FLOOR`);
  `edit_decisions` = the dict above minus `subtitles`, plus
  `"audio": {"narration": {"segments": [{"id": "n1"}]}}` (the exact nesting the gate
  reads at video_compose.py:2529-2531 — this is the assertion the finding wanted: if a
  refactor renames the nesting, `narration_expected` goes False and this test's
  gate-fire assert fails). Assert: `review["status"] == "revise"`;
  `review["recommended_action"] == "re_render"`;
  `any("narration missing" in i for i in review["issues_found"])`;
  `any("programme audio too quiet" in i for i in review["issues_found"])`;
  `review["checks"]["audio_spotcheck"]["narration_verdict"].startswith("measured")`
  (E1's measured-absent verdict — this fixture is deliberately a *measured* silence,
  per E's dependency note; an analysis-failure fixture would correctly NOT fire the
  gate after E1).

### Why this design

Behavioral asserts on `_run_final_review`'s returned dict are revert-proof by
construction — they hold under any spelling of the code. The per-verdict fine-grained
coverage (indeterminate on probe failure, quiet mix, no-audio-stream, `-vn` argv)
already lives in E's `tests/tools/test_final_review_audio_gates.py`; this file keeps
exactly the two honesty invariants its docstring declares (no fabricated subtitle
pass; critical gates actually flip status) in one render each, rather than duplicating
E's matrix. Alternative — keeping the lexical asserts alongside — lost: they are the
false-confidence the finding is about, and E's
`test_negative_only_gates_flip_status` source-string dependency (`"— narration
missing"` present) is preserved *by E's code sketch*, not needed here.

### Acceptance

Red checks: (1) apply the finding's respelled revert
(`subtitle_check.update({"subtitles_present": True, "coverage_ratio": 1.0})` on the
burn-in branch) → burn-in test fails; (2) delete `"narration missing"` from the
critical-keyword list at video_compose.py:2705 → status-flip test fails on
`status == "revise"`; (3) rename the `audio.narration.segments` nesting in the gate →
status-flip test fails. Both tests require ffmpeg — same standing requirement as
`test_hyperframes_compose.py`.

### Risk

Two more real ffmpeg renders (~2s clips) in the suite — trivial next to the existing
render tests. Cross-module import couples this file to E's; if E's helper moves, one
import line follows it. Landing order enforced by the shared PR train (see
Dependencies).

---

## G3. `get_latest_checkpoint`'s copy of the legacy tolerance is untested (`tests/lib/test_checkpoint_cost_snapshot.py:67`, MINOR)

### Fix

`tests/lib/test_checkpoint_cost_snapshot.py`. Add `get_latest_checkpoint` to the
imports. Two new tests mirroring the existing `read_checkpoint` pair, written against
the **public entry point** so they survive (and pin) A1's helper extraction:

- `test_get_latest_checkpoint_tolerates_legacy_cost_snapshot(tmp_path)` — arrange
  exactly as `test_read_checkpoint_tolerates_legacy_cost_snapshot` (init
  framework-smoke, write research, rewrite the file on disk with
  `cost_snapshot={"spent_usd": 0.28, "approved_budget_usd": 2.0}`). Act:
  `checkpoint = get_latest_checkpoint(tmp_path, "run")`. Assert it is not None, its
  `stage == "research"`, and `checkpoint["cost_snapshot"]` equals the legacy dict —
  the resume/inspect entry point returns the file, does not raise.
- `test_get_latest_checkpoint_still_raises_on_non_cost_snapshot_corruption(tmp_path)`
  — same arrange, but parametrized over the two corruption shapes from G7 (see G7's
  parametrization — one injects `data["rogue_top_level_key"] = "smuggled"`
  [`field=None` branch], the other `data["human_approved"] = "yes"`
  [`field=="human_approved"` branch]); assert
  `pytest.raises(CheckpointValidationError)`.

### Why this design

The finding is drift between copies; A1 collapses the copies into
`_validate_tolerating_legacy_cost_snapshot`, and A's own risk note hands G exactly
this: "the helper makes a single tolerance test sufficient per entry point." Testing
the public function (not the helper) means these tests are meaningful both before A
lands (they pin the current duplicated hunk at lib/checkpoint.py:660-673) and after
(they pin the call site that a dedup refactor could drop). Alternative — unit-testing
A's helper directly — lost: the failure mode is a *call site* reverting to bare
`validate_checkpoint`, which a helper unit test cannot see.

### Acceptance

Both green today (the branch already carries the get_latest tolerance) and after A1.
Red check: replace `get_latest_checkpoint`'s tolerance call with bare
`validate_checkpoint(checkpoint)` → tolerance test fails, scoping test still passes.

### Risk

None. Independent of A's landing order.

---

## G4. Reserve-flag and quantity-pricing contract guards cover only explainer / 3 pipelines (`tests/contracts/test_agent_instruction_integrity.py:48`, MINOR)

### Fix

`tests/contracts/test_agent_instruction_integrity.py`. Replace both narrow tests with
dynamically-discovered sweeps (plain-loop style, matching the file; no pytest
parametrize needed — the file uses bare asserts in loops with f-string messages naming
the offending file). Add one module-level helper:

```python
def _director_files(pattern: str, containing: str) -> list[Path]:
    """Every skills/pipelines/*/<pattern> whose text carries `containing`.

    Discovery is dynamic so a pipeline wired later (the Epic-1 rollout of
    screen-demo, talking-head, podcast-repurpose, character-animation,
    localization-dub, clip-factory) is swept automatically — wiring a
    director and dropping the contract lines must fail here with no test
    edit."""
    root = REPO_ROOT / "skills" / "pipelines"
    return sorted(
        p for p in root.glob(f"*/{pattern}")
        if containing in p.read_text(encoding="utf-8")
    )
```

- Replace `test_paid_explainer_reservations_carry_the_gate_approval` with
  `test_every_ledger_wired_spending_director_reserves_with_gate_approval`:
  discovery = `_director_files("asset-director.md", "CostTracker.for_project") +
  _director_files("compose-director.md", "CostTracker.for_project")` (verified: this
  matches exactly the 12 wired files today — proposal-directors mention
  `tracker.reserve(...)` only in prose and never open a tracker with `for_project` in
  the reserve sense... they do reference `CostTracker.for_project`, so the glob is
  scoped to asset/compose director filenames, which excludes them by name). For each
  file: `assert "tracker.reserve(entry_id, user_approved=True)" in text`, and
  per-occurrence (panel fix — a whitespace/suffix-anchored negative assert is evadable
  by a trailing comment, the same respelled-revert class G2 closes):
  `for call in re.findall(r"tracker\.reserve\([^)]*\)", text): assert
  "user_approved=True" in call`, message naming the file and the offending call.
  **Sentinel floor** (a sweep that discovers nothing proves nothing): assert the
  discovered set contains all 12 known-wired files — both directors for each of
  `explainer, animation, cinematic, avatar-spokesperson, hybrid, documentary-montage`
  — so a mass revert that deletes the ledger blocks (removing
  `CostTracker.for_project` and the reserve line together) still fails.
- Replace `test_proposal_gates_multiply_unit_price_by_planned_quantity` with
  `test_every_quantity_priced_proposal_gate_multiplies_unit_price`:
  discovery = `_director_files("proposal-director.md", "estimate_cost(planned")`
  (matches explainer/cinematic/animation today). For each:
  `assert 'unit_usd = tool.estimate_cost(planned["inputs"])' in text` and
  `assert "estimated_usd = round(unit_usd * quantity, 4)" in text`. Sentinel floor:
  discovered set ⊇ those three.

When workstream D wires the six remaining pipelines (their directors gain
`CostTracker.for_project` per D's rollout, and any new proposal gates copy C1's
blocks), both sweeps extend to them with zero test edits — the exact auto-coverage
this item was asked to provide. D's spec must NOT hand-extend the sentinel lists;
sentinels pin the floor, discovery pins the ceiling.

### Why this design

Presence-of-`CostTracker.for_project` is the definition of "ledger-wired" on this
branch (verified: 12/12 wired directors carry it, 0/12 unwired ones do), so it is the
discovery predicate that tracks D's rollout for free. Alternative — hardcoding all
pipeline names — lost: it is precisely what let five pipelines ship unguarded, and it
goes stale again the day D lands. The sentinel-floor assert closes the classic
dynamic-discovery hole (empty sweep = vacuous pass).

### Acceptance

Green today. Red checks: (1) delete `user_approved=True` from
`cinematic/asset-director.md`'s reserve line (the finding's scenario) → sweep 1 fails
naming that file; (2) delete the `round(unit_usd * quantity, 4)` line from
`animation/proposal-director.md` → sweep 2 fails; (3) delete
`CostTracker.for_project` from any of the 12 wired directors → sentinel fails.

### Risk

C2's fix edits `explainer/compose-director.md`'s estimate call but keeps its
`tracker.reserve(entry_id, user_approved=True)` line — no conflict (verified against
C's before/after text). If D wires a pipeline whose spending director legitimately has
no paid reserve (none exists today), the sweep would demand the flag anyway — accepted:
a director that opens the project ledger and reserves nothing carries no
`tracker.reserve(` call at all, so the per-occurrence sweep is vacuously satisfied.

---

## G5. `resolve_playbook_path`'s custom branch runs in zero tests on a clean checkout (`tests/contracts/test_remotion_theme_playbook_keys.py:32`, MINOR)

### Fix

New file `tests/styles/test_playbook_loader.py` (sits beside
`tests/styles/test_playbook_catalog.py`, the loader's existing test home — the
contracts file stays a theme-keys test). `resolve_playbook_path` never parses YAML, so
fixtures are `touch`-level; every test uses an explicit `styles_dir=tmp_path`, making
them independent of the untracked `styles/custom/` that hid this gap:

```python
from styles.playbook_loader import CUSTOM_SUBDIR, list_playbooks, resolve_playbook_path

def _seed(styles_dir, *, presets=(), customs=()):
    (styles_dir / CUSTOM_SUBDIR).mkdir(parents=True, exist_ok=True)
    for n in presets:
        (styles_dir / f"{n}.yaml").write_text("x: 1\n", encoding="utf-8")
    for n in customs:
        (styles_dir / CUSTOM_SUBDIR / f"{n}.yaml").write_text("x: 1\n", encoding="utf-8")
```

- `test_custom_playbook_resolves_to_custom_subdir(tmp_path)` — seed
  `customs=("brand-x",)` only. Assert
  `resolve_playbook_path("brand-x", styles_dir=tmp_path) == tmp_path / CUSTOM_SUBDIR / "brand-x.yaml"`
  — the branch at styles/playbook_loader.py:50-52 that runs in zero tests today.
- `test_preset_wins_over_custom(tmp_path)` — seed `presets=("dup",),
  customs=("dup",)`. Assert the resolved path is `tmp_path / "dup.yaml"` (the
  docstring's "a preset wins when both exist", :47-49).
- `test_missing_playbook_raises_filenotfounderror(tmp_path)` — seed nothing beyond the
  empty dirs. `pytest.raises(FileNotFoundError, match="nope")` on
  `resolve_playbook_path("nope", styles_dir=tmp_path)`; assert the message names both
  search locations (`str(tmp_path)` and `CUSTOM_SUBDIR`) — that message is the
  user-facing diagnostic the finding's regression would garble.
- `test_list_playbooks_includes_customs_and_dedupes(tmp_path)` — seed
  `presets=("a", "dup"), customs=("b", "dup")`. Assert
  `list_playbooks(styles_dir=tmp_path) == ["a", "b", "dup"]` — pins the
  `sorted(set(...))` contract that makes `resolve_playbook_path` necessary (a name
  listed from `custom/` must resolve), i.e. the exact invariant
  `test_remotion_theme_playbook_keys.py::_raw` now relies on.

### Why this design

Direct unit tests through the `styles_dir` injection point the function was given for
exactly this purpose — hermetic on CI, no dependence on generated local playbooks.
Alternative — committing a fixture playbook into `styles/custom/` so the existing
parametrized theme tests sweep it — lost: `styles/custom/` is the *output* directory
of `lib/playbook_generator.save_playbook()`; seeding repo files into it conflates
generated and tracked content and still leaves precedence and the error path untested.

### Acceptance

Green today. Red checks: revert `resolve_playbook_path`'s custom lookup to a plain
`styles_dir / f"{name}.yaml"` join → tests 1 and 3 fail; swap the lookup order →
test 2 fails.

### Risk

None — pure additions against a stable public signature.

---

## G6. No test drives `reconcile(success=False)` (`tests/tools/test_cost_tracker_governance.py:116`, MINOR)

### Fix

`tests/tools/test_cost_tracker_governance.py`, one new test covering the half of the
failure path B3 and C3 leave open — **a failed call that WAS charged**:

- `test_reconcile_failure_lands_failed_state_and_counts_real_spend` — tracker: WARN
  mode, `budget_total_usd=10.0, reserve_pct=0.0, single_action_approval_usd=99.0,
  require_approval_for_new_paid_tool=False, cost_log_path=tmp`.
  `entry_id = estimate("video_selector", "generate", 0.60)`; `reserve(entry_id)`;
  `reconcile(entry_id, 0.60, success=False)` — the provider billed a failed
  generation. Assert: entry `status == "failed"` (terminal — satisfies the six
  manifests' compose criterion "every entry in a terminal state");
  `actual_usd == 0.60` and `reserved_usd == 0.0`;
  `tracker.budget_spent_usd == 0.60` (money spent on a failed call is still spent —
  tools/cost_tracker.py:103-109) and `tracker.budget_reserved_usd == 0.0`; the
  persisted file passes `validate_artifact("cost_log", persisted)` and its entry shows
  `"failed"` — the schema-validity leg of the manifests' criterion. Finally, a second
  round trip (`estimate` 0.60 → `reserve` → `reconcile(0.60, success=True)`) brings
  `budget_spent_usd` to `1.20` — failed and completed spend aggregate.

Division of labor, pinned here so the three specs do not triple-cover:
C3's `test_documented_booking_rule_failed_call_books_no_phantom_spend` owns
failed-and-NOT-charged ($0 books $0, retry unblocked); B3's
`test_orphan_resolutions_keep_totals_honest` owns failure-reconcile of a crash orphan
by a *fresh* tracker instance; this test owns failed-and-charged on one live instance
plus the schema-validity assertion the manifests' criterion names.

### Why this design

The finding's revert scenario is a tracker change making `success=False` leave the
entry `reserved` or stop counting failed spend — both are direct asserts here.
Placed in the governance file (not B's persistence file) because it is single-instance
lifecycle semantics, the governance file's subject.

### Acceptance

Green today. Red checks: make `reconcile` map `success=False` to `"refunded"` → the
status and `budget_spent_usd` asserts fail; drop `EntryStatus.FAILED` from
`budget_spent_usd`'s filter → the `0.60` assert fails.

### Risk

None. If B2 lands first, `reconcile` runs inside `_locked()` — semantics unchanged
for a single instance, test unaffected.

---

## G7. Scoping test's docstring claims a 'forged stage' but injects a rogue top-level key (`tests/lib/test_checkpoint_cost_snapshot.py:99`, NIT)

### Fix

`tests/lib/test_checkpoint_cost_snapshot.py`. Convert
`test_read_checkpoint_still_raises_on_non_cost_snapshot_corruption` to a
parametrized test over the two branches of the tolerance's scoping condition
(`exc.field != "cost_snapshot"`, lib/checkpoint.py — field is
`str(exc.absolute_path[0]) if exc.absolute_path else None`):

> **SUPERSEDED by owner ruling (Epic 25, Ruling 2).** The shared list is no longer
> only the two scoping branches. It now also carries the `cost_snapshot` values
> that the field guard alone cannot tell apart from real legacy history — a bare
> string, a null, a list, and `*_usd` figures that are strings, nested objects,
> booleans, or NaN. Its name still reads true: these are the corruptions that are
> NOT the tolerated legacy `cost_snapshot` shape. It stays one list, imported by
> all three call sites' tests.

```python
@pytest.mark.parametrize(
    "corrupt",
    [
        # additionalProperties violation at the root: absolute_path is empty,
        # so the tolerance sees field=None — must still raise.
        lambda d: d.__setitem__("rogue_top_level_key", "smuggled"),
        # A named property with the wrong type: absolute_path is
        # ['human_approved'], so field == "human_approved" — a violation
        # attributable to a specific non-cost_snapshot property must also
        # still raise.
        lambda d: d.__setitem__("human_approved", "yes"),
    ],
    ids=["rogue-top-level-key-field-none", "wrong-typed-named-field"],
)
def test_read_checkpoint_still_raises_on_non_cost_snapshot_corruption(tmp_path, corrupt):
    """The legacy tolerance is scoped to exc.field == "cost_snapshot". Both
    other branches of that check — a violation with no attributable field
    (rogue top-level key ⇒ field=None) and one attributed to a different
    named property (wrong-typed human_approved ⇒ field="human_approved") —
    must still fail loudly rather than resume silently. (A forged-but-valid
    *stage value* is a different animal: the schema types stage as a plain
    string and the Python-side check only rejects names outside the
    pipeline's stage list, so it is not what this test covers.)"""
```

Body unchanged apart from applying `corrupt(data)` instead of the hardcoded key.
G3's `test_get_latest_checkpoint_still_raises_on_non_cost_snapshot_corruption` takes
the identical parametrization (share the param list via a module-level
`NON_COST_SNAPSHOT_CORRUPTIONS` constant).

### Why this design

The honest docstring states exactly which branch each case exercises and explicitly
disclaims the forged-stage coverage the old docstring overstated — in this repo
docstrings are read as ground truth. `human_approved = "yes"` is the cheapest
named-field violation: it passes every Python-side check in `validate_checkpoint`
(only stage/status/artifacts are type-checked there) and fails only at the jsonschema
layer with a populated `absolute_path`, which is the branch under test.

### Acceptance

Both param cases green today against `read_checkpoint` and `get_latest_checkpoint`.
Red check: widen the tolerance to `if exc.field is not None: return` (swallow every
attributable violation) → the `wrong-typed-named-field` case fails while
`rogue-top-level-key` alone would have stayed green — the exact drift the old
single-case test could not see.

### Risk

None; A1's helper extraction changes neither branch's behavior (the two existing
tolerance tests plus these pin it across the refactor).

---

## G8. Integration regressions the per-workstream acceptance tests leave uncovered

### G8a. Whole-pipeline legacy resume — the A-finding's deadlock end to end

A's acceptance proves `write_checkpoint` succeeds past a legacy predecessor. What no
sibling test proves is the *orchestrator agreement* the MAJOR finding actually
describes: the tolerant read path telling the agent to proceed AND the write path then
accepting the work — the two halves that disagreed.

`tests/lib/test_checkpoint_cost_snapshot.py`, one new test (imports add
`get_completed_stages, get_latest_checkpoint, get_next_stage`):

- `test_legacy_project_resumes_end_to_end(tmp_path)` — the full resume walk on
  framework-smoke (research → script, both gated):
  1. Arrange the legacy fixture: `init_project(...)`; write research
     `awaiting_human`; rewrite `checkpoint_research.json` on disk with
     `status="completed"`, `human_approved=True`, and
     `cost_snapshot={"spent_usd": 0.28, "approved_budget_usd": 2.0}` (the
     disk-rewrite pattern from
     `tests/lib/test_checkpoint_prerequisites.py::test_later_stage_rejects_unapproved_gated_predecessor`).
  2. Resume reads: `get_latest_checkpoint(tmp_path, "run")["stage"] == "research"`;
     `get_completed_stages(tmp_path, "run", pipeline_type="framework-smoke") == ["research"]`;
     `get_next_stage(tmp_path, "run", pipeline_type="framework-smoke") == "script"`.
  3. The write the orchestrator just directed: `write_checkpoint(tmp_path, "run",
     "script", "completed", {"script": <the `_script_artifact()` shape from
     test_checkpoint_prerequisites.py:13-26>}, pipeline_type="framework-smoke",
     human_approved=True)` succeeds (this line deadlocks with PREREQUISITE VIOLATION
     until A1 lands).
  4. Post-conditions: `get_next_stage(...)` now returns `None` (pipeline complete);
     `read_checkpoint(tmp_path, "run", "research")["cost_snapshot"]` still returns
     the legacy dict — resume did not rewrite history.

Red until A1 lands — this test rides A's PR (see Dependencies). It is the only test
in the repo where `get_next_stage`'s answer and `write_checkpoint`'s verdict are
asserted against the *same* legacy fixture, which is the invariant the finding says
broke.

### G8b. Two-process ledger race — covered by B; no new test

B's `test_parallel_processes_lose_no_entries`
(`tests/tools/test_cost_tracker_persistence.py`) already runs 4 real processes × 5
estimate→reserve→reconcile round trips against one path and asserts 20 completed
entries, correct `budget_spent_usd`, and `validate_artifact` — real `flock`
contention, real `os.replace` interleaving. That is the multi-process regression test
this workstream was asked to confirm exists; duplicating it with 2 processes adds
nothing. G adds none. (B's single-instance interleavings —
`test_two_instances_do_not_erase_each_others_entries`,
`test_cap_mode_reserve_sees_other_instances_spend` — cover the deterministic
orderings; gap check performed, none found.)

### Why this design

Integration tests are specced only where two workstreams' units meet and no sibling
asserts the joint invariant: A's read/write agreement (G8a) qualifies; B's race does
not (already joint by construction). No new fixtures, no new test infrastructure.

### Acceptance / Risk

G8a red-before/green-after A1 is its acceptance. Risk: framework-smoke gaining a
third stage would change step 4's `None` assert — the manifest is a test fixture by
declaration ("used to exercise the Phase 0 framework contracts"), so this is the
stable pipeline to pin.

---

## Landing order & file map

| Item | File | Rides with |
|---|---|---|
| G1, G6 | `tests/tools/test_cost_tracker_governance.py` | independent; before or with B/C |
| G2 | `tests/test_final_review_honesty.py` (rewrite) | **after E** |
| G3, G7, G8a | `tests/lib/test_checkpoint_cost_snapshot.py` | G3/G7 independent; **G8a with A** |
| G4 | `tests/contracts/test_agent_instruction_integrity.py` | independent; auto-extends when D lands |
| G5 | `tests/styles/test_playbook_loader.py` (new) | independent |

C also extends the two shared files (G1/G6's and G4's) — the test names above collide
with none of C's (`test_documented_arming_formula_*`, `test_plan_name_keyed_*`,
`test_no_or_estimated_fallback_*`, etc.); whoever lands second rebases trivially
(pure additions, plus G4's two replacements of tests C does not touch).

**Open questions:** none
**Dependencies:** Workstream E — G2 rewrites tests/test_final_review_honesty.py against E1/E2's measured/indeterminate verdict design and imports _make_mp4 from E's tests/tools/test_final_review_audio_gates.py; G2 must land after E (a measured-silence fixture is required for the gate-fire assert, per E's own dependency note). | Workstream A — G8a's end-to-end legacy resume test is red until A1's prerequisite tolerance lands; it should ride A's PR. G3/G7 are independent of A but pin the entry points across A1's helper extraction. | Workstream B — G8b deliberately adds no multi-process test because B's test_parallel_processes_lose_no_entries covers it; if B's acceptance suite lands without that test, G must add the two-process race test instead. G1/G6 are single-instance and unaffected by B2's locking. | Workstream C — C extends the same two shared test files (test_cost_tracker_governance.py, test_agent_instruction_integrity.py); names verified non-colliding, land in either order with a trivial rebase. G6's division of labor assumes C3's failed-$0 booking test lands as specced. | Workstream D — no landing dependency: G4's dynamic discovery (CostTracker.for_project predicate + sentinel floor of the 12 currently-wired files) auto-covers the six pipelines D wires; D must copy the canonical blocks (per C's constraint) and must not hand-extend G4's sentinel lists.
