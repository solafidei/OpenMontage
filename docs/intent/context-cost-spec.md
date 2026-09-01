# Spec: gate-anchored compaction with a judgment note

Status: **proposed, awaiting go-ahead**. Intent confirmed in
[`context-cost.md`](context-cost.md).

## Problem

Session cost is `sum over API calls of context size at that call` ≈ `0.5 × peak × n_calls`
— quadratic in session length. Sessions reach 541–587K peak over ~220–293 API calls and
**never compact**, because `settings.json` sets `"model": "opus[1m]"` with no
`autoCompact` key, putting the trigger near ~920K. Peaks reach 57–64% of the window.

Eight ingestion-side levers were specced and all eight were refuted on quality grounds.
The reason is structural: **every one reduced what *enters* context; none evicted
anything.** Eviction is the only mechanism that addresses a quadratic.

## Why gates, not a threshold

Real per-call deltas replayed across the 5 substantial sessions:

| strategy | total context-tokens | saving | fires/session |
|---|---|---|---|
| actual today | 355M | — | 0 |
| **gate-anchored, 150K floor** | **172M** | **51.5%** | 3–6 |
| gate-anchored, 250K floor | 208M | 41.4% | 1–2 |
| blind threshold @300K | 206M | 41.9% | — |

Compacting blind at the *same* 150K floor saves more — 61.8% vs 51.5%. **10.3 points is
the price of boundary control**, and it is worth paying: blind compaction can fire while
you are mid-comparison across takes, summarising in-flight visual-QA state that has no
durable home. Gate-anchored can never do that.

Recommended shape is gate-anchored discipline **plus a blind backstop**:

| strategy | saving | fires |
|---|---|---|
| blind `--autocompact 150000` | 61.8% | anywhere, including mid-QA |
| gate-anchored @150K | 51.5% | closed stages only |
| **gate@150K + backstop `--autocompact 400000`** | **51.5%** | 21 gate fires, **0 backstop fires** |

The backstop never engaged in any of the five sessions — gates arrive often enough that
context never reaches 400K under the discipline. It is free insurance against a single
stage running unusually long, and costs nothing when the discipline holds.

Measured gate positions (deduped call index):

- `f979e306` (293 calls): 7, 127, 179, 185, 186, 202, 266, 280, 292
- `2db89d51` (222 calls): 5, 14, 126, 149–154, 215, 220, 221
- `e14bd906` (237 calls): 50, 70, 72, 73, 147, 150, 155, 158, 194, 213, 215, 222, 223, 230

## Design

### 1. Trigger

Fire at a stage boundary **only when both** hold:

- `write_checkpoint()` has just written `status` of `completed` or `awaiting_human`
  ([`lib/checkpoint.py:435`](../../lib/checkpoint.py#L435)), and
- effective context exceeds a **150K floor**.

Never fire mid-stage. Never fire while a render, a take comparison, or a visual-QA
review is in flight. Gates that cluster (185, 186) collapse to one fire via the floor.

### 2. The judgment note

The checkpoint already carries *pipeline* state. It does not carry *judgment* state —
"take 3 rejected, mouth drift at 0:04", "warm grade vetoed", "do not re-cut scene 2".
That is precisely what a compaction summary drops silently and what you would feel the
loss of.

Before each fire, append to `projects/<id>/artifacts/decision_log.json`
(append-only, spans stages, one readable document — the name already appears in
[`scripts/backlot_screenshot_stage.py`](../../scripts/backlot_screenshot_stage.py)):

```json
{ "stage": "render", "at": "<iso8601>",
  "rejections": [{"subject": "take 3", "reason": "mouth drift @0:04", "evidence": "scratchpad/mouth/s4_sheet.png"}],
  "rulings":    [{"ruling": "warm grade vetoed", "scope": "all scenes"}],
  "open":       ["scene 2 audio sync unverified"],
  "measured":   {"loudness_lufs": -16.2, "fps": 24} }
```

Rules: verdicts and their **reasons**, never a narrative retelling. Evidence by path,
never by re-embedding the image. Append, never rewrite.

### 3. What carries forward

1. the checkpoint file (pipeline state — already durable)
2. `decision_log.json` (judgment state — new)
3. `AGENT_GUIDE.md` routing (re-read on demand)

Everything else — tool_result bulk, thinking, the agent's own analysis scripts — is
discardable by construction, because 1–3 reconstruct every decision that has been made.

## Quality invariants

This spec is disqualified if it violates any of these:

- **Nothing in flight is ever summarized.** Fires only at a closed stage boundary.
- **No image is ever re-read to recover state.** Verdicts live in the decision log; the
  frames stay on disk and are re-read only if you ask a *new* question about them.
- **No pipeline output changes.** This touches only what the agent must hold in context,
  never what any tool produces.
- **A dropped judgment is a bug, not a tradeoff.** If a decision is lost across a fire,
  the note schema is wrong and gets fixed — the answer is never "compact less carefully".

## Open questions — must resolve before implementing

1. ~~Can compaction be invoked programmatically?~~ **RESOLVED.** `claude --autocompact
   <auto|tokens>` accepts 100k–1M, so the blind threshold is settable — that is the
   backstop. Gate-anchored firing still ships as a *discipline* (an `AGENT_GUIDE.md`
   rule at the checkpoint boundary), since the flag has no notion of a stage. Still
   unverified: whether a hook can trigger compaction directly, which would let the
   discipline be enforced rather than merely stated.
2. **What does `/compact` actually preserve** in this harness version? The 45K
   carried-summary assumption in the simulation comes from the prior analysis, not from
   measurement — no session on disk has ever compacted, so there is no local evidence.
3. **Floor tuning.** 150K is the best of three tested values, not an optimum. Worth one
   sweep once real fire data exists.

## Rollout

1. **DONE** — backstop set via `alias claude='claude --autocompact 400000'` in `~/.bashrc`.
   The CLI flag is verified working; a `settings.json` `autocompact` key was *not* verified
   (the file was accepted, which is not proof the key is honoured) so the alias is the
   supported route. Zero behavioural change in any historical session; pure insurance.
2. **DONE (mechanism already existed)** — no new code was needed. `write_checkpoint()`
   already merges `artifacts["decision_log"]` into a cumulative project-level
   `decision_log.json` via `_merge_decision_log()`
   ([`lib/checkpoint.py:405`](../../lib/checkpoint.py#L405)), and the
   `decision_log` artifact is fully schema'd
   ([`schemas/artifacts/decision_log.schema.json`](../../schemas/artifacts/decision_log.schema.json))
   with a `visual_accuracy_check` category that fits QA verdicts.

   **Prerequisite bug found and fixed:** `ask-jess` had two divergent logs — root with 11
   decisions, `artifacts/` with 30. No code writes the `artifacts/` copy; the agent
   hand-wrote it during the session, bypassing the merge (a Rule Zero violation).
   Backfilled via `_merge_decision_log()`; root is now the complete 30-decision trail.
   `only-in-root` was 0, so the backfill was purely additive. The other two projects
   already agreed. **The writer is still unfixed — this will recur.**
3. Add the `AGENT_GUIDE.md` rule to compact at a closed stage when context exceeds 150K.
   **HELD** at your instruction.
4. Measure one episode. If the decision log holds, keep going; if anything you ruled on
   went missing, fix the schema before trusting the mechanism.

Steps 1–2 are independently useful and carry no risk on their own. Step 3 is where the
saving lands and where the quality question actually lives.

## Verification plan

- Instrument: after each fire, assert `decision_log.json` parses and its rulings count is
  monotonically non-decreasing. One assert, run at the next gate.
- Measure: with the now-fixed tracker (`token-usage-report.mjs`, deduped by `message.id`),
  compare context-tokens per completed episode before and after. Expect ~50%.
- Quality gate: for the first 3 episodes, diff the decision log against the session
  scrollback by hand and confirm nothing you ruled on is missing. If anything is, the
  schema is wrong — fix it before trusting the mechanism.
