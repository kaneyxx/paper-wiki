"""Unit tests for paperwiki.runners.gc_bak (Task 9.33, v0.3.29).

Mirrors v0.3.28's `test_gc_digest_archive.py` design:

- Filename pattern guard (only `<ver>.bak.<YYYYMMDDTHHMMSSZ>` eligible).
- ``--keep-recent N`` mode: sort .bak DESC, keep first N, remove rest.
- ``--max-age-days N`` mode: mtime-based threshold.
- Combined modes (intersection — remove only if BOTH say "remove").
- ``--dry-run`` reports without modifying disk.
- Idempotent.
- Missing cache root is a clean no-op.
- ``PAPERWIKI_BAK_KEEP`` env var honored as default for ``--keep-recent``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from paperwiki.runners.gc_bak import (
    BAK_FILENAME_RE,
    DEFAULT_BAK_KEEP,
    gc_bak,
)

if TYPE_CHECKING:
    import pytest


def _seed_bak_dir(
    cache_root: Path,
    name: str,
    *,
    age_days: int = 0,
    files: dict[str, str] | None = None,
    now: datetime | None = None,
) -> Path:
    """Synthesise a fake `.bak.<ts>` directory under cache_root."""
    cache_root.mkdir(parents=True, exist_ok=True)
    bak = cache_root / name
    bak.mkdir()
    for relpath, content in (files or {"sentinel.txt": "sentinel"}).items():
        target = bak / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if now is None:
        now = datetime.now(tz=UTC)
    target_ts = (now - timedelta(days=age_days)).timestamp()
    os.utime(bak, (target_ts, target_ts))
    return bak


class TestFilenameGuard:
    def test_eligible_pattern_matches(self) -> None:
        assert BAK_FILENAME_RE.match("0.3.28.bak.20260428T150731Z")
        assert BAK_FILENAME_RE.match("0.3.29.bak.20240101T000000Z")
        assert BAK_FILENAME_RE.match("1.0.0.bak.20300101T000000Z")

    def test_user_directory_does_not_match(self) -> None:
        assert not BAK_FILENAME_RE.match("0.3.28")  # active cache
        assert not BAK_FILENAME_RE.match("notes")
        assert not BAK_FILENAME_RE.match("0.3.28.bak.invalid")
        assert not BAK_FILENAME_RE.match(".DS_Store")

    def test_user_dir_in_cache_root_skipped(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        _seed_bak_dir(cache, "0.3.28.bak.20240101T000000Z", age_days=400)
        (cache / "user-notes").mkdir()  # user-added dir, must be ignored
        (cache / "0.3.29").mkdir()  # active cache version

        report = gc_bak(cache, keep_recent=0, dry_run=True)
        # Only .bak dirs eligible; active version + user-notes preserved.
        assert "0.3.28.bak.20240101T000000Z" in report.removed
        assert "user-notes" in report.skipped_unrecognized
        assert "0.3.29" in report.skipped_unrecognized


class TestKeepRecent:
    def test_keep_recent_3_with_5_baks_removes_oldest_2(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        # Newer first (timestamp-sortable strings).
        names = [
            "0.3.28.bak.20260101T000000Z",  # newest (kept)
            "0.3.27.bak.20251201T000000Z",  # 2nd newest (kept)
            "0.3.26.bak.20251101T000000Z",  # 3rd newest (kept)
            "0.3.25.bak.20251001T000000Z",  # 4th (removed)
            "0.3.24.bak.20250901T000000Z",  # 5th (removed)
        ]
        for name in names:
            _seed_bak_dir(cache, name)

        report = gc_bak(cache, keep_recent=3, dry_run=False)
        assert sorted(report.kept) == [
            "0.3.26.bak.20251101T000000Z",
            "0.3.27.bak.20251201T000000Z",
            "0.3.28.bak.20260101T000000Z",
        ]
        assert sorted(report.removed) == [
            "0.3.24.bak.20250901T000000Z",
            "0.3.25.bak.20251001T000000Z",
        ]
        # Kept dirs still on disk; removed dirs gone.
        for kept in report.kept:
            assert (cache / kept).is_dir()
        for removed in report.removed:
            assert not (cache / removed).exists()

    def test_keep_recent_0_removes_everything(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        _seed_bak_dir(cache, "0.3.27.bak.20260101T000000Z")
        _seed_bak_dir(cache, "0.3.26.bak.20260201T000000Z")

        report = gc_bak(cache, keep_recent=0, dry_run=False)
        assert len(report.removed) == 2
        assert report.kept == []

    def test_keep_recent_higher_than_count_keeps_all(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        _seed_bak_dir(cache, "0.3.27.bak.20260101T000000Z")
        _seed_bak_dir(cache, "0.3.28.bak.20260201T000000Z")

        report = gc_bak(cache, keep_recent=10, dry_run=False)
        assert sorted(report.kept) == sorted(
            ["0.3.27.bak.20260101T000000Z", "0.3.28.bak.20260201T000000Z"]
        )
        assert report.removed == []


class TestMaxAgeDays:
    def test_old_baks_removed(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        _seed_bak_dir(cache, "0.3.27.bak.20260101T000000Z", age_days=400)
        _seed_bak_dir(cache, "0.3.28.bak.20260201T000000Z", age_days=10)

        report = gc_bak(cache, keep_recent=None, max_age_days=365, dry_run=False)
        assert report.removed == ["0.3.27.bak.20260101T000000Z"]
        assert report.kept == ["0.3.28.bak.20260201T000000Z"]


class TestCombinedModes:
    def test_keep_recent_and_max_age_intersection(self, tmp_path: Path) -> None:
        """Combining both modes: bak removed only if BOTH agree on removal.

        - keep-recent=2 says: keep newest 2, remove rest.
        - max-age-days=365 says: remove anything > 365 days old.
        Intersection: a bak is removed only if it falls outside the
        recent-N window AND is older than max-age. So a recent
        old bak (within keep-recent but stale) is preserved.
        """
        cache = tmp_path / "cache"
        # 5 baks; oldest first by name + age.
        _seed_bak_dir(
            cache, "0.3.24.bak.20240101T000000Z", age_days=500
        )  # outside keep + old → removed
        _seed_bak_dir(
            cache, "0.3.25.bak.20240601T000000Z", age_days=400
        )  # outside keep + old → removed
        _seed_bak_dir(
            cache, "0.3.26.bak.20241001T000000Z", age_days=200
        )  # outside keep + young → kept
        _seed_bak_dir(cache, "0.3.27.bak.20250101T000000Z", age_days=10)  # within keep → kept
        _seed_bak_dir(cache, "0.3.28.bak.20250601T000000Z", age_days=5)  # within keep → kept

        report = gc_bak(cache, keep_recent=2, max_age_days=365, dry_run=False)
        assert sorted(report.removed) == [
            "0.3.24.bak.20240101T000000Z",
            "0.3.25.bak.20240601T000000Z",
        ]
        assert sorted(report.kept) == [
            "0.3.26.bak.20241001T000000Z",
            "0.3.27.bak.20250101T000000Z",
            "0.3.28.bak.20250601T000000Z",
        ]


class TestDryRun:
    def test_dry_run_doesnt_delete(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        bak = _seed_bak_dir(cache, "0.3.27.bak.20260101T000000Z")

        report = gc_bak(cache, keep_recent=0, dry_run=True)
        assert report.dry_run is True
        assert report.removed == ["0.3.27.bak.20260101T000000Z"]
        assert bak.is_dir()  # disk untouched


class TestIdempotent:
    def test_second_run_is_noop(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        _seed_bak_dir(cache, "0.3.27.bak.20260101T000000Z")
        _seed_bak_dir(cache, "0.3.28.bak.20260201T000000Z")

        first = gc_bak(cache, keep_recent=1, dry_run=False)
        assert len(first.removed) == 1

        second = gc_bak(cache, keep_recent=1, dry_run=False)
        assert second.removed == []
        assert len(second.kept) == 1


class TestMissingCacheRoot:
    def test_missing_cache_returns_empty(self, tmp_path: Path) -> None:
        cache = tmp_path / "does-not-exist"
        report = gc_bak(cache, keep_recent=3, dry_run=False)
        assert report.removed == []
        assert report.kept == []
        assert report.errors == []


class TestDefaults:
    def test_default_bak_keep_is_3(self) -> None:
        """D-9.33.1: default = 3 (current + 2 bak)."""
        assert DEFAULT_BAK_KEEP == 3


class TestCli:
    def test_help_lists_all_flags(self) -> None:
        from typer.testing import CliRunner

        from paperwiki.runners.gc_bak import app

        result = CliRunner().invoke(app, ["--help"])
        assert result.exit_code == 0
        for flag in ("--keep-recent", "--max-age-days", "--dry-run"):
            assert flag in result.output, f"missing {flag} in --help"

    def test_explicit_cache_root_runs_cleanly(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from paperwiki.runners.gc_bak import app

        cache = tmp_path / "cache"
        _seed_bak_dir(cache, "0.3.27.bak.20260101T000000Z")
        _seed_bak_dir(cache, "0.3.28.bak.20260201T000000Z")

        result = CliRunner().invoke(
            app,
            ["--cache-root", str(cache), "--keep-recent", "1"],
        )
        assert result.exit_code == 0, result.output
        assert (cache / "0.3.28.bak.20260201T000000Z").is_dir()
        assert not (cache / "0.3.27.bak.20260101T000000Z").exists()

    def test_paperwiki_bak_keep_env_var_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D-9.33.1: PAPERWIKI_BAK_KEEP env var controls default --keep-recent."""
        from typer.testing import CliRunner

        from paperwiki.runners.gc_bak import app

        cache = tmp_path / "cache"
        for i in range(5):
            _seed_bak_dir(cache, f"0.3.{20 + i}.bak.2026010{i + 1}T000000Z")

        monkeypatch.setenv("PAPERWIKI_BAK_KEEP", "2")
        result = CliRunner().invoke(app, ["--cache-root", str(cache)])
        assert result.exit_code == 0, result.output
        # Newest 2 kept.
        assert (cache / "0.3.24.bak.20260105T000000Z").is_dir()
        assert (cache / "0.3.23.bak.20260104T000000Z").is_dir()
        # Oldest 3 removed.
        assert not (cache / "0.3.20.bak.20260101T000000Z").exists()
        assert not (cache / "0.3.21.bak.20260102T000000Z").exists()
        assert not (cache / "0.3.22.bak.20260103T000000Z").exists()

    def test_paperwiki_bak_keep_zero_skips_cleanup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PAPERWIKI_BAK_KEEP=0 + no other flag = preserve everything (escape hatch)."""
        from typer.testing import CliRunner

        from paperwiki.runners.gc_bak import app

        cache = tmp_path / "cache"
        _seed_bak_dir(cache, "0.3.27.bak.20260101T000000Z")
        _seed_bak_dir(cache, "0.3.28.bak.20260201T000000Z")

        # PAPERWIKI_BAK_KEEP=0 with no --keep-recent override should skip.
        # The runner treats 0 (when explicitly set) as "don't auto-prune".
        monkeypatch.setenv("PAPERWIKI_BAK_KEEP", "0")
        result = CliRunner().invoke(app, ["--cache-root", str(cache)])
        assert result.exit_code == 0, result.output
        # Both still present (no cleanup happened).
        assert (cache / "0.3.27.bak.20260101T000000Z").is_dir()
        assert (cache / "0.3.28.bak.20260201T000000Z").is_dir()
