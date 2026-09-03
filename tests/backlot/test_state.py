"""Unit tests for Backlot BoardState derivation (backlot/state.py)."""

import json
import time
from pathlib import Path

import pytest

from backlot import state as state_mod
from backlot.state import list_projects, load_board_state, summarize_project


@pytest.fixture
def projects_root(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    return root


def _make_project(root: Path, pid: str) -> Path:
    p = root / pid
    (p / "artifacts").mkdir(parents=True)
    (p / "assets" / "images").mkdir(parents=True)
    (p / "renders").mkdir()
    return p


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


SCENE_PLAN = {
    "version": "1.0",
    "scenes": [
        {"id": "sc1", "type": "generated", "description": "opening",
         "start_seconds": 0, "end_seconds": 4, "script_section_id": "s1",
         "hero_moment": False},
        {"id": "sc2", "type": "generated", "description": "climax",
         "start_seconds": 4, "end_seconds": 10, "hero_moment": True},
    ],
}

SCRIPT = {
    "version": "1.0", "title": "Test Film", "total_duration_seconds": 10,
    "sections": [
        {"id": "s1", "text": "It begins.", "start_seconds": 0, "end_seconds": 4},
        {"id": "s2", "text": "It ends.", "start_seconds": 4, "end_seconds": 10},
    ],
}


class TestBoardState:
    def test_full_project(self, projects_root):
        p = _make_project(projects_root, "film")
        _write(p / "project.json", {"project_id": "film", "title": "My Film",
                                    "pipeline_type": "cinematic", "created_at": "2026-01-01T00:00:00Z"})
        _write(p / "artifacts" / "scene_plan.json", SCENE_PLAN)
        _write(p / "artifacts" / "script.json", SCRIPT)
        img = p / "assets" / "images" / "sc1.png"
        img.write_bytes(b"fake")
        _write(p / "artifacts" / "asset_manifest.json", {
            "version": "1.0",
            "assets": [
                {"id": "a1", "type": "image", "path": "assets/images/sc1.png",
                 "scene_id": "sc1", "source_tool": "t", "cost_usd": 0.1},
                {"id": "a2", "type": "image", "path": "assets/images/missing.png",
                 "scene_id": "sc2", "source_tool": "t"},
            ],
            "total_cost_usd": 0.1,
        })
        _write(p / "checkpoint_script.json", {
            "version": "1.0", "project_id": "film", "pipeline_type": "cinematic",
            "stage": "script", "status": "completed", "timestamp": "2026-01-01T01:00:00Z",
            "human_approved": True, "artifacts": {},
        })

        s = load_board_state(p)
        assert s["title"] == "My Film"
        assert s["pipeline"]["pipeline_type"] == "cinematic"
        assert s["pipeline"]["known"] is True
        board = s["storyboard"]
        assert len(board["scenes"]) == 2
        sc1, sc2 = board["scenes"]
        assert sc1["narration"] == "It begins."
        assert sc1["visual"]["exists"] is True
        # sc2 has no script_section_id -> joined by timing overlap
        assert sc2["narration"] == "It ends."
        assert sc2["hero_moment"] is True
        assert sc2["visual"]["exists"] is False  # missing file flagged
        script_stage = next(x for x in s["stages"] if x["name"] == "script")
        assert script_stage["status"] == "completed"
        assert script_stage["produces"] == ["script"]
        proposal_stage = next(x for x in s["stages"] if x["name"] == "proposal")
        assert proposal_stage["produces"] == ["proposal_packet", "decision_log"]

    def test_gate_skip_detection(self, projects_root):
        p = _make_project(projects_root, "sneaky")
        # completed on a gated stage with no awaiting_human history and no
        # human_approved -> gate_skipped flag
        _write(p / "checkpoint_script.json", {
            "version": "1.0", "project_id": "sneaky", "pipeline_type": "cinematic",
            "stage": "script", "status": "completed",
            "timestamp": "2026-01-01T01:00:00Z", "artifacts": {},
        })
        s = load_board_state(p)
        script_stage = next(x for x in s["stages"] if x["name"] == "script")
        assert script_stage["gate_skipped"] is True

        # with an archived awaiting_human version, the gate was honored
        _write(p / "history" / "checkpoint_script_20260101.json", {
            "stage": "script", "status": "awaiting_human",
        })
        s2 = load_board_state(p)
        script_stage2 = next(x for x in s2["stages"] if x["name"] == "script")
        assert script_stage2["gate_skipped"] is False

    def test_generating_state_from_events(self, projects_root):
        p = _make_project(projects_root, "live")
        _write(p / "artifacts" / "scene_plan.json", SCENE_PLAN)
        events = [
            {"ts": "t1", "tool": "img", "event": "start", "scene_id": "sc1"},
            {"ts": "t2", "tool": "img", "event": "finish", "scene_id": "sc1"},
            {"ts": "t3", "tool": "img", "event": "start", "scene_id": "sc2"},
        ]
        (p / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        s = load_board_state(p)
        cards = {c["id"]: c for c in s["storyboard"]["scenes"]}
        assert cards["sc1"]["generating"] is False
        assert cards["sc2"]["generating"] is True
        assert cards["sc2"]["generating_tool"] == "img"

    def test_degraded_project_never_crashes(self, projects_root):
        p = projects_root / "bare"
        p.mkdir()
        (p / "something.mp4").write_bytes(b"x")
        (p / "artifacts").mkdir()
        (p / "artifacts" / "script.json").write_text("NOT JSON", encoding="utf-8")
        s = load_board_state(p)
        assert s["has_pipeline_state"] is False
        assert s["storyboard"] is None
        assert s["media"]["renders"][0]["path"] == "something.mp4"
        assert s["media"]["renders"][0]["at_root"] is True

    def test_undeclared_stage_surfaces(self, projects_root):
        p = _make_project(projects_root, "legacy")
        _write(p / "checkpoint_idea.json", {
            "version": "1.0", "project_id": "legacy", "pipeline_type": "cinematic",
            "stage": "idea", "status": "completed",
            "timestamp": "2026-01-01T01:00:00Z", "artifacts": {},
        })
        s = load_board_state(p)
        idea = next(x for x in s["stages"] if x["name"] == "idea")
        assert idea.get("undeclared") is True


class TestLibrary:
    def test_list_projects_sorts_live_first(self, projects_root):
        old = _make_project(projects_root, "old-film")
        _write(old / "checkpoint_script.json", {"stage": "script", "status": "completed"})
        # backdate everything in old-film
        import os
        past = time.time() - 60 * 60 * 24 * 30
        for f in old.rglob("*"):
            if f.is_file():
                os.utime(f, (past, past))

        fresh = _make_project(projects_root, "fresh-film")
        _write(fresh / "checkpoint_script.json", {"stage": "script", "status": "in_progress"})

        projects = list_projects(projects_root)
        assert [p["project_id"] for p in projects][0] == "fresh-film"
        assert projects[0]["live"] is True
        assert projects[1]["live"] is False

    def test_underscore_dirs_skipped(self, projects_root):
        (projects_root / "_analysis").mkdir()
        _make_project(projects_root, "real")
        ids = [p["project_id"] for p in list_projects(projects_root)]
        assert ids == ["real"]

    def test_summary_shape(self, projects_root):
        p = _make_project(projects_root, "sum")
        _write(p / "project.json", {"title": "Sum", "pipeline_type": "cinematic"})
        _write(p / "checkpoint_script.json", {
            "stage": "script", "status": "awaiting_human",
            "timestamp": "2026-01-01T01:00:00Z", "artifacts": {},
        })
        summary = summarize_project(p)
        assert summary["awaiting_human"] is True
        assert summary["active_stage"] == "script"


class TestFindingsFixes:
    """Regression tests for dogfood findings F-04/F-05."""

    def test_artifact_refs_outside_project_are_not_followed(self, projects_root, tmp_path):
        # F-04: a checkpoint pointing at JSON outside the project tree
        # must not surface that file on the board.
        secret = tmp_path / "secret.json"
        secret.write_text(json.dumps({"version": "1.0", "leaked": True}), encoding="utf-8")
        p = _make_project(projects_root, "sneaky-ref")
        _write(p / "checkpoint_script.json", {
            "stage": "script", "status": "completed",
            "timestamp": "2026-01-01T01:00:00Z",
            "artifacts": {"script": str(secret)},
        })
        s = load_board_state(p)
        assert "script" not in s["artifacts"]

    def test_inside_project_absolute_refs_still_resolve(self, projects_root):
        p = _make_project(projects_root, "abs-ref")
        _write(p / "artifacts" / "inline_script.json", SCRIPT)
        _write(p / "checkpoint_script.json", {
            "stage": "script", "status": "completed",
            "timestamp": "2026-01-01T01:00:00Z",
            "artifacts": {"script": str((p / "artifacts" / "inline_script.json").resolve())},
        })
        s = load_board_state(p)
        assert s["artifacts"]["script"]["title"] == "Test Film"

    def test_stalled_in_progress_stage_flagged(self, projects_root):
        # F-05: an in_progress stage with no recent activity reads stalled.
        import os
        p = _make_project(projects_root, "wedged")
        _write(p / "checkpoint_research.json", {
            "stage": "research", "status": "in_progress",
            "timestamp": "2026-01-01T01:00:00Z", "artifacts": {},
        })
        past = time.time() - 30 * 60
        for f in p.rglob("*"):
            if f.is_file():
                os.utime(f, (past, past))
        s = load_board_state(p)
        research = next(x for x in s["stages"] if x["name"] == "research")
        assert research["stalled"] is True
        assert research["stalled_minutes"] >= 29

    def test_fresh_in_progress_not_stalled(self, projects_root):
        p = _make_project(projects_root, "busy")
        _write(p / "checkpoint_research.json", {
            "stage": "research", "status": "in_progress",
            "timestamp": "2026-01-01T01:00:00Z", "artifacts": {},
        })
        s = load_board_state(p)
        research = next(x for x in s["stages"] if x["name"] == "research")
        assert "stalled" not in research


class TestStoryboardVisualSelection:
    """The renderable / snapshot / takes logic in _build_storyboard.

    Covers the atelier-thumbnail work: a .tsx composition asset is not a
    showable visual; a missing raster file still surfaces as an indicator;
    an existing SVG diagram IS showable; snapshots/<id>.png is the fallback.
    """

    def _project_with_scenes(self, root, scenes, assets):
        p = _make_project(root, "vis")
        _write(p / "project.json", {"pipeline_type": "cinematic"})
        _write(p / "artifacts" / "scene_plan.json", {"version": "1.0", "scenes": scenes})
        _write(p / "artifacts" / "asset_manifest.json", {"version": "1.0", "assets": assets})
        return p

    def _card(self, p, scene_id):
        s = load_board_state(p)
        return next(c for c in s["storyboard"]["scenes"] if c["id"] == scene_id)

    def test_existing_tsx_animation_is_not_a_visual(self, projects_root):
        # A bespoke composition asset exists on disk but can't be shown.
        p = self._project_with_scenes(
            projects_root,
            [{"id": "sc1", "type": "animation", "description": "morph",
              "start_seconds": 0, "end_seconds": 5}],
            [{"id": "a1", "type": "animation", "path": "Composition.tsx", "scene_id": "sc1",
              "source_tool": "atelier_remotion"}],
        )
        (p / "Composition.tsx").write_text("export const X = 1;", encoding="utf-8")
        card = self._card(p, "sc1")
        # No snapshot yet -> no renderable visual, falls to placeholder (None).
        assert card["visual"] is None
        assert card["takes"] == []

    def test_snapshot_is_the_fallback_for_animation_scene(self, projects_root):
        p = self._project_with_scenes(
            projects_root,
            [{"id": "sc1", "type": "animation", "description": "morph",
              "start_seconds": 0, "end_seconds": 5}],
            [{"id": "a1", "type": "animation", "path": "Composition.tsx", "scene_id": "sc1",
              "source_tool": "atelier_remotion"}],
        )
        (p / "Composition.tsx").write_text("x", encoding="utf-8")
        (p / "snapshots").mkdir()
        (p / "snapshots" / "sc1.png").write_bytes(b"\x89PNG")
        card = self._card(p, "sc1")
        assert card["visual"] is not None
        assert card["visual"]["snapshot"] is True
        assert card["visual"]["renderable"] is True
        assert card["visual"]["path"].endswith("sc1.png")

    def test_snapshot_matches_id_underscore_suffix(self, projects_root):
        p = self._project_with_scenes(
            projects_root,
            [{"id": "sc1", "type": "animation", "start_seconds": 0, "end_seconds": 5}],
            [],
        )
        (p / "snapshots").mkdir()
        (p / "snapshots" / "sc1_hero.png").write_bytes(b"\x89PNG")
        card = self._card(p, "sc1")
        assert card["visual"] is not None and card["visual"]["snapshot"] is True

    def test_existing_svg_diagram_is_renderable(self, projects_root):
        # Regression guard: an existing non-raster-but-showable image (.svg)
        # must remain a visual, not be dropped to a placeholder.
        p = self._project_with_scenes(
            projects_root,
            [{"id": "sc1", "type": "diagram", "start_seconds": 0, "end_seconds": 5}],
            [{"id": "a1", "type": "diagram", "path": "assets/images/d.svg", "scene_id": "sc1",
              "source_tool": "diagram_gen"}],
        )
        (p / "assets" / "images" / "d.svg").write_text("<svg/>", encoding="utf-8")
        card = self._card(p, "sc1")
        assert card["visual"] is not None
        assert card["visual"]["exists"] is True
        assert card["visual"]["renderable"] is True

    def test_missing_raster_file_still_flagged(self, projects_root):
        # The "asset in manifest, file missing" indicator must survive.
        p = self._project_with_scenes(
            projects_root,
            [{"id": "sc1", "type": "generated", "start_seconds": 0, "end_seconds": 5}],
            [{"id": "a1", "type": "image", "path": "assets/images/gone.png", "scene_id": "sc1",
              "source_tool": "t"}],
        )
        card = self._card(p, "sc1")
        assert card["visual"] is not None
        assert card["visual"]["exists"] is False

    def test_renderable_prefers_existing_and_takes_exclude_missing(self, projects_root):
        # Two takes: one real png, one missing. Active = the real one;
        # takes carries only renderable (showable) entries.
        p = self._project_with_scenes(
            projects_root,
            [{"id": "sc1", "type": "generated", "start_seconds": 0, "end_seconds": 5}],
            [
                {"id": "a1", "type": "image", "path": "assets/images/real.png", "scene_id": "sc1", "source_tool": "t"},
                {"id": "a2", "type": "image", "path": "assets/images/missing.png", "scene_id": "sc1", "source_tool": "t"},
            ],
        )
        (p / "assets" / "images" / "real.png").write_bytes(b"\x89PNG")
        card = self._card(p, "sc1")
        assert card["visual"]["exists"] is True
        assert card["visual"]["path"].endswith("real.png")
        assert [t["path"].split("/")[-1] for t in card["takes"]] == ["real.png"]


# ----------------------------------------------------------------------
# Reel cards (#50). A batch is N deliverables, not N versions of one.
# ----------------------------------------------------------------------


def _reel_batch_project(root: Path, *, rendered: int = 5, reels: int = 5) -> Path:
    p = _make_project(root, "reel-batch-001")
    _write(p / "artifacts" / "reel_plan.json", {
        "version": "1.0",
        "reels": [
            {
                "reel_id": f"reel_{n:02d}",
                "music_asset_id": f"asset_track_{n:02d}",
                "subtitle_source": f"assets/captions/reel_{n:02d}.json",
                "hook": f"hook line for reel {n}",
                "cut_ids": [f"reel_{n:02d}-{c:02d}" for c in range(1, 5)],
            }
            for n in range(1, reels + 1)
        ],
    })
    _write(p / "artifacts" / "asset_manifest.json", {
        "version": "1.0",
        "assets": [
            {"id": f"asset_track_{n:02d}", "type": "music",
             "path": f"assets/music/track_{n:02d}.mp3",
             "source_tool": "audio_mixer", "scene_id": f"reel_{n:02d}"}
            for n in range(1, reels + 1)
        ],
    })
    for n in range(1, rendered + 1):
        # The two-plane render leaves the un-captioned master beside the real one.
        (p / "renders" / f"reel_{n:02d}.mp4").write_bytes(b"finished")
        (p / "renders" / f"reel_{n:02d}-picture.mp4").write_bytes(b"intermediate")
    return p


def test_reel_batch_shows_one_card_per_reel(projects_root):
    """Five reels, five cards — each with its own hook, track and cut count."""
    _reel_batch_project(projects_root)

    s = load_board_state(projects_root / "reel-batch-001")

    assert [r["reel_id"] for r in s["reels"]] == [f"reel_{n:02d}" for n in range(1, 6)]
    for n, card in enumerate(s["reels"], start=1):
        assert card["hook"] == f"hook line for reel {n}"
        assert card["track"] == f"track_{n:02d}.mp3"
        assert card["cut_count"] == 4
        assert card["output"] == f"renders/reel_{n:02d}.mp4"


def test_reel_cards_do_not_point_at_the_picture_intermediate(projects_root):
    """`<reel_id>-picture.mp4` is a working master, not a deliverable.

    Ten files in renders/ for a five-reel batch is what made the board show
    "10 versions" of one video. They stay listed — that file is what you look
    at when the captions are wrong — but they are flagged, and no reel card
    resolves to one.
    """
    _reel_batch_project(projects_root)

    s = load_board_state(projects_root / "reel-batch-001")

    assert all(not c["output"].endswith("-picture.mp4") for c in s["reels"])
    flagged = {Path(r["path"]).name for r in s["media"]["renders"] if r.get("intermediate")}
    assert flagged == {f"reel_{n:02d}-picture.mp4" for n in range(1, 6)}
    # And the deliverables themselves are never flagged.
    assert all(
        not r.get("intermediate")
        for r in s["media"]["renders"]
        if not Path(r["path"]).stem.endswith("-picture")
    )


def test_a_reel_with_no_render_yet_still_gets_a_card(projects_root):
    """Mid-batch is the normal state — two done, three to go."""
    _reel_batch_project(projects_root, rendered=2)

    s = load_board_state(projects_root / "reel-batch-001")

    assert len(s["reels"]) == 5
    assert [bool(c["output"]) for c in s["reels"]] == [True, True, False, False, False]


def test_a_project_with_no_reel_plan_renders_with_no_reels(projects_root):
    """The board is an observer. Twelve pipelines have no reel_plan and must
    look exactly as they did — `reels` is None, not an empty section."""
    p = _make_project(projects_root, "ordinary-project")
    _write(p / "artifacts" / "scene_plan.json", SCENE_PLAN)

    s = load_board_state(p)

    assert s["reels"] is None


@pytest.mark.parametrize("plan", [
    {},                                        # no reels key
    {"version": "1.0", "reels": []},           # written but empty
    {"version": "1.0", "reels": "not a list"},  # half-written / wrong type
    {"version": "1.0", "reels": [{"hook": "no reel_id"}]},
])
def test_a_malformed_reel_plan_never_breaks_the_board(projects_root, plan):
    """`load_board_state` never raises — a board that crashes on a half-written
    artifact is worse than a board with one section missing."""
    p = _make_project(projects_root, "half-written")
    _write(p / "artifacts" / "reel_plan.json", plan)

    s = load_board_state(p)

    assert s["reels"] is None
    assert s["project_id"] == "half-written"
