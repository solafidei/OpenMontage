from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_music_plans_discover_all_music_capabilities() -> None:
    instruction_files = [
        "AGENT_GUIDE.md",
        "skills/pipelines/cinematic/idea-director.md",
        "skills/pipelines/cinematic/proposal-director.md",
        "skills/pipelines/documentary-montage/idea-director.md",
        "skills/pipelines/explainer/proposal-director.md",
    ]

    for relative_path in instruction_files:
        text = _read(relative_path)
        for capability in ("music_library", "music_search", "music_generation"):
            assert f'get_by_capability("{capability}")' in text, (
                f"{relative_path} omits the {capability!r} music source"
            )


def test_explainer_directors_do_not_reference_fictitious_submit_functions() -> None:
    for stage in ("idea", "script", "scene"):
        text = _read(f"skills/pipelines/explainer/{stage}-director.md")
        assert "handle_explainer_" not in text


def test_proposal_gates_multiply_unit_price_by_planned_quantity() -> None:
    """estimate_cost prices ONE call. image_selector/video_selector ignore any
    quantity key, so a gate that skips the multiplication under-prices a
    6-clip plan by 6x — on screen and in the seeded cost_log alike."""
    for pipeline in ("explainer", "cinematic", "animation"):
        text = _read(f"skills/pipelines/{pipeline}/proposal-director.md")
        assert 'unit_usd = tool.estimate_cost(planned["inputs"])' in text, (
            f"{pipeline} proposal-director must price one unit via estimate_cost"
        )
        assert "estimated_usd = round(unit_usd * quantity, 4)" in text, (
            f"{pipeline} proposal-director must multiply the unit price by quantity"
        )


def test_paid_explainer_reservations_carry_the_gate_approval() -> None:
    """An approved line item over single_action_approval_usd must not deadlock
    at the point of spend — every paid reserve in a spending director waives
    the single-action threshold for its own entry."""
    for stage in ("asset", "compose"):
        text = _read(f"skills/pipelines/explainer/{stage}-director.md")
        assert "tracker.reserve(entry_id, user_approved=True)" in text
        assert "tracker.reserve(entry_id)\n" not in text, (
            f"explainer {stage}-director reserves without the gate approval flag"
        )
