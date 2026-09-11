"""MiniMax H3 (Hailuo 03) generation through fal.ai."""

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


class MiniMaxFalVideo(BaseTool):
    name = "minimax_fal_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "minimax"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API
    dependencies = ["env:FAL_KEY"]
    install_instructions = (
        "Set FAL_KEY (or FAL_AI_API_KEY) from https://fal.ai/dashboard/keys."
    )
    agent_skills = ["minimax-h3", "ai-video-gen"]
    capabilities = ["text_to_video", "image_to_video", "reference_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "reference_to_video": True,
        "multiple_reference_images": True,
        "reference_video": True,
        "reference_audio": True,
        "native_audio": True,
    }
    best_for = [
        "MiniMax H3 through an existing fal.ai account",
        "2K multimodal reference video",
    ]
    not_good_for = ["offline generation"]
    fallback_tools = ["minimax_video", "runway_video", "comfyui_video"]
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
            "duration": {"type": "integer", "minimum": 5, "maximum": 15, "default": 5},
            "aspect_ratio": {
                "type": "string",
                "enum": ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
                "default": "16:9",
                "description": "Ignored for image_to_video (the canvas follows the image). 'adaptive' is only accepted by reference_to_video (its fal default).",
            },
            "resolution": {
                "type": "string",
                "enum": ["480P", "768P", "2K", "4K"],
                "default": "2K",
                "description": "480P and 768P are native generation modes; 2K and 4K upscale a 768P base result. Billed per second of output: $0.05 (480P), $0.06 (768P), $0.13 (2K), $0.16 (4K).",
            },
            "image_url": {"type": "string"},
            "end_image_url": {"type": "string"},
            "reference_image_urls": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 9,
                "description": "Up to 9 subject/style images, cited in the prompt as Image 1, Image 2, ... The first 5 are free; each additional image costs $0.08. Images + videos + audio clips must total at most 12 files.",
            },
            "reference_video_urls": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
                "description": "Up to 3 motion/reference clips, 2-15 s each and at most 15 s combined, cited as Video 1, Video 2, ...",
            },
            "reference_audio_urls": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
                "description": "Up to 3 audio clips, 2-15 s each and at most 15 s combined, cited as Audio 1, ... Audio cannot be the only reference input.",
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
    idempotency_key_fields = ["prompt", "operation", "duration", "aspect_ratio", "resolution"]
    side_effects = ["writes video file to output_path", "calls fal.ai API"]
    user_visible_verification = ["Watch the result and verify native audio"]

    @staticmethod
    def _api_key() -> str | None:
        return os.environ.get("FAL_KEY") or os.environ.get("FAL_AI_API_KEY")

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._api_key() else ToolStatus.UNAVAILABLE

    # fal.ai minimax/h3/* list prices per second of output, by resolution
    # (fal_all.json pricingInfoOverride, 2026-09-09).
    _COST_PER_SECOND = {"480P": 0.05, "768P": 0.06, "2K": 0.13, "4K": 0.16}
    # reference_to_video: the first 5 reference images are free, then $0.08 each.
    _FREE_REFERENCE_IMAGES = 5
    _EXTRA_REFERENCE_IMAGE_USD = 0.08

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        resolution = str(inputs.get("resolution", "2K")).upper()
        rate = self._COST_PER_SECOND.get(resolution, self._COST_PER_SECOND["2K"])
        cost = rate * int(inputs.get("duration", 5))
        if inputs.get("operation") == "reference_to_video":
            extra = len(inputs.get("reference_image_urls") or []) - self._FREE_REFERENCE_IMAGES
            cost += max(0, extra) * self._EXTRA_REFERENCE_IMAGE_USD
        return round(cost, 2)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 120.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = self._api_key()
        if not api_key:
            return ToolResult(
                success=False, error="FAL_KEY not set. " + self.install_instructions
            )
        import requests
        from tools.video._shared import probe_output

        operation = inputs.get("operation", "text_to_video")
        payload: dict[str, Any] = {
            "prompt": inputs["prompt"],
            "duration": int(inputs.get("duration", 5)),
            "resolution": str(inputs.get("resolution", "2K")).upper(),
        }
        if operation != "image_to_video":
            payload["aspect_ratio"] = inputs.get("aspect_ratio", "16:9")
        if operation == "image_to_video":
            if not inputs.get("image_url"):
                return ToolResult(
                    success=False, error="image_to_video requires image_url"
                )
            payload["image_url"] = inputs["image_url"]
            if inputs.get("end_image_url"):
                payload["end_image_url"] = inputs["end_image_url"]
        elif operation == "reference_to_video":
            for key in (
                "reference_image_urls",
                "reference_video_urls",
                "reference_audio_urls",
            ):
                if inputs.get(key):
                    payload[key] = inputs[key]
            if not any(
                payload.get(key)
                for key in ("reference_image_urls", "reference_video_urls")
            ):
                return ToolResult(
                    success=False,
                    error="reference_to_video requires a reference image or video",
                )
        # fal catalog id (published 2026-07-31). The older fal-ai/minimax/hailuo-03/*
        # path still resolves as a legacy alias but is no longer a listed model.
        endpoint = f"minimax/h3/{operation.replace('_', '-')}"
        headers = {
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
        }
        started = time.time()
        try:
            submit = requests.post(
                f"https://queue.fal.run/{endpoint}",
                headers=headers,
                json=payload,
                timeout=30,
            )
            submit.raise_for_status()
            queued = submit.json()
            while True:
                time.sleep(5)
                status_response = requests.get(
                    queued["status_url"], headers=headers, timeout=15
                )
                status_response.raise_for_status()
                status = status_response.json().get("status")
                if status == "COMPLETED":
                    break
                if status in {"FAILED", "CANCELLED"}:
                    return ToolResult(
                        success=False,
                        error=f"fal.ai MiniMax H3 generation {status.lower()}",
                    )
            result_response = requests.get(
                queued["response_url"], headers=headers, timeout=30
            )
            result_response.raise_for_status()
            video_url = result_response.json()["video"]["url"]
            download = requests.get(video_url, timeout=180)
            download.raise_for_status()
            output_path = Path(inputs.get("output_path", "minimax_h3_fal_output.mp4"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(download.content)
        except Exception as exc:
            return ToolResult(
                success=False, error=f"fal.ai MiniMax H3 generation failed: {exc}"
            )
        return ToolResult(
            success=True,
            data={
                "provider": "minimax",
                "gateway": "fal.ai",
                "model": endpoint,
                "operation": operation,
                "output": str(output_path),
                **probe_output(output_path),
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - started, 2),
            model=endpoint,
        )
