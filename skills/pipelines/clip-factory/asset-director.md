# Asset Director - Clip Factory Pipeline

## When To Use

This stage builds the shared visual and audio kit for the entire clip batch. The key is reuse, not bespoke design per clip.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/asset_manifest.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["scene_plan"]["scene_plan"]`, `state.artifacts["script"]["script"]`, `state.artifacts["idea"]["brief"]` | Clip plans and rankings |
| Tools | `subtitle_gen`, `audio_enhance` | Batch-ready subtitles and audio cleanup |
| Cost tracker | `tools/cost_tracker.py` — `CostTracker.for_project(project_id)` | Reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea director already wrote to |
| Playbook | Active style playbook | Subtitle and overlay consistency |

## Process

### 1. Build Shared Assets First

Prefer reusable assets over per-clip reinvention:

- one subtitle style system,
- one hook text treatment,
- one lower-third treatment,
- one watermark / brand frame,
- one CTA / end-tag treatment if needed.

### 1b. Hero Scene Sample (Mandatory)

Before batch asset generation:
1. Identify the hero scene (the visual peak of the batch)
2. Generate ONE sample visual asset for that scene
3. Present it: "This is the visual direction for the most important clip. Does this match what you're imagining? I'll generate the rest in this style."
4. Wait for approval before proceeding to batch generation

This prevents the most expensive mistake: generating 10+ assets in a direction the user doesn't like.

### 1c. Ledger Discipline For Every Paid Call

Open the project's tracker once — `tracker = CostTracker.for_project(project_id)` reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea director and every other stage share. Every tool this stage runs (`subtitle_gen`, `audio_enhance`) is local and prices $0.00, and every one of them still gets the full estimate → reserve → reconcile round trip. The lightening on this pipeline is in the DATA, not the protocol: book **one entry per tool batch across the whole clip set**, never one per clip.

```python
# ONE entry for the whole subtitle batch — not one per clip.
inputs = {"segments": clip_segments, "format": "srt", "output_path": subtitle_dir}
estimated_usd = subtitle_gen.estimate_cost(inputs)          # 0.0 — local tool
entry_id = tracker.estimate("subtitle_gen", "subtitles x 12 clips", estimated_usd)
tracker.reserve(entry_id, user_approved=True)  # this batch fulfills the plan approved at idea

result = run_subtitle_batch(inputs)   # the whole batch, all clips

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

**Known-free routes book $0.00.** When the result itself shows the routed provider is free/local (e.g. the selector's `result.data` names a $0 route, or the entry was estimated at $0), a success reporting 0.0 IS the actual cost — book 0.0, not the estimate. Every tool on this manifest is such a route, so every entry here reconciles at `0.00`. See `skills/meta/checkpoint-protocol.md` → Cost Ledger Governance for the shared rules.

`user_approved=True` is for approved-plan work only — omit it for anything outside what the user approved at the idea gate. That call should hit the single-action guard like any unplanned spend, which is the guard working as intended. Surface a tripped guard as a structured blocker per AGENT_GUIDE.md → "Escalate Blockers Explicitly." If a reservation is made but the batch never runs (hero sample rejected), call `tracker.refund(entry_id)`. A batch that fails outright still reconciles — with `success=False` — so no entry reaches compose in `estimated`/`reserved` state.

### 2. Generate Per-Clip Subtitles

Each approved clip needs its own subtitle asset, timed from clip start rather than source start. This timestamp rebasing is critical.

Store clip-relative timing details in `asset_manifest.metadata.subtitle_map`.

### 3. Normalize Audio Consistently

Use `audio_enhance` across the clip set so the batch feels like one series:

- similar loudness,
- similar noise floor,
- similar vocal clarity.

### 4. Keep Hook Assets Lightweight

Most hook overlays should be text-first and template-based. Do not spend time or budget generating bespoke art unless the batch truly benefits.

### 5. Use Metadata For Batch Structure

Recommended metadata keys:

- `shared_assets`
- `subtitle_map`
- `audio_profile`
- `clip_asset_index`
- `style_tokens`

### 6. Quality Gate

- every clip has subtitles,
- every clip has a clean audio asset or verified source audio path,
- shared assets are referenced consistently,
- the asset count stays practical for the batch size.

### Mid-Production Fact Verification

If you encounter uncertainty during asset generation:
- Use `web_search` to verify visual accuracy of subjects (e.g. what does this building actually look like?)
- Use `web_search` to find reference images before generating illustrations
- Log verification in the decision log: `category="visual_accuracy_check"`

Visual accuracy matters. If the script mentions a specific place, person, or object,
verify what it actually looks like before generating images. Don't rely on
the AI model's training data — it may be wrong or outdated.

## Common Pitfalls

- Forgetting to rebase subtitle timing per clip.
- Overdesigning hook assets so the batch becomes inconsistent.
- Normalizing some clips and not others.
- Treating a 10-clip batch like 10 unrelated projects.


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
