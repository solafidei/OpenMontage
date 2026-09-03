"""Tests for the footage_library tool — local pool ingest as corpus segments.

Three properties are load-bearing and each has a test that fails if the logic
is reverted:

* **The identity lock.** `ClipRecord.identity_locked` defaults to False on
  purpose (all 17 corpus adapters are network stock providers), so the whole
  identity guarantee of spec R5 rests on this ingest path setting it. Every row
  this tool writes is asserted locked.
* **The measurement.** Spec R8 has the idea gate compare usable segments
  against `N reels x cuts per reel`, so the count, the exclusions with reasons,
  and the implied maximum reel count must all be reported — and re-indexing the
  same pool must not inflate them.
* **The probe.** `source_media_review` is the governance gate of record for user
  media; its frame sampling never populated `representative_frames` because the
  call omitted the required `strategy` and read a `frame_paths` key the tool has
  never returned.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tools.video.footage_library as footage_library
from lib.corpus import EMBED_DIM, Corpus
from lib.source_media_review import review_source_media
from tools.base_tool import ToolTier
from tools.tool_registry import ToolRegistry
from tools.video.footage_library import FootageLibrary, _plan_segments

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required to synthesise pool clips",
)


def _make_clip(path: Path, source: str, seconds: int) -> None:
    """Synthesise one pool clip with ffmpeg's lavfi sources."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", source,
            "-t", str(seconds), "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
        timeout=60,
    )


# testsrc2 is all edges — a high variance-of-Laplacian, i.e. in focus.
_SHARP = "testsrc2=size=320x240:rate=15"
# A flat grey field has no edges at all — variance ~0, i.e. unusably soft.
_SOFT = "color=c=gray:size=320x240:rate=15"


def _unit(index: int) -> np.ndarray:
    v = np.zeros(EMBED_DIM, dtype=np.float32)
    v[index] = 1.0
    return v


def _stub_embedders(mp: pytest.MonkeyPatch) -> None:
    """CLIP would download 350 MB of weights; the vectors are not under test."""
    mp.setattr(footage_library, "_embed_frames", lambda paths: _unit(0))
    mp.setattr(footage_library, "_embed_text", lambda text: _unit(1))


def _index(pool: Path, corpus_dir: Path, **overrides):
    inputs = {
        "footage_dir": str(pool),
        "corpus_dir": str(corpus_dir),
        "max_segment_seconds": 3.0,
        "cuts_per_reel": 2,
    }
    inputs.update(overrides)
    with pytest.MonkeyPatch.context() as mp:
        _stub_embedders(mp)
        return FootageLibrary().execute(inputs)


@pytest.fixture(scope="module")
def pool(tmp_path_factory):
    """One sharp 6s set and one unusably soft 4s set."""
    directory = tmp_path_factory.mktemp("footage_pool")
    _make_clip(directory / "deadlift_set.mp4", _SHARP, 6)
    _make_clip(directory / "soft_focus.mp4", _SOFT, 4)
    return directory


@pytest.fixture(scope="module")
def indexed(pool, tmp_path_factory):
    corpus_dir = tmp_path_factory.mktemp("footage_corpus") / "corpus"
    result = _index(pool, corpus_dir)
    return result, corpus_dir


# ----------------------------------------------------------------------
# Contract
# ----------------------------------------------------------------------


def test_contract_metadata():
    tool = FootageLibrary()
    info = tool.get_info()
    assert info["name"] == "footage_library"
    assert info["capability"] == "footage_library"
    assert info["provider"] == "local"
    assert info["runtime"] == "local"
    assert info["tier"] == ToolTier.SOURCE.value
    # Local ingest: no provider bills for it and nothing leaves the machine.
    assert info["resource_profile"]["network_required"] is False
    assert tool.estimate_cost({}) == 0.0


def test_registry_discovers_footage_library():
    reg = ToolRegistry()
    reg.discover()
    assert reg.get("footage_library") is not None
    assert reg.find_by_capability("local_footage_ingest")[0].name == "footage_library"


# ----------------------------------------------------------------------
# Identity (spec R5)
# ----------------------------------------------------------------------


def test_every_indexed_row_is_identity_locked(indexed):
    """The only ingest that can honestly know whose footage this is.

    Reverting `identity_locked=True` leaves rows that look like stock, and the
    compose gate that reads provenance has nothing to enforce.
    """
    result, corpus_dir = indexed
    assert result.success is True, result.error

    corp = Corpus(corpus_dir)
    corp.load()
    assert len(corp) == result.data["segments_added"] > 0
    assert all(rec.identity_locked is True for rec in corp.records)
    assert result.data["identity_locked"] is True


def test_rows_are_segments_with_offsets_and_sharpness(indexed):
    _, corpus_dir = indexed
    corp = Corpus(corpus_dir)
    corp.load()

    for rec in corp.records:
        assert rec.source == "footage_library"
        assert rec.start_seconds is not None and rec.end_seconds is not None
        assert rec.end_seconds > rec.start_seconds
        assert rec.sharpness > 0.0
        assert Path(rec.local_path).is_file()
        assert (corpus_dir / rec.thumb_dir).is_dir()

    # The 6s sharp file split at max_segment_seconds=3.0 into two rows that are
    # distinct segments of the same source — the whole point of segment rows.
    starts = sorted(r.start_seconds for r in corp.records)
    assert starts == [0.0, 3.0]
    assert len({r.clip_id for r in corp.records}) == len(corp.records)


# ----------------------------------------------------------------------
# The measurement (spec R8)
# ----------------------------------------------------------------------


def test_soft_segments_are_excluded_with_a_reason(indexed):
    result, corpus_dir = indexed
    data = result.data

    assert data["excluded_segments"] > 0
    assert data["excluded_by_reason"]["below_sharpness_floor"] == data["excluded_segments"]
    assert all(item["reason"] == "below_sharpness_floor" for item in data["exclusions"])
    assert all("soft_focus" in item["source"] for item in data["exclusions"])
    # Excluded, not silently dropped: every planned segment is accounted for.
    assert data["segments_planned"] == data["usable_segments"] + data["excluded_segments"]

    corp = Corpus(corpus_dir)
    corp.load()
    assert not any("soft_focus" in rec.local_path for rec in corp.records)


def test_reports_totals_and_implied_reel_count(indexed):
    result, _ = indexed
    data = result.data

    assert data["files_scanned"] == 2
    assert data["files_indexed"] == 2
    assert data["usable_segments"] == 2
    assert data["cuts_per_reel"] == 2
    # Two usable segments at two cuts a reel is exactly one reel, no spare.
    assert data["max_reels"] == 1
    assert data["spare_segments"] == 0
    assert "1 reel(s)" in data["verdict"]


def test_reindexing_the_same_directory_is_idempotent(pool, tmp_path):
    corpus_dir = tmp_path / "corpus"
    first = _index(pool, corpus_dir)
    second = _index(pool, corpus_dir)

    corp = Corpus(corpus_dir)
    corp.load()
    assert len(corp) == first.data["segments_added"]
    assert corp.clip_embeddings.shape[0] == len(corp)

    assert second.data["segments_added"] == 0
    assert second.data["segments_already_indexed"] == first.data["segments_added"]
    # The number the gate acts on must not move on a re-index.
    assert second.data["usable_segments"] == first.data["usable_segments"]
    assert second.data["max_reels"] == first.data["max_reels"]
    assert second.data["excluded_segments"] == first.data["excluded_segments"]


def test_pool_with_no_usable_segments_fails_loudly(tmp_path):
    """A thin pool must fail, not silently degrade reels 4 and 5."""
    pool = tmp_path / "soft_pool"
    pool.mkdir()
    _make_clip(pool / "all_soft.mp4", _SOFT, 4)

    result = _index(pool, tmp_path / "corpus")

    assert result.success is False
    assert "cannot support a single reel" in result.error
    assert result.data["usable_segments"] == 0
    assert result.data["max_reels"] == 0


def test_missing_or_empty_footage_dir_fails_closed(tmp_path):
    absent = FootageLibrary().execute(
        {"footage_dir": str(tmp_path / "nope"), "corpus_dir": str(tmp_path / "corpus")}
    )
    assert absent.success is False
    assert "not found" in absent.error

    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "notes.txt").write_text("not footage", encoding="utf-8")
    result = FootageLibrary().execute(
        {"footage_dir": str(empty), "corpus_dir": str(tmp_path / "corpus")}
    )
    assert result.success is False
    assert "No video files" in result.error


# ----------------------------------------------------------------------
# Segment planning
# ----------------------------------------------------------------------


def test_plan_segments_chunks_long_scenes_and_rejects_short_ones():
    scenes = [
        {"start_seconds": 0.0, "end_seconds": 9.0},   # -> 3 x 3s
        {"start_seconds": 9.0, "end_seconds": 10.0},  # -> too short for a cut
        {"start_seconds": 10.0, "end_seconds": 13.0},  # -> 1 x 3s
    ]
    segments, rejects = _plan_segments(scenes, min_seconds=1.5, max_seconds=3.0)

    assert segments == [
        (0.0, 3.0), (3.0, 6.0), (6.0, 9.0),
        (10.0, 13.0),
    ]
    assert rejects == [(9.0, 10.0, "shorter_than_min_segment")]


def test_plan_segments_never_chunks_below_the_minimum():
    """A 4s scene at max=3.0 must not become two 2s pieces if min forbids it."""
    segments, rejects = _plan_segments(
        [{"start_seconds": 0.0, "end_seconds": 4.0}], min_seconds=2.5, max_seconds=3.0
    )
    assert segments == [(0.0, 4.0)]
    assert rejects == []


# ----------------------------------------------------------------------
# The governance probe
# ----------------------------------------------------------------------


def test_source_media_review_populates_representative_frames(pool, tmp_path):
    """Regression: the sampling call omitted `strategy` and read `frame_paths`.

    frame_sampler's execute() reads inputs["strategy"] unguarded and returns its
    frames under `frames`, so both mistakes left representative_frames empty on
    every run — a governance artifact claiming a review that produced nothing.
    """
    review = review_source_media(
        [pool / "deadlift_set.mp4"],
        {"transcribe": False, "frames_dir": tmp_path / "frames"},
    )

    entry = review["files"][0]
    assert entry["representative_frames"], "frame sampling produced no frames"
    assert all(Path(p).is_file() for p in entry["representative_frames"])
    assert all(str(tmp_path) in p for p in entry["representative_frames"])


def test_result_carries_the_source_media_review_artifact(indexed):
    result, _ = indexed
    review = result.data["source_media_review"]
    assert review["version"] == "1.0"
    assert {Path(f["path"]).name for f in review["files"]} == {
        "deadlift_set.mp4",
        "soft_focus.mp4",
    }
    assert all(f["representative_frames"] for f in review["files"])


def test_a_broken_embedder_is_not_reported_as_a_thin_pool(pool, tmp_path, monkeypatch):
    """Infrastructure faults and footage verdicts must not share a channel.

    embed failures used to land in `exclusions`, which rolls into usable=0 and
    produced "The pool cannot support a single reel" — sending the operator to
    shoot more footage when the real fault was a down CLIP stack. The pool is
    the epic's central measurement; mislabelling why it reads zero is worse
    than failing.
    """
    import tools.video.footage_library as fl

    def _boom(*_a, **_k):
        raise RuntimeError("CLIP weights not cached")

    monkeypatch.setattr(fl, "_embed_frames", _boom)
    monkeypatch.setattr(fl, "_embed_text", _boom)

    result = fl.FootageLibrary().execute(
        {
            "footage_dir": str(pool),
            "corpus_dir": str(tmp_path / "corpus"),
            "max_segment_seconds": 3.0,
            "cuts_per_reel": 2,
        }
    )

    assert result.success is False
    assert "Embedding backend unavailable" in result.error
    assert "NOT a thin pool" in result.error
    assert "cannot support a single reel" not in result.error
    # The count is reported on its own axis, not smuggled into exclusions.
    assert result.data["segments_unembeddable"] > 0
    assert all("embed_failed" not in e.get("reason", "") for e in result.data["exclusions"])


def test_embedding_needs_no_network(monkeypatch):
    """resource_profile declares network_required=False. Make that true.

    Without the offline pin, transformers reaches huggingface.co on every run
    even with the weights cached — measured at 804 outbound attempts and ~190s
    of retry backoff on a machine whose network is merely faulty. For a tool
    whose entire job is indexing a local directory, that is both a false
    contract and minutes of stall.
    """
    import socket

    import tools.video.footage_library as fl

    def _refuse(self, addr):
        raise AssertionError(f"embedding reached the network: {addr}")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    vector = fl._embed_text("empty gym at 5am, cold light")
    assert vector.shape == (512,)
