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
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from paperwiki._internal.logging import configure_runner_logging
from paperwiki._internal.paths import resolve_paperwiki_venv_dir
from paperwiki.runners.diagnostics import main as _diagnostics_main
from paperwiki.runners.digest import main as _digest_main
from paperwiki.runners.extract_paper_images import main as _extract_images_main
from paperwiki.runners.gc_bak import (
    BAK_FILENAME_RE,
)
from paperwiki.runners.gc_bak import (
    _resolve_default_keep_recent as _resolve_bak_keep,
)
from paperwiki.runners.gc_bak import (
    gc_bak as _gc_bak_run,
)
from paperwiki.runners.gc_bak import (
    main as _gc_bak_main,
)
from paperwiki.runners.gc_digest_archive import main as _gc_archive_main
from paperwiki.runners.migrate_recipe import main as _migrate_recipe_main
from paperwiki.runners.migrate_sources import main as _migrate_sources_main
from paperwiki.runners.uninstall import (
    UninstallOpts,
)
from paperwiki.runners.uninstall import (
    uninstall as _uninstall_run,
)
from paperwiki.runners.where import main as _where_main
from paperwiki.runners.wiki_compile import main as _wiki_compile_main
from paperwiki.runners.wiki_ingest_plan import main as _wiki_ingest_main
from paperwiki.runners.wiki_lint import main as _wiki_lint_main
from paperwiki.runners.wiki_query import main as _wiki_query_main

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
# corresponding ``paperwiki.runners.<name>.main`` callable directly via
# ``app.command(name=...)(...)`` rather than ``add_typer`` — the latter wraps
# the sub-app in a click.Group that requires a sub-command, which broke
# ``paperwiki <name>`` invocations (Task 9.29 / v0.3.27 regression caught
# in v0.3.30 user smoke). Each runner module still ships its own standalone
# Typer app for ``python -m paperwiki.runners.<name>`` invocation; this file
# only re-uses the ``main`` callable as a parent-app command.
app.command(name="migrate-recipe")(_migrate_recipe_main)
app.command(name="digest")(_digest_main)
app.command(name="wiki-ingest")(_wiki_ingest_main)
app.command(name="wiki-lint")(_wiki_lint_main)
app.command(name="wiki-compile")(_wiki_compile_main)
app.command(name="wiki-query")(_wiki_query_main)
app.command(name="extract-images")(_extract_images_main)
app.command(name="migrate-sources")(_migrate_sources_main)
app.command(name="gc-archive")(_gc_archive_main)
app.command(name="gc-bak")(_gc_bak_main)
app.command(name="where")(_where_main)
# Task 9.59 (v0.3.34): expose `paperwiki diagnostics` so the setup and
# bio-search SKILLs can use the shim consistently. The runner module
# uses `@app.callback()` for its own standalone `python -m
# paperwiki.runners.diagnostics` entrypoint; the same callable doubles
# as a parent-app subcommand here without modification.
app.command(name="diagnostics")(_diagnostics_main)

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


def _uninstall_stale_editable_paperwiki() -> None:
    """Uninstall ``paperwiki`` from the shared venv before cache rename.

    Task v0.3.31-B. The shared venv at ``${PAPERWIKI_VENV_DIR}`` carries
    an editable install of ``paperwiki`` whose ``.pth`` file references
    ``<cache>/<current-ver>/src``. When ``paperwiki update`` renames
    that cache dir to ``.bak.<ts>``, the ``.pth`` path becomes stale —
    next ``paperwiki <X>`` invocation hits
    ``ModuleNotFoundError: No module named 'paperwiki'`` until the
    SessionStart re-runs ``ensure-env.sh`` against the new cache.

    Pre-rename uninstall removes the stale ``.pth`` cleanly so the
    re-install on next SessionStart is the only source of truth. The
    shim's ``PYTHONPATH`` fallback (v0.3.31-A) covers the runtime gap
    in case this uninstall is skipped (no venv, missing pip, etc).

    Best-effort: any failure is silently absorbed — we do NOT block
    the upgrade flow on this housekeeping step.
    """
    venv_dir = resolve_paperwiki_venv_dir()
    venv_python = venv_dir / "bin" / "python"
    if not venv_python.is_file():
        return  # No venv yet — nothing to uninstall.

    # v0.3.32: prefer `uv pip uninstall` because uv-created venvs ship
    # WITHOUT pip by default (uv philosophy: use `uv pip` not pip
    # directly). Falling straight to `python -m pip uninstall` was a
    # silent skip on uv users — Prong B effectively dead. Try uv first,
    # fall back to python -m pip for venvs created by ensurepip /
    # virtualenv.
    cmd: list[str] | None
    if shutil.which("uv"):
        cmd = ["uv", "pip", "uninstall", "--python", str(venv_python), "paperwiki"]
    else:
        cmd = [str(venv_python), "-m", "pip", "uninstall", "paperwiki", "-y"]
    try:
        subprocess.run(  # noqa: S603 — args are literal + resolved path
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        logger.debug("paperwiki_update.uninstall_skipped", error=str(exc))


def _find_cache_dir(version: str) -> Path | None:
    """Return ``<_CACHE_BASE>/<version>/`` if it exists."""
    candidate = _CACHE_BASE / version
    return candidate if candidate.is_dir() else None


# v0.3.39 D-9.39.1: cache "is empty" means no version subdir at all.
# Strict version-only regex — ``.bak.<ts>`` etc. are NOT versions.
_VERSION_DIR_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _cache_has_any_version(cache_base: Path) -> bool:
    """Return True if ``cache_base`` contains at least one version subdir.

    Used by ``paperwiki update`` to gate the self-heal path
    (D-9.39.1). Treats ``.bak.<ts>`` and other non-version names as
    "not a version" — strict ``\\d+\\.\\d+\\.\\d+`` match only. The
    cache base not existing at all also counts as "no version".
    """
    if not cache_base.is_dir():
        return False
    return any(d.is_dir() and _VERSION_DIR_RE.match(d.name) for d in cache_base.iterdir())


def _self_heal_from_marketplace(
    marketplace_dir: Path,
    cache_base: Path,
    version: str,
) -> None:
    """Bootstrap an empty cache by copying the marketplace clone whole-sale.

    Per v0.3.39 D-9.39.1: when ``_cache_has_any_version(cache_base)`` is
    False, this fills the gap so the rest of the update flow has
    something to base on. Copies ``marketplace_dir`` to
    ``cache_base / version`` byte-for-byte (including ``.git``, mirroring
    a manual ``cp -R``). No-op if the target dir already exists (race
    safety / idempotency).
    """
    cache_base.mkdir(parents=True, exist_ok=True)
    target = cache_base / version
    if target.exists():
        return
    shutil.copytree(marketplace_dir, target)


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

    # v0.3.39 D-9.39.1 self-heal: when the plugin cache contains no
    # version subdirs (empty dir, or ``.bak.*``-only), bootstrap from
    # the marketplace clone before running the diff-and-sync logic.
    # Catches the dev-workflow corner case where Claude Code's plugin
    # manager half-fails (installed_plugins.json points at a non-
    # existent cache dir) — without this, ``paperwiki update`` would
    # exit "already at vX.Y.Z" while leaving the cache empty.
    if not _cache_has_any_version(_CACHE_BASE):
        _self_heal_from_marketplace(marketplace_dir, _CACHE_BASE, marketplace_ver)
        typer.echo(
            f"paper-wiki: cache was empty — bootstrapped from marketplace at v{marketplace_ver}."
        )

    cache_ver = _cache_version()

    if cache_ver == marketplace_ver:
        typer.echo(f"paper-wiki is already at {marketplace_ver}")
        return

    # Versions differ — perform upgrade.
    # v0.3.31-B: BEFORE renaming the cache dir, uninstall the editable
    # `paperwiki` install from the shared venv. The editable install's
    # .pth file holds an absolute path to <cache>/<old-ver>/src; if we
    # rename without uninstalling first, the .pth points at a path
    # that no longer exists and the next `paperwiki <X>` call hits
    # `ModuleNotFoundError: No module named 'paperwiki'`. The
    # subsequent SessionStart's ensure-env.sh re-runs editable install
    # against the new cache, so this uninstall is purely a cleanup
    # gate. Best-effort: if the uninstall fails (no venv yet, network,
    # permissions), continue with rename — the shim's PYTHONPATH
    # fallback (v0.3.31-A) covers the runtime gap.
    _uninstall_stale_editable_paperwiki()

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
    # v0.3.40 D-9.40.2: 5-step "Next:" message — the upgrade flow needs
    # TWO restart cycles, not one. v0.3.39 user feedback: the 3-step
    # version implied a single restart sufficed, so users hit the
    # half-installed state and reported it as a regression.
    #   restart 1 → /plugin install registers the plugin
    #   restart 2 → SessionStart fires ensure-env.sh which rewrites
    #               the shim and helper to the new version
    typer.echo(
        f"paper-wiki: {old_display} → {marketplace_ver}"
        + bak_suffix
        + bak_summary
        + "\n"
        + "\nNext:"
        + "\n  1. Exit any running session: /exit (or Ctrl-D)"
        + "\n  2. Open a fresh session: claude"
        + "\n  3. Inside: /plugin install paper-wiki@paper-wiki"
        + "\n  4. Exit again: /exit"
        + "\n  5. Open another fresh session: claude"
        + "\n     (SessionStart fires ensure-env.sh against the now-registered"
        + "\n      plugin and rewrites the shim/helper to the new version)"
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
    everything: Annotated[
        bool,
        typer.Option(
            "--everything",
            help=(
                "Also remove the user-controlled ~/.config/paper-wiki/ root, "
                "the ~/.local/bin/paperwiki shim + PATH-warned marker, the "
                "marketplace clone, and the settings.json marketplace entry."
            ),
        ),
    ] = False,
    purge_vault: Annotated[
        Path | None,
        typer.Option(
            "--purge-vault",
            help=(
                "Also remove paperwiki-created files (Daily/, Wiki/, "
                ".digest-archive/, .vault.lock, Welcome.md) under PATH. "
                "Preserves .obsidian/ and any other content not created by "
                "paperwiki. PATH must exist."
            ),
        ),
    ] = None,
    nuke_vault: Annotated[
        bool,
        typer.Option(
            "--nuke-vault",
            help=(
                "Replaces --purge-vault's surgical removal with rm -rf PATH "
                "(everything, including .obsidian/). Requires --purge-vault."
            ),
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompts."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Remove paperwiki state (plugin layer, optionally user config + vault)."""
    configure_runner_logging(verbose=verbose)

    # v0.3.35: orchestration moved to ``paperwiki.runners.uninstall``.
    # The CLI handler is now a thin flag-collector.
    expanded_vault: Path | None = None
    if purge_vault is not None:
        expanded_vault = Path(purge_vault).expanduser().resolve()

    opts = UninstallOpts(
        everything=everything,
        purge_vault=expanded_vault,
        nuke_vault=nuke_vault,
        yes=yes,
        verbose=verbose,
    )
    _uninstall_run(opts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:  # pragma: no cover — thin wrapper
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover — supports `python -m paperwiki.cli`
    main()


__all__ = ["app", "main"]
