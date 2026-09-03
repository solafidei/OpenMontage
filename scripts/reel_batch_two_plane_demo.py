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

from lib.reel_plan import materialise, partition_is_total  # noqa: E402
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
# Five reels means five tracks: `edit_decisions` holds exactly one `audio.music`
# object, which is the whole reason `reel_plan` exists (spec §4.2).
DEFAULT_TRACKS = [
    "projects/ask-jess/public/music.mp3",
    "projects/sacred-mysteries-ep1/assets/audio/narration_s1.mp3",
    "projects/sacred-mysteries-ep1/assets/audio/narration_s3.mp3",
    "projects/sacred-mysteries-ep1/assets/audio/narration_s5b.mp3",
    "projects/sacred-mysteries-ep1/assets/audio/narration_s7.mp3",
]


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


def build_spine(clips: list[Path], reels: int) -> dict:
    """The batch spine: shared look, one flat cuts[] with `<reel_id>-` prefixed ids.

    Every reel of the sitting lives here. The per-reel axes it structurally cannot
    hold — a track, a subtitle source, a hook — go in the reel_plan below.
    """
    cuts = []
    for r in range(reels):
        for i in range(CUTS_PER_REEL):
            clip = clips[(i + r) % len(clips)]
            start = round(r * 0.4 + i * 0.2, 2)
            cuts.append({
                "id": f"reel_{r + 1:02d}-{i + 1:02d}",
                "source": str(clip),
                "in_seconds": start,
                "out_seconds": round(start + CUT_SECONDS, 2),
                "polish": dict(POLISH[i % len(POLISH)]),
            })
    return {
        "version": "1.0",
        "render_runtime": "ffmpeg",
        "renderer_family": "documentary-montage",
        "cuts": cuts,
        "metadata": {"pipeline": "reel-batch", "identity_lock": True},
    }


def build_reel_plan(reels: int, tracks: list[Path]) -> dict:
    """The per-reel axes: one track, one hook and one cut list per reel."""
    return {
        "version": "1.0",
        "reels": [
            {
                "reel_id": f"reel_{r + 1:02d}",
                "track_id": f"track_{r + 1:02d}",
                "music_asset_id": str(tracks[r % len(tracks)]),
                "subtitle_source": f"asset_reel_{r + 1:02d}_captions_json",
                "hook": HOOKS[r % len(HOOKS)],
                "cut_ids": [f"reel_{r + 1:02d}-{i + 1:02d}" for i in range(CUTS_PER_REEL)],
            }
            for r in range(reels)
        ],
    }


def render_reel(spine: dict, entry: dict, out_dir: Path) -> dict:
    """Picture plane, then text plane, for one reel of the batch.

    The reel's `edit_decisions` is materialised IN MEMORY from the spine — nothing
    per-reel is written to disk. The spine stays the artifact of record.
    """
    reel_id = entry["reel_id"]
    decisions = materialise(spine, entry)
    picture = out_dir / f"{reel_id}-picture.mp4"
    final = out_dir / f"{reel_id}.mp4"

    t0 = time.time()
    result = VideoCompose().execute({
        "operation": "render",
        "edit_decisions": decisions,
        "asset_manifest": {"version": "1.0", "assets": []},
        "profile": "instagram_reels",
        "audio_path": decisions["audio"]["music"]["asset_id"],
        "batch_look": BATCH_LOOK,
        "output_path": str(picture),
    })
    if not result.success:
        raise SystemExit(f"{reel_id}: picture plane failed — {result.error}")
    picture_s = time.time() - t0

    hook = entry["hook"]
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
        "track": Path(entry["music_asset_id"]).name,
        "cut_count": len(decisions["cuts"]),
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
    ap.add_argument("--tracks", nargs="*", default=DEFAULT_TRACKS)
    ap.add_argument("--out", default="renders/reel-batch-demo")
    args = ap.parse_args()

    def _resolve(paths: list[str], what: str) -> list[Path]:
        resolved = [Path(p) if Path(p).is_absolute() else REPO / p for p in paths]
        missing = [p for p in resolved if not p.exists()]
        if missing:
            raise SystemExit(f"{what} not found: {missing}")
        return resolved

    clips = _resolve(args.clips, "clips")
    tracks = _resolve(args.tracks, "tracks")
    if len(tracks) < args.reels:
        print(f"note: {len(tracks)} track(s) for {args.reels} reels — cycling. "
              f"A real sitting gives every reel its own.")
    out_dir = Path(args.out) if Path(args.out).is_absolute() else REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    spine = build_spine(clips, args.reels)
    plan = build_reel_plan(args.reels, tracks)
    partition_is_total(spine, plan)   # every cut in exactly one reel, or ReelPlanError

    print(f"\nreel-batch two-plane render — {args.reels} reel(s), {REEL_SECONDS:.0f}s each")
    print(f"pool: {len(clips)} clips   tracks: {len(tracks)}   look: {BATCH_LOOK}")
    print(f"spine: {len(spine['cuts'])} cuts across {len(plan['reels'])} reel_plan entries")
    print("=" * 72)

    t0 = time.time()
    rows = [render_reel(spine, entry, out_dir) for entry in plan["reels"]]
    total = time.time() - t0

    for r in rows:
        print(f"\n{r['reel_id']}  \"{r['hook']}\"   track {r['track']}   "
              f"{r['cut_count']} cuts")
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
