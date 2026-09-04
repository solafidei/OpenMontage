"""Segment-level corpus rows: offsets, sharpness, identity_locked.

A corpus row used to be one whole file, so "split a 45s gym set into
three usable pieces and index each" had no representation anywhere. The
four new `ClipRecord` fields are real dataclass fields rather than a
side-map because `dataclasses.asdict` is what `clip_search` hands the
agent (`tools/video/clip_search.py:301, :323, :356`), and every artifact
item schema that could otherwise carry them is `additionalProperties:
false`.

Two properties are load-bearing and tested explicitly here:

* **Backward compatibility.** An index.jsonl written before segments
  existed must load with no migration, and its rows must read as the
  whole file, `[0, duration]`.
* **Sibling independence.** `Corpus.rank_by_text` tests
  `rec.clip_id in exclude` and nothing else (`lib/corpus.py:353-356`),
  so the whole no-reuse guarantee rests on two segments of one source
  being distinct rows with distinct clip_ids: excluding one must leave
  its siblings rankable.
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.corpus import EMBED_DIM, ClipRecord, Corpus


def _vec(*head: float) -> np.ndarray:
    """A small L2-normalised embedding, padded out to EMBED_DIM."""
    v = np.zeros(EMBED_DIM, dtype=np.float32)
    v[: len(head)] = head
    return v / np.linalg.norm(v)


def _segment(clip_id: str, start: float, end: float, **kw) -> ClipRecord:
    """One segment row of the same 45s gym set."""
    return ClipRecord(
        clip_id=clip_id,
        source="pool",
        source_id="gym_set_01",
        source_url="",
        local_path="clips/gym_set_01.mp4",
        duration=45.0,
        start_seconds=start,
        end_seconds=end,
        **kw,
    )


# ----------------------------------------------------------------------
# Backward compatibility
# ----------------------------------------------------------------------


def test_pre_segment_row_loads_without_migration_and_reads_whole_file(tmp_path):
    # An index.jsonl exactly as it was written before segments existed:
    # no start_seconds, no end_seconds, no sharpness, no identity_locked.
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    legacy = {
        "clip_id": "pexels_12345",
        "source": "pexels",
        "source_id": "12345",
        "source_url": "https://example.invalid/12345",
        "local_path": "clips/pexels_12345.mp4",
        "kind": "video",
        "thumb_dir": "thumbnails/pexels_12345",
        "query": "city at night",
        "creator": "someone",
        "license": "pexels",
        "duration": 12.5,
        "width": 1920,
        "height": 1080,
        "motion_score": 0.4,
        "dominant_colors": [],
        "source_tags": "city night",
        "shot_type": "",
        "time_of_day": "",
        "added_at": 1700000000.0,
    }
    (corpus_dir / "index.jsonl").write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    np.save(corpus_dir / "embeddings.npy", _vec(1, 0).reshape(1, -1))
    np.save(corpus_dir / "tag_embeddings.npy", _vec(1, 0).reshape(1, -1))

    corp = Corpus(corpus_dir)
    corp.load()  # no migration step anywhere

    rec = corp.get("pexels_12345")
    assert rec is not None
    assert rec.start_seconds is None
    assert rec.end_seconds is None
    # Absent offsets mean the whole file.
    assert rec.interval == (0.0, 12.5)


def test_segment_offsets_survive_a_save_load_round_trip(tmp_path):
    corp = Corpus(tmp_path / "corpus")
    corp.add(_segment("pool_gym_set_01_s1", 4.0, 9.5, sharpness=180.0), _vec(1, 0), _vec(1, 0))
    corp.save()

    reloaded = Corpus(tmp_path / "corpus")
    reloaded.load()

    rec = reloaded.get("pool_gym_set_01_s1")
    assert rec.interval == (4.0, 9.5)
    assert rec.sharpness == 180.0
    assert rec.identity_locked is False


# ----------------------------------------------------------------------
# The fields reach the agent verbatim
# ----------------------------------------------------------------------


def test_asdict_carries_all_four_segment_fields():
    # clip_search serialises with dataclasses.asdict, so anything not a
    # real field is invisible to the agent.
    row = asdict(_segment("pool_gym_set_01_s0", 0.0, 3.25, sharpness=210.5))

    assert row["start_seconds"] == 0.0
    assert row["end_seconds"] == 3.25
    assert row["sharpness"] == 210.5
    assert row["identity_locked"] is False


# ----------------------------------------------------------------------
# identity_locked is declared at ingest, not defaulted
# ----------------------------------------------------------------------


def test_identity_locked_defaults_to_stock_not_operator():
    """A corpus row is stock unless an ingest path declares otherwise.

    All 17 corpus adapters are network stock providers, so defaulting True
    would make every pexels/NASA/archive.org row claim it depicts the
    operator — a falsehood the next Corpus.save() would persist across the
    twelve pipelines sharing this index. Default-deny lives at the pool
    (footage_library), which is the only ingest that can honestly know.
    """
    stock = ClipRecord(
        clip_id="x", source="pexels", source_id="1", source_url="", local_path=""
    )
    assert stock.identity_locked is False

    # The operator's own pool declares the lock explicitly, and it survives
    # a save/load round trip — the guarantee travels with the row, not with
    # the code path that happened to create it.
    operator = ClipRecord(
        clip_id="y",
        source="footage_library",
        source_id="2",
        source_url="",
        local_path="",
        identity_locked=True,
    )
    assert operator.identity_locked is True
    assert asdict(operator)["identity_locked"] is True


# ----------------------------------------------------------------------
# Sibling segments are independent rows — the no-reuse guarantee
# ----------------------------------------------------------------------


def _three_segment_corpus(tmp_path) -> Corpus:
    """One 45s gym set indexed as three non-overlapping segments."""
    corp = Corpus(tmp_path / "corpus")
    corp.add(_segment("pool_gym_set_01_s0", 0.0, 3.0), _vec(1, 0, 0), _vec(1, 0, 0))
    corp.add(_segment("pool_gym_set_01_s1", 12.0, 15.0), _vec(1, 0, 0), _vec(1, 0, 0))
    corp.add(_segment("pool_gym_set_01_s2", 30.0, 33.5), _vec(1, 0, 0), _vec(1, 0, 0))
    return corp


def test_non_overlapping_segments_of_one_file_are_distinct_rankable_rows(tmp_path):
    corp = _three_segment_corpus(tmp_path)

    assert len(corp) == 3
    # Same source file, three distinct rows.
    assert {r.local_path for r in corp.records} == {"clips/gym_set_01.mp4"}
    assert len({r.clip_id for r in corp.records}) == 3
    assert [r.interval for r in corp.records] == [(0.0, 3.0), (12.0, 15.0), (30.0, 33.5)]

    ranked = corp.rank_by_text(_vec(1, 0, 0), k=10)
    assert {rec.clip_id for rec, _ in ranked} == {
        "pool_gym_set_01_s0",
        "pool_gym_set_01_s1",
        "pool_gym_set_01_s2",
    }


def test_excluding_one_segment_leaves_its_siblings_available(tmp_path):
    # This is the whole no-reuse guarantee: rank_by_text filters on
    # clip_id alone, so consuming one segment must not consume the source.
    corp = _three_segment_corpus(tmp_path)

    ranked = corp.rank_by_text(_vec(1, 0, 0), k=10, exclude_ids=["pool_gym_set_01_s1"])

    assert {rec.clip_id for rec, _ in ranked} == {
        "pool_gym_set_01_s0",
        "pool_gym_set_01_s2",
    }


# ----------------------------------------------------------------------
# Trust boundary
# ----------------------------------------------------------------------


def test_inverted_segment_is_rejected_at_construction():
    with pytest.raises(ValueError, match="must exceed"):
        _segment("pool_gym_set_01_bad", 9.0, 4.0)


def test_negative_in_point_is_rejected_at_construction():
    with pytest.raises(ValueError, match="start_seconds"):
        _segment("pool_gym_set_01_bad", -1.0, 4.0)


def test_half_specified_zero_length_out_point_is_rejected_at_construction():
    # `end_seconds` alone implies an in-point of 0.0, so out <= 0 is the
    # same zero-length cut as an inverted pair — it used to pass because
    # the pairwise check needs both offsets.
    with pytest.raises(ValueError, match="end_seconds must be > 0"):
        ClipRecord(
            clip_id="pool_gym_set_01_bad",
            source="pool",
            source_id="gym_set_01",
            source_url="",
            local_path="clips/gym_set_01.mp4",
            duration=10.0,
            end_seconds=0.0,
        )


def test_open_ended_row_with_only_an_in_point_is_still_legal():
    # "From here to the end of the file" is a real shape, not a degenerate
    # one — tightening the out-point guard must not take it out.
    rec = ClipRecord(
        clip_id="pool_gym_set_01_tail",
        source="pool",
        source_id="gym_set_01",
        source_url="",
        local_path="clips/gym_set_01.mp4",
        duration=45.0,
        start_seconds=30.0,
    )
    assert rec.interval == (30.0, 45.0)


# ----------------------------------------------------------------------
# Stills have no timeline
# ----------------------------------------------------------------------


def test_interval_on_an_image_row_refuses_rather_than_reading_zero_length():
    # A still's duration is 0, so [0, duration] answered (0.0, 0.0) and
    # every caller that compares `end - start` against a slot length
    # dropped the row as "too short" with no diagnostic.
    rec = ClipRecord(
        clip_id="wikimedia_9001",
        source="wikimedia",
        source_id="9001",
        source_url="",
        local_path="clips/wikimedia_9001.jpg",
        kind="image",
        duration=0.0,
    )
    with pytest.raises(ValueError, match="undefined for image row"):
        rec.interval
