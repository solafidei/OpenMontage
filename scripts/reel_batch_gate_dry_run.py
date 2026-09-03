#!/usr/bin/env python3
"""Dry-run the reel-batch cost gate on a sufficient pool and on a short one.

Issue #46 / spec docs/intent/reel-batch-spec.md R8, and decision log #6. The gate in
`skills/pipelines/reel-batch/idea-director.md` decides two things from one measurement:
how many reels are plannable, and whether any paid cutaway is armed at all. This runs
that arithmetic against the real `video_selector` price so the two headline numbers in
the spec can be checked rather than trusted:

  a pool that covers the batch  ->  TOTAL ESTIMATED $0.00 of $2.00, a proven-$0 ledger
  a pool five cuts short        ->  TOTAL ESTIMATED $0.50 of $2.00, itemised per reel

The cap that makes the second number reachable is decision #6: at most ONE cut per reel
may be an AI flash, so a reel needs `cuts_per_reel - 1` of the operator's own segments.
Without it, greedy fill-free-reels-first allocation gives four reels at $0.00 from a
20-segment pool and the $0.50 worst case never occurs.

Run:  python scripts/reel_batch_gate_dry_run.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from tools.video.cutaway_gen import CUTAWAY_PROVIDER_PIN  # noqa: E402
from tools.video.video_selector import VideoSelector  # noqa: E402

CUTS_PER_REEL = 5
REQUESTED_REELS = 5
REEL_SECONDS = 10.0
# One 5s clip, pinned, 9:16 — what cutaway_gen prices and executes (cutaway_gen.py:296-303).
CLIP = {
    "prompt": "chalk dust drifting through a hard side light, black background, macro",
    "operation": "text_to_video",
    "allowed_providers": list(CUTAWAY_PROVIDER_PIN),
    "duration": "5",
    "aspect_ratio": "9:16",
}


def valve(have: int, cuts: int = CUTS_PER_REEL, requested: int = REQUESTED_REELS) -> dict:
    """The gate's own arithmetic, verbatim from idea-director.md step 2."""
    max_reels = have // cuts                      # reels with ZERO paid help
    assisted_ceiling = have // (cuts - 1)         # reels with one AI flash accent each
    reels = min(requested, assisted_ceiling)
    cutaway_count = max(0, reels * cuts - have)
    return {
        "have": have,
        "max_reels": max_reels,
        "spare_segments": have - max_reels * cuts,
        "assisted_ceiling": assisted_ceiling,
        "reels": reels,
        "cutaway_count": cutaway_count,
        "paid_cutaways_armed": cutaway_count > 0,
        "reel_ids": [f"reel_{i:02d}" for i in range(1, reels + 1)],
    }


def budget_cap(reels: int) -> float:
    o = yaml.safe_load((REPO / "pipeline_defs/reel-batch.yaml").read_text())["orchestration"]
    target_minutes = reels * (REEL_SECONDS / 60.0)
    return max(o["budget_default_usd"], round(o["budget_per_output_minute_usd"] * target_minutes, 2))


def report(label: str, have: int, unit_usd: float) -> None:
    v = valve(have)
    cap = budget_cap(v["reels"])
    armed = v["reel_ids"][: v["cutaway_count"]]

    print(f"\n{label}")
    print("=" * 66)
    print(f"  {have} usable segments · {v['reels']} reels x {CUTS_PER_REEL} cuts "
          f"= {v['reels'] * CUTS_PER_REEL} needed")
    print(f"  max_reels {v['max_reels']} (no paid help) · assisted_ceiling "
          f"{v['assisted_ceiling']} (one AI flash a reel) · spare {v['spare_segments']}")
    print(f"  paid_cutaways_armed = {v['paid_cutaways_armed']}\n")

    total = 0.0
    for reel_id in v["reel_ids"]:
        if reel_id in armed:
            total += unit_usd
            print(f"    {reel_id}  video_selector  cutaway flash via "
                  f"{CUTAWAY_PROVIDER_PIN[0]}_video   ${unit_usd:.2f}")
        else:
            print(f"    {reel_id}  video_selector  pool-covered, no generation    $0.00")

    print(f"\n  TOTAL ESTIMATED ${total:.2f} of ${cap:.2f}")
    if not v["paid_cutaways_armed"]:
        print("  proven-$0 ledger: every entry seeded, reserved and reconciled at 0.00 —")
        print("  full ceremony, no lite variant. The lightening lever is data, not protocol.")


def main() -> int:
    unit = VideoSelector().estimate_cost(CLIP)

    print(f"\nreel-batch cost gate — dry run  (unit price ${unit:.2f}/clip, pinned to "
          f"{CUTAWAY_PROVIDER_PIN[0]})")
    report("A sufficient pool", 31, unit)
    report("A pool five cuts short", 20, unit)

    print("\n" + "=" * 66)
    print("  The flat $2.00 floor wins the max() until about twenty reels; at 3.333")
    print(f"  output minutes the rate takes over at ${budget_cap(20):.2f}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
