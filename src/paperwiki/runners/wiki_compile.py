"""``paperwiki.runners.wiki_compile`` — rebuild ``Wiki/index.md``.

Invoked by the ``paperwiki:wiki-compile`` SKILL via::

    ${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.wiki_compile <vault>

Walks the wiki via :class:`MarkdownWikiBackend`, sorts everything
deterministically, and rewrites ``Wiki/index.md`` with:

* Frontmatter recording the compile date and concept/source counts.
* A warning banner so users know hand-edits will be overwritten.
* A bullet list of concepts (wikilinked, with source counts and
  confidence).
* A table of sources (date, wikilinked title, listed concepts).

Per SPEC §6, no LLM calls; the SKILL paraphrases the result for the
user. The output is deterministic — same vault state produces the same
file bytes — so the file fits cleanly in version control.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import aiofiles
import typer
from loguru import logger

from paperwiki import __version__
from paperwiki._internal.locking import acquire_vault_lock
from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.config.vault_resolver import resolve_vault
from paperwiki.core.errors import PaperWikiError, UserError
from paperwiki.plugins.backends.markdown_wiki import MarkdownWikiBackend

if TYPE_CHECKING:
    from paperwiki.plugins.backends.markdown_wiki import (
        ConceptSummary,
        SourceSummary,
    )


app = typer.Typer(
    add_completion=False,
    help="Rebuild Wiki/index.md from the current vault state.",
    no_args_is_help=True,
)


@dataclass(frozen=True, slots=True)
class CompileResult:
    """Summary returned by :func:`compile_wiki`."""

    index_path: Path
    concepts: int
    sources: int


async def compile_wiki(
    vault_path: Path,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
    now: datetime | None = None,
    allow_auto_migrate: bool = True,
) -> CompileResult:
    """Rebuild the wiki index file and return a summary.

    Acquires the vault advisory lock for the duration of the operation so
    concurrent ingest runs cannot observe a partial index.

    Task 9.187 (D-T): when ``allow_auto_migrate`` is true (default)
    AND ``PAPERWIKI_NO_AUTO_MIGRATE`` is unset, an in-place
    ``Wiki/sources/`` → ``Wiki/papers/`` migration via
    :mod:`paperwiki.runners.migrate_v04` runs BEFORE the index
    rebuild. The migration is gated by ``migrate_v04.needs_migration``
    (idempotent — no-op when ``papers/`` is already populated) and
    uses the existing D-J SHA-256 backup at
    ``<vault>/.paperwiki/migration-backup/<ts>/``.

    Pass ``allow_auto_migrate=False`` to skip the move entirely
    (the index rebuild still runs against the legacy layout via
    :meth:`MarkdownWikiBackend.list_sources`'s read-fallback shim).
    """
    async with acquire_vault_lock(vault_path):
        if allow_auto_migrate:
            _run_auto_migrate_if_needed(vault_path, wiki_subdir=wiki_subdir)
        return await _compile_wiki_locked(vault_path, wiki_subdir=wiki_subdir, now=now)


def _run_auto_migrate_if_needed(vault_path: Path, *, wiki_subdir: str = WIKI_SUBDIR) -> None:
    """Fire :func:`migrate_v04.migrate_if_needed` and print a banner.

    The banner uses :func:`typer.echo` (stdout) rather than ``loguru``
    so users see it as part of the runner's normal output rather than
    buried in extras. ``migrate_v04`` already logs its own
    ``migrate_v04.move.complete`` event for observability.
    """
    from paperwiki.runners import migrate_v04

    if not migrate_v04.needs_migration(vault_path, wiki_subdir=wiki_subdir):
        return
    plan = migrate_v04.dry_run(vault_path, wiki_subdir=wiki_subdir)
    file_count = len(plan.planned_moves)
    result = migrate_v04.migrate_if_needed(vault_path, wiki_subdir=wiki_subdir)
    if result is None:
        # User opted out via PAPERWIKI_NO_AUTO_MIGRATE=1.
        return
    if result.moved_count == 0:
        return
    backup_rel = (
        result.backup_dir.relative_to(vault_path)
        if vault_path in result.backup_dir.parents or result.backup_dir.is_relative_to(vault_path)
        else result.backup_dir
    )
    typer.echo(
        f"Migrating Wiki/sources/ → Wiki/papers/ ({file_count} files, backup at {backup_rel}/)"
    )


async def _compile_wiki_locked(
    vault_path: Path,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
    now: datetime | None = None,
) -> CompileResult:
    """Inner implementation — called with vault lock already held."""
    backend = MarkdownWikiBackend(vault_path=vault_path, wiki_subdir=wiki_subdir)
    sources = await backend.list_sources()
    concepts = await backend.list_concepts()

    # Sort deterministically.
    concepts_sorted = sorted(concepts, key=lambda c: c.title.lower())
    sources_sorted = sorted(sources, key=lambda s: s.canonical_id.lower())

    when = now or datetime.now(UTC)
    body = _render_index(concepts_sorted, sources_sorted, when=when)

    index_path = vault_path / wiki_subdir / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(index_path, "w", encoding="utf-8") as fh:
        await fh.write(body)

    return CompileResult(
        index_path=index_path,
        concepts=len(concepts_sorted),
        sources=len(sources_sorted),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_index(
    concepts: list[ConceptSummary],
    sources: list[SourceSummary],
    *,
    when: datetime,
) -> str:
    parts: list[str] = []
    parts.append(_render_frontmatter(len(concepts), len(sources), when))
    parts.append(
        "# Wiki Index\n\n"
        "_Auto-generated. Edit at your own risk; "
        "`/paper-wiki:wiki-compile` overwrites this file._\n"
    )

    if concepts:
        parts.append("## Concepts\n")
        parts.extend(
            f"- [[{c.name}]] — {len(c.sources)} sources, confidence {c.confidence:.2f}"
            for c in concepts
        )
        parts.append("")
    else:
        parts.append("## Concepts\n\n_No concepts yet._\n")

    if sources:
        parts.append("## Sources\n")
        # Inverted index: which concepts list each source.
        by_source: dict[str, list[str]] = {}
        for concept in concepts:
            for src_id in concept.sources:
                by_source.setdefault(src_id, []).append(concept.name)
        parts.append("| Date | Source | Concepts |")
        parts.append("| ---- | ------ | -------- |")
        for source in sources:
            stem = source.path.stem
            concept_links = (
                ", ".join(f"[[{name}]]" for name in sorted(by_source.get(source.canonical_id, [])))
                or "—"
            )
            parts.append(f"| {when.strftime('%Y-%m-%d')} | [[{stem}]] | {concept_links} |")
        parts.append("")
    else:
        parts.append("## Sources\n\n_No sources yet._\n")

    return "\n".join(parts) + "\n"


def _render_frontmatter(
    concept_count: int,
    source_count: int,
    when: datetime,
) -> str:
    return (
        "---\n"
        f'generated_by: "paper-wiki/{__version__}"\n'
        f'last_compiled: "{when.strftime("%Y-%m-%d")}"\n'
        f"concepts: {concept_count}\n"
        f"sources: {source_count}\n"
        "---\n"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@app.command(name="wiki-compile")
def main(
    vault: Annotated[
        Path | None,
        typer.Argument(
            help=(
                "Path to the user's vault. Optional (Task 9.216 / D-V) — "
                "falls back to $PAPERWIKI_DEFAULT_VAULT, then "
                "~/.config/paper-wiki/config.toml::default_vault."
            ),
            show_default=False,
        ),
    ] = None,
    migrate_dry_run: Annotated[
        bool,
        typer.Option(
            "--migrate-dry-run",
            help=(
                "Preview the v0.3.x → v0.4.x typed-subdir migration "
                "(per task 9.160) without touching the filesystem; "
                "exits before the index rebuild."
            ),
        ),
    ] = False,
    restore_migration: Annotated[
        str | None,
        typer.Option(
            "--restore-migration",
            help=(
                "Reverse a previous v0.4.x migration by SHA-256-verified "
                "restore from <vault>/.paperwiki/migration-backup/<ts>/. "
                "Argument is the backup timestamp (per R3). Exits before "
                "the index rebuild."
            ),
        ),
    ] = None,
    properties_dry_run: Annotated[
        bool,
        typer.Option(
            "--properties-dry-run",
            help=(
                "Preview the v0.4.0-Phase-1 → Phase-2 Obsidian Properties "
                "frontmatter rewrite (per task 9.161) without touching the "
                "filesystem; exits before the index rebuild."
            ),
        ),
    ] = False,
    restore_properties: Annotated[
        str | None,
        typer.Option(
            "--restore-properties",
            help=(
                "Reverse a previous Properties migration by SHA-256-verified "
                "restore from <vault>/.paperwiki/properties-migration-backup/"
                "<ts>/. Argument is the backup timestamp (per task 9.161 R12). "
                "Exits before the index rebuild."
            ),
        ),
    ] = None,
    no_auto_migrate: Annotated[
        bool,
        typer.Option(
            "--no-auto-migrate",
            help=(
                "Skip the v0.3.x → v0.4.x typed-subdir auto-migration "
                "fired automatically before the index rebuild (Task 9.187). "
                "Prints the dry-run plan instead, then runs the rebuild "
                "against the legacy layout via the read-fallback shim. "
                "Use when you want to inspect the planned moves before "
                "committing — the global env-var equivalent is "
                "PAPERWIKI_NO_AUTO_MIGRATE=1."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Rebuild Wiki/index.md and print a one-line summary.

    Per task 9.160: ``--migrate-dry-run`` and ``--restore-migration <ts>``
    short-circuit the normal compile so users can preview / reverse the
    typed-subdir migration without re-running the whole index rebuild.

    Per task 9.161 increment 6: ``--properties-dry-run`` and
    ``--restore-properties <ts>`` mirror the same pattern for the
    Phase-1 → Phase-2 Obsidian Properties frontmatter rewrite.
    """
    configure_runner_logging(verbose=verbose)

    # Task 9.216 / D-V: resolve the vault when the positional was omitted.
    # Mirrors the wiki_graph_query.py:294-309 pattern — explicit positional
    # wins, otherwise fall through $PAPERWIKI_DEFAULT_VAULT →
    # $PAPERWIKI_HOME/config.toml::default_vault → actionable error.
    if vault is None:
        try:
            vault = resolve_vault(None)
        except UserError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(exc.exit_code) from exc
    else:
        vault = vault.expanduser()

    # Migration short-circuits — handled before the normal compile path.
    if migrate_dry_run:
        from paperwiki.runners.migrate_v04 import dry_run

        plan = dry_run(vault)
        typer.echo(
            json.dumps(
                {
                    "planned_moves": [
                        {
                            "src": str(m.src),
                            "dst": str(m.dst),
                            "sha256": m.sha256,
                        }
                        for m in plan.planned_moves
                    ]
                },
                indent=2,
            )
        )
        return

    if restore_migration is not None:
        from paperwiki.runners.migrate_v04 import restore

        try:
            restore(vault, timestamp=restore_migration)
        except PaperWikiError as exc:
            # Task 9.211: surface the actual error to stderr.
            typer.echo(str(exc), err=True)
            logger.error("wiki_compile.restore_failed", error=str(exc))
            raise typer.Exit(exc.exit_code) from exc
        typer.echo(f"restored migration {restore_migration}")
        return

    if properties_dry_run:
        from paperwiki.runners.migrate_properties import dry_run as props_dry_run

        props_plan = props_dry_run(vault)
        typer.echo(
            json.dumps(
                {
                    "planned_rewrites": [
                        {"src": str(r.src), "sha256": r.sha256} for r in props_plan.planned_rewrites
                    ]
                },
                indent=2,
            )
        )
        return

    if restore_properties is not None:
        from paperwiki.runners.migrate_properties import restore as props_restore

        try:
            props_restore(vault, timestamp=restore_properties)
        except PaperWikiError as exc:
            # Task 9.211: surface the actual error to stderr.
            typer.echo(str(exc), err=True)
            logger.error("wiki_compile.restore_properties_failed", error=str(exc))
            raise typer.Exit(exc.exit_code) from exc
        typer.echo(f"restored properties migration {restore_properties}")
        return

    # Task 9.187: surface the dry-run plan first if the user is
    # opting out of the auto-migrate path so they can see what
    # would have moved.
    if no_auto_migrate:
        from paperwiki.runners.migrate_v04 import dry_run

        plan = dry_run(vault)
        typer.echo(
            json.dumps(
                {
                    "planned_moves": [
                        {
                            "src": str(m.src),
                            "dst": str(m.dst),
                            "sha256": m.sha256,
                        }
                        for m in plan.planned_moves
                    ]
                },
                indent=2,
            )
        )

    try:
        result = asyncio.run(compile_wiki(vault, allow_auto_migrate=not no_auto_migrate))
    except PaperWikiError as exc:
        # Task 9.211: surface the actual error to stderr.
        typer.echo(str(exc), err=True)
        logger.error("wiki_compile.failed", error=str(exc))
        raise typer.Exit(exc.exit_code) from exc

    typer.echo(
        f"compiled: {result.concepts} concepts, {result.sources} sources -> {result.index_path}"
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["CompileResult", "app", "compile_wiki"]
