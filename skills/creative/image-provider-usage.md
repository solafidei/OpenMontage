# Image Provider Usage for OpenMontage

> How to choose between image generation and stock providers, and how to use each effectively.
> Supplements the existing `image-gen-usage.md` (which covers FLUX prompting in depth).

## Provider Landscape

### Generation Providers (AI creates the image)

| Tool | Provider | Cost | Speed | Best For |
|------|----------|------|-------|----------|
| `flux_image` | FLUX via fal.ai (`model` enum: `flux-pro/v1.1` = FLUX 1.1 [pro], the default; `flux/dev`; `flux/schnell`; `flux-2-pro` = FLUX.2 [pro]; `flux-2`; legacy `flux-pro`) | Per output megapixel, rounded up (1024x1024 = 1 MP, 1920x1080 = 2 MP): $0.04 flux-pro/v1.1, $0.025 flux/dev, $0.003 flux/schnell, $0.03 first MP + $0.015 per extra MP flux-2-pro, $0.012 flux-2, $0.05 legacy flux-pro | ~5-10s | Photorealism, general purpose, workhorse |
| `grok_image` | Grok Imagine Image (xAI) | $0.02/output + $0.002/input edit image | ~5-15s | Image edits, style transfer, multi-image compositing |
| `openai_image` | GPT Image 2 (OpenAI) | ~$0.01-0.21 | ~5-15s | Complex instructions, text in images, multi-element |
| `recraft_image` | Recraft V4 via fal.ai (`model` v4 → `fal-ai/recraft/v4/text-to-image`, v4-pro → `fal-ai/recraft/v4/pro/text-to-image`; `style="vector_illustration"` routes to `fal-ai/recraft/v4[/pro]/text-to-vector` and returns real SVG; Recraft V4.1 `fal-ai/recraft/v4.1/*`, published 2026-05-14, exists on fal but the tool never calls it) | $0.04 (V4), $0.25 (V4 Pro) per raster image; SVG via `text-to-vector` $0.08 (V4), $0.30 (V4 Pro) | ~5-10s | Logos, brand assets, text rendering; SVG only via the text-to-vector endpoints (see caveat below) |
| `google_imagen` | Google Gemini image models via the Gemini API. Live: Nano Banana 2 `gemini-3.1-flash-image` (tool default), Nano Banana 2 Lite `gemini-3.1-flash-lite-image`, Nano Banana Pro `gemini-3-pro-image`. The legacy `imagen-4.0-*` ids shut down on the Gemini API 2026-08-17 and `gemini-2.5-flash-image` shuts down 2026-10-02 — do not plan on them | ~$0.045-0.15 (NB2, by resolution), ~$0.034 (NB2 Lite, 1K only), ~$0.13-0.24 (NB Pro) | ~5-15s | Multi-reference consistency (up to 14 refs), multi-turn edits, 21:9 and 4K output, search-grounded imagery |
| `local_diffusion` | Stable Diffusion (local) | Free | ~30s+ | Offline, privacy, free |
| `image_gen` | Multi (legacy, deprecated) | Varies | Varies | **Deprecated** — use `image_selector` or per-provider tools |

### Stock Providers (search and download existing images)

| Tool | Provider | Cost | Speed | Best For |
|------|----------|------|-------|----------|
| `pexels_image` | Pexels | Free | ~2-5s | High-quality photography, color filtering |
| `pixabay_image` | Pixabay | Free | ~2-5s | Large library, category filtering, illustrations |

### Selector

| Tool | Purpose |
|------|---------|
| `image_selector` | Routes to the best available provider based on preference and availability |

## Provider Selection by Scene Type

| Scene Type | Primary Provider | Why | Fallback |
|-----------|-----------------|-----|----------|
| **Real-world photo** (city, nature, people) | `pexels_image` | Real photos > AI for realism | `pixabay_image` → `flux_image` |
| **Technical diagram** | `diagram_gen` | Structured, editable | `flux_image` with diagram prompt |
| **Abstract/conceptual illustration** | `flux_image` | AI excels at custom concepts | `openai_image` |
| **Style transfer / repaint of an existing image** | `grok_image` | Native edit flow, strong promptable transforms | `openai_image` |
| **Multi-image merge / composite** | `grok_image` | Can combine multiple source images into one scene | `openai_image` |
| **Logo or brand asset** | `recraft_image` | SVG support, text accuracy | `openai_image` |
| **Image with text/labels** | `openai_image` | Best text rendering (GPT Image 2) | `recraft_image` |
| **Complex multi-element composition** | `openai_image` | Best instruction following | `flux_image` |
| **Hero image (key visual)** | `flux_image` | Highest visual quality | `openai_image` |
| **Thumbnail** | `flux_image` or `recraft_image` | Needs to be eye-catching | — |
| **Budget/free project** | `pexels_image` or `pixabay_image` | Free, immediate | `local_diffusion` |
| **Offline/air-gapped** | `local_diffusion` | No network needed | — |

## Provider-Specific Caveats

### Recraft V4 via fal.ai
- **`style` is not a fal input** — `fal-ai/recraft/v4/text-to-image` and `fal-ai/recraft/v4/pro/text-to-image` accept only `prompt`, `image_size`, `colors`, `background_color` and `enable_safety_checker`, with no `style` property at all (this caused 422 errors when first seen in 2026-04). `recraft_image` no longer forwards `style` to fal, so passing any value (`digital_illustration`, `realistic_image`, …) is safe and cannot 422 the request. **Workaround for styling:** encode style direction in the prompt text instead (e.g. "digital illustration of a tooth cross-section" rather than `style="digital_illustration"`). The one exception is `style="vector_illustration"`, which `recraft_image` uses to select the separate `fal-ai/recraft/v4/text-to-vector` endpoint ($0.08; V4 Pro `fal-ai/recraft/v4/pro/text-to-vector` $0.30) and genuinely returns SVG. The `image_size` and `colors` parameters work fine.
- **Text rendering is unreliable for exact business names.** Recraft (like all AI image models) may hallucinate wrong text. For any scene where text must be verbatim (CTA screens, business names, phone numbers), use Remotion `text_card` instead of generating an image with text.

## Cost-Quality Tradeoff

```

PRODUCTION PATH: Premium
├── Hero images: flux_image flux-pro/v1.1 ($0.04/MP -> ~$0.04 at 1024x1024, ~$0.08 at 1920x1080)
├── Supporting visuals: flux_image flux/dev ($0.025/MP -> ~$0.03/img at 1 MP)
├── Text overlays: openai_image ($0.05/img medium)
├── B-roll stills: pexels_image ($0.00)
└── Total for 10 images: ~$0.35-0.50 (rises with hero pixel count)

PRODUCTION PATH: Standard
├── All generated: flux_image flux/dev ($0.025/MP -> ~$0.03/img at 1 MP)
├── B-roll stills: pexels_image ($0.00)
└── Total for 10 images: ~$0.25

PRODUCTION PATH: Budget
├── All stock: pexels_image + pixabay_image ($0.00)
├── Diagrams: diagram_gen ($0.00)
└── Total: $0.00

PRODUCTION PATH: Offline
├── All generated: local_diffusion ($0.00)
├── Diagrams: diagram_gen ($0.00)
└── Total: $0.00 (but slower, lower quality)
```

Use `generation_mode="edit"` when the task starts from an existing image and should route only to edit-capable providers.

## Using the Image Selector

For most cases, use `image_selector` and let it route:

```python
# The selector finds the best available provider
result = image_selector.execute({
    "prompt": "aerial view of a modern data center",
    "preferred_provider": "auto",  # or "flux", "pexels", etc.
    "output_path": "assets/images/scene-3.png"
})
```

Override with `preferred_provider` when you know which provider is best for the scene type.
Use `allowed_providers` to restrict to free or local options:

```python
# Budget mode: only free providers
result = image_selector.execute({
    "prompt": "server room interior",
    "allowed_providers": ["pexels", "pixabay", "local_diffusion"],
    "output_path": "assets/images/scene-3.jpg"
})
```

## Consistency Across Mixed Sources

When mixing stock and generated images in the same video, visual consistency is the challenge.

### Strategy: Color Grade Everything
Apply the playbook's color grading LUT to both stock and generated images in the compose stage.
This unifies the look. The `color_grade` enhancement tool handles this.

### Strategy: Match The Visual Identity, Not A Copied Prefix
When generating images, adapt the playbook's mood, palette, texture, and medium
into a short scene-specific anchor. When searching stock, filter for the same
emotional and visual qualities: color, lighting, environment, composition, era,
and texture. Use the playbook as a consistency source, not a script to paste.

### Strategy: Avoid Mixing Styles Within a Scene
Don't use a stock photo for one element and an AI illustration for another in the same scene.
Keep each scene internally consistent — all stock or all generated.
