#!/usr/bin/env python3
"""Show what pinning the cutaway route is worth, and what a bad pin does.

Issue #40 / spec docs/intent/reel-batch-spec.md §5. The reel-batch cost model
assumes two things a reader should be able to check rather than trust:

  1. An unpinned cutaway routes to whatever the scorer ranks top, which is
     currently seedance at $1.52 a clip -- 15x the pinned figure, for footage
     that gets trimmed to a sub-second flash.
  2. A pin that resolves to nothing must RAISE. Before #40 it estimated
     $0.00, which is exempt from both approval guards in cost_tracker
     (estimated > single_action_approval_usd, and
     require_approval_for_new_paid_tool and estimated > 0), so a typo seeded
     an unguarded paid line item.

Run:  python scripts/reel_batch_route_cost.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.tool_registry import ToolRegistry  # noqa: E402
from tools.video.video_selector import ProviderPinUnresolvedError  # noqa: E402

# A full five-reel pool shortfall: one cutaway per reel (spec R8).
REELS = 5
CLIP = {"prompt": "gym atmosphere, 5am, empty street", "duration": "5", "aspect_ratio": "9:16"}


def main() -> int:
    registry = ToolRegistry()
    registry.discover()
    selector = registry.get("video_selector")

    print(f"\nReel-batch cutaway routing — {REELS} reels, one clip each\n" + "=" * 58)

    rows: list[tuple[str, str]] = []
    for label, pin in (
        ("unpinned (scorer's choice)", None),
        ("pinned: kling", ["kling"]),
        ("pinned: gemini_omni", ["gemini_omni"]),
    ):
        inputs = dict(CLIP) | ({"allowed_providers": pin} if pin else {})
        try:
            unit = selector.estimate_cost(inputs)
        except ProviderPinUnresolvedError as exc:
            rows.append((label, f"RAISED — {exc}"))
            continue
        rows.append((label, f"${unit:>5.2f}/clip   ->  ${unit * REELS:>5.2f} for the sitting"))

    for label, value in rows:
        print(f"  {label:<28s} {value}")

    print("\nBad pins — the guard that did not exist before #40\n" + "=" * 58)
    for pin in (["fal"], ["typo_provider"], ["kling", "nonsense"]):
        inputs = dict(CLIP) | {"allowed_providers": pin}
        try:
            unit = selector.estimate_cost(inputs)
            verdict = f"${unit:.2f}"
            if unit == 0.0:
                verdict += "   <-- BUG: $0.00 bypasses both approval guards"
        except ProviderPinUnresolvedError:
            verdict = "raised ProviderPinUnresolvedError (correct)"
        print(f"  allowed_providers={str(pin):<24s} {verdict}")

    print(
        "\n'fal' and 'typo_provider' name no live provider, so they must raise.\n"
        "A pin that partially resolves still routes, and prices at the live member.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
