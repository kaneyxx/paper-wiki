"""Unit tests for paperwiki.runners.migrate_sources.

The runner walks ``Wiki/sources/*.md`` and rewrites pre-v0.3.2 source
stubs into the current section-organized format, preserving any
user-authored content in ``## Notes``, ``## Key Takeaways``, and
``## Figures`` sections (when those sections already exist).

When the source-stub format changes again in the future, this runner
must be updated alongside ``MarkdownWikiBackend._default_source_body``
so users can upgrade their vault in-place with a single command.
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_OLD_FORMAT = """---
canonical_id: arxiv:2604.21360
title: Prototype-Based Test-Time Adaptation
status: draft
confidence: 0.7
tags:
- cs.CV
related_concepts:
- '[[vision-language]]'
last_synthesized: '2026-04-26'
---

# Prototype-Based Test-Time Adaptation

- **Authors**: Zhaohong Huang, Yuxin Zhang, Wenjing Liu
- **Source**: https://arxiv.org/abs/2604.21360v1

Test-time adaptation has emerged as a promising paradigm for vision-
language models to bridge the distribution gap between pre-training
and test data.
"""


def _seed(vault: Path, filename: str, content: str) -> Path:
    target = vault / "Wiki" / "sources" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# migrate_source (single-file)
# ---------------------------------------------------------------------------


class TestMigrateSource:
    def test_old_format_gains_section_organized_body(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_sources import migrate_source

        path = _seed(tmp_path, "arxiv_2604.21360.md", _OLD_FORMAT)
        changed = migrate_source(path)
        assert changed is True

        body = _read(path)
        for section in (
            "## Core Information",
            "## Abstract",
            "## Key Takeaways",
            "## Figures",
            "## Notes",
        ):
            assert section in body, f"missing section: {section!r}"

    def test_old_format_frontmatter_fills_in_missing_fields(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_sources import migrate_source

        path = _seed(tmp_path, "arxiv_2604.21360.md", _OLD_FORMAT)
        migrate_source(path)

        text = _read(path)
        # New required fields show up.
        assert "published_at:" in text
        assert "landing_url:" in text
        assert "score_breakdown:" in text
        assert "domain:" in text
        # Stable fields preserved.
        assert "canonical_id: arxiv:2604.21360" in text
        assert "Prototype-Based Test-Time Adaptation" in text

    def test_old_format_authors_lift_into_core_information(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_sources import migrate_source

        path = _seed(tmp_path, "arxiv_2604.21360.md", _OLD_FORMAT)
        migrate_source(path)

        body = _read(path)
        assert "Zhaohong Huang" in body
        assert "Yuxin Zhang" in body

    def test_old_format_abstract_lifts_into_abstract_section(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_sources import migrate_source

        path = _seed(tmp_path, "arxiv_2604.21360.md", _OLD_FORMAT)
        migrate_source(path)

        body = _read(path)
        # Abstract paragraph lives under the Abstract heading now.
        abstract_idx = body.index("## Abstract")
        next_heading_idx = body.index("## Key Takeaways")
        abstract_block = body[abstract_idx:next_heading_idx]
        assert "Test-time adaptation has emerged" in abstract_block

    def test_already_new_format_is_no_op(self, tmp_path: Path) -> None:
        """A file that already has ``## Core Information`` shouldn't be touched."""
        from paperwiki.runners.migrate_sources import migrate_source

        new_format = (
            "---\ncanonical_id: arxiv:1234.5678\ntitle: New\nstatus: draft\n"
            "confidence: 0.5\ndomain: cs.CV\ntags: [cs.CV]\n"
            "published_at: '2026-04-20'\nlanding_url: ''\npdf_url: ''\n"
            "citation_count: 0\nscore_breakdown:\n  composite: 0.5\n"
            "  relevance: 0.0\n  novelty: 0.0\n  momentum: 0.0\n  rigor: 0.0\n"
            "related_concepts: []\nlast_synthesized: '2026-04-26'\n---\n\n"
            "# New\n\n## Core Information\n\n- ...\n\n## Abstract\n\nx.\n"
            "\n## Key Takeaways\n\n## Figures\n\n## Notes\n"
        )
        path = _seed(tmp_path, "arxiv_1234.5678.md", new_format)
        original = _read(path)

        changed = migrate_source(path)

        assert changed is False
        assert _read(path) == original

    def test_preserves_user_notes_section_when_already_present(self, tmp_path: Path) -> None:
        """Hybrid case: file partially migrated (e.g. extract-images appended
        ## Figures + ## Notes already). User edits in ## Notes must survive
        a re-migration."""
        from paperwiki.runners.migrate_sources import migrate_source

        hybrid = _OLD_FORMAT + (
            "\n## Figures\n\n![[arxiv_2604.21360/images/Figure_1.pdf|800]]\n"
            "\n## Notes\n\nMY_PRECIOUS_USER_NOTES — keep these.\n"
        )
        path = _seed(tmp_path, "arxiv_2604.21360.md", hybrid)
        migrate_source(path)

        body = _read(path)
        assert "MY_PRECIOUS_USER_NOTES" in body
        # Figures embed survives too.
        assert "![[arxiv_2604.21360/images/Figure_1.pdf" in body


# ---------------------------------------------------------------------------
# migrate_vault (bulk walker)
# ---------------------------------------------------------------------------


class TestMigrateVault:
    async def test_walks_all_sources_and_reports_count(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_sources import migrate_vault

        # Two old-format, one already-new.
        _seed(tmp_path, "arxiv_111.md", _OLD_FORMAT.replace("21360", "111"))
        _seed(tmp_path, "arxiv_222.md", _OLD_FORMAT.replace("21360", "222"))
        new_format_min = (
            "---\ncanonical_id: arxiv:333\ntitle: T\nstatus: draft\n"
            "confidence: 0.5\n---\n\n# T\n\n## Core Information\n- x\n"
            "\n## Abstract\n\nx.\n\n## Key Takeaways\n\n## Figures\n\n## Notes\n"
        )
        _seed(tmp_path, "arxiv_333.md", new_format_min)

        report = await migrate_vault(tmp_path)
        assert report.checked == 3
        assert report.migrated == 2
        assert report.skipped == 1
        assert sorted(report.migrated_paths) == sorted(
            [
                str((tmp_path / "Wiki/sources/arxiv_111.md").relative_to(tmp_path)),
                str((tmp_path / "Wiki/sources/arxiv_222.md").relative_to(tmp_path)),
            ]
        )

    async def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_sources import migrate_vault

        path = _seed(tmp_path, "arxiv_111.md", _OLD_FORMAT.replace("21360", "111"))
        before = _read(path)

        report = await migrate_vault(tmp_path, dry_run=True)
        assert report.migrated == 1  # would migrate
        assert _read(path) == before  # but file untouched

    async def test_empty_vault_reports_zero(self, tmp_path: Path) -> None:
        from paperwiki.runners.migrate_sources import migrate_vault

        report = await migrate_vault(tmp_path)
        assert report.checked == 0
        assert report.migrated == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_emits_valid_json(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from paperwiki.runners import migrate_sources as runner

        _seed(tmp_path, "arxiv_111.md", _OLD_FORMAT.replace("21360", "111"))

        cli = CliRunner()
        result = cli.invoke(runner.app, [str(tmp_path)])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["checked"] == 1
        assert payload["migrated"] == 1
