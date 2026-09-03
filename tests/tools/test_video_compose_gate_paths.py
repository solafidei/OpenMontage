"""The pre-compose gate must police every render runtime, not just one.

`_pre_compose_validation` had exactly one call site, placed after the atelier
and HyperFrames early returns. It read as a gate on `render`, but two of the
three runtimes returned before reaching it — so any check added there (delivery
promise, slideshow risk, missing `renderer_family`) silently did not run for
bespoke Remotion or HyperFrames work.
"""

from __future__ import annotations

import pytest

from tools.base_tool import ToolResult
from tools.video.video_compose import VideoCompose

# (label, extra edit_decisions keys) — one per early-return route out of _render.
ROUTES = [
    ("templated", {"render_runtime": "remotion"}),
    ("atelier", {"render_runtime": "remotion", "composition_mode": "atelier"}),
    ("hyperframes", {"render_runtime": "hyperframes", "composition_mode": "atelier"}),
]


def _inputs(tmp_path, extra: dict, **overrides) -> dict:
    ed = {
        "version": "1.0",
        "cuts": [{"id": "c1", "source": "clip1", "in_seconds": 0, "out_seconds": 2}],
        **extra,
    }
    ed.update(overrides.pop("edit_decisions", {}))
    return {
        "operation": "render",
        "edit_decisions": ed,
        "asset_manifest": {
            "version": "1.0",
            "assets": [{"id": "clip1", "path": str(tmp_path / "clip1.mp4")}],
        },
        "output_path": str(tmp_path / "out.mp4"),
        **overrides,
    }


@pytest.mark.parametrize("label,extra", ROUTES, ids=[r[0] for r in ROUTES])
def test_gate_runs_on_every_runtime(tmp_path, monkeypatch, label, extra):
    """The gate is consulted before any runtime branch is taken."""
    calls = []
    monkeypatch.setattr(
        VideoCompose,
        "_pre_compose_validation",
        lambda self, ed, cuts, sp=None: calls.append((ed, cuts, sp)) or None,
    )
    sentinel = ToolResult(success=True, data={"reached": label})
    for method in ("_render_via_atelier", "_render_via_hyperframes"):
        monkeypatch.setattr(VideoCompose, method, lambda *a, **k: sentinel)
    monkeypatch.setattr(VideoCompose, "_needs_remotion", lambda self, cuts: False)
    monkeypatch.setattr(VideoCompose, "_render_via_ffmpeg", lambda *a, **k: sentinel)
    monkeypatch.setattr(VideoCompose, "_compose", lambda self, i: sentinel)
    monkeypatch.setattr(VideoCompose, "_run_final_review", lambda *a, **k: {})

    VideoCompose().execute(_inputs(tmp_path, extra))

    assert len(calls) == 1, f"{label}: gate was not consulted"
    # The gate sees asset-resolved sources, not raw asset ids — an unresolved
    # id defeats the delivery-promise check, which reads the file extension.
    assert calls[0][1][0]["source"].endswith("clip1.mp4")


@pytest.mark.parametrize("label,extra", ROUTES, ids=[r[0] for r in ROUTES])
def test_gate_blocks_on_every_runtime(tmp_path, monkeypatch, label, extra):
    """A real violation stops the render on every route, before the renderer runs."""
    boom = lambda *a, **k: pytest.fail(f"{label}: renderer ran past a blocking gate")
    for method in ("_render_via_atelier", "_render_via_hyperframes",
                   "_render_via_ffmpeg", "_compose", "_remotion_render"):
        monkeypatch.setattr(VideoCompose, method, boom)

    # No renderer_family — locked at proposal, and a block condition in the gate.
    result = VideoCompose().execute(_inputs(tmp_path, extra))

    assert not result.success
    assert "Pre-compose validation failed" in result.error
    assert "renderer_family" in result.error


@pytest.mark.parametrize("label,extra", ROUTES, ids=[r[0] for r in ROUTES])
def test_a_clean_plan_still_reaches_its_runtime(tmp_path, monkeypatch, label, extra):
    """Positive control: the gate is a gate, not a wall."""
    sentinel = ToolResult(success=True, data={"reached": label})
    for method in ("_render_via_atelier", "_render_via_hyperframes", "_render_via_ffmpeg"):
        monkeypatch.setattr(VideoCompose, method, lambda *a, **k: sentinel)
    monkeypatch.setattr(VideoCompose, "_needs_remotion", lambda self, cuts: False)
    monkeypatch.setattr(VideoCompose, "_compose", lambda self, i: sentinel)
    monkeypatch.setattr(VideoCompose, "_run_final_review", lambda *a, **k: {})

    result = VideoCompose().execute(
        _inputs(tmp_path, extra, edit_decisions={"renderer_family": "bespoke"})
    )

    assert result.success, result.error
