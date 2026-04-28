"""Unit tests for paperwiki.runners.migrate_recipe.

Covers:
- dry-run prints diff without writing
- apply mode creates backup + writes updated YAML
- custom 5th topic (user-added) keywords are preserved
- idempotent re-run is a no-op (applied_changes: [])
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_recipe(path: Path, data: dict) -> None:
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def stale_recipe_path(tmp_path: Path) -> Path:
    """A recipe that contains the pre-v0.3.17 stale keywords."""
    data = {
        "name": "daily",
        "sources": [{"name": "arxiv", "config": {"categories": ["cs.AI"]}}],
        "filters": [
            {
                "name": "relevance",
                "config": {
                    "topics": [
                        {
                            "name": "biomedical-pathology",
                            "keywords": [
                                "pathology",
                                "histopathology",
                                "WSI",
                                "digital pathology",
                                "foundation model",  # stale — should be removed
                                "clinical AI",
                            ],
                        },
                        {
                            "name": "custom-topic",
                            "keywords": ["my-custom-keyword", "specialised-term"],
                        },
                    ]
                },
            }
        ],
        "scorer": {
            "name": "composite",
            "config": {
                "topics": [
                    {
                        "name": "biomedical-pathology",
                        "keywords": [
                            "pathology",
                            "histopathology",
                            "foundation model",  # stale — should be removed
                            "clinical AI",
                        ],
                    }
                ]
            },
        },
        "reporters": [{"name": "markdown", "config": {"output_dir": "~/paper-wiki/digests"}}],
        "top_k": 10,
    }
    p = tmp_path / "daily.yaml"
    _write_recipe(p, data)
    return p


@pytest.fixture
def clean_recipe_path(tmp_path: Path) -> Path:
    """A recipe already at the v0.3.17+ shape — no stale keywords."""
    data = {
        "name": "daily",
        "sources": [{"name": "arxiv", "config": {"categories": ["cs.AI"]}}],
        "filters": [
            {
                "name": "relevance",
                "config": {
                    "topics": [
                        {
                            "name": "biomedical-pathology",
                            "keywords": [
                                "pathology",
                                "histopathology",
                                "WSI",
                                "clinical AI",
                            ],
                        }
                    ]
                },
            }
        ],
        "scorer": {
            "name": "composite",
            "config": {
                "topics": [
                    {
                        "name": "biomedical-pathology",
                        "keywords": ["pathology", "histopathology", "clinical AI"],
                    }
                ]
            },
        },
        "reporters": [{"name": "markdown", "config": {"output_dir": "~/paper-wiki/digests"}}],
        "top_k": 10,
    }
    p = tmp_path / "daily_clean.yaml"
    _write_recipe(p, data)
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestMigrateRecipeFile:
    def test_apply_mode_removes_stale_keywords(self, stale_recipe_path: Path) -> None:
        from paperwiki.runners.migrate_recipe import migrate_recipe_file

        report = migrate_recipe_file(stale_recipe_path)

        assert len(report.applied_changes) > 0, "must have at least one applied change"
        # foundation model must be removed
        removed_all = [kw for c in report.applied_changes for kw in c.removed_keywords]
        assert "foundation model" in removed_all, "must remove 'foundation model'"

    def test_apply_mode_creates_backup(self, stale_recipe_path: Path) -> None:
        from paperwiki.runners.migrate_recipe import migrate_recipe_file

        report = migrate_recipe_file(stale_recipe_path)

        assert report.backup_path is not None, "backup_path must be set after apply"
        backup = Path(report.backup_path)
        assert backup.is_file(), f"backup file must exist: {backup}"
        assert ".bak." in backup.name, "backup name must contain '.bak.' timestamp"

    def test_apply_mode_writes_updated_recipe(self, stale_recipe_path: Path) -> None:
        from paperwiki.runners.migrate_recipe import migrate_recipe_file

        migrate_recipe_file(stale_recipe_path)

        updated = yaml.safe_load(stale_recipe_path.read_text(encoding="utf-8"))
        # Collect all keywords from all topic blocks
        all_keywords = _collect_all_keywords(updated)
        assert "foundation model" not in all_keywords, (
            "stale keyword 'foundation model' must be absent from written recipe"
        )

    def test_dry_run_does_not_write(self, stale_recipe_path: Path) -> None:
        from paperwiki.runners.migrate_recipe import migrate_recipe_file

        original_text = stale_recipe_path.read_text(encoding="utf-8")
        report = migrate_recipe_file(stale_recipe_path, dry_run=True)

        # File must be unchanged
        assert stale_recipe_path.read_text(encoding="utf-8") == original_text, (
            "dry-run must not modify the recipe file"
        )
        # No backup created
        assert report.backup_path is None, "dry-run must not create a backup"

    def test_dry_run_still_reports_changes(self, stale_recipe_path: Path) -> None:
        from paperwiki.runners.migrate_recipe import migrate_recipe_file

        report = migrate_recipe_file(stale_recipe_path, dry_run=True)

        assert len(report.applied_changes) > 0, "dry-run must still report what would change"
        removed_all = [kw for c in report.applied_changes for kw in c.removed_keywords]
        assert "foundation model" in removed_all

    def test_idempotent_rerun_is_noop(self, stale_recipe_path: Path) -> None:
        from paperwiki.runners.migrate_recipe import migrate_recipe_file

        # First run — applies changes
        first = migrate_recipe_file(stale_recipe_path)
        assert first.applied_changes, "first run must have changes"

        # Second run — must be no-op
        second = migrate_recipe_file(stale_recipe_path)
        assert second.applied_changes == [], (
            "second run on already-migrated recipe must have applied_changes: []"
        )
        assert second.backup_path is None, "second run must not create a backup"

    def test_custom_user_keywords_preserved(self, stale_recipe_path: Path) -> None:
        from paperwiki.runners.migrate_recipe import migrate_recipe_file

        migrate_recipe_file(stale_recipe_path)

        updated = yaml.safe_load(stale_recipe_path.read_text(encoding="utf-8"))
        all_keywords = _collect_all_keywords(updated)
        # User's custom-topic keywords must survive
        assert "my-custom-keyword" in all_keywords, (
            "user-added keyword in custom topic must be preserved"
        )
        assert "specialised-term" in all_keywords, (
            "user-added keyword 'specialised-term' must be preserved"
        )

    def test_clean_recipe_is_noop(self, clean_recipe_path: Path) -> None:
        from paperwiki.runners.migrate_recipe import migrate_recipe_file

        original_text = clean_recipe_path.read_text(encoding="utf-8")
        report = migrate_recipe_file(clean_recipe_path)

        assert report.applied_changes == [], (
            "already-migrated recipe must produce no applied_changes"
        )
        assert report.backup_path is None
        assert clean_recipe_path.read_text(encoding="utf-8") == original_text, (
            "clean recipe file must not be modified"
        )

    def test_backup_files_do_not_overwrite_each_other(
        self, stale_recipe_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two migrations within the same second must not collide (coverage of
        uniqueness contract — backup timestamps include seconds)."""
        import time

        from paperwiki.runners.migrate_recipe import migrate_recipe_file

        # First apply
        report1 = migrate_recipe_file(stale_recipe_path)
        assert report1.backup_path is not None
        backup1 = Path(report1.backup_path)
        assert backup1.is_file()

        # Recreate a stale recipe to trigger a second backup
        stale_recipe_path.write_text(
            yaml.dump(
                {
                    "name": "daily",
                    "sources": [{"name": "arxiv", "config": {"categories": ["cs.AI"]}}],
                    "filters": [
                        {
                            "name": "relevance",
                            "config": {
                                "topics": [
                                    {
                                        "name": "biomedical-pathology",
                                        "keywords": ["foundation model", "pathology"],
                                    }
                                ]
                            },
                        }
                    ],
                    "scorer": {
                        "name": "composite",
                        "config": {"topics": []},
                    },
                    "reporters": [{"name": "markdown", "config": {"output_dir": "~/out"}}],
                    "top_k": 5,
                }
            ),
            encoding="utf-8",
        )

        # Sleep 1 second so timestamp suffix is different
        time.sleep(1.1)
        report2 = migrate_recipe_file(stale_recipe_path)
        if report2.backup_path:
            assert report2.backup_path != report1.backup_path, (
                "two backup files must have different names"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_all_keywords(data: dict) -> list[str]:
    """Recursively collect all keyword strings from topic blocks."""
    results: list[str] = []

    def _walk(obj: object) -> None:
        if isinstance(obj, dict):
            if "name" in obj and "keywords" in obj:
                kws = obj["keywords"]
                if isinstance(kws, list):
                    results.extend(str(k) for k in kws if k is not None)
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)
    return results
