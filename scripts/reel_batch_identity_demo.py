#!/usr/bin/env python3
"""Show the identity chain refusing the two things it exists to refuse.

    python scripts/reel_batch_identity_demo.py

Spec `docs/intent/reel-batch-spec.md` §3 R5. Two attempts, both refused:

1. **A gym clip handed to a generator as a reference.** `cutaway_gen` refuses it
   before pricing, and refuses every renaming and nesting of the same idea.
2. **A mislabelled cut list.** An operator clip declared `ai_generated` — which
   is how identity protection gets switched off — blocked at the compose gate,
   on all three render runtimes.

Nothing here is paid, and nothing renders. The refusals are the output.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.base_tool import ToolResult  # noqa: E402
from tools.video.cutaway_gen import CutawayGen, MediaReferenceRefusedError  # noqa: E402
from tools.video.video_compose import VideoCompose  # noqa: E402

POOL_CLIP = "/pool/rack_pulls_A.mp4"

# Six ways to hand a generator the operator's face. The guard walks the whole
# input structure, so none of them is a way round it.
REFERENCE_ATTEMPTS = [
    ("the obvious one", {"prompts": ["chalk dust"], "reference_image_path": POOL_CLIP}),
    ("renamed key", {"prompts": ["chalk dust"], "init_video": POOL_CLIP}),
    ("nested one level", {"prompts": ["chalk dust"], "extra": {"image_url": POOL_CLIP}}),
    ("inside a list", {"prompts": ["chalk dust"], "refs": [{"last_image_url": POOL_CLIP}]}),
    ("innocuous key name", {"prompts": ["chalk dust"], "style": POOL_CLIP}),
    ("base64, no path at all",
     {"prompts": ["chalk dust"], "seed_frame": "data:image/png;base64,iVBORw0KGgo="}),
]

ROUTES = [
    ("templated Remotion", {"render_runtime": "remotion"}),
    ("atelier Remotion", {"render_runtime": "remotion", "composition_mode": "atelier"}),
    ("HyperFrames", {"render_runtime": "hyperframes", "composition_mode": "atelier"}),
]


def _rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def demo_generation_refusal() -> int:
    _rule("1. A gym clip as a generation reference")
    print("   Each attempt calls cutaway_gen.estimate_cost() — the pricing seam,")
    print("   before any provider is chosen and before a byte is sent.\n")

    tool = CutawayGen()
    failures = 0
    for label, inputs in REFERENCE_ATTEMPTS:
        try:
            cost = tool.estimate_cost(inputs)
        except MediaReferenceRefusedError as e:
            # The message names the exact path it walked to, which is the
            # useful half — "inputs.refs[0].last_image_url", not the sermon.
            where = str(e).split(" ", 1)[0]
            print(f"   REFUSED  {label:<26} at {where}")
        else:
            print(f"   *** ACCEPTED at ${cost:.2f} — {label}: THE GUARD IS GONE ***")
            failures += 1
    return failures


def _mislabelled_plan(extra: dict, tmp: Path) -> dict:
    """An operator clip declared `ai_generated`. The asset says otherwise."""
    return {
        "operation": "render",
        "edit_decisions": {
            "version": "1.0",
            "renderer_family": "documentary-montage",
            "cuts": [{
                "id": "reel_01-01",
                "source": "pool_01",
                "in_seconds": 4.20,
                "out_seconds": 6.14,
                "provenance": "ai_generated",
            }],
            **extra,
        },
        "asset_manifest": {
            "version": "1.0",
            "assets": [{
                "id": "pool_01", "type": "video", "path": str(tmp / "rack_pulls.mp4"),
                "source_tool": "footage_library", "scene_id": "reel_01-01",
            }],
        },
        "output_path": str(tmp / "out.mp4"),
    }


def demo_gate_rejection(tmp: Path) -> int:
    _rule("2. A mislabelled cut list, on every render runtime")
    print("   The clip came from footage_library — the operator's own pool, locked")
    print("   at ingest. The cut declares ai_generated, which is exactly how the")
    print("   grade-and-grain restriction gets switched off.\n")

    # Every renderer is stubbed to shout. If one runs, the gate did not hold.
    reached: list[str] = []
    original = {}
    for method in ("_render_via_atelier", "_render_via_hyperframes",
                   "_render_via_ffmpeg", "_compose", "_remotion_render"):
        original[method] = getattr(VideoCompose, method)
        setattr(VideoCompose, method,
                lambda *a, _m=method, **k: (reached.append(_m),
                                            ToolResult(success=True, data={}))[1])

    failures = 0
    try:
        for label, extra in ROUTES:
            reached.clear()
            result = VideoCompose().execute(_mislabelled_plan(extra, tmp))
            if result.success or reached:
                print(f"   *** RENDERED on {label}: THE GATE DID NOT FIRE ***")
                failures += 1
                continue
            reason = next(
                (ln.strip(" •") for ln in (result.error or "").splitlines()
                 if "Identity violation" in ln),
                (result.error or "").strip(),
            )
            print(f"   BLOCKED  {label:<20}")
            print(f"            {reason}")
    finally:
        for method, fn in original.items():
            setattr(VideoCompose, method, fn)
    return failures


def main() -> int:
    import tempfile

    print(__doc__.split("\n\n")[0])
    with tempfile.TemporaryDirectory() as td:
        failures = demo_generation_refusal() + demo_gate_rejection(Path(td))

    _rule("What this does NOT prove")
    print("   provenance is a DECLARATION, not a detection. A hand-placed file with")
    print("   a hand-written provenance has no asset row to be checked against, and")
    print("   a cut with no provenance key at all is treated as unlocked. Default-deny")
    print("   at ingest is what keeps that gap small: the whole pool is locked, so")
    print("   mislabelling takes an active override rather than an omission.")
    print("   And `faceswap` is still one Bash call away — doctrine, not enforcement.")

    print()
    if failures:
        print(f"FAILED — {failures} attempt(s) got through. The identity chain is broken.")
        return 1
    print("All attempts refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
