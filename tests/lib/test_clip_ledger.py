"""ClipLedger: segment-granular, no-clip-reused-in-one-batch guarantee.

Covers reel-batch spec R7:
- the overlap predicate (adjacent cuts from one take are NOT reuse)
- partial-batch release (abandon reel 4, its segments return to the pool)
- CostTracker's persistence, copied verbatim: flock + merge-from-disk, atomic
  save, terminal states that never regress, and a corruption error that never
  silently resets
- self-validation on every read, because registration in ARTIFACT_NAMES /
  SUPPLEMENTARY_ARTIFACTS never sees this live side file

Mirrors the pytest + tmp_path pattern of the other tests/lib modules; the
fork-based concurrency test mirrors tests/tools/test_cost_tracker_persistence.py.
"""

import json
import multiprocessing
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.checkpoint import SUPPLEMENTARY_ARTIFACTS  # noqa: E402
from lib.clip_ledger import (  # noqa: E402
    ClipLedger,
    ClipLedgerCorruptedError,
    ClipReuseError,
    SegmentAlreadyClaimedError,
)
from schemas.artifacts import ARTIFACT_NAMES, validate_artifact  # noqa: E402

SET = "footage/deadlift_set_01.mp4"


def _ledger(tmp_path) -> ClipLedger:
    return ClipLedger(ledger_path=tmp_path / "artifacts" / "clip_ledger.json")


def _claim(ledger, reel_id, in_seconds, out_seconds, source=SET, clip_id=None):
    return ledger.claim(
        reel_id=reel_id,
        source=source,
        in_seconds=in_seconds,
        out_seconds=out_seconds,
        clip_id=clip_id,
    )


# ---- for_project ----

def test_for_project_creates_and_reads_the_side_file(tmp_path):
    ledger = ClipLedger.for_project("reel-batch-001", projects_dir=tmp_path)
    path = tmp_path / "reel-batch-001" / "artifacts" / "clip_ledger.json"
    assert path.exists()
    validate_artifact("clip_ledger", json.loads(path.read_text()))

    _claim(ledger, "reel-1", 0.0, 3.0, clip_id="seg-a")

    reopened = ClipLedger.for_project("reel-batch-001", projects_dir=tmp_path)
    assert [c["clip_id"] for c in reopened.live_claims()] == ["seg-a"]


# ---- the overlap predicate: the core rule ----

def test_two_non_overlapping_cuts_from_one_take_both_claim(tmp_path):
    """A 40s set legitimately yields several distinct 3s cuts.

    This is the revert check for `_overlaps`: any predicate that keys on the
    source alone (or treats touching intervals [0,3) and [3,6) as a clash)
    refuses the second claim and starves the pool.
    """
    ledger = _ledger(tmp_path)
    _claim(ledger, "reel-1", 0.0, 3.0)
    _claim(ledger, "reel-2", 3.0, 6.0)  # touches, does not overlap
    _claim(ledger, "reel-3", 30.0, 33.0)

    assert len(ledger.live_claims()) == 3
    ledger.assert_no_reuse()


@pytest.mark.parametrize(
    "in_seconds,out_seconds",
    [
        (2.0, 5.0),    # straddles the end of the held cut
        (0.0, 3.0),    # exactly the held cut
        (1.0, 2.0),    # strictly inside it
        (-0.0, 40.0),  # whole file, containing it
        (2.9, 60.0),   # one frame of shared footage is still reuse
    ],
)
def test_overlapping_cut_is_refused(tmp_path, in_seconds, out_seconds):
    ledger = _ledger(tmp_path)
    _claim(ledger, "reel-1", 0.0, 3.0)

    with pytest.raises(SegmentAlreadyClaimedError):
        _claim(ledger, "reel-2", in_seconds, out_seconds)

    assert ledger.is_available(
        source=SET, in_seconds=in_seconds, out_seconds=out_seconds
    ) is False
    # The refused claim left nothing behind.
    assert len(ledger.live_claims()) == 1


def test_same_interval_on_another_source_never_collides(tmp_path):
    ledger = _ledger(tmp_path)
    _claim(ledger, "reel-1", 0.0, 3.0)
    _claim(ledger, "reel-2", 0.0, 3.0, source="footage/squat_set_02.mp4")
    assert len(ledger.live_claims()) == 2
    ledger.assert_no_reuse()


def test_whole_file_claim_blocks_every_cut_inside_it(tmp_path):
    """"Whole file" is just the interval [0, duration] — no special case."""
    ledger = _ledger(tmp_path)
    _claim(ledger, "reel-1", 0.0, 40.0)
    with pytest.raises(SegmentAlreadyClaimedError):
        _claim(ledger, "reel-2", 12.0, 15.0)


def test_empty_interval_is_refused(tmp_path):
    """A zero-length interval overlaps nothing, so it would be reuse in silence."""
    ledger = _ledger(tmp_path)
    with pytest.raises(ValueError):
        _claim(ledger, "reel-1", 3.0, 3.0)
    with pytest.raises(ValueError):
        _claim(ledger, "reel-1", 5.0, 2.0)


# ---- partial batch ----

def test_abandoned_reel_returns_exactly_its_segments(tmp_path):
    """Reels 1-3 approved, reel 4 abandoned: only reel 4's segments come back."""
    ledger = _ledger(tmp_path)
    for reel in range(1, 6):
        for cut in range(2):
            start = reel * 10.0 + cut * 3.0
            _claim(ledger, f"reel-{reel}", start, start + 3.0)
    for reel in (1, 2, 3):
        ledger.reconcile_reel(f"reel-{reel}")

    released = ledger.release_reel("reel-4")

    assert {(c["in_seconds"], c["out_seconds"]) for c in released} == {
        (40.0, 43.0), (43.0, 46.0)
    }
    assert all(c["status"] == "released" for c in released)

    # Reconciled reels are untouched; reel 5 is still holding its own.
    live = ledger.live_claims()
    assert sorted({c["reel_id"] for c in live}) == [
        "reel-1", "reel-2", "reel-3", "reel-5"
    ]
    # Reel 4's segments are genuinely back in the pool.
    assert ledger.is_available(source=SET, in_seconds=40.0, out_seconds=43.0)
    _claim(ledger, "reel-6", 40.0, 43.0)
    ledger.assert_no_reuse()

    # ...while a reconciled reel's segments are not.
    assert not ledger.is_available(source=SET, in_seconds=10.0, out_seconds=13.0)


def test_release_does_not_regress_a_reconciled_claim(tmp_path):
    ledger = _ledger(tmp_path)
    _claim(ledger, "reel-1", 0.0, 3.0)
    ledger.reconcile_reel("reel-1")

    assert ledger.release_reel("reel-1") == []
    assert [c["status"] for c in ledger.claims_for_reel("reel-1")] == ["reconciled"]


# ---- audit ----

def test_assert_no_reuse_fails_when_two_reels_share_a_segment(tmp_path):
    """The audit reads the file, so it catches claims claim() never approved."""
    path = tmp_path / "artifacts" / "clip_ledger.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "version": "1.0",
        "claims": [
            {
                "claim_id": "c1", "reel_id": "reel-1", "source": SET,
                "clip_id": "seg-a", "in_seconds": 0.0, "out_seconds": 3.0,
                "status": "claimed", "timestamp": "2026-01-01T00:00:00+00:00",
            },
            {
                "claim_id": "c2", "reel_id": "reel-2", "source": SET,
                "clip_id": "seg-b", "in_seconds": 2.0, "out_seconds": 5.0,
                "status": "claimed", "timestamp": "2026-01-01T00:00:01+00:00",
            },
        ],
    }))

    with pytest.raises(ClipReuseError):
        ClipLedger(ledger_path=path).assert_no_reuse()


# ---- persistence: corruption, merge, concurrency ----

def test_corrupt_ledger_raises_by_type_and_never_resets(tmp_path):
    ledger = _ledger(tmp_path)
    _claim(ledger, "reel-1", 0.0, 3.0)
    path = ledger.ledger_path
    corrupt = b'{"version": "1.0", "claims": [{"claim_id": "ab'
    path.write_bytes(corrupt)

    with pytest.raises(ClipLedgerCorruptedError):
        ClipLedger(ledger_path=path)
    # ...and the live instance refuses to write over it, too.
    with pytest.raises(ClipLedgerCorruptedError):
        _claim(ledger, "reel-2", 10.0, 13.0)

    assert path.read_bytes() == corrupt, "a corrupt ledger was silently reset"


def test_side_file_is_validated_on_read_not_only_at_checkpoint_time(tmp_path):
    """Registration alone buys nothing: nobody hands this file to write_checkpoint.

    `_validate_artifacts_for_stage` only iterates the dict passed to
    write_checkpoint(artifacts=...), so a ledger damaged in place — here a
    status outside the schema's enum, which would make the claim invisible to
    the holding-status filter and hand the same footage to a second reel —
    must be caught by the ledger's own read.
    """
    ledger = _ledger(tmp_path)
    _claim(ledger, "reel-1", 0.0, 3.0)
    path = ledger.ledger_path
    damaged = json.loads(path.read_text())
    damaged["claims"][0]["status"] = "used"
    path.write_text(json.dumps(damaged))

    with pytest.raises(ClipLedgerCorruptedError):
        ClipLedger(ledger_path=path).live_claims()
    with pytest.raises(ClipLedgerCorruptedError):
        _claim(ledger, "reel-2", 1.0, 2.0)


def test_registered_as_a_supplementary_artifact():
    assert "clip_ledger" in ARTIFACT_NAMES
    assert "clip_ledger" in SUPPLEMENTARY_ARTIFACTS


def test_second_instance_merges_rather_than_overwrites(tmp_path):
    path = tmp_path / "artifacts" / "clip_ledger.json"
    first = ClipLedger(ledger_path=path)
    second = ClipLedger(ledger_path=path)  # opened before either wrote

    _claim(first, "reel-1", 0.0, 3.0)
    _claim(second, "reel-2", 3.0, 6.0)

    persisted = json.loads(path.read_text())
    validate_artifact("clip_ledger", persisted)
    assert sorted(c["reel_id"] for c in persisted["claims"]) == ["reel-1", "reel-2"]

    # And the stale instance cannot resurrect a claim the other one settled.
    first.release_reel("reel-1")
    _claim(second, "reel-3", 20.0, 23.0)
    persisted = json.loads(path.read_text())
    statuses = {c["reel_id"]: c["status"] for c in persisted["claims"]}
    assert statuses["reel-1"] == "released"


def _claim_worker(path_str: str, reel_id: str, rounds: int) -> None:
    """One child process: `rounds` claims on its own slice of one long take."""
    ledger = ClipLedger(ledger_path=Path(path_str))
    offset = int(reel_id.rsplit("-", 1)[1]) * 100.0
    for index in range(rounds):
        start = offset + index * 3.0
        ledger.claim(
            reel_id=reel_id,
            source=SET,
            in_seconds=start,
            out_seconds=start + 3.0,
            clip_id=f"{reel_id}-{index}",
        )


def test_parallel_processes_lose_no_claims(tmp_path):
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork start method unavailable")
    ctx = multiprocessing.get_context("fork")
    processes, rounds = 4, 5
    path = tmp_path / "artifacts" / "clip_ledger.json"
    path.parent.mkdir(parents=True)

    workers = [
        ctx.Process(target=_claim_worker, args=(str(path), f"reel-{n}", rounds))
        for n in range(processes)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)
    for worker in workers:
        assert worker.exitcode == 0

    persisted = json.loads(path.read_text())
    validate_artifact("clip_ledger", persisted)
    assert len(persisted["claims"]) == processes * rounds
    ClipLedger(ledger_path=path).assert_no_reuse()


def test_is_available_agrees_with_claim_on_degenerate_intervals(tmp_path):
    """A probe must answer the question claim() will actually answer.

    Reporting True for an interval claim() rejects would walk a caller
    straight into a ValueError it was told to expect.
    """
    ledger = ClipLedger(tmp_path / "clip_ledger.json")
    for bad in ((3.0, 3.0), (5.0, 2.0), (-1.0, 4.0)):
        assert ledger.is_available(source="a.mp4", in_seconds=bad[0], out_seconds=bad[1]) is False
        with pytest.raises(ValueError):
            ledger.claim(reel_id="r1", source="a.mp4", in_seconds=bad[0], out_seconds=bad[1])


def test_abandoning_two_reels_leaves_the_rest_claimed_and_the_batch_clean(tmp_path):
    """#49(d): the batch-level property, not the per-claim one.

    `test_abandoned_reel_returns_exactly_its_segments` already proves one
    reel's release is exact against a batch whose other reels were
    *reconciled*. This is the state a real abort leaves behind: reels 1-3 are
    still mid-flight at `claimed`, and two reels go back at once. Both matter.
    `claimed` and `reconciled` are both holding statuses, so a test that only
    asserts "still live" cannot tell a reel that is still working from one
    that finished — the status is asserted explicitly here.

    The vacuous pass is the trap this guards. `release_reel` is a silent no-op
    on an unknown reel id and on an already-released one, returning `[]` with
    no exception, so "exactly their segments came back" is satisfied by
    releasing nothing at all unless the count is pinned.
    """
    ledger = _ledger(tmp_path)
    for reel in range(1, 6):
        for cut in range(2):
            start = reel * 10.0 + cut * 3.0
            _claim(ledger, f"reel-{reel}", start, start + 3.0)

    released = []
    for reel in (4, 5):
        released += ledger.release_reel(f"reel-{reel}")

    # Not vacuous: two reels x two cuts actually came back.
    assert len(released) == 4
    assert {(c["in_seconds"], c["out_seconds"]) for c in released} == {
        (40.0, 43.0), (43.0, 46.0), (50.0, 53.0), (53.0, 56.0)
    }
    assert {c["reel_id"] for c in released} == {"reel-4", "reel-5"}

    # Reels 1-3 are untouched AND still working — not merely still live.
    survivors = [c for c in ledger.live_claims()]
    assert sorted({c["reel_id"] for c in survivors}) == ["reel-1", "reel-2", "reel-3"]
    assert {c["status"] for c in survivors} == {"claimed"}
    assert len(survivors) == 6

    # Every abandoned segment is genuinely back in the pool, and none of the
    # survivors' is.
    for start in (40.0, 43.0, 50.0, 53.0):
        assert ledger.is_available(source=SET, in_seconds=start, out_seconds=start + 3.0)
    for start in (10.0, 20.0, 30.0):
        assert not ledger.is_available(source=SET, in_seconds=start, out_seconds=start + 3.0)

    # The partial batch is still internally consistent.
    ledger.assert_no_reuse()

    # And a retry can take an abandoned segment without colliding.
    _claim(ledger, "reel-4b", 40.0, 43.0)
    ledger.assert_no_reuse()
