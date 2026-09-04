"""Provider-routing regression coverage for VideoSelector (REVIEW §8 #3, #5, #7, #10).

The selector had NO routing tests (``ls tests | grep video`` turned up only
provider-specific suites), so several routing defects shipped:

- #3 Seedance dedup race: two tools sharing provider="seedance" (the fal and
  Replicate backends) were keyed by provider string in tool_by_provider, so
  only the first-registered was ever selectable. The other was invisible.
- #5 preferred_provider had no score-gap gate: it returned the preferred
  provider on the first ranking match regardless of how far below the top it
  scored (the comment claimed "unless drastically worse" but nothing enforced it).
- #7 fallback_tools appended image_selector unconditionally — a motion-required
  brief could fall back to an image-only tool.

These tests exercise _select_best_tool / estimate_cost / estimate_runtime /
fallback_tools_for directly with stub providers, patching lib.scoring.rank_providers
for deterministic rankings so we test ROUTING logic, not the scorer.
"""

from __future__ import annotations

from typing import Any

import pytest

from tools.base_tool import ToolResult, ToolStatus
from tools.video.video_selector import ProviderPinUnresolvedError, VideoSelector


class _StubTool:
    """Minimal stand-in satisfying what _select_best_tool / _filter_candidates touch."""

    capability = "video_generation"

    def __init__(
        self,
        name: str,
        provider: str,
        *,
        supports_image_to_video: bool = True,
        status: ToolStatus = ToolStatus.AVAILABLE,
        cost: float = 0.10,
        runtime: float = 60.0,
    ) -> None:
        self.name = name
        self.provider = provider
        self.quality_score: float | None = None
        self.best_for = [name]
        self.supports = {
            "text_to_video": True,
            "image_to_video": supports_image_to_video,
        }
        self.input_schema = {"properties": {"prompt": {}}}
        self._status = status
        self._cost = cost
        self._runtime = runtime
        self.last_execute_inputs: dict[str, Any] | None = None

    # --- BaseTool surface used by the selector -------------------------------
    def get_status(self) -> ToolStatus:
        return self._status

    def is_operation_available(self, operation: str) -> bool:
        return self.supports.get(operation, False)

    def get_info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "agent_skills": [],
            "best_for": self.best_for,
            "supports": self.supports,
            "quality_score": self.quality_score,
        }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return self._cost

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return self._runtime

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        self.last_execute_inputs = dict(inputs)
        return ToolResult(success=True, data={})


# ProviderScore.weighted_score is a read-only computed property, so we can't
# override it per-instance. Instead _ScoreStub exposes the same attribute surface
# (provider / tool_name / weighted_score) the selector reads via getattr.
class _ScoreStub:
    def __init__(self, tool_name: str, provider: str, weighted: float) -> None:
        self.tool_name = tool_name
        self.provider = provider
        self.weighted_score = weighted

    def explain(self) -> str:  # noqa: D401 - selector may call this
        return f"{self.tool_name} ({self.provider}): {self.weighted_score:.2f}"

    def to_dict(self) -> dict[str, Any]:
        return {"tool_name": self.tool_name, "provider": self.provider, "weighted_score": self.weighted_score}


@pytest.fixture()
def rankings(monkeypatch):
    """Set the ranking table the patched rank_providers returns."""
    table: list[_ScoreStub] = []

    def fake_rank(candidates, task_context):  # noqa: ANN001
        return list(table)

    monkeypatch.setattr("lib.scoring.rank_providers", fake_rank)
    return table


# ---------------------------------------------------------------------------
# #3 — Seedance dedup race: two tools, same provider, must both be selectable
# ---------------------------------------------------------------------------

def test_two_tools_sharing_provider_are_both_selectable(rankings):
    """The higher-RANKED of two same-provider tools wins; the other isn't shadowed.

    Pre-fix, tool_by_provider keyed by provider string, so whichever of
    seedance_video / seedance_replicate registered second was unreachable
    even if it ranked higher.
    """
    fal = _StubTool("seedance_video", "seedance")
    rep = _StubTool("seedance_replicate", "seedance")
    rankings.extend([
        _ScoreStub("seedance_replicate", "seedance", 0.90),  # ranked higher
        _ScoreStub("seedance_video", "seedance", 0.80),
    ])

    tool, score = VideoSelector()._select_best_tool(
        {"preferred_provider": "auto"}, [fal, rep], {}
    )
    assert tool is not None
    assert tool.name == "seedance_replicate", "higher-ranked same-provider tool must win"


def test_lower_ranked_same_provider_still_reachable_when_higher_unavailable(rankings):
    """If the top-ranked same-provider tool is unavailable, the other is selected.

    Pre-fix the unavailable one could shadow the available one in tool_by_provider
    depending on registration order.
    """
    fal = _StubTool("seedance_video", "seedance", status=ToolStatus.UNAVAILABLE)
    rep = _StubTool("seedance_replicate", "seedance")
    rankings.extend([
        _ScoreStub("seedance_video", "seedance", 0.95),     # ranked higher but unavailable
        _ScoreStub("seedance_replicate", "seedance", 0.80),
    ])

    tool, score = VideoSelector()._select_best_tool(
        {"preferred_provider": "auto"}, [fal, rep], {}
    )
    assert tool is not None
    assert tool.name == "seedance_replicate"


# ---------------------------------------------------------------------------
# #5 — preferred_provider score-gap gate
# ---------------------------------------------------------------------------

def test_preferred_provider_honored_when_within_gap(rankings):
    """Preferred provider ranked #2 but within the gap → selected."""
    veo = _StubTool("veo_video", "veo")
    kling = _StubTool("kling_video", "kling")
    rankings.extend([
        _ScoreStub("veo_video", "veo", 0.90),
        _ScoreStub("kling_video", "kling", 0.80),  # 0.10 below top, within default 0.15 gap
    ])

    tool, score = VideoSelector()._select_best_tool(
        {"preferred_provider": "kling"}, [veo, kling], {}
    )
    assert tool.name == "kling_video"


def test_preferred_provider_ignored_when_drastically_worse(rankings):
    """Preferred provider far below top → top-ranked provider wins instead.

    Pre-fix the preferred provider was returned on the first ranking match
    regardless of the gap (no gate), silently dragging selection to a worse tool.
    """
    veo = _StubTool("veo_video", "veo")
    kling = _StubTool("kling_video", "kling")
    rankings.extend([
        _ScoreStub("veo_video", "veo", 0.95),
        _ScoreStub("kling_video", "kling", 0.50),  # 0.45 below top, outside 0.15 gap
    ])

    tool, score = VideoSelector()._select_best_tool(
        {"preferred_provider": "kling"}, [veo, kling], {}
    )
    assert tool.name == "veo_video", "preference must yield to a drastically better top"


def test_preferred_provider_gap_is_configurable(rankings):
    """A wider gap lets an otherwise-too-low preferred provider win."""
    veo = _StubTool("veo_video", "veo")
    kling = _StubTool("kling_video", "kling")
    rankings.extend([
        _ScoreStub("veo_video", "veo", 0.95),
        _ScoreStub("kling_video", "kling", 0.70),  # 0.25 below top
    ])

    # default gap (0.15) → veo wins
    tool_default, _ = VideoSelector()._select_best_tool(
        {"preferred_provider": "kling"}, [veo, kling], {}
    )
    assert tool_default.name == "veo_video"

    # widened gap (0.30) → kling wins
    tool_wide, _ = VideoSelector()._select_best_tool(
        {"preferred_provider": "kling", "preferred_provider_gap": 0.30}, [veo, kling], {}
    )
    assert tool_wide.name == "kling_video"


def test_preferred_provider_not_in_rankings_falls_through(rankings):
    """An unknown/preferred provider that doesn't rank yields the top provider."""
    veo = _StubTool("veo_video", "veo")
    rankings.append(_ScoreStub("veo_video", "veo", 0.90))

    tool, _ = VideoSelector()._select_best_tool(
        {"preferred_provider": "nonexistent"}, [veo], {}
    )
    assert tool.name == "veo_video"


# ---------------------------------------------------------------------------
# #7 — fallback_tools gate for motion-required briefs
# ---------------------------------------------------------------------------

def test_fallback_excludes_image_selector_for_image_to_video():
    sel = VideoSelector()
    fallback = sel.fallback_tools_for({"operation": "image_to_video"})
    assert "image_selector" not in fallback


def test_fallback_excludes_image_selector_for_reference_to_video():
    sel = VideoSelector()
    fallback = sel.fallback_tools_for({"operation": "reference_to_video"})
    assert "image_selector" not in fallback


def test_fallback_keeps_image_selector_for_text_to_video():
    """A still-image degraded fallback is acceptable for a non-motion brief."""
    sel = VideoSelector()
    fallback = sel.fallback_tools_for({"operation": "text_to_video"})
    assert "image_selector" in fallback


def test_static_fallback_tools_property_still_lists_image_selector():
    """The input-agnostic property preserves the old shape for external consumers."""
    assert "image_selector" in VideoSelector().fallback_tools


# ---------------------------------------------------------------------------
# #10 — estimate_cost / estimate_runtime delegate to the selected provider
# ---------------------------------------------------------------------------

def test_estimate_cost_uses_selected_provider(rankings):
    veo = _StubTool("veo_video", "veo", cost=0.42)
    kling = _StubTool("kling_video", "kling", cost=0.99)
    rankings.append(_ScoreStub("veo_video", "veo", 0.90))
    rankings.append(_ScoreStub("kling_video", "kling", 0.50))

    sel = VideoSelector()
    sel._providers = lambda: [veo, kling]  # type: ignore[assignment]
    assert sel.estimate_cost({"prompt": "x"}) == pytest.approx(0.42)


def test_estimate_runtime_uses_selected_provider(rankings):
    veo = _StubTool("veo_video", "veo", runtime=123.0)
    rankings.append(_ScoreStub("veo_video", "veo", 0.90))

    sel = VideoSelector()
    sel._providers = lambda: [veo]  # type: ignore[assignment]
    assert sel.estimate_runtime({"prompt": "x"}) == pytest.approx(123.0)


def test_estimate_cost_zero_when_no_providers():
    sel = VideoSelector()
    sel._providers = lambda: []  # type: ignore[assignment]
    assert sel.estimate_cost({"prompt": "x"}) == 0.0


def test_ark_local_reference_routes_without_fal_upload(rankings, monkeypatch, tmp_path):
    """An explicit Ark route preserves the local path for Ark's own encoder."""
    ark = _StubTool("seedance_ark", "ark")
    ark.input_schema = {
        "properties": {
            "prompt": {},
            "reference_image_path": {},
            "reference_image_url": {},
        }
    }
    rankings.append(_ScoreStub("seedance_ark", "ark", 0.99))

    def fail_upload(*args, **kwargs):
        raise AssertionError("Ark local references must never be uploaded via FAL")

    monkeypatch.setattr("tools.video._shared.upload_image_fal", fail_upload)
    image_path = tmp_path / "anchor.png"
    image_path.write_bytes(b"not-read-by-selector")

    selector = VideoSelector()
    selector._providers = lambda: [ark]  # type: ignore[assignment]
    result = selector.execute({
        "prompt": "motion",
        "operation": "image_to_video",
        "preferred_provider": "ark",
        "allowed_providers": ["ark"],
        "reference_image_path": str(image_path),
    })

    assert result.success is True
    assert ark.last_execute_inputs is not None
    assert ark.last_execute_inputs["reference_image_path"] == str(image_path)
    assert "image_url" not in ark.last_execute_inputs
    assert result.data["selected_tool"] == "seedance_ark"
    assert result.data["selected_provider"] == "ark"


# ---------------------------------------------------------------------------
# #40 / spec §2.3 D1-D3 — estimate integrity
#
# The shipped probe table (verified by execution against the live registry):
#
#     allowed_providers=None              -> $1.5200   (seedance standard default)
#     allowed_providers=["kling"]         -> $0.1000
#     allowed_providers=["gemini_omni"]   -> $0.5000
#     allowed_providers=["fal"]           -> $0.0000   <- no-candidate branch
#     allowed_providers=["typo_provider"] -> $0.0000
#
# The two zeros were the defect: a $0.00 estimate is exempt from BOTH cost_tracker
# approval guards, so a mistyped pin seeded an unguarded line item that only failed
# later in execute(). They must raise now. The three prices are pinned twice — on the
# provider tools (the live dollar figures) and through the selector with stubs (the
# routing), so a re-pricing or a re-route fails CI instead of silently changing a batch.
# ---------------------------------------------------------------------------

def _probe_providers() -> list[_StubTool]:
    """Stand-ins priced at the live probe figures."""
    return [
        _StubTool("seedance_video", "seedance", cost=1.52),
        _StubTool("kling_video", "kling", cost=0.10),
        _StubTool("gemini_omni_video", "gemini_omni", cost=0.50),
    ]


@pytest.fixture()
def probe_selector(rankings):
    """A selector over the three probe providers, seedance ranked top (the default route)."""
    providers = _probe_providers()
    rankings.extend([
        _ScoreStub("seedance_video", "seedance", 0.90),
        _ScoreStub("gemini_omni_video", "gemini_omni", 0.70),
        _ScoreStub("kling_video", "kling", 0.60),
    ])
    sel = VideoSelector()
    sel._providers = lambda: providers  # type: ignore[assignment]
    return sel


def test_live_probe_prices_are_pinned():
    """The dollar figures the cost model is derived from (spec §5.2)."""
    from tools.video.kling_video import KlingVideo
    from tools.video.seedance_video import SeedanceVideo
    from tools.video.gemini_omni_video import GeminiOmniVideo

    five_seconds = {"prompt": "gym b-roll", "duration": "5"}
    assert KlingVideo().estimate_cost(five_seconds) == pytest.approx(0.10)
    assert GeminiOmniVideo().estimate_cost(five_seconds) == pytest.approx(0.50)
    assert SeedanceVideo().estimate_cost(five_seconds) == pytest.approx(1.52)


def test_unpinned_estimate_routes_to_the_expensive_default(probe_selector):
    """D1 — no pin means the top-ranked (expensive) provider prices the clip."""
    assert probe_selector.estimate_cost({"prompt": "x"}) == pytest.approx(1.52)


def test_pinned_estimates_price_the_pinned_provider(probe_selector):
    """A resolvable pin prices that provider, not the top-ranked one."""
    assert probe_selector.estimate_cost(
        {"prompt": "x", "allowed_providers": ["kling"]}
    ) == pytest.approx(0.10)
    assert probe_selector.estimate_cost(
        {"prompt": "x", "allowed_providers": ["gemini_omni"]}
    ) == pytest.approx(0.50)


@pytest.mark.parametrize("pin", [["fal"], ["typo_provider"]])
def test_unresolvable_pin_raises_instead_of_estimating_zero(probe_selector, pin):
    """D2 — an unresolvable pin must raise, never return an unguardable $0.00."""
    with pytest.raises(ProviderPinUnresolvedError) as excinfo:
        probe_selector.estimate_cost({"prompt": "x", "allowed_providers": pin})
    assert "allowed_providers" in str(excinfo.value)


def test_pin_on_an_unavailable_provider_raises(rankings):
    """A pin naming a real-but-unavailable provider is unresolvable too."""
    kling = _StubTool("kling_video", "kling", status=ToolStatus.UNAVAILABLE, cost=0.10)
    seedance = _StubTool("seedance_video", "seedance", cost=1.52)
    rankings.extend([
        _ScoreStub("seedance_video", "seedance", 0.90),
        _ScoreStub("kling_video", "kling", 0.60),
    ])
    sel = VideoSelector()
    sel._providers = lambda: [kling, seedance]  # type: ignore[assignment]

    with pytest.raises(ProviderPinUnresolvedError):
        sel.estimate_cost({"prompt": "x", "allowed_providers": ["kling"]})


def test_unpinned_estimate_with_no_providers_still_returns_zero():
    """Backward compatibility: only a PIN turns the zero branch into a raise."""
    sel = VideoSelector()
    sel._providers = lambda: []  # type: ignore[assignment]
    assert sel.estimate_cost({"prompt": "x"}) == 0.0


# --- D3: the estimate/execute split ---------------------------------------

def test_execute_flags_divergence_from_the_estimated_pin(probe_selector):
    """D3 — pricing with ["kling"] then executing unpinned is a 15x under-price.

    It slips both approval guards ($0.10 < $0.50), so the selector records the
    divergence on the result where a reviewer (and this test) can see it.
    """
    gate_inputs = {"prompt": "x", "allowed_providers": ["kling"]}
    assert probe_selector.estimate_cost(gate_inputs) == pytest.approx(0.10)

    result = probe_selector.execute({"prompt": "x"})  # pin dropped

    assert result.success is True
    divergence = result.data["estimate_divergence"]
    assert divergence["estimated_provider"] == "kling"
    assert divergence["executed_provider"] == "seedance"
    assert divergence["estimated_usd"] == pytest.approx(0.10)
    assert divergence["executed_estimate_usd"] == pytest.approx(1.52)
    assert divergence["estimated_routing"]["allowed_providers"] == ["kling"]
    assert divergence["executed_routing"]["allowed_providers"] == []


def test_execute_with_the_estimated_inputs_reports_no_divergence(probe_selector):
    """The rule the directors follow: build the inputs dict once, pass the same one."""
    inputs = {"prompt": "x", "allowed_providers": ["kling"], "duration": "5"}
    estimated = probe_selector.estimate_cost(inputs)

    result = probe_selector.execute(inputs)

    assert result.success is True
    assert "estimate_divergence" not in result.data
    assert result.data["executed_estimate_usd"] == pytest.approx(estimated)


def test_execute_without_a_prior_estimate_reports_no_divergence(probe_selector):
    """Nothing to diverge from — but the executed price is still recorded."""
    result = probe_selector.execute({"prompt": "x"})

    assert "estimate_divergence" not in result.data
    assert result.data["executed_estimate_usd"] == pytest.approx(1.52)


# ---------------------------------------------------------------------------
# Live routing — no stubs. The tests above patch rank_providers, so they
# police the selector's plumbing but say nothing about what the REAL scorer
# does with the REAL registry. The cost model in spec §5 rests on that, so
# it gets its own check.
# ---------------------------------------------------------------------------
def _live_selector():
    from tools.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.discover()
    return registry.get("video_selector")


def _kling_is_live() -> bool:
    from tools.video.kling_video import KlingVideo
    from tools.base_tool import ToolStatus

    return KlingVideo().get_status() == ToolStatus.AVAILABLE


@pytest.mark.skipif(not _kling_is_live(), reason="kling_video not credentialed here")
def test_pinning_actually_redirects_the_real_scorer():
    """The whole cost model assumes a pin changes where the money goes.

    No monkeypatch: real registry, real rank_providers, real prices. If
    allowed_providers stopped being honoured by the scorer, every figure in
    spec §5 would be fiction and this is the test that would say so.
    """
    sel = _live_selector()
    clip = {"prompt": "gym atmosphere", "duration": "5", "aspect_ratio": "9:16"}

    unpinned = sel.estimate_cost(dict(clip))
    pinned = sel.estimate_cost({**clip, "allowed_providers": ["kling"]})

    from tools.video.kling_video import KlingVideo

    assert pinned == pytest.approx(KlingVideo().estimate_cost(clip)), (
        "a kling pin must price at kling's own rate, not the selector's default"
    )
    assert unpinned > pinned, (
        f"unpinned ({unpinned}) should route somewhere pricier than a kling "
        f"pin ({pinned}); if these converge the pin has stopped mattering"
    )


@pytest.mark.skipif(not _kling_is_live(), reason="kling_video not credentialed here")
def test_five_reel_shortfall_costs_fifty_cents():
    """Spec §5.3: a full five-reel pool shortfall is 5 x $0.10 = $0.50."""
    sel = _live_selector()
    clip = {
        "prompt": "gym atmosphere",
        "duration": "5",
        "aspect_ratio": "9:16",
        "allowed_providers": ["kling"],
    }
    assert sum(sel.estimate_cost(dict(clip)) for _ in range(5)) == pytest.approx(0.50)


def test_rank_operation_still_prices_free_under_an_unresolvable_pin():
    """The guard protects PAID line items; a ranking query is free and read-only.

    Raising here would be a behaviour regression for callers that only ever
    wanted the shortlist.
    """
    sel = _live_selector()
    assert sel.estimate_cost(
        {"prompt": "x", "operation": "rank", "allowed_providers": ["typo_provider"]}
    ) == 0.0


# --- #51: where an estimate/execute divergence is allowed to land -----------
#
# #40's acceptance criterion offered "refused, or recorded on the ledger
# entry". The ledger arm is not reachable from a tool: CostTracker entries are
# minted by the stage director, execute() is handed no entry id and no tracker,
# and there is no mutator that attaches a free-form field to an entry. So the
# chosen behaviour is result + run-log warning, deliberately NOT the ledger —
# these two tests pin both halves so a later change has to choose it again on
# purpose.

def test_divergence_is_warned_into_the_run_log(probe_selector, caplog):
    """The result payload is only seen by a caller who inspects it; the log is not.

    An operator reading the run log must see the 15x under-price even when
    nobody opens result.data — that is the whole reason the warning exists.
    """
    assert probe_selector.estimate_cost(
        {"prompt": "x", "allowed_providers": ["kling"]}
    ) == pytest.approx(0.10)

    with caplog.at_level("WARNING", logger="tools.video.video_selector"):
        result = probe_selector.execute({"prompt": "x"})  # pin dropped

    assert result.success is True
    warnings = [
        r.getMessage() for r in caplog.records
        if r.levelname == "WARNING" and "divergence" in r.getMessage()
    ]
    assert warnings, "a divergence must reach the run log, not only result.data"
    message = warnings[0]
    assert "kling" in message and "seedance" in message
    assert "0.1000" in message and "1.52" in message


def test_matching_routing_logs_no_divergence_warning(probe_selector, caplog):
    """The warning must stay rare enough to mean something — no cry on the happy path."""
    inputs = {"prompt": "x", "allowed_providers": ["kling"], "duration": "5"}
    probe_selector.estimate_cost(inputs)

    with caplog.at_level("WARNING", logger="tools.video.video_selector"):
        probe_selector.execute(inputs)

    assert not [r for r in caplog.records if "divergence" in r.getMessage()]


def test_divergence_does_not_touch_the_cost_ledger(probe_selector, tmp_path):
    """Pinned on purpose: a tool never writes to cost_log.json.

    A selector-minted entry is one no director reconciles, so it strands in
    ``non_terminal_entries()`` and fails the compose gate's "every entry
    terminal" criterion — worse for the audit trail than the silence. Routing
    the divergence ONTO the director's existing entry needs an entry id the
    tool is never handed plus an annotate API CostTracker does not expose; see
    the comment at the divergence site in video_selector.execute.
    """
    from tools.cost_tracker import BudgetMode, CostTracker

    log_path = tmp_path / "cost_log.json"
    tracker = CostTracker(
        budget_total_usd=10.0,
        reserve_pct=0.0,
        single_action_approval_usd=99.0,
        require_approval_for_new_paid_tool=False,
        mode=BudgetMode.WARN,
        cost_log_path=log_path,
    )
    entry_id = tracker.estimate("video_selector", "reel_1 cutaway via kling_video", 0.10)
    before = log_path.read_text()

    probe_selector.estimate_cost({"prompt": "x", "allowed_providers": ["kling"]})
    result = probe_selector.execute({"prompt": "x"})  # diverges to seedance at $1.52

    assert result.data["estimate_divergence"]["executed_provider"] == "seedance"
    assert log_path.read_text() == before, "the selector must not write to the money log"
    reloaded = CostTracker(
        budget_total_usd=10.0,
        reserve_pct=0.0,
        single_action_approval_usd=99.0,
        require_approval_for_new_paid_tool=False,
        mode=BudgetMode.WARN,
        cost_log_path=log_path,
    )
    (entry,) = reloaded.entries
    assert entry["id"] == entry_id
    assert "estimate_divergence" not in entry
    assert entry["estimated_usd"] == pytest.approx(0.10)  # still the QUOTED figure
