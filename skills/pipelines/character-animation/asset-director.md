# Asset Director - Character Animation Pipeline

## Goal

Produce `asset_manifest` with character parts, backgrounds, props, audio, music,
and preview artifacts.

## Layer 3 Gate

Before authoring or generating animation assets, read the relevant Layer 3 skills:

- `character-rigging`
- `svg-character-animation`
- `pose-library-design`
- `canvas-procedural-animation` when p5/canvas effects are used
- `character-animation-qa` before review
- `gsap-core`, `gsap-timeline`, and `gsap-react` for GSAP/Remotion work
- `remotion` and `remotion-best-practices` for Remotion render work
- `hyperframes` and `hyperframes-cli` for HyperFrames work

Before image/TTS/music generation, read the tool's `agent_skills` from the
registry.

## Ledger Discipline For Every Paid Call

Open the project's tracker once — `tracker = CostTracker.for_project(project_id)`
reopens the same `projects/<project_id>/artifacts/cost_log.json` the proposal
director seeded and every other stage shares. For every paid call (`tts_selector`,
`image_selector`, `music_gen`), run the full estimate → reserve → reconcile round
trip, booking under the PLAN's line-item name, never the concrete provider name:

```python
from tools.cost_tracker import CostTracker

tracker = CostTracker.for_project(project_id)  # same ledger the proposal director opened

inputs = {
    "prompt": scene["music_plan"]["prompt_seed"],
    "duration_seconds": scene_plan["duration_seconds"],  # required — estimate_cost raises without it
    "output_path": f"projects/{project_id}/assets/music/score_bed.mp3",
}
estimated_usd = music_gen.estimate_cost(inputs)
entry_id = tracker.estimate("music_gen", "score_bed", estimated_usd)
tracker.reserve(entry_id, user_approved=True)  # this call fulfills the music line item approved at proposal

result = music_gen.execute(inputs)

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
    # budget_spent_usd counts FAILED entries as well as completed ones
    # (CostTracker.budget_spent_usd), so a substituted estimate is phantom
    # spend that shrinks usable budget and can block the real retry in cap
    # mode.
    actual_usd = reported
tracker.reconcile(entry_id, actual_usd, success=result.success)
```

The same round trip covers the other two paid tools, keyed on the approved plan's
line-item names — `tracker.estimate("tts_selector", "dialogue via openai_tts", ...)`
(quantity 1, whole payload) and `tracker.estimate("image_selector", "backgrounds x 5", ...)`
(one batched entry per same-tool batch, unit price × count).

**Known-free routes book $0.00.** When the result itself shows the routed provider is free/local (e.g. the selector's `result.data` names a $0 route, or the entry was estimated at $0), a success reporting 0.0 IS the actual cost — book 0.0, not the estimate. See `skills/meta/checkpoint-protocol.md` → Cost Ledger Governance for the shared rules.

`user_approved=True` is for approved-plan work only — omit it for anything outside
what the user approved at the proposal gate (a re-generation of the whole cast
beyond the approved sheet count); that call should hit the single-action guard like
any unplanned spend, which is the guard working as intended. Surface a tripped guard
as a structured blocker per AGENT_GUIDE.md → "Escalate Blockers Explicitly." If a
reservation is made but the call never runs (sample rejected), call
`tracker.refund(entry_id)`. The free/local renderer (`character_rig_renderer`) still
gets the same round-trip with `0.0` — ONE batched entry per logical batch, e.g.
`tracker.estimate("character_rig_renderer", "part previews x 12", 0.0)` — so every
entry lands in a terminal state before compose.

## Asset Organization

Write character assets under:

```text
projects/<project-name>/assets/characters/<character-id>/
```

Use subfolders:

```text
parts/
poses/
previews/
```

Generated backgrounds go under:

```text
projects/<project-name>/assets/backgrounds/
```

## Process

1. Produce or source only the parts required by `rig_plan`.
2. Keep each moving part separate.
3. Preserve transparent backgrounds for parts.
4. Record prompts, seeds, providers, and model names.
5. Build a small preview before full asset expansion.

## Quality Bar

All parts referenced by `rig_plan` must exist before compose. Missing parts are a
blocker unless the action timeline removes the action requiring them.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
