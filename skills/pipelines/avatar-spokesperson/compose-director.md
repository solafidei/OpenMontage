# Compose Director - Avatar Spokesperson Pipeline

## When To Use

Render the final spokesperson outputs. The bar is simple: the presenter must look stable, speech must be clear, and subtitles or support cards must not crowd the frame.

## Runtime Routing (HARD CONSTRAINT — Remotion only)

Phase 1 deferred from HyperFrames. `edit_decisions.render_runtime` must be `"remotion"`. This pipeline depends on the Remotion `TalkingHead` composition and `remotion_caption_burn` — both have no HyperFrames parity in Phase 1.

- If `edit_decisions.render_runtime == "hyperframes"`, stop. Re-open the idea stage and surface the constraint. Silent rewrite is a governance violation.
- Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)": the lock to remotion is NOT an excuse to skip the conversation. The user deserves to know that HyperFrames exists as a runtime and why it isn't viable for avatar-spokesperson. Log a `render_runtime_selection` decision with hyperframes `rejected_because: "TalkingHead + caption parity deferred on avatar-spokesperson"`.
- Pass `proposal_packet`/`brief` to `video_compose.execute()` for in-tool runtime-swap detection.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/render_report.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["edit"]["edit_decisions"]`, `state.artifacts["assets"]["asset_manifest"]` | What to render |
| Tools | `video_compose`, `audio_mixer`, `video_stitch`, `audio_enhance` | Render and audio finishing |
| Cost tracker | `tools/cost_tracker.py` — `CostTracker.for_project(project_id)` | Reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea and asset directors already wrote to |
| Playbook | Active style playbook | Typography and layout rules |

## Process

### 0b. Cost Track The Render

The render itself is a local, $0-API-cost operation — round-trip it through the same tracker so `cost_log.json` leaves no entry in `estimated`/`reserved` state: `entry_id = tracker.estimate("video_compose", "render", 0.0)`, `tracker.reserve(entry_id, user_approved=True)`, then `tracker.reconcile(entry_id, 0.0, success=True)` once the render finishes (`success=False` if it failed). This is what the compose stage's cost_log success criterion checks — every entry in a terminal state with totals matching what the run actually spent.

### 1. Render The Hero Cut First

Prefer one strong master before derivatives. Compose:

- presenter video,
- subtitles,
- lower-thirds,
- CTA cards,
- mixed narration.

### 2. Keep The Frame Clean

Subtitle and CTA placement matter more here than flashy transitions. Leave the face and mouth region unobstructed.

### 3. Verify Mouth Timing And Audio

If the avatar path used lip sync or audio-driven talking head, check:

- mouth timing,
- face artifacts,
- drift on long sections,
- audio clarity.

### 4. Verify Every Output

Record important findings in:

- `render_report.verification_notes`
- `render_report.warnings`
- `render_report.metadata.variant_notes`

### 5. Quality Gate

- the output file is valid,
- speech is clear,
- subtitles stay readable,
- the presenter remains visually stable.

## Common Pitfalls

- Letting subtitles cover the chin or mouth area.
- Shipping a long lip-sync render without spot-checking drift.
- Making derivative crops that cut off the presenter or CTA.
