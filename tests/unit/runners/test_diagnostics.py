"""Unit tests for paperwiki.runners.diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from paperwiki.runners import diagnostics as diagnostics_runner

if TYPE_CHECKING:
    import pytest

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
