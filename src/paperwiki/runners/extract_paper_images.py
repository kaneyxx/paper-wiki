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
3. Extracts image files using a 3-priority strategy:

   - **Priority 1** (existing): image files from figure dirs inside the
     source tarball (``figures/``, ``fig/``, ``pics/``, etc.).
   - **Priority 2** (new): standalone PDF files at the tarball root,
     converted to PNG via PyMuPDF.
   - **Priority 3** (new): when P1+P2 yield <2 figures and the source
     contains TikZ, caption-aware crops of the compiled paper PDF.

4. Writes ``Wiki/sources/<id>/images/index.md`` manifest with per-figure
   source class.
5. Rewrites the ``## Figures`` section of the source ``.md`` with
   Obsidian wikilink embeds (``![[<id>/images/<name>|800]]``). Other
   sections (``## Notes``, ``## Key Takeaways``, etc.) are preserved
   intact.
6. Emits a JSON report on stdout::

       {
         "canonical_id": "arxiv:2506.13063",
         "image_count": 7,
         "images": ["Wiki/sources/arxiv_2506.13063/images/teaser.png", ...],
         "cached": false,
         "sources": {"arxiv-source": 5, "pdf-figure": 2, "tikz-cropped": 0}
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
    _has_tikz,
    download_arxiv_source,
    extract_images_from_tarball,
    extract_root_pdfs_from_tarball,
    extract_tikz_crop_from_pdf,
)
from paperwiki._internal.http import build_client
from paperwiki._internal.logging import configure_runner_logging
from paperwiki.config.layout import LEGACY_PAPERS_SUBDIR, PAPERS_SUBDIR, WIKI_SUBDIR
from paperwiki.core.errors import PaperWikiError, UserError
from paperwiki.plugins.backends.markdown_wiki import _canonical_id_to_filename

if TYPE_CHECKING:
    import httpx


app = typer.Typer(
    add_completion=False,
    help="Download arXiv source for a paper, extract figures, embed in Wiki/papers/.",
    no_args_is_help=True,
)


_FIGURES_SECTION_RE = re.compile(
    r"(?P<heading>^## Figures\n)(?P<body>.*?)(?=^## |\Z)",
    re.DOTALL | re.MULTILINE,
)

# Task 9.186: track legacy ``Wiki/sources/`` hits so the deprecation
# warning fires exactly once per process per file. Tests reset by
# clearing this set; production never resets.
_LEGACY_WARNED: set[Path] = set()


@dataclass(slots=True)
class SourceCounts:
    """Per-priority figure counts."""

    arxiv_source: int = 0
    pdf_figure: int = 0
    tikz_cropped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "arxiv-source": self.arxiv_source,
            "pdf-figure": self.pdf_figure,
            "tikz-cropped": self.tikz_cropped,
        }


@dataclass(slots=True)
class ExtractResult:
    """Machine-readable result returned by the runner."""

    canonical_id: str
    image_count: int
    images: list[str] = field(default_factory=list)
    cached: bool = False
    sources: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# index.md manifest writer
# ---------------------------------------------------------------------------


def _write_index_md(
    images_dir: Path,
    *,
    p1: list[Path],
    p2: list[Path],
    p3: list[Path],
) -> None:
    """Write images/index.md with per-figure source class."""
    lines: list[str] = ["# Figure Index\n"]
    lines.append(
        f"Total: {len(p1) + len(p2) + len(p3)} figures "
        f"({len(p1)} arxiv-source, {len(p2)} pdf-figure, {len(p3)} tikz-cropped)\n"
    )

    def _section(title: str, paths: list[Path], source_class: str) -> None:
        if not paths:
            return
        lines.append(f"\n## {title}\n")
        for p in paths:
            try:
                size_kb = p.stat().st_size / 1024
            except OSError:
                size_kb = 0.0
            lines.append(f"- **{p.name}**")
            lines.append(f"  - source: {source_class}")
            lines.append(f"  - path: {p.relative_to(images_dir.parent)}")
            lines.append(f"  - size: {size_kb:.1f} KB")
            lines.append(f"  - format: {p.suffix.lstrip('.')}\n")

    _section("Priority 1 — arXiv source figures", p1, "arxiv-source")
    _section("Priority 2 — Root PDF figures", p2, "pdf-figure")
    _section("Priority 3 — TikZ caption crops", p3, "tikz-cropped")

    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


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
    source_filename = _canonical_id_to_filename(canonical_id)

    # Task 9.186 (D-T): resolve the per-paper source against the
    # canonical ``Wiki/papers/<id>.md`` first. For one release, also
    # accept the v0.3.x legacy ``Wiki/sources/<id>.md`` location with
    # a one-shot ``extract_images.legacy.sources_path`` warning so
    # users know to run ``paperwiki wiki-compile`` and migrate.
    canonical_source_path = wiki_root / PAPERS_SUBDIR / f"{source_filename}.md"
    legacy_source_path = wiki_root / LEGACY_PAPERS_SUBDIR / f"{source_filename}.md"

    if canonical_source_path.is_file():
        source_path = canonical_source_path
    elif legacy_source_path.is_file():
        source_path = legacy_source_path
        if legacy_source_path not in _LEGACY_WARNED:
            _LEGACY_WARNED.add(legacy_source_path)
            logger.warning(
                "extract_images.legacy.sources_path path={path}",
                path=str(legacy_source_path),
            )
    else:
        msg = (
            f"extract_paper_images: source file not found at "
            f"Wiki/{PAPERS_SUBDIR}/{source_filename}.md. Run "
            f"`/paper-wiki:digest` or `/paper-wiki:analyze` first to create it."
        )
        raise UserError(msg)

    # The internal arXiv tarball cache (``Wiki/.cache/sources/``) is
    # NOT renamed — it is not user-facing and keeping the spelling
    # preserves every existing user's tarball cache across the
    # v0.4.1 → v0.4.2 upgrade. (See plan §5 risks table.)
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

    # Image manifest follows the source-file directory the user
    # actually has, so legacy vaults keep their figures in
    # ``Wiki/sources/<id>/images/`` until the migrate runs.
    images_dir = source_path.parent / source_filename / "images"
    if force and images_dir.is_dir():
        for old in images_dir.glob("*"):
            if old.is_file():
                old.unlink()

    # ------------------------------------------------------------------
    # Priority 1: figure dirs in source tarball
    # ------------------------------------------------------------------
    p1 = extract_images_from_tarball(tarball_path, images_dir)
    logger.info("extract_paper_images.p1", count=len(p1))

    # ------------------------------------------------------------------
    # Priority 2: standalone root PDFs → PNG
    # ------------------------------------------------------------------
    p2 = extract_root_pdfs_from_tarball(tarball_path, images_dir, paper_id=arxiv_id)
    logger.info("extract_paper_images.p2", count=len(p2))

    # ------------------------------------------------------------------
    # Priority 3: TikZ caption-aware crop (only when P1+P2 < 2 figures)
    # ------------------------------------------------------------------
    p3: list[Path] = []
    if len(p1) + len(p2) < 2:
        if _has_tikz(tarball_path):
            # Look for compiled PDF in the cache or alongside the tarball.
            paper_pdf = cache_dir / f"{arxiv_id}.pdf"
            if paper_pdf.is_file():
                p3 = extract_tikz_crop_from_pdf(paper_pdf, images_dir, paper_id=arxiv_id)
                logger.info("extract_paper_images.p3", count=len(p3))
            else:
                logger.debug(
                    "extract_paper_images.p3_skip",
                    reason="no compiled PDF found at cache path",
                    expected=str(paper_pdf),
                )
        else:
            logger.debug("extract_paper_images.p3_skip", reason="no TikZ detected in source")

    # ------------------------------------------------------------------
    # Write index.md manifest
    # ------------------------------------------------------------------
    _write_index_md(images_dir, p1=p1, p2=p2, p3=p3)

    # ------------------------------------------------------------------
    # All extracted paths (excluding index.md)
    # ------------------------------------------------------------------
    extracted = [img for img in sorted(p1 + p2 + p3) if img.name != "index.md"]

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
    source_counts = SourceCounts(
        arxiv_source=len(p1),
        pdf_figure=len(p2),
        tikz_cropped=len(p3),
    )
    logger.info(
        "extract_paper_images.done",
        canonical_id=canonical_id,
        count=len(extracted),
        cached=cached,
        sources=source_counts.as_dict(),
    )
    return ExtractResult(
        canonical_id=canonical_id,
        image_count=len(extracted),
        images=rel_paths,
        cached=cached,
        sources=source_counts.as_dict(),
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


@app.command(name="extract-images")
def main(
    arg1: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Either the canonical id (arxiv:..., s2:...) when only one positional "
                "is given, or the vault path when two positionals are given. The "
                "single-arg form (Task 9.193 / D-V) resolves the vault from "
                "$PAPERWIKI_DEFAULT_VAULT or ~/.config/paper-wiki/config.toml."
            ),
            show_default=False,
        ),
    ] = None,
    arg2: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Canonical id (arxiv:...) when arg1 was a vault path. "
                "Omit when arg1 already carries the canonical id."
            ),
            show_default=False,
        ),
    ] = None,
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

    vault, canonical_id = _resolve_vault_and_canonical_id(arg1, arg2)

    try:
        result = asyncio.run(extract_paper_images(vault, canonical_id, force=force))
    except PaperWikiError as exc:
        logger.error("extract_paper_images.failed", error=str(exc))
        raise typer.Exit(exc.exit_code) from exc

    typer.echo(json.dumps(asdict(result), indent=2))


def _resolve_vault_and_canonical_id(arg1: str | None, arg2: str | None) -> tuple[Path, str]:
    """Disambiguate the two-form CLI signature into ``(vault, canonical_id)``.

    Two valid forms (Task 9.193 / D-V):

    * ``extract-images <vault> <id>`` — back-compat, both args present.
    * ``extract-images <id>`` — new form, vault resolved from D-V chain.

    Heuristic: when only ``arg1`` is given, it MUST contain ``:`` to be a
    canonical id (e.g. ``arxiv:2506.13063`` or ``s2:abc...``). A single
    arg without ``:`` is rejected with a usage hint rather than silently
    treated as a vault path that crashes later when the canonical id is
    missing.
    """
    # Lazy import to keep module import cheap and avoid circular issues.
    from paperwiki.config.vault_resolver import resolve_vault

    if arg1 is None:
        # Typer normally rejects missing required positionals with exit
        # code 2 before calling this function; this branch is defensive.
        raise typer.BadParameter("Missing CANONICAL_ID (e.g. 'arxiv:2506.13063' or 's2:abc123').")

    if arg2 is None:
        # Single positional — must look like a canonical id.
        if ":" not in arg1:
            raise typer.BadParameter(
                f"Single argument {arg1!r} is not a canonical id "
                "(expected 'arxiv:...' or 's2:...'). To pass a vault path, "
                "give the canonical id as the second argument."
            )
        canonical_id = arg1
        try:
            vault = resolve_vault(None)
        except UserError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(exc.exit_code) from exc
    else:
        # Two positionals — vault first (back-compat), canonical_id second.
        vault = Path(arg1).expanduser()
        canonical_id = arg2

    return vault, canonical_id


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()


__all__ = ["ExtractResult", "app", "extract_paper_images"]
