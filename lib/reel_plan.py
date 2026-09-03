"""Materialise one reel's `edit_decisions` from the batch spine.

Reel-batch spec §4.2. `edit_decisions` structurally cannot hold N reels: it carries
exactly one ``audio.music`` object with a single ``asset_id``
(``schemas/artifacts/edit_decisions.schema.json``) and exactly one ``subtitles``
object. Five reels means five tracks and five subtitle sources.

So the `edit` stage emits two artifacts — the spine (shared look, one flat ``cuts[]``
with ``<reel_id>-`` prefixed ids) and `reel_plan` (the per-reel axes) — and `compose`
recombines them **in memory**, once per reel, immediately before rendering. Nothing
built here is written to disk: the spine stays the artifact of record.

This lives in ``lib/`` rather than inside the compose director because the director is
an instruction, not an implementation. A reel that renders short because a filter
dropped a cut is a silent defect, so the filtering is code with a test behind it.
"""

from __future__ import annotations

from typing import Any


class ReelPlanError(ValueError):
    """A reel_plan and a spine that cannot be recombined."""


def reel_ids(reel_plan: dict[str, Any]) -> list[str]:
    """Every planned reel id, in plan order."""
    return [entry["reel_id"] for entry in reel_plan["reels"]]


def entry_for(reel_plan: dict[str, Any], reel_id: str) -> dict[str, Any]:
    """One reel's plan entry."""
    for entry in reel_plan["reels"]:
        if entry["reel_id"] == reel_id:
            return entry
    raise ReelPlanError(f"reel_plan has no entry for {reel_id!r}")


def materialise(spine: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """One reel's `edit_decisions`, built in memory from the spine and one plan entry.

    Cuts come out in **reel order** — ``entry["cut_ids"]`` order, which is not
    necessarily spine order. A ``cut_id`` the spine does not carry raises: a reel_plan
    naming a cut that is not there must fail loudly rather than render short.

    Whole cut objects are copied, never rebuilt. ``provenance`` is what the identity
    gate reads per cut (``lib/polish_filters.py`` → ``look_filters``), so a cut that
    lost it renders an unsafe look no matter what ``metadata.identity_lock`` says.
    """
    by_id = {cut["id"]: cut for cut in spine.get("cuts") or []}
    missing = [cut_id for cut_id in entry["cut_ids"] if cut_id not in by_id]
    if missing:
        raise ReelPlanError(
            f"{entry['reel_id']}: reel_plan names {missing} but the spine has no such cut"
        )

    reel: dict[str, Any] = {
        "version": "1.0",
        "render_runtime": spine["render_runtime"],
        "cuts": [by_id[cut_id] for cut_id in entry["cut_ids"]],
        "audio": {"music": {"asset_id": entry["music_asset_id"], "volume": 0.9}},
        "subtitles": {"enabled": True, "style": "word-by-word",
                      "source": entry["subtitle_source"]},
        "metadata": dict(spine.get("metadata") or {}, reel_id=entry["reel_id"]),
    }
    # edit_decisions is additionalProperties:false at the root — only real properties
    # may be carried, or the materialised reel fails validation at compose.
    for carried in ("renderer_family", "composition_mode", "transitions"):
        if spine.get(carried):
            reel[carried] = spine[carried]
    return reel


def partition_is_total(spine: dict[str, Any], reel_plan: dict[str, Any]) -> None:
    """Every spine cut belongs to exactly one reel. Raises if not.

    A cut in no reel is silently dropped from the batch; a cut in two reels is the
    within-batch reuse the whole clip ledger exists to prevent.
    """
    planned: list[str] = [cid for entry in reel_plan["reels"] for cid in entry["cut_ids"]]
    duplicated = sorted({cid for cid in planned if planned.count(cid) > 1})
    if duplicated:
        raise ReelPlanError(f"cut ids claimed by more than one reel: {duplicated}")
    orphaned = sorted({cut["id"] for cut in spine.get("cuts") or []} - set(planned))
    if orphaned:
        raise ReelPlanError(f"spine cuts in no reel_plan entry: {orphaned}")
