"""Unit tests for v0.3.40 ``paperwiki status`` install-health check (D-9.40.1).

Per plan §17.3 task 9.114, ``paperwiki status`` adds a 4-row install-health
section after the bak-directories line. Each row is one of:

  1. helper file present at ``~/.local/lib/paperwiki/bash-helpers.sh``
  2. helper file's first-line tag matches current plugin ``__version__``
  3. shim present at ``~/.local/bin/paperwiki`` AND first-line tag matches
  4. ``~/.local/bin`` on ``$PATH``

Status command MUST remain exit-0 in every healthy/unhealthy combination
(D-9.40.1 — warn-not-error contract).

Tests use ``monkeypatch.setattr(Path, "home", lambda: tmp_home)`` so the
helper/shim path lookups land in ``tmp_path``. The ``__version__`` is
pulled dynamically from ``paperwiki.__version__`` so tests don't break on
the next version bump.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperwiki import __version__ as _PAPERWIKI_VERSION  # noqa: N812 — constant alias
from paperwiki import cli as cli_module
from paperwiki.cli import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def health_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Stage a fake $HOME with a controllable .local/ tree.

    Returns paths so individual tests can selectively populate
    helper / shim / PATH state to drive each row of the health check.
    """
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    helper_path = home / ".local" / "lib" / "paperwiki" / "bash-helpers.sh"
    shim_path = home / ".local" / "bin" / "paperwiki"
    local_bin = home / ".local" / "bin"

    # Pin cli module's path constants so the existing 4-line status output
    # stays well-formed even though we're testing the new section.
    cache_base = home / ".claude" / "plugins" / "cache" / "paper-wiki" / "paper-wiki"
    marketplace = home / ".claude" / "plugins" / "marketplaces" / "paper-wiki"
    installed_plugins = home / ".claude" / "plugins" / "installed_plugins.json"
    settings_json = home / ".claude" / "settings.json"
    settings_local_json = home / ".claude" / "settings.local.json"
    monkeypatch.setattr(cli_module, "_CACHE_BASE", cache_base)
    monkeypatch.setattr(cli_module, "_INSTALLED_PLUGINS_JSON", installed_plugins)
    monkeypatch.setattr(cli_module, "_SETTINGS_JSON", settings_json)
    monkeypatch.setattr(cli_module, "_SETTINGS_LOCAL_JSON", settings_local_json)
    monkeypatch.setattr(cli_module, "_DEFAULT_MARKETPLACE_DIR", marketplace)

    # Seed minimal marketplace + installed_plugins so the bak-directories
    # line + cache/marketplace lines render cleanly. (Health check is
    # independent — these paths exist so the 4-line preamble doesn't crash.)
    marketplace.mkdir(parents=True)
    (marketplace / ".claude-plugin").mkdir()
    (marketplace / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "paper-wiki", "version": _PAPERWIKI_VERSION}),
        encoding="utf-8",
    )
    cache_base.mkdir(parents=True)

    return {
        "home": home,
        "helper_path": helper_path,
        "shim_path": shim_path,
        "local_bin": local_bin,
        "marketplace": marketplace,
    }


def _seed_helper(path: Path, *, version: str) -> None:
    """Write a helper file with a ``v<version>`` tag on the first line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# paperwiki bash-helpers — v{version} (PATH guard + CLAUDE_PLUGIN_ROOT resolver).\n"
        f"# (rest of helper omitted for fixture)\n",
        encoding="utf-8",
    )


def _seed_shim(path: Path, *, version: str) -> None:
    """Write a shim file with a ``v<version>`` tag on the second line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"# paperwiki shim — v{version} (shared venv + self-bootstrap + PYTHONPATH fallback).\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_status(
    home: Path,
    marketplace: Path,
    *,
    path_env: str,
):
    """Invoke ``paperwiki status`` with a controlled ``PATH`` env var.

    ``CliRunner.invoke`` accepts ``env=`` to control the subprocess env;
    we stage ``PATH`` so the row-4 check (``~/.local/bin`` on PATH) is
    deterministic per test. ``home`` is accepted for fixture symmetry
    even though only ``marketplace`` and ``path_env`` are forwarded.
    """
    del home  # silence unused-arg lint; signature kept for fixture symmetry
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "PATH": path_env})
    return runner.invoke(app, ["status", "--marketplace-dir", str(marketplace)])


# ---------------------------------------------------------------------------
# Helper-level: _check_install_health (direct unit tests)
# ---------------------------------------------------------------------------


class TestCheckInstallHealth:
    """Direct tests of the ``_check_install_health()`` helper."""

    def test_all_healthy_returns_four_ok_rows(
        self, health_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_helper(health_env["helper_path"], version=_PAPERWIKI_VERSION)
        _seed_shim(health_env["shim_path"], version=_PAPERWIKI_VERSION)
        monkeypatch.setenv("PATH", f"{health_env['local_bin']}:/usr/bin:/bin")

        rows = cli_module._check_install_health()

        assert len(rows) == 4
        assert all(ok for _label, ok, _hint in rows), rows

    def test_helper_missing_row_one_fails(
        self, health_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Don't seed helper. Seed shim + PATH so other rows pass.
        _seed_shim(health_env["shim_path"], version=_PAPERWIKI_VERSION)
        monkeypatch.setenv("PATH", f"{health_env['local_bin']}:/usr/bin:/bin")

        rows = cli_module._check_install_health()

        # Row 0 (helper present) and row 1 (helper tag) both fail when
        # the file is missing.
        assert rows[0][1] is False
        assert rows[1][1] is False
        # Action hint mentions restarting Claude Code.
        assert rows[0][2] is not None
        assert "restart Claude Code" in rows[0][2]

    def test_helper_stale_tag_row_two_fails(
        self, health_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Helper present but with a stale version tag.
        _seed_helper(health_env["helper_path"], version="0.0.0")
        _seed_shim(health_env["shim_path"], version=_PAPERWIKI_VERSION)
        monkeypatch.setenv("PATH", f"{health_env['local_bin']}:/usr/bin:/bin")

        rows = cli_module._check_install_health()

        assert rows[0][1] is True  # helper present
        assert rows[1][1] is False  # helper tag stale
        assert rows[1][2] is not None
        assert "restart Claude Code" in rows[1][2]

    def test_shim_missing_row_three_fails(
        self, health_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_helper(health_env["helper_path"], version=_PAPERWIKI_VERSION)
        # Don't seed shim.
        monkeypatch.setenv("PATH", f"{health_env['local_bin']}:/usr/bin:/bin")

        rows = cli_module._check_install_health()

        assert rows[2][1] is False  # combined shim row
        assert rows[2][2] is not None
        assert "restart Claude Code" in rows[2][2]

    def test_shim_stale_tag_row_three_fails(
        self, health_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_helper(health_env["helper_path"], version=_PAPERWIKI_VERSION)
        _seed_shim(health_env["shim_path"], version="0.0.0")
        monkeypatch.setenv("PATH", f"{health_env['local_bin']}:/usr/bin:/bin")

        rows = cli_module._check_install_health()

        # Combined row fails when shim present-but-stale.
        assert rows[2][1] is False

    def test_path_missing_local_bin_row_four_fails(
        self, health_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_helper(health_env["helper_path"], version=_PAPERWIKI_VERSION)
        _seed_shim(health_env["shim_path"], version=_PAPERWIKI_VERSION)
        # PATH does NOT include ~/.local/bin.
        monkeypatch.setenv("PATH", "/usr/bin:/bin")

        rows = cli_module._check_install_health()

        assert rows[3][1] is False  # PATH check row
        assert rows[3][2] is not None
        assert "export PATH" in rows[3][2]


# ---------------------------------------------------------------------------
# Integration: full ``paperwiki status`` output with health section
# ---------------------------------------------------------------------------


class TestStatusHealthSectionOutput:
    """End-to-end output checks via CliRunner."""

    def test_all_healthy_shows_summary_and_four_check_rows(
        self, health_env: dict[str, Path]
    ) -> None:
        _seed_helper(health_env["helper_path"], version=_PAPERWIKI_VERSION)
        _seed_shim(health_env["shim_path"], version=_PAPERWIKI_VERSION)

        result = _run_status(
            health_env["home"],
            health_env["marketplace"],
            path_env=f"{health_env['local_bin']}:/usr/bin:/bin",
        )
        assert result.exit_code == 0, result.output
        # Summary line.
        assert "install health" in result.output
        assert "4/4 healthy" in result.output
        # Four ✓ rows.
        assert result.output.count("✓") == 4, result.output  # ✓ U+2713

    def test_unhealthy_shows_x_rows_and_action_hints(self, health_env: dict[str, Path]) -> None:
        # Only seed PATH; helper + shim absent.
        result = _run_status(
            health_env["home"],
            health_env["marketplace"],
            path_env=f"{health_env['local_bin']}:/usr/bin:/bin",
        )
        assert result.exit_code == 0, result.output
        # 1/4 healthy summary.
        assert "1/4 healthy" in result.output
        # 3 ✗ rows + 1 ✓ row.
        assert result.output.count("✗") == 3, result.output  # ✗ U+2717
        assert result.output.count("✓") == 1, result.output
        # Action hint mentions restart.
        assert "restart Claude Code" in result.output

    def test_path_missing_shows_export_action_hint(self, health_env: dict[str, Path]) -> None:
        _seed_helper(health_env["helper_path"], version=_PAPERWIKI_VERSION)
        _seed_shim(health_env["shim_path"], version=_PAPERWIKI_VERSION)

        result = _run_status(
            health_env["home"],
            health_env["marketplace"],
            path_env="/usr/bin:/bin",  # ~/.local/bin missing
        )
        assert result.exit_code == 0, result.output
        assert "3/4 healthy" in result.output
        assert "export PATH" in result.output

    def test_status_exits_zero_when_completely_unhealthy(self, health_env: dict[str, Path]) -> None:
        """Per D-9.40.1: status command always exits 0 (warn-not-error)."""
        # Don't seed anything. PATH lacks ~/.local/bin.
        result = _run_status(
            health_env["home"],
            health_env["marketplace"],
            path_env="/usr/bin:/bin",
        )
        assert result.exit_code == 0, result.output
        assert "0/4 healthy" in result.output

    def test_existing_status_lines_still_present(self, health_env: dict[str, Path]) -> None:
        """The new health section is APPENDED — original 4 lines preserved."""
        _seed_helper(health_env["helper_path"], version=_PAPERWIKI_VERSION)
        _seed_shim(health_env["shim_path"], version=_PAPERWIKI_VERSION)

        result = _run_status(
            health_env["home"],
            health_env["marketplace"],
            path_env=f"{health_env['local_bin']}:/usr/bin:/bin",
        )
        assert result.exit_code == 0, result.output
        # Pre-existing lines stay (defended by TestCliStatus + TestCliStatusBakLine).
        assert "cache version" in result.output
        assert "marketplace ver" in result.output
        assert "enabledPlugins" in result.output
        assert "bak directories" in result.output
        # New line.
        assert "install health" in result.output


# ---------------------------------------------------------------------------
# v0.3.41 D-9.41.2: paperwiki status --strict flag
# ---------------------------------------------------------------------------


def _run_status_with_flags(
    marketplace: Path,
    *,
    path_env: str,
    extra_args: list[str] | None = None,
):
    """Variant of ``_run_status`` that passes additional CLI flags."""
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "PATH": path_env})
    args = ["status", "--marketplace-dir", str(marketplace)]
    if extra_args:
        args.extend(extra_args)
    return runner.invoke(app, args)


class TestStatusStrictFlag:
    """Plan §18.3 task 9.125 / D-9.41.2.

    The default ``paperwiki status`` exits 0 in all healthy/unhealthy
    combinations (D-9.40.1 warn-not-error). v0.3.41 adds an opt-in
    ``--strict`` flag that flips behaviour to exit 1 on any ✗ row,
    enabling CI/automation to gate on install-health.

    Acceptance criteria:
    (a) ``paperwiki status --strict`` on a healthy install → exit 0.
    (b) ``paperwiki status --strict`` on an unhealthy install → exit 1.
    (c) Default ``paperwiki status`` (no flag) on an unhealthy
        install → exit 0 (D-9.40.1 contract preserved).
    """

    def test_strict_on_healthy_install_exits_zero(self, health_env: dict[str, Path]) -> None:
        _seed_helper(health_env["helper_path"], version=_PAPERWIKI_VERSION)
        _seed_shim(health_env["shim_path"], version=_PAPERWIKI_VERSION)

        result = _run_status_with_flags(
            health_env["marketplace"],
            path_env=f"{health_env['local_bin']}:/usr/bin:/bin",
            extra_args=["--strict"],
        )
        assert result.exit_code == 0, result.output
        # Output content is identical to default mode (only exit code differs).
        assert "4/4 healthy" in result.output

    def test_strict_on_unhealthy_install_exits_one(self, health_env: dict[str, Path]) -> None:
        # Don't seed helper or shim. PATH ok.
        result = _run_status_with_flags(
            health_env["marketplace"],
            path_env=f"{health_env['local_bin']}:/usr/bin:/bin",
            extra_args=["--strict"],
        )
        # Strict mode → non-zero exit.
        assert result.exit_code == 1, (
            f"--strict on unhealthy install must exit 1; got {result.exit_code}:\n{result.output}"
        )
        # Output still shows the health rows (so user sees what failed).
        assert "1/4 healthy" in result.output
        assert "✗" in result.output

    def test_default_mode_on_unhealthy_install_still_exits_zero(
        self, health_env: dict[str, Path]
    ) -> None:
        """D-9.40.1 contract preserved when --strict is NOT passed."""
        # Don't seed helper or shim. PATH ok.
        result = _run_status_with_flags(
            health_env["marketplace"],
            path_env=f"{health_env['local_bin']}:/usr/bin:/bin",
            extra_args=[],  # NO --strict
        )
        assert result.exit_code == 0, (
            f"Default mode (no --strict) must exit 0 even when unhealthy; "
            f"got {result.exit_code}:\n{result.output}"
        )
