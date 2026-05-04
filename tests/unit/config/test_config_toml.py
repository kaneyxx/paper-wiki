"""Unit tests for ``paperwiki.config.config_toml`` (Task 9.192 / D-V).

The ``config.toml`` reader is the storage layer for user-level paper-wiki
defaults — currently ``default_vault`` and ``default_recipe``. The schema
is intentionally minimal so the module owns one concern: parsing the
file into a typed model with friendly error messages.

These tests pin the acceptance bullets from
``tasks/todo.md::Task 9.192``:

* missing file → empty model (resolver continues to next rung)
* malformed TOML → user-friendly error with the offending line
* tilde expansion at read time (so callers always see an absolute Path)
* forward-compat: unknown keys are ignored without warning so adding new
  fields in v0.4.6+ doesn't crash older readers
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Happy path — minimal valid TOML
# ---------------------------------------------------------------------------


def test_read_config_missing_returns_empty_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No file → empty ``ConfigToml`` with all fields ``None``."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))

    from paperwiki.config.config_toml import read_config

    cfg = read_config()
    assert cfg.default_vault is None
    assert cfg.default_recipe is None


def test_read_config_minimal_valid_toml_parses_fields(tmp_path: Path) -> None:
    """A two-line TOML round-trips through the reader."""
    target = tmp_path / "config.toml"
    fake_vault = tmp_path / "some-vault"
    fake_recipe = tmp_path / "some-recipe.yaml"
    target.write_text(
        f'default_vault = "{fake_vault}"\ndefault_recipe = "{fake_recipe}"\n',
        encoding="utf-8",
    )

    from paperwiki.config.config_toml import read_config

    cfg = read_config(path=target)
    assert cfg.default_vault == fake_vault
    assert cfg.default_recipe == fake_recipe


def test_read_config_expands_tilde_in_default_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``~/foo`` becomes ``$HOME/foo`` so callers always see absolute Paths."""
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "config.toml"
    target.write_text('default_vault = "~/Documents/Paper-Wiki"\n', encoding="utf-8")

    from paperwiki.config.config_toml import read_config

    cfg = read_config(path=target)
    assert cfg.default_vault == tmp_path / "Documents" / "Paper-Wiki"


def test_read_config_expands_tilde_in_default_recipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tilde expansion applies to ``default_recipe`` too."""
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "config.toml"
    target.write_text(
        'default_recipe = "~/.config/paper-wiki/recipes/daily.yaml"\n',
        encoding="utf-8",
    )

    from paperwiki.config.config_toml import read_config

    cfg = read_config(path=target)
    assert cfg.default_recipe == tmp_path / ".config" / "paper-wiki" / "recipes" / "daily.yaml"


def test_read_config_partial_only_default_vault(tmp_path: Path) -> None:
    """A file with only ``default_vault`` leaves ``default_recipe`` ``None``."""
    target = tmp_path / "config.toml"
    fake_vault = tmp_path / "v"
    target.write_text(f'default_vault = "{fake_vault}"\n', encoding="utf-8")

    from paperwiki.config.config_toml import read_config

    cfg = read_config(path=target)
    assert cfg.default_vault == fake_vault
    assert cfg.default_recipe is None


# ---------------------------------------------------------------------------
# Error path — malformed TOML
# ---------------------------------------------------------------------------


def test_read_config_malformed_toml_raises_user_error_with_offending_line(
    tmp_path: Path,
) -> None:
    """A syntactically broken TOML file produces a ``UserError`` that names
    the offending line so users can fix the file without guessing."""
    target = tmp_path / "config.toml"
    target.write_text(
        "default_vault = /tmp/v\n",  # missing quotes — invalid TOML
        encoding="utf-8",
    )

    from paperwiki.config.config_toml import read_config
    from paperwiki.core.errors import UserError

    with pytest.raises(UserError) as exc_info:
        read_config(path=target)

    msg = str(exc_info.value)
    assert "config.toml" in msg
    # The TOML decoder reports a line number; surfacing it lets users
    # fix the file without trial-and-error.
    assert "line" in msg.lower()


# ---------------------------------------------------------------------------
# Forward-compat — unknown keys ignored
# ---------------------------------------------------------------------------


def test_read_config_extra_keys_ignored_for_forward_compat(tmp_path: Path) -> None:
    """A v0.4.6+ field appearing in a v0.4.5 reader must not crash.

    Adding a new top-level key (``future_widget`` here) reflects the
    pattern of "user upgraded paper-wiki, then downgraded" — the older
    reader should treat the unknown key as a no-op rather than refusing
    to parse the entire file.
    """
    target = tmp_path / "config.toml"
    fake_vault = tmp_path / "v"
    target.write_text(
        f'default_vault = "{fake_vault}"\nfuture_widget = "value"\n',
        encoding="utf-8",
    )

    from paperwiki.config.config_toml import read_config

    cfg = read_config(path=target)
    assert cfg.default_vault == fake_vault


# ---------------------------------------------------------------------------
# Resolver — canonical path lookup under PAPERWIKI_HOME
# ---------------------------------------------------------------------------


def test_read_config_uses_paperwiki_home_when_no_path_arg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``path=`` → reader looks at ``$PAPERWIKI_HOME/config.toml``."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    fake_vault = tmp_path / "from-home"
    (tmp_path / "config.toml").write_text(
        f'default_vault = "{fake_vault}"\n',
        encoding="utf-8",
    )

    from paperwiki.config.config_toml import read_config

    cfg = read_config()
    assert cfg.default_vault == fake_vault
