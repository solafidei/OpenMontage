---
name: gemini-omni
description: |
  Generate and conversationally edit short videos with Google Gemini Omni Flash (`gemini-omni-1.1-flash`; the original preview id `gemini-omni-flash-preview` shuts down 2026-09-30). Use when: (1) iterating on a clip with natural-language edits instead of regenerating ("make the phone invisible, keep everything else the same"), (2) generating 3-10s clips at 360p-4K (720p default; the model's `extend` task reaches 40s, but `gemini_omni_video` does not expose it yet) with synthesized audio, rendered on-screen text, or timecoded beats, (3) binding reference images to roles with <FIRST_FRAME>/<LAST_FRAME>/<IMAGE_REF_N> prompt tags, (4) editing an existing uploaded video. Accessed via the `gemini_omni_video` tool using the project's GEMINI_API_KEY/GOOGLE_API_KEY — the same key as `google_imagen` (Gemini image models; Imagen 4 shut down 2026-08-17) and Google TTS.
allowed-tools: Bash, Read, Write
metadata:
  openclaw:
    requires:
      env_any:
        - GEMINI_API_KEY
        - GOOGLE_API_KEY
---

# Gemini Omni Flash (Google DeepMind)

Gemini Omni is Google DeepMind's video generation **and editing** model family, announced at I/O 2026. The current model, **Gemini Omni Flash** (`gemini-omni-1.1-flash`, stable since 2026-08-27), generates 3-10 second clips at 24fps in 360p, 720p (default), 1080p or 4K (1080p/4K are upscaled) with synthesized audio via the Gemini **Interactions API** (`video_config` tasks: text_to_video, image_to_video, reference_to_video, edit, extend; extension adds 3-10 s per step up to 40 s total). The original `gemini-omni-flash-preview` (developer access June 30, 2026) is deprecated and **shuts down 2026-09-30** — do not pin it. Its differentiator in the OpenMontage fleet is **stateful conversational editing**: each generation returns an `interaction_id`, and a follow-up call with `previous_interaction_id` edits that video in place — no other wrapped provider can refine a clip without regenerating it.

OpenMontage wraps it as `gemini_omni_video` (native Gemini API, no gateway). It shares `GOOGLE_API_KEY`/`GEMINI_API_KEY` with `google_imagen` and `google_tts` — one key, three capabilities. Paid tier only: $1.50/1M input tokens and $17.50/1M video output tokens; Google publishes only the 720p rate (5,792 output tokens per second of 720p video ≈ $0.10/s). 360p, 1080p and 4K bill by their own token counts, which Google's pricing page does not list — the only published per-resolution ladder is fal's for the same model ($0.03 / $0.10 / $0.15 / $0.30 per second at 360p / 720p / 1080p / 4K), so treat non-720p Google costs as unquoted.

Other documented routes are available when the direct Google key is not the
chosen provider:

| Route | OpenMontage call | Important limitation |
|-------|------------------|----------------------|
| fal.ai | `gemini_omni_fal` | T2V, I2V, reference video, and edit endpoints; no Google interaction ID is returned. The tool calls **Gemini Omni Flash 1.1**'s `google/gemini-omni-flash/v1.1/{text-to-video,image-to-video,reference-to-video,edit}` endpoints (published 2026-08-27), billed per second of output by resolution — $0.03 / $0.10 / $0.15 / $0.30 at 360p / 720p / 1080p / 4k — and carries `reference_video_urls` (up to 3 clips, ≤3s each) on the reference-to-video endpoint. The legacy unversioned `google/gemini-omni-flash/*` endpoints (token-billed, ≈$0.125-0.13/s at 720p) back the preview model that retires 2026-09-30 and are no longer used here |
| Runway | `runway_video`, `model: "gemini_omni_flash"` | T2V/I2V/V2V; video edits accept up to five image references |
| ComfyUI Partner Node | `comfyui_video`, `model_family: "gemini_omni_flash"` | Hosted paid node; requires network, Comfy login, and credits |

Use the direct `gemini_omni_video` route for stateful conversational editing.
Gateway routes return ordinary provider tasks and cannot preserve Google's
`previous_interaction_id` workflow. The fal edit endpoint can still be iterated
by feeding each output video URL into the next edit call.

## When to pick it (and when not)

| Use it for | Prefer another provider for |
|---|---|
| Iterative refinement — generate, review, then edit the same clip in layers | One-shot cinematic hero clips (→ Seedance 2.0, see `seedance-2-0`) |
| Editing an existing/uploaded clip (restyle, add/remove objects, change text) | Clips longer than 10s per generation (the model's `extend` task reaches 40s in 3-10s steps, but `gemini_omni_video` does not expose it yet), or native (non-upscaled) 1080p/4K |
| On-screen rendered text and word-by-word text beats | Seed-reproducible generations (no seed support) |
| Reference-image-bound subjects/styles and first/last-frame pinning via prompt tags (`<FIRST_FRAME>`, `<LAST_FRAME>`, `<IMAGE_REF_N>`) | Reference-video inputs via `gemini_omni_video` (`<VIDEO_REF_N>`: the model takes up to three ≤3s clips, but `gemini_omni_video` takes images only — use `gemini_omni_fal`'s `reference_video_urls` input instead) and scene extension (the model's `extend` task and Veo 3.1's 20 × 7s extensions are exposed by neither `gemini_omni_video` nor `veo_video`; for a single clip over 10s → `seedance_video` or `kling_video`) |
| Timecode-scheduled multi-beat clips from one prompt | Non-English narration (English only fully supported) |

Route through `video_selector` for generation operations. **Editing (`edit_video`) is a direct-tool operation** — call `gemini_omni_video` from the registry, because the multi-turn interaction state lives outside the selector's model.

## Generation prompting

Describe **scene + camera + lighting + motion + audio**. Official example:

> Continuous, unbroken handheld shot of a fluffy tabby cat sitting on a sunny windowsill, looking out into a leafy garden. The cat's tail twitches slowly, and its ears rotate slightly toward ambient noises. Sunbeams illuminate dust motes in the air.

- **Force a single shot** explicitly: "In a single continuous shot," / "No scene cuts." Otherwise the model may cut between scenes.
- **Negatives go in prose** — there is no `negative_prompt` parameter: "No dialogue," "No extra sound effects."
- **No sampler controls**: system instructions, temperature, top_p, and seeds are all unsupported. The prompt is the only lever.
- **Meta-prompt for quality**: "Consider micro-detail, expression and timing to create a very rich, detailed but entirely natural scene."

### Timecode syntax

Schedule beats with bracketed ranges or natural language — this maps directly onto OpenMontage scene-plan timings:

```
[0-3s] A person is walking [3-6s] They stop and turn around
```

> "After 3 seconds, a woman enters the scene." / "At 5s the chorus starts in the background audio."

### Audio and on-screen text

Audio is synthesized automatically; direct it in the prompt: "Include calm background music," "The audio is a low tinny radio broadcast in the background." Rendered text works and can be timed:

> One word on the screen at a time: 'did, you, know, that, Omni, can, do, awesome, text?' Each word appears for 1s.

## Reference images (`<FIRST_FRAME>` / `<IMAGE_REF_N>` tags)

Pass local images via `reference_image_paths` (they are sent in order), then bind them to roles **inside the prompt** with tags. `<IMAGE_REF_N>` indexes from 0 in the order supplied:

```
in the style of <IMAGE_REF_0> a woman <IMAGE_REF_1> is walking
```

```
[0-3s] A studio fashion sequence. Starting with woman <IMAGE_REF_0>, she is
holding <IMAGE_REF_1> [3-6s] Then we see the man <IMAGE_REF_2> holding <IMAGE_REF_3>
```

- `<FIRST_FRAME>` makes an image the opening frame: `<FIRST_FRAME> a woman is walking`.
- `<LAST_FRAME>` pins the closing frame to transition to and **must be used together with `<FIRST_FRAME>`** — supply that image in `reference_image_paths` like any other reference.
- `<VIDEO_REF_N>` binds a reference video as a character/object likeness (up to three, each ≤3 s; any audio in it is ignored): `the person in <VIDEO_REF_0> is playing the violin`. `gemini_omni_video` takes images only and does not expose this tag; use `gemini_omni_fal`'s `reference_video_urls` input (up to 3 clips, ≤3 s each) on the v1.1 `reference-to-video` endpoint instead.
- Use high-resolution images; describe the intended motion specifically rather than "make it move."
- Say what each image *is* (product / character / style / background reference) — the model decides usage from context.

## Conversational editing (the differentiator)

**Editing prompts are the opposite of generation prompts: short and surgical.** Overly descriptive edit prompts cause unintended changes.

1. Generate the base clip (subject + scene + motion). The tool returns `interaction_id` in its result data.
2. Pass it back as `previous_interaction_id` with `operation="edit_video"` and describe **only the delta**.
3. Append **"Keep everything else the same."** to pin unmentioned elements.
4. Refine in layers — one turn for lighting, one for camera, one for action, one for audio.

Official good/bad pairs:

| Avoid | Instead |
|---|---|
| "In the video of the man sitting on the sofa, please add a small black cat..." | "Add a cat that jumps onto his lap, he begins to pet it. Keep everything else the same." |
| "Please remove the cell phone... and fill in the background so it looks like..." | "Make the phone invisible. Keep everything else the same." |

Other working edit prompts: "Make this video anime" / "Put a fashionable hat on this person" / "Change the lighting to be more dramatic" / "Change the text on the sign to say 'Omni Flash'".

**Gotcha — `store`:** editing via `previous_interaction_id` only works if the *prior* call kept the interaction server-side (`store` defaults to true in `gemini_omni_video`). Set `store=false` only for one-shot generations you will never edit.

**Editing uploaded videos:** pass `input_video_path` instead of `previous_interaction_id`; the tool uploads it via the Files API. Unavailable in the EEA, Switzerland, and the UK (editing *generated* videos works everywhere).

## Hard limitations (`gemini-omni-1.1-flash`, stable since 2026-08-27)

- Output: 3-10s per generation (extendable in 3-10s steps to 40s total), 360p / 720p (default) / 1080p / 4K (1080p and 4K are upscaled), 24fps, MP4 with audio, delivered inline as base64 by default (videos under 4MB) or via `delivery="uri"` for larger payloads; aspect ratio `16:9` or `9:16`. All output carries an invisible SynthID watermark.
- No seed, negative prompt, temperature, top_p, or system instructions.
- No voice editing. The model's `extend` task (3-10s per step, 40s total) exists but only appends to the end of a clip, and `<FIRST_FRAME>`/`<LAST_FRAME>` (which must be used together) pin the opening/closing frames — there is no Veo-style 20-step extension. `gemini_omni_video` exposes no `extend` operation yet (enum: text_to_video, image_to_video, reference_to_video, edit_video).
- Audio reference inputs unsupported. The model accepts up to three reference videos of ≤3s each (`<VIDEO_REF_N>`, likenesses only, their audio ignored); `gemini_omni_video` takes images only and does not carry them, but `gemini_omni_fal` does via its `reference_video_urls` input on the v1.1 `reference-to-video` endpoint. Input videos for edit/extend must be ≤10s when uploaded.
- Referencing or reasoning across multiple videos is unsupported; multi-video prompting may degrade output.
- English fully supported; other languages untested.
- Images of minors (EEA/CH/UK) and certain recognizable people are blocked for upload/editing.

## Sources

- Generation & editing guide: https://ai.google.dev/gemini-api/docs/omni
- Model card: https://ai.google.dev/gemini-api/docs/models/gemini-omni-flash
- Pricing: https://ai.google.dev/gemini-api/docs/pricing
- Announcement: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-omni/
