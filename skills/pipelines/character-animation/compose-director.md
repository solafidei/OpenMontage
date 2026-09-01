# Compose Director - Character Animation Pipeline

## Goal

Render the approved character animation and prove it was reviewed.

## Runtime Routing

First read `edit_decisions.render_runtime`. It must match the runtime locked in
proposal unless a `render_runtime_selection` decision explicitly changed it.

- `remotion`: stage assets into `remotion-composer/public`, build composition
  JSON, render via `video_compose`.
- `hyperframes`: materialize a HyperFrames workspace and let `video_compose`
  delegate to `hyperframes_compose`. `hyperframes lint` and `validate` must pass.
- `ffmpeg`: only for post-processing or simple video assembly; not enough for
  character acting by itself.

## Review Workflow

1. Run `character_rig_renderer` to produce or refresh the HyperFrames package.
   The browser preview is a QA/debug artifact only, not the render path.
2. Verify the renderer emitted a HyperFrames `workspace_path`, composition HTML,
   `asset_manifest`, and `edit_decisions.render_runtime: "hyperframes"` handoff.
3. Run `character_animation_reviewer` against rig, poses, timeline, and preview.
4. Render final video through `video_compose` using the renderer handoff or the
   approved Remotion/HyperFrames package. The deliverable path is
   `projects/<project-name>/renders/final.mp4`, matching the standard
   OpenMontage project convention.
5. Run standard `final_review`: ffprobe, frame sampling, visual spotcheck, audio
   spotcheck, promise preservation.

## Browser QA

When Playwright is available:

- open the preview,
- capture opening/middle/end frames,
- check for console errors,
- verify characters are visible,
- compare frame deltas to ensure motion exists.

When Playwright is unavailable, use static artifact checks and FFmpeg frame
sampling, and report the reduced confidence.

## Ledger Round-Trip For The Render

The render itself is a local, $0-API-cost operation — `character_rig_renderer`,
`video_compose`, `audio_mixer` and `character_animation_reviewer` are all free.
Round-trip it through the same tracker so `cost_log.json` leaves no entry in
`estimated`/`reserved` state. Open the project's tracker here rather than
assuming one is in scope — `tracker = CostTracker.for_project(project_id)`
reopens the same `projects/<project_id>/artifacts/cost_log.json` the proposal
director seeded and the asset director already wrote to, and it is what carries
the gate-approved cap into this stage's checkpoint (an unopened tracker reports
config's default budget instead). ONE batched entry covers the whole render,
however many renderer, reviewer and Remotion/HyperFrames passes it takes:

```python
from tools.cost_tracker import CostTracker

tracker = CostTracker.for_project(project_id)  # same ledger the proposal director opened

entry_id = tracker.estimate("video_compose", "render", 0.0)
tracker.reserve(entry_id, user_approved=True)
# ... run the Review Workflow above: rig render, reviewer, final video_compose ...
tracker.reconcile(entry_id, 0.0, success=True)   # success=False if the render failed
```

This is what the compose stage's cost_log success criterion checks — every entry in
a terminal state with totals matching what the run actually spent. Any paid post
pass actually run (a paid upscale, a re-generated audio bed) gets its own round trip
under its plan line-item name, booked with the same rule as the asset-director's
paid calls. See `skills/meta/checkpoint-protocol.md` → Cost Ledger Governance for
the shared rules.

## Quality Bar

Do not present the output as complete when `character_qa_report.status` is
`revise` or `fail`.
