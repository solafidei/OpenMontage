from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.config_model import BudgetMode, OpenMontageConfig
from lib.paths import PROJECTS_DIR
from schemas.artifacts import validate_artifact
from tools.cost_tracker import (
    ApprovalRequiredError,
    BudgetExceededError,
    CostTracker,
    EntryAlreadyTerminalError,
)


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

    # ---- Workstream C acceptance: the documented skill blocks, executed ----

    @staticmethod
    def _documented_arming_total(
        line_items: list[float],
        budget_cap_usd: float,
        reserve_pct: float,
        approved_budget_usd: float | None = None,
    ) -> float:
        """The arming formula exactly as the proposal/idea gates document it
        (skills/pipelines/*/proposal-director.md → 'On Approval — Arm the
        Tracker', point 1). Kept as one helper so the behavioral tests below
        exercise the same arithmetic the skill text instructs."""
        import math

        total_estimated_usd = round(sum(line_items), 4)
        min_workable_usd = (
            math.ceil(total_estimated_usd / (1 - reserve_pct) * 100) / 100 + 0.01
        )
        return approved_budget_usd or max(budget_cap_usd, min_workable_usd)

    def test_documented_arming_formula_reserves_full_plan_in_cap_mode(self) -> None:
        """The pre-fix fallback (`approved_budget_usd or total_estimated_usd`)
        armed the bare estimate, so usable_budget_usd topped out at
        (1 - reserve_pct) x total and the plan's FINAL approved reservation
        could never fit. The documented gross-up must let every planned item
        reserve and reconcile."""
        import tempfile
        from pathlib import Path

        from tools.cost_tracker import BudgetExceededError

        reserve_pct = OpenMontageConfig.load().budget.reserve_pct

        def run_plan(line_items, budget_cap_usd, approved_budget_usd=None):
            with tempfile.TemporaryDirectory() as temp_dir:
                log_path = Path(temp_dir) / "cost_log.json"
                tracker = CostTracker(
                    budget_total_usd=None,
                    reserve_pct=reserve_pct,
                    single_action_approval_usd=0.50,
                    require_approval_for_new_paid_tool=True,
                    mode=BudgetMode.CAP,
                    cost_log_path=log_path,
                )
                tracker.budget_total_usd = self._documented_arming_total(
                    line_items, budget_cap_usd, reserve_pct, approved_budget_usd
                )
                for index, _ in enumerate(line_items):
                    tracker.approve_tool(f"image_selector_{index}")
                for index, estimated_usd in enumerate(line_items):
                    entry_id = tracker.estimate(
                        f"image_selector_{index}", f"plan_item_{index}", estimated_usd
                    )
                    tracker.reserve(entry_id, user_approved=True)
                    tracker.reconcile(entry_id, estimated_usd, success=True)
                return tracker

        # The critic's own scenario: $0.60 / $0.60 / $0.32, cap deliberately
        # below the estimate so the min_workable_usd gross-up branch is taken.
        tracker = run_plan([0.60, 0.60, 0.32], budget_cap_usd=1.00)
        self.assertAlmostEqual(tracker.budget_total_usd, 1.70, places=6)
        self.assertAlmostEqual(tracker.budget_spent_usd, 1.52, places=6)
        for entry in tracker.entries:
            self.assertEqual(entry["status"], "completed")
            self.assertNotIn("budget_warning", entry)

        # Exact-cent boundary: 0.54 / (1 - 0.10) == 0.60 exactly, where a bare
        # ceil() adds zero slack. The designed extra cent must survive it.
        boundary = run_plan([0.27, 0.27], budget_cap_usd=0.30)
        self.assertAlmostEqual(boundary.budget_spent_usd, 0.54, places=6)
        for entry in boundary.entries:
            self.assertEqual(entry["status"], "completed")
            self.assertNotIn("budget_warning", entry)

        # A figure the user NAMED is honoured verbatim — the fix is scoped to
        # the fallback, so an under-provisioned named cap still trips the guard.
        with self.assertRaises(BudgetExceededError):
            run_plan([0.60, 0.60, 0.32], budget_cap_usd=1.00, approved_budget_usd=1.52)

    def test_plan_name_keyed_reserve_passes_first_paid_use_guard(self) -> None:
        """C2: the ledger keys on the PLAN's line-item name. A gate that armed
        `tts_selector` must let the compose stage book narration under
        `tts_selector`; booking the concrete provider name instead is exactly
        the deadlock the old compose-director text instructed."""
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
            tracker.approve_tool("tts_selector")

            entry_id = tracker.estimate(
                "tts_selector", "narration via openai_tts", 0.18
            )
            tracker.reserve(entry_id, user_approved=True)
            self.assertEqual(tracker.entries[-1]["status"], "reserved")
            self.assertEqual(
                tracker.entries[-1]["operation"], "narration via openai_tts"
            )

            # The pre-fix instruction: book under the concrete provider name.
            concrete_id = tracker.estimate("openai_tts", "narration", 0.18)
            with self.assertRaises(ApprovalRequiredError):
                tracker.reserve(concrete_id, user_approved=True)

    def test_documented_booking_rule_failed_call_books_no_phantom_spend(self) -> None:
        """C3: `actual_usd = result.cost_usd or estimated_usd` booked the
        estimate on a FAILED call, and budget_spent_usd counts failed entries —
        phantom spend that shrinks usable budget and stalls the real retry."""
        import tempfile
        from pathlib import Path

        from tools.base_tool import ToolResult

        def book(tracker, entry_id, result, estimated_usd):
            """The canonical booking block from the skill text, executed."""
            reported = result.cost_usd or 0.0
            if result.success:
                actual_usd = reported if reported > 0 else estimated_usd
            else:
                actual_usd = reported
            tracker.reconcile(entry_id, actual_usd, success=result.success)
            return actual_usd

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(
                budget_total_usd=0.80,  # armed per C1 for a single $0.60 item
                reserve_pct=OpenMontageConfig.load().budget.reserve_pct,
                single_action_approval_usd=0.50,
                require_approval_for_new_paid_tool=True,
                mode=BudgetMode.CAP,
                cost_log_path=log_path,
            )
            tracker.approve_tool("video_selector")

            entry_id = tracker.estimate("video_selector", "hero_shot", 0.60)
            tracker.reserve(entry_id, user_approved=True)
            failed = ToolResult(success=False, cost_usd=0.0, error="provider 500")
            self.assertEqual(book(tracker, entry_id, failed, 0.60), 0.0)

            entry = tracker.entries[0]
            self.assertEqual(entry["status"], "failed")
            self.assertEqual(entry["actual_usd"], 0.0)
            self.assertEqual(tracker.budget_spent_usd, 0.0)

            # The retry the phantom spend used to block.
            retry_id = tracker.estimate("video_selector", "hero_shot retry", 0.60)
            tracker.reserve(retry_id, user_approved=True)
            self.assertEqual(tracker.entries[-1]["status"], "reserved")

            # Success reporting $0.00 on a paid estimate books the estimate.
            self.assertEqual(
                book(tracker, retry_id, ToolResult(success=True, cost_usd=0.0), 0.60),
                0.60,
            )
            self.assertEqual(tracker.budget_spent_usd, 0.60)

            # A positive report is authoritative.
            third_id = tracker.estimate("video_selector", "insert", 0.05)
            tracker.reserve(third_id, user_approved=True)
            self.assertEqual(
                book(tracker, third_id, ToolResult(success=True, cost_usd=0.04), 0.05),
                0.04,
            )
            self.assertEqual(tracker.entries[-1]["actual_usd"], 0.04)

    def test_music_gen_estimate_contract(self) -> None:
        """C4's behavioral leg: music_gen.estimate_cost raises on a missing
        duration_seconds, not on a missing prompt — so the documentary-montage
        examples must carry duration_seconds in the inputs dict."""
        from tools.audio.music_gen import MusicGen

        self.assertEqual(
            MusicGen().estimate_cost({"prompt": "x", "duration_seconds": 90}), 0.15
        )
        with self.assertRaises(ValueError):
            MusicGen().estimate_cost({"prompt": "x"})
        # A promptless dict carrying duration_seconds returns normally — the
        # raise keys on duration_seconds alone.
        self.assertEqual(MusicGen().estimate_cost({"duration_seconds": 90}), 0.15)

    # ---- Workstream G acceptance: the two non-waiver clauses of reserve(),
    # ---- and the failed-and-charged reconcile path ----

    def test_user_approved_does_not_waive_budget_cap(self) -> None:
        """G1: `user_approved=True` waives the single-action threshold ONLY.
        In cap mode an over-budget reservation still raises, and the raise
        lands BEFORE the status mutation — the entry must stay `estimated`
        holding no budget, in memory and on disk."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(
                budget_total_usd=1.0,
                reserve_pct=0.0,
                # Both other clauses provably disarmed: the threshold is far
                # above the estimate and the first-paid-use guard is off, so
                # only the budget check can be the actor here.
                single_action_approval_usd=99.0,
                require_approval_for_new_paid_tool=False,
                mode=BudgetMode.CAP,
                cost_log_path=log_path,
            )
            entry_id = tracker.estimate("paid_video", "generate", 2.0)

            with self.assertRaises(BudgetExceededError):
                tracker.reserve(entry_id, user_approved=True)

            entry = tracker.entries[0]
            self.assertEqual(entry["id"], entry_id)
            self.assertEqual(entry["status"], "estimated")
            self.assertEqual(entry["reserved_usd"], 0.0)
            self.assertEqual(tracker.budget_reserved_usd, 0.0)

            persisted = json.loads(log_path.read_text())
            self.assertEqual(persisted["entries"][0]["status"], "estimated")
            self.assertEqual(persisted["entries"][0]["reserved_usd"], 0.0)
            self.assertEqual(persisted["budget_reserved_usd"], 0.0)
            validate_artifact("cost_log", persisted)

    def test_user_approved_does_not_waive_first_paid_use_guard(self) -> None:
        """G1: `user_approved=True` does not stand in for `approve_tool`.
        The estimate sits UNDER the single-action threshold, so the threshold
        clause cannot be the actor — only the first-paid-use guard can."""
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
            # Deliberately NOT approved.
            entry_id = tracker.estimate("elevenlabs_tts", "narration", 0.18)

            with self.assertRaises(ApprovalRequiredError) as caught:
                tracker.reserve(entry_id, user_approved=True)
            # Distinguishes this from the threshold error's
            # "exceeds single-action threshold".
            self.assertIn("First paid use", str(caught.exception))
            self.assertEqual(tracker.entries[0]["status"], "estimated")

            # Approving the tool — and nothing else — unblocks the same call,
            # proving the guard, and only the guard, was the blocker.
            tracker.approve_tool("elevenlabs_tts")
            tracker.reserve(entry_id, user_approved=True)

            entry = tracker.entries[0]
            self.assertEqual(entry["status"], "reserved")
            self.assertEqual(entry["reserved_usd"], 0.18)
            self.assertTrue(entry["user_approved"])

            persisted = json.loads(log_path.read_text())
            self.assertEqual(persisted["entries"][0]["status"], "reserved")
            validate_artifact("cost_log", persisted)

    def test_reconcile_failure_lands_failed_state_and_counts_real_spend(self) -> None:
        """G6: a failed call that WAS charged. `failed` is terminal (the six
        manifests' compose criterion), and money spent on a failure is still
        spent — budget_spent_usd counts FAILED alongside COMPLETED."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(
                budget_total_usd=10.0,
                reserve_pct=0.0,
                single_action_approval_usd=99.0,
                require_approval_for_new_paid_tool=False,
                mode=BudgetMode.WARN,
                cost_log_path=log_path,
            )
            entry_id = tracker.estimate("video_selector", "generate", 0.60)
            tracker.reserve(entry_id)

            # The provider billed a generation that then failed.
            tracker.reconcile(entry_id, 0.60, success=False)

            entry = tracker.entries[0]
            self.assertEqual(entry["status"], "failed")
            self.assertAlmostEqual(entry["actual_usd"], 0.60)
            self.assertEqual(entry["reserved_usd"], 0.0)
            self.assertAlmostEqual(tracker.budget_spent_usd, 0.60)
            self.assertEqual(tracker.budget_reserved_usd, 0.0)
            self.assertEqual(tracker.non_terminal_entries(), [])

            persisted = json.loads(log_path.read_text())
            validate_artifact("cost_log", persisted)
            self.assertEqual(persisted["entries"][0]["status"], "failed")
            self.assertAlmostEqual(persisted["budget_spent_usd"], 0.60)

            # Failed and completed spend aggregate.
            second_id = tracker.estimate("video_selector", "generate retry", 0.60)
            tracker.reserve(second_id)
            tracker.reconcile(second_id, 0.60, success=True)

            self.assertEqual(tracker.entries[1]["status"], "completed")
            self.assertAlmostEqual(tracker.budget_spent_usd, 1.20)
            self.assertEqual(tracker.budget_reserved_usd, 0.0)

            persisted = json.loads(log_path.read_text())
            validate_artifact("cost_log", persisted)
            self.assertAlmostEqual(persisted["budget_spent_usd"], 1.20)

    # ---- Workstream D acceptance: the cap arithmetic the six new manifests
    # ---- document, and the all-$0 ceremony D0 ruled safe ----

    @staticmethod
    def _manifest_orchestration(pipeline: str) -> dict:
        """The live `orchestration:` block of a pipeline manifest.

        Read at test time on purpose (no rate literals below): editing
        `budget_per_output_minute_usd` in the manifest must flip these
        tests rather than leave a stale copy of the number passing here.
        """
        import yaml

        raw = yaml.safe_load(
            (ROOT / "pipeline_defs" / f"{pipeline}.yaml").read_text(encoding="utf-8")
        )
        return raw["orchestration"]

    @staticmethod
    def _documented_cap_usd(
        flat_usd: float, rate_usd: float, output_minutes: float
    ) -> float:
        """The default gate cap exactly as the D skills document it:
        `max(budget_default_usd, budget_per_output_minute_usd x output_minutes)`.
        The flat figure is a floor, never a ceiling."""
        return max(flat_usd, round(rate_usd * output_minutes, 2))

    def test_localization_dub_cap_scales_per_localized_minute(self) -> None:
        """D1.1: localization-dub bills per LOCALIZED minute — source duration
        x language count — so a 2-language run of a 5-minute source is capped
        on 10 output minutes, not 5. Rates come from the live manifest."""
        orchestration = self._manifest_orchestration("localization-dub")
        flat_usd = orchestration["budget_default_usd"]
        rate_usd = orchestration["budget_per_output_minute_usd"]

        source_minutes = 5.0

        # The language multiplier IS the semantics under test.
        two_language_minutes = source_minutes * 2
        self.assertEqual(two_language_minutes, 10.0)
        one_language_minutes = source_minutes * 1

        cap_two = self._documented_cap_usd(flat_usd, rate_usd, two_language_minutes)
        cap_one = self._documented_cap_usd(flat_usd, rate_usd, one_language_minutes)

        # At the manifest's live rate the per-minute branch wins for two
        # languages (so the cap tracks the extra language)...
        self.assertGreater(cap_two, flat_usd)
        self.assertAlmostEqual(cap_two, round(rate_usd * two_language_minutes, 2))
        # ...and the flat floor wins for one, which is what keeps a short
        # single-language dub from being capped below workable.
        self.assertAlmostEqual(cap_one, flat_usd)
        self.assertGreater(cap_one, round(rate_usd * one_language_minutes, 2))

        # Adding the second language raised the cap: the multiplier is live,
        # not decorative.
        self.assertGreater(cap_two, cap_one)

    def test_podcast_output_minutes_sum_across_deliverables(self) -> None:
        """D1.2: podcast-repurpose caps on the SUM of every deliverable's
        runtime — 6 clips x 0.5 min plus a 12-minute companion is 15 output
        minutes, not 12 and not 3. Rates come from the live manifest."""
        orchestration = self._manifest_orchestration("podcast-repurpose")
        flat_usd = orchestration["budget_default_usd"]
        rate_usd = orchestration["budget_per_output_minute_usd"]

        clip_count = 6
        clip_minutes = 0.5
        companion_minutes = 12.0

        output_minutes = clip_count * clip_minutes + companion_minutes
        self.assertEqual(output_minutes, 15.0)

        cap = self._documented_cap_usd(flat_usd, rate_usd, output_minutes)

        # The summed-deliverable branch wins over the flat floor at the
        # manifest's live rate.
        self.assertGreater(cap, flat_usd)
        self.assertAlmostEqual(cap, round(rate_usd * output_minutes, 2))

        # Counting only the companion — the drift this locks out — would
        # under-cap the run by the whole clip set.
        companion_only_cap = self._documented_cap_usd(
            flat_usd, rate_usd, companion_minutes
        )
        self.assertLess(companion_only_cap, cap)

    def test_zero_estimate_plan_arms_and_reconciles_clean(self) -> None:
        """D0's load-bearing ruling, executed: the FULL ledger ceremony on a
        pipeline that cannot spend (clip-factory: every tool prices $0) is
        safe. Same arming formula, same approve/estimate/reserve/reconcile
        blocks, all-$0 data — no exception, no phantom spend, no entry left
        holding budget, and a schema-valid cost_log on disk. If any of this
        raised, D1.6's `$0` compose snapshot would be unprovable."""
        import tempfile
        from pathlib import Path

        orchestration = self._manifest_orchestration("clip-factory")
        budget_cap_usd = orchestration["budget_default_usd"]
        # D1.6: the rate key is deliberately absent — no paid tools to scale.
        self.assertNotIn("budget_per_output_minute_usd", orchestration)

        reserve_pct = OpenMontageConfig.load().budget.reserve_pct

        # The clip-factory shape: one batched line item per tool batch,
        # each priced $0.00 — never one entry per clip.
        plan = [
            ("subtitle_gen", "subtitles x 12 clips", 0.0),
            ("audio_enhance", "enhance x 12 clips", 0.0),
            ("video_compose", "render x 12 clips", 0.0),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(
                budget_total_usd=None,
                reserve_pct=reserve_pct,
                single_action_approval_usd=0.50,
                require_approval_for_new_paid_tool=True,
                mode=BudgetMode.CAP,
                cost_log_path=log_path,
            )

            # C1's canonical arming, run on an all-$0 plan: min_workable_usd
            # is the bare +$0.01, so the manifest's flat cap wins and the
            # gross-up branch is provably inert rather than degenerate.
            tracker.budget_total_usd = self._documented_arming_total(
                [estimated_usd for _, _, estimated_usd in plan],
                budget_cap_usd,
                reserve_pct,
            )
            self.assertAlmostEqual(tracker.budget_total_usd, budget_cap_usd, places=6)

            for tool, operation, estimated_usd in plan:
                tracker.approve_tool(tool)
                entry_id = tracker.estimate(tool, operation, estimated_usd)
                tracker.reserve(entry_id, user_approved=True)
                tracker.reconcile(entry_id, estimated_usd, success=True)

            self.assertEqual(tracker.cost_snapshot()["total_spent_usd"], 0.0)
            self.assertEqual(tracker.cost_snapshot()["total_reserved_usd"], 0.0)
            self.assertEqual(tracker.non_terminal_entries(), [])
            self.assertEqual(len(tracker.entries), len(plan))
            for entry in tracker.entries:
                self.assertEqual(entry["status"], "completed")
                self.assertEqual(entry["actual_usd"], 0.0)
                self.assertNotIn("budget_warning", entry)

            persisted = json.loads(log_path.read_text())
            self.assertEqual(persisted["budget_spent_usd"], 0.0)
            self.assertEqual(
                [entry["status"] for entry in persisted["entries"]],
                ["completed"] * len(plan),
            )
            validate_artifact("cost_log", persisted)

    # ---- reel-batch (#49): the three guarantees that only show up under
    # ---- failure. A batch is N deliverables on one ledger, so "the run
    # ---- spent $X" is no longer a single number anyone can check.

    # A reel is <= 10 seconds (spec §5), which is where every figure below
    # comes from. Derived, not copied: change the reel length and these
    # tests move with it.
    REEL_SECONDS = 10.0

    @classmethod
    def _reel_batch_output_minutes(cls, reels: int) -> float:
        return reels * cls.REEL_SECONDS / 60.0

    def test_reel_batch_output_minutes_sum_across_reels(self) -> None:
        """The cap is priced on the batch, not on one reel.

        Five ten-second reels are 0.8333 output minutes. At the manifest's
        live rate that prices below the flat floor, so the floor governs —
        and the floor must still clear `min_workable_usd` for the spec's
        worst-case $0.50 sitting, or a bare "approve" drops the operator into
        the below-minimum conversation on a run that was always affordable.
        """
        orchestration = self._manifest_orchestration("reel-batch")
        flat_usd = orchestration["budget_default_usd"]
        rate_usd = orchestration["budget_per_output_minute_usd"]
        reserve_pct = OpenMontageConfig.load().budget.reserve_pct

        five_reel_minutes = self._reel_batch_output_minutes(5)
        self.assertAlmostEqual(five_reel_minutes, 0.8333, places=4)

        cap = self._documented_cap_usd(flat_usd, rate_usd, five_reel_minutes)

        # The floor wins at five reels — the rate branch is well under it.
        self.assertAlmostEqual(cap, flat_usd)
        self.assertGreater(cap, round(rate_usd * five_reel_minutes, 2))

        # And the floor clears the arming minimum for the spec's worst case:
        # a full five-reel pool shortfall, 5 x $0.10 on the pinned route.
        worst_case_estimate_usd = 0.50
        armed = self._documented_arming_total(
            [worst_case_estimate_usd], cap, reserve_pct
        )
        self.assertAlmostEqual(armed, cap)
        self.assertGreater(
            cap,
            math.ceil(worst_case_estimate_usd / (1 - reserve_pct) * 100) / 100 + 0.01,
            "the flat cap no longer clears min_workable_usd for a $0.50 sitting — "
            "a bare approve would force the below-minimum conversation",
        )

    def test_reel_batch_cap_flips_to_the_rate_on_a_large_batch(self) -> None:
        """The other regime. The manifest's flat figure is a floor, not a ceiling.

        Both branches must be asserted or the test proves only that a
        constant equals itself: at five reels the floor governs and the rate
        is decorative, so only a batch large enough to cross over shows the
        rate is live at all. Twenty ten-second reels is 3.3333 minutes.
        """
        orchestration = self._manifest_orchestration("reel-batch")
        flat_usd = orchestration["budget_default_usd"]
        rate_usd = orchestration["budget_per_output_minute_usd"]

        twenty_reel_minutes = self._reel_batch_output_minutes(20)
        self.assertAlmostEqual(twenty_reel_minutes, 3.3333, places=4)

        cap = self._documented_cap_usd(flat_usd, rate_usd, twenty_reel_minutes)

        self.assertAlmostEqual(cap, round(rate_usd * twenty_reel_minutes, 2))
        self.assertGreater(cap, flat_usd)
        # The crossover is real and sits between the two batch sizes.
        self.assertGreater(
            cap, self._documented_cap_usd(flat_usd, rate_usd,
                                          self._reel_batch_output_minutes(5))
        )

    def test_reel_batch_zero_cost_sitting_still_reconciles_to_a_cost_log(self) -> None:
        """Spec §6 item 23: the full ceremony on a sitting that spends nothing.

        Under R8 cutaways are free-first, so the TYPICAL reel batch estimates
        $0.00 — the pool covers every cut and no AI fires. That is the common
        case, not the edge case, and it must still arm, book and reconcile to
        a schema-valid terminal `cost_log`. A pipeline whose normal run cannot
        produce an auditable ledger has no audit trail at all.
        """
        import tempfile

        orchestration = self._manifest_orchestration("reel-batch")
        budget_cap_usd = orchestration["budget_default_usd"]
        reserve_pct = OpenMontageConfig.load().budget.reserve_pct

        # Batched per tool, not per reel: these are the $0 stages, and the
        # per-reel divergence below is only justified for entries that can
        # actually diverge.
        plan = [
            ("footage_library", "index pool x 1 sitting", 0.0),
            ("beat_grid", "beat analysis x 5 tracks", 0.0),
            ("subtitle_gen", "captions x 5 reels", 0.0),
            ("video_compose", "render x 5 reels", 0.0),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(
                budget_total_usd=None,
                reserve_pct=reserve_pct,
                single_action_approval_usd=0.50,
                require_approval_for_new_paid_tool=True,
                mode=BudgetMode.CAP,
                cost_log_path=log_path,
            )
            tracker.budget_total_usd = self._documented_arming_total(
                [estimated_usd for _, _, estimated_usd in plan],
                budget_cap_usd,
                reserve_pct,
            )
            self.assertAlmostEqual(tracker.budget_total_usd, budget_cap_usd, places=6)

            for tool, operation, estimated_usd in plan:
                entry_id = tracker.estimate(tool, operation, estimated_usd)
                tracker.reserve(entry_id, user_approved=True)
                tracker.reconcile(entry_id, 0.0, success=True)

            self.assertEqual(tracker.non_terminal_entries(), [])
            self.assertAlmostEqual(tracker.budget_spent_usd, 0.0)
            self.assertAlmostEqual(tracker.budget_reserved_usd, 0.0)

            persisted = json.loads(log_path.read_text(encoding="utf-8"))
            validate_artifact("cost_log", persisted)
            self.assertEqual(
                [entry["status"] for entry in persisted["entries"]],
                ["completed"] * len(plan),
            )
            self.assertAlmostEqual(persisted["budget_spent_usd"], 0.0)

    def test_partial_reel_batch_reconciles_honestly(self) -> None:
        """A batch aborted at reel four, settled without lying in either direction.

        Two reels are stranded in different states and the checkpoint protocol
        resolves them differently: reel 4 was RESERVED, so the call may have
        fired and been billed — reconcile at its estimate with success=False,
        because overstating is the safe direction for a budget guard. Reel 5
        was only ESTIMATED, a placeholder that never executed — refund it, or
        it holds phantom spend against the retry.
        """
        import tempfile

        orchestration = self._manifest_orchestration("reel-batch")
        reserve_pct = OpenMontageConfig.load().budget.reserve_pct
        per_reel_usd = 0.10

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(
                budget_total_usd=None,
                reserve_pct=reserve_pct,
                single_action_approval_usd=0.50,
                require_approval_for_new_paid_tool=True,
                mode=BudgetMode.CAP,
                cost_log_path=log_path,
            )
            tracker.budget_total_usd = self._documented_arming_total(
                [per_reel_usd] * 5,
                orchestration["budget_default_usd"],
                reserve_pct,
            )
            tracker.approve_tool("video_selector")

            # One entry PER REEL — the divergence from the batching rule that
            # test (c) below exists to justify.
            entries = {
                reel: tracker.estimate(
                    "video_selector", f"cutaway_reel_{reel:02d}_kling_video", per_reel_usd
                )
                for reel in range(1, 6)
            }
            for reel in range(1, 5):  # reel 5 is never reserved
                tracker.reserve(entries[reel], user_approved=True)

            for reel in range(1, 4):
                tracker.reconcile(entries[reel], per_reel_usd, success=True)

            # --- the abort lands here ---
            stranded = tracker.non_terminal_entries()
            self.assertEqual(
                {entry["id"] for entry in stranded},
                {entries[4], entries[5]},
                "non_terminal_entries must name exactly the two stranded reels",
            )
            self.assertEqual(
                {entry["id"]: entry["status"] for entry in stranded},
                {entries[4]: "reserved", entries[5]: "estimated"},
            )

            # --- resolution, per skills/meta/checkpoint-protocol.md ---
            reel_four = next(e for e in stranded if e["id"] == entries[4])
            tracker.reconcile(entries[4], reel_four["estimated_usd"], success=False)
            tracker.refund(entries[5])

            self.assertEqual(tracker.non_terminal_entries(), [])
            # Three reels that finished, plus the one that may have billed.
            # The refunded placeholder contributes nothing.
            self.assertAlmostEqual(tracker.budget_spent_usd, 4 * per_reel_usd)
            self.assertAlmostEqual(tracker.budget_reserved_usd, 0.0)

            persisted = json.loads(log_path.read_text(encoding="utf-8"))
            validate_artifact("cost_log", persisted)
            self.assertAlmostEqual(persisted["budget_spent_usd"], 4 * per_reel_usd)
            # Visible under `pytest -k reel_batch -v -s`, beside the control's
            # figure below — the two numbers are the point of the pair.
            print(
                f"\n  per-reel booking, aborted at reel 4: "
                f"spent ${tracker.budget_spent_usd:.2f} "
                f"(3 done + 1 possibly billed, 1 refunded)"
            )
            self.assertEqual(
                {entry["id"]: entry["status"] for entry in persisted["entries"]},
                {
                    entries[1]: "completed",
                    entries[2]: "completed",
                    entries[3]: "completed",
                    entries[4]: "failed",
                    entries[5]: "refunded",
                },
            )

    def test_reel_batch_single_entry_cannot_reconcile_a_partial_batch(self) -> None:
        """The negative control, and the whole justification for per-reel booking.

        Booking one entry for the batch is what the batching rule would ask
        for. Abort at reel three and there is no `reconcile` argument that is
        both terminal and honest: settle at the estimate and the ledger claims
        spend that never happened, and the correction is refused because the
        entry has already settled. The overstatement is larger than a whole
        reel — which is the number that matters in cap mode, where phantom
        spend shrinks the budget the retry has to work in.
        """
        import tempfile

        per_reel_usd = 0.10
        reels_completed = 3
        batch_estimate_usd = 0.50

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "cost_log.json"
            tracker = CostTracker(
                budget_total_usd=2.00,
                reserve_pct=0.0,
                single_action_approval_usd=99.0,
                require_approval_for_new_paid_tool=False,
                mode=BudgetMode.CAP,
                cost_log_path=log_path,
            )
            entry_id = tracker.estimate(
                "video_selector", "cutaways x 5 reels kling_video", batch_estimate_usd
            )
            tracker.reserve(entry_id, user_approved=True)

            # Three of five reels got their cutaway before the abort.
            honest_usd = reels_completed * per_reel_usd

            # The only terminal move available: settle at the estimate.
            tracker.reconcile(entry_id, batch_estimate_usd, success=False)

            overstatement_usd = tracker.budget_spent_usd - honest_usd
            self.assertAlmostEqual(overstatement_usd, 0.20)
            self.assertGreater(
                overstatement_usd,
                per_reel_usd,
                "a single batched entry must overstate by more than one reel — "
                "otherwise per-reel booking buys nothing",
            )

            # And the correction is refused BY TYPE. Asserting on the class
            # rather than the message ties this to tools/cost_tracker.py's
            # terminal guard, not to wording anyone may reword.
            with self.assertRaises(EntryAlreadyTerminalError):
                tracker.reconcile(entry_id, honest_usd, success=False)

            self.assertAlmostEqual(tracker.budget_spent_usd, batch_estimate_usd)
            print(
                f"\n  one batched entry, aborted at reel 3: "
                f"spent ${tracker.budget_spent_usd:.2f} "
                f"against ${honest_usd:.2f} actually incurred "
                f"— ${overstatement_usd:.2f} phantom, and unfixable"
            )

            # Contrast: five per-reel entries settle to the truth exactly.
            per_reel_tracker = CostTracker(
                budget_total_usd=2.00,
                reserve_pct=0.0,
                single_action_approval_usd=99.0,
                require_approval_for_new_paid_tool=False,
                mode=BudgetMode.CAP,
                cost_log_path=Path(temp_dir) / "per_reel.json",
            )
            per_reel_ids = [
                per_reel_tracker.estimate(
                    "video_selector", f"cutaway_reel_{reel:02d}_kling_video", per_reel_usd
                )
                for reel in range(1, 6)
            ]
            for entry in per_reel_ids[:reels_completed]:
                per_reel_tracker.reserve(entry, user_approved=True)
                per_reel_tracker.reconcile(entry, per_reel_usd, success=True)
            for entry in per_reel_ids[reels_completed:]:
                per_reel_tracker.refund(entry)

            self.assertAlmostEqual(per_reel_tracker.budget_spent_usd, honest_usd)
            self.assertEqual(per_reel_tracker.non_terminal_entries(), [])


if __name__ == "__main__":
    unittest.main()
