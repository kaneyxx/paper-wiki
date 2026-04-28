"""Unit tests for paperwiki.config.recipe_migrations.

AC-9.21.7 (third bullet): test_0_3_17_target_drops_foundation_model_from_biomedical.
"""

from __future__ import annotations


class TestRecipeMigrations:
    def test_0_3_17_entry_exists(self) -> None:
        from paperwiki.config.recipe_migrations import RECIPE_MIGRATIONS

        assert "0.3.17" in RECIPE_MIGRATIONS, "RECIPE_MIGRATIONS must have a '0.3.17' entry"

    def test_0_3_17_target_drops_foundation_model_from_biomedical(self) -> None:
        from paperwiki.config.recipe_migrations import RECIPE_MIGRATIONS

        migrations = RECIPE_MIGRATIONS["0.3.17"]
        bio_migrations = [m for m in migrations if m.topic_name == "biomedical-pathology"]
        assert bio_migrations, (
            "0.3.17 migration must contain a TopicMigration for 'biomedical-pathology'"
        )
        bio = bio_migrations[0]
        remove_lower = [kw.lower().strip() for kw in bio.remove]
        assert "foundation model" in remove_lower, (
            "0.3.17 biomedical-pathology migration must remove 'foundation model'"
        )

    def test_stale_markers_has_0_3_17_biomedical_entry(self) -> None:
        from paperwiki.config.recipe_migrations import STALE_MARKERS

        assert "0.3.17" in STALE_MARKERS, "STALE_MARKERS must have a '0.3.17' key"
        bio_markers = STALE_MARKERS["0.3.17"].get("biomedical-pathology", set())
        assert "foundation model" in bio_markers, (
            "STALE_MARKERS 0.3.17 must flag 'foundation model' as a stale marker "
            "for biomedical-pathology"
        )

    def test_topic_migration_is_frozen(self) -> None:
        from paperwiki.config.recipe_migrations import TopicMigration

        m = TopicMigration(topic_name="test", remove=["a"], add=["b"])
        assert m.topic_name == "test"
        assert "a" in m.remove
        assert "b" in m.add
