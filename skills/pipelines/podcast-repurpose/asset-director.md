# Asset Director - Podcast Repurpose Pipeline

## When To Use

This stage builds the reusable kit for podcast-derived video assets: subtitles, speaker cards, quote cards, optional topic art, and optional music support.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/asset_manifest.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["scene_plan"]["scene_plan"]`, `state.artifacts["script"]["script"]`, `state.artifacts["idea"]["brief"]` | Deliverable plan and transcript truth |
| Tools | `subtitle_gen`, `image_selector`, `diagram_gen`, `music_gen`, `audio_enhance` | Asset generation |
| Cost tracker | `tools/cost_tracker.py` — `CostTracker.for_project(project_id)` | Reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea director already wrote to |
| Playbook | Active style playbook | Brand consistency |

## Process

### 1. Start With Mandatory Assets

Highest priority:

- subtitles for every clip,
- clean audio where needed,
- speaker attribution assets if multiple speakers appear,
- quote-card templates for quote-led outputs.

### 1b. Hero Scene Sample (Mandatory)

Before batch asset generation:
1. Identify the hero clip (the most important or impactful clip in the batch)
2. Generate ONE sample asset for that clip (subtitle style, speaker card, or quote card)
3. Present it: "This is the visual direction for the most important clip. Does this match what you're imagining? I'll generate the rest in this style."
4. Wait for approval before proceeding to batch generation

This prevents the most expensive mistake: generating 10+ assets in a direction the user doesn't like.

### 1c. Ledger Discipline For Every Paid Call

Open the project's tracker once — `tracker = CostTracker.for_project(project_id)` reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea director and every other stage share. Most of this stage is free: `subtitle_gen`, `audio_enhance` and the template work are local and cost $0. The paid calls are `music_gen` clip beds and `image_selector` quote/speaker cards. For every paid call, run the full estimate → reserve → reconcile round trip:

```python
from tools.cost_tracker import CostTracker

tracker = CostTracker.for_project(project_id)  # same ledger the idea director opened

inputs = {
    "prompt": bed["prompt_seed"],
    "duration_seconds": bed["duration_seconds"],  # required — music_gen.estimate_cost raises without it
    "output_path": f"projects/{project_id}/assets/music/clip_bed_hook_1.mp3",
}
estimated_usd = music_gen.estimate_cost(inputs)
entry_id = tracker.estimate("music_gen", "clip_bed_hook_1", estimated_usd)
tracker.reserve(entry_id, user_approved=True)  # this call fulfills the deliverable mix approved at idea

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

Card work batches: one entry per same-tool batch, not one per artifact — `entry_id = tracker.estimate("image_selector", "quote_cards x 6", estimated_usd)`, reserve it, then reconcile once the batch lands, booking with the same success/failure rule as above.

**Known-free routes book $0.00.** When the result itself shows the routed provider is free/local (e.g. the selector's `result.data` names a $0 route, or the entry was estimated at $0), a success reporting 0.0 IS the actual cost — book 0.0, not the estimate. See `skills/meta/checkpoint-protocol.md` → Cost Ledger Governance for the shared rules.

`user_approved=True` is for approved-plan work only — omit it for anything outside what the user approved at the idea gate (a bed for a clip that was not in the approved deliverable mix); that call should hit the single-action guard like any unplanned spend, which is the guard working as intended. Surface a tripped guard as a structured blocker per AGENT_GUIDE.md → "Escalate Blockers Explicitly." If a reservation is made but the call never runs (the hero sample is rejected), call `tracker.refund(entry_id)`. Free/local tools (`subtitle_gen`, `audio_enhance`) still get the same round-trip with `0.0` — one batched entry per logical batch, e.g. `tracker.estimate("subtitle_gen", "subtitles x 6 clips + companion", 0.0)` — so every entry lands in a terminal state before compose.

### 2. Treat Topic Graphics As Optional

Generated graphics should support the batch, not dominate it. Use them only when:

- the topic truly benefits from a clarifying image,
- the episode companion needs chapter separation,
- the budget can support consistent outputs.

### 3. Use Templates, Not Reinvention

Prefer reusable templates for:

- speaker cards,
- quote cards,
- end cards,
- brand containers.

### 4. Store Rich Asset Truth In Metadata

Recommended metadata keys:

- `speaker_assets`
- `subtitle_assets`
- `quote_card_assets`
- `topic_graphics`
- `music_assets`

### 5. Quality Gate

- all clips have subtitle assets,
- speaker identity is visually consistent,
- quote-card text remains mobile-readable,
- optional generated art stays within budget and style constraints.

### Mid-Production Fact Verification

If you encounter uncertainty during asset generation:
- Use `web_search` to verify visual accuracy of subjects (e.g. what does this building actually look like?)
- Use `web_search` to find reference images before generating illustrations
- Log verification in the decision log: `category="visual_accuracy_check"`

Visual accuracy matters. If the script mentions a specific place, person, or object,
verify what it actually looks like before generating images. Don't rely on
the AI model's training data — it may be wrong or outdated.

## Common Pitfalls

- Spending budget on optional art before subtitles and attribution assets are complete.
- Creating inconsistent speaker cards across the same episode.
- Overproducing topic graphics for long-form companion videos.


## When You Do Not Know How

If you encounter a generation technique, provider behavior, or prompting pattern you are unsure about:

1. **Search the web** for current best practices — models and APIs change frequently, and the agent's training data may be stale
2. **Check `.agents/skills/`** for existing Layer 3 knowledge (provider-specific prompting guides, API patterns)
3. **If neither helps**, write a project-scoped skill at `projects/<project-name>/skills/<name>.md` documenting what you learned
4. **Reference source URLs** in the skill so the knowledge is traceable
5. **Log it** in the decision log: `category: "capability_extension"`, `subject: "learned technique: <name>"`

This is especially important for:
- **Video generation prompting** — models respond to specific vocabularies that change with each version
- **Image model parameters** — optimal settings for FLUX, GPT Image, Imagen differ and evolve
- **Audio provider quirks** — voice cloning, music generation, and TTS each have model-specific best practices
- **Remotion component patterns** — new composition techniques emerge as the framework evolves

Do not rely on stale knowledge. When in doubt, search first.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.
