# Compose Director - Localization Dub Pipeline

## When To Use

Render the localized outputs. The quality bar is intelligibility, timing coherence, and clear version labeling across every language package.

## Runtime Routing (HARD CONSTRAINT — Remotion or FFmpeg only)

Phase 1 deferred from HyperFrames. `edit_decisions.render_runtime` must be `"remotion"` or `"ffmpeg"`. Localization depends on Remotion's caption stack (per-locale subtitle burn) and, when dubbing with lip-sync, on the Remotion TalkingHead pipeline. HyperFrames has no parity for either in Phase 1.

- If `edit_decisions.render_runtime == "hyperframes"`, stop. Re-open the idea stage and surface the constraint — don't silently rewrite the runtime.
- Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)": the pipeline's constraint does NOT skip the conversation. Present the constraint to the user so they know HyperFrames exists but isn't viable here. Log a `render_runtime_selection` decision with hyperframes `rejected_because: "caption + lip-sync parity deferred on localization-dub"`.
- Pass `proposal_packet`/`brief` to `video_compose.execute()` for end-to-end runtime-swap detection.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/render_report.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["edit"]["edit_decisions"]`, `state.artifacts["assets"]["asset_manifest"]` | Locale-specific render instructions |
| Tools | `video_compose`, `audio_mixer`, `video_trimmer`, `audio_enhance` | Final render and audio finishing |
| Cost tracker | `tools/cost_tracker.py` — `CostTracker.for_project(project_id)` | Reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea and asset directors already wrote to |
| Playbook | Active style playbook | Subtitle placement and output quality |

## Process

### 1. Render By Locale

Treat each target language as its own deliverable set. Keep names and output directories explicit.

### 2. Expect Timing Adjustments

Allow for:

- subtitle reflow,
- dub-audio duration drift,
- longer CTA holds,
- optional trims or coverage sections.

### 3. Verify Every Locale

Record important findings in:

- `render_report.verification_notes`
- `render_report.warnings`
- `render_report.metadata.locale_notes`

Check:

- intelligibility,
- subtitle fit,
- obvious sync drift,
- version labeling.

### 4. Quality Gate

- each locale output exists,
- the dub and subtitle timing are acceptable,
- labels and filenames are unambiguous,
- warnings are preserved.

### Ledger Round-Trip For The Render

The render itself is a local, $0-API-cost operation — round-trip it through the same tracker so `cost_log.json` leaves no entry in `estimated`/`reserved` state. ONE batched entry covers the whole locale render set, however many Remotion/FFmpeg passes each locale takes — never one entry per locale file:

```python
entry_id = tracker.estimate("video_compose", "render x 2 locales", 0.0)  # one entry for the whole set, count = len(target_languages)
tracker.reserve(entry_id, user_approved=True)
# ... render every locale deliverable (Step 1) ...
tracker.reconcile(entry_id, 0.0, success=True)   # success=False if the render set was abandoned
```

If one locale fails but the set is still delivered, book the batch `success=True` and record the failed locale in `render_report.warnings` — a $0 entry carries no money either way, and the render report is where the failure belongs. This is what the compose stage's cost_log success criterion checks — every entry in a terminal state with totals matching what the run actually spent. Any paid post pass actually run (`audio_enhance` on a paid route) gets its own round trip under its plan line-item name, booked with the asset director's rule.

## Common Pitfalls

- Rendering all locales as if they were timing-identical.
- Forgetting to re-check subtitle line length after translation.
- Naming outputs in ways that hide the locale or treatment mode.
