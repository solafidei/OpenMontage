"""Unit tests for `styles.playbook_loader`'s name resolution.

`resolve_playbook_path`'s custom-subdir branch ran in zero tests on a clean
checkout: the only coverage came from theme-key tests that happened to sweep
locally-generated playbooks in the untracked `styles/custom/`. Every test here
seeds its own `styles_dir=tmp_path`, so nothing depends on generated content
existing on disk.
"""

import pytest

from styles.playbook_loader import (
    CUSTOM_SUBDIR,
    list_playbooks,
    resolve_playbook_path,
)


def _seed(styles_dir, *, presets=(), customs=()):
    (styles_dir / CUSTOM_SUBDIR).mkdir(parents=True, exist_ok=True)
    for n in presets:
        (styles_dir / f"{n}.yaml").write_text("x: 1\n", encoding="utf-8")
    for n in customs:
        (styles_dir / CUSTOM_SUBDIR / f"{n}.yaml").write_text("x: 1\n", encoding="utf-8")


def test_custom_playbook_resolves_to_custom_subdir(tmp_path) -> None:
    """A generated playbook lives only in custom/ — resolving it by name must
    fall through to that subdir, not join the styles dir and give up."""
    _seed(tmp_path, customs=("brand-x",))

    assert resolve_playbook_path("brand-x", styles_dir=tmp_path) == (
        tmp_path / CUSTOM_SUBDIR / "brand-x.yaml"
    )


def test_preset_wins_over_custom(tmp_path) -> None:
    """The docstring's precedence rule: a preset wins when both exist."""
    _seed(tmp_path, presets=("dup",), customs=("dup",))

    assert resolve_playbook_path("dup", styles_dir=tmp_path) == tmp_path / "dup.yaml"


def test_missing_playbook_raises_filenotfounderror(tmp_path) -> None:
    """The not-found message is the user-facing diagnostic — it must name the
    playbook and both search locations."""
    _seed(tmp_path)

    with pytest.raises(FileNotFoundError, match="nope") as excinfo:
        resolve_playbook_path("nope", styles_dir=tmp_path)

    message = str(excinfo.value)
    assert str(tmp_path) in message
    assert CUSTOM_SUBDIR in message


def test_list_playbooks_includes_customs_and_dedupes(tmp_path) -> None:
    """`list_playbooks` returns presets and customs as one sorted, deduped set —
    the invariant that makes `resolve_playbook_path` necessary: every listed
    name must resolve."""
    _seed(tmp_path, presets=("a", "dup"), customs=("b", "dup"))

    assert list_playbooks(styles_dir=tmp_path) == ["a", "b", "dup"]
