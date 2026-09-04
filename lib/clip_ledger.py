"""Clip ledger: which footage segments the reels of one batch have claimed.

The guarantee is **within-batch uniqueness**: no segment of the operator's
footage pool is used twice across the reels of one sitting, so five reels cut
from one pool cannot look like each other.

Granularity is a **segment**, keyed ``(source, in_seconds, out_seconds)`` with
``clip_id`` carried alongside. "Whole file" is the interval ``[0, duration]``.
Two claims collide when they name the same source and their intervals
*overlap* — adjacent cuts do not, so one 40s set legitimately yields several
non-overlapping 3s cuts.

Scope is one project. The ledger deliberately does **not** persist across
sittings: a new project may reuse a clip from a previous batch. Cross-sitting
memory is a different feature with a different storage location.

Persistence is copied from :class:`tools.cost_tracker.CostTracker` verbatim
rather than abstracted behind a shared base — ``_locked()`` flocking a sibling
``.lock``, ``_save()`` via tmp + ``os.replace``, ``_merge_from_disk()`` union
by id where a terminal state never regresses, and a corruption error that
never silently resets. Two small ledgers that each read obviously are worth
more here than one clever one shared by the money log and the pool.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import jsonschema

try:
    import fcntl
except ImportError:  # non-POSIX (native Windows)
    fcntl = None  # type: ignore[assignment]

from lib.paths import PROJECTS_DIR
from schemas.artifacts import validate_artifact

logger = logging.getLogger(__name__)

# One warning per process when advisory locking is unavailable (see _locked).
_LOCKING_WARNING_EMITTED = False

CLAIMED = "claimed"
RELEASED = "released"
RECONCILED = "reconciled"

# Lifecycle rank used when the same claim id exists in memory and on disk:
# a terminal status never regresses to a pre-terminal one.
_STATUS_RANK = {CLAIMED: 0, RELEASED: 1, RECONCILED: 1}

# Statuses that settle a claim. `released` returned the segment to the pool,
# `reconciled` means the reel shipped with it — neither may be re-decided.
_TERMINAL_STATUSES = frozenset({RELEASED, RECONCILED})

# Statuses that still hold a segment OUT of the pool. A reconciled claim is as
# binding as a live one: the reel that used it has been approved.
_HOLDING_STATUSES = frozenset({CLAIMED, RECONCILED})


class ClipLedgerCorruptedError(Exception):
    """clip_ledger.json exists but cannot be parsed. Never silently reset."""
    pass


class ClipLedgerUnreadableError(Exception):
    """clip_ledger.json could not be opened at all — IO, not content.

    Deliberately NOT a subclass of ClipLedgerCorruptedError, because the two
    demand opposite operator action. "Corrupt" tells the operator to rebuild
    the claims from the reels already cut; a chmod, a stale mount or a full
    disk leaves the file itself intact, and rebuilding on top of it is how a
    recoverable IO error turns into a lost claim ledger. Fix the access
    problem and retry instead.
    """
    pass


class SegmentAlreadyClaimedError(Exception):
    """A claim overlaps a segment another reel in this batch already holds."""
    pass


class ClipReuseError(Exception):
    """assert_no_reuse() found two live claims overlapping on one source."""
    pass


def _overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Do two claims name the same source with overlapping intervals?

    Intervals are half-open ``[in_seconds, out_seconds)``, so cuts that merely
    touch (``a.out == b.in``) do NOT overlap — that is what lets one long take
    yield several distinct cuts. This predicate is the whole no-reuse rule;
    widening it to "same source" alone would starve the pool, narrowing it to
    an exact key match would let two reels ship the same frames.
    """
    return (
        a["source"] == b["source"]
        and a["in_seconds"] < b["out_seconds"]
        and b["in_seconds"] < a["out_seconds"]
    )


class ClipLedger:
    """Segment claims for one project's batch of reels.

    Every mutation runs inside a lock-reload-merge-mutate-save critical
    section (see ``_locked``), so several reel stages may share one
    ``clip_ledger.json`` without erasing each other's claims. The lock is
    advisory: it only holds while *all* writes go through ``ClipLedger``.
    """

    def __init__(self, ledger_path: Optional[Path] = None) -> None:
        self.ledger_path = Path(ledger_path) if ledger_path is not None else None
        self.claims: list[dict[str, Any]] = []
        if self.ledger_path is not None and self.ledger_path.exists():
            self._load()

    @classmethod
    def for_project(
        cls,
        project_id: str,
        *,
        projects_dir: Optional[Path] = None,
    ) -> "ClipLedger":
        """Open (creating if needed) the project's clip ledger in one line.

        Mirrors ``CostTracker.for_project``: the path follows the project
        workspace convention — ``<projects_dir>/<project_id>/artifacts/
        clip_ledger.json`` — so any stage can call this again with the same
        project_id and get the same persisted ledger.
        """
        base = projects_dir if projects_dir is not None else PROJECTS_DIR
        path = base / project_id / "artifacts" / "clip_ledger.json"
        ledger = cls(ledger_path=path)
        if not path.exists():
            with ledger._locked():
                ledger._save()
        return ledger

    # ---- Claims ----

    def claim(
        self,
        *,
        reel_id: str,
        source: str,
        in_seconds: float,
        out_seconds: float,
        clip_id: Optional[str] = None,
    ) -> str:
        """Claim one segment for a reel. Raises on overlap with a live claim."""
        segment = self._new_claim(
            reel_id=reel_id,
            source=source,
            in_seconds=in_seconds,
            out_seconds=out_seconds,
            clip_id=clip_id,
        )
        with self._locked():
            holder = self._holder_of(segment)
            if holder is not None:
                raise SegmentAlreadyClaimedError(
                    f"Segment {source!r} [{in_seconds}, {out_seconds}) overlaps "
                    f"[{holder['in_seconds']}, {holder['out_seconds']}) already "
                    f"held by reel {holder['reel_id']!r} (claim "
                    f"{holder['claim_id']!r}, status {holder['status']}). "
                    "Pick a different segment — no clip is reused across the "
                    "reels of one batch."
                )
            self.claims.append(segment)
            self._save()
        return segment["claim_id"]

    def is_available(
        self, *, source: str, in_seconds: float, out_seconds: float
    ) -> bool:
        """Would this segment claim cleanly right now? (Re-reads the file.)

        Answers the same question ``claim`` will: a degenerate or inverted
        interval is not "available", it is unclaimable, and reporting True
        here would send a caller into a ValueError it was told to expect.
        """
        try:
            probe = self._new_claim(
                source=source,
                in_seconds=in_seconds,
                out_seconds=out_seconds,
                reel_id="__probe__",
                clip_id=None,
            )
        except ValueError:
            return False
        with self._locked():
            return self._holder_of(probe) is None

    def claims_for_reel(self, reel_id: str) -> list[dict[str, Any]]:
        """Every claim this reel has ever made, live or settled."""
        with self._locked():
            return [dict(c) for c in self.claims if c["reel_id"] == reel_id]

    def live_claims(self) -> list[dict[str, Any]]:
        """Claims still holding a segment out of the pool."""
        with self._locked():
            return [
                dict(c) for c in self.claims if c["status"] in _HOLDING_STATUSES
            ]

    def release_reel(self, reel_id: str) -> list[dict[str, Any]]:
        """Abandon a reel: return exactly its live claims to the pool.

        Reels already reconciled are untouched — including this reel's own
        reconciled claims, which are a shipped record, not a reservation.
        """
        return self._settle_reel(reel_id, RELEASED)

    def reconcile_reel(self, reel_id: str) -> list[dict[str, Any]]:
        """Approve a reel: its claims stay out of the pool permanently."""
        return self._settle_reel(reel_id, RECONCILED)

    def assert_no_reuse(self) -> None:
        """Audit the batch: no two live claims may overlap on one source."""
        live = self.live_claims()
        for index, first in enumerate(live):
            for second in live[index + 1:]:
                if _overlaps(first, second):
                    raise ClipReuseError(
                        f"Clip reuse in batch: reel {first['reel_id']!r} "
                        f"[{first['in_seconds']}, {first['out_seconds']}) and "
                        f"reel {second['reel_id']!r} "
                        f"[{second['in_seconds']}, {second['out_seconds']}) "
                        f"overlap on source {first['source']!r}."
                    )

    # ---- Internals ----

    @staticmethod
    def _new_claim(
        *,
        reel_id: str,
        source: str,
        in_seconds: float,
        out_seconds: float,
        clip_id: Optional[str],
    ) -> dict[str, Any]:
        in_seconds = float(in_seconds)
        out_seconds = float(out_seconds)
        if in_seconds < 0 or out_seconds <= in_seconds:
            # A zero-length or inverted interval overlaps nothing, so it would
            # be claimed by every reel in silence — reuse with no error.
            raise ValueError(
                f"Segment {source!r} needs 0 <= in_seconds < out_seconds, got "
                f"[{in_seconds}, {out_seconds})"
            )
        return {
            "claim_id": str(uuid.uuid4()),
            "reel_id": reel_id,
            "source": source,
            "clip_id": clip_id,
            "in_seconds": in_seconds,
            "out_seconds": out_seconds,
            "status": CLAIMED,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _holder_of(self, segment: dict[str, Any]) -> Optional[dict[str, Any]]:
        """The live claim this segment collides with, if any."""
        for claim in self.claims:
            if claim["status"] in _HOLDING_STATUSES and _overlaps(claim, segment):
                return claim
        return None

    def _settle_reel(self, reel_id: str, status: str) -> list[dict[str, Any]]:
        settled: list[dict[str, Any]] = []
        with self._locked():
            for claim in self.claims:
                if claim["reel_id"] == reel_id and claim["status"] == CLAIMED:
                    claim["status"] = status
                    claim["timestamp"] = datetime.now(timezone.utc).isoformat()
                    settled.append(dict(claim))
            if settled:
                self._save()
        return settled

    # ---- Persistence ----

    @contextmanager
    def _locked(self):
        """Serialize load-merge-save across processes. No-op when in-memory only.

        The lock is NOT reentrant: no mutator may call another mutator from
        inside this block. A separate ``.lock`` file is locked, never the data
        file — ``_save``'s ``os.replace`` swaps the data file's inode, so a
        flock held on it would stop excluding the next opener.
        """
        global _LOCKING_WARNING_EMITTED
        if self.ledger_path is None:
            yield
            return
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if fcntl is None:
            if not _LOCKING_WARNING_EMITTED:
                _LOCKING_WARNING_EMITTED = True
                logger.warning(
                    "clip ledger file locking unavailable on this platform — "
                    "concurrent reel stages may race"
                )
            # Reload-merge-save still runs, which alone removes most
            # lost-update windows.
            self._merge_from_disk()
            yield
            return
        lock_path = self.ledger_path.with_suffix(".json.lock")
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                self._merge_from_disk()
                yield
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

    def _save(self) -> None:
        if self.ledger_path is None:
            return
        data = {"version": "1.0", "claims": self.claims}
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        # tmp + os.replace: a mid-dump crash can never leave a truncated
        # ledger, which _read_ledger would (correctly) refuse to open.
        tmp_path = self.ledger_path.with_suffix(".json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        os.replace(tmp_path, self.ledger_path)

    def _read_ledger(self) -> dict[str, Any]:
        """Parse and validate the persisted ledger. Never resets it.

        The schema check runs on every read, not only when the ledger travels
        inside ``write_checkpoint(artifacts=...)``: ``_validate_artifacts_for_
        stage`` only iterates the dict handed to that call and never sees this
        live, lock-mutated side file, so registration in ARTIFACT_NAMES alone
        would buy nothing at runtime.
        """
        try:
            with open(self.ledger_path) as f:  # type: ignore[arg-type]
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(
                    f"top-level JSON is {type(data).__name__}, expected object"
                )
            validate_artifact("clip_ledger", data)
            self._validate_intervals(data)
        except OSError as exc:
            # Ordered before the content errors (the two hierarchies are
            # disjoint, so this only claims genuine IO). Folding it in with
            # them told the operator a chmod meant CORRUPT and sent them off
            # to rebuild claims from cut lists — destructive advice for a
            # file that is still perfectly intact on disk.
            raise ClipLedgerUnreadableError(
                f"Clip ledger {self.ledger_path} could not be read ({exc}). "
                "The ledger's contents were never examined, so this is NOT a "
                "corruption report: do not delete, reset or rebuild it. Fix "
                "the access problem (permissions, mount, disk space) and run "
                "the stage again."
            ) from exc
        except (
            json.JSONDecodeError,
            jsonschema.ValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise ClipLedgerCorruptedError(
                f"Clip ledger {self.ledger_path} is corrupt ({exc}). Do NOT "
                "delete it or start fresh — a reset ledger reports an empty "
                "pool of claims and the batch would happily ship the same "
                "footage in two reels. Recover it from the reels already cut "
                "(each reel's cut list names its segments) and re-claim them, "
                "or abandon the batch and start a new project."
            ) from exc
        return data

    @staticmethod
    def _validate_intervals(data: dict[str, Any]) -> None:
        """Reject intervals the schema cannot express: out must exceed in.

        JSON Schema can bound each figure but not compare them, and a
        zero-length or inverted interval overlaps nothing — it would be
        silently claimable by every reel, which is exactly the failure this
        ledger exists to prevent.
        """
        for claim in data.get("claims", []):
            if claim["out_seconds"] <= claim["in_seconds"]:
                raise ValueError(
                    f"claim {claim['claim_id']!r} has empty interval "
                    f"[{claim['in_seconds']}, {claim['out_seconds']})"
                )

    def _load(self) -> None:
        self.claims = self._read_ledger().get("claims", [])

    def _merge_from_disk(self) -> None:
        """Fold the persisted ledger into memory before mutating and saving.

        Deterministic rule: claims union by claim_id, where a terminal status
        (released/reconciled) never regresses to `claimed`.
        """
        if self.ledger_path is None or not self.ledger_path.exists():
            return
        data = self._read_ledger()

        disk_claims = data.get("claims", []) or []
        local_by_id = {c["claim_id"]: c for c in self.claims}
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for disk_claim in disk_claims:
            claim_id = disk_claim.get("claim_id")
            seen.add(claim_id)
            local_claim = local_by_id.get(claim_id)
            if local_claim is None:
                merged.append(disk_claim)
            else:
                merged.append(self._pick_claim(local_claim, disk_claim))
        for claim in self.claims:
            if claim["claim_id"] not in seen:
                merged.append(claim)
        self.claims = merged

    @staticmethod
    def _pick_claim(
        local_claim: dict[str, Any], disk_claim: dict[str, Any]
    ) -> dict[str, Any]:
        """Higher lifecycle rank wins; tie → later timestamp; tie → local."""
        local_rank = _STATUS_RANK.get(local_claim.get("status"), -1)
        disk_rank = _STATUS_RANK.get(disk_claim.get("status"), -1)
        if disk_rank > local_rank:
            return disk_claim
        if local_rank > disk_rank:
            return local_claim
        if str(disk_claim.get("timestamp", "")) > str(
            local_claim.get("timestamp", "")
        ):
            return disk_claim
        return local_claim
