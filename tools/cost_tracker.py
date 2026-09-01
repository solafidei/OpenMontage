"""Cost tracker core: estimate, reserve, reconcile, and persist to cost_log.json.

Implements the budget governance rules from the spec:
- Every paid operation produces a preflight estimate
- The orchestrator reserves estimated budget before execution
- Budget overruns trigger pauses (in warn/cap mode)
- Actual spend is reconciled when the tool finishes or fails
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import fcntl
except ImportError:  # non-POSIX (native Windows)
    fcntl = None  # type: ignore[assignment]

from lib.config_model import BudgetMode, OpenMontageConfig
from lib.paths import PROJECTS_DIR

logger = logging.getLogger(__name__)

# One warning per process when advisory locking is unavailable (see _locked).
_LOCKING_WARNING_EMITTED = False


class EntryStatus(str, Enum):
    ESTIMATED = "estimated"
    RESERVED = "reserved"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class BudgetExceededError(Exception):
    """Raised when an operation would exceed the budget in cap mode."""
    pass


class ApprovalRequiredError(Exception):
    """Raised when an operation needs user approval before proceeding."""
    pass


class CostLogCorruptedError(Exception):
    """cost_log.json exists but cannot be parsed. Never silently reset."""
    pass


class EntryAlreadyTerminalError(Exception):
    """A mutator would overwrite an entry that already reached a terminal state.

    Terminal-vs-terminal writes cannot be resolved by ``_pick_entry`` — every
    terminal status shares one lifecycle rank, so the *value* (actual_usd,
    reserved_usd) of a settled money record would be silently replaced by
    whichever writer ran last. Two agents resolving the same stranded entry
    by different rules (the recovery workflow ``non_terminal_entries``
    documents) is exactly that case, so the second one is stopped here
    instead of zeroing billed spend.
    """
    pass


# Lifecycle rank used when the same entry id exists in memory and on disk:
# a terminal status never regresses to a pre-terminal one.
_STATUS_RANK = {
    EntryStatus.ESTIMATED.value: 0,
    EntryStatus.RESERVED.value: 1,
    EntryStatus.COMPLETED.value: 2,
    EntryStatus.FAILED.value: 2,
    EntryStatus.REFUNDED.value: 2,
}

# Statuses that settle an entry: rank 2 above. A settled entry is a money
# record, not a work item — see EntryAlreadyTerminalError.
_TERMINAL_STATUSES = frozenset({
    EntryStatus.COMPLETED.value,
    EntryStatus.FAILED.value,
    EntryStatus.REFUNDED.value,
})

# Entry fields the budget arithmetic sums; a non-number here would raise a
# bare TypeError deep inside a property, so _validate_ledger_shape rejects it.
_NUMERIC_ENTRY_FIELDS = ("estimated_usd", "reserved_usd", "actual_usd")


class CostTracker:
    """Tracks estimated, reserved, and actual costs for a pipeline project.

    Every mutation runs inside a lock-reload-merge-mutate-save critical
    section (see ``_locked``), so several processes may share one
    ``cost_log.json`` without erasing each other's spend. The lock is
    advisory: this only holds while *all* writes go through ``CostTracker``.
    Never hand-edit ``cost_log.json`` — it is the money audit log.
    """

    def __init__(
        self,
        budget_total_usd: Optional[float] = None,
        reserve_pct: float = 0.10,
        single_action_approval_usd: float = 0.50,
        require_approval_for_new_paid_tool: bool = True,
        mode: BudgetMode = BudgetMode.WARN,
        cost_log_path: Optional[Path] = None,
    ) -> None:
        if budget_total_usd is None:
            # config.yaml is the single source of the default budget — no
            # duplicated constant here to drift away from BudgetConfig.
            budget_total_usd = OpenMontageConfig.load().budget.total_usd
        # Backing field written directly: a defaulted/constructed budget is
        # NOT "dirty", so it yields to a persisted armed header on merge.
        self._budget_total_usd = budget_total_usd
        self._budget_dirty = False
        self.reserve_pct = reserve_pct
        self.single_action_approval_usd = single_action_approval_usd
        self.require_approval_for_new_paid_tool = require_approval_for_new_paid_tool
        self.mode = mode
        self.cost_log_path = cost_log_path
        self.entries: list[dict[str, Any]] = []
        self._approved_tools: set[str] = set()

        if cost_log_path and cost_log_path.exists():
            self._load()

    @property
    def budget_total_usd(self) -> float:
        return self._budget_total_usd

    @budget_total_usd.setter
    def budget_total_usd(self, value: float) -> None:
        """Arming the budget explicitly makes the local value authoritative.

        The proposal gate does ``tracker.budget_total_usd = <approved>``;
        that assignment must survive a merge against a stale disk header.
        """
        self._budget_total_usd = value
        self._budget_dirty = True

    @classmethod
    def for_project(
        cls,
        project_id: str,
        *,
        projects_dir: Optional[Path] = None,
    ) -> "CostTracker":
        """Open the project's cost tracker in one line.

        Reads the global budget config block (mode, total, reserve percent,
        single-action approval threshold, new-paid-tool approval) and derives
        the log path from the project workspace convention —
        ``<projects_dir>/<project_id>/artifacts/cost_log.json`` — so any
        stage can call this again with the same project_id to re-open the
        same persisted ledger.
        """
        cfg = OpenMontageConfig.load()
        base = projects_dir if projects_dir is not None else PROJECTS_DIR
        log_path = base / project_id / "artifacts" / "cost_log.json"
        return cls(
            budget_total_usd=cfg.budget.total_usd,
            reserve_pct=cfg.budget.reserve_pct,
            single_action_approval_usd=cfg.budget.single_action_approval_usd,
            require_approval_for_new_paid_tool=cfg.budget.require_approval_for_new_paid_tool,
            mode=cfg.budget.mode,
            cost_log_path=log_path,
        )

    # ---- Budget calculations ----

    @property
    def budget_reserved_usd(self) -> float:
        return sum(
            e.get("reserved_usd", 0.0)
            for e in self.entries
            if e["status"] == EntryStatus.RESERVED.value
        )

    @property
    def budget_spent_usd(self) -> float:
        return sum(
            e.get("actual_usd", 0.0)
            for e in self.entries
            if e["status"] in (EntryStatus.COMPLETED.value, EntryStatus.FAILED.value)
        )

    @property
    def budget_remaining_usd(self) -> float:
        return self.budget_total_usd - self.budget_spent_usd - self.budget_reserved_usd

    @property
    def usable_budget_usd(self) -> float:
        """Budget minus the reserve holdback."""
        holdback = self.budget_total_usd * self.reserve_pct
        return max(0.0, self.budget_remaining_usd - holdback)

    def cost_snapshot(self) -> dict[str, float]:
        return {
            "total_spent_usd": round(self.budget_spent_usd, 4),
            "total_reserved_usd": round(self.budget_reserved_usd, 4),
            "budget_remaining_usd": round(self.budget_remaining_usd, 4),
        }

    # ---- Core operations ----

    def estimate(self, tool: str, operation: str, estimated_usd: float) -> str:
        """Record an estimate. Returns entry ID."""
        entry_id = self._new_id()
        with self._locked():
            self.entries.append({
                "id": entry_id,
                "tool": tool,
                "operation": operation,
                "status": EntryStatus.ESTIMATED.value,
                "estimated_usd": round(estimated_usd, 4),
                "reserved_usd": 0.0,
                "actual_usd": 0.0,
                "timestamp": self._now(),
            })
            self._save()
        return entry_id

    def reserve(
        self, entry_id: str, *, user_approved: bool = False, force: bool = False
    ) -> None:
        """Reserve budget for an estimated entry.

        Raises BudgetExceededError in cap mode, or ApprovalRequiredError
        when the action exceeds the single-action approval threshold.

        ``user_approved=True`` waives the single-action threshold for THIS
        entry only — use it when the user explicitly approved this exact
        line item (e.g. at the proposal gate). It does not waive the
        first-paid-use guard (call ``approve_tool`` for that) or the budget
        check. The flag persists on the entry so the approval is auditable
        in cost_log.json.

        Raises EntryAlreadyTerminalError if the entry has already settled
        (another process reconciled or refunded it). ``force=True`` overrides
        that guard and logs the overwrite; never use it to "retry" a settled
        entry — create a new one.
        """
        with self._locked():
            entry = self._find(entry_id)
            self._guard_terminal(entry, "reserve", force)
            estimated = entry["estimated_usd"]

            # Check single-action approval threshold
            if estimated > self.single_action_approval_usd and not user_approved:
                if self.mode != BudgetMode.OBSERVE:
                    raise ApprovalRequiredError(
                        f"Action costs ${estimated:.2f}, exceeds "
                        f"single-action threshold ${self.single_action_approval_usd:.2f}"
                    )

            # Check new paid tool approval
            if self.require_approval_for_new_paid_tool and estimated > 0:
                if entry["tool"] not in self._approved_tools:
                    if self.mode != BudgetMode.OBSERVE:
                        raise ApprovalRequiredError(
                            f"First paid use of tool {entry['tool']!r} requires approval"
                        )

            # Check budget. Runs after _locked()'s reload-merge, so it sees
            # every other process's persisted spend, not a stale view.
            if estimated > self.usable_budget_usd:
                message = (
                    f"Reservation of ${estimated:.2f} exceeds usable budget "
                    f"${self.usable_budget_usd:.2f}"
                )
                if self.mode == BudgetMode.CAP:
                    raise BudgetExceededError(message)
                if self.mode == BudgetMode.WARN:
                    entry["budget_warning"] = True
                    entry["budget_warning_message"] = message

            entry["status"] = EntryStatus.RESERVED.value
            entry["reserved_usd"] = estimated
            if user_approved:
                entry["user_approved"] = True
            entry["timestamp"] = self._now()
            self._save()

    def approve_tool(self, tool: str) -> None:
        """Mark a tool as approved for paid operations."""
        with self._locked():
            self._approved_tools.add(tool)
            self._save()

    def reconcile(
        self,
        entry_id: str,
        actual_usd: float,
        success: bool = True,
        *,
        force: bool = False,
    ) -> None:
        """Reconcile actual spend after tool execution.

        Raises EntryAlreadyTerminalError if the entry already settled —
        double-booking a reconciled entry silently replaces one billed figure
        with another. ``force=True`` overrides the guard and logs the
        overwrite; use it only to correct a record you know is wrong.
        """
        with self._locked():
            entry = self._find(entry_id)
            self._guard_terminal(entry, "reconcile", force)
            entry["status"] = (
                EntryStatus.COMPLETED.value if success else EntryStatus.FAILED.value
            )
            entry["actual_usd"] = round(actual_usd, 4)
            entry["reserved_usd"] = 0.0
            entry["timestamp"] = self._now()
            self._save()

    def refund(self, entry_id: str, *, force: bool = False) -> None:
        """Cancel a reservation without executing.

        Raises EntryAlreadyTerminalError if the entry already settled —
        refunding a `completed` entry zeroes real billed spend out of the
        budget guard's view. ``force=True`` overrides the guard and logs the
        overwrite; use it only to correct a record you know is wrong.
        """
        with self._locked():
            entry = self._find(entry_id)
            self._guard_terminal(entry, "refund", force)
            entry["status"] = EntryStatus.REFUNDED.value
            entry["reserved_usd"] = 0.0
            entry["timestamp"] = self._now()
            self._save()

    def non_terminal_entries(self) -> list[dict[str, Any]]:
        """Entries still holding or awaiting budget: status estimated or reserved.

        A `reserved` entry with no live owner (a crash between reserve and
        reconcile) consumes usable_budget_usd until resolved. NEVER resolve
        one automatically — the ledger cannot know whether the interrupted
        call was billed. Resolution rules for the agent:
          - output exists on disk / provider confirmed the charge:
              reconcile(id, estimated_or_known_actual, success=True|False)
          - provider confirmed no charge, or the call never fired:
              refund(id)
          - unknowable: reconcile at the estimate with success=False —
            overstating spend is the safe direction for a budget guard.

        Resolution is first-writer-wins. If another agent resolved the same
        orphan first, this list no longer contains it and the resolving call
        raises EntryAlreadyTerminalError rather than overwriting their
        settled figure — re-read the ledger and accept the existing record.
        """
        return [
            e for e in self.entries
            if e["status"] in (EntryStatus.ESTIMATED.value, EntryStatus.RESERVED.value)
        ]

    # ---- Reference-driven estimation ----

    def estimate_from_reference(
        self,
        video_analysis_brief: dict,
        target_duration_seconds: int,
        tool_plan: dict,
    ) -> dict:
        """Estimate production cost based on reference analysis + target duration.

        Args:
            video_analysis_brief: The VideoAnalysisBrief artifact from video analysis
            target_duration_seconds: How long the output video should be
            tool_plan: Which tools will be used for each asset type, e.g.:
                {
                    "image_generation": {"tool": "flux_fal", "cost_per_unit": 0.05},
                    "video_generation": {"tool": "kling_fal", "cost_per_unit": 0.30,
                                         "clip_duration_seconds": 5},
                    "tts": {"tool": "elevenlabs_tts", "cost_per_word": 0.00003},
                    "music": {"tool": "music_gen", "cost_per_track": 0.10},
                }

        Returns:
            Itemized cost breakdown with line items, total, sample cost, and assumptions.
        """
        structure = video_analysis_brief.get("structure_analysis", {})
        pacing = structure.get("pacing_profile", {})
        narration = video_analysis_brief.get("narration_transcript", {})
        ref_duration = video_analysis_brief.get("source", {}).get("duration_seconds", 60)
        pacing_style = pacing.get("pacing_style", "steady_educational")

        # ── Scene count estimation ──
        # Don't just scale linearly — use the PACING DENSITY from the reference.
        # A music video with 8 scenes in 162s has ~3 cuts/min.
        # Scaling to 60s should PRESERVE that cut rate, not reduce scene count.
        ref_scenes = structure.get("total_scenes", 8)
        if ref_duration > 0:
            cuts_per_minute = ref_scenes / (ref_duration / 60)
        else:
            cuts_per_minute = 4.0  # default: moderate pacing

        # Apply pacing-aware minimums (a fast-cut video doesn't become a slideshow)
        min_scenes_by_pacing = {
            "rapid_fire": 10,
            "dynamic_social": 8,
            "steady_educational": 5,
            "slow_contemplative": 3,
            "variable": 6,
        }
        min_scenes = min_scenes_by_pacing.get(pacing_style, 5)

        # Scene count = max(pacing-density-based, minimum for style)
        density_based_scenes = round(cuts_per_minute * (target_duration_seconds / 60))
        estimated_scenes = max(min_scenes, density_based_scenes)

        # ── Narration word count ──
        ref_word_count = narration.get("word_count", 0)
        if ref_duration > 0 and ref_word_count > 0:
            actual_wpm = (ref_word_count / ref_duration) * 60
        else:
            actual_wpm = 150  # default conversational pace
        estimated_words = round(actual_wpm * (target_duration_seconds / 60))

        # ── Motion ratio from reference ──
        scenes_list = structure.get("scenes", [])
        motion_ratio, motion_basis = self._estimate_motion_ratio(
            video_analysis_brief=video_analysis_brief,
            scenes_list=scenes_list,
            pacing_style=pacing_style,
        )

        estimated_motion_scenes = (
            max(1, round(estimated_scenes * motion_ratio))
            if motion_ratio > 0
            else 0
        )
        estimated_still_scenes = estimated_scenes - estimated_motion_scenes

        # ── Video clip coverage ──
        # Video gen tools produce clips of limited duration (typically 5-10s).
        # A 60s video with motion needs enough clips to COVER the duration,
        # not just 1 per scene.
        vid_plan = tool_plan.get("video_generation", {})
        clip_duration = vid_plan.get("clip_duration_seconds", 5) if vid_plan else 5
        motion_seconds = target_duration_seconds * motion_ratio
        clips_needed_for_coverage = max(
            estimated_motion_scenes,
            round(motion_seconds / clip_duration)
        ) if vid_plan else 0

        # ── Retry/waste buffer ──
        # Not every generation succeeds or looks good. Add a buffer.
        retry_multiplier = 1.3  # ~30% extra for retries and rejected outputs

        # ── Image count ──
        # Images per scene depends on visual variety needs:
        # - Explainer: 1-2 images per scene
        # - Music video / cinematic: 2-3 images per scene (mood shifts, variety)
        images_per_scene = 2.0 if pacing_style in ("dynamic_social", "rapid_fire") else 1.5
        estimated_images = max(
            estimated_scenes,
            round(estimated_scenes * images_per_scene)
        )

        # Build line items
        line_items = []
        assumptions = []

        assumptions.append(
            f"{estimated_scenes} scenes (reference has {cuts_per_minute:.1f} cuts/min, "
            f"pacing: {pacing_style})"
        )
        assumptions.append(motion_basis)

        # Image generation
        img_plan = tool_plan.get("image_generation", {})
        if img_plan:
            img_count = round(estimated_images * retry_multiplier)
            unit_cost = img_plan.get("cost_per_unit", 0.05)
            line_items.append({
                "category": "image_generation",
                "provider": img_plan.get("tool", "unknown"),
                "quantity": img_count,
                "unit_cost_usd": unit_cost,
                "total_usd": round(img_count * unit_cost, 4),
                "basis": (
                    f"~{images_per_scene:.0f} images/scene x {estimated_scenes} scenes "
                    f"+ {round((retry_multiplier - 1) * 100)}% retry buffer"
                ),
            })

        # Video generation
        if vid_plan and clips_needed_for_coverage > 0:
            clip_count = round(clips_needed_for_coverage * retry_multiplier)
            unit_cost = vid_plan.get("cost_per_unit", 0.30)
            line_items.append({
                "category": "video_generation",
                "provider": vid_plan.get("tool", "unknown"),
                "quantity": clip_count,
                "unit_cost_usd": unit_cost,
                "total_usd": round(clip_count * unit_cost, 4),
                "basis": (
                    f"{motion_seconds:.0f}s of motion / {clip_duration}s clips = "
                    f"{clips_needed_for_coverage} clips + retry buffer"
                ),
            })
            assumptions.append(
                f"{round(motion_ratio * 100)}% motion ratio → "
                f"{motion_seconds:.0f}s needs {clips_needed_for_coverage} clips "
                f"({clip_duration}s each)"
            )

        # TTS narration
        tts_plan = tool_plan.get("tts", {})
        if tts_plan and estimated_words > 10:
            cost_per_word = tts_plan.get("cost_per_word", 0.00003)
            tts_cost = round(estimated_words * cost_per_word, 4)
            line_items.append({
                "category": "tts_narration",
                "provider": tts_plan.get("tool", "unknown"),
                "quantity": estimated_words,
                "unit_cost_usd": cost_per_word,
                "total_usd": tts_cost,
                "basis": f"Narration at {round(actual_wpm)} WPM = ~{estimated_words} words",
            })
            assumptions.append(
                f"Narration at {round(actual_wpm)} WPM = ~{estimated_words} words "
                f"for {target_duration_seconds} seconds"
            )

        # Music
        music_plan = tool_plan.get("music", {})
        if music_plan:
            music_cost = music_plan.get("cost_per_track", 0.0)
            line_items.append({
                "category": "music",
                "provider": music_plan.get("tool", "unknown"),
                "quantity": 1,
                "unit_cost_usd": music_cost,
                "total_usd": music_cost,
                "basis": "1 background music track",
            })

        subtotal = round(sum(item["total_usd"] for item in line_items), 4)

        # ── Cost range instead of single number ──
        # Low: everything works first try. High: retry buffer fully consumed.
        low_total = round(subtotal / retry_multiplier, 4)
        high_total = round(subtotal * 1.15, 4)  # 15% above retry-buffered estimate

        # Sample cost: 2 scenes worth of assets (hook + 1 middle)
        sample_scenes = 2
        sample_fraction = sample_scenes / max(estimated_scenes, 1)
        sample_cost = round(subtotal * sample_fraction, 4)

        # Confidence based on how much data we have
        if scenes_list and narration.get("word_count", 0) > 0:
            confidence = "high"
        elif scenes_list or narration.get("word_count", 0) > 0:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "line_items": line_items,
            "total_usd": subtotal,
            "total_range_usd": {"low": low_total, "high": high_total},
            "sample_cost_usd": sample_cost,
            "confidence": confidence,
            "assumptions": assumptions,
            "estimated_scenes": estimated_scenes,
            "estimated_images": estimated_images,
            "estimated_clips": clips_needed_for_coverage,
            "estimated_words": estimated_words,
            "motion_ratio": round(motion_ratio, 2),
            "cuts_per_minute": round(cuts_per_minute, 1),
            "target_duration_seconds": target_duration_seconds,
        }

    def _estimate_motion_ratio(
        self,
        *,
        video_analysis_brief: dict,
        scenes_list: list[dict[str, Any]],
        pacing_style: str,
    ) -> tuple[float, str]:
        """Estimate how much of the target treatment truly needs motion."""
        motion_weights = {
            "animation": 1.0,
            "b_roll": 1.0,
            "stock_footage": 1.0,
            "product_shot": 0.9,
            "transition": 0.6,
            "screen_recording": 0.45,
            "talking_head": 0.35,
            "diagram": 0.25,
            "chart": 0.25,
            "text_card": 0.2,
        }
        classified_weights = [
            motion_weights[visual_type]
            for scene in scenes_list
            if (visual_type := scene.get("visual_type")) in motion_weights
        ]
        if classified_weights:
            ratio = sum(classified_weights) / len(classified_weights)
            unknown_count = max(0, len(scenes_list) - len(classified_weights))
            if unknown_count:
                fallback_ratio, _ = self._fallback_motion_ratio(
                    video_analysis_brief=video_analysis_brief,
                    pacing_style=pacing_style,
                )
                ratio = (
                    (sum(classified_weights) + fallback_ratio * unknown_count)
                    / len(scenes_list)
                )
                basis = (
                    "motion ratio blended from classified scene types and "
                    "reference-style fallback for unclassified scenes"
                )
            else:
                basis = "motion ratio derived from classified scene types"
            return round(min(max(ratio, 0.0), 0.95), 2), basis

        return self._fallback_motion_ratio(
            video_analysis_brief=video_analysis_brief,
            pacing_style=pacing_style,
        )

    def _fallback_motion_ratio(
        self,
        *,
        video_analysis_brief: dict,
        pacing_style: str,
    ) -> tuple[float, str]:
        """Fallback heuristic for motion ratio before scene vision enrichment."""
        source_type = video_analysis_brief.get("source", {}).get("type", "")
        replication = video_analysis_brief.get("replication_guidance", {})
        motion_required = bool(replication.get("motion_required"))
        suggested_pipeline = replication.get("suggested_pipeline", "")

        base_by_pacing = {
            "rapid_fire": 0.8,
            "dynamic_social": 0.65,
            "steady_educational": 0.35,
            "slow_contemplative": 0.2,
            "variable": 0.5,
        }
        ratio = base_by_pacing.get(pacing_style, 0.5)

        if source_type in ("shorts", "instagram", "tiktok"):
            ratio = max(ratio, 0.7)
        if motion_required:
            ratio = max(ratio, 0.6)
        if suggested_pipeline == "cinematic":
            ratio = max(ratio, 0.55)

        ratio = round(min(max(ratio, 0.1), 0.95), 2)
        basis = (
            "motion ratio inferred from pacing/style because scene visual types "
            "have not been enriched yet"
        )
        return ratio, basis

    # ---- Persistence ----

    @contextmanager
    def _locked(self):
        """Serialize load-merge-save across processes. No-op when in-memory only.

        The lock is NOT reentrant: no mutator may call another mutator from
        inside this block. A separate ``.lock`` file is locked, never the
        data file — ``_save``'s ``os.replace`` swaps the data file's inode,
        so a flock held on it would stop excluding the next opener.
        """
        global _LOCKING_WARNING_EMITTED
        if self.cost_log_path is None:
            yield
            return
        self.cost_log_path.parent.mkdir(parents=True, exist_ok=True)
        if fcntl is None:
            if not _LOCKING_WARNING_EMITTED:
                _LOCKING_WARNING_EMITTED = True
                logger.warning(
                    "cost ledger file locking unavailable on this platform — "
                    "concurrent stages may race"
                )
            # Reload-merge-save still runs, which alone removes most
            # lost-update windows.
            self._merge_from_disk()
            yield
            return
        lock_path = self.cost_log_path.with_suffix(".json.lock")
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                self._merge_from_disk()
                yield
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

    def _save(self) -> None:
        if self.cost_log_path is None:
            return
        data = {
            "version": "1.0",
            "budget_total_usd": self.budget_total_usd,
            "budget_reserved_usd": round(self.budget_reserved_usd, 4),
            "budget_spent_usd": round(self.budget_spent_usd, 4),
            "mode": BudgetMode(self.mode).value,
            "reserve_pct": self.reserve_pct,
            "single_action_approval_usd": self.single_action_approval_usd,
            "approved_tools": sorted(self._approved_tools),
            "entries": self.entries,
        }
        self.cost_log_path.parent.mkdir(parents=True, exist_ok=True)
        # tmp + os.replace: a mid-dump crash can never leave a truncated ledger
        # (write_checkpoint's idiom, cited by symbol — its line numbers move).
        tmp_path = self.cost_log_path.with_suffix(".json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        os.replace(tmp_path, self.cost_log_path)

    def _read_ledger(self) -> dict[str, Any]:
        """Parse the persisted ledger. Raises CostLogCorruptedError, never resets."""
        try:
            with open(self.cost_log_path) as f:  # type: ignore[arg-type]
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(
                    f"top-level JSON is {type(data).__name__}, expected object"
                )
            self._validate_ledger_shape(data)
        except (json.JSONDecodeError, TypeError, ValueError, OSError) as exc:
            raise CostLogCorruptedError(
                f"Cost ledger {self.cost_log_path} is corrupt ({exc}). "
                "This is the money audit log — do NOT delete it or start fresh, "
                "a reset ledger reports $0 spent and the budget guard would "
                "re-authorize money already spent. Recovery: call "
                "CostTracker.reconstruct_from_snapshot(...) with the latest "
                "checkpoint's cost_snapshot and the approved plan's tool names — "
                "it quarantines this file and rebuilds an honest ledger. See its "
                "docstring."
            ) from exc
        return data

    @staticmethod
    def _validate_ledger_shape(data: dict[str, Any]) -> None:
        """Reject a parseable-but-damaged ledger, one level below the top.

        A dict top level is not enough: the merge indexes ``entry["id"]`` and
        the budget properties index ``entry["status"]``, so a ledger whose
        entries are strings, or are dicts missing those keys, used to brick
        the tracker with a bare KeyError/AttributeError/TypeError from the
        first mutator — a traceback carrying none of the recovery guidance
        CostLogCorruptedError exists to deliver. Raises ValueError; the
        caller turns it into that error. Nothing here repairs or drops a bad
        entry: B1's policy is a pointed crash, never a silent reset.
        """
        budget_total = data.get("budget_total_usd")
        if budget_total is not None and (
            isinstance(budget_total, bool)
            or not isinstance(budget_total, (int, float))
        ):
            raise ValueError(
                f"budget_total_usd is {type(budget_total).__name__}, "
                "expected a number"
            )

        approved_tools = data.get("approved_tools")
        if approved_tools is not None:
            if not isinstance(approved_tools, list):
                raise ValueError(
                    f"approved_tools is {type(approved_tools).__name__}, "
                    "expected an array of strings"
                )
            for index, tool in enumerate(approved_tools):
                if not isinstance(tool, str):
                    raise ValueError(
                        f"approved_tools[{index}] is {type(tool).__name__}, "
                        "expected a string"
                    )

        if "entries" not in data:
            return
        entries = data["entries"]
        if not isinstance(entries, list):
            raise ValueError(
                f"entries is {type(entries).__name__}, expected an array"
            )
        known_statuses = {status.value for status in EntryStatus}
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"entries[{index}] is {type(entry).__name__}, "
                    "expected an object"
                )
            entry_id = entry.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                raise ValueError(
                    f"entries[{index}] has no usable 'id' (found "
                    f"{entry_id!r}); every entry must carry a non-empty "
                    "string id"
                )
            status = entry.get("status")
            if status not in known_statuses:
                raise ValueError(
                    f"entries[{index}] (id {entry_id!r}) has status "
                    f"{status!r}, expected one of "
                    f"{sorted(known_statuses)}"
                )
            for field in _NUMERIC_ENTRY_FIELDS:
                value = entry.get(field)
                if value is None:
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"entries[{index}] (id {entry_id!r}) has {field} "
                        f"{value!r}, expected a number"
                    )

    def _guard_terminal(
        self, entry: dict[str, Any], action: str, force: bool
    ) -> None:
        """Stop a mutator from silently overwriting a settled money record.

        Every terminal status shares one rank in ``_STATUS_RANK``, so the
        merge cannot tell a completed entry from a refund of it — ties break
        on timestamp and the later writer wins. That makes a second
        resolution of the same entry (two agents following
        ``non_terminal_entries``' recovery rules differently) able to zero
        real billed spend. First writer wins; the second gets this error.
        """
        status = entry.get("status")
        if status not in _TERMINAL_STATUSES:
            return
        if force:
            logger.warning(
                "cost ledger: forced %s over already-%s entry %s "
                "(actual_usd %s, reserved_usd %s) — a settled money record "
                "is being overwritten",
                action,
                status,
                entry.get("id"),
                entry.get("actual_usd"),
                entry.get("reserved_usd"),
            )
            return
        raise EntryAlreadyTerminalError(
            f"Cost entry {entry.get('id')!r} is already {status} "
            f"(actual_usd ${float(entry.get('actual_usd', 0.0) or 0.0):.4f}); "
            f"{action}() would overwrite a settled money record and can zero "
            "spend that was really billed. Another process or agent resolved "
            "this entry first — re-read the ledger (non_terminal_entries() no "
            "longer lists it) and accept the existing record; bill new work "
            "against a new estimate() entry. If you are deliberately "
            "correcting a record you know is wrong, pass force=True — the "
            "override is logged."
        )

    def _load(self) -> None:
        data = self._read_ledger()
        self.entries = data.get("entries", [])
        # Backing field: a persisted header is not a local arming decision.
        self._budget_total_usd = data.get("budget_total_usd", self._budget_total_usd)
        self._approved_tools = set(data.get("approved_tools", []))

    def _merge_from_disk(self) -> None:
        """Fold the persisted ledger into memory before mutating and saving.

        Deterministic rules: entries union by id (a terminal status never
        regresses); approved_tools union; budget_total_usd from disk unless
        this instance armed it explicitly after construction.
        """
        if self.cost_log_path is None or not self.cost_log_path.exists():
            return
        data = self._read_ledger()

        disk_entries = data.get("entries", []) or []
        local_by_id = {e["id"]: e for e in self.entries}
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for disk_entry in disk_entries:
            entry_id = disk_entry.get("id")
            seen.add(entry_id)
            local_entry = local_by_id.get(entry_id)
            if local_entry is None:
                merged.append(disk_entry)
            else:
                merged.append(self._pick_entry(local_entry, disk_entry))
        for entry in self.entries:
            if entry["id"] not in seen:
                merged.append(entry)
        self.entries = merged

        self._approved_tools |= set(data.get("approved_tools", []) or [])

        if not self._budget_dirty and "budget_total_usd" in data:
            self._budget_total_usd = data["budget_total_usd"]

    @staticmethod
    def _pick_entry(
        local_entry: dict[str, Any], disk_entry: dict[str, Any]
    ) -> dict[str, Any]:
        """Higher lifecycle rank wins; tie → later timestamp; tie → local."""
        local_rank = _STATUS_RANK.get(local_entry.get("status"), -1)
        disk_rank = _STATUS_RANK.get(disk_entry.get("status"), -1)
        if disk_rank > local_rank:
            return disk_entry
        if local_rank > disk_rank:
            return local_entry
        if str(disk_entry.get("timestamp", "")) > str(local_entry.get("timestamp", "")):
            return disk_entry
        return local_entry

    # ---- Recovery ----

    @classmethod
    def reconstruct_from_snapshot(
        cls,
        cost_log_path: Path,
        cost_snapshot: dict[str, Any],
        approved_tools: Iterable[str] = (),
        budget_total_usd: Optional[float] = None,
        **kwargs: Any,
    ) -> "CostTracker":
        """Rebuild a quarantined ledger from the last checkpoint's cost_snapshot.

        Renames the corrupt file to cost_log.json.corrupt-<n> (kept for audit,
        never deleted), then writes a fresh ledger seeded with ONE completed
        entry — tool "ledger_reconstruction", operation "prior spend per
        checkpoint cost_snapshot", actual_usd = cost_snapshot["total_spent_usd"]
        — so budget_spent_usd is honest immediately and the budget guard cannot
        re-authorize money already spent. Re-arms budget_total_usd (the
        snapshot's approved figure unless overridden) and re-approves the given
        tool names. Line-item detail from before the corruption is lost and NOT
        invented; the seed entry's operation string says so. Returns the new
        tracker.

        The estimate→reconcile seed deliberately bypasses ``reserve``'s guards:
        it records past spend, it does not authorize new spend.
        """
        path = Path(cost_log_path)
        if path.exists():
            index = 1
            while path.with_suffix(f".json.corrupt-{index}").exists():
                index += 1
            os.replace(path, path.with_suffix(f".json.corrupt-{index}"))

        resolved_budget = budget_total_usd
        if resolved_budget is None:
            resolved_budget = cost_snapshot.get("budget_total_usd")

        tracker = cls(
            budget_total_usd=resolved_budget,
            cost_log_path=path,
            **kwargs,
        )
        tracker._approved_tools = set(approved_tools)
        prior_spend = float(cost_snapshot.get("total_spent_usd", 0.0) or 0.0)
        tracker.entries.append({
            "id": tracker._new_id(),
            "tool": "ledger_reconstruction",
            "operation": (
                "prior spend per checkpoint cost_snapshot "
                "(line-item detail lost with the corrupt ledger, not reconstructed)"
            ),
            "status": EntryStatus.COMPLETED.value,
            "estimated_usd": round(prior_spend, 4),
            "reserved_usd": 0.0,
            "actual_usd": round(prior_spend, 4),
            "timestamp": cls._now(),
        })
        tracker._save()
        return tracker

    # ---- Helpers ----

    def _find(self, entry_id: str) -> dict[str, Any]:
        for entry in self.entries:
            if entry["id"] == entry_id:
                return entry
        raise KeyError(f"Cost entry {entry_id!r} not found")

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:12]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
