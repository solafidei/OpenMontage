"""Behavioral tests for _merge_decision_log's orphan-absorption self-heal.

The side file <project>/artifacts/decision_log.json is by definition
hand-written and governed by no schema. Merging it must never be able to
abort a checkpoint write, must never rewrite or delete it, and must absorb
each well-formed orphan exactly once.
"""

import json
import logging
import os
import threading

import pytest
from tests.contracts.test_phase0_contracts import sample_artifact

from lib import checkpoint as checkpoint_module
from lib.checkpoint import (
    CheckpointValidationError,
    _merge_decision_log,
    init_project,
    write_checkpoint,
)


def _decision(did: str) -> dict:
    return {
        "decision_id": did, "stage": "research",
        "category": "provider_selection", "subject": "tts provider",
        "options_considered": [
            {"option_id": "a", "label": "A", "score": 0.9, "reason": "fits"},
        ],
        "selected": "a", "reason": "best fit",
    }


def _log(*decisions: dict) -> dict:
    return {"version": "1.0", "project_id": "run", "decisions": list(decisions)}


def _project(tmp_path):
    return init_project(
        "run",
        title="Run",
        pipeline_type="framework-smoke",
        pipeline_dir=tmp_path,
    )


def _write_side(project_dir, payload) -> "object":
    side = project_dir / "artifacts" / "decision_log.json"
    side.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        side.write_text(payload, encoding="utf-8")
    else:
        side.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return side


def _research_write(tmp_path, decision_log):
    return write_checkpoint(
        tmp_path,
        "run",
        "research",
        "awaiting_human",
        {
            "research_brief": sample_artifact("research_brief"),
            "decision_log": decision_log,
        },
        pipeline_type="framework-smoke",
    )


def _canonical(project_dir) -> dict:
    return json.loads((project_dir / "decision_log.json").read_text(encoding="utf-8"))


def _ids(canonical: dict) -> list:
    return [d.get("decision_id") for d in canonical["decisions"]]


def test_side_entry_without_decision_id_does_not_crash_write(tmp_path, caplog) -> None:
    project_dir = _project(tmp_path)
    side = _write_side(
        project_dir,
        _log({"id": "d-031", "note": "wrong key"}, _decision("d-9")),
    )
    snapshot = side.read_bytes()

    with caplog.at_level(logging.WARNING):
        path = _research_write(tmp_path, _log(_decision("d-1")))

    assert path.exists()

    canonical = _canonical(project_dir)
    assert set(_ids(canonical)) == {"d-1", "d-9"}
    assert all(d.get("id") != "d-031" for d in canonical["decisions"])

    assert side.read_bytes() == snapshot

    text = caplog.text
    assert "skipped 1" in text
    assert "were absorbed" in text


def test_duplicate_side_ids_absorbed_exactly_once(tmp_path) -> None:
    project_dir = _project(tmp_path)
    _write_side(
        project_dir,
        _log(_decision("d-9"), {**_decision("d-9"), "reason": "second copy"}),
    )

    _research_write(tmp_path, _log(_decision("d-1")))

    canonical = _canonical(project_dir)
    nines = [d for d in canonical["decisions"] if d.get("decision_id") == "d-9"]
    assert len(nines) == 1
    assert nines[0]["reason"] == "best fit"


@pytest.mark.parametrize(
    "payload",
    [
        {"decisions": {"a": 1}},
        {"decisions": ["not-a-dict"]},
        [{"decision_id": "d-9"}],
    ],
    ids=["decisions-is-dict", "decisions-list-of-strings", "top-level-list"],
)
def test_side_decisions_wrong_container_degrades(tmp_path, caplog, payload) -> None:
    project_dir = _project(tmp_path)
    _write_side(project_dir, payload)

    with caplog.at_level(logging.WARNING):
        path = _research_write(tmp_path, _log(_decision("d-1")))

    assert path.exists()
    canonical = _canonical(project_dir)
    assert _ids(canonical) == ["d-1"]
    assert "decision_log merge" in caplog.text


def test_corrupt_side_file_skips_absorption(tmp_path, caplog) -> None:
    project_dir = _project(tmp_path)
    side = _write_side(project_dir, '{"decisions": [')
    snapshot = side.read_bytes()

    with caplog.at_level(logging.WARNING):
        path = _research_write(tmp_path, _log(_decision("d-1")))

    assert path.exists()
    assert _ids(_canonical(project_dir)) == ["d-1"]
    assert "unreadable" in caplog.text
    assert side.read_bytes() == snapshot


def test_checkpoint_decision_missing_id_reports_schema_error_not_keyerror(
    tmp_path,
) -> None:
    project_dir = _project(tmp_path)
    broken = {k: v for k, v in _decision("d-1").items() if k != "decision_id"}

    with pytest.raises(CheckpointValidationError):
        _research_write(tmp_path, _log(broken))

    canonical_path = project_dir / "decision_log.json"
    if canonical_path.exists():
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        assert canonical["decisions"] == []


def test_canonical_entry_without_id_survives_merge_untouched(tmp_path) -> None:
    project_dir = _project(tmp_path)
    (project_dir / "decision_log.json").write_text(
        json.dumps(_log({"note": "hand-edited, no id"}), indent=2),
        encoding="utf-8",
    )

    path = _research_write(tmp_path, _log(_decision("d-2")))
    assert path.exists()

    canonical = _canonical(project_dir)
    assert {"note": "hand-edited, no id"} in canonical["decisions"]
    assert "d-2" in _ids(canonical)


@pytest.mark.parametrize(
    "payload",
    [[{"decision_id": "d-1"}], {"decisions": {"a": 1}}],
    ids=["top-level-list", "decisions-is-dict"],
)
def test_canonical_container_corruption_raises_pointed_error(tmp_path, payload) -> None:
    project_dir = _project(tmp_path)
    (project_dir / "decision_log.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    with pytest.raises(CheckpointValidationError) as exc:
        _research_write(tmp_path, _log(_decision("d-2")))

    assert "decision_log.json" in str(exc.value)
    assert "hand-damaged" in str(exc.value)


@pytest.mark.parametrize(
    "bad_id",
    [["D-014"], {"id": "D-014"}],
    ids=["list-id", "dict-id"],
)
def test_canonical_unhashable_id_survives_merge_untouched(
    tmp_path, caplog, bad_id
) -> None:
    """An unhashable decision_id in the CANONICAL log must not abort the write.

    The side file already tolerates every malformed shape (_usable_decisions
    filters on isinstance(did, str)); the canonical id-set build guarded only
    isinstance(d, dict), so a hand-written list/dict decision_id raised a bare
    TypeError: unhashable type — no filename, no field, no repair guidance —
    and took the whole checkpoint write down with it. Parity with the side
    path: skip it for id purposes, warn naming the file, keep the entry
    verbatim on disk.
    """
    project_dir = _project(tmp_path)
    broken = {"decision_id": bad_id, "note": "hand-edited"}
    (project_dir / "decision_log.json").write_text(
        json.dumps(_log(broken), indent=2), encoding="utf-8"
    )

    with caplog.at_level(logging.WARNING):
        path = _research_write(tmp_path, _log(_decision("d-2")))

    assert path.exists()

    canonical = _canonical(project_dir)
    assert broken in canonical["decisions"]
    assert "d-2" in _ids(canonical)
    assert "skipped 1" in caplog.text
    assert "decision_log.json" in caplog.text


def test_concurrent_merges_do_not_collide_on_a_shared_tmp_file(
    tmp_path, monkeypatch
) -> None:
    """Two stages of one project merging at once must both survive.

    Every stage merges into the SAME decision_log.json, so a single fixed
    ``decision_log.json.tmp`` was shared scratch space: both writers wrote it,
    the first os.replace consumed it, and the second died with
    FileNotFoundError — losing its decision AND aborting its checkpoint write.
    The barrier below holds both writers between their dump and their replace,
    which is exactly the interleaving that collides.
    """
    project_dir = _project(tmp_path)

    barrier = threading.Barrier(2, timeout=10)
    real_dump = json.dump

    def synced_dump(obj, fp, **kwargs):
        real_dump(obj, fp, **kwargs)
        fp.flush()
        barrier.wait()  # both tmp files written; neither replace has run yet

    monkeypatch.setattr(checkpoint_module.json, "dump", synced_dump)

    errors: list[BaseException] = []

    def merge(did: str) -> None:
        try:
            _merge_decision_log(tmp_path, "run", _log(_decision(did)))
        except BaseException as exc:  # noqa: BLE001 - the defect under test
            errors.append(exc)

    threads = [threading.Thread(target=merge, args=(d,)) for d in ("d-1", "d-2")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert not any(t.is_alive() for t in threads)

    assert errors == [], f"concurrent merge crashed: {errors!r}"

    canonical = _canonical(project_dir)
    assert set(_ids(canonical)) & {"d-1", "d-2"}
    assert not list(project_dir.glob("*.tmp"))


def test_merge_tmp_name_is_unique_per_writer(tmp_path, monkeypatch) -> None:
    """The scratch name must differ per writer, not just per project file."""
    _project(tmp_path)
    seen: list[str] = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(str(src))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)

    _merge_decision_log(tmp_path, "run", _log(_decision("d-1")))
    _merge_decision_log(tmp_path, "run", _log(_decision("d-2")))

    assert len(seen) == 2
    assert len(set(seen)) == 2, f"writers shared a tmp path: {seen}"
