"""Seedance 2.0 and 2.5 (ByteDance) video generation via fal.ai API.

Best for cinematic clips with native audio, director-level camera control,
and lip-sync from quoted dialogue in prompts.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class SeedanceVideo(BaseTool):
    name = "seedance_video"
    version = "0.3.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "seedance"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set FAL_KEY to your fal.ai API key.\n"
        "  Get one at https://fal.ai/dashboard/keys"
    )
    agent_skills = ["seedance-2-0", "seedance-2-5", "ai-video-gen"]

    capabilities = ["text_to_video", "image_to_video", "reference_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "reference_to_video": True,
        "multiple_reference_images": True,
        "reference_image": True,
        "native_audio": True,
        "cinematic_quality": True,
        "camera_direction": True,
        "lip_sync": True,
        "multi_shot": True,
        "aspect_ratio": True,
        "seed": True,
    }
    best_for = [
        "preferred premium video gen when FAL_KEY is available",
        "cinematic trailers, teasers, and high-fidelity clips with native synchronized audio",
        "director-level camera control and multi-shot editing in a single generation",
        "lip-sync from quoted dialogue in prompts",
        "Seedance 2.5 reference generation (up to 30 images + 10 video + 10 audio clips)",
        "consistent character identity across shots",
    ]
    not_good_for = ["offline generation", "budget-constrained projects"]
    fallback_tools = ["veo_video", "kling_video", "minimax_video"]
    # Premium model — beat out "experimental stability" baseline. The scoring
    # engine reads quality_score directly when present (see lib/scoring.py).
    quality_score = 0.95

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video", "reference_to_video"],
                "default": "text_to_video",
            },
            "model_variant": {
                "type": "string",
                "enum": ["standard", "fast", "mini"],
                "default": "standard",
                "description": "standard = highest quality; fast = lower latency and cost; mini = Seedance 2.0 Mini (bytedance/seedance-2.0/mini/*, cheapest tier, 480p/720p, 4-15 s, same 9/3/3 reference caps). fast and mini exist for model_version 2.0 only.",
            },
            "model_version": {
                "type": "string",
                "enum": ["2.0", "2.5"],
                "default": "2.0",
                "description": "Seedance 2.5 is the current high-quality model; 2.0 retains fast-tier access.",
            },
            "duration": {
                "type": "string",
                "enum": [
                    "auto",
                    "4",
                    "5",
                    "6",
                    "7",
                    "8",
                    "9",
                    "10",
                    "11",
                    "12",
                    "13",
                    "14",
                    "15",
                    "16",
                    "17",
                    "18",
                    "19",
                    "20",
                    "21",
                    "22",
                    "23",
                    "24",
                    "25",
                    "26",
                    "27",
                    "28",
                    "29",
                    "30",
                ],
                "default": "5",
                "description": "Duration in seconds. 'auto' lets the model decide. Seedance 2.0 routes (standard/fast/mini) accept 4-15; only Seedance 2.5 accepts 16-30.",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
                "default": "16:9",
            },
            "resolution": {
                "type": "string",
                "enum": ["480p", "720p", "1080p", "4k"],
                "default": "720p",
                "description": "480p/720p on every route. 1080p on 2.0 standard ($0.682/s) and 2.5 (~$1.164/s); 4k on 2.0 standard only. fast and mini are 480p/720p.",
            },
            "generate_audio": {
                "type": "boolean",
                "default": True,
                "description": "Generate synchronized audio (speech, SFX, ambient)",
            },
            "image_url": {
                "type": "string",
                "description": "Start frame image URL for image_to_video (jpg, png, webp)",
            },
            "image_path": {
                "type": "string",
                "description": "Local start-frame path for image_to_video. Auto-uploaded to fal.ai storage.",
            },
            "end_image_url": {
                "type": "string",
                "description": "Optional end frame URL for image_to_video",
            },
            "reference_image_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Up to 9 reference image URLs for reference_to_video (identity / wardrobe / setting / style anchors).",
            },
            "reference_image_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Local reference image paths for reference_to_video. Auto-uploaded to fal.ai storage.",
            },
            "reference_video_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Up to 3 reference video clip URLs for reference_to_video (motion / camera / pacing anchors).",
            },
            "reference_audio_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Up to 3 reference audio clip URLs for reference_to_video (voice / music / ambience anchors).",
            },
            "seed": {
                "type": "integer",
                "description": "Optional seed for reproducibility",
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True
    )
    retry_policy = RetryPolicy(
        max_retries=2, retryable_errors=["rate_limit", "timeout"]
    )
    idempotency_key_fields = [
        "prompt",
        "model_version",
        "model_variant",
        "operation",
        "duration",
        "seed",
    ]
    side_effects = ["writes video file to output_path", "calls fal.ai API"]
    user_visible_verification = [
        "Watch generated clip for motion coherence, audio sync, and visual quality"
    ]

    def _get_api_key(self) -> str | None:
        return os.environ.get("FAL_KEY") or os.environ.get("FAL_AI_API_KEY")

    def get_status(self) -> ToolStatus:
        if self._get_api_key():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    # fal.ai per-second output prices (pricingInfoOverride, 2026-09-09), keyed by
    # (model_version, model_variant) -> resolution. Where fal publishes no
    # per-second figure for a tier (2.0 standard/fast at 480p) the 720p rate is
    # charged, which over- rather than under-quotes. 2.0 standard 4k is derived
    # from fal's own token formula: 3840*2160*24/1024 = 194,400 tokens/s at
    # $0.008 per 1k tokens. 2.5 with video references bills input + output
    # seconds at 0.6x (~$0.2838/s at 720p) - not modelled here.
    _COST_PER_SECOND = {
        ("2.0", "standard"): {"480p": 0.3034, "720p": 0.3034, "1080p": 0.682, "4k": 1.5552},
        ("2.0", "fast"): {"480p": 0.2419, "720p": 0.2419},
        ("2.0", "mini"): {"480p": 0.0721, "720p": 0.1547},
        ("2.5", "standard"): {"480p": 0.2205, "720p": 0.4730, "1080p": 1.164},
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        model_version = str(inputs.get("model_version", "2.0"))
        variant = "standard" if model_version == "2.5" else inputs.get("model_variant", "standard")
        duration = inputs.get("duration", "5")
        secs = 5 if duration == "auto" else int(duration)
        table = self._COST_PER_SECOND.get(
            (model_version, variant), self._COST_PER_SECOND[("2.0", "standard")]
        )
        resolution = str(inputs.get("resolution", "720p")).lower()
        rate = table.get(resolution, table["720p"])
        return round(rate * secs, 2)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        if inputs.get("model_version", "2.0") == "2.5":
            return 150.0
        variant = inputs.get("model_variant", "standard")
        return 60.0 if variant in ("fast", "mini") else 120.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = self._get_api_key()
        if not api_key:
            return ToolResult(
                success=False,
                error="FAL_KEY not set. " + self.install_instructions,
            )

        import requests

        start = time.time()
        operation = inputs.get("operation", "text_to_video")
        model_version = inputs.get("model_version", "2.0")
        variant = inputs.get("model_variant", "standard")
        operation_path = operation.replace("_", "-")

        if model_version == "2.5":
            if variant in ("fast", "mini"):
                return ToolResult(
                    success=False,
                    error=f"Seedance 2.5 on fal.ai has no {variant} endpoint; use model_variant='standard'.",
                )
            model_path = f"bytedance/seedance-2.5/{operation_path}"
        elif variant in ("fast", "mini"):
            model_path = f"bytedance/seedance-2.0/{variant}/{operation_path}"
        else:
            model_path = f"bytedance/seedance-2.0/{operation_path}"

        # fal per-route limits: 2.0 routes stop at 15 s; fast/mini are 480p/720p
        # only; 4k exists on 2.0 standard only; 2.5 tops out at 1080p.
        requested_duration = str(inputs.get("duration", "5"))
        if model_version != "2.5" and requested_duration != "auto" and int(requested_duration) > 15:
            return ToolResult(
                success=False,
                error=f"Seedance 2.0 ({variant}) on fal.ai accepts 4-15 s; got {requested_duration}. Use model_version='2.5' for 16-30 s.",
            )
        requested_resolution = str(inputs.get("resolution", "720p")).lower()
        if model_version == "2.5":
            allowed_resolutions = ("480p", "720p", "1080p")
        elif variant == "standard":
            allowed_resolutions = ("480p", "720p", "1080p", "4k")
        else:
            allowed_resolutions = ("480p", "720p")
        if requested_resolution not in allowed_resolutions:
            return ToolResult(
                success=False,
                error=f"Seedance {model_version} {variant} on fal.ai supports {', '.join(allowed_resolutions)}; got {requested_resolution}.",
            )

        payload: dict[str, Any] = {"prompt": inputs["prompt"]}

        if inputs.get("duration"):
            payload["duration"] = inputs["duration"]
        if inputs.get("aspect_ratio"):
            payload["aspect_ratio"] = inputs["aspect_ratio"]
        if inputs.get("resolution"):
            payload["resolution"] = inputs["resolution"]
        if "generate_audio" in inputs:
            payload["generate_audio"] = inputs["generate_audio"]
        if inputs.get("seed") is not None:
            payload["seed"] = inputs["seed"]

        if operation == "image_to_video":
            if inputs.get("image_url"):
                payload["image_url"] = inputs["image_url"]
            elif inputs.get("image_path"):
                from tools.video._shared import upload_image_fal

                payload["image_url"] = upload_image_fal(inputs["image_path"])
            if inputs.get("end_image_url"):
                payload["end_image_url"] = inputs["end_image_url"]
            if model_version == "2.5":
                payload["aspect_ratio"] = "auto"

        if operation == "reference_to_video":
            ref_image_urls = list(inputs.get("reference_image_urls") or [])
            for local_path in inputs.get("reference_image_paths") or []:
                from tools.video._shared import upload_image_fal

                ref_image_urls.append(upload_image_fal(local_path))
            max_images = 30 if model_version == "2.5" else 9
            max_videos = 10 if model_version == "2.5" else 3
            max_audios = 10 if model_version == "2.5" else 3
            if len(ref_image_urls) > max_images:
                return ToolResult(
                    success=False,
                    error=f"Seedance {model_version} reference_to_video accepts at most {max_images} reference images; got {len(ref_image_urls)}",
                )
            ref_video_urls = list(inputs.get("reference_video_urls") or [])
            if len(ref_video_urls) > max_videos:
                return ToolResult(
                    success=False,
                    error=f"Seedance {model_version} reference_to_video accepts at most {max_videos} reference videos; got {len(ref_video_urls)}",
                )
            ref_audio_urls = list(inputs.get("reference_audio_urls") or [])
            if len(ref_audio_urls) > max_audios:
                return ToolResult(
                    success=False,
                    error=f"Seedance {model_version} reference_to_video accepts at most {max_audios} reference audio clips; got {len(ref_audio_urls)}",
                )
            max_files = 50 if model_version == "2.5" else 12
            total_files = len(ref_image_urls) + len(ref_video_urls) + len(ref_audio_urls)
            if total_files > max_files:
                return ToolResult(
                    success=False,
                    error=f"Seedance {model_version} reference_to_video accepts at most {max_files} reference files in total; got {total_files}",
                )
            if not ref_image_urls and not ref_video_urls:
                return ToolResult(
                    success=False,
                    error="Seedance reference_to_video needs at least one reference image or video (audio cannot be the only reference)",
                )
            # Every fal Seedance reference route (2.0, 2.0/fast, 2.0/mini, 2.5)
            # takes image_urls / video_urls / audio_urls, cited in the prompt as
            # @Image1, @Video1, @Audio1. The reference_* keys previously sent to
            # the 2.0 routes are not in their schema, so the references were
            # dropped and fal failed with "at least one reference image or video
            # is required".
            if ref_image_urls:
                payload["image_urls"] = ref_image_urls
            if ref_video_urls:
                payload["video_urls"] = ref_video_urls
            if ref_audio_urls:
                payload["audio_urls"] = ref_audio_urls

        headers = {
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
        }

        try:
            submit_resp = requests.post(
                f"https://queue.fal.run/{model_path}",
                headers=headers,
                json=payload,
                timeout=30,
            )
            submit_resp.raise_for_status()
            queue_data = submit_resp.json()
            status_url = queue_data["status_url"]
            response_url = queue_data["response_url"]

            while True:
                time.sleep(5)
                status_resp = requests.get(status_url, headers=headers, timeout=15)
                status_resp.raise_for_status()
                status = status_resp.json().get("status", "UNKNOWN")
                if status == "COMPLETED":
                    break
                if status in ("FAILED", "CANCELLED"):
                    return ToolResult(
                        success=False,
                        error=f"Seedance {model_version} video generation {status.lower()}",
                    )

            result_resp = requests.get(response_url, headers=headers, timeout=30)
            result_resp.raise_for_status()
            data = result_resp.json()

            video_url = data["video"]["url"]
            video_response = requests.get(video_url, timeout=120)
            video_response.raise_for_status()

            output_path = Path(inputs.get("output_path", "seedance_output.mp4"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(video_response.content)

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Seedance {model_version} video generation failed: {e}",
            )

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        return ToolResult(
            success=True,
            data={
                "provider": "seedance",
                "model": model_path,
                "prompt": inputs["prompt"],
                "operation": operation,
                "variant": variant,
                "model_version": model_version,
                "aspect_ratio": inputs.get("aspect_ratio", "16:9"),
                "resolution": inputs.get("resolution", "720p"),
                "generate_audio": inputs.get("generate_audio", True),
                "seed": data.get("seed"),
                "output": str(output_path),
                "output_path": str(output_path),
                "format": "mp4",
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model=model_path,
        )
