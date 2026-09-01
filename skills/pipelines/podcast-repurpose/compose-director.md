# Compose Director - Podcast Repurpose Pipeline

## When To Use

Render the podcast-derived outputs with audio fidelity as the top priority. The visuals need to support the speech, not compete with it.

## Runtime Routing (HARD CONSTRAINT — Remotion or FFmpeg only)

Phase 1 deferred from HyperFrames. `edit_decisions.render_runtime` must be `"remotion"` (audiograms, composed outputs) or `"ffmpeg"` (pure-audio-led clip exports). HyperFrames caption-burn parity is deferred, and podcast outputs lean on Remotion's word-level caption stack.

- If `edit_decisions.render_runtime == "hyperframes"`, stop. Re-open the idea stage and surface the constraint to the user. Never silently rewrite the runtime.
- Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)": tell the user HyperFrames exists and why it isn't viable on this pipeline, rather than silently locking remotion. Record a `render_runtime_selection` decision with hyperframes `rejected_because: "caption-burn parity deferred on podcast-repurpose"`.
- Pass `proposal_packet`/`brief` to `video_compose.execute()` for end-to-end runtime-swap detection.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/render_report.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["edit"]["edit_decisions"]`, `state.artifacts["assets"]["asset_manifest"]` | Output plans and asset paths |
| Tools | `video_compose`, `audio_mixer` | Rendering and mix control |
| Cost tracker | `tools/cost_tracker.py` — `CostTracker.for_project(project_id)` | Reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea and asset directors already wrote to |
| Playbook | Active style playbook | Brand consistency |

## Process

### 1. Render Highest-Value Outputs First

Priority order:

1. short highlight clips
2. quote-led clips
3. optional long-form companion video

This keeps the most publishable assets available first.

### 2. Preserve Audio Quality

- avoid unnecessary re-encoding,
- keep speech intelligible and stable,
- use music sparingly and only when it does not compete,
- verify subtitle sync after render.

### 3. Respect Platform Shapes

- `9:16` for short-form social
- `1:1` for quote-led or feed-safe clips
- `16:9` for long-form YouTube companion output

### 4. Verify Every Deliverable

- correct duration,
- correct aspect ratio,
- readable subtitles,
- accurate speaker attribution,
- stable audio,
- consistent brand treatment.

### 5. Use Render Report Metadata

Recommended metadata keys:

- `deliverable_groups`
- `audio_notes`
- `subtitle_checks`
- `failed_outputs`

### 6. Ledger Round-Trip For The Render

The render itself is a local, $0-API-cost operation — round-trip it through the same tracker so `cost_log.json` leaves no entry in `estimated`/`reserved` state. One batched entry covers every deliverable render, however many Remotion/FFmpeg passes it takes; open it before Step 1 and close it once Step 4 has verified the outputs:

```python
entry_id = tracker.estimate("video_compose", "render x 6 clips + companion", 0.0)
tracker.reserve(entry_id, user_approved=True)
# ... render every deliverable (Steps 1-4) ...
tracker.reconcile(entry_id, 0.0, success=True)   # success=False if the render failed
```

This is what the compose stage's cost_log success criterion checks — every entry in a terminal state with totals matching what the run actually spent. `audio_mixer`, `video_trimmer` and `audio_enhance` are local and free, so they ride the same batched `$0.00` entry rather than earning one each. Any genuinely paid post pass actually run (a paid upscale, a re-cut music bed) gets its own round trip under its plan line-item name, booked with the same rule as the asset director's paid calls.

## Common Pitfalls

- Letting visual treatments degrade audio quality.
- Rendering the full companion first and delaying the clips that matter most.
- Forgetting that a simple, readable clip beats a technically elaborate but confusing one.
