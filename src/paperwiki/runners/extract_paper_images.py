"""``paperwiki.runners.extract_paper_images`` — pull figures from arXiv source.

Invoked by the ``paperwiki:extract-images`` SKILL via::

    ${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.extract_paper_images \
        <vault> <canonical-id> [--force]

What it does:

1. Verifies that ``Wiki/sources/<id>.md`` exists in the vault (created
   earlier by digest or analyze).
2. Downloads the arXiv source tarball to ``Wiki/.cache/sources/<id>.tar.gz``
   (idempotent — skips when the tarball is already cached unless
   ``--force`` is passed).
3. Extracts image files from common figure dirs into
   ``Wiki/sources/<id>/images/``.
4. Rewrites the ``## Figures`` section of the source ``.md`` with
   Obsidian wikilink embeds (``![[<id>/images/<name>|800]]``). Other
   sections (``## Notes``, ``## Key Takeaways``, etc.) are preserved
   intact.
5. Emits a JSON report on stdout::

       {
         "canonical_id": "arxiv:2506.13063",
         "image_count": 7,
         "images": ["Wiki/sources/arxiv_2506.13063/images/teaser.png", ...],
         "cached": false
       }

Per SPEC §6, no LLM calls — Claude does the synthesis on top later.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from loguru import logger

from paperwiki._internal.arxiv_source import (
    download_arxiv_source,
    extract_images_from_tarball,
)
from paperwiki._internal.http import build_client
from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.layout import WIKI_SUBDIR
from paperwiki.core.errors import PaperWikiError, UserError
from paperwiki.plugins.backends.markdown_wiki import _canonical_id_to_filename

if TYPE_CHECKING:
    import httpx


app = typer.Typer(
    add_completion=False,
    help="Download arXiv source for a paper, extract figures, embed in Wiki/sources/.",
    no_args_is_help=True,
)


_FIGURES_SECTION_RE = re.compile(
    r"(?P<heading>^## Figures\n)(?P<body>.*?)(?=^## |\Z)",
    re.DOTALL | re.MULTILINE,
)


@dataclass(slots=True)
class ExtractResult:
    """Machine-readable result returned by the runner."""

    canonical_id: str
    image_count: int
    images: list[str] = field(default_factory=list)
    cached: bool = False


# ---------------------------------------------------------------------------
# Core async function
# ---------------------------------------------------------------------------


async def extract_paper_images(
    vault_path: Path,
    canonical_id: str,
    *,
    wiki_subdir: str = WIKI_SUBDIR,
    http_client: httpx.AsyncClient | None = None,
    force: bool = False,
) -> ExtractResult:
    """Download + extract + embed in one shot.

    ``http_client`` is injectable so tests can stub network calls; in
    production the runner builds a default client.
    """
    wiki_root = vault_path / wiki_subdir
    sources_dir = wiki_root / "sources"
    source_filename = _canonical_id_to_filename(canonical_id)
    source_path = sources_dir / f"{source_filename}.md"
    if not source_path.is_file():
        try:
            relative = source_path.relative_to(vault_path)
        except ValueError:
            relative = source_path
        msg = (
            f"extract_paper_images: source file not found at "
            f"Wiki/sources/{relative.name}. Run `/paper-wiki:digest` or "
            "`/paper-wiki:analyze` first to create it."
        )
        raise UserError(msg)

    cache_dir = wiki_root / ".cache" / "sources"
    arxiv_id = canonical_id.split(":", 1)[1] if ":" in canonical_id else canonical_id
    tarball_path = cache_dir / f"{arxiv_id}.tar.gz"

    owns_client = http_client is None
    client = http_client or build_client()
    try:
        cached = tarball_path.is_file() and not force
        if not cached:
            await download_arxiv_source(canonical_id, cache_dir, http_client=client)
    finally:
        if owns_client:
            await client.aclose()

    images_dir = sources_dir / source_filename / "images"
    if force and images_dir.is_dir():
        for old in images_dir.glob("*"):
            if old.is_file():
                old.unlink()
    extracted = extract_images_from_tarball(tarball_path, images_dir)

    new_body = _rewrite_figures_section(
        source_path.read_text(encoding="utf-8"),
        canonical_id=canonical_id,
        source_filename=source_filename,
        images=extracted,
    )
    source_path.write_text(new_body, encoding="utf-8")

    rel_paths = [
        str(p.relative_to(vault_path))
        if vault_path in p.parents or p.is_relative_to(vault_path)
        else str(p)
        for p in extracted
    ]
    logger.info(
        "extract_paper_images.done",
        canonical_id=canonical_id,
        count=len(extracted),
        cached=cached,
    )
    return ExtractResult(
        canonical_id=canonical_id,
        image_count=len(extracted),
        images=rel_paths,
        cached=cached,
    )


# ---------------------------------------------------------------------------
# Body-rewrite helper
# ---------------------------------------------------------------------------


def _rewrite_figures_section(
    body: str,
    *,
    canonical_id: str,
    source_filename: str,
    images: list[Path],
) -> str:
    """Replace the body of the ``## Figures`` section with embeds (or a note)."""
    if images:
        embeds = "\n\n".join(f"![[{source_filename}/images/{p.name}|800]]" for p in images)
        new_section_body = f"\n{embeds}\n\n"
    else:
        new_section_body = (
            "\n_arXiv source has no figures to extract — paper may be PDF-only "
            f"(0 figures found in source tarball for `{canonical_id}`)._\n\n"
        )

    def _sub(match: re.Match[str]) -> str:
        return f"{match.group('heading')}{new_section_body}"

    new_body, count = _FIGURES_SECTION_RE.subn(_sub, body, count=1)
    if count == 0:
        # Defensive: source body lacks the section (manually edited /
        # legacy format). Append a fresh section at the end so the
        # extraction isn't silently lost.
        new_body = body.rstrip() + "\n\n## Figures\n" + new_section_body
    return new_body


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


@app.command()
def main(
    vault: Annotated[Path, typer.Argument(help="Path to the user's vault")],
    canonical_id: Annotated[str, typer.Argument(help="Canonical id (arxiv:...)")],
    force: Annotated[
        bool, typer.Option("--force", help="Re-download tarball even if cached")
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Run the extractor and emit a JSON report."""
    configure_runner_logging(verbose=verbose)
    try:
        result = asyncio.run(extract_paper_images(vault, canonical_id, force=force))
    except PaperWikiError as exc:
        logger.error("extract_paper_images.failed", error=str(exc))
        raise typer.Exit(exc.exit_code) from exc

    typer.echo(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["ExtractResult", "app", "extract_paper_images"]
