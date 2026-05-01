"""``paperwiki status --vault <path>`` surfaces run-status ledger (task 9.167).

The status command grew an opt-in ``--vault`` flag in v0.4.x: when
present, the last 5 entries from ``<vault>/.paperwiki/run-status.jsonl``
are printed after the install-health section so users can audit recent
digest outcomes (success counts, source errors, schema failures)
without grepping JSONL by hand.

Without the flag, the status command's existing 4-line + health-check
output is unchanged — the run-status section only appears when the
user opts into it. This keeps automation that pipes status output
unaffected.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperwiki import __version__ as _PAPERWIKI_VERSION  # noqa: N812 — constant alias
from paperwiki import cli as cli_module
from paperwiki._internal.run_status import (
    LEDGER_DIR,
    LEDGER_FILE,
    RunStatusEntry,
    append_run_status,
)
from paperwiki.cli import app


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stage a fake $HOME so the install-health preamble renders cleanly.

    Mirrors the seeding in ``test_status_health.py`` — without it the
    cache/marketplace lines would crash before our new section runs.
    """
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

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

    marketplace.mkdir(parents=True)
    (marketplace / ".claude-plugin").mkdir()
    (marketplace / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "paper-wiki", "version": _PAPERWIKI_VERSION}),
        encoding="utf-8",
    )
    cache_base.mkdir(parents=True)
    return home


def _entry(recipe: str, *, error: str | None = None) -> RunStatusEntry:
    return RunStatusEntry(
        timestamp=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        recipe=recipe,
        target_date=datetime(2026, 5, 1, tzinfo=UTC),
        source_counts={"arxiv": 12},
        source_errors={},
        filter_drops={"recency": 4},
        final_count=8,
        elapsed_ms=1500,
        error_class=error,
        error_message=error,
    )


class TestStatusRunLedgerSection:
    def test_omits_section_without_vault_flag(self, fake_home: Path) -> None:
        """Existing call sites stay untouched when --vault is absent."""
        result = CliRunner().invoke(app, ["status"])
        assert result.exit_code == 0
        assert "recent runs" not in result.output.lower()

    def test_prints_last_n_entries_with_vault_flag(self, fake_home: Path, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        for i in range(7):
            append_run_status(vault, _entry(f"recipe-{i}"))

        result = CliRunner().invoke(app, ["status", "--vault", str(vault)])
        assert result.exit_code == 0
        # Section header appears.
        assert "recent runs" in result.output.lower()
        # Last 5 recipe names show up; the 2 oldest do not.
        for i in (2, 3, 4, 5, 6):
            assert f"recipe-{i}" in result.output
        for i in (0, 1):
            assert f"recipe-{i}" not in result.output

    def test_prints_friendly_message_on_missing_ledger(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        # No append → ledger does not exist.

        result = CliRunner().invoke(app, ["status", "--vault", str(vault)])
        assert result.exit_code == 0
        # Some "no runs" / "no entries" hint is shown rather than crashing.
        assert "no runs" in result.output.lower() or "no entries" in result.output.lower()

    def test_marks_failed_runs_with_error_class(self, fake_home: Path, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        append_run_status(vault, _entry("good-run"))
        append_run_status(vault, _entry("bad-run", error="UserError"))

        result = CliRunner().invoke(app, ["status", "--vault", str(vault)])
        assert result.exit_code == 0
        assert "good-run" in result.output
        assert "bad-run" in result.output
        # The error class shows up next to the failing run.
        assert "UserError" in result.output

    def test_ledger_path_is_dotpaperwiki_runstatus(self, fake_home: Path, tmp_path: Path) -> None:
        """Sanity check: append_run_status writes under the documented namespace."""
        vault = tmp_path / "vault"
        vault.mkdir()
        append_run_status(vault, _entry("anchor"))
        assert (vault / LEDGER_DIR / LEDGER_FILE).is_file()
