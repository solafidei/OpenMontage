---
name: minimax-h3
description: |
  Generate MiniMax H3 (Hailuo 3.0) video through the official MiniMax v2 API, fal.ai, Atlas Cloud, Runway, ComfyUI Partner Nodes, or local open weights in ComfyUI. Use for 5-15 second clips at 480P/768P/2K/4K on fal (2K default), 4-15 s at 768P/2K on Atlas Cloud (2K default), and 4-15 s 2K-only on the first-party v2 API, first/last-frame animation, and image/video/audio reference-conditioned video.
---

# MiniMax H3

MiniMax H3 is the Hailuo 3.0 family. The first-party API identifier is
`MiniMax-H3`; fal.ai's catalog id is `minimax/h3` (`minimax/h3/{text,image,reference}-to-video`).
`minimax_fal_video` calls that catalog id directly (480P/768P native, 2K default and 4K
upscaled from 768P); the older `fal-ai/minimax/hailuo-03/*` path is an unlisted legacy alias
that still resolves but is no longer called by the tool. Runway uses `hailuo3`. Do not
substitute one provider's identifier into another API.

## Choose a route

| Route | Tool call | Execution |
|-------|-----------|-----------|
| MiniMax direct | `minimax_video`, `model: "MiniMax-H3"` | Hosted first-party v2 API; global or mainland-China region |
| fal.ai | `minimax_fal_video` | Hosted gateway; T2V, I2V, reference-to-video; 5–15 s (integer), 480P/768P native with 2K (default) / 4K upscaled from 768P; reference mode: ≤9 images + ≤3 videos + ≤3 audio clips (≤12 files, video/audio 2–15 s each, ≤15 s combined). $0.05/s 480P, $0.06/s 768P, $0.13/s 2K, $0.16/s 4K; first 5 reference images free then $0.08 each. fal also lists **H3 Max** (`minimax/h3-max/{text,image,reference}-to-video`, 480P/768P/1080P, list $0.05/$0.08/$0.16 per s after the promo ends 2026-09-14) and **H3 Max Turbo** (`minimax/h3-max-turbo/{text,image}-to-video`), neither wrapped yet |
| Atlas Cloud | `atlas_video`, `model: "minimax/h3/{text,image,reference}-to-video"` | Hosted gateway; 4–15 s, 768P/2K (2K default), $0.10/s |
| Runway | `runway_video`, `model: "hailuo3"` | Hosted; 768P or 2K (2K default), 5–15 s; $0.15/s at 2K, $0.10/s at 768P |
| ComfyUI Partner Node | `comfyui_video`, `model_family: "minimax_h3_api"` | Hosted and billed in Comfy credits |
| ComfyUI open weights | `comfyui_video`, `model_family: "minimax_h3_local"` | Local GPU with official workflow and model stack |

For local ComfyUI, export the official workflow in API format and pass
`workflow_json` or `workflow_path` plus `output_node`. OpenMontage reports the
required diffusion model, Qwen3-VL text encoder, video VAE, and audio VAE; it
does not silently download large weights.

## Operations and prompting

- Text-to-video: concrete ratio; do not use `adaptive` without visual input.
- Image-to-video: provide a first frame.
- First/last-frame: provide both images and describe the motion between them.
- Reference-to-video: images, videos, and audio can be combined. Audio needs at
  least one visual reference.

Write prompts as subject + action + camera path + environment + lighting +
audio intent. MiniMax responds well to explicit camera direction. Keep the
requested motion achievable within 4–15 seconds and inspect native audio as
carefully as the image track.

## Provider differences

The direct MiniMax v2 route currently outputs 2K and supports 4–15 seconds.
fal.ai's `minimax/h3` route accepts 5–15 seconds and 480P/768P natively (its 2K default
and 4K are upscales of a 768P base). Runway's Hailuo 3.0 route supports 768P/2K and
documents 5–15 seconds. Partner
Nodes require network access and credits. Only the open-weight ComfyUI route is
local/offline after all models are installed.
