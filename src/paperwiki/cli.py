"""``paperwiki`` — CLI for managing the paper-wiki Claude Code plugin.

Subcommands
-----------
paperwiki update      Refresh the marketplace clone, compare versions, and on
                      drift rename the stale cache + prune JSON entries so the
                      next ``/plugin install`` does a real install.
paperwiki status      Print a 3-line state report (cache / marketplace / settings).
paperwiki uninstall   Remove cache and JSON entries cleanly.

Wire ``--verbose`` to ``configure_runner_logging`` so output is consistent
with the runners.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from paperwiki._internal.logging import configure_runner_logging
from paperwiki.runners.digest import app as _digest_app
from paperwiki.runners.extract_paper_images import app as _extract_images_app
from paperwiki.runners.gc_bak import (
    BAK_FILENAME_RE,
)
from paperwiki.runners.gc_bak import (
    _resolve_default_keep_recent as _resolve_bak_keep,
)
from paperwiki.runners.gc_bak import (
    app as _gc_bak_app,
)
from paperwiki.runners.gc_bak import (
    gc_bak as _gc_bak_run,
)
from paperwiki.runners.gc_digest_archive import app as _gc_archive_app
from paperwiki.runners.migrate_recipe import app as _migrate_recipe_app
from paperwiki.runners.migrate_sources import app as _migrate_sources_app
from paperwiki.runners.where import app as _where_app
from paperwiki.runners.wiki_compile import app as _wiki_compile_app
from paperwiki.runners.wiki_ingest_plan import app as _wiki_ingest_app
from paperwiki.runners.wiki_lint import app as _wiki_lint_app
from paperwiki.runners.wiki_query import app as _wiki_query_app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PLUGIN_NAME = "paper-wiki"
_PLUGIN_KEY = "paper-wiki@paper-wiki"
_DEFAULT_MARKETPLACE_DIR = Path.home() / ".claude" / "plugins" / "marketplaces" / _PLUGIN_NAME
_INSTALLED_PLUGINS_JSON = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
_CACHE_BASE = Path.home() / ".claude" / "plugins" / "cache" / _PLUGIN_NAME / _PLUGIN_NAME
_SETTINGS_JSON = Path.home() / ".claude" / "settings.json"
_SETTINGS_LOCAL_JSON = Path.home() / ".claude" / "settings.local.json"

# ---------------------------------------------------------------------------
# Typer app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="paperwiki",
    add_completion=False,
    help="Manage the paper-wiki Claude Code plugin.",
    no_args_is_help=True,
)

# Plugin lifecycle commands (update / status / uninstall) are defined inline
# below as ``@app.command()`` decorators.  Operational subcommands re-use the
# corresponding ``paperwiki.runners.<name>`` Typer apps so each runner has a
# single source of truth — the CLI surface and ``python -m paperwiki.runners.<name>``
# stay in lock-step (Task 9.29 / D-9.29.2).
app.add_typer(_migrate_recipe_app, name="migrate-recipe")
app.add_typer(_digest_app, name="digest")
app.add_typer(_wiki_ingest_app, name="wiki-ingest")
app.add_typer(_wiki_lint_app, name="wiki-lint")
app.add_typer(_wiki_compile_app, name="wiki-compile")
app.add_typer(_wiki_query_app, name="wiki-query")
app.add_typer(_extract_images_app, name="extract-images")
app.add_typer(_migrate_sources_app, name="migrate-sources")
app.add_typer(_gc_archive_app, name="gc-archive")
app.add_typer(_gc_bak_app, name="gc-bak")
app.add_typer(_where_app, name="where")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, object]:
    """Return parsed JSON from *path*, or {} when the file is missing."""
    if not path.is_file():
        return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as exc:
        msg = f"paperwiki: failed to parse {path}: {exc}"
        raise typer.Exit(1) from typer.BadParameter(msg)


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _marketplace_version(marketplace_dir: Path) -> str | None:
    """Read version from ``<marketplace_dir>/.claude-plugin/plugin.json``."""
    plugin_json = marketplace_dir / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        return None
    try:
        data = json.loads(plugin_json.read_text(encoding="utf-8"))
        return str(data.get("version", ""))
    except (json.JSONDecodeError, OSError):
        return None


def _cache_version() -> str | None:
    """Read version from installed_plugins.json for _PLUGIN_KEY."""
    data = _read_json(_INSTALLED_PLUGINS_JSON)
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        return None
    entries = plugins.get(_PLUGIN_KEY)
    if not isinstance(entries, list) or not entries:
        return None
    # Use the first entry's version (multi-scope is rare; first one wins).
    first = entries[0]
    if not isinstance(first, dict):
        return None
    ver = first.get("version")
    return str(ver) if ver else None


def _git_pull(marketplace_dir: Path) -> None:
    """Fetch + pull --ff-only inside the marketplace clone."""
    for cmd in (
        ["git", "-C", str(marketplace_dir), "fetch", "--tags"],
        ["git", "-C", str(marketplace_dir), "pull", "--ff-only"],
    ):
        result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
        if result.returncode != 0:
            msg = (
                f"paperwiki update: git command failed: {' '.join(cmd)}\n"
                f"stderr: {result.stderr.strip()}"
            )
            typer.echo(msg, err=True)
            raise typer.Exit(1)
        if result.stdout.strip():
            logger.debug("git.output", cmd=cmd[-1], output=result.stdout.strip())


def _drop_from_enabled_plugins(settings_path: Path) -> None:
    """Remove _PLUGIN_KEY from enabledPlugins in a settings file (silent if absent)."""
    if not settings_path.is_file():
        return
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    enabled = data.get("enabledPlugins")
    if not isinstance(enabled, dict):
        return
    if _PLUGIN_KEY not in enabled:
        return
    del enabled[_PLUGIN_KEY]
    _write_json(settings_path, data)


def _drop_from_installed_plugins() -> None:
    """Remove _PLUGIN_KEY entry from installed_plugins.json."""
    if not _INSTALLED_PLUGINS_JSON.is_file():
        return
    data = _read_json(_INSTALLED_PLUGINS_JSON)
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        return
    if _PLUGIN_KEY not in plugins:
        return
    del plugins[_PLUGIN_KEY]
    _write_json(_INSTALLED_PLUGINS_JSON, data)


def _find_cache_dir(version: str) -> Path | None:
    """Return ``<_CACHE_BASE>/<version>/`` if it exists."""
    candidate = _CACHE_BASE / version
    return candidate if candidate.is_dir() else None


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


@app.command()
def update(
    marketplace_dir: Annotated[
        Path,
        typer.Option(
            "--marketplace-dir",
            help="Path to the marketplace git clone.",
        ),
    ] = _DEFAULT_MARKETPLACE_DIR,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Refresh marketplace clone and upgrade plugin cache when version drifts."""
    configure_runner_logging(verbose=verbose)

    if not marketplace_dir.is_dir():
        typer.echo(
            f"paper-wiki marketplace clone not found at {marketplace_dir}\n"
            "Run: git clone https://github.com/kaneyxx/paper-wiki "
            f"{marketplace_dir}",
            err=True,
        )
        raise typer.Exit(2)

    # Pull latest
    _git_pull(marketplace_dir)

    marketplace_ver = _marketplace_version(marketplace_dir)
    if not marketplace_ver:
        typer.echo(
            f"paper-wiki: could not read marketplace version from {marketplace_dir}",
            err=True,
        )
        raise typer.Exit(1)

    cache_ver = _cache_version()

    if cache_ver == marketplace_ver:
        typer.echo(f"paper-wiki is already at {marketplace_ver}")
        return

    # Versions differ — perform upgrade.
    old_cache_dir = _find_cache_dir(cache_ver) if cache_ver else None
    bak_suffix = ""
    if old_cache_dir is not None and cache_ver:
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        bak_name = f"{cache_ver}.bak.{ts}"
        bak_path = old_cache_dir.parent / bak_name
        try:
            old_cache_dir.rename(bak_path)
            bak_suffix = f"\n(cache backed up to {bak_name})"
        except OSError as exc:
            typer.echo(f"paper-wiki: could not rename cache dir: {exc}", err=True)
            raise typer.Exit(1) from exc

    _drop_from_installed_plugins()
    _drop_from_enabled_plugins(_SETTINGS_JSON)
    _drop_from_enabled_plugins(_SETTINGS_LOCAL_JSON)

    # Task 9.33 / D-9.33.2: auto-prune old .bak directories per
    # PAPERWIKI_BAK_KEEP retention. Default 3 keeps current cache + 2
    # rollback targets. PAPERWIKI_BAK_KEEP=0 = skip auto-prune (escape
    # hatch for power users who manage .bak themselves).
    bak_summary = ""
    keep_recent = _resolve_bak_keep()
    if keep_recent > 0:
        prune_report = _gc_bak_run(
            _CACHE_BASE,
            keep_recent=keep_recent,
            dry_run=False,
        )
        if prune_report.removed:
            bak_summary = (
                f"\n(removed {len(prune_report.removed)} old .bak "
                f"directories; kept {len(prune_report.kept)} most recent)"
            )

    old_display = cache_ver if cache_ver else "not installed"
    typer.echo(
        f"paper-wiki: {old_display} → {marketplace_ver}"
        + bak_suffix
        + bak_summary
        + "\n"
        + "\nNext:"
        + "\n  1. Exit any running session: /exit (or Ctrl-D)"
        + "\n  2. Open a fresh session: claude"
        + "\n  3. Inside: /plugin install paper-wiki@paper-wiki"
    )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    marketplace_dir: Annotated[
        Path,
        typer.Option(
            "--marketplace-dir",
            help="Path to the marketplace git clone.",
        ),
    ] = _DEFAULT_MARKETPLACE_DIR,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Print a 3-line state report (cache / marketplace / enabledPlugins)."""
    configure_runner_logging(verbose=verbose)

    cache_ver = _cache_version() or "(not in installed_plugins.json)"
    marketplace_ver = _marketplace_version(marketplace_dir) or "(marketplace clone not found)"

    settings_data = _read_json(_SETTINGS_JSON)
    settings_local_data = _read_json(_SETTINGS_LOCAL_JSON)

    def _is_enabled(data: dict[str, object]) -> bool:
        enabled = data.get("enabledPlugins")
        return isinstance(enabled, dict) and _PLUGIN_KEY in enabled

    enabled_in_settings = _is_enabled(settings_data)
    enabled_in_local = _is_enabled(settings_local_data)

    typer.echo(f"cache version    : {cache_ver}")
    typer.echo(f"marketplace ver  : {marketplace_ver}")
    typer.echo(
        f"enabledPlugins   : settings.json={'yes' if enabled_in_settings else 'no'}"
        f"  settings.local.json={'yes' if enabled_in_local else 'no'}"
    )

    # Task 9.33: 4th line surfaces the .bak retention state at a glance.
    bak_count, oldest_ts = _summarize_bak_state(_CACHE_BASE)
    if bak_count == 0:
        bak_line = "no backups"
    else:
        bak_line = f"{bak_count} kept; oldest {oldest_ts or 'unknown'}"
    typer.echo(f"bak directories  : {bak_line}")


def _summarize_bak_state(cache_root: Path) -> tuple[int, str | None]:
    """Return (count, oldest_timestamp) for .bak directories under cache_root.

    Used by ``paperwiki status`` to show retention state at a glance.
    Returns ``(0, None)`` when the cache root is missing or empty.
    """
    if not cache_root.is_dir():
        return (0, None)
    matches: list[str] = [
        entry.name
        for entry in cache_root.iterdir()
        if entry.is_dir() and BAK_FILENAME_RE.match(entry.name)
    ]
    if not matches:
        return (0, None)
    matches.sort()
    # The oldest is the lexicographically smallest .bak.<ts> when sorted asc.
    oldest = matches[0]
    # Extract YYYY-MM-DD from the YYYYMMDDTHHMMSSZ suffix for readability.
    suffix = oldest.split(".bak.", 1)[-1] if ".bak." in oldest else None
    if suffix and len(suffix) >= 8:
        oldest_human = f"{suffix[:4]}-{suffix[4:6]}-{suffix[6:8]}"
    else:
        oldest_human = oldest
    return (len(matches), oldest_human)


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------


@app.command()
def uninstall(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Remove cache dir and JSON entries cleanly (what /plugin uninstall should do)."""
    configure_runner_logging(verbose=verbose)

    cache_ver = _cache_version()
    if cache_ver:
        cache_dir = _find_cache_dir(cache_ver)
        if cache_dir is not None:
            import shutil

            try:
                shutil.rmtree(cache_dir)
                typer.echo(f"removed cache: {cache_dir}")
            except OSError as exc:
                typer.echo(f"paper-wiki: could not remove cache dir: {exc}", err=True)
                raise typer.Exit(1) from exc

    _drop_from_installed_plugins()
    _drop_from_enabled_plugins(_SETTINGS_JSON)
    _drop_from_enabled_plugins(_SETTINGS_LOCAL_JSON)

    typer.echo("paper-wiki uninstalled (JSON entries cleared).")
    typer.echo("Open a fresh claude session and run: /plugin install paper-wiki@paper-wiki")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:  # pragma: no cover — thin wrapper
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover — supports `python -m paperwiki.cli`
    main()


__all__ = ["app", "main"]
