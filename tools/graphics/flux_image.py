"""FLUX image generation via fal.ai API."""

from __future__ import annotations

import math
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


class FluxImage(BaseTool):
    name = "flux_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = "flux"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.API

    dependencies = []  # checked dynamically via env var
    install_instructions = (
        "Set FAL_KEY to your fal.ai API key.\n"
        "  Get one at https://fal.ai/dashboard/keys"
    )
    agent_skills = ["flux-best-practices", "bfl-api"]

    capabilities = ["generate_image", "generate_illustration", "text_to_image"]
    supports = {
        "negative_prompt": False,
        "seed": True,
        "custom_size": True,
    }
    best_for = [
        "photorealistic images",
        "general-purpose image generation",
        "high quality at low cost (flux-pro/v1.1 $0.04 per output megapixel, rounded up; $0.003-$0.05/MP across the model enum; 1024x1024 is 1 MP)",
    ]
    not_good_for = ["text rendering in images", "offline generation"]

    # fal price per output megapixel as (first megapixel, each additional
    # megapixel). fal rounds the output area UP to a whole megapixel
    # (1 MP = 1024x1024; 1920x1080 bills as 2 MP, 512x512 as 1 MP).
    _PRICE_PER_MEGAPIXEL = {
        "flux-pro/v1.1": (0.04, 0.04),  # https://fal.ai/models/fal-ai/flux-pro/v1.1
        "flux/dev": (0.025, 0.025),  # https://fal.ai/models/fal-ai/flux/dev
        "flux/schnell": (0.003, 0.003),  # https://fal.ai/models/fal-ai/flux/schnell
        "flux-2-pro": (0.03, 0.015),  # catalog: $0.03 first MP + $0.015 per extra MP
        "flux-2": (0.012, 0.012),  # https://fal.ai/models/fal-ai/flux-2
        "flux-pro": (0.05, 0.05),  # legacy FLUX.1 [pro] v1; https://fal.ai/models/fal-ai/flux-pro ($0.05/MP; absent from the public catalog JSON)
    }

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "negative_prompt": {
                "type": "string",
                "default": "",
                "description": "Accepted for image_selector compatibility only; fal FLUX endpoints have no negative_prompt input, so it is not sent.",
            },
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
            "model": {
                "type": "string",
                # fal ids under fal-ai/. "flux-pro" is the legacy FLUX.1 [pro] v1
                # route: it still resolves on the fal OpenAPI but is absent from
                # the public catalog; prefer flux-pro/v1.1 or flux-2-pro.
                "enum": [
                    "flux-pro/v1.1",
                    "flux/dev",
                    "flux/schnell",
                    "flux-2-pro",
                    "flux-2",
                    "flux-pro",
                ],
                "default": "flux-pro/v1.1",
            },
            "seed": {"type": "integer"},
            "num_inference_steps": {
                "type": "integer",
                "description": "Honoured by flux/dev (1-50, default 28), flux/schnell (1-12, default 4), flux-2 (4-50, default 28) and legacy flux-pro (1-50, default 28); flux-pro/v1.1 and flux-2-pro expose no steps/guidance inputs and ignore it.",
            },
            "guidance_scale": {
                "type": "number",
                "description": "Honoured by flux/dev, flux/schnell and legacy flux-pro (1-20, default 3.5) and flux-2 (0-20, default 2.5); ignored by flux-pro/v1.1 and flux-2-pro.",
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=100, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "width", "height", "seed", "model"]
    side_effects = ["writes image file to output_path", "calls fal.ai API"]
    user_visible_verification = ["Inspect generated image for relevance and quality"]

    def _get_api_key(self) -> str | None:
        return os.environ.get("FAL_KEY") or os.environ.get("FAL_AI_API_KEY")

    def get_status(self) -> ToolStatus:
        if self._get_api_key():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # fal bills FLUX text-to-image per output megapixel, rounded UP to
        # the nearest whole megapixel (1 MP = 1024x1024).
        model = inputs.get("model", "flux-pro/v1.1")
        width = int(inputs.get("width", 1024))
        height = int(inputs.get("height", 1024))
        megapixels = max(1, math.ceil((width * height) / 1_048_576))
        first, extra = self._PRICE_PER_MEGAPIXEL.get(model, (0.04, 0.04))
        return round(first + extra * (megapixels - 1), 4)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = self._get_api_key()
        if not api_key:
            return ToolResult(
                success=False,
                error="No fal.ai API key found. " + self.install_instructions,
            )

        import requests

        start = time.time()
        model = inputs.get("model", "flux-pro/v1.1")
        prompt = inputs["prompt"]
        width = inputs.get("width", 1024)
        height = inputs.get("height", 1024)

        payload: dict[str, Any] = {
            "prompt": prompt,
            "image_size": {"width": width, "height": height},
        }
        if inputs.get("seed") is not None:
            payload["seed"] = inputs["seed"]
        if inputs.get("num_inference_steps"):
            payload["num_inference_steps"] = inputs["num_inference_steps"]
        if inputs.get("guidance_scale"):
            payload["guidance_scale"] = inputs["guidance_scale"]
        # negative_prompt is deliberately not forwarded: no fal FLUX endpoint
        # (flux-pro/v1.1, flux/dev, flux/schnell, flux-2, flux-2-pro) has one.

        try:
            response = requests.post(
                f"https://fal.run/fal-ai/{model}",
                headers={
                    "Authorization": f"Key {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()

            image_url = data["images"][0]["url"]
            image_response = requests.get(image_url, timeout=60)
            image_response.raise_for_status()

            output_path = Path(inputs.get("output_path", "generated_image.png"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(image_response.content)

        except Exception as e:
            return ToolResult(success=False, error=f"FLUX generation failed: {e}")

        return ToolResult(
            success=True,
            data={
                "provider": "flux",
                "model": model,
                "prompt": prompt,
                "output": str(output_path),
                "seed": data.get("seed"),
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            seed=data.get("seed"),
            model=f"fal-ai/{model}",
        )
