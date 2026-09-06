"""Persistence, concurrency, recovery, and default-budget tests for CostTracker.

Covers workstream B of the Epic 1 review fixes:
- B1 atomic `_save` + corruption-handling `_load` (`CostLogCorruptedError`,
  `reconstruct_from_snapshot`)
- B2 flock + reload-before-save merge
- B3 `non_terminal_entries()` stranded-reservation recovery
- B4 constructor default resolved from config

Mirrors the unittest + tempfile.TemporaryDirectory + validate_artifact pattern
of tests/tools/test_cost_tracker_governance.py.
"""

from __future__ import annotations

import json
import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.config_model import BudgetMode, OpenMontageConfig
from schemas.artifacts import validate_artifact
from tools.cost_tracker import (
    BudgetExceededError,
    CostLogCorruptedError,
    CostTracker,
    EntryAlreadyTerminalError,
)

CORRUPT_BYTES = b'{"version": "1.0", "entries": [{"id": "ab'


def _tracker(log_path: Path, **overrides) -> CostTracker:
    """An ungoverned tracker: the guards under test are enabled per-test."""
    kwargs = dict(
        budget_total_usd=10.0,
        reserve_pct=0.0,
        single_action_approval_usd=99.0,
        require_approval_for_new_paid_tool=False,
        mode=BudgetMode.WARN,
        cost_log_path=log_path,
    )
    kwargs.update(overrides)
    return CostTracker(**kwargs)


def _parallel_worker(log_path_str: str, rounds: int) -> None:
    """One child process: `rounds` full estimate→reserve→reconcile round trips."""
    tracker = _tracker(Path(log_path_str), budget_total_usd=1000.0)
    for index in range(rounds):
        entry_id = tracker.estimate("parallel_tool", f"op-{index}", 0.01)
        tracker.reserve(entry_id, user_approved=True)
        tracker.reconcile(entry_id, 0.01)


class CostTrackerAtomicPersistenceTests(unittest.TestCase):
    """B1: a mid-write crash must never truncate the money ledger."""

    def test_failed_save_leaves_previous_ledger_intact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = _tracker(log_path)
            tracker.estimate("paid_video", "generate", 0.10)
            snapshot = log_path.read_bytes()

            with mock.patch(
                "tools.cost_tracker.json.dump", side_effect=RuntimeError("disk full")
            ):
                with self.assertRaises(RuntimeError):
                    tracker.approve_tool("paid_video")

            self.assertEqual(log_path.read_bytes(), snapshot)
            persisted = json.loads(log_path.read_text())
            validate_artifact("cost_log", persisted)
            # The mutation was lost, the ledger was not.
            self.assertEqual(persisted["approved_tools"], [])
            self.assertEqual(len(persisted["entries"]), 1)

    def test_load_corrupt_ledger_raises_pointed_error_and_leaves_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            log_path.write_bytes(CORRUPT_BYTES)

            with self.assertRaises(CostLogCorruptedError) as ctx:
                CostTracker(cost_log_path=log_path)

            message = str(ctx.exception)
            self.assertIn(str(log_path), message)
            self.assertIn("quarantine", message)
            self.assertIn("reconstruct_from_snapshot", message)
            # The constructor must not touch the corrupt file.
            self.assertEqual(log_path.read_bytes(), CORRUPT_BYTES)

    def test_load_rejects_non_object_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            log_path.write_text("[]")

            with self.assertRaises(CostLogCorruptedError):
                CostTracker(cost_log_path=log_path)

    def test_save_replaces_not_appends(self) -> None:
        """The ledger is swapped in whole: a reader never sees a half-write.

        Asserting only "no .tmp remains and the file parses" passes under a
        plain `open(cost_log.json, "w") + json.dump` too, so this watches the
        durable file *while* the new bytes are being written: it must still
        hold the complete previous ledger, and the dump must target a
        different path that `os.replace` then swaps in.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = _tracker(log_path)
            entry_id = tracker.estimate("paid_video", "generate", 0.10)
            previous = log_path.read_bytes()
            previous_inode = log_path.stat().st_ino

            real_dump = json.dump
            observed: dict[str, object] = {}

            def spy(obj, file_obj, *args, **kwargs):
                observed["dump_target"] = getattr(file_obj, "name", "")
                observed["visible_during_write"] = log_path.read_bytes()
                return real_dump(obj, file_obj, *args, **kwargs)

            with mock.patch("tools.cost_tracker.json.dump", side_effect=spy):
                tracker.reserve(entry_id)

            # The dump went to a scratch file, not to the live ledger.
            self.assertTrue(
                str(observed["dump_target"]).endswith(".json.tmp"),
                f"_save wrote directly to {observed['dump_target']!r}",
            )
            self.assertNotEqual(str(observed["dump_target"]), str(log_path))
            # A concurrent reader mid-save still sees the whole old ledger.
            self.assertEqual(observed["visible_during_write"], previous)
            json.loads(observed["visible_during_write"])
            # os.replace swaps the inode; an in-place rewrite would keep it.
            self.assertNotEqual(log_path.stat().st_ino, previous_inode)

            self.assertEqual(list(Path(temp_dir).glob("*.json.tmp")), [])
            persisted = json.loads(log_path.read_text())
            validate_artifact("cost_log", persisted)
            self.assertEqual(len(persisted["entries"]), 1)
            self.assertEqual(persisted["entries"][0]["status"], "reserved")

    def test_failed_save_leaves_no_orphan_tmp_file(self) -> None:
        """The tmp file is cleaned up on any failure, including BaseException.

        An orphaned `cost_log.json.tmp` is a half-written money ledger left
        on disk under a fixed name that the next save reuses.
        """
        for error in (RuntimeError("disk full"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with tempfile.TemporaryDirectory() as temp_dir:
                    log_path = Path(temp_dir) / "cost_log.json"
                    tracker = _tracker(log_path)
                    tracker.estimate("paid_video", "generate", 0.10)

                    with mock.patch(
                        "tools.cost_tracker.json.dump", side_effect=error
                    ):
                        with self.assertRaises(type(error)):
                            tracker.approve_tool("paid_video")

                    self.assertEqual(
                        list(Path(temp_dir).glob("*.json.tmp")),
                        [],
                        "a failed save left a half-written ledger behind",
                    )
                    validate_artifact("cost_log", json.loads(log_path.read_text()))

    def test_reconstruct_from_snapshot_restores_spend_and_quarantines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            log_path.write_bytes(CORRUPT_BYTES)

            tracker = CostTracker.reconstruct_from_snapshot(
                log_path,
                {"total_spent_usd": 1.20, "budget_total_usd": 2.0},
                approved_tools=["tts_selector"],
            )

            quarantined = Path(temp_dir) / "cost_log.json.corrupt-1"
            self.assertTrue(quarantined.exists())
            self.assertEqual(quarantined.read_bytes(), CORRUPT_BYTES)

            persisted = json.loads(log_path.read_text())
            validate_artifact("cost_log", persisted)
            self.assertAlmostEqual(tracker.budget_spent_usd, 1.20)
            self.assertEqual(tracker.budget_total_usd, 2.0)
            self.assertIn("tts_selector", persisted["approved_tools"])
            self.assertEqual(persisted["entries"][0]["tool"], "ledger_reconstruction")

            # The guard works against reconstructed spend: only $0.80 is left.
            reopened = _tracker(
                log_path, budget_total_usd=None, mode=BudgetMode.CAP
            )
            self.assertEqual(reopened.budget_total_usd, 2.0)
            entry_id = reopened.estimate("tts_selector", "synthesize", 1.0)
            with self.assertRaises(BudgetExceededError):
                reopened.reserve(entry_id)


class CostTrackerDamagedLedgerShapeTests(unittest.TestCase):
    """B1: a parseable-but-damaged ledger must raise the pointed error too.

    Valid JSON with the wrong *shape* used to pass the top-level dict check
    and then brick the tracker with a bare KeyError/AttributeError/TypeError
    from the first mutator — a traceback carrying none of the recovery
    guidance CostLogCorruptedError was written to deliver.
    """

    DAMAGED_LEDGERS = {
        "entry_missing_id": {
            "version": "1.0",
            "entries": [
                {"tool": "x", "status": "completed", "actual_usd": 1.0},
            ],
        },
        "entry_missing_status": {
            "version": "1.0",
            "entries": [{"id": "abc123", "tool": "x", "actual_usd": 1.0}],
        },
        "entry_unknown_status": {
            "version": "1.0",
            "entries": [{"id": "abc123", "tool": "x", "status": "done"}],
        },
        "entries_is_a_string": {"version": "1.0", "entries": "[]"},
        "entries_is_an_object": {
            "version": "1.0",
            "entries": {"a": {"id": "a", "status": "completed"}},
        },
        "entry_is_a_string": {"version": "1.0", "entries": ["abc123"]},
        "entry_id_is_a_number": {
            "version": "1.0",
            "entries": [{"id": 7, "status": "completed"}],
        },
        "actual_usd_is_a_string": {
            "version": "1.0",
            "entries": [{"id": "abc123", "status": "completed", "actual_usd": "1.0"}],
        },
        "approved_tools_is_a_string": {
            "version": "1.0",
            "entries": [],
            "approved_tools": "flux_fal",
        },
        "budget_total_is_a_string": {
            "version": "1.0",
            "entries": [],
            "budget_total_usd": "10.0",
        },
    }

    def test_damaged_shapes_raise_pointed_error_on_open(self) -> None:
        for name, payload in self.DAMAGED_LEDGERS.items():
            with self.subTest(shape=name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    log_path = Path(temp_dir) / "cost_log.json"
                    log_path.write_text(json.dumps(payload))
                    original = log_path.read_bytes()

                    with self.assertRaises(CostLogCorruptedError) as ctx:
                        CostTracker(cost_log_path=log_path)

                    message = str(ctx.exception)
                    self.assertIn(str(log_path), message)
                    self.assertIn("quarantine", message)
                    self.assertIn("reconstruct_from_snapshot", message)
                    # No silent repair, no dropped entries, no reset.
                    self.assertEqual(log_path.read_bytes(), original)

    def test_damaged_shapes_raise_pointed_error_on_every_mutator(self) -> None:
        """The merge path is guarded too: damage after open must not brick.

        A tracker opened against a healthy ledger reloads from disk inside
        every mutator, so the same shape check has to run there.
        """
        mutators = {
            "estimate": lambda t: t.estimate("flux_fal", "image", 0.10),
            "approve_tool": lambda t: t.approve_tool("flux_fal"),
            "reserve": lambda t: t.reserve("seed-entry"),
            "reconcile": lambda t: t.reconcile("seed-entry", 0.10),
            "refund": lambda t: t.refund("seed-entry"),
        }
        for name, mutate in mutators.items():
            with self.subTest(mutator=name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    log_path = Path(temp_dir) / "cost_log.json"
                    tracker = _tracker(log_path)
                    tracker.estimate("flux_fal", "image", 0.10)
                    tracker.entries[0]["id"] = "seed-entry"

                    log_path.write_text(
                        json.dumps(self.DAMAGED_LEDGERS["entry_missing_id"])
                    )
                    with self.assertRaises(CostLogCorruptedError):
                        mutate(tracker)

    def test_healthy_ledger_still_opens(self) -> None:
        """The tightened check must not reject ledgers this code writes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = _tracker(log_path)
            entry_id = tracker.estimate("flux_fal", "image", 0.10)
            tracker.reserve(entry_id)
            tracker.reconcile(entry_id, 0.09)

            reopened = _tracker(log_path)
            self.assertAlmostEqual(reopened.budget_spent_usd, 0.09)
            # A header-only ledger (no entries key) is not damage.
            header_only = Path(temp_dir) / "header_only.json"
            header_only.write_text(json.dumps({"version": "1.0"}))
            self.assertEqual(_tracker(header_only).entries, [])


class CostTrackerTerminalOverwriteTests(unittest.TestCase):
    """A settled entry is a money record: the second writer must not win.

    All terminal statuses share one rank in `_STATUS_RANK`, so the merge
    cannot protect a completed entry from being replaced by a refund of it —
    ties break on timestamp alone. This is reachable through
    `non_terminal_entries()`'s own recovery workflow.
    """

    def test_refund_cannot_zero_another_instances_reconciled_spend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker_a = _tracker(log_path)
            entry_id = tracker_a.estimate("kling_fal", "clip", 0.40)
            tracker_a.reserve(entry_id)
            # B follows the same stranded entry, opened while it was reserved.
            tracker_b = _tracker(log_path)
            self.assertEqual(
                [e["id"] for e in tracker_b.non_terminal_entries()], [entry_id]
            )

            # A resolves it first: the provider billed $0.40.
            tracker_a.reconcile(entry_id, 0.40)

            # B resolves the same orphan by the other rule.
            with self.assertRaises(EntryAlreadyTerminalError) as ctx:
                tracker_b.refund(entry_id)
            self.assertIn(entry_id, str(ctx.exception))
            self.assertIn("completed", str(ctx.exception))

            tracker_c = _tracker(log_path)
            entry = tracker_c.entries[0]
            self.assertEqual(entry["status"], "completed")
            self.assertAlmostEqual(entry["actual_usd"], 0.40)
            self.assertAlmostEqual(tracker_c.budget_spent_usd, 0.40)
            persisted = json.loads(log_path.read_text())
            validate_artifact("cost_log", persisted)
            self.assertAlmostEqual(persisted["budget_spent_usd"], 0.40)

    def test_reconcile_twice_does_not_rewrite_billed_spend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = _tracker(log_path)
            entry_id = tracker.estimate("kling_fal", "clip", 0.40)
            tracker.reserve(entry_id)
            tracker.reconcile(entry_id, 0.40)

            with self.assertRaises(EntryAlreadyTerminalError):
                tracker.reconcile(entry_id, 0.90)

            self.assertAlmostEqual(tracker.budget_spent_usd, 0.40)
            self.assertAlmostEqual(
                json.loads(log_path.read_text())["budget_spent_usd"], 0.40
            )

    def test_refunded_entry_cannot_be_reconciled_or_re_refunded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = _tracker(log_path)
            entry_id = tracker.estimate("kling_fal", "clip", 0.40)
            tracker.refund(entry_id)

            with self.assertRaises(EntryAlreadyTerminalError):
                tracker.reconcile(entry_id, 0.40)
            with self.assertRaises(EntryAlreadyTerminalError):
                tracker.refund(entry_id)
            self.assertAlmostEqual(tracker.budget_spent_usd, 0.0)
            self.assertEqual(tracker.entries[0]["status"], "refunded")

    def test_reserve_cannot_resurrect_a_settled_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = _tracker(log_path)
            entry_id = tracker.estimate("kling_fal", "clip", 0.40)
            tracker.reserve(entry_id)
            tracker.reconcile(entry_id, 0.40, success=False)

            with self.assertRaises(EntryAlreadyTerminalError):
                tracker.reserve(entry_id)

            self.assertEqual(tracker.entries[0]["status"], "failed")
            self.assertAlmostEqual(tracker.budget_reserved_usd, 0.0)
            self.assertAlmostEqual(tracker.budget_spent_usd, 0.40)

    def test_force_overrides_the_guard_and_logs_the_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = _tracker(log_path)
            entry_id = tracker.estimate("kling_fal", "clip", 0.40)
            tracker.reserve(entry_id)
            tracker.reconcile(entry_id, 0.40)

            with self.assertLogs("tools.cost_tracker", level="WARNING") as logs:
                tracker.refund(entry_id, force=True)

            self.assertTrue(
                any(
                    "forced refund" in record.getMessage()
                    and entry_id in record.getMessage()
                    for record in logs.records
                ),
                logs.output,
            )
            self.assertEqual(tracker.entries[0]["status"], "refunded")
            validate_artifact("cost_log", json.loads(log_path.read_text()))

    def test_non_terminal_workflow_still_resolves_a_real_orphan(self) -> None:
        """The guard must not block the recovery workflow it protects."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker_a = _tracker(log_path)
            billed_id = tracker_a.estimate("kling_fal", "clip", 0.30)
            tracker_a.reserve(billed_id)
            unbilled_id = tracker_a.estimate("flux_fal", "image", 0.20)
            tracker_a.reserve(unbilled_id)
            del tracker_a

            tracker_b = _tracker(log_path)
            for orphan in list(tracker_b.non_terminal_entries()):
                if orphan["id"] == billed_id:
                    tracker_b.reconcile(orphan["id"], 0.30, success=False)
                else:
                    tracker_b.refund(orphan["id"])

            self.assertEqual(tracker_b.non_terminal_entries(), [])
            self.assertAlmostEqual(tracker_b.budget_spent_usd, 0.30)


class CostTrackerConcurrentWriteTests(unittest.TestCase):
    """B2: two live instances must not erase each other's spend."""

    def test_two_instances_do_not_erase_each_others_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker_a = _tracker(log_path)
            # B opens before A has written anything: a stale in-memory view.
            tracker_b = _tracker(log_path)

            a_id = tracker_a.estimate("flux_fal", "image", 0.40)
            tracker_a.reserve(a_id)
            tracker_a.reconcile(a_id, 0.40)

            b_id = tracker_b.estimate("kling_fal", "clip", 0.30)
            tracker_b.reserve(b_id)
            tracker_b.reconcile(b_id, 0.30)

            tracker_c = _tracker(log_path)
            self.assertEqual(len(tracker_c.entries), 2)
            self.assertEqual(
                {e["id"] for e in tracker_c.entries}, {a_id, b_id}
            )
            self.assertAlmostEqual(tracker_c.budget_spent_usd, 0.70)
            validate_artifact("cost_log", json.loads(log_path.read_text()))

    def test_cap_mode_reserve_sees_other_instances_spend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker_a = _tracker(
                log_path, budget_total_usd=1.0, mode=BudgetMode.CAP
            )
            # B opened while the file was still empty.
            tracker_b = _tracker(
                log_path, budget_total_usd=1.0, mode=BudgetMode.CAP
            )

            a_id = tracker_a.estimate("flux_fal", "image", 0.80)
            tracker_a.reserve(a_id)
            tracker_a.reconcile(a_id, 0.80)

            b_id = tracker_b.estimate("kling_fal", "clip", 0.50)
            with self.assertRaises(BudgetExceededError):
                # user_approved waives the single-action threshold only —
                # never the budget check, and never against merged spend.
                tracker_b.reserve(b_id, user_approved=True)

    def test_merge_never_regresses_terminal_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker_a = _tracker(log_path)
            entry_id = tracker_a.estimate("flux_fal", "image", 0.25)
            tracker_a.reserve(entry_id)

            # B reads the entry while it is still `reserved`.
            tracker_b = _tracker(log_path)
            self.assertEqual(tracker_b.entries[0]["status"], "reserved")

            tracker_a.reconcile(entry_id, 0.25)
            tracker_b.approve_tool("flux_fal")

            self.assertEqual(tracker_b.entries[0]["status"], "completed")
            persisted = json.loads(log_path.read_text())
            self.assertEqual(persisted["entries"][0]["status"], "completed")
            self.assertAlmostEqual(persisted["budget_spent_usd"], 0.25)
            self.assertEqual(persisted["approved_tools"], ["flux_fal"])

    def test_armed_budget_survives_merge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            seed = _tracker(log_path, budget_total_usd=9.0)
            seed.estimate("flux_fal", "image", 0.10)

            armer = _tracker(log_path, budget_total_usd=9.0)
            armer.budget_total_usd = 1.52
            armer.estimate("flux_fal", "image", 0.10)

            fresh = _tracker(log_path)
            self.assertEqual(fresh.budget_total_usd, 1.52)
            self.assertEqual(
                json.loads(log_path.read_text())["budget_total_usd"], 1.52
            )

    def test_unarmed_instance_yields_to_disk_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            armer = _tracker(log_path, budget_total_usd=9.0)
            armer.budget_total_usd = 1.52
            armer.estimate("flux_fal", "image", 0.10)

            # Constructed before the arming: its own budget is not dirty.
            stale = _tracker(log_path, budget_total_usd=9.0)
            stale._budget_total_usd = 9.0  # simulate a pre-arming construction
            stale.estimate("flux_fal", "image", 0.10)

            self.assertEqual(stale.budget_total_usd, 1.52)
            self.assertEqual(
                json.loads(log_path.read_text())["budget_total_usd"], 1.52
            )

    def test_parallel_processes_lose_no_entries(self) -> None:
        if "fork" not in multiprocessing.get_all_start_methods():
            self.skipTest("fork start method unavailable")
        ctx = multiprocessing.get_context("fork")
        processes = 4
        rounds = 5
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            workers = [
                ctx.Process(target=_parallel_worker, args=(str(log_path), rounds))
                for _ in range(processes)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=60)
            for worker in workers:
                self.assertEqual(worker.exitcode, 0)

            tracker = _tracker(log_path, budget_total_usd=1000.0)
            self.assertEqual(len(tracker.entries), processes * rounds)
            self.assertTrue(
                all(e["status"] == "completed" for e in tracker.entries)
            )
            self.assertAlmostEqual(
                tracker.budget_spent_usd, processes * rounds * 0.01
            )
            persisted = json.loads(log_path.read_text())
            validate_artifact("cost_log", persisted)
            self.assertEqual(len(persisted["entries"]), processes * rounds)


class CostTrackerStrandedReservationTests(unittest.TestCase):
    """B3: crash between reserve() and reconcile() must be discoverable."""

    def test_non_terminal_entries_surfaces_crash_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker_a = _tracker(log_path, reserve_pct=0.10)
            entry_id = tracker_a.estimate("kling_fal", "clip", 0.30)
            tracker_a.reserve(entry_id)
            del tracker_a  # simulated crash: no reconcile ever runs

            tracker_b = _tracker(log_path, reserve_pct=0.10)
            orphans = tracker_b.non_terminal_entries()
            self.assertEqual([e["id"] for e in orphans], [entry_id])
            self.assertAlmostEqual(tracker_b.budget_reserved_usd, 0.30)
            # 10.0 - 0.30 held - 1.00 holdback
            self.assertAlmostEqual(tracker_b.usable_budget_usd, 8.70)

            tracker_b.reconcile(entry_id, 0.30, success=False)
            self.assertEqual(tracker_b.non_terminal_entries(), [])
            self.assertAlmostEqual(tracker_b.budget_reserved_usd, 0.0)

    def test_orphan_resolutions_keep_totals_honest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker_a = _tracker(log_path)
            billed_id = tracker_a.estimate("kling_fal", "clip", 0.30)
            tracker_a.reserve(billed_id)
            unbilled_id = tracker_a.estimate("flux_fal", "image", 0.20)
            tracker_a.reserve(unbilled_id)
            del tracker_a

            tracker_b = _tracker(log_path)
            self.assertEqual(len(tracker_b.non_terminal_entries()), 2)

            # Unknowable / billed → reconcile at the estimate, success=False.
            tracker_b.reconcile(billed_id, 0.30, success=False)
            # Provider confirmed no charge → refund.
            tracker_b.refund(unbilled_id)

            self.assertEqual(tracker_b.non_terminal_entries(), [])
            self.assertAlmostEqual(tracker_b.budget_spent_usd, 0.30)
            self.assertAlmostEqual(tracker_b.budget_reserved_usd, 0.0)

            persisted = json.loads(log_path.read_text())
            validate_artifact("cost_log", persisted)
            by_id = {e["id"]: e for e in persisted["entries"]}
            self.assertEqual(by_id[billed_id]["status"], "failed")
            self.assertEqual(by_id[billed_id]["actual_usd"], 0.30)
            self.assertEqual(by_id[unbilled_id]["status"], "refunded")
            self.assertEqual(by_id[unbilled_id]["reserved_usd"], 0.0)
            self.assertAlmostEqual(persisted["budget_spent_usd"], 0.30)


class CostTrackerDefaultBudgetTests(unittest.TestCase):
    """B4: the constructor default comes from config, not a duplicated literal."""

    def test_default_budget_resolves_from_config(self) -> None:
        expected = OpenMontageConfig.load().budget.total_usd
        self.assertEqual(CostTracker().budget_total_usd, expected)
        self.assertEqual(CostTracker(budget_total_usd=3.0).budget_total_usd, 3.0)


if __name__ == "__main__":
    unittest.main()
