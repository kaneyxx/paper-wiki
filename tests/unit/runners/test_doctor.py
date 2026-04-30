"""Unit tests for ``paperwiki.runners.doctor`` (v0.3.43 D-9.43.3).

``paperwiki doctor`` aggregates install-state health checks behind
one command. The pure ``run_doctor`` function (mirrors
``runners/diag.py:render_diag`` design) takes home/claude_home/etc as
args, returns a structured ``DoctorReport``, and never mutates
filesystem or env.

Sections covered:
  - Cache & marketplace (cache version, marketplace version, enabledPlugins)
  - Install integrity (helper present + tag, shim present + tag, ~/.local/bin on PATH)
  - Python venv (venv present, python runs, paperwiki module importable)
  - Shell-rc integration (auto-source block in detected rc; n/a for fish/opt-out)

8 acceptance cases per plan §20.5 9.152.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperwiki.runners.doctor import (
    DoctorReport,
    DoctorRow,
    DoctorSection,
    format_doctor_json,
    format_doctor_pretty,
    run_doctor,
)

# ---------------------------------------------------------------------------
# Fixture helpers — mirror tests/unit/runners/test_diag.py shape
# ---------------------------------------------------------------------------


def _seed_helper(home: Path, *, version: str = "0.3.43") -> Path:
    helper_dir = home / ".local" / "lib" / "paperwiki"
    helper_dir.mkdir(parents=True)
    helper = helper_dir / "bash-helpers.sh"
    helper.write_text(
        f"# paperwiki bash-helpers — v{version} (test stub)\n",
        encoding="utf-8",
    )
    return helper


def _seed_shim(home: Path, *, version: str = "0.3.43") -> Path:
    shim_dir = home / ".local" / "bin"
    shim_dir.mkdir(parents=True)
    shim = shim_dir / "paperwiki"
    shim.write_text(
        f"#!/usr/bin/env bash\n# paperwiki shim — v{version} (test stub)\n",
        encoding="utf-8",
    )
    return shim


def _seed_installed_plugins(claude_home: Path, *, version: str = "0.3.43") -> Path:
    path = claude_home / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "paper-wiki@paper-wiki": [
                        {
                            "scope": "user",
                            "version": version,
                            "installPath": str(
                                claude_home
                                / "plugins"
                                / "cache"
                                / "paper-wiki"
                                / "paper-wiki"
                                / version
                            ),
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _seed_settings(claude_home: Path, *, enabled: bool = True) -> Path:
    path = claude_home / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    enabled_dict: dict[str, bool] = {}
    if enabled:
        enabled_dict["paper-wiki@paper-wiki"] = True
    path.write_text(json.dumps({"enabledPlugins": enabled_dict}), encoding="utf-8")
    return path


def _seed_marketplace(home: Path, *, version: str = "0.3.43") -> Path:
    marketplace_dir = home / ".claude" / "plugins" / "marketplaces" / "paper-wiki"
    (marketplace_dir / ".claude-plugin").mkdir(parents=True)
    (marketplace_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "paper-wiki", "version": version}),
        encoding="utf-8",
    )
    return marketplace_dir


def _seed_venv(home: Path, *, healthy: bool = True) -> Path:
    venv_dir = home / ".config" / "paper-wiki" / "venv"
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    if healthy:
        # Real-ish python that responds to --version + import-paperwiki check.
        py = bin_dir / "python"
        py.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "--version" ]; then\n'
            "  echo 'Python 3.13.1'\n"
            'elif [ "$1" = "-c" ]; then\n'
            "  exit 0\n"
            "fi\n",
            encoding="utf-8",
        )
        py.chmod(0o755)
    return venv_dir


def _seed_zshrc_with_block(home: Path) -> Path:
    rc = home / ".zshrc"
    rc.write_text(
        "# user content above\n"
        "# >>> paperwiki helpers >>> (managed by paperwiki — do not edit between markers)\n"
        '[ -f "$HOME/.local/lib/paperwiki/bash-helpers.sh" ] '
        '&& . "$HOME/.local/lib/paperwiki/bash-helpers.sh"\n'
        "# <<< paperwiki helpers <<<\n",
        encoding="utf-8",
    )
    return rc


# ---------------------------------------------------------------------------
# Common doctor-call helper — mirrors a healthy fully-installed env.
# ---------------------------------------------------------------------------


def _doctor_args(tmp_path: Path, *, version: str = "0.3.43") -> dict[str, object]:
    home = tmp_path / "home"
    claude_home = home / ".claude"
    home.mkdir()
    return {
        "home": home,
        "claude_home": claude_home,
        "bak_root": home / ".local" / "share" / "paperwiki" / "bak",
        "venv_dir": home / ".config" / "paper-wiki" / "venv",
        "marketplace_dir": home / ".claude" / "plugins" / "marketplaces" / "paper-wiki",
        "shell": "/bin/zsh",
        "path_env": str(home / ".local" / "bin") + ":/usr/bin",
        "expected_version": version,
        "rc_integration_disabled": False,
    }


# ---------------------------------------------------------------------------
# 1. All-healthy → 9/9 (or whatever total the doctor reports)
# ---------------------------------------------------------------------------


def test_run_doctor_all_healthy_passes_every_row(tmp_path: Path) -> None:
    args = _doctor_args(tmp_path)
    home = args["home"]
    claude_home = args["claude_home"]
    assert isinstance(home, Path)
    assert isinstance(claude_home, Path)

    _seed_helper(home, version="0.3.43")
    _seed_shim(home, version="0.3.43")
    _seed_installed_plugins(claude_home, version="0.3.43")
    _seed_settings(claude_home, enabled=True)
    _seed_marketplace(home, version="0.3.43")
    _seed_venv(home, healthy=True)
    _seed_zshrc_with_block(home)

    report = run_doctor(**args)  # type: ignore[arg-type]

    assert isinstance(report, DoctorReport)
    assert report.total >= 9, f"expected >= 9 rows, got {report.total}"
    assert report.healthy == report.total, (
        f"expected all rows healthy; got {report.healthy}/{report.total}\n"
        f"failing: "
        + str([(s.name, r.label) for s in report.sections for r in s.rows if not (r.ok or r.na)])
    )


# ---------------------------------------------------------------------------
# 2. Missing venv → ✗ on venv-present row + hint
# ---------------------------------------------------------------------------


def test_run_doctor_missing_venv_marks_unhealthy(tmp_path: Path) -> None:
    args = _doctor_args(tmp_path)
    home = args["home"]
    claude_home = args["claude_home"]
    assert isinstance(home, Path)
    assert isinstance(claude_home, Path)
    _seed_helper(home, version="0.3.43")
    _seed_shim(home, version="0.3.43")
    _seed_installed_plugins(claude_home, version="0.3.43")
    _seed_settings(claude_home, enabled=True)
    _seed_marketplace(home, version="0.3.43")
    # Skip venv setup on purpose.
    _seed_zshrc_with_block(home)

    report = run_doctor(**args)  # type: ignore[arg-type]

    venv_section = next((s for s in report.sections if "venv" in s.name.lower()), None)
    assert venv_section is not None, f"missing venv section: {[s.name for s in report.sections]}"
    # Every venv row should be unhealthy when the venv is missing.
    unhealthy_rows = [r for r in venv_section.rows if not r.ok and not r.na]
    venv_row_summary = [(r.label, r.ok) for r in venv_section.rows]
    assert unhealthy_rows, f"expected at least one unhealthy venv row, got {venv_row_summary}"
    # The unhealthy rows must carry an actionable hint.
    hint_summary = [(r.label, r.hint) for r in unhealthy_rows]
    assert all(r.hint is not None for r in unhealthy_rows), (
        f"unhealthy venv rows must include action hints: {hint_summary}"
    )
    assert report.healthy < report.total


# ---------------------------------------------------------------------------
# 3. Missing shim → ✗ on shim row
# ---------------------------------------------------------------------------


def test_run_doctor_missing_shim_marks_unhealthy(tmp_path: Path) -> None:
    args = _doctor_args(tmp_path)
    home = args["home"]
    claude_home = args["claude_home"]
    assert isinstance(home, Path)
    assert isinstance(claude_home, Path)
    _seed_helper(home, version="0.3.43")
    # Skip shim
    _seed_installed_plugins(claude_home, version="0.3.43")
    _seed_settings(claude_home, enabled=True)
    _seed_marketplace(home, version="0.3.43")
    _seed_venv(home, healthy=True)
    _seed_zshrc_with_block(home)

    report = run_doctor(**args)  # type: ignore[arg-type]

    shim_rows = [r for s in report.sections for r in s.rows if "shim" in r.label.lower()]
    assert shim_rows, "expected at least one shim row"
    shim_summary = [(r.label, r.ok) for r in shim_rows]
    assert any(not r.ok for r in shim_rows), (
        f"expected at least one shim row to be unhealthy, got {shim_summary}"
    )


# ---------------------------------------------------------------------------
# 4. Missing rc-block → ✗ on rc row
# ---------------------------------------------------------------------------


def test_run_doctor_missing_rc_block_marks_unhealthy(tmp_path: Path) -> None:
    args = _doctor_args(tmp_path)
    home = args["home"]
    claude_home = args["claude_home"]
    assert isinstance(home, Path)
    assert isinstance(claude_home, Path)
    _seed_helper(home, version="0.3.43")
    _seed_shim(home, version="0.3.43")
    _seed_installed_plugins(claude_home, version="0.3.43")
    _seed_settings(claude_home, enabled=True)
    _seed_marketplace(home, version="0.3.43")
    _seed_venv(home, healthy=True)
    # Create the rc file but WITHOUT the marker block.
    (home / ".zshrc").write_text("# vanilla rc, no paperwiki block\n", encoding="utf-8")

    report = run_doctor(**args)  # type: ignore[arg-type]

    rc_section = next(
        (s for s in report.sections if "rc" in s.name.lower() or "shell" in s.name.lower()), None
    )
    assert rc_section is not None, f"missing rc section: {[s.name for s in report.sections]}"
    rc_rows = list(rc_section.rows)
    rc_summary = [(r.label, r.ok, r.na) for r in rc_rows]
    assert any(not r.ok and not r.na for r in rc_rows), (
        f"expected at least one rc row to be unhealthy, got {rc_summary}"
    )


# ---------------------------------------------------------------------------
# 5. PAPERWIKI_NO_RC_INTEGRATION=1 → rc row is n/a (counted as healthy)
# ---------------------------------------------------------------------------


def test_run_doctor_opt_out_env_treats_rc_block_as_na(tmp_path: Path) -> None:
    args = _doctor_args(tmp_path)
    args["rc_integration_disabled"] = True
    home = args["home"]
    claude_home = args["claude_home"]
    assert isinstance(home, Path)
    assert isinstance(claude_home, Path)
    _seed_helper(home, version="0.3.43")
    _seed_shim(home, version="0.3.43")
    _seed_installed_plugins(claude_home, version="0.3.43")
    _seed_settings(claude_home, enabled=True)
    _seed_marketplace(home, version="0.3.43")
    _seed_venv(home, healthy=True)
    # No rc block written — but opt-out flag means we don't expect one.

    report = run_doctor(**args)  # type: ignore[arg-type]

    rc_section = next(
        (s for s in report.sections if "rc" in s.name.lower() or "shell" in s.name.lower()), None
    )
    assert rc_section is not None
    # The rc row should be marked n/a, not ✗.
    assert any(r.na for r in rc_section.rows), (
        f"expected at least one rc row to be n/a (opt-out): "
        f"{[(r.label, r.ok, r.na) for r in rc_section.rows]}"
    )
    # Overall: all rows are either ok or n/a.
    assert report.healthy == report.total


# ---------------------------------------------------------------------------
# 6. JSON mode roundtrips the report shape
# ---------------------------------------------------------------------------


def test_format_doctor_json_roundtrips(tmp_path: Path) -> None:
    args = _doctor_args(tmp_path)
    home = args["home"]
    claude_home = args["claude_home"]
    assert isinstance(home, Path)
    assert isinstance(claude_home, Path)
    _seed_helper(home, version="0.3.43")
    _seed_shim(home, version="0.3.43")
    _seed_installed_plugins(claude_home, version="0.3.43")
    _seed_settings(claude_home, enabled=True)
    _seed_marketplace(home, version="0.3.43")
    _seed_venv(home, healthy=True)
    _seed_zshrc_with_block(home)

    report = run_doctor(**args)  # type: ignore[arg-type]
    json_str = format_doctor_json(report)

    parsed = json.loads(json_str)
    assert isinstance(parsed, dict)
    assert "sections" in parsed
    assert "healthy" in parsed
    assert "total" in parsed
    assert parsed["healthy"] == report.healthy
    assert parsed["total"] == report.total
    # Each section has rows with (label, ok, hint, na) shape.
    for section in parsed["sections"]:
        assert "name" in section
        assert "rows" in section
        for row in section["rows"]:
            assert {"label", "ok"}.issubset(row.keys())


# ---------------------------------------------------------------------------
# 7. Pretty format includes section headers + healthy/total summary
# ---------------------------------------------------------------------------


def test_format_doctor_pretty_includes_summary(tmp_path: Path) -> None:
    args = _doctor_args(tmp_path)
    home = args["home"]
    claude_home = args["claude_home"]
    assert isinstance(home, Path)
    assert isinstance(claude_home, Path)
    _seed_helper(home, version="0.3.43")
    _seed_shim(home, version="0.3.43")
    _seed_installed_plugins(claude_home, version="0.3.43")
    _seed_settings(claude_home, enabled=True)
    _seed_marketplace(home, version="0.3.43")
    _seed_venv(home, healthy=True)
    _seed_zshrc_with_block(home)

    report = run_doctor(**args)  # type: ignore[arg-type]
    out = format_doctor_pretty(report)

    assert "paper-wiki" in out.lower()
    # Section headers appear.
    for section in report.sections:
        assert section.name in out
    # Overall summary line.
    assert f"{report.healthy}/{report.total}" in out


# ---------------------------------------------------------------------------
# 8. Fish shell → rc row is n/a (not unhealthy)
# ---------------------------------------------------------------------------


def test_run_doctor_fish_shell_marks_rc_block_na(tmp_path: Path) -> None:
    args = _doctor_args(tmp_path)
    args["shell"] = "/usr/local/bin/fish"
    home = args["home"]
    claude_home = args["claude_home"]
    assert isinstance(home, Path)
    assert isinstance(claude_home, Path)
    _seed_helper(home, version="0.3.43")
    _seed_shim(home, version="0.3.43")
    _seed_installed_plugins(claude_home, version="0.3.43")
    _seed_settings(claude_home, enabled=True)
    _seed_marketplace(home, version="0.3.43")
    _seed_venv(home, healthy=True)

    report = run_doctor(**args)  # type: ignore[arg-type]

    rc_section = next(
        (s for s in report.sections if "rc" in s.name.lower() or "shell" in s.name.lower()), None
    )
    assert rc_section is not None
    # On fish, the bash-helpers auto-source row should be n/a.
    assert any(r.na for r in rc_section.rows), (
        f"expected at least one rc row to be n/a (fish shell): "
        f"{[(r.label, r.ok, r.na) for r in rc_section.rows]}"
    )


# ---------------------------------------------------------------------------
# 9. DoctorRow / DoctorSection / DoctorReport dataclasses are immutable
# ---------------------------------------------------------------------------


def test_doctor_dataclasses_are_frozen() -> None:
    """The result types must be immutable so consumers can cache/share them."""
    row = DoctorRow(label="x", ok=True)
    with pytest.raises((AttributeError, TypeError)):
        row.label = "y"  # type: ignore[misc]
    section = DoctorSection(name="x", rows=[row])
    with pytest.raises((AttributeError, TypeError)):
        section.name = "y"  # type: ignore[misc]
