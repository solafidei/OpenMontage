# Asset Director - Localization Dub Pipeline

## When To Use

This stage produces the localized asset kit: translated subtitle files, dubbed audio, optional lip-sync renders, and any language-specific replacements needed for the final outputs.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/asset_manifest.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["scene_plan"]["scene_plan"]`, `state.artifacts["script"]["script"]`, `state.artifacts["idea"]["brief"]` | Language plan and transcript package |
| Tools | `tts_selector`, `subtitle_gen`, `lip_sync`, `audio_enhance` — `tts_selector` auto-discovers all available TTS providers from the registry | Dubbed audio, subtitle, and optional lip-sync production |
| Cost tracker | `tools/cost_tracker.py` — `CostTracker.for_project(project_id)` | Reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea director already wrote to |
| Playbook | Active style playbook | Subtitle and replacement-text rules |

## Process

### 1. Produce Subtitle Assets First

Create the subtitle or caption package for each language. This gives a reviewable fallback even if dubbed-audio generation or lip sync is blocked.

### 1b. Hero Scene Sample (Mandatory)

Before batch asset generation:
1. Identify the hero scene (the visual peak of the video)
2. Generate ONE sample dubbed audio clip for that scene in the target language
3. Present it: "This is the voice direction for the most important scene. Does this match what you're imagining? I'll generate the rest in this style."
4. Wait for approval before proceeding to batch generation

This prevents the most expensive mistake: generating 10+ dubbed assets in a direction the user doesn't like.

### 1c. Ledger Discipline For Every Paid Call

Open the project's tracker once — `tracker = CostTracker.for_project(project_id)` reopens the same `projects/<project_id>/artifacts/cost_log.json` the idea director and every other stage share. `tts_selector` is the only paid tool on this stage; `subtitle_gen`, `lip_sync` and `audio_enhance` are local/free. Every call — paid or free — runs the full estimate → reserve → reconcile round trip.

Book ONE entry per target language, keyed by the PLAN's line-item name (`tts_selector`), never the concrete provider the selector routes to — the provider belongs in the operation string, alongside the locale, so the entry matches the per-language line item armed at the idea gate:

```python
lang = "es"  # repeat this round trip once per target language
inputs = {"text": translated_script_by_language[lang], "language": lang}
estimated_usd = tts_selector.estimate_cost(inputs)
entry_id = tracker.estimate("tts_selector", "dub_es via azure_tts", estimated_usd)
tracker.reserve(entry_id, user_approved=True)  # this call fulfills the per-language dub line item approved at idea

result = tts_selector.execute(inputs)

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

`user_approved=True` is for approved-plan work only — omit it for anything outside what the user approved at the idea gate. **A language added mid-run has no line item at all**, so its first dub call trips the first-paid-use guard: that is the guard working as designed. Do not reserve around it — surface it as a structured blocker per AGENT_GUIDE.md → "Escalate Blockers Explicitly" and take the language back to the idea gate. If a reservation is made but the call never runs (the hero sample is rejected), call `tracker.refund(entry_id)`.

Free/local tools still get the same round trip with `0.0`, batched — one entry per logical batch, not one per artifact: `tracker.estimate("subtitle_gen", "subtitles x 2 locales", 0.0)` and, when lip sync actually runs, `tracker.estimate("lip_sync", "lip_sync x 6 shots", 0.0)`, each reserved and reconciled the same way so no entry reaches compose in `estimated`/`reserved` state.

### 2. Generate Dubbed Audio Per Language

Use the approved translated script package, not raw machine output. Record which voice or synthesis path was used for each language.

### 3. Treat Lip Sync As Optional

Only generate lip-sync assets for scenes and languages that actually need it. If the tool path is blocked, record that and keep the dub-audio path alive.

### 4. Use Metadata For Localization Truth

Recommended metadata keys:

- `subtitle_assets_by_language`
- `dub_audio_assets_by_language`
- `lip_sync_assets_by_language`
- `voice_map`
- `pronunciation_warnings`
- `blocked_assets`

### 5. Quality Gate

- subtitle assets exist,
- dubbed audio assets exist for planned dub outputs,
- lip-sync remains explicitly optional,
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

- Generating dubbed audio before finalizing translation review.
- Treating lip sync as mandatory for every language.
- Failing to record which language asset maps to which voice and subtitle set.


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
