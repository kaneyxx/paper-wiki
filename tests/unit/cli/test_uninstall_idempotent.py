"""A11: re-running ``paperwiki uninstall --everything --yes`` is idempotent.

A successful uninstall leaves nothing behind. A second run must:

- exit 0
- not error on missing targets
- print a clean "nothing to remove" line
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperwiki.cli import app


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def _seed_full_state(home: Path) -> None:
    """Seed plugin + everything layer for the double-run test."""
    claude = home / ".claude"
    claude.mkdir(parents=True, exist_ok=True)

    cache_dir = claude / "plugins" / "cache" / "paper-wiki" / "paper-wiki" / "0.3.34"
    cache_dir.mkdir(parents=True)
    (cache_dir / "sentinel.txt").write_text("active", encoding="utf-8")

    installed = claude / "plugins" / "installed_plugins.json"
    installed.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "paper-wiki@paper-wiki": [
                        {"scope": "user", "version": "0.3.34", "installPath": "/fake"}
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    settings = claude / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "enabledPlugins": {"paper-wiki@paper-wiki": True},
                "extraKnownMarketplaces": {
                    "paper-wiki": {"type": "github", "repo": "kaneyxx/paper-wiki"}
                },
            }
        ),
        encoding="utf-8",
    )

    # everything layer
    config = home / ".config" / "paper-wiki"
    (config / "recipes").mkdir(parents=True)
    (config / "secrets.env").write_text("API=test\n", encoding="utf-8")
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "paperwiki").write_text("#!shim", encoding="utf-8")
    (local_bin / ".paperwiki-path-warned").write_text("", encoding="utf-8")
    clone = claude / "plugins" / "marketplaces" / "paper-wiki"
    clone.mkdir(parents=True)


def test_uninstall_idempotent_double_run(fake_home: Path) -> None:
    """Re-running the same uninstall on a clean state is a no-op."""
    _seed_full_state(fake_home)

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    first = runner.invoke(app, ["uninstall", "--everything", "--yes"])
    assert first.exit_code == 0, first.output

    # Re-run on now-clean state.
    second = runner.invoke(app, ["uninstall", "--everything", "--yes"])
    assert second.exit_code == 0, second.output
    assert "nothing to remove" in second.output


def test_uninstall_idempotent_no_state_at_all(fake_home: Path) -> None:
    """Uninstall on a never-installed system: clean exit, no error."""
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["uninstall", "--everything", "--yes"])
    assert result.exit_code == 0, result.output
    assert "nothing to remove" in result.output
