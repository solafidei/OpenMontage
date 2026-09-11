"""Kling video generation via fal.ai API.

Best for cinematic B-roll with high visual fidelity and fluid motion.
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


class KlingVideo(BaseTool):
    name = "kling_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "kling"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set FAL_KEY to your fal.ai API key.\n"
        "  Get one at https://fal.ai/dashboard/keys"
    )
    agent_skills = ["ai-video-gen"]

    capabilities = ["text_to_video", "image_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "native_audio": True,
        "cinematic_quality": True,
    }
    best_for = [
        "cinematic B-roll with highest visual fidelity",
        "fluid motion and camera direction",
        "professional video clips",
    ]
    not_good_for = ["budget-constrained projects", "offline generation", "quick iteration"]
    fallback_tools = ["minimax_video", "veo_video", "wan_video"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video"],
                "default": "text_to_video",
            },
            "model_variant": {
                "type": "string",
                "enum": [
                    "v3/standard", "v3/pro", "v3/turbo/standard", "v3/turbo/pro",
                    "o3/standard", "o3/pro", "v3/4k", "o3/4k",
                    "v2.1/master", "v2.1/pro", "v2.1/standard",
                ],
                "default": "v3/standard",
                "description": (
                    "fal endpoint prefix: fal-ai/kling-video/<variant>/<operation>. "
                    "v3/o3/turbo lines accept 3-15 s. v2.1 lines are legacy (5 or 10 s); "
                    "v2.1/pro and v2.1/standard exist on fal only as image-to-video."
                ),
            },
            "duration": {
                "type": "string",
                "enum": ["3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"],
                "default": "5",
                "description": "Duration in seconds: 3-15 on v3/o3/turbo lines; v2.1 lines accept only 5 or 10",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["16:9", "9:16", "1:1"],
                "default": "16:9",
                "description": (
                    "fal declares aspect_ratio only on the text-to-video endpoints; "
                    "the image-to-video endpoints have no such field."
                ),
            },
            "generate_audio": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Native audio. Priced separately on v3/standard, v3/pro, o3/standard and "
                    "o3/pro (fal defaults: on for v3, off for o3); flat-rate on v3/4k and o3/4k; "
                    "not available on v3/turbo/* or v2.1/* (ignored there)."
                ),
            },
            "image_url": {"type": "string", "description": "Reference image URL for image_to_video"},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = [
        "prompt", "model_variant", "operation", "duration", "generate_audio",
    ]
    side_effects = ["writes video file to output_path", "calls fal.ai API"]
    user_visible_verification = ["Watch generated clip for motion coherence and visual quality"]

    def _get_api_key(self) -> str | None:
        return os.environ.get("FAL_KEY") or os.environ.get("FAL_AI_API_KEY")

    def get_status(self) -> ToolStatus:
        if self._get_api_key():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    # fal.ai list prices, USD per second of output (fal_all.json pricingInfoOverride,
    # read 2026-09-09). A pair is (audio off, audio on); a bare number means the
    # endpoint has no audio switch or bills the same either way. Voice control on
    # v3/standard|pro ($0.154 / $0.196 per second) is not exposed by this tool.
    FAL_PRICE_PER_SECOND: dict[str, tuple[float, float] | float] = {
        "v3/standard": (0.084, 0.126),
        "v3/pro": (0.112, 0.168),
        "v3/turbo/standard": 0.112,
        "v3/turbo/pro": 0.14,
        "o3/standard": (0.084, 0.112),
        "o3/pro": (0.112, 0.14),
        "v3/4k": 0.42,
        "o3/4k": 0.42,
        "v2.1/master": 0.28,  # $1.40 per 5 s + $0.28 per extra second
        "v2.1/pro": 0.098,  # $0.49 per 5 s + $0.098 per extra second (image_to_video only)
        "v2.1/standard": 0.056,  # $0.28 per 5 s + $0.056 per extra second (image_to_video only)
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        variant = inputs.get("model_variant", "v3/standard")
        duration = int(inputs.get("duration", "5"))
        rate = self.FAL_PRICE_PER_SECOND.get(variant, self.FAL_PRICE_PER_SECOND["v3/standard"])
        if isinstance(rate, tuple):
            rate = rate[1] if bool(inputs.get("generate_audio", True)) else rate[0]
        return round(rate * duration, 4)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 60.0  # ~1 minute typical

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
        variant = inputs.get("model_variant", "v3/standard")
        # fal.ai uses hyphens in endpoint paths (text-to-video, not text_to_video)
        operation_path = operation.replace("_", "-")
        model_path = f"kling-video/{variant}/{operation_path}"

        # fal per-variant limits: the v2.1 line is legacy — its endpoints accept
        # only 5 or 10 s, and fal lists v2.1/pro and v2.1/standard as
        # image-to-video only (v2.1/master is the one v2.1 route with both).
        if variant.startswith("v2.1/"):
            requested_duration = str(inputs.get("duration", "5"))
            if requested_duration not in ("5", "10"):
                return ToolResult(
                    success=False,
                    error=(
                        f"Kling {variant} on fal.ai is legacy and accepts only 5 or 10 s; "
                        f"got {requested_duration}. Use a v3/o3 variant for 3-15 s."
                    ),
                )
            if variant in ("v2.1/pro", "v2.1/standard") and operation == "text_to_video":
                return ToolResult(
                    success=False,
                    error=(
                        f"fal.ai lists kling-video/{variant} only as image-to-video; "
                        "use operation='image_to_video', or model_variant='v2.1/master' "
                        "for legacy text-to-video."
                    ),
                )

        payload: dict[str, Any] = {"prompt": inputs["prompt"]}
        if inputs.get("duration"):
            payload["duration"] = inputs["duration"]
        # fal declares aspect_ratio only on the text-to-video endpoints; the
        # image-to-video ones derive it from the supplied image.
        if operation == "text_to_video" and inputs.get("aspect_ratio"):
            payload["aspect_ratio"] = inputs["aspect_ratio"]
        if operation == "image_to_video" and inputs.get("image_url"):
            # fal's kling-video/v3/{standard,pro,4k} image-to-video endpoints require
            # start_image_url; o3/*, v3/turbo/* and v2.1/* take image_url.
            image_key = (
                "start_image_url"
                if variant.startswith("v3/") and not variant.startswith("v3/turbo/")
                else "image_url"
            )
            payload[image_key] = inputs["image_url"]
        # Only v3/standard|pro|4k and o3/* expose the audio switch; fal defaults it on
        # for v3 and off for o3, so send it explicitly to keep the bill equal to the
        # estimate. Turbo and v2.1 endpoints have no such field.
        if variant in {"v3/standard", "v3/pro", "v3/4k", "o3/standard", "o3/pro", "o3/4k"}:
            payload["generate_audio"] = bool(inputs.get("generate_audio", True))

        headers = {
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
        }

        try:
            # Submit to queue API (async) — sync endpoint times out for video gen
            submit_resp = requests.post(
                f"https://queue.fal.run/fal-ai/{model_path}",
                headers=headers,
                json=payload,
                timeout=30,
            )
            submit_resp.raise_for_status()
            queue_data = submit_resp.json()
            status_url = queue_data["status_url"]
            response_url = queue_data["response_url"]

            # Poll until complete
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
                        error=f"Kling video generation {status.lower()}",
                    )

            # Fetch result
            result_resp = requests.get(response_url, headers=headers, timeout=30)
            result_resp.raise_for_status()
            data = result_resp.json()

            video_url = data["video"]["url"]
            video_response = requests.get(video_url, timeout=120)
            video_response.raise_for_status()

            output_path = Path(inputs.get("output_path", "kling_output.mp4"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(video_response.content)

        except Exception as e:
            return ToolResult(success=False, error=f"Kling video generation failed: {e}")

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        return ToolResult(
            success=True,
            data={
                "provider": "kling",
                "model": f"fal-ai/{model_path}",
                "prompt": inputs["prompt"],
                "operation": operation,
                "aspect_ratio": inputs.get("aspect_ratio", "16:9"),
                "output": str(output_path),
                "output_path": str(output_path),
                "format": "mp4",
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model=f"fal-ai/{model_path}",
        )
