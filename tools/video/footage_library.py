"""Footage library: index a directory of the operator's own clips as corpus segments.

Every other path into the corpus is a network stock provider — `corpus_builder`
requires `queries` plus a `StockSource` adapter and all 17 adapters call an API.
This is the only *local* ingest, and the only one that can honestly know whose
footage it is reading.

What it does, per file, per segment
-----------------------------------
1. Probe the whole pool through `lib.source_media_review.review_source_media` —
   the governance gate of record for user media. Its artifact travels back out in
   the result so the reviewing stage can read one probe, not two.
2. Split each file into shot-level segments with `scene_detect`, then chunk any
   scene longer than `max_segment_seconds` so a 45s set becomes several
   independently rankable rows rather than one unusable one.
3. Sample frames inside each segment with `frame_sampler`, measure sharpness
   (variance of the Laplacian) on those frames, and drop the blurry ones — with
   the exclusion counted and reasoned, never silently.
4. Embed the surviving frames with CLIP and write one `ClipRecord` per segment
   carrying `start_seconds` / `end_seconds` / `sharpness` and
   **`identity_locked=True`**.

Identity (spec R5)
------------------
`ClipRecord.identity_locked` defaults to False because a corpus row is stock
unless an ingest path declares otherwise. This tool is that declaration: the
directory is the operator's own pool, so **every row it writes is locked**.
Nothing else in the system sets the flag, so the identity guarantee rests here.

The measurement (spec R8)
-------------------------
The usable-segment count is the pipeline's central number. The idea gate compares
it against `N reels x cuts per reel` (~5 cuts for a 10s reel) to decide both how
many reels it may plan and whether to arm the paid AI-cutaway valve. So the
result reports `usable_segments`, `max_reels`, and every exclusion with its
reason. Re-indexing the same directory is idempotent: segment clip_ids are
derived from (path, in-point, out-point), so a second run adds nothing and
reports the same totals.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from lib.corpus import ClipRecord, Corpus
from lib.source_media_review import detect_media_type, review_source_media
from tools.analysis.frame_sampler import FrameSampler
from tools.analysis.scene_detect import SceneDetect
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)

# A 10s reel is ~5 cuts at ~2s each (spec §5.1), so a segment shorter than a cut
# cannot fill one and a segment much longer wastes pool it could have split into.
DEFAULT_MIN_SEGMENT_SECONDS = 1.5
DEFAULT_MAX_SEGMENT_SECONDS = 6.0
DEFAULT_CUTS_PER_REEL = 5
DEFAULT_FRAMES_PER_SEGMENT = 3
# Variance-of-Laplacian on an 8-bit grey frame. Handheld gym footage sits well
# above this; motion-blurred and out-of-focus frames sit below it.
DEFAULT_SHARPNESS_FLOOR = 60.0


class FootageLibrary(BaseTool):
    name = "footage_library"
    version = "0.1.0"
    tier = ToolTier.SOURCE
    capability = "footage_library"
    provider = "local"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = [
        "cmd:ffmpeg",
        "cmd:ffprobe",
        "python:numpy",
        "python:PIL",
        "python:torch",
        "python:transformers",
    ]
    install_instructions = (
        "Install FFmpeg (https://ffmpeg.org/download.html) and\n"
        "  pip install numpy pillow transformers torch\n"
        "Then point footage_dir at the folder holding your own clips."
    )
    agent_skills = []

    capabilities = [
        "local_footage_ingest",
        "segment_indexing",
        "corpus_population",
        "pool_sufficiency_measurement",
    ]
    supports = {
        "local_offline": True,
        "segment_level_rows": True,
        "identity_locked_rows": True,
        "idempotent_reindex": True,
    }
    best_for = [
        "indexing an operator's own footage pool as rankable segments",
        "measuring how many reels a pool can support without clip reuse",
    ]
    not_good_for = [
        "stock footage (use corpus_builder — those rows are not identity-locked)",
        "semantic retrieval itself (use clip_search)",
    ]
    fallback_tools = []

    input_schema = {
        "type": "object",
        "required": ["footage_dir", "corpus_dir"],
        "properties": {
            "footage_dir": {
                "type": "string",
                "description": "Directory of the operator's own clips (searched recursively).",
            },
            "corpus_dir": {
                "type": "string",
                "description": "Project-local corpus directory, e.g. projects/foo/corpus",
            },
            "min_segment_seconds": {
                "type": "number",
                "minimum": 0.1,
                "default": DEFAULT_MIN_SEGMENT_SECONDS,
                "description": "Segments shorter than this are excluded — they cannot fill a cut.",
            },
            "max_segment_seconds": {
                "type": "number",
                "minimum": 0.1,
                "default": DEFAULT_MAX_SEGMENT_SECONDS,
                "description": "Scenes longer than this are chunked into equal segments.",
            },
            "sharpness_floor": {
                "type": "number",
                "minimum": 0.0,
                "default": DEFAULT_SHARPNESS_FLOOR,
                "description": "Variance-of-Laplacian floor; below it a segment is excluded as blurry.",
            },
            "cuts_per_reel": {
                "type": "integer",
                "minimum": 1,
                "default": DEFAULT_CUTS_PER_REEL,
                "description": "Cuts one reel consumes; sets the implied maximum reel count.",
            },
            "frames_per_segment": {
                "type": "integer",
                "minimum": 1,
                "default": DEFAULT_FRAMES_PER_SEGMENT,
                "description": "Frames sampled inside each segment for sharpness and embedding.",
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "footage_dir": {"type": "string"},
            "corpus_dir": {"type": "string"},
            "files_scanned": {"type": "integer"},
            "files_indexed": {"type": "integer"},
            "files_failed": {"type": "array", "items": {"type": "object"}},
            "segments_planned": {"type": "integer"},
            "usable_segments": {"type": "integer"},
            "segments_added": {"type": "integer"},
            "segments_already_indexed": {"type": "integer"},
            "excluded_segments": {"type": "integer"},
            "excluded_by_reason": {"type": "object"},
            "exclusions": {"type": "array", "items": {"type": "object"}},
            "cuts_per_reel": {"type": "integer"},
            "max_reels": {"type": "integer"},
            "spare_segments": {"type": "integer"},
            "identity_locked": {"type": "boolean"},
            "verdict": {"type": "string"},
            "source_media_review": {"type": "object"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=2048, vram_mb=0, disk_mb=200, network_required=False
    )
    idempotency_key_fields = ["footage_dir", "corpus_dir"]
    side_effects = [
        "writes corpus rows, embeddings and segment thumbnails under corpus_dir",
    ]
    user_visible_verification = [
        "Confirm the usable-segment count matches the pool you intended to index",
        "Confirm every indexed row is your own footage — the whole pool is identity-locked",
    ]

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 60.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()

        footage_dir = Path(inputs["footage_dir"]).expanduser()
        corpus_dir = Path(inputs["corpus_dir"]).expanduser()
        min_seconds = float(inputs.get("min_segment_seconds", DEFAULT_MIN_SEGMENT_SECONDS))
        max_seconds = float(inputs.get("max_segment_seconds", DEFAULT_MAX_SEGMENT_SECONDS))
        floor = float(inputs.get("sharpness_floor", DEFAULT_SHARPNESS_FLOOR))
        cuts_per_reel = int(inputs.get("cuts_per_reel", DEFAULT_CUTS_PER_REEL))
        frames_per_segment = int(inputs.get("frames_per_segment", DEFAULT_FRAMES_PER_SEGMENT))

        if max_seconds < min_seconds:
            return ToolResult(
                success=False,
                error=f"max_segment_seconds ({max_seconds}) < min_segment_seconds ({min_seconds})",
            )
        if not footage_dir.is_dir():
            return ToolResult(success=False, error=f"Footage directory not found: {footage_dir}")

        files = [
            p
            for p in sorted(footage_dir.rglob("*"), key=lambda p: p.as_posix().lower())
            if p.is_file() and detect_media_type(p) == "video"
        ]
        if not files:
            return ToolResult(
                success=False,
                error=f"No video files found under {footage_dir}",
                data={"footage_dir": str(footage_dir), "files_scanned": 0, "usable_segments": 0},
            )

        # The governance gate of record. Transcription is off: a footage pool is
        # indexed for pictures, and the captions come from the audio track.
        review = review_source_media(
            files,
            {
                "pipeline_type": "reel-batch",
                "project_dir": corpus_dir.parent,
                "transcribe": False,
                "frames_dir": corpus_dir / "source_review_frames",
            },
        )

        corp = Corpus(corpus_dir)
        corp.ensure_dirs()
        corp.load()

        files_indexed = 0
        files_failed: list[dict[str, Any]] = []
        segments_planned = 0
        added = 0
        reused = 0
        exclusions: list[dict[str, Any]] = []
        # Segments the embedder could not process. Deliberately NOT exclusions:
        # an infrastructure fault must never read as a verdict on the footage.
        unembeddable: list[dict[str, Any]] = []

        for entry in review["files"]:
            if entry.get("media_type") != "video":
                continue
            path = Path(entry["path"])
            duration = float(entry.get("technical_probe", {}).get("duration_seconds") or 0.0)
            if duration <= 0.0:
                files_failed.append({"path": str(path), "reason": "probe_failed"})
                continue

            scenes = _scene_boundaries(path, duration, corpus_dir)
            segments, rejects = _plan_segments(scenes, min_seconds, max_seconds)
            segments_planned += len(segments) + len(rejects)
            for seg_start, seg_end, reason in rejects:
                exclusions.append(
                    {
                        "source": str(path),
                        "start_seconds": seg_start,
                        "end_seconds": seg_end,
                        "reason": reason,
                    }
                )

            for seg_start, seg_end in segments:
                clip_id = _segment_clip_id(path, footage_dir, seg_start, seg_end)
                if corp.has(clip_id):
                    reused += 1
                    continue

                thumb_rel = Path("thumbnails") / clip_id
                frames = _sample_segment_frames(
                    path, seg_start, seg_end, frames_per_segment, corpus_dir / thumb_rel
                )
                greys = [g for g in (_grey_frame(f) for f in frames) if g is not None]
                if not greys:
                    exclusions.append(
                        {
                            "source": str(path),
                            "start_seconds": seg_start,
                            "end_seconds": seg_end,
                            "reason": "no_frames_extracted",
                        }
                    )
                    continue

                sharpness = round(float(np.mean([_sharpness(g) for g in greys])), 2)
                if sharpness < floor:
                    exclusions.append(
                        {
                            "source": str(path),
                            "start_seconds": seg_start,
                            "end_seconds": seg_end,
                            "reason": "below_sharpness_floor",
                            "sharpness": sharpness,
                        }
                    )
                    continue

                tags = _segment_tags(path)
                try:
                    clip_vec = _embed_frames(frames)
                    tag_vec = _embed_text(tags)
                except Exception as exc:
                    # A broken CLIP stack must not look like a thin pool. These
                    # are counted separately and NEVER folded into `exclusions`,
                    # because exclusions roll into usable=0 and the operator is
                    # then told to go and shoot more footage when the real fault
                    # is that the embedding backend is down.
                    unembeddable.append(
                        {
                            "source": str(path),
                            "start_seconds": seg_start,
                            "end_seconds": seg_end,
                            "error": f"{type(exc).__name__}: {exc}"[:200],
                        }
                    )
                    continue

                corp.add(
                    ClipRecord(
                        clip_id=clip_id,
                        source="footage_library",
                        source_id=_relative_id(path, footage_dir),
                        source_url="",
                        # Absolute on purpose: the pool lives outside the corpus
                        # and must not be copied. `corpus_dir / local_path` still
                        # resolves, because an absolute right-hand side wins.
                        local_path=path.resolve().as_posix(),
                        kind="video",
                        thumb_dir=thumb_rel.as_posix(),
                        query="",
                        creator="operator",
                        license="operator_owned",
                        duration=round(duration, 3),
                        # audio_probe wins the probe race on some files and
                        # reports no resolution, so fall back to the frame we
                        # already decoded rather than writing a 0x0 row.
                        width=_dimension(entry, 0) or int(greys[0].shape[1]),
                        height=_dimension(entry, 1) or int(greys[0].shape[0]),
                        motion_score=_motion_score(greys),
                        source_tags=tags,
                        start_seconds=seg_start,
                        end_seconds=seg_end,
                        sharpness=sharpness,
                        # Declared at ingest (spec R5) — the pool is his footage,
                        # so the whole pool is locked. Set nowhere else.
                        identity_locked=True,
                    ),
                    clip_vec,
                    tag_vec,
                )
                added += 1

            files_indexed += 1

        corp.save()

        usable = added + reused
        max_reels = usable // cuts_per_reel
        excluded_by_reason: dict[str, int] = {}
        for item in exclusions:
            key = str(item["reason"]).split(":")[0]
            excluded_by_reason[key] = excluded_by_reason.get(key, 0) + 1

        verdict = (
            f"{usable} usable operator segments from {files_indexed} file(s) — "
            f"supports {max_reels} reel(s) at {cuts_per_reel} cuts each with no clip reuse "
            f"({usable - max_reels * cuts_per_reel} spare, {len(exclusions)} excluded)"
        )

        data = {
            "footage_dir": str(footage_dir),
            "corpus_dir": str(corpus_dir),
            "files_scanned": len(files),
            "files_indexed": files_indexed,
            "files_failed": files_failed,
            "segments_planned": segments_planned,
            "usable_segments": usable,
            "segments_added": added,
            "segments_already_indexed": reused,
            "excluded_segments": len(exclusions),
            "excluded_by_reason": excluded_by_reason,
            "exclusions": exclusions,
            "sharpness_floor": floor,
            "cuts_per_reel": cuts_per_reel,
            "max_reels": max_reels,
            "spare_segments": usable - max_reels * cuts_per_reel,
            "identity_locked": True,
            "verdict": verdict,
            "segments_unembeddable": len(unembeddable),
            "unembeddable": unembeddable,
            "source_media_review": review,
        }

        if unembeddable and usable == 0:
            # Infrastructure, not footage. Saying "the pool cannot support a
            # single reel" here would send the operator to the gym instead of
            # to the embedding backend.
            first = unembeddable[0]["error"]
            return ToolResult(
                success=False,
                data=data,
                error=(
                    f"Embedding backend unavailable: {len(unembeddable)} segment(s) "
                    f"from {len(files)} file(s) could not be embedded (first failure: "
                    f"{first}). This is NOT a thin pool — the footage was probed and "
                    "segmented successfully. Fix the CLIP stack and re-run; nothing "
                    "about the pool has been measured yet."
                ),
                duration_seconds=round(time.time() - start, 2),
            )

        if usable == 0:
            # Fail loudly rather than hand the gate an empty pool it will plan
            # five reels against. corpus_builder sets the same precedent.
            return ToolResult(
                success=False,
                data=data,
                error=(
                    f"No usable segments indexed from {len(files)} file(s) under {footage_dir}: "
                    f"{len(exclusions)} segment(s) excluded ({excluded_by_reason}). "
                    "The pool cannot support a single reel."
                ),
                duration_seconds=round(time.time() - start, 2),
            )

        return ToolResult(
            success=True,
            data=data,
            duration_seconds=round(time.time() - start, 2),
        )


# ----------------------------------------------------------------------
# Module-level helpers (kept outside the class so tests can hit them)
# ----------------------------------------------------------------------


def _scene_boundaries(path: Path, duration: float, corpus_dir: Path) -> list[dict[str, float]]:
    """Shot boundaries for one file, falling back to the whole file."""
    scene_json = corpus_dir / "scene_cache" / f"{path.stem}_{_path_digest(path)}.scenes.json"
    scene_json.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = SceneDetect().execute(
            {
                "input_path": str(path),
                "min_scene_length_seconds": 1.0,
                "output_path": str(scene_json),
            }
        )
        scenes = result.data.get("scenes") or [] if result.success else []
    except Exception:
        scenes = []
    return scenes or [{"start_seconds": 0.0, "end_seconds": duration}]


def _plan_segments(
    scenes: list[dict[str, Any]], min_seconds: float, max_seconds: float
) -> tuple[list[tuple[float, float]], list[tuple[float, float, str]]]:
    """Turn shot boundaries into cut-sized segments.

    Scenes longer than `max_seconds` are chunked into equal pieces — a 45s set
    that stayed one row would be one clip the ledger burns in a single cut.
    Scenes shorter than `min_seconds` cannot fill a cut and are rejected with a
    reason so the caller can report them rather than drop them.
    """
    segments: list[tuple[float, float]] = []
    rejects: list[tuple[float, float, str]] = []

    for scene in scenes:
        start = float(scene.get("start_seconds", 0.0) or 0.0)
        end = float(scene.get("end_seconds", 0.0) or 0.0)
        span = end - start
        if span < min_seconds:
            rejects.append((round(start, 3), round(end, 3), "shorter_than_min_segment"))
            continue

        pieces = max(1, math.ceil(span / max_seconds))
        while pieces > 1 and span / pieces < min_seconds:
            pieces -= 1
        step = span / pieces
        for i in range(pieces):
            segments.append((round(start + i * step, 3), round(start + (i + 1) * step, 3)))

    return segments, rejects


def _sample_segment_frames(
    path: Path, start: float, end: float, count: int, out_dir: Path
) -> list[Path]:
    """Extract `count` evenly-spaced frames from inside one segment."""
    span = end - start
    timestamps = [round(start + (i + 1) * span / (count + 1), 3) for i in range(count)]
    out_dir.mkdir(parents=True, exist_ok=True)
    result = FrameSampler().execute(
        {
            "input_path": str(path),
            "strategy": "timestamps",
            "timestamps": timestamps,
            "output_dir": str(out_dir),
            "format": "jpg",
        }
    )
    if not result.success:
        return []
    return [Path(f["path"]) for f in result.data.get("frames", [])]


def _grey_frame(path: Path) -> Optional[np.ndarray]:
    """Load a sampled frame as a float32 greyscale array, or None if unreadable."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            return np.asarray(img.convert("L"), dtype=np.float32)
    except Exception:
        return None


# The resolution the focus measure is taken at, whatever the source is shot at.
# Laplacian variance is a FIXED-PIXEL-NEIGHBOURHOOD measure, so it falls as
# resolution rises: adjacent pixels of a 4K frame are more alike than adjacent
# pixels of the same scene at 1080p, and the discrete Laplacian shrinks with
# them. Measured on this repo's own gym pool (2160x3840, phone video, in
# focus): the SAME frame scores 23.0 native, 143.8 normalised here and 481.9 at
# 720p — a 20x swing from nothing but a resize. Against a floor of 60.0 that
# gate was reading resolution, not focus, and it rejected 53 of 56 sharp
# segments while passing the same footage downscaled.
SHARPNESS_NORMALISED_LONG_SIDE = 1920


def _sharpness(grey: np.ndarray) -> float:
    """Variance of the Laplacian at a normalised resolution — a focus measure.

    Normalising the MEASUREMENT rather than the threshold is what keeps
    `DEFAULT_SHARPNESS_FLOOR` meaning the same thing across a mixed pool, and
    makes this a no-op (factor 1) for the ~1080p sources the floor was set on.

    Box-average rather than subsample because dropping pixels aliases detail
    back in; measured on a blurred frame carrying sensor noise, subsampling
    scores 4x higher than box-averaging (2888 vs 721). Note what that measurement
    also says: BOTH are far above the floor, so noise still reads as focus here.
    That is a known limit of Laplacian variance and it predates this function —
    do not read the box-average as making the gate noise-proof.
    """
    if grey.shape[0] < 3 or grey.shape[1] < 3:
        return 0.0
    grey = _normalise_for_sharpness(grey)
    if grey.shape[0] < 3 or grey.shape[1] < 3:
        return 0.0
    lap = (
        grey[:-2, 1:-1]
        + grey[2:, 1:-1]
        + grey[1:-1, :-2]
        + grey[1:-1, 2:]
        - 4.0 * grey[1:-1, 1:-1]
    )
    return float(lap.var())


def _normalise_for_sharpness(grey: np.ndarray) -> np.ndarray:
    """Box-downsample so the long side is about SHARPNESS_NORMALISED_LONG_SIDE."""
    height, width = grey.shape
    factor = max(1, int(round(max(height, width) / SHARPNESS_NORMALISED_LONG_SIDE)))
    if factor == 1:
        return grey
    trimmed_h, trimmed_w = (height // factor) * factor, (width // factor) * factor
    if trimmed_h < factor or trimmed_w < factor:
        return grey
    return (
        grey[:trimmed_h, :trimmed_w]
        .reshape(trimmed_h // factor, factor, trimmed_w // factor, factor)
        .mean(axis=(1, 3))
    )


def _motion_score(greys: list[np.ndarray]) -> float:
    """Mean absolute pixel difference across the segment's sampled frames."""
    if len(greys) < 2 or greys[0].shape != greys[-1].shape:
        return 0.0
    return round(float(np.abs(greys[0] - greys[-1]).mean()), 3)


def _embed_frames(frame_paths: list[Path]) -> np.ndarray:
    from lib.clip_embedder import embed_images, pool_frames

    return pool_frames(embed_images(frame_paths))


def _embed_text(text: str) -> np.ndarray:
    from lib.clip_embedder import embed_texts

    return embed_texts([text])[0]


def _relative_id(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _path_digest(path: Path) -> str:
    return hashlib.sha256(path.resolve().as_posix().encode("utf-8")).hexdigest()[:8]


def _segment_clip_id(path: Path, root: Path, start: float, end: float) -> str:
    """Deterministic id for one (file, in-point, out-point).

    Idempotence rests on this: a second index of the same directory recomputes
    the same ids, `Corpus.has` short-circuits them, and no duplicate row is
    written. The digest keeps same-named files in different subfolders distinct.
    """
    rel = _relative_id(path, root)
    slug = re.sub(r"[^a-z0-9]+", "_", rel.lower()).strip("_")[:40]
    return (
        f"footage_{slug}_{_path_digest(path)}_"
        f"{int(round(start * 1000)):08d}_{int(round(end * 1000)):08d}"
    )


def _segment_tags(path: Path) -> str:
    """Text channel for a local clip: the filename is the only label there is."""
    words = re.sub(r"[^a-z0-9]+", " ", path.stem.lower()).strip()
    return f"operator footage {words}".strip()


def _dimension(entry: dict[str, Any], index: int) -> int:
    resolution = str(entry.get("technical_probe", {}).get("resolution", ""))
    parts = resolution.split("x")
    if len(parts) != 2:
        return 0
    try:
        return int(parts[index])
    except ValueError:
        return 0
