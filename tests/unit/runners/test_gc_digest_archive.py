"""Unit tests for paperwiki.runners.gc_digest_archive (Task 9.30, v0.3.28).

Covers:
- Filename pattern guard (only <YYYY-MM-DD>-paper-digest.md(.gz) eligible).
- Age-threshold gating (mtime-based; respects --max-age-days).
- Dry-run reports without mutating disk.
- Delete vs gzip modes.
- Idempotency.
- Vault auto-discovery from default recipe (D-9.30.1).
- Missing archive dir is a clean no-op.
"""

from __future__ import annotations

import gzip
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from paperwiki.runners.gc_digest_archive import (
    ARCHIVE_DIRNAME,
    DEFAULT_MAX_AGE_DAYS,
    discover_vault_from_recipe,
    gc_archive,
)

if TYPE_CHECKING:
    import pytest


def _seed_archive_file(
    archive_dir: Path,
    name: str,
    *,
    age_days: int,
    body: str = "# digest body\n",
    now: datetime | None = None,
) -> Path:
    """Create a file under ``archive_dir`` with mtime backdated by ``age_days``."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / name
    path.write_text(body, encoding="utf-8")
    if now is None:
        now = datetime.now(tz=UTC)
    target_ts = (now - timedelta(days=age_days)).timestamp()
    os.utime(path, (target_ts, target_ts))
    return path


class TestFilenamePatternGuard:
    def test_eligible_files_match_pattern(self, tmp_path: Path) -> None:
        archive = tmp_path / ARCHIVE_DIRNAME
        _seed_archive_file(archive, "2024-01-05-paper-digest.md", age_days=400)
        _seed_archive_file(archive, "2024-06-15-paper-digest.md.gz", age_days=200)

        report = gc_archive(tmp_path, max_age_days=365, dry_run=True)
        assert report.removed + report.kept == [
            "2024-01-05-paper-digest.md",
            "2024-06-15-paper-digest.md.gz",
        ]
        assert report.skipped_unrecognized == []

    def test_user_file_is_skipped(self, tmp_path: Path) -> None:
        """D-9.30.2: user-added files in .digest-archive must NOT be touched."""
        archive = tmp_path / ARCHIVE_DIRNAME
        _seed_archive_file(archive, "my-personal-notes.md", age_days=400)
        _seed_archive_file(archive, "2026-01-05-paper-digest.md", age_days=400)

        report = gc_archive(tmp_path, max_age_days=365, dry_run=True)
        assert "my-personal-notes.md" in report.skipped_unrecognized
        assert "2026-01-05-paper-digest.md" in report.removed

    def test_icloud_sync_stub_is_skipped(self, tmp_path: Path) -> None:
        """Sync conflict files (.icloud, .DS_Store) bypass the regex."""
        archive = tmp_path / ARCHIVE_DIRNAME
        _seed_archive_file(archive, "2024-01-05-paper-digest.md.icloud", age_days=999)
        _seed_archive_file(archive, ".DS_Store", age_days=999)
        report = gc_archive(tmp_path, max_age_days=365, dry_run=True)
        assert "2024-01-05-paper-digest.md.icloud" in report.skipped_unrecognized
        assert ".DS_Store" in report.skipped_unrecognized
        assert report.removed == []


class TestAgeThreshold:
    def test_recent_files_kept(self, tmp_path: Path) -> None:
        archive = tmp_path / ARCHIVE_DIRNAME
        _seed_archive_file(archive, "2026-04-28-paper-digest.md", age_days=10)

        report = gc_archive(tmp_path, max_age_days=365, dry_run=False)
        assert report.kept == ["2026-04-28-paper-digest.md"]
        assert report.removed == []
        assert (archive / "2026-04-28-paper-digest.md").is_file()

    def test_old_files_removed(self, tmp_path: Path) -> None:
        archive = tmp_path / ARCHIVE_DIRNAME
        _seed_archive_file(archive, "2024-01-05-paper-digest.md", age_days=500)

        report = gc_archive(tmp_path, max_age_days=365, dry_run=False)
        assert report.removed == ["2024-01-05-paper-digest.md"]
        assert not (archive / "2024-01-05-paper-digest.md").exists()

    def test_threshold_at_zero_removes_everything(self, tmp_path: Path) -> None:
        """--max-age-days 0 means everything older than zero days (i.e., all)."""
        archive = tmp_path / ARCHIVE_DIRNAME
        _seed_archive_file(archive, "2026-04-27-paper-digest.md", age_days=1)
        report = gc_archive(tmp_path, max_age_days=0, dry_run=False)
        assert report.removed == ["2026-04-27-paper-digest.md"]


class TestDryRun:
    def test_dry_run_lists_but_doesnt_delete(self, tmp_path: Path) -> None:
        archive = tmp_path / ARCHIVE_DIRNAME
        _seed_archive_file(archive, "2024-01-05-paper-digest.md", age_days=500)
        _seed_archive_file(archive, "2026-04-28-paper-digest.md", age_days=5)

        report = gc_archive(tmp_path, max_age_days=365, dry_run=True)
        assert report.dry_run is True
        assert report.removed == ["2024-01-05-paper-digest.md"]
        assert report.kept == ["2026-04-28-paper-digest.md"]
        # Disk untouched.
        assert (archive / "2024-01-05-paper-digest.md").is_file()
        assert (archive / "2026-04-28-paper-digest.md").is_file()


class TestGzipMode:
    def test_old_file_gzipped_when_use_gzip_true(self, tmp_path: Path) -> None:
        archive = tmp_path / ARCHIVE_DIRNAME
        body = "# old digest\n\nfar-back content\n"
        _seed_archive_file(archive, "2024-01-05-paper-digest.md", age_days=500, body=body)

        report = gc_archive(tmp_path, max_age_days=365, dry_run=False, use_gzip=True)
        assert report.gzipped == ["2024-01-05-paper-digest.md"]
        assert report.mode == "gzip"
        # Plaintext is gone, gz exists.
        assert not (archive / "2024-01-05-paper-digest.md").exists()
        gz_path = archive / "2024-01-05-paper-digest.md.gz"
        assert gz_path.is_file()
        # Reversible: gunzip restores the body.
        with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
            assert fh.read() == body

    def test_already_gzipped_file_kept_when_use_gzip_true(self, tmp_path: Path) -> None:
        """Don't double-gzip already-compressed files."""
        archive = tmp_path / ARCHIVE_DIRNAME
        _seed_archive_file(archive, "2024-01-05-paper-digest.md.gz", age_days=500)
        report = gc_archive(tmp_path, max_age_days=365, dry_run=False, use_gzip=True)
        assert "2024-01-05-paper-digest.md.gz" in report.kept
        assert (archive / "2024-01-05-paper-digest.md.gz").is_file()


class TestIdempotent:
    def test_second_run_is_noop(self, tmp_path: Path) -> None:
        archive = tmp_path / ARCHIVE_DIRNAME
        _seed_archive_file(archive, "2024-01-05-paper-digest.md", age_days=500)

        first = gc_archive(tmp_path, max_age_days=365, dry_run=False)
        assert first.removed == ["2024-01-05-paper-digest.md"]

        second = gc_archive(tmp_path, max_age_days=365, dry_run=False)
        assert second.removed == []
        assert second.kept == []


class TestMissingArchive:
    def test_no_archive_dir_returns_empty_report(self, tmp_path: Path) -> None:
        """AC-9.30.7: missing .digest-archive/ subdir is a no-op."""
        # No .digest-archive/ exists under tmp_path.
        report = gc_archive(tmp_path, max_age_days=365, dry_run=False)
        assert report.removed == []
        assert report.gzipped == []
        assert report.kept == []
        assert report.skipped_unrecognized == []
        assert report.errors == []


class TestDiscoverVaultFromRecipe:
    def test_discover_from_obsidian_vault_path(self, tmp_path: Path) -> None:
        """D-9.30.1: prefer obsidian reporter's vault_path."""
        recipe_path = tmp_path / "daily.yaml"
        recipe_path.write_text(
            f"reporters:\n  - {{name: obsidian, config: {{vault_path: {tmp_path / 'vault'}}}}}\n",
            encoding="utf-8",
        )
        result = discover_vault_from_recipe(recipe_path)
        assert result == tmp_path / "vault"

    def test_discover_falls_back_to_markdown_output_dir(self, tmp_path: Path) -> None:
        """When obsidian reporter is absent, derive vault from markdown
        reporter's output_dir ending in /.digest-archive."""
        recipe_path = tmp_path / "daily.yaml"
        archive_path = tmp_path / "myvault" / ".digest-archive"
        recipe_path.write_text(
            f"reporters:\n  - {{name: markdown, config: {{output_dir: {archive_path}}}}}\n",
            encoding="utf-8",
        )
        result = discover_vault_from_recipe(recipe_path)
        assert result == tmp_path / "myvault"

    def test_missing_recipe_returns_none(self, tmp_path: Path) -> None:
        result = discover_vault_from_recipe(tmp_path / "does-not-exist.yaml")
        assert result is None

    def test_malformed_recipe_returns_none(self, tmp_path: Path) -> None:
        recipe_path = tmp_path / "daily.yaml"
        recipe_path.write_text("not: [valid: yaml syntax", encoding="utf-8")
        result = discover_vault_from_recipe(recipe_path)
        assert result is None

    def test_recipe_without_vault_hint_returns_none(self, tmp_path: Path) -> None:
        recipe_path = tmp_path / "daily.yaml"
        recipe_path.write_text(
            "reporters:\n  - {name: jsonl, config: {output_dir: /tmp/out}}\n",
            encoding="utf-8",
        )
        result = discover_vault_from_recipe(recipe_path)
        assert result is None


class TestDefaults:
    def test_default_max_age_days_is_365(self) -> None:
        """D-9.30.3: default = 365 (1 year)."""
        assert DEFAULT_MAX_AGE_DAYS == 365


class TestCli:
    def test_help_lists_all_flags(self) -> None:
        from typer.testing import CliRunner

        from paperwiki.runners.gc_digest_archive import app

        # NO_COLOR/TERM/COLUMNS keep Rich from wrapping flag names across
        # lines on narrow CI terminals (the literal substring check would
        # miss "--max-age-days" if Rich split it as "--max-age-\ndays").
        result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"}).invoke(
            app, ["--help"]
        )
        assert result.exit_code == 0
        for flag in ("--vault", "--max-age-days", "--dry-run", "--gzip"):
            assert flag in result.output, f"missing {flag} in --help"

    def test_missing_vault_and_no_recipe_exits_2(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from typer.testing import CliRunner

        import paperwiki.runners.gc_digest_archive as mod
        from paperwiki.runners.gc_digest_archive import app

        monkeypatch.setattr(mod, "DEFAULT_RECIPE_PATH", tmp_path / "missing.yaml")
        # Force empty fallback chain — no recipe, no --vault.
        result = CliRunner().invoke(app, [])
        assert result.exit_code == 2

    def test_explicit_vault_runs_cleanly(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from paperwiki.runners.gc_digest_archive import app

        archive = tmp_path / ARCHIVE_DIRNAME
        _seed_archive_file(archive, "2024-01-05-paper-digest.md", age_days=500)
        _seed_archive_file(archive, "2026-04-28-paper-digest.md", age_days=5)

        result = CliRunner().invoke(
            app,
            ["--vault", str(tmp_path), "--max-age-days", "365"],
        )
        assert result.exit_code == 0, result.output
        # Old removed, new kept.
        assert not (archive / "2024-01-05-paper-digest.md").exists()
        assert (archive / "2026-04-28-paper-digest.md").is_file()
