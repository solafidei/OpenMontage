# VEO 3.1 — Prompting Guide

> Source: [Vertex AI Video Gen Prompt Guide](https://cloud.google.com/vertex-ai/generative-ai/docs/video/video-gen-prompt-guide)
> Status (2026-09): Veo 2 / 3.0 (`veo-2.0-generate-001`, `veo-3.0-generate-001`, `veo-3.0-fast-generate-001`) shut down 2026-06-30. Live ids: `veo-3.1-generate-preview` / `veo-3.1-fast-generate-preview` / `veo-3.1-lite-generate-preview` (Gemini API), `veo-3.1-generate-001` / `veo-3.1-fast-generate-001` (Vertex GA; `veo-3.1-lite-generate-001` announced 2026-04, launch stage unverified), and on fal.ai `fal-ai/veo3.1`, `fal-ai/veo3.1/fast`, `fal-ai/veo3.1/lite`. In `veo_video`, `model_variant` takes the bare variant — `veo3.1`, `veo3.1/fast` or `veo3.1/lite` (the tool prepends `fal-ai/` itself, so never pass the prefix). `veo3.1/lite` is wired on both backends (Gemini `veo-3.1-lite-generate-preview` / Vertex `veo-3.1-lite-generate-001`), priced at its own lite tier by `estimate_cost`, and rejected with a clear error for `resolution="4k"` and `reference_to_video`, which fal does not publish for lite. Limits: 4 / 6 / 8 s (8 s required for 1080p, 4K, or reference images), `veo_video` defaults `resolution` to **1080p** (fal's own endpoint default is 720p) — and 1080p/4K force duration to 8 s, silently coerced when `auto_fix` is left on, so pass `resolution="720p"` explicitly for a 4 s or 6 s clip; 720p, 1080p, 4K (not lite), 16:9 or 9:16, native audio (`generate_audio`, default true), `negative_prompt`, up to 3 reference images, extension +7 s per step (model-level capability per Google's docs — up to 20 steps, 720p only, standard and fast only — NOT exposed by `veo_video`: the operation enum has no extend entry). Per-second price — Gemini API: standard $0.40 (720p/1080p) and $0.60 (4K); fast $0.10 / $0.12 / $0.30; lite $0.05 (720p) and $0.08 (1080p). fal.ai, audio on (audio off): standard $0.40 ($0.20) at 720p/1080p and $0.60 ($0.40) at 4K; fast $0.15 ($0.10) at 720p/1080p and $0.35 ($0.30) at 4K; lite $0.05 ($0.03) at 720p and $0.08 ($0.05) at 1080p. Google now recommends Gemini Omni Flash as the default video model; choose Veo 3.1 for last-frame control or legacy pipelines.
> For universal vocabulary, see: `skills/creative/video-gen-prompting.md`

**Word count:** VEO 3.1 sweet spot is 100–250 words; longer prompts stop helping.

## VEO-Specific 14-Component Structure

VEO responds to the most comprehensive prompt structure of any model:

1. **Subject** — who/what the action revolves around
2. **Action** — movements, interactions, expressions
3. **Scene / Context** — location, time, weather, period
4. **Camera Angles** — shot type and perspective
5. **Camera Movements** — dynamic motion
6. **Lens / Optical Effects** — how the camera "sees"
7. **Lighting** — source, direction, quality
8. **Tone / Mood** — emotional register
9. **Artistic Style** — photorealistic, cinematic, animation, art movement
10. **Ambiance** — color palettes, atmospheric effects, textures
11. **Temporal Elements** — pacing, time flow, rhythm
12. **Audio** — sound effects, ambient, dialogue (VEO 3.1 generates dialogue natively; keep `generate_audio=true`)
13. **Cinematic Terms** — editing techniques (match cut, montage, split diopter)
14. **Negative Prompt** — what to exclude

## VEO-Specific Strengths

- **Dialogue generation**: VEO 3.1 natively generates character speech. Write dialogue naturally.
- **Audio integration**: Ambient sound, music, and voice are generated together with video.
- **Negative prompts**: Explicitly supported — "no text overlays, no watermarks, no lens flare"
- **Editing vocabulary**: Understands "match cut", "jump cut", "montage", "split diopter" as prompt terms.

### Camera vocabulary VEO honors literally

VEO 3.1 distinguishes the three camera-motion families and treats their tokens as separate primitives. Mixing them up (e.g. asking for a "zoom" when you mean a "dolly") will produce the wrong move.

- **Translation (rig physically moves):** `dolly` (in/out along the lens axis), `truck` (left/right laterally), `pedestal` (up/down vertically)
- **Rotation (rig stays put, camera rotates):** `pan` (yaw, left/right), `tilt` (pitch, up/down), `roll` (Dutch / Z-axis)
- **Lens-only (rig and body don't move):** `zoom` (focal length change), `rack focus` / `pull focus` / `focus tracking` (focal-plane change)

dolly ≠ zoom; pan ≠ truck. VEO follows whichever token leads.

## VEO Lens Effects (Unique)

VEO specifically responds to optical effects most models ignore:

| Effect | Prompt Language |
|--------|----------------|
| **Rack focus** | "rack focus from foreground flower to background figure" (snap shift) |
| **Pull focus** | "slow pull focus from the candle in the foreground to the doorway behind" (gradual, slower than rack) |
| **Focus tracking** | "focus tracks the runner as she crosses frame; background stays soft" (focus follows a moving subject) |
| **Dolly zoom (vertigo)** | "vertigo effect as character realizes the truth" |
| **Fisheye** | "fisheye lens distortion, skatepark POV" |
| **Anamorphic lens flare** | "anamorphic lens flare streaking horizontally from setting sun" |

These three focus modes (rack, pull, tracking) are different — VEO 3.1 honors the distinction per the paper.

## VEO Art Movement References

VEO responds well to specific art movements as style anchors:
- "Van Gogh-inspired swirling sky"
- "Surrealist Dalí-esque melting landscape"
- "Art Deco geometric patterns in the architecture"
- "Bauhaus clean lines and primary colors"
- "Gritty graphic novel illustration style"
- "Chinese ink wash painting animation"

## Subtitle Prevention

VEO may add subtitles by default for dialogue. To prevent:
- Add to negative prompt: "no subtitles, no captions, no text overlays"

## Example

```
Subject: A lone astronaut in a weathered white spacesuit
Action: Slowly turns to face the camera, visor reflecting a dying star
Scene: Surface of a barren moon, cracked grey terrain, massive ringed
       planet filling the horizon
Camera: Low-angle medium shot, slow arc around subject
Lens: Wide-angle, deep focus keeping both astronaut and planet sharp
Lighting: Harsh rim light from the star behind, cool blue fill from
          planet reflection, no atmosphere diffusion
Mood: Awe, isolation, quiet grandeur
Style: Photorealistic sci-fi cinematography, IMAX-scale
Audio: Breathing inside helmet, faint radio static, low rumble
Negative: No text, no HUD overlay, no lens flare
```
