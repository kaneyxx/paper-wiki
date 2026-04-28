"""Unit tests for paperwiki.runners.where (Task 9.35, v0.3.29 / D-9.31.5).

Replaces user's mental "where is everything?" check with one command:

    paperwiki where [--json] [-v]

Surfaces all paperwiki paths on disk with sizes:
- config + venv root (PAPERWIKI_HOME)
- plugin cache (active + bak versions)
- marketplace clone
- ~/.local/bin/paperwiki shim
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from paperwiki.runners.where import (
    PathReport,
    build_where_report,
    format_human_report,
)

if TYPE_CHECKING:
    import pytest


def _make_paperwiki_home(tmp_path: Path, *, with_venv: bool = True) -> Path:
    """Synthesise a fake PAPERWIKI_HOME with recipes/secrets/venv."""
    home = tmp_path / ".config" / "paper-wiki"
    (home / "recipes").mkdir(parents=True)
    (home / "recipes" / "daily.yaml").write_text("name: daily\n", encoding="utf-8")
    (home / "secrets.env").write_text("PAPERWIKI_S2_API_KEY=stub\n", encoding="utf-8")
    if with_venv:
        (home / "venv" / "bin").mkdir(parents=True)
        (home / "venv" / ".installed").write_text("0.3.29", encoding="utf-8")
        (home / "venv" / "bin" / "python").write_text("#!/usr/bin/env python\n", encoding="utf-8")
    return home


def _make_plugin_cache(tmp_path: Path) -> Path:
    """Synthesise a Claude-Code-style plugin cache root with bak history."""
    cache = tmp_path / ".claude" / "plugins" / "cache" / "paper-wiki" / "paper-wiki"
    (cache / "0.3.29").mkdir(parents=True)
    (cache / "0.3.29" / "src" / "paperwiki").mkdir(parents=True)
    (cache / "0.3.29" / "src" / "paperwiki" / "__init__.py").write_text(
        '__version__ = "0.3.29"\n', encoding="utf-8"
    )
    for bak in ("0.3.28.bak.20260101T000000Z", "0.3.27.bak.20251201T000000Z"):
        (cache / bak).mkdir()
        (cache / bak / "sentinel.txt").write_text("seed", encoding="utf-8")
    return cache


def _make_shim(tmp_path: Path) -> Path:
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    shim = bin_dir / "paperwiki"
    shim.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    shim.chmod(0o755)
    return shim


class TestPathReport:
    def test_existing_file_reports_size(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_text("hello", encoding="utf-8")
        report = PathReport.from_path(target, label="test")
        assert report.exists is True
        assert report.size_bytes == 5
        assert "B" in report.size_human or "byte" in report.size_human.lower()

    def test_existing_dir_reports_recursive_size(self, tmp_path: Path) -> None:
        d = tmp_path / "d"
        d.mkdir()
        (d / "a.txt").write_text("12345", encoding="utf-8")
        (d / "sub").mkdir()
        (d / "sub" / "b.txt").write_text("67890", encoding="utf-8")
        report = PathReport.from_path(d, label="d")
        assert report.exists is True
        assert report.size_bytes == 10  # 5 + 5

    def test_missing_path_reports_zero(self, tmp_path: Path) -> None:
        report = PathReport.from_path(tmp_path / "nope", label="nope")
        assert report.exists is False
        assert report.size_bytes == 0

    def test_human_size_formats_kb_mb(self, tmp_path: Path) -> None:
        target = tmp_path / "big.bin"
        target.write_bytes(b"\x00" * 1024 * 1024 * 5)  # 5 MB
        report = PathReport.from_path(target, label="big")
        assert "MB" in report.size_human or "M" in report.size_human


class TestBuildWhereReport:
    def test_includes_all_path_categories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _make_paperwiki_home(tmp_path)
        _make_plugin_cache(tmp_path)
        shim = _make_shim(tmp_path)

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PAPERWIKI_HOME", str(home))
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(p).replace("~", str(tmp_path)))

        report = build_where_report()
        # Top-level keys present.
        assert report.paperwiki_home is not None
        assert report.recipes_dir is not None
        assert report.secrets_path is not None
        assert report.venv_dir is not None
        assert report.cache_root is not None
        assert report.shim_path is not None

        # Discovered the synthesised paths.
        assert report.paperwiki_home.path == str(home)
        assert report.paperwiki_home.exists is True
        assert report.shim_path.path == str(shim)

    def test_active_cache_version_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _make_paperwiki_home(tmp_path)
        _make_plugin_cache(tmp_path)
        _make_shim(tmp_path)

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PAPERWIKI_HOME", str(home))

        report = build_where_report()
        assert report.cache_active_version == "0.3.29"
        assert sorted(report.cache_bak_versions) == [
            "0.3.27.bak.20251201T000000Z",
            "0.3.28.bak.20260101T000000Z",
        ]

    def test_missing_paths_handled_gracefully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No paperwiki_home, no cache, no shim.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path / "nonexistent"))

        report = build_where_report()
        assert report.paperwiki_home.exists is False
        assert report.cache_root.exists is False
        assert report.shim_path.exists is False
        assert report.cache_active_version is None
        assert report.cache_bak_versions == []
        # Shouldn't crash.

    def test_total_disk_used_aggregates_existing_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _make_paperwiki_home(tmp_path)
        _make_plugin_cache(tmp_path)
        _make_shim(tmp_path)

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PAPERWIKI_HOME", str(home))

        report = build_where_report()
        assert report.total_disk_used_bytes > 0


class TestFormatHumanReport:
    def test_human_output_lists_every_label(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _make_paperwiki_home(tmp_path)
        _make_plugin_cache(tmp_path)
        _make_shim(tmp_path)

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PAPERWIKI_HOME", str(home))

        report = build_where_report()
        text = format_human_report(report)
        # Every documented path label in the planned output.
        for label in ("config + venv", "plugin cache", "shim"):
            assert label in text, f"human report missing label {label!r}"

    def test_human_output_includes_total(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _make_paperwiki_home(tmp_path)
        _make_plugin_cache(tmp_path)
        _make_shim(tmp_path)

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PAPERWIKI_HOME", str(home))

        report = build_where_report()
        text = format_human_report(report)
        assert "total disk used" in text.lower()


class TestCli:
    def test_help_lists_json_flag(self) -> None:
        from typer.testing import CliRunner

        from paperwiki.runners.where import app

        result = CliRunner().invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--json" in result.output

    def test_default_human_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner

        from paperwiki.runners.where import app

        home = _make_paperwiki_home(tmp_path)
        _make_plugin_cache(tmp_path)
        _make_shim(tmp_path)

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PAPERWIKI_HOME", str(home))

        result = CliRunner().invoke(app, [])
        assert result.exit_code == 0, result.output
        assert "config + venv" in result.output
        assert "plugin cache" in result.output

    def test_json_output_parseable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner

        from paperwiki.runners.where import app

        home = _make_paperwiki_home(tmp_path)
        _make_plugin_cache(tmp_path)
        _make_shim(tmp_path)

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PAPERWIKI_HOME", str(home))

        result = CliRunner().invoke(app, ["--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        # Has the documented top-level keys.
        for key in (
            "paperwiki_home",
            "recipes_dir",
            "secrets_path",
            "venv_dir",
            "cache_root",
            "cache_active_version",
            "cache_bak_versions",
            "shim_path",
            "total_disk_used_bytes",
        ):
            assert key in payload, f"JSON output missing key {key!r}"
