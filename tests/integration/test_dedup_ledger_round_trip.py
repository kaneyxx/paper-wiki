"""End-to-end persistence test for the dedup ledger (task 9.168).

Two consecutive runs of the same recipe — same source, same single
paper. The first run surfaces the paper. The second run consults
``<vault>/.paperwiki/dedup-ledger.jsonl`` and silently drops it (per
**D-F**). This is the contract that makes the ledger valuable.

The test uses real :class:`Pipeline` + :class:`DedupFilter` + the
real :class:`DedupLedgerKeyLoader` so the integration is exercised
end-to-end. Pipeline construction goes through ``instantiate_pipeline``
to lock in the recipe-builder behavior (auto-engage of the ledger
loader when an obsidian reporter is present).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

from paperwiki._internal.dedup_ledger import (
    LEDGER_DIR,
    LEDGER_FILE,
    read_dedup_keys,
)
from paperwiki.config.recipe import RecipeSchema
from paperwiki.core.models import Author, Paper, RunContext
from paperwiki.runners import digest as digest_runner


def _recipe(vault: Path, *, output_dir: Path) -> RecipeSchema:
    data: dict[str, Any] = {
        "name": "9168-round-trip",
        "sources": [{"name": "arxiv", "config": {"categories": ["cs.AI"], "lookback_days": 1}}],
        "filters": [{"name": "dedup", "config": {"vault_paths": []}}],
        "scorer": {
            "name": "composite",
            "config": {"topics": [{"name": "vlm", "keywords": ["foundation model"]}]},
        },
        "reporters": [
            {"name": "markdown", "config": {"output_dir": str(output_dir)}},
            {
                "name": "obsidian",
                "config": {"vault_path": str(vault), "daily_subdir": "Daily"},
            },
        ],
        "top_k": 5,
    }
    return RecipeSchema.model_validate(data)


_PAPER = Paper(
    canonical_id="arxiv:2401.12345",
    title="Foundation Models for Vision-Language",
    authors=[Author(name="A")],
    abstract="abstract",
    published_at=datetime(2026, 4, 20, tzinfo=UTC),
)


class _OneShotSource:
    name = "arxiv"

    async def fetch(self, ctx: RunContext) -> AsyncIterator[Paper]:
        yield _PAPER


async def test_second_run_silently_drops_surfaced_paper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    recipe_path = tmp_path / "r.yaml"

    # Build a recipe object once and pin it through monkeypatched
    # load_recipe so we don't have to maintain a YAML fixture file.
    recipe = _recipe(vault, output_dir=output_dir)
    monkeypatch.setattr(digest_runner, "load_recipe", lambda _path: recipe)

    # Use the real instantiate_pipeline so the ledger loader is actually
    # wired in via _build_filter. Stub only the source so the test
    # doesn't need network access.
    real_instantiate = digest_runner.instantiate_pipeline

    def patched_instantiate(r: RecipeSchema) -> Any:
        pipeline = real_instantiate(r)
        # Replace the live arxiv source with our stub.
        pipeline.sources = [_OneShotSource()]
        return pipeline

    monkeypatch.setattr(digest_runner, "instantiate_pipeline", patched_instantiate)

    # First run — paper surfaces, ledger gets a `surfaced` row.
    await digest_runner.run_digest(recipe_path)

    keys_after_first = read_dedup_keys(vault)
    assert "2401.12345" in keys_after_first.arxiv_ids, (
        "first run should record the emitted paper in the dedup ledger"
    )

    # Sanity check the ledger lives at the documented path.
    assert (vault / LEDGER_DIR / LEDGER_FILE).is_file()

    # Second run — same paper, but the dedup filter should drop it.
    # We assert via the digest output: the markdown reporter writes a
    # "no recommendations" section when the final list is empty.
    await digest_runner.run_digest(recipe_path)

    md_files = list(output_dir.glob("*-paper-digest.md"))
    assert md_files, "markdown reporter should have written a digest file"
    second_run_text = md_files[0].read_text(encoding="utf-8")
    # The original paper is gone from the second digest (silent drop).
    assert "Foundation Models for Vision-Language" not in second_run_text
