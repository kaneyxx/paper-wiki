"""CLI tests for ``paperwiki doctor`` (v0.3.43 D-9.43.3).

Smoke-level tests via ``typer.testing.CliRunner`` that verify the
subcommand wires up, the ``--json`` mode emits valid JSON, the
``--strict`` mode exits 1 on unhealthy rows, and ``--verbose``
configures DEBUG logging without crashing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperwiki import cli as cli_module
from paperwiki.cli import app


@pytest.fixture
def doctor_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Stage a fake $HOME and stub the venv subprocess probe.

    Returns the resolved home + claude_home so tests can seed files
    if they want a healthy/unhealthy result. By default, the venv
    probe reports unhealthy (no fake python script wired up) — tests
    that need a healthy result monkeypatch the probe themselves.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    # Override default constants so doctor doesn't reach the real $HOME.
    monkeypatch.setattr(
        cli_module,
        "_DEFAULT_MARKETPLACE_DIR",
        home / ".claude" / "plugins" / "marketplaces" / "paper-wiki",
    )

    # Stub _run_doctor's venv subprocess so the test isn't slow.
    # Use a simple no-op fake outcome via the runner's monkeypatched function.
    # The subprocess probe defaults to returning unhealthy when no python
    # script is present; that's fine for the unhealthy-path tests.

    # Clear env vars that would alter the resolved bak/venv dirs.
    monkeypatch.delenv("PAPERWIKI_BAK_DIR", raising=False)
    monkeypatch.delenv("PAPERWIKI_VENV_DIR", raising=False)
    monkeypatch.delenv("PAPERWIKI_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("PAPERWIKI_NO_RC_INTEGRATION", raising=False)
    # Default to bash so the rc-block check has a real target.
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("PATH", f"{home}/.local/bin:/usr/bin")

    return {"home": home, "claude_home": home / ".claude"}


def _seed_full_healthy_install(home: Path, claude_home: Path, version: str = "0.3.43") -> None:
    """Mirror test_doctor.py's helpers, condensed."""
    # Helper.
    (home / ".local" / "lib" / "paperwiki").mkdir(parents=True)
    (home / ".local" / "lib" / "paperwiki" / "bash-helpers.sh").write_text(
        f"# paperwiki bash-helpers — v{version} (test stub)\n",
        encoding="utf-8",
    )
    # Shim.
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "paperwiki").write_text(
        f"#!/usr/bin/env bash\n# paperwiki shim — v{version} (test stub)\n",
        encoding="utf-8",
    )
    # installed_plugins.json.
    (claude_home / "plugins").mkdir(parents=True)
    (claude_home / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "paper-wiki@paper-wiki": [
                        {"scope": "user", "version": version, "installPath": "/x"}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    # settings.
    (claude_home / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"paper-wiki@paper-wiki": True}}),
        encoding="utf-8",
    )
    # marketplace.
    (claude_home / "plugins" / "marketplaces" / "paper-wiki" / ".claude-plugin").mkdir(parents=True)
    (
        claude_home / "plugins" / "marketplaces" / "paper-wiki" / ".claude-plugin" / "plugin.json"
    ).write_text(json.dumps({"name": "paper-wiki", "version": version}), encoding="utf-8")
    # bash rc with paperwiki block.
    (home / ".bashrc").write_text(
        "# >>> paperwiki helpers >>>\n"
        '. "$HOME/.local/lib/paperwiki/bash-helpers.sh"\n'
        "# <<< paperwiki helpers <<<\n",
        encoding="utf-8",
    )


def test_doctor_pretty_includes_section_headers(doctor_env: dict[str, Path]) -> None:
    """``paperwiki doctor`` (default, no flags) prints all four sections."""
    home, claude_home = doctor_env["home"], doctor_env["claude_home"]
    _seed_full_healthy_install(home, claude_home)

    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])

    # Default exits 0 even with unhealthy rows (no --strict).
    assert result.exit_code == 0, result.output
    assert "paper-wiki" in result.output
    # All four sections should appear.
    for header in ("Cache & marketplace", "Install integrity", "Python venv", "Shell-rc"):
        assert header in result.output, f"missing section header {header!r}\n{result.output}"
    # Overall summary.
    assert "overall:" in result.output


def test_doctor_json_emits_valid_json(doctor_env: dict[str, Path]) -> None:
    """``paperwiki doctor --json`` produces parseable JSON."""
    home, claude_home = doctor_env["home"], doctor_env["claude_home"]
    _seed_full_healthy_install(home, claude_home)

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "sections" in data
    assert "healthy" in data
    assert "total" in data


def test_doctor_strict_exits_1_when_unhealthy(doctor_env: dict[str, Path]) -> None:
    """``paperwiki doctor --strict`` exits 1 when any row is unhealthy."""
    # No seeding — virtually every row will be unhealthy.
    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--strict"])

    assert result.exit_code == 1, result.output


def test_doctor_verbose_does_not_crash(doctor_env: dict[str, Path]) -> None:
    """``paperwiki doctor --verbose`` configures DEBUG logging without crashing."""
    home, claude_home = doctor_env["home"], doctor_env["claude_home"]
    _seed_full_healthy_install(home, claude_home)

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--verbose"])

    assert result.exit_code == 0, result.output
    assert "paper-wiki" in result.output
