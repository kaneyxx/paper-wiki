"""Unit tests for paperwiki.runners.diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperwiki.runners import diagnostics as diagnostics_runner


@pytest.fixture(autouse=True)
def _stub_claude_mcp_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: stub ``claude mcp list`` so tests never shell out for real.

    Individual tests that care about the MCP behavior re-patch
    ``diagnostics_runner.subprocess.run`` themselves and override this.
    """

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="No MCP servers configured.\n", stderr=""
        )

    monkeypatch.setattr(diagnostics_runner.subprocess, "run", fake_run)


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


class TestBuildReport:
    def test_includes_paperwiki_version(self) -> None:
        report = diagnostics_runner.build_report()
        assert report.paperwiki_version
        assert report.paperwiki_version.count(".") >= 2

    def test_includes_python_version(self) -> None:
        report = diagnostics_runner.build_report()
        expected = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        assert report.python_version == expected

    def test_plugin_root_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        # venv stamp absent by default.
        report = diagnostics_runner.build_report()
        assert report.plugin_root == str(tmp_path)
        assert report.venv_path == str(tmp_path / ".venv")
        assert report.venv_installed_stamp is False
        assert any("venv .installed stamp missing" in issue for issue in report.issues)

    def test_plugin_root_unset_warns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        report = diagnostics_runner.build_report()
        assert report.plugin_root == ""
        assert any("CLAUDE_PLUGIN_ROOT" in i for i in report.issues)

    def test_venv_stamp_detected_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / ".installed").write_text("")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        report = diagnostics_runner.build_report()
        assert report.venv_installed_stamp is True
        assert all("stamp missing" not in i for i in report.issues)

    def test_lists_bundled_recipes(self) -> None:
        report = diagnostics_runner.build_report()
        assert "daily-arxiv.yaml" in report.bundled_recipes
        assert all(name.endswith(".yaml") for name in report.bundled_recipes)

    def test_config_path_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Without XDG_CONFIG_HOME, fall back to ~/.config/paperwiki
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        report = diagnostics_runner.build_report()
        assert report.config_path.endswith(".config/paperwiki/config.toml")

    def test_config_path_uses_xdg(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        report = diagnostics_runner.build_report()
        assert report.config_path == str(tmp_path / "paperwiki" / "config.toml")
        assert report.config_exists is False

    def test_config_existence_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_dir = tmp_path / "paperwiki"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text("vault_path = '/tmp'\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        report = diagnostics_runner.build_report()
        assert report.config_exists is True


# ---------------------------------------------------------------------------
# mcp_servers detection (Phase 7.1)
# ---------------------------------------------------------------------------


class TestMcpServersDetection:
    """`build_report.mcp_servers` reflects ``claude mcp list`` output."""

    @staticmethod
    def _patch_claude_mcp_list(
        monkeypatch: pytest.MonkeyPatch,
        *,
        stdout: str,
        returncode: int = 0,
    ) -> None:
        """Stub ``subprocess.run`` so the test never shells out for real."""
        import subprocess as sp_real

        def fake_run(*args: object, **kwargs: object) -> sp_real.CompletedProcess[str]:
            return sp_real.CompletedProcess(
                args=args, returncode=returncode, stdout=stdout, stderr=""
            )

        monkeypatch.setattr(diagnostics_runner.subprocess, "run", fake_run)

    def test_lists_registered_mcp_servers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_claude_mcp_list(
            monkeypatch,
            stdout=(
                "Checking MCP server health...\n"
                "\n"
                "paperclip: https://paperclip.gxl.ai/mcp - ✓ Connected\n"
                "plugin:oh-my-claudecode:t: node /tmp/server.js - ✓ Connected\n"
            ),
        )
        report = diagnostics_runner.build_report()
        assert "paperclip" in report.mcp_servers
        assert "plugin:oh-my-claudecode:t" in report.mcp_servers

    def test_empty_when_no_mcp_servers_registered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_claude_mcp_list(
            monkeypatch,
            stdout="Checking MCP server health...\n\nNo MCP servers configured.\n",
        )
        report = diagnostics_runner.build_report()
        assert report.mcp_servers == []

    def test_claude_cli_missing_records_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If ``claude`` isn't on PATH, surface gracefully — never raise."""

        def raises_filenotfound(*args: object, **kwargs: object) -> object:
            raise FileNotFoundError("claude")

        monkeypatch.setattr(diagnostics_runner.subprocess, "run", raises_filenotfound)
        report = diagnostics_runner.build_report()
        assert report.mcp_servers == []
        assert any("claude CLI not found" in i for i in report.issues)

    def test_claude_cli_failure_records_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-zero exit → empty list + issue, not a crash."""
        self._patch_claude_mcp_list(monkeypatch, stdout="oh no\n", returncode=1)
        report = diagnostics_runner.build_report()
        assert report.mcp_servers == []
        assert any("claude mcp list" in i for i in report.issues)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCli:
    def test_prints_valid_json(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        runner = CliRunner()
        result = runner.invoke(diagnostics_runner.app, [])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert "paperwiki_version" in payload
        assert "python_version" in payload
        assert "issues" in payload
