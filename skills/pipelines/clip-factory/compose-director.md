# Compose Director - Clip Factory Pipeline

## When To Use

Render each clip and platform variant independently. The important behaviors here are consistency, batch resilience, and clear reporting of partial failures.

## Runtime Routing (HARD CONSTRAINT — Remotion or FFmpeg only)

This pipeline is Phase 1 deferred from the HyperFrames adoption schedule. `edit_decisions.render_runtime` must be `"remotion"` (default) or `"ffmpeg"` (pure-concat clip jobs with no composition). HyperFrames is NOT a valid runtime here — clip-factory depends on Remotion word-level caption burn, and HyperFrames caption parity is deferred work.

- If `edit_decisions.render_runtime == "hyperframes"`, stop. Re-open the idea stage so the user can be presented the real constraint and lock `remotion` with a `render_runtime_selection` decision that records `hyperframes` as `rejected_because: "caption-burn parity deferred on clip-factory"`.
- Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)": the constraint is NOT an excuse to skip the conversation. The user still gets to see that HyperFrames exists and why it isn't viable here.
- Pass `proposal_packet`/`brief` to `video_compose.execute()` so the in-tool runtime-swap check runs end-to-end.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/render_report.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["edit"]["edit_decisions"]`, `state.artifacts["assets"]["asset_manifest"]` | Clip edits and assets |
| Tools | `video_trimmer`, `video_compose`, `audio_mixer`, `color_grade` | Render pipeline |
| Cost tracker | `tools/cost_tracker.py` — `CostTracker.for_project(project_id)` | Reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea and asset directors already wrote to |
| Media profiles | `lib/media_profiles.py` | Platform targets |

## Process

### 1. Treat Each Output As Its Own Job

One clip across three platforms is three render jobs. Name and track them explicitly.

### 2. Reuse What Can Be Shared

- shared audio mix where possible,
- shared subtitle styling,
- shared overlay assets,
- shared grading if the source needs it.

### 3. Fail Softly

If one clip or one platform variant fails:

- log it clearly,
- continue the rest of the batch,
- do not block successful exports.

### 4. Verify Every Output

Per render:

- correct duration,
- correct resolution/aspect ratio,
- no black opening frame,
- hook appears on time,
- subtitles render correctly,
- audio is present and consistent.

### 5. Use Render Report Metadata

Recommended metadata keys:

- `job_index`
- `failed_jobs`
- `shared_intermediates`
- `platform_groupings`

### 6. Ledger Round-Trip For The Render

The render itself is a local, $0-API-cost operation — round-trip it through the same tracker so `cost_log.json` leaves no entry in `estimated`/`reserved` state. One batched entry covers the whole clip render set, however many clips, platform variants, and Remotion/FFmpeg passes it takes:

```python
entry_id = tracker.estimate("video_compose", "render x 12 clip jobs", 0.0)  # one entry, the whole batch
tracker.reserve(entry_id, user_approved=True)
# ... run every render job (Steps 1-4) ...
tracker.reconcile(entry_id, 0.0, success=True)   # success=False only if the whole batch is abandoned
```

This is what the compose stage's cost_log success criterion checks — every entry in a terminal state with totals matching what the run actually spent. Any paid post pass actually run (`audio_enhance`, a paid upscale) gets its own round trip under its plan line-item name, booked with the same rule as the asset director's calls.

**Interplay with `### 3. Fail Softly`:** partial batch failure does NOT flip the batch entry. A clip that fails to render is recorded in `render_report.metadata.failed_jobs`; the batch entry still reconciles `success=True` because the batch was run and the money involved is $0.00 either way. Reconcile with `success=False` only when the whole batch is abandoned. Never open a second entry for a retried clip — the batch entry covers it.

## Common Pitfalls

- Rendering sequentially without reason when jobs are independent.
- Treating a failed clip as a reason to stop the batch.
- Letting one platform variant quietly use the wrong framing or subtitle zone.
