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

import contextlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

from paperwiki import __version__ as _PAPERWIKI_VERSION  # noqa: N812 — module constant alias
from paperwiki._internal.health import check_install_health as _shared_check_install_health
from paperwiki._internal.logging import configure_runner_logging
from paperwiki._internal.paths import (
    resolve_paperwiki_bak_dir,
    resolve_paperwiki_venv_dir,
)
from paperwiki.runners.diag import render_diag as _render_diag
from paperwiki.runners.diagnostics import main as _diagnostics_main
from paperwiki.runners.digest import main as _digest_main
from paperwiki.runners.doctor import (
    format_doctor_json as _format_doctor_json,
)
from paperwiki.runners.doctor import (
    format_doctor_pretty as _format_doctor_pretty,
)
from paperwiki.runners.doctor import (
    run_doctor as _run_doctor,
)
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
from paperwiki.runners.wiki_graph_query import main as _wiki_graph_query_main
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
app.command(name="wiki-graph")(_wiki_graph_query_main)
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
    """Best-effort fetch + pull --ff-only inside the marketplace clone.

    v0.3.40 D-9.40.4: changed from strict-fail to best-effort. Failure
    modes — non-zero exit, ``FileNotFoundError`` (git binary missing),
    ``TimeoutExpired`` — are logged at WARN level but DO NOT raise.
    The caller falls through to use the on-disk clone (same outcome as
    if the upstream had no new commits). 10-second timeout per
    subprocess guards against hanging on dead connections.

    Rationale (R3 in plan §17.4): an offline first-install or a corrupt
    marketplace clone shouldn't abort ``paperwiki update`` — the
    self-heal path can still bootstrap from the on-disk clone, and the
    user sees the WARN log explaining why the pull was skipped.
    """
    for cmd in (
        ["git", "-C", str(marketplace_dir), "fetch", "--tags"],
        ["git", "-C", str(marketplace_dir), "pull", "--ff-only"],
    ):
        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning(
                "paperwiki update: marketplace git command skipped "
                "({cmd}): {exc}; using on-disk clone",
                cmd=" ".join(cmd[3:]),
                exc=exc,
            )
            continue
        if result.returncode != 0:
            logger.warning(
                "paperwiki update: marketplace git command failed "
                "({cmd}, exit {rc}): {stderr}; using on-disk clone",
                cmd=" ".join(cmd[3:]),
                rc=result.returncode,
                stderr=result.stderr.strip() or "(no stderr)",
            )
            continue
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


# v0.3.43 D-9.43.2: legacy ``.bak`` filenames live under the plugin cache
# subdir as ``<ver>.bak.<UTC-ts>/``. Match the same shape gc_bak uses
# (``BAK_FILENAME_RE`` in ``runners.gc_bak``) so we never confuse a
# user-added directory with an old paperwiki backup.
_LEGACY_BAK_FILENAME_RE = re.compile(r"^\d+\.\d+\.\d+\.bak\.\d{8}T\d{6}Z$")


def _migrate_legacy_bak(cache_base: Path, bak_root: Path) -> None:
    """Move ``<cache>/<ver>.bak.<ts>/`` into ``<bak_root>/<ver>.bak.<ts>/``.

    v0.3.43 D-9.43.2 migration helper. v0.3.42 wrote ``.bak`` under the
    plugin cache subdir; v0.3.43 relocates them outside cache so they
    survive ``/plugin install``. This helper runs at the top of
    ``paperwiki update`` apply mode and idempotently relocates any
    legacy backups.

    Behavior:

    - Missing ``cache_base`` → no-op (no backups to migrate).
    - Each ``<ver>.bak.<ts>/`` matching the canonical regex is moved
      via ``shutil.move`` (cross-filesystem-safe).
    - Collisions (same name already at ``bak_root``) are skipped with
      a warn-log; never overwrites the existing target.
    - ``shutil.move`` failures (permissions, filesystem read-only) are
      logged at WARN; the migration loop continues with the next entry.

    Idempotent — second invocation finds nothing legacy to migrate.
    """
    if not cache_base.is_dir():
        return
    bak_root.mkdir(parents=True, exist_ok=True)
    for entry in sorted(cache_base.iterdir()):
        if not entry.is_dir():
            continue
        if not _LEGACY_BAK_FILENAME_RE.match(entry.name):
            continue
        target = bak_root / entry.name
        if target.exists():
            logger.warning(
                "paperwiki update: legacy .bak migration collision; preserving "
                "{target} and leaving source at {source}",
                target=target,
                source=entry,
            )
            continue
        try:
            shutil.move(str(entry), str(target))
            logger.info(
                "paperwiki update: migrated legacy .bak {name} from cache to {target}",
                name=entry.name,
                target=target,
            )
        except OSError as exc:
            logger.warning(
                "paperwiki update: failed to migrate {source}: {exc}; leaving in cache",
                source=entry,
                exc=exc,
            )


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def _consume_rc_just_added_stamp() -> None:
    """Surface the first-run rc-edit message and delete the stamp.

    v0.3.42 9.141 / D-9.42.2. ``hooks/ensure-env.sh`` writes
    ``$HELPER_DIR/.rc-just-added`` containing the rc-file path the
    first time it adds the auto-source block. ``paperwiki update``
    reads + deletes the stamp so the user sees exactly one note about
    the edit. Defensive: missing / unreadable stamp = silent no-op.

    The stamp path is computed lazily via ``Path.home()`` so tests can
    monkeypatch HOME before invoking ``paperwiki update`` and have
    their fixture stamps picked up.
    """
    stamp = Path.home() / ".local" / "lib" / "paperwiki" / ".rc-just-added"
    if not stamp.is_file():
        return
    try:
        rc_path = stamp.read_text(encoding="utf-8").strip()
    except OSError:
        rc_path = ""
    # Best-effort delete; the message has already been computed.
    with contextlib.suppress(OSError):
        stamp.unlink(missing_ok=True)
    if rc_path:
        typer.echo(
            f"Added auto-source line to {rc_path} — open a new terminal "
            "or run `source <rc-file>` to use paperwiki_diag now."
        )


def _print_update_check_plan(
    *,
    marketplace_ver: str,
    cache_ver: str | None,
    cache_empty: bool,
    mid_upgrade: bool,
) -> None:
    """Print the ``paperwiki update --check`` preview output.

    v0.3.42 9.142 / D-9.42.5. Pure-print helper, no side effects.
    Output shape:

      plan: <state-summary>
        → <action 1 (always emitted via "would")>
        → <action 2>
      Note: ...
      nothing applied — re-run without --check to apply.
    """
    if mid_upgrade:
        # 9.143 hint takes priority — user is mid-upgrade, they should
        # finish that first before inspecting drift.
        typer.echo(
            "plan: paper-wiki appears to be mid-upgrade — restart "
            "Claude Code and run /plugin install paper-wiki@paper-wiki "
            "to complete."
        )
        typer.echo("nothing applied — re-run without --check to apply.")
        return

    if cache_empty:
        typer.echo(f"plan: cache is empty — would self-heal from marketplace at v{marketplace_ver}")
        typer.echo("nothing applied — re-run without --check to apply.")
        return

    if cache_ver == marketplace_ver:
        typer.echo(f"plan: paper-wiki is already at {marketplace_ver} — no action needed")
        return

    old_display = cache_ver if cache_ver else "not installed"
    bak_root = resolve_paperwiki_bak_dir()
    typer.echo(
        f"plan: would upgrade {old_display} → {marketplace_ver}\n"
        f"  → would move cache dir {old_display} to "
        f"{bak_root}/{old_display}.bak.<UTC-timestamp>\n"
        "  → would drop paper-wiki entry from installed_plugins.json\n"
        "  → would drop paper-wiki from settings.json enabledPlugins\n"
        f"Note: .bak directories live at {bak_root} and survive /plugin install.\n"
        "nothing applied — re-run without --check to apply."
    )


def _cache_in_mid_upgrade_state(cache_base: Path, recorded_ver: str | None) -> bool:
    """Return True when installed_plugins.json points at a vX whose cache
    dir is gone but ``vX.bak.*`` directories remain.

    v0.3.42 9.143 / D-9.42.5 helper. Used by ``paperwiki update`` (both
    apply mode and ``--check`` mode) to surface a "you appear to be
    mid-upgrade" hint to users who ran ``paperwiki update`` but forgot
    to follow the TWO-restart guidance.
    """
    if not recorded_ver:
        return False
    if not cache_base.is_dir():
        return False
    if (cache_base / recorded_ver).is_dir():
        return False  # vX still present — not mid-upgrade
    bak_pattern = f"{recorded_ver}.bak."
    return any(p.name.startswith(bak_pattern) for p in cache_base.iterdir() if p.is_dir())


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
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help=(
                "Dry run: print planned actions without applying any "
                "filesystem mutations. Useful for previewing upgrades "
                "before committing."
            ),
        ),
    ] = False,
) -> None:
    """Refresh marketplace clone and upgrade plugin cache when version drifts."""
    configure_runner_logging(verbose=verbose)

    # v0.3.43 D-9.43.4: ``_consume_rc_just_added_stamp()`` was previously
    # called HERE (top of update()), which printed the rc-edit note
    # BEFORE the plan/result. Reading order should be plan → side-note,
    # not side-note → plan. The call is now made at the END of each
    # branch (--check exit, apply-mode end) so the rc-edit hint appears
    # after the user has read the primary result.

    if not marketplace_dir.is_dir():
        typer.echo(
            f"paper-wiki marketplace clone not found at {marketplace_dir}\n"
            "Run: git clone https://github.com/kaneyxx/paper-wiki "
            f"{marketplace_dir}",
            err=True,
        )
        raise typer.Exit(2)

    # Pull latest. v0.3.42 D-9.42.5: skip in --check mode so the dry
    # run doesn't perform any network I/O (matches the user's
    # expectation that --check is a pure preview).
    if not check:
        _git_pull(marketplace_dir)

    marketplace_ver = _marketplace_version(marketplace_dir)
    if not marketplace_ver:
        typer.echo(
            f"paper-wiki: could not read marketplace version from {marketplace_dir}",
            err=True,
        )
        raise typer.Exit(1)

    # v0.3.42 D-9.42.5: --check exits here after printing the preview.
    # The remainder of this function is the apply-mode body.
    if check:
        cache_ver_for_check = _cache_version()
        cache_empty = not _cache_has_any_version(_CACHE_BASE)
        mid_upgrade = _cache_in_mid_upgrade_state(_CACHE_BASE, cache_ver_for_check)
        _print_update_check_plan(
            marketplace_ver=marketplace_ver,
            cache_ver=cache_ver_for_check,
            cache_empty=cache_empty,
            mid_upgrade=mid_upgrade,
        )
        # v0.3.43 D-9.43.4: rc-edit note appears AFTER the plan, not before.
        _consume_rc_just_added_stamp()
        return

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

    # v0.3.42 9.143 / D-9.42.5: surface a "between steps" hint when the
    # apply path detects the user ran update but didn't finish the
    # upgrade flow (cache contains only .bak.<ts> for the recorded ver).
    if _cache_in_mid_upgrade_state(_CACHE_BASE, cache_ver):
        typer.echo(
            "paper-wiki: you appear to be mid-upgrade — restart Claude "
            "Code and run /plugin install paper-wiki@paper-wiki to "
            "complete."
        )

    # v0.3.44 D-9.44.1: migrate any legacy in-cache .bak directories
    # BEFORE the no-op-return gate. v0.3.43 only ran this inside the
    # upgrade branch (when versions differed), so users who upgraded
    # via the v0.3.42 binary (which wrote .bak in-cache) had no
    # automatic migration path — the in-cache .bak stayed forever or
    # got eaten by the next /plugin install. Now migration runs
    # unconditionally as a one-time housekeeping pass; idempotent
    # when there's nothing to migrate.
    bak_root = resolve_paperwiki_bak_dir()
    _migrate_legacy_bak(_CACHE_BASE, bak_root)

    if cache_ver == marketplace_ver:
        typer.echo(f"paper-wiki is already at {marketplace_ver}")
        # v0.3.43 D-9.43.4: rc-edit note appears AFTER the result line.
        _consume_rc_just_added_stamp()
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
        # v0.3.43 D-9.43.2: write .bak outside the plugin cache subdir
        # so it survives /plugin install. ``shutil.move`` handles
        # cross-filesystem renames (rename(2) fails on EXDEV when
        # ``~/.local/share`` is on a different mount).
        bak_root.mkdir(parents=True, exist_ok=True)
        bak_path = bak_root / bak_name
        try:
            shutil.move(str(old_cache_dir), str(bak_path))
            bak_suffix = f"\n(cache backed up to {bak_path})"
        except OSError as exc:
            typer.echo(f"paper-wiki: could not move cache dir: {exc}", err=True)
            raise typer.Exit(1) from exc

    _drop_from_installed_plugins()
    _drop_from_enabled_plugins(_SETTINGS_JSON)
    _drop_from_enabled_plugins(_SETTINGS_LOCAL_JSON)

    # Task 9.33 / D-9.33.2: auto-prune old .bak directories per
    # PAPERWIKI_BAK_KEEP retention. Default 3 keeps current cache + 2
    # rollback targets. PAPERWIKI_BAK_KEEP=0 = skip auto-prune (escape
    # hatch for power users who manage .bak themselves).
    # v0.3.43 D-9.43.2: scan the new bak root, not the in-cache location.
    bak_summary = ""
    keep_recent = _resolve_bak_keep()
    if keep_recent > 0:
        prune_report = _gc_bak_run(
            bak_root,
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
    #
    # v0.3.41 D-9.41.1 / v0.3.43 D-9.43.2: ``.bak`` directories now live
    # at ``~/.local/share/paperwiki/bak/`` (outside Claude Code's plugin
    # cache subdir) so they survive the next ``/plugin install``. The
    # v0.3.41 "cleared by /plugin install" warning no longer applies —
    # rollback access is durable. Old in-cache backups are migrated by
    # ``_migrate_legacy_bak`` at the top of this function.
    typer.echo(
        f"paper-wiki: {old_display} → {marketplace_ver}"
        + bak_suffix
        + bak_summary
        + "\n"
        + f"\nNote: .bak directories live at {bak_root} and survive /plugin install."
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

    # v0.3.43 D-9.43.4: rc-edit note appears AFTER the upgrade summary +
    # Next: block, not before. Consume-once semantics preserved (the
    # stamp is deleted after the message is printed).
    _consume_rc_just_added_stamp()


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
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Exit 1 if any install-health row is unhealthy "
            "(opt-in; default exits 0 regardless).",
        ),
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
    # v0.3.43 D-9.43.2: scan the new bak root (outside cache); print the
    # location so users know where to look for rollback targets.
    bak_root = resolve_paperwiki_bak_dir()
    bak_count, oldest_ts = _summarize_bak_state(bak_root)
    if bak_count == 0:
        bak_line = f"no backups  (location: {bak_root})"
    else:
        bak_line = f"{bak_count} kept; oldest {oldest_ts or 'unknown'}  (location: {bak_root})"
    typer.echo(f"bak directories  : {bak_line}")

    # v0.3.40 Task 9.114 / D-9.40.1: install-health check.
    # Pushes the source-or-die contract from SKILL prose down to the
    # runner layer per the v0.3.39 §15.4 R1 retro. Status command stays
    # exit-0 in all healthy/unhealthy combinations — warnings are loud
    # but non-fatal so automation that pipes status output isn't broken
    # by helper-state issues.
    health_rows = _check_install_health()
    healthy = sum(1 for _label, ok, _hint in health_rows if ok)
    typer.echo(f"install health   : {healthy}/{len(health_rows)} healthy")
    for label, ok, hint in health_rows:
        if ok:
            typer.echo(f"  ✓ {label}")
        else:
            typer.echo(f"  ✗ {label}  (action: {hint})")

    # v0.3.41 D-9.41.2: opt-in strict mode flips exit code to 1 when any
    # health row is ✗. Default (no --strict) preserves the v0.3.40 D-9.40.1
    # warn-not-error contract — automation that pipes status output without
    # the flag is unaffected.
    if strict and healthy < len(health_rows):
        raise typer.Exit(1)


# v0.3.43 D-9.43.3: install-health logic moved to
# ``paperwiki._internal.health`` so ``paperwiki doctor`` can reuse it
# without an import cycle. The thin wrapper below preserves the
# zero-argument call site used by ``paperwiki status``.


def _check_install_health() -> list[tuple[str, bool, str | None]]:
    """Return ``[(label, ok, action_hint)]`` for the 4 install-health checks.

    Thin wrapper around ``paperwiki._internal.health.check_install_health``
    that pre-fills ``home`` from ``Path.home()``, the expected version
    from ``paperwiki.__version__``, and ``path_env`` from
    ``os.environ`` so existing call sites in this module need no changes.
    """
    return _shared_check_install_health(
        home=Path.home(),
        expected_version=_PAPERWIKI_VERSION,
        path_env=os.environ.get("PATH"),
    )


def _summarize_bak_state(bak_root: Path) -> tuple[int, str | None]:
    """Return (count, oldest_timestamp) for .bak directories under ``bak_root``.

    Used by ``paperwiki status`` to show retention state at a glance.
    Returns ``(0, None)`` when the directory is missing or empty.

    v0.3.43 D-9.43.2: ``bak_root`` is the post-relocation backup
    directory (``~/.local/share/paperwiki/bak`` by default, overridable
    via ``PAPERWIKI_BAK_DIR``), no longer the in-cache subdir.
    """
    if not bak_root.is_dir():
        return (0, None)
    matches: list[str] = [
        entry.name
        for entry in bak_root.iterdir()
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
# diag — v0.3.42 D-9.42.1
# ---------------------------------------------------------------------------


@app.command()
def diag(
    file: Annotated[
        bool,
        typer.Option(
            "--file",
            help=(
                "Write diag to a file instead of stdout. Pair with a "
                "positional PATH for an explicit destination, or pass "
                "--file alone to use $HOME/paper-wiki-diag-<UTC-ts>.txt."
            ),
        ),
    ] = False,
    path: Annotated[
        Path | None,
        typer.Argument(
            help=(
                "Output file path (with --file). Omit to write to "
                "$HOME/paper-wiki-diag-<UTC-timestamp>.txt."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Print install-state diagnostic dump.

    v0.3.42 D-9.42.1: CLI parity with the ``paperwiki_diag`` bash
    function defined in ``lib/bash-helpers.sh``. The bash form requires
    sourcing the helper first; the CLI form works in any fresh shell
    via ``$HOME/.local/bin/paperwiki``.

    Modes:

    - ``paperwiki diag``                — print to stdout (default)
    - ``paperwiki diag --file``        — write to ``$HOME/paper-wiki-diag-<UTC-ts>.txt``
    - ``paperwiki diag --file PATH``   — write to PATH (parent dirs created)

    Output is **safe to share**: prints PATH, helper version tag, shim
    first lines, ``ls -1`` of cache + recipes, and the paper-wiki entry
    from ``installed_plugins.json``. Never prints secrets.env content.
    """
    configure_runner_logging(verbose=verbose)

    home = Path.home()
    claude_home = home / ".claude"
    dump = _render_diag(
        home=home,
        claude_home=claude_home,
        path_env=os.environ.get("PATH"),
        plugin_root=os.environ.get("CLAUDE_PLUGIN_ROOT"),
    )

    # Mode resolution: explicit path > --file alone (default path) > stdout.
    output_path: Path | None
    if path is not None:
        output_path = path
    elif file:
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        output_path = home / f"paper-wiki-diag-{ts}.txt"
    else:
        output_path = None

    if output_path is None:
        typer.echo(dump, nl=False)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump, encoding="utf-8")
    typer.echo(f"wrote diag to {output_path}")


# ---------------------------------------------------------------------------
# doctor — v0.3.43 D-9.43.3
# ---------------------------------------------------------------------------


@app.command()
def doctor(
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit a structured JSON report instead of the pretty "
                "multi-section output. Useful for CI/automation."
            ),
        ),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help=(
                "Exit 1 when any health row is unhealthy (default exits "
                "0 regardless — pipe-friendly)."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """One-command install health check.

    Aggregates v0.3.42's separate probes (status / diag / venv) behind a
    single command. Sections shown:

    - **Cache & marketplace** — installed version, marketplace version,
      enabledPlugins state.
    - **Install integrity** — helper / shim presence + version-tag match,
      ``~/.local/bin`` on PATH (shared with ``paperwiki status``).
    - **Python venv** — venv at ``$PAPERWIKI_VENV_DIR``, python runs,
      ``paperwiki`` module importable (subprocess probe with 5s timeout).
    - **Shell-rc integration** — auto-source block present in the
      detected rc file (n/a for fish/csh and for opt-out via
      ``PAPERWIKI_NO_RC_INTEGRATION=1``).

    The ``--json`` schema is ``@experimental`` until v0.4 — see CHANGELOG.
    """
    configure_runner_logging(verbose=verbose)

    home = Path.home()
    claude_home = home / ".claude"
    bak_root = resolve_paperwiki_bak_dir()
    venv_dir = resolve_paperwiki_venv_dir()
    marketplace_dir = _DEFAULT_MARKETPLACE_DIR
    shell = os.environ.get("SHELL")
    path_env = os.environ.get("PATH")
    rc_disabled = os.environ.get("PAPERWIKI_NO_RC_INTEGRATION") == "1"

    report = _run_doctor(
        home=home,
        claude_home=claude_home,
        bak_root=bak_root,
        venv_dir=venv_dir,
        marketplace_dir=marketplace_dir,
        shell=shell,
        path_env=path_env,
        expected_version=_PAPERWIKI_VERSION,
        rc_integration_disabled=rc_disabled,
    )

    if json_mode:
        typer.echo(_format_doctor_json(report))
    else:
        typer.echo(_format_doctor_pretty(report), nl=False)

    if strict and report.healthy < report.total:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:  # pragma: no cover — thin wrapper
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover — supports `python -m paperwiki.cli`
    main()


__all__ = ["app", "main"]
