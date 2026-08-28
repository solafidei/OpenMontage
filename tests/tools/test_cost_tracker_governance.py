from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.config_model import BudgetMode, OpenMontageConfig
from lib.paths import PROJECTS_DIR
from schemas.artifacts import validate_artifact
from tools.cost_tracker import ApprovalRequiredError, CostTracker


class CostTrackerGovernanceTests(unittest.TestCase):
    def test_warn_mode_marks_over_budget_reservation(self) -> None:
        with self.subTest("warning is recorded and persisted"):
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as temp_dir:
                log_path = Path(temp_dir) / "cost_log.json"
                tracker = CostTracker(
                    budget_total_usd=1.0,
                    reserve_pct=0.0,
                    single_action_approval_usd=99.0,
                    require_approval_for_new_paid_tool=False,
                    mode=BudgetMode.WARN,
                    cost_log_path=log_path,
                )
                entry_id = tracker.estimate("paid_video", "generate", 2.0)

                tracker.reserve(entry_id)

                entry = tracker.entries[0]
                self.assertEqual(entry["status"], "reserved")
                self.assertEqual(entry["reserved_usd"], 2.0)
                self.assertTrue(entry["budget_warning"])
                self.assertIn("exceeds usable budget", entry["budget_warning_message"])
                persisted = json.loads(log_path.read_text())
                self.assertTrue(persisted["entries"][0]["budget_warning"])

    def test_approved_tools_persist_across_tracker_restarts(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(cost_log_path=log_path)
            tracker.approve_tool("paid_video")

            restarted = CostTracker(cost_log_path=log_path)

            entry_id = restarted.estimate("paid_video", "generate", 0.01)
            restarted.reserve(entry_id)
            self.assertEqual(restarted.entries[-1]["status"], "reserved")

    def test_for_project_factory_derives_log_path_and_persists_governance_header(self) -> None:
        import tempfile
        from pathlib import Path

        # No override: the factory derives the log path from PROJECTS_DIR.
        # Constructing a tracker writes nothing until an entry is recorded,
        # so this stays hermetic.
        self.assertEqual(
            CostTracker.for_project("X").cost_log_path,
            PROJECTS_DIR / "X" / "artifacts" / "cost_log.json",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            projects_dir = Path(temp_dir) / "projects"
            project_id = "X"

            tracker = CostTracker.for_project(project_id, projects_dir=projects_dir)
            tracker.approve_tool("image_selector")
            entry_id = tracker.estimate("image_selector", "generate", 0.01)
            tracker.reserve(entry_id)
            tracker.reconcile(entry_id, 0.01)

            expected_path = projects_dir / project_id / "artifacts" / "cost_log.json"
            self.assertTrue(expected_path.exists())
            self.assertEqual(tracker.cost_log_path, expected_path)

            budget = OpenMontageConfig.load().budget
            persisted = json.loads(expected_path.read_text())
            self.assertEqual(persisted["budget_total_usd"], budget.total_usd)
            self.assertEqual(persisted["mode"], budget.mode.value)
            self.assertEqual(persisted["reserve_pct"], budget.reserve_pct)
            self.assertEqual(
                persisted["single_action_approval_usd"], budget.single_action_approval_usd
            )

            # Another stage re-opening the same project_id gets the same ledger back.
            reopened = CostTracker.for_project(project_id, projects_dir=projects_dir)
            self.assertEqual(len(reopened.entries), 1)
            self.assertEqual(reopened.entries[0]["id"], entry_id)

    def test_warn_mode_round_trip_persists_schema_valid_cost_log(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(
                budget_total_usd=1.0,
                reserve_pct=0.0,
                single_action_approval_usd=99.0,
                require_approval_for_new_paid_tool=False,
                mode=BudgetMode.WARN,
                cost_log_path=log_path,
            )
            entry_id = tracker.estimate("paid_video", "generate", 2.0)
            tracker.reserve(entry_id)  # over budget in warn mode: recorded, not raised
            tracker.reconcile(entry_id, 2.0)

            persisted = json.loads(log_path.read_text())
            # Fails against the pre-fix schema (mode/reserve_pct/single_action_approval_usd/
            # approved_tools at top level, budget_warning* on entries are all rejected by
            # additionalProperties: false) and passes once the schema accepts them.
            validate_artifact("cost_log", persisted)

    def test_unapproved_tool_blocks_reservation_until_approved(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(
                budget_total_usd=10.0,
                reserve_pct=0.0,
                single_action_approval_usd=0.50,
                require_approval_for_new_paid_tool=True,
                mode=BudgetMode.WARN,
                cost_log_path=log_path,
            )
            entry_id = tracker.estimate("elevenlabs_tts", "narration", 0.18)

            with self.assertRaises(ApprovalRequiredError):
                tracker.reserve(entry_id)

            tracker.approve_tool("elevenlabs_tts")
            tracker.reserve(entry_id)

            self.assertEqual(tracker.entries[0]["status"], "reserved")

    def test_user_approved_flag_waives_single_action_threshold(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(
                budget_total_usd=10.0,
                reserve_pct=0.0,
                single_action_approval_usd=0.50,
                require_approval_for_new_paid_tool=True,
                mode=BudgetMode.WARN,
                cost_log_path=log_path,
            )
            # Tool is already approved (e.g. named in the approved plan) — the
            # first-paid-use guard is clear. The single-action threshold still
            # blocks this batch on its own.
            tracker.approve_tool("video_selector")
            entry_id = tracker.estimate("video_selector", "generate_batch", 2.40)

            with self.assertRaises(ApprovalRequiredError):
                tracker.reserve(entry_id)

            # The user explicitly approved this exact line item at the gate.
            tracker.reserve(entry_id, user_approved=True)

            entry = tracker.entries[0]
            self.assertEqual(entry["status"], "reserved")
            self.assertTrue(entry["user_approved"])

            persisted = json.loads(log_path.read_text())
            self.assertTrue(persisted["entries"][0]["user_approved"])
            validate_artifact("cost_log", persisted)

    def test_approved_plan_reserves_once_at_execution_not_at_the_gate(self) -> None:
        """End-to-end Step 9 handshake: the proposal gate seeds a placeholder
        estimate, approves the tool, and refunds the placeholder (per the
        fixed proposal-director.md Step 9). The stage that actually spends
        (asset-director.md) then reserves its OWN entry for the same
        planned work with user_approved=True. An over-threshold batch must
        reserve cleanly at execution time, and the plan total must land in
        `reserved` exactly once — never doubled by a stranded gate-time
        reservation that nothing ever reconciles."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(
                budget_total_usd=3.0,
                reserve_pct=0.0,
                single_action_approval_usd=0.50,
                require_approval_for_new_paid_tool=True,
                mode=BudgetMode.WARN,
                cost_log_path=log_path,
            )
            plan_total_usd = 1.52

            # --- Proposal Step 6: seed a placeholder matching the plan.
            plan_entry_id = tracker.estimate("video_selector", "generate_batch", plan_total_usd)

            # --- Proposal Step 9: approve the tool, refund the placeholder.
            # Never reserve it — nothing here ever reconciles it.
            tracker.approve_tool("video_selector")
            for entry in tracker.entries:
                if entry["status"] == "estimated":
                    tracker.refund(entry["id"])

            self.assertEqual(tracker.entries[0]["status"], "refunded")
            self.assertEqual(tracker.budget_reserved_usd, 0.0)

            # --- Asset stage: reserves its OWN entry for the same planned
            # work, with user_approved=True. Must not raise even though
            # $1.52 is well over the $0.50 single-action threshold.
            exec_entry_id = tracker.estimate("video_selector", "generate_batch", plan_total_usd)
            self.assertNotEqual(exec_entry_id, plan_entry_id)
            tracker.reserve(exec_entry_id, user_approved=True)

            # Reserved exactly once — the plan total, not double it.
            self.assertEqual(tracker.budget_reserved_usd, plan_total_usd)

            tracker.reconcile(exec_entry_id, plan_total_usd)
            self.assertEqual(tracker.budget_spent_usd, plan_total_usd)
            self.assertEqual(tracker.budget_reserved_usd, 0.0)

            persisted = json.loads(log_path.read_text())
            validate_artifact("cost_log", persisted)


if __name__ == "__main__":
    unittest.main()
