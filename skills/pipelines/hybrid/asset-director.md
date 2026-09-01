# Asset Director - Hybrid Pipeline

## When To Use

This stage prepares the support kit around the anchor edit: subtitles, diagrams, generated inserts, narration, music, and reusable overlay systems.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/asset_manifest.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["scene_plan"]["scene_plan"]`, `state.artifacts["script"]["script"]`, `state.artifacts["idea"]["brief"]` | Support needs and variant plan |
| Tools | `subtitle_gen`, `tts_selector`, `image_selector`, `video_selector`, `diagram_gen`, `code_snippet`, `music_gen`, `audio_enhance` — selectors auto-discover all available providers from the registry | Optional support asset production |
| Cost tracker | `tools/cost_tracker.py` — `CostTracker.for_project(project_id)` | Reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea director already wrote to |
| Playbook | Active style playbook | Consistency rules |

## Process

### 1. Build Shared Support Assets First

Start with reusable systems:

- subtitle treatment,
- lower-third or label system,
- stat-card system,
- CTA container,
- diagram style.

### 1b. Sample Preview (Prevents Wasted Spend)

Before batch-generating support assets, produce one sample of each expensive generated type and show the user:

1. **TTS sample** (if narration is needed): Generate one section. Confirm voice and tone before batching.
2. **Image/video sample** (if generating inserts): Generate one representative visual. Confirm style fits the source footage before batching.

If rejected, adjust parameters and retry (max 3 iterations). Do not batch until approved.

### 1c. Ledger Discipline For Every Paid Call

Open the project's tracker once — `tracker = CostTracker.for_project(project_id)` reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea director and every other stage share. For every paid support-asset call (`tts_selector`, `image_selector`, `video_selector`, `music_gen`, ...), run the full estimate → reserve → reconcile round trip:

```python
inputs = {"prompt": prompt, "provider": provider}
estimated_usd = image_selector.estimate_cost(inputs)
entry_id = tracker.estimate("image_selector", "diagram_insert_2", estimated_usd)
tracker.reserve(entry_id, user_approved=True)  # this call fulfills a line item approved at idea

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
    # budget_spent_usd counts FAILED entries as well as completed ones
    # (CostTracker.budget_spent_usd), so a substituted estimate is phantom
    # spend that shrinks usable budget and can block the real retry in cap
    # mode.
    actual_usd = reported
tracker.reconcile(entry_id, actual_usd, success=result.success)
```

**Known-free routes book $0.00.** When the result itself shows the routed provider is free/local (e.g. the selector's `result.data` names a $0 route, or the entry was estimated at $0), a success reporting 0.0 IS the actual cost — book 0.0, not the estimate. See `skills/meta/checkpoint-protocol.md` → Cost Ledger Governance for the shared rules.

`user_approved=True` is for approved-plan work only — omit it for anything outside what the user approved at the idea gate; that call should hit the single-action guard like any unplanned spend, which is the guard working as intended. Surface a tripped guard as a structured blocker per AGENT_GUIDE.md → "Escalate Blockers Explicitly." If a reservation is made but the call never runs (sample rejected), call `tracker.refund(entry_id)`. Free/local tools (`diagram_gen`, `code_snippet`, `subtitle_gen`) still get the same round-trip with `0.0` so every entry lands in a terminal state before compose.

### 2. Generate Only The Support Assets You Need

Support assets should fill identified needs from the script and scene plan, not speculative possibilities.

### 3. Preserve Anchor Truth

Keep the metadata clear about which assets are:

- source-derived,
- provided,
- recorded,
- generated.

### 4. Use Metadata For The Support Map

Recommended metadata keys:

- `shared_support_assets`
- `scene_asset_index`
- `source_vs_generated_map`
- `variant_assets`

### 5. Quality Gate

- support assets map to real narrative needs,
- reusable kits are present,
- source and generated assets are clearly separated,
- every referenced file exists.

### Mid-Production Fact Verification

If you encounter uncertainty during asset generation:
- Use `web_search` to verify visual accuracy of subjects (e.g. what does this building actually look like?)
- Use `web_search` to find reference images before generating illustrations
- Log verification in the decision log: `category="visual_accuracy_check"`

Visual accuracy matters. If the script mentions a specific place, person, or object,
verify what it actually looks like before generating images. Don't rely on
the AI model's training data — it may be wrong or outdated.

## Common Pitfalls

- Overbuilding support assets before the anchor cut is proven.
- Losing track of which assets are generated versus supplied.
- Creating inconsistent overlay systems across one project.


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
