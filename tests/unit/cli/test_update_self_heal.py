"""Unit tests for v0.3.39 ``paperwiki update`` self-heal (D-9.39.1).

When the plugin cache at ``~/.claude/plugins/cache/paper-wiki/paper-wiki/``
contains no version subdirs (regex ``^\\d+\\.\\d+\\.\\d+$``), the update
runner must bootstrap from the marketplace clone before running the
existing diff-and-sync logic. This module covers the four acceptance
cases from plan §16.3 task 9.112:

(a) Empty cache → self-heal succeeds.
(b) Cache with only non-version dirs (``.bak.*``) → self-heal succeeds.
(c) Cache with ≥1 version dir → no self-heal (existing logic runs).
(d) Marketplace clone missing → clear error message (existing path).

Plus a direct unit test for the new ``_cache_has_any_version`` helper.

All filesystem state is staged under ``tmp_path``; the ``paperwiki.cli``
module-level constants (``_CACHE_BASE``, ``_INSTALLED_PLUGINS_JSON``,
``_SETTINGS_JSON``, ``_SETTINGS_LOCAL_JSON``) are monkeypatched per test
because they are resolved at import time and don't honor a runtime
``Path.home()`` override.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from paperwiki import cli as cli_module
from paperwiki.cli import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def update_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Stage a fake $HOME + monkeypatch the cli module's path constants.

    Returns a dict with the cache_base + marketplace_dir + installed_plugins
    paths so tests can directly populate / inspect them.
    """
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    cache_base = home / ".claude" / "plugins" / "cache" / "paper-wiki" / "paper-wiki"
    marketplace_dir = home / ".claude" / "plugins" / "marketplaces" / "paper-wiki"
    installed_plugins = home / ".claude" / "plugins" / "installed_plugins.json"
    settings_json = home / ".claude" / "settings.json"
    settings_local_json = home / ".claude" / "settings.local.json"

    monkeypatch.setattr(cli_module, "_CACHE_BASE", cache_base)
    monkeypatch.setattr(cli_module, "_INSTALLED_PLUGINS_JSON", installed_plugins)
    monkeypatch.setattr(cli_module, "_SETTINGS_JSON", settings_json)
    monkeypatch.setattr(cli_module, "_SETTINGS_LOCAL_JSON", settings_local_json)
    monkeypatch.setattr(cli_module, "_DEFAULT_MARKETPLACE_DIR", marketplace_dir)

    # Stub the git pull — tests provide a flat marketplace clone, not a
    # real git repo. The self-heal logic doesn't need a fresh fetch.
    monkeypatch.setattr(cli_module, "_git_pull", lambda _dir: None)

    return {
        "home": home,
        "cache_base": cache_base,
        "marketplace_dir": marketplace_dir,
        "installed_plugins": installed_plugins,
    }


def _seed_marketplace(marketplace_dir: Path, version: str) -> None:
    """Build a minimal fake marketplace clone with a plugin.json + sentinel content."""
    marketplace_dir.mkdir(parents=True, exist_ok=True)
    (marketplace_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (marketplace_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "paper-wiki", "version": version}),
        encoding="utf-8",
    )
    (marketplace_dir / "lib").mkdir(parents=True, exist_ok=True)
    (marketplace_dir / "lib" / "bash-helpers.sh").write_text(
        f"# paperwiki bash-helpers — v{version} (test fixture)\n",
        encoding="utf-8",
    )
    # A sentinel file so we can verify the copytree actually happened.
    (marketplace_dir / "MARKETPLACE_SENTINEL").write_text("yes", encoding="utf-8")


def _seed_installed_plugins_json(path: Path, version: str) -> None:
    """Pre-populate installed_plugins.json with a paper-wiki entry at ``version``."""
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
                                path.parent / "cache" / "paper-wiki" / "paper-wiki" / version
                            ),
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Helper-level: _cache_has_any_version
# ---------------------------------------------------------------------------


class TestCacheHasAnyVersion:
    def test_returns_false_when_cache_dir_does_not_exist(self, tmp_path: Path) -> None:
        cache = tmp_path / "nonexistent"
        assert cli_module._cache_has_any_version(cache) is False

    def test_returns_false_when_cache_dir_is_empty(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        cache.mkdir()
        assert cli_module._cache_has_any_version(cache) is False

    def test_returns_false_when_cache_has_only_bak_dirs(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        (cache / "0.3.37.bak.20260428T120000Z").mkdir(parents=True)
        (cache / "0.3.36.bak.20260427T120000Z").mkdir(parents=True)
        assert cli_module._cache_has_any_version(cache) is False

    def test_returns_true_when_cache_has_version_dir(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        (cache / "0.3.38").mkdir(parents=True)
        assert cli_module._cache_has_any_version(cache) is True

    def test_returns_true_even_with_mix_of_version_and_bak(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        (cache / "0.3.38").mkdir(parents=True)
        (cache / "0.3.37.bak.20260428T120000Z").mkdir(parents=True)
        assert cli_module._cache_has_any_version(cache) is True


# ---------------------------------------------------------------------------
# Integration: the full ``paperwiki update`` flow with self-heal
# ---------------------------------------------------------------------------


class TestUpdateSelfHeal:
    def test_self_heals_when_cache_completely_empty(self, update_env: dict[str, Path]) -> None:
        """(a) Cache dir doesn't exist + marketplace at v0.3.38 → cache populated."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]
        _seed_marketplace(marketplace, "0.3.38")
        # No installed_plugins.json — that's also part of the broken state.

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--marketplace-dir", str(update_env["marketplace_dir"])],
        )

        assert result.exit_code == 0, result.output
        assert "bootstrapped from marketplace at v0.3.38" in result.output
        # Cache populated at v0.3.38 with marketplace contents.
        assert (cache_base / "0.3.38").is_dir()
        assert (cache_base / "0.3.38" / "MARKETPLACE_SENTINEL").read_text() == "yes"
        assert (cache_base / "0.3.38" / "lib" / "bash-helpers.sh").is_file()

    def test_self_heals_when_cache_has_only_bak_dirs(self, update_env: dict[str, Path]) -> None:
        """(b) Cache contains only ``.bak.*`` dirs (no version dir) → self-heal fires.

        v0.3.43 D-9.43.2 update: legacy ``.bak`` directories under the
        plugin cache subdir are now migrated to ``~/.local/share/paperwiki/bak/``
        as part of the update flow. The migration runs at the start of
        the apply branch — *after* self-heal but before the cache rename.
        Self-heal short-circuits ("already at v0.3.38") so migration
        does NOT run in this scenario; the legacy bak stays in cache.
        """
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]
        _seed_marketplace(marketplace, "0.3.38")
        # Pre-existing .bak dir from a prior failed install.
        bak_dir = cache_base / "0.3.37.bak.20260428T120000Z"
        bak_dir.mkdir(parents=True)
        (bak_dir / "old_sentinel.txt").write_text("backup", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--marketplace-dir", str(update_env["marketplace_dir"])],
        )

        assert result.exit_code == 0, result.output
        assert "bootstrapped from marketplace at v0.3.38" in result.output
        # New version dir created.
        assert (cache_base / "0.3.38").is_dir()
        assert (cache_base / "0.3.38" / "MARKETPLACE_SENTINEL").read_text() == "yes"
        # Old .bak dir contents survive — either still in cache (if self-heal
        # short-circuited before migration) or relocated to the new bak root.
        legacy_in_cache = bak_dir.is_dir()
        bak_root_default = update_env["home"] / ".local" / "share" / "paperwiki" / "bak"
        migrated = bak_root_default / "0.3.37.bak.20260428T120000Z"
        legacy_at_new = migrated.is_dir()
        assert legacy_in_cache or legacy_at_new, (
            "legacy .bak should be present at either the old or new location"
        )
        # The actual contents survive regardless of which location.
        if legacy_in_cache:
            assert (bak_dir / "old_sentinel.txt").read_text() == "backup"
        else:
            assert (migrated / "old_sentinel.txt").read_text() == "backup"

    def test_no_self_heal_when_version_dir_already_present(
        self, update_env: dict[str, Path]
    ) -> None:
        """(c) Cache has ≥1 version dir → bootstrap skipped, normal flow runs."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]
        _seed_marketplace(marketplace, "0.3.38")
        # Existing cache at v0.3.38 (marketplace == cache).
        existing = cache_base / "0.3.38"
        existing.mkdir(parents=True)
        (existing / "EXISTING_SENTINEL").write_text("preserved", encoding="utf-8")
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.38")

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--marketplace-dir", str(update_env["marketplace_dir"])],
        )

        assert result.exit_code == 0, result.output
        # NO bootstrap message — cache wasn't empty.
        assert "bootstrapped from marketplace" not in result.output
        # Normal "already at" path runs; existing files untouched.
        assert "already at 0.3.38" in result.output
        assert (existing / "EXISTING_SENTINEL").read_text() == "preserved"
        # New marketplace files NOT copied (no overwrite of existing version dir).
        assert not (existing / "MARKETPLACE_SENTINEL").exists()

    def test_marketplace_clone_missing_errors_clearly(self, update_env: dict[str, Path]) -> None:
        """(d) Marketplace clone missing → existing error path fires; no self-heal attempt."""
        cache_base = update_env["cache_base"]
        # Don't seed the marketplace dir.

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--marketplace-dir", str(update_env["marketplace_dir"])],
        )

        assert result.exit_code == 2, result.output
        assert "marketplace clone not found" in result.output
        # Cache untouched — no self-heal happened (we never even read marketplace_ver).
        assert not cache_base.exists()


# ---------------------------------------------------------------------------
# v0.3.40 D-9.40.2: "Next:" message must call out TWO restart cycles
# ---------------------------------------------------------------------------


class TestUpdateNextMessage:
    """Plan §17.3 task 9.121 / D-9.40.2.

    The v0.3.39 "Next:" message implied a single Claude Code restart was
    sufficient, but the actual upgrade flow requires TWO: (1) the first
    restart so ``/plugin install`` can register the plugin in
    ``installed_plugins.json``; (2) the second restart so SessionStart's
    ``ensure-env.sh`` fires against the now-registered plugin and
    rewrites the shim/helper. v0.3.40 makes this explicit.

    Acceptance criteria:
    (a) Substring ``"Open another fresh session"`` appears (= step 5).
    (b) ``"/exit"`` appears at least twice (= steps 1 and 4).
    """

    def test_next_message_calls_out_two_restarts_on_upgrade(
        self, update_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]
        # Marketplace at v0.3.40 (the new version we're upgrading to).
        _seed_marketplace(marketplace, "0.3.40")
        # Cache at v0.3.39 (the old version we're upgrading from) — triggers
        # the actual upgrade path (cache_ver != marketplace_ver) which is
        # the only branch that emits the "Next:" message.
        old_cache = cache_base / "0.3.39"
        old_cache.mkdir(parents=True)
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.39")
        # Stub the editable-install uninstall — there's no real venv in
        # tmp_path. The function is best-effort but we don't want the
        # subprocess.run call to fire.
        monkeypatch.setattr(cli_module, "_uninstall_stale_editable_paperwiki", lambda: None)

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--marketplace-dir", str(update_env["marketplace_dir"])],
        )

        assert result.exit_code == 0, result.output
        # Sanity: the upgrade headline appears (this is the only branch
        # that emits "Next:").
        assert "0.3.39 → 0.3.40" in result.output
        # D-9.40.2 acceptance (a): step 5 substring present.
        assert "Open another fresh session" in result.output, (
            f"missing 5th step in output:\n{result.output}"
        )
        # D-9.40.2 acceptance (b): /exit appears for both step 1 and step 4.
        assert result.output.count("/exit") >= 2, (
            f"expected at least 2 occurrences of /exit, got "
            f"{result.output.count('/exit')}:\n{result.output}"
        )

    def test_bak_lifecycle_note_appears_before_next_block(
        self, update_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """v0.3.43 D-9.43.2 update of v0.3.41 D-9.41.1.

        v0.3.41's NOTE warned that ``.bak`` is cleared by
        ``/plugin install``. v0.3.43 D-9.43.2 fixes the underlying
        problem by relocating ``.bak`` outside the plugin cache
        (to ``~/.local/share/paperwiki/bak/``); the NOTE now reads
        the *positive* form ("survive /plugin install").

        Acceptance criteria:
        (a) The NOTE substring contains "/plugin install" (so users
            can search/grep for it).
        (b) The NOTE mentions "survive" — the rollback contract.
        (c) The NOTE appears BEFORE the "Next:" block (so users see
            the rollback location before the restart instructions).
        """
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]
        _seed_marketplace(marketplace, "0.3.41")
        old_cache = cache_base / "0.3.40"
        old_cache.mkdir(parents=True)
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.40")
        monkeypatch.setattr(cli_module, "_uninstall_stale_editable_paperwiki", lambda: None)

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--marketplace-dir", str(update_env["marketplace_dir"])],
        )

        assert result.exit_code == 0, result.output
        # (a) NOTE substring contains "/plugin install".
        assert "/plugin install" in result.output
        # (b) The NOTE specifically mentions "survive" — the rollback contract.
        assert "survive" in result.output, (
            f"NOTE must mention 'survive /plugin install':\n{result.output}"
        )
        # (c) The NOTE appears BEFORE the "Next:" block.
        note_pos = result.output.find("Note:")
        next_pos = result.output.find("\nNext:")
        assert note_pos != -1, f"missing 'Note:' line:\n{result.output}"
        assert next_pos != -1, f"missing 'Next:' block:\n{result.output}"
        assert note_pos < next_pos, (
            f"Note: must appear before Next: block; "
            f"note_pos={note_pos}, next_pos={next_pos}\n{result.output}"
        )


# ---------------------------------------------------------------------------
# v0.3.40 D-9.40.4: marketplace git pull is best-effort
# ---------------------------------------------------------------------------


class TestGitPullBestEffort:
    """Plan §17.3 task 9.118 / D-9.40.4.

    The v0.3.39 ``_git_pull`` aborted ``paperwiki update`` whenever
    fetch/pull returned non-zero. v0.3.40 makes the pull best-effort
    so first-install / offline / corrupt-clone scenarios fall through
    to use the on-disk marketplace clone instead of failing the whole
    update. Failures land in WARN-level logs; the function still
    returns normally (no typer.Exit).

    The four cases below match plan §17.3 task 9.118 acceptance:
    (a) success → no warning
    (b) non-zero returncode → WARN, function returns
    (c) git binary missing (FileNotFoundError) → WARN, returns
    (d) timeout (TimeoutExpired) → WARN, returns
    """

    def test_pull_success_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        marketplace = tmp_path / "marketplace"
        marketplace.mkdir()

        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        # Should not raise.
        cli_module._git_pull(marketplace)
        # Both fetch and pull invoked.
        assert any("fetch" in c for c in calls)
        assert any("pull" in c for c in calls)

    def test_pull_failure_returns_normally(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Non-zero exit → WARN log, no exception."""
        marketplace = tmp_path / "marketplace"
        marketplace.mkdir()

        def failing_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: not a git repo")

        monkeypatch.setattr(subprocess, "run", failing_run)
        # Should NOT raise.
        cli_module._git_pull(marketplace)

    def test_pull_git_binary_missing_returns_normally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``FileNotFoundError`` (no git installed) → no exception raised."""
        marketplace = tmp_path / "marketplace"
        marketplace.mkdir()

        def raise_fnf(*_args: Any, **_kwargs: Any) -> None:
            raise FileNotFoundError("git not installed")

        monkeypatch.setattr(subprocess, "run", raise_fnf)
        cli_module._git_pull(marketplace)

    def test_pull_times_out_returns_normally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``TimeoutExpired`` → caught and logged; function returns."""
        marketplace = tmp_path / "marketplace"
        marketplace.mkdir()

        def raise_timeout(*_args: Any, **_kwargs: Any) -> None:
            raise subprocess.TimeoutExpired(cmd="git", timeout=10)

        monkeypatch.setattr(subprocess, "run", raise_timeout)
        cli_module._git_pull(marketplace)

    def test_pull_passes_timeout_to_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D-9.40.4 contract: subprocess.run is called with ``timeout=10``."""
        marketplace = tmp_path / "marketplace"
        marketplace.mkdir()

        captured_kwargs: list[dict[str, Any]] = []

        def capturing_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            captured_kwargs.append(kwargs)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", capturing_run)
        cli_module._git_pull(marketplace)
        # Both fetch + pull get the timeout kwarg.
        assert all(kw.get("timeout") == 10 for kw in captured_kwargs), captured_kwargs


class TestSelfHealOfflineFlow:
    """End-to-end: empty cache + git failures → self-heal still completes.

    Built without the ``update_env`` fixture because that fixture stubs
    ``_git_pull`` with a no-op (which would mask the offline behavior we
    want to exercise here). We stage HOME + monkeypatch ``subprocess.run``
    directly so the real (now best-effort per D-9.40.4) ``_git_pull`` runs.
    """

    def test_self_heal_completes_when_subprocess_run_returns_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """v0.3.40 R3: offline first-install path completes without abort."""
        home = tmp_path / "fake-home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)

        cache_base = home / ".claude" / "plugins" / "cache" / "paper-wiki" / "paper-wiki"
        marketplace = home / ".claude" / "plugins" / "marketplaces" / "paper-wiki"
        monkeypatch.setattr(cli_module, "_CACHE_BASE", cache_base)
        monkeypatch.setattr(cli_module, "_DEFAULT_MARKETPLACE_DIR", marketplace)
        monkeypatch.setattr(
            cli_module,
            "_INSTALLED_PLUGINS_JSON",
            home / ".claude" / "plugins" / "installed_plugins.json",
        )
        monkeypatch.setattr(cli_module, "_SETTINGS_JSON", home / ".claude" / "settings.json")
        monkeypatch.setattr(
            cli_module,
            "_SETTINGS_LOCAL_JSON",
            home / ".claude" / "settings.local.json",
        )

        _seed_marketplace(marketplace, "0.3.40")

        # Mock subprocess.run to simulate network failure on every call
        # (covers both fetch and pull commands inside _git_pull).
        def failing_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 1, "", "network unreachable")

        monkeypatch.setattr(subprocess, "run", failing_run)

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--marketplace-dir", str(marketplace)],
        )

        # Self-heal completed despite git failure (D-9.40.4 best-effort pull).
        assert result.exit_code == 0, result.output
        assert "bootstrapped from marketplace" in result.output
        assert (cache_base / "0.3.40").is_dir()


# ---------------------------------------------------------------------------
# v0.3.42 9.141 / D-9.42.2 — first-run rc-block UX message
#
# When ensure-env.sh writes the auto-source block to ``~/.zshrc`` (or
# similar) for the first time, it drops a ``$HELPER_DIR/.rc-just-added``
# stamp containing the rc-file path. The next ``paperwiki update``
# invocation reads the stamp, surfaces a one-line note to the user
# (so they know an rc-edit happened), and deletes the stamp
# (consume-once semantics). Subsequent updates without the stamp are
# silent on this front.
# ---------------------------------------------------------------------------


class TestRcFirstRunStamp:
    """Tests for ``paperwiki update`` reading + consuming the .rc-just-added stamp."""

    def _seed_stamp(self, home: Path, rc_path: str) -> Path:
        helper_dir = home / ".local" / "lib" / "paperwiki"
        helper_dir.mkdir(parents=True)
        stamp = helper_dir / ".rc-just-added"
        stamp.write_text(rc_path + "\n", encoding="utf-8")
        return stamp

    def test_stamp_present_surfaces_message_and_deletes_stamp(
        self, update_env: dict[str, Path]
    ) -> None:
        """First-run: rc-edit note appears + stamp is consumed.

        v0.3.43 D-9.43.4: the rc-just-added note must appear AFTER the
        plan/result text, not before. v0.3.42 ran the consume call at
        the top of update() so the note showed up first; this assertion
        pins the corrected ordering.
        """
        home = update_env["home"]
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]

        # Simulate "we're already at v0.3.41" so update is a no-op upgrade.
        # The stamp path runs regardless of upgrade outcome.
        _seed_marketplace(marketplace, "0.3.41")
        (cache_base / "0.3.41").mkdir(parents=True)
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.41")

        stamp = self._seed_stamp(home, str(home / ".zshrc"))

        runner = CliRunner()
        result = runner.invoke(app, ["update", "--marketplace-dir", str(marketplace)])
        assert result.exit_code == 0, result.output
        assert "Added auto-source line to" in result.output, (
            f"first-run rc-edit message must appear in update output:\n{result.output}"
        )
        assert ".zshrc" in result.output
        # v0.3.43 D-9.43.4: the rc-edit note must come AFTER the
        # primary result line ("already at vX" in this no-op case).
        result_pos = result.output.find("already at")
        rc_pos = result.output.find("Added auto-source line to")
        assert result_pos != -1
        assert rc_pos != -1
        assert result_pos < rc_pos, (
            f"rc-edit message must appear AFTER the result line; "
            f"result_pos={result_pos}, rc_pos={rc_pos}\n{result.output}"
        )
        # Stamp must be consumed (deleted) so subsequent updates are silent.
        assert not stamp.exists(), "the .rc-just-added stamp must be deleted after surfacing once"

    def test_stamp_absent_no_message(self, update_env: dict[str, Path]) -> None:
        """Subsequent update (no stamp) does NOT surface the rc message."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]

        _seed_marketplace(marketplace, "0.3.41")
        (cache_base / "0.3.41").mkdir(parents=True)
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.41")

        runner = CliRunner()
        result = runner.invoke(app, ["update", "--marketplace-dir", str(marketplace)])
        assert result.exit_code == 0, result.output
        assert "Added auto-source line to" not in result.output

    def test_stamp_message_appears_after_check_plan(self, update_env: dict[str, Path]) -> None:
        """v0.3.43 D-9.43.4: ``--check`` mode prints plan first, rc-edit note last.

        v0.3.42 D-9.42.5 added ``--check``. v0.3.42 9.141 also dropped
        the ``.rc-just-added`` stamp consumption at the top of
        ``update()``, which printed the rc-edit note BEFORE the plan
        when both events fired in the same run. v0.3.43 D-9.43.4 moves
        the consumption to the end of each branch — the user sees the
        plan first, side-note last.
        """
        home = update_env["home"]
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]

        # Set up a drift scenario so ``--check`` prints a meaningful plan.
        _seed_marketplace(marketplace, "0.3.43")
        (cache_base / "0.3.42").mkdir(parents=True)
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.42")

        # Drop a stamp so the first-run note fires too.
        self._seed_stamp(home, str(home / ".zshrc"))

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--check", "--marketplace-dir", str(marketplace)],
        )
        assert result.exit_code == 0, result.output

        # Both messages present.
        assert "plan:" in result.output
        assert "Added auto-source line to" in result.output

        # Plan first, rc-edit note last.
        plan_pos = result.output.find("plan:")
        rc_pos = result.output.find("Added auto-source line to")
        assert plan_pos < rc_pos, (
            f"plan must appear before rc-edit note in --check mode; "
            f"plan_pos={plan_pos}, rc_pos={rc_pos}\n{result.output}"
        )


# ---------------------------------------------------------------------------
# v0.3.42 9.142 / D-9.42.5 — `paperwiki update --check` dry-run flag
# ---------------------------------------------------------------------------


class TestUpdateCheckMode:
    """``--check`` previews planned actions without applying them."""

    def test_check_at_latest_reports_no_op(self, update_env: dict[str, Path]) -> None:
        """Cache + marketplace at same version → "already at" + no mutations."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]

        _seed_marketplace(marketplace, "0.3.42")
        (cache_base / "0.3.42").mkdir(parents=True)
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.42")

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--check", "--marketplace-dir", str(marketplace)],
        )
        assert result.exit_code == 0, result.output
        assert "0.3.42" in result.output
        # Cache dir untouched; no .bak created.
        assert (cache_base / "0.3.42").is_dir()
        assert not list(cache_base.glob("*.bak.*"))

    def test_check_drift_detected_previews_rename_without_applying(
        self, update_env: dict[str, Path]
    ) -> None:
        """Cache vX, marketplace vY → "would upgrade" with no actual rename."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]

        _seed_marketplace(marketplace, "0.3.42")
        (cache_base / "0.3.41").mkdir(parents=True)
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.41")

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--check", "--marketplace-dir", str(marketplace)],
        )
        assert result.exit_code == 0, result.output
        out = result.output
        # The dry-run output mentions the planned upgrade.
        assert "would" in out.lower() or "plan" in out.lower(), (
            f"--check should describe planned actions:\n{out}"
        )
        assert "0.3.41" in out
        assert "0.3.42" in out
        # No-mutation invariants: original cache dir still present, no .bak.
        assert (cache_base / "0.3.41").is_dir(), "--check must not rename the cache dir"
        assert not list(cache_base.glob("*.bak.*"))
        # installed_plugins.json untouched.
        installed = json.loads(update_env["installed_plugins"].read_text(encoding="utf-8"))
        assert "paper-wiki@paper-wiki" in installed.get("plugins", {}), (
            "--check must not drop the installed_plugins entry"
        )

    def test_check_cache_empty_previews_self_heal(self, update_env: dict[str, Path]) -> None:
        """Empty cache + valid marketplace → preview self-heal without copy."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]

        _seed_marketplace(marketplace, "0.3.42")
        cache_base.mkdir(parents=True)  # empty cache base

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--check", "--marketplace-dir", str(marketplace)],
        )
        assert result.exit_code == 0, result.output
        # No version subdir created.
        assert not list(cache_base.iterdir()), "--check must not bootstrap the cache"


# ---------------------------------------------------------------------------
# v0.3.42 9.143 / D-9.42.5 — mid-upgrade "between steps" detection
# ---------------------------------------------------------------------------


class TestMidUpgradeStateDetection:
    """``installed_plugins.json`` records vX, but cache has only vX.bak.<ts>.

    This is the half-installed state users reach when they run
    ``paperwiki update`` but forget to follow the TWO-restart guidance.
    Both apply mode and ``--check`` mode surface a "you appear to be
    mid-upgrade" hint pointing at the right next step.
    """

    def test_apply_mode_surfaces_between_steps_hint(self, update_env: dict[str, Path]) -> None:
        """Apply mode prints the hint when cache contains only the bak dir."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]

        _seed_marketplace(marketplace, "0.3.42")
        # Cache shape: only ``0.3.41.bak.<ts>`` — no plain ``0.3.41``.
        cache_base.mkdir(parents=True)
        (cache_base / "0.3.41.bak.20260430T000000Z").mkdir()
        # installed_plugins.json still records 0.3.41 (the half-state).
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.41")

        runner = CliRunner()
        result = runner.invoke(app, ["update", "--marketplace-dir", str(marketplace)])
        assert result.exit_code == 0, result.output
        assert "mid-upgrade" in result.output, (
            f"between-steps hint missing in output:\n{result.output}"
        )
        assert "/plugin install paper-wiki@paper-wiki" in result.output

    def test_check_mode_surfaces_between_steps_hint_too(self, update_env: dict[str, Path]) -> None:
        """``--check`` reports the same hint without applying anything."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]

        _seed_marketplace(marketplace, "0.3.42")
        cache_base.mkdir(parents=True)
        (cache_base / "0.3.41.bak.20260430T000000Z").mkdir()
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.41")

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["update", "--check", "--marketplace-dir", str(marketplace)],
        )
        assert result.exit_code == 0, result.output
        assert "mid-upgrade" in result.output
        assert "nothing applied" in result.output

    def test_normal_state_does_not_emit_hint(self, update_env: dict[str, Path]) -> None:
        """Healthy state (cache vX present + installed_plugins records vX) → no hint."""
        marketplace = update_env["marketplace_dir"]
        cache_base = update_env["cache_base"]

        _seed_marketplace(marketplace, "0.3.42")
        (cache_base / "0.3.42").mkdir(parents=True)
        _seed_installed_plugins_json(update_env["installed_plugins"], "0.3.42")

        runner = CliRunner()
        result = runner.invoke(app, ["update", "--marketplace-dir", str(marketplace)])
        assert result.exit_code == 0, result.output
        assert "mid-upgrade" not in result.output
