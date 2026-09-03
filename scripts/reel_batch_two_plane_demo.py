#!/usr/bin/env python3
"""Render a reel the way the reel-batch pipeline does: two planes, in order.

Issue #45 / spec docs/intent/reel-batch-spec.md §3 R6. The split is a
capability ruling, not a speed one:

  picture plane -> ffmpeg   cuts, punch-in, speed ramp, flash, whip, grade,
                            grain, sharpen -- all inside the per-segment
                            re-encode `_compose` already runs. Remotion's only
                            grading hook is a CSS `filter` and cannot express
                            curves, per-channel balance, grain, or a ramp.
  text plane    -> remotion exactly one overlay pass over the finished picture.
                            ffmpeg cannot do pop captions at all: `subtitle_gen`
                            emits srt/vtt/json and its "karaoke" style is an SRT
                            <b> on the active word. That gap is the only reason
                            Remotion is in this pipeline.

Measured on the dev machine at 1080x1920, 10s, 5 cuts (2026-09-03):
picture 9.4s + text 13.6s = 23.0s for a single reel, and 117.0s for a
five-reel sitting -- 23.4s a reel, the extra 0.4s being the probe between
planes. Re-measure with --reels 5 rather than quoting these; one machine.

Run:  python scripts/reel_batch_two_plane_demo.py            # one reel
      python scripts/reel_batch_two_plane_demo.py --reels 5  # batch wall clock

The defaults point at footage already in this repo so the demo runs with no
arguments. Point --clips at the operator's own pool and --track at a real
motivational track for the real thing.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.video.remotion_caption_burn import RemotionCaptionBurn  # noqa: E402
from tools.video.video_compose import VideoCompose  # noqa: E402

REEL_SECONDS = 10.0
CUTS_PER_REEL = 5
CUT_SECONDS = REEL_SECONDS / CUTS_PER_REEL

# One look for the whole sitting — same grade, grain and sharpen on every reel.
BATCH_LOOK = {"grade": "high_contrast", "grain": 4, "sharpen": "sharpen_light"}

# Per-cut picture polish, cycled across the cut list.
POLISH = [
    {"punch_in": 1.12},
    {"speed_ramp": 1.35, "transition_out": "flash"},
    {"punch_in": 1.18},
    {"transition_out": "whip"},
    {"punch_in": 1.08},
]

HOOKS = [
    "5AM. NO EXCUSES.",
    "THE WORK IS THE POINT.",
    "NOBODY IS COMING.",
    "SHOW UP ANYWAY.",
    "ONE MORE REP.",
]

# Word-synced caption line. In the pipeline these come from `transcriber` run
# over the track's speech at the `script` stage; hard-coded here so the demo
# has no ASR dependency.
LINE = "you don't need motivation you need a decision made once and kept every single day"

DEFAULT_CLIPS = [
    "projects/luxury-car-perfume-poc/assets/video/car_reveal_10s.mp4",
    "projects/ask-jess/assets/video/s2_veo_v2.mp4",
    "projects/luxury-car-perfume-poc/assets/video/perfume_reveal_8s.mp4",
    "projects/ask-jess/assets/video/s4_veo_v2.mp4",
    "projects/ask-jess/assets/video/probe2_veo.mp4",
]
DEFAULT_TRACK = "projects/ask-jess/public/music.mp3"


def word_segments(line: str = LINE, span: float = REEL_SECONDS) -> list[dict]:
    """Evenly-spaced word timings across the reel."""
    words = line.split()
    per = span / len(words)
    return [{
        "start": 0.0,
        "end": span,
        "words": [
            {"word": w, "start": round(i * per, 3), "end": round((i + 1) * per, 3)}
            for i, w in enumerate(words)
        ],
    }]


def build_edit_decisions(reel_id: str, clips: list[Path], offset: float) -> dict:
    """One reel's cut list. `offset` walks the in-points so reels don't repeat."""
    cuts = []
    for i in range(CUTS_PER_REEL):
        clip = clips[(i + int(offset)) % len(clips)]
        start = round(offset * 0.4 + i * 0.2, 2)
        cuts.append({
            "id": f"{reel_id}-c{i + 1}",
            "source": str(clip),
            "in_seconds": start,
            "out_seconds": round(start + CUT_SECONDS, 2),
            "polish": dict(POLISH[i % len(POLISH)]),
        })
    return {
        "version": "1.0",
        "render_runtime": "ffmpeg",
        "renderer_family": "cinematic",
        "cuts": cuts,
    }


def render_reel(reel_id: str, clips: list[Path], track: Path, out_dir: Path, index: int) -> dict:
    """Picture plane, then text plane. Returns paths and per-plane wall clock."""
    picture = out_dir / f"{reel_id}-picture.mp4"
    final = out_dir / f"{reel_id}.mp4"

    t0 = time.time()
    result = VideoCompose().execute({
        "operation": "render",
        "edit_decisions": build_edit_decisions(reel_id, clips, float(index)),
        "asset_manifest": {"version": "1.0", "assets": []},
        "profile": "instagram_reels",
        "audio_path": str(track),
        "batch_look": BATCH_LOOK,
        "output_path": str(picture),
    })
    if not result.success:
        raise SystemExit(f"{reel_id}: picture plane failed — {result.error}")
    picture_s = time.time() - t0

    hook = HOOKS[index % len(HOOKS)]
    t1 = time.time()
    burn = RemotionCaptionBurn().execute({
        "input_path": str(picture),
        "output_path": str(final),
        "segments": word_segments(),
        "preset": "reel_pop",
        "safe_zone": {"bottom": 0.18, "sides": 0.06},
        "words_per_page": 3,
        "run_id": reel_id,
        "overlays": [{
            "type": "hero_title",
            "in_seconds": 0.0,
            "out_seconds": 2.5,
            "position": "upper_third",
            "text": hook,
        }],
    })
    if not burn.success:
        raise SystemExit(f"{reel_id}: text plane failed — {burn.error}")
    text_s = time.time() - t1

    return {
        "reel_id": reel_id,
        "hook": hook,
        "picture": picture,
        "final": final,
        "picture_s": picture_s,
        "text_s": text_s,
        "engine": burn.data.get("engine") or burn.data.get("renderer"),
    }


def probe(path: Path) -> str:
    import subprocess
    v = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    a = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_name", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    d = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    w, h = v.split(",")[:2]
    return f"{w}x{h}  {float(d):.2f}s  audio={a or 'NONE'}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reels", type=int, default=1)
    ap.add_argument("--clips", nargs="*", default=DEFAULT_CLIPS)
    ap.add_argument("--track", default=DEFAULT_TRACK)
    ap.add_argument("--out", default="renders/reel-batch-demo")
    args = ap.parse_args()

    clips = [Path(c) if Path(c).is_absolute() else REPO / c for c in args.clips]
    missing = [c for c in clips if not c.exists()]
    if missing:
        raise SystemExit(f"clips not found: {missing}")
    track = Path(args.track) if Path(args.track).is_absolute() else REPO / args.track
    if not track.exists():
        raise SystemExit(f"track not found: {track}")
    out_dir = Path(args.out) if Path(args.out).is_absolute() else REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nreel-batch two-plane render — {args.reels} reel(s), {REEL_SECONDS:.0f}s each")
    print(f"pool: {len(clips)} clips   track: {track.name}   look: {BATCH_LOOK}")
    print("=" * 72)

    t0 = time.time()
    rows = [render_reel(f"reel{i + 1}", clips, track, out_dir, i) for i in range(args.reels)]
    total = time.time() - t0

    for r in rows:
        print(f"\n{r['reel_id']}  \"{r['hook']}\"")
        print(f"  picture (ffmpeg)   {r['picture_s']:6.1f}s   {probe(r['picture'])}")
        print(f"  text ({r['engine'] or 'remotion'})  {r['text_s']:6.1f}s   {probe(r['final'])}")
        print(f"  -> {r['final']}")

    print("\n" + "=" * 72)
    print(f"TOTAL {total:.1f}s for {args.reels} reel(s)  "
          f"({total / args.reels:.1f}s each)")
    print(f"picture plane {sum(r['picture_s'] for r in rows):.1f}s   "
          f"text plane {sum(r['text_s'] for r in rows):.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
