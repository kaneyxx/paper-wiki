"""Task 9.212 — ``write_config`` helper for ``$PAPERWIKI_HOME/config.toml``.

The reader has existed since 9.192 (D-V); the writer is new in 9.212
to support the post-upgrade auto-create flow plus the
``/paper-wiki:setup`` SKILL refactor (9.213).

Contract:

* Writes a minimal v0.4.5+ schema (``default_vault`` and/or
  ``default_recipe``) — both fields optional, but at least one must
  be supplied (refuse to write an empty stub).
* **Idempotent** — refuses to clobber an existing file unless
  ``force=True`` is passed (defends against the auto-create hook
  trampling a maintainer's hand-edited config).
* Tilde-expansion is **not** applied at write time — paths are
  emitted verbatim so a config that says
  ``default_vault = "~/Documents/Paper-Wiki"`` survives a write
  round-trip without mutation.
* Unicode-safe — emoji or non-ASCII paths round-trip without
  ``ascii``-codec errors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from paperwiki.config.config_toml import read_config, write_config
from paperwiki.core.errors import UserError

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_write_creates_minimal_config_with_both_keys(tmp_path: Path) -> None:
    """Both keys supplied → file written with both lines."""
    target = tmp_path / "config.toml"

    write_config(
        target,
        default_vault="~/Documents/Paper-Wiki",
        default_recipe="~/.config/paper-wiki/recipes/daily.yaml",
    )

    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert 'default_vault = "~/Documents/Paper-Wiki"' in text
    assert 'default_recipe = "~/.config/paper-wiki/recipes/daily.yaml"' in text


def test_write_creates_config_with_only_default_vault(tmp_path: Path) -> None:
    """Only ``default_vault`` supplied → file has just that key."""
    target = tmp_path / "config.toml"

    write_config(target, default_vault="~/Documents/Paper-Wiki")

    text = target.read_text(encoding="utf-8")
    assert 'default_vault = "~/Documents/Paper-Wiki"' in text
    assert "default_recipe" not in text


def test_write_round_trip_via_read_config(tmp_path: Path) -> None:
    """Round-trip writer → reader produces an equivalent model."""
    target = tmp_path / "config.toml"

    write_config(
        target,
        default_vault="~/Documents/Paper-Wiki",
        default_recipe="~/.config/paper-wiki/recipes/daily.yaml",
    )

    cfg = read_config(path=target)
    # Reader tilde-expands.
    assert cfg.default_vault is not None
    assert str(cfg.default_vault).endswith("Documents/Paper-Wiki")
    assert cfg.default_recipe is not None
    assert str(cfg.default_recipe).endswith("daily.yaml")


# ---------------------------------------------------------------------------
# Refuse to overwrite (the maintainer-protection contract)
# ---------------------------------------------------------------------------


def test_write_refuses_to_clobber_existing_file(tmp_path: Path) -> None:
    """Calling without ``force=True`` raises when target exists."""
    target = tmp_path / "config.toml"
    target.write_text(
        'default_vault = "~/already-here"\n',
        encoding="utf-8",
    )
    original = target.read_text(encoding="utf-8")

    with pytest.raises(UserError) as exc_info:
        write_config(target, default_vault="~/different")

    assert "already exists" in str(exc_info.value).lower() or "force" in str(exc_info.value).lower()
    # Original content preserved (no partial write).
    assert target.read_text(encoding="utf-8") == original


def test_write_force_overwrites_existing_file(tmp_path: Path) -> None:
    """``force=True`` clobbers — used only by ``/paper-wiki:setup`` after
    explicit user confirmation."""
    target = tmp_path / "config.toml"
    target.write_text('default_vault = "~/old"\n', encoding="utf-8")

    write_config(
        target,
        default_vault="~/new",
        force=True,
    )

    text = target.read_text(encoding="utf-8")
    assert "~/new" in text
    assert "~/old" not in text


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_write_refuses_empty_payload(tmp_path: Path) -> None:
    """Both keys ``None`` → refuse to write an empty stub.

    A blank config.toml provides no information to the resolver, so
    writing one is a footgun (it makes the maintainer think the
    resolver should be working when it's still at Rung 5)."""
    target = tmp_path / "config.toml"

    with pytest.raises(UserError):
        write_config(target)

    assert not target.exists()


def test_write_creates_parent_directory_when_missing(tmp_path: Path) -> None:
    """Auto-create the ``~/.config/paper-wiki/`` parent dir.

    The post-upgrade hook may run before the user has created the
    config directory themselves (fresh upgrade from a pre-D-V version)
    so the writer must mkdir parents instead of crashing.
    """
    target = tmp_path / "nonexistent" / "deep" / "config.toml"

    write_config(target, default_vault="~/Documents/Paper-Wiki")

    assert target.is_file()


# ---------------------------------------------------------------------------
# Path-input shapes
# ---------------------------------------------------------------------------


def test_write_accepts_path_inputs(tmp_path: Path) -> None:
    """Accept :class:`pathlib.Path` directly (not just strings)."""
    target = tmp_path / "config.toml"
    from pathlib import Path as _Path

    write_config(
        target,
        default_vault=_Path("~/Documents/Paper-Wiki"),
        default_recipe=_Path("~/.config/paper-wiki/recipes/daily.yaml"),
    )

    text = target.read_text(encoding="utf-8")
    assert "Documents/Paper-Wiki" in text
    assert "daily.yaml" in text
