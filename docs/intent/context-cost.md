# Intent: cut session context cost without touching pipeline quality

Confirmed 2026-08-31. Status: spec in progress.

## Confirmed intent

- **Outcome:** Cut cache-read volume in long OpenMontage sessions by shrinking what is
  resident in context, not by ending sessions earlier.
- **User:** Solomon, doing multi-hour visual QA on video output where a session is one
  continuous review.
- **Why now:** Sessions average ~300K context across 500+ API calls; every tool call
  re-reads all of it, and that product is the bill.
- **Success:** Cache-read tokens per session drop materially (target ~40%) with zero
  change to what can be seen and decided.
- **Constraint (absolute):** *"there should be no reduction in the quality of the
  pipeline. if that is affected, i'd rather pay the overhead than get worse pipeline."*
  Visual QA is non-negotiable — the agent must still actually see frames and contact
  sheets. Any lever that makes review blind, or changes what the pipeline produces,
  is disqualified regardless of savings.
- **Out of scope:** cross-session amnesia / decision log, splitting sessions, switching
  models, trimming `AGENT_GUIDE.md`, compaction tuning.

## Measured ground truth

From 14 session transcripts (188MB) in
`~/.claude/projects/-home-solafidei-OpenMontage/*.jsonl`:

| Fact | Value |
|---|---|
| Cache hit rate | 97.3% |
| Total uncached input, all 14 sessions | 5,580 tokens |
| Total cache-read tokens (deduped) | 381,600,000 |
| Peak context, 3 biggest sessions | 541,892 / 558,983 / 587,247 |
| API calls in those sessions (deduped) | ~282 / ~267 / ~273 |
| Context growth | linear, ~1,760 tokens per real API call |
| Baseline share of bill | 14–16% |
| Accumulation share of bill | 84–86% |
| Compaction events in a 587K session | 0 |

**Falsified hypothesis:** there is no cache cliff at 500K. Cache is healthy; the bill is
cache-*read* volume.

**Cost model:** `total context-tokens ≈ 0.5 × peak × n_calls` — quadratic in session
length. Cutting per-turn accretion by X% cuts the bill ~X%; cutting call count by Y%
cuts it ~Y% *and* shrinks peak, compounding.

**Residency decomposition** (position-weighted, 5 substantial sessions, 96.75% accounted):

| Category | Share of bill |
|---|---|
| tool_result text (Bash alone 26.1%) | 28.8% |
| assistant tool_use **input** (code the agent writes) | 21.4% |
| assistant thinking | 20.4% |
| baseline | 16.1% |
| images | 5.9% |
| assistant visible text | 2.2% |
| user text | 2.0% |

Images are **5.9%**, not the ~17% first estimated — that early figure counted base64
bytes instead of image tokens.

**Image cost is pixel-proportional, not a flat cap.** ≈ `(w × h) / 750` after downscale
to a 1568px long edge. Measured over 101 isolated single-image context deltas:
min 336, median 1632, mean 1806, p90 3174, max 3872 — an **11.5x spread**, with 50%
below the 1600 flat figure. The flat assumption is accurate in aggregate (ratio 1.13),
which is why it survived four investigations unchallenged, but it hides the whole lever:

> A 1920x1080 frame read whole costs ~2,700-3,900 tokens **and** is downsampled to
> 1568px — an 18% linear loss on exactly the glyph edges, sparkle pixels and step-edges
> the QA is judging. The native crop of the region that answers the question costs
> ~460 tokens and loses nothing. The agent pays ~6x for a strictly **worse** look at
> the evidence.

## Reproducing the measurement

Parse the JSONL; assistant lines carry `message.usage` with `input_tokens`,
`cache_read_input_tokens`, `cache_creation_input_tokens`. Context size at a call is the
sum of those three. Count images as ~1.6K tokens each, not base64 bytes.

**Dedupe by `message.id` for USAGE only.** Content blocks for one message are written
on separate lines sharing that id, so first-occurrence dedupe discards ~69% of content
blocks. Merge blocks within an id when counting content; dedupe when summing usage.

**You MUST dedupe by `message.id`.** The transcripts write each assistant message 1–3
times per API call, all sharing one `message.id`/`requestId`. Naive summing inflates the
bill by **2.05x** — verified: 781.2M raw over 2,864 lines vs 381.6M over 1,405 unique
ids. Ratios and percentages survive the error; absolute totals do not.
`~/.claude/token-tracker/token-usage-report.mjs` has this bug and reports 2x high.

## Why compaction never fires

`settings.json` sets `"model": "opus[1m]"` with no `autoCompact` key, so the autocompact
trigger sits near ~920K. Peak sessions reach 541–587K — 57–64% of the window. The
sessions are not failing to compact; they are structurally incapable of reaching the
threshold. This is the root cause, and no ingestion-side lever addresses it.
