"""Smoke tests for the synthetic 100-note fixture vault.

Per consensus plan iter-2 R10 + §"Plan body — 9.156a", the fixture is
committed up-front (not lazily generated at test time) so:

* 9.157 (wiki_compile_graph) byte-equality tests have a stable input.
* 9.158 (wiki-lint --check-graph) scaling tests have realistic edge
  density.
* Scenario 3 (perf cliff) regressions are catchable in CI.
* Scenario 5 (vault-layout rollback round-trip) has a real corpus
  to migrate + restore against.

This test file only verifies the fixture's *structure* — that the
40+30+20+10 split is intact, that wikilink density meets the avg-5
per paper acceptance criterion, and that total size stays under the
200 KB budget. Functional tests live alongside the runners that
exercise the fixture.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parent.parent.parent / "fixtures" / "synthetic_vault_100"

EXPECTED_LAYOUT = {
    "papers": 40,
    "concepts": 30,
    "topics": 20,
    "people": 10,
}
TOTAL_NOTES = sum(EXPECTED_LAYOUT.values())
SIZE_BUDGET_BYTES = 200 * 1024
MIN_AVG_WIKILINKS_PER_PAPER = 5

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _iter_vault_notes(root: Path) -> list[Path]:
    """Iterate only the typed-subdir notes — skip the top-level README.

    The fixture root carries a documentation README that is intentionally
    not a vault note (no frontmatter, not part of the typed-subdir
    contract). Tests should never inspect it.
    """
    return sorted(p for subdir in EXPECTED_LAYOUT for p in (root / subdir).glob("*.md"))


@pytest.fixture(scope="module")
def fixture_root() -> Path:
    if not FIXTURE_ROOT.exists():
        pytest.fail(
            f"synthetic vault fixture missing at {FIXTURE_ROOT}; "
            "rebuild via `python tests/fixtures/build_synthetic_vault.py`"
        )
    return FIXTURE_ROOT


class TestSyntheticVaultStructure:
    def test_root_exists(self, fixture_root: Path) -> None:
        assert fixture_root.is_dir()

    def test_typed_subdirs_present(self, fixture_root: Path) -> None:
        for subdir in EXPECTED_LAYOUT:
            sub = fixture_root / subdir
            assert sub.is_dir(), f"missing typed subdir: {subdir}"

    def test_per_subdir_note_counts(self, fixture_root: Path) -> None:
        for subdir, expected_count in EXPECTED_LAYOUT.items():
            files = sorted((fixture_root / subdir).glob("*.md"))
            assert len(files) == expected_count, (
                f"{subdir} has {len(files)} notes, expected {expected_count}"
            )

    def test_total_note_count(self, fixture_root: Path) -> None:
        total = sum(len(list((fixture_root / subdir).glob("*.md"))) for subdir in EXPECTED_LAYOUT)
        assert total == TOTAL_NOTES

    def test_total_size_under_budget(self, fixture_root: Path) -> None:
        total_bytes = sum(f.stat().st_size for f in _iter_vault_notes(fixture_root))
        assert total_bytes <= SIZE_BUDGET_BYTES, (
            f"fixture is {total_bytes:,} bytes; budget is {SIZE_BUDGET_BYTES:,}"
        )


class TestSyntheticVaultContent:
    def test_each_note_has_yaml_frontmatter(self, fixture_root: Path) -> None:
        for md_path in _iter_vault_notes(fixture_root):
            text = md_path.read_text()
            assert text.startswith("---\n"), (
                f"{md_path.relative_to(fixture_root)} missing YAML frontmatter"
            )
            # Frontmatter terminator within first 30 lines (loose bound).
            assert "\n---\n" in text[:2000], (
                f"{md_path.relative_to(fixture_root)} frontmatter not closed"
            )

    def test_each_note_has_h1(self, fixture_root: Path) -> None:
        for md_path in _iter_vault_notes(fixture_root):
            text = md_path.read_text()
            # H1 must follow the frontmatter terminator.
            body = text.split("\n---\n", 1)[1] if "\n---\n" in text else text
            assert re.search(r"^# .+", body, flags=re.MULTILINE), (
                f"{md_path.relative_to(fixture_root)} missing H1 heading"
            )

    def test_papers_have_typed_frontmatter(self, fixture_root: Path) -> None:
        for paper_path in (fixture_root / "papers").glob("*.md"):
            text = paper_path.read_text()
            assert "type: paper" in text

    def test_concepts_have_typed_frontmatter(self, fixture_root: Path) -> None:
        for concept_path in (fixture_root / "concepts").glob("*.md"):
            assert "type: concept" in concept_path.read_text()

    def test_topics_have_typed_frontmatter(self, fixture_root: Path) -> None:
        for topic_path in (fixture_root / "topics").glob("*.md"):
            assert "type: topic" in topic_path.read_text()

    def test_people_have_typed_frontmatter(self, fixture_root: Path) -> None:
        for person_path in (fixture_root / "people").glob("*.md"):
            assert "type: person" in person_path.read_text()


class TestWikilinkDensity:
    def test_papers_have_avg_5_wikilinks(self, fixture_root: Path) -> None:
        # Acceptance criterion from plan §9.156a: "avg 5 outbound links per paper".
        paper_links = [
            len(WIKILINK_RE.findall(p.read_text())) for p in (fixture_root / "papers").glob("*.md")
        ]
        avg_links = sum(paper_links) / len(paper_links)
        assert avg_links >= MIN_AVG_WIKILINKS_PER_PAPER, (
            f"avg wikilink density is {avg_links:.2f}, expected ≥ {MIN_AVG_WIKILINKS_PER_PAPER}"
        )

    def test_total_wikilinks_at_realistic_scale(self, fixture_root: Path) -> None:
        # Sanity bound: with 100 notes and avg 3+ outbound links each, we
        # expect ≥ 200 wikilinks total. This catches a builder regression
        # where wikilinks silently disappear.
        total_links = sum(
            len(WIKILINK_RE.findall(p.read_text())) for p in _iter_vault_notes(fixture_root)
        )
        assert total_links >= 200, (
            f"only {total_links} wikilinks across the fixture; builder may have regressed"
        )


class TestDeterministicBuild:
    def test_builder_script_present(self) -> None:
        builder = Path(__file__).parent.parent.parent / "fixtures" / "build_synthetic_vault.py"
        assert builder.is_file(), "fixture builder script missing"

    def test_builder_uses_seed_42(self) -> None:
        # Per plan §9.156a acceptance: "Fixture built deterministically by
        # tests/fixtures/build_synthetic_vault.py (seed = 42)."
        builder = Path(__file__).parent.parent.parent / "fixtures" / "build_synthetic_vault.py"
        text = builder.read_text()
        assert "42" in text, "builder must reference seed=42 explicitly"
