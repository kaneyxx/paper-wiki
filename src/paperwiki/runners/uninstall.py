"""``paperwiki.runners.uninstall`` — flag-driven uninstall orchestration.

v0.3.35. Replaces the old ``paperwiki uninstall`` (plugin-layer only)
with a composable, flag-driven flow that can do a full fresh-user
reset in one command. The CLI handler in ``paperwiki.cli`` collects
flags into :class:`UninstallOpts` and delegates here; this module
owns the filesystem orchestration.

Flag composition (see plan / README for full table)::

    paperwiki uninstall                              # plugin layer only
    paperwiki uninstall --everything                 # + config root, shim, marketplace, settings
    paperwiki uninstall --everything --purge-vault PATH       # + vault content (surgical)
    paperwiki uninstall --everything --purge-vault PATH --nuke-vault   # + rm -rf PATH
    paperwiki uninstall --yes                        # skip confirmation prompts
    paperwiki uninstall -v                           # verbose listing

A successful flow is idempotent: re-running after a clean uninstall is
a no-op (each helper checks existence before acting).
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import typer
from loguru import logger

# ---------------------------------------------------------------------------
# Constants — plugin / cache / settings paths.
#
# Computed at module import once; tests monkeypatch the resolver functions
# below (which read these constants) rather than mutating them directly.
# ---------------------------------------------------------------------------

_PLUGIN_NAME = "paper-wiki"
_PLUGIN_KEY = "paper-wiki@paper-wiki"

# Vault-content targets (paperwiki-created files under a user vault).
# Hard-coded — paperwiki creates exactly these paths under a vault root.
# A glob would be cleverer but riskier; this list is auditable.
_VAULT_TARGETS: tuple[str, ...] = (
    "Daily",
    "Wiki",
    ".digest-archive",
    ".vault.lock",
    "Welcome.md",
)


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UninstallOpts:
    """Options for :func:`uninstall`.

    The CLI handler builds one of these from flags and passes it to
    ``uninstall``. Tests construct it directly.
    """

    everything: bool = False
    purge_vault: Path | None = None
    nuke_vault: bool = False
    yes: bool = False
    verbose: bool = False
    # Path overrides for tests.  Production callers leave these None and
    # the resolver functions compute defaults under $HOME / .claude.
    home: Path | None = None
    claude_home: Path | None = None


# ---------------------------------------------------------------------------
# Default-path resolvers — call-site so tests' monkeypatched $HOME applies.
# ---------------------------------------------------------------------------


def _claude_home(opts: UninstallOpts) -> Path:
    return opts.claude_home if opts.claude_home else Path.home() / ".claude"


def _home(opts: UninstallOpts) -> Path:
    return opts.home if opts.home else Path.home()


def _cache_base(opts: UninstallOpts) -> Path:
    return _claude_home(opts) / "plugins" / "cache" / _PLUGIN_NAME / _PLUGIN_NAME


def _installed_plugins_json(opts: UninstallOpts) -> Path:
    return _claude_home(opts) / "plugins" / "installed_plugins.json"


def _settings_json(opts: UninstallOpts) -> Path:
    return _claude_home(opts) / "settings.json"


def _settings_local_json(opts: UninstallOpts) -> Path:
    return _claude_home(opts) / "settings.local.json"


def _config_dir(opts: UninstallOpts) -> Path:
    return _home(opts) / ".config" / _PLUGIN_NAME


def _shim_path(opts: UninstallOpts) -> Path:
    return _home(opts) / ".local" / "bin" / "paperwiki"


def _shim_marker(opts: UninstallOpts) -> Path:
    return _home(opts) / ".local" / "bin" / ".paperwiki-path-warned"


def _marketplace_clone(opts: UninstallOpts) -> Path:
    return _claude_home(opts) / "plugins" / "marketplaces" / _PLUGIN_NAME


# ---------------------------------------------------------------------------
# Targets — the concrete plan a given flag combo produces.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Target:
    """Single removal target shown in the prompt and verbose listing."""

    label: str
    path: Path | None
    kind: str  # "dir", "file", "json-key"
    detail: str = ""
    extra_paths: list[Path] = field(default_factory=list)


def _format_size(size_bytes: int) -> str:
    """Human-friendly byte format. Mirrors ``runners.where._format_size``."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    units = ("KB", "MB", "GB", "TB")
    value = float(size_bytes)
    for unit in units:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PB"


def _dir_size(path: Path) -> int:
    """Recursive byte sum for a directory; 0 on missing or unreadable."""
    if not path.is_dir():
        return 0
    total = 0
    try:
        for entry in path.rglob("*"):
            try:
                if entry.is_file() and not entry.is_symlink():
                    total += entry.stat().st_size
            except OSError:
                continue
    except OSError:
        return 0
    return total


def _path_size(path: Path) -> int:
    if path.is_dir():
        return _dir_size(path)
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    return 0


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _has_installed_plugins_entry(path: Path) -> bool:
    data = _read_json(path)
    plugins = data.get("plugins")
    return isinstance(plugins, dict) and _PLUGIN_KEY in plugins


def _has_enabled_plugins_entry(path: Path) -> bool:
    data = _read_json(path)
    enabled = data.get("enabledPlugins")
    return isinstance(enabled, dict) and _PLUGIN_KEY in enabled


def _has_marketplace_entry(path: Path) -> bool:
    data = _read_json(path)
    extra = data.get("extraKnownMarketplaces")
    return isinstance(extra, dict) and _PLUGIN_NAME in extra


def _drop_installed_plugins_entry(path: Path) -> bool:
    if not path.is_file():
        return False
    data = _read_json(path)
    plugins = data.get("plugins")
    if not isinstance(plugins, dict) or _PLUGIN_KEY not in plugins:
        return False
    del plugins[_PLUGIN_KEY]
    _write_json(path, data)
    return True


def _drop_enabled_plugins_entry(path: Path) -> bool:
    if not path.is_file():
        return False
    data = _read_json(path)
    enabled = data.get("enabledPlugins")
    if not isinstance(enabled, dict) or _PLUGIN_KEY not in enabled:
        return False
    del enabled[_PLUGIN_KEY]
    _write_json(path, data)
    return True


def _drop_marketplace_entry(path: Path) -> bool:
    """Remove ``extraKnownMarketplaces[paper-wiki]`` from a settings file."""
    if not path.is_file():
        return False
    data = _read_json(path)
    extra = data.get("extraKnownMarketplaces")
    if not isinstance(extra, dict) or _PLUGIN_NAME not in extra:
        return False
    del extra[_PLUGIN_NAME]
    _write_json(path, data)
    return True


# ---------------------------------------------------------------------------
# Plan — produce list of targets for the given opts.
# ---------------------------------------------------------------------------


def plan_targets(opts: UninstallOpts) -> list[Target]:
    """Return the ordered list of :class:`Target` for the given opts.

    Only existing things are listed. The list drives both the
    confirmation prompt (when ``yes=False``) and the actual removal.
    """
    targets: list[Target] = []

    cache_base = _cache_base(opts)
    if cache_base.is_dir():
        # Count all version dirs (including .bak) to summarise.
        versions = [c for c in cache_base.iterdir() if c.is_dir()]
        total_bytes = _dir_size(cache_base)
        targets.append(
            Target(
                label="plugin cache",
                path=cache_base,
                kind="dir",
                detail=f"{len(versions)} versions, {_format_size(total_bytes)}",
            )
        )

    installed_json = _installed_plugins_json(opts)
    if _has_installed_plugins_entry(installed_json):
        targets.append(
            Target(
                label=f"{installed_json}: paper-wiki@paper-wiki entry",
                path=installed_json,
                kind="json-key",
                detail="installed_plugins.json",
            )
        )

    settings_json = _settings_json(opts)
    if _has_enabled_plugins_entry(settings_json):
        targets.append(
            Target(
                label=f'{settings_json}: enabledPlugins["paper-wiki@paper-wiki"]',
                path=settings_json,
                kind="json-key",
                detail="settings.json enabledPlugins",
            )
        )

    settings_local = _settings_local_json(opts)
    if _has_enabled_plugins_entry(settings_local):
        targets.append(
            Target(
                label=f'{settings_local}: enabledPlugins["paper-wiki@paper-wiki"]',
                path=settings_local,
                kind="json-key",
                detail="settings.local.json enabledPlugins",
            )
        )

    if opts.everything:
        config_dir = _config_dir(opts)
        if config_dir.is_dir():
            size = _dir_size(config_dir)
            targets.append(
                Target(
                    label="paperwiki config root (recipes, secrets, venv)",
                    path=config_dir,
                    kind="dir",
                    detail=_format_size(size),
                )
            )

        shim = _shim_path(opts)
        marker = _shim_marker(opts)
        extra: list[Path] = [marker] if marker.exists() else []
        if shim.exists() or extra:
            targets.append(
                Target(
                    label="~/.local/bin/paperwiki shim",
                    path=shim if shim.exists() else None,
                    kind="file",
                    detail="+ .paperwiki-path-warned" if extra else "",
                    extra_paths=extra,
                )
            )

        clone = _marketplace_clone(opts)
        if clone.is_dir():
            targets.append(
                Target(
                    label="marketplace clone",
                    path=clone,
                    kind="dir",
                    detail=_format_size(_dir_size(clone)),
                )
            )

        if _has_marketplace_entry(settings_json):
            targets.append(
                Target(
                    label=f"{settings_json}: extraKnownMarketplaces.paper-wiki",
                    path=settings_json,
                    kind="json-key",
                    detail="settings.json extraKnownMarketplaces",
                )
            )

    if opts.purge_vault is not None:
        vault = opts.purge_vault
        if opts.nuke_vault:
            targets.append(
                Target(
                    label=f"vault root (NUKE): {vault}",
                    path=vault,
                    kind="dir",
                    detail=_format_size(_dir_size(vault)),
                )
            )
        else:
            for name in _VAULT_TARGETS:
                candidate = vault / name
                if candidate.exists():
                    kind = "dir" if candidate.is_dir() else "file"
                    size = _path_size(candidate)
                    targets.append(
                        Target(
                            label=f"vault: {name}",
                            path=candidate,
                            kind=kind,
                            detail=_format_size(size),
                        )
                    )

    return targets


# ---------------------------------------------------------------------------
# Apply — perform the removals for a list of targets.
# ---------------------------------------------------------------------------


def _log_removed(label: str, detail: str = "") -> None:
    """Emit an INFO-level "removed: …" line to stderr."""
    msg = f"removed: {label}"
    if detail:
        msg = f"{msg}  ({detail})"
    logger.info(msg)


def apply(targets: list[Target], opts: UninstallOpts) -> int:
    """Remove every :class:`Target` in *targets*.

    Returns the count of targets actually removed (idempotency: missing
    paths are silently no-op'd).
    """
    removed = 0
    for tgt in targets:
        kind = tgt.kind
        path = tgt.path

        if kind == "dir" and path is not None and path.is_dir():
            try:
                shutil.rmtree(path)
            except OSError as exc:
                typer.echo(f"paperwiki uninstall: could not remove {path}: {exc}", err=True)
                raise typer.Exit(1) from exc
            removed += 1
            _log_removed(tgt.label, tgt.detail)
        elif kind == "file" and path is not None and path.exists():
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                typer.echo(f"paperwiki uninstall: could not remove {path}: {exc}", err=True)
                raise typer.Exit(1) from exc
            removed += 1
            _log_removed(tgt.label, tgt.detail)
            for extra in tgt.extra_paths:
                if extra.exists():
                    extra.unlink(missing_ok=True)
        elif kind == "file" and tgt.extra_paths:
            # Only the marker exists (shim was already gone).
            for extra in tgt.extra_paths:
                if extra.exists():
                    extra.unlink(missing_ok=True)
                    removed += 1
                    _log_removed(tgt.label, tgt.detail)
        elif kind == "json-key" and path is not None and path.is_file():
            label = tgt.label
            data = _read_json(path)
            mutated = False
            if "enabledPlugins" in label:
                mutated = _drop_enabled_plugins_entry(path) or mutated
            elif "extraKnownMarketplaces" in label:
                mutated = _drop_marketplace_entry(path) or mutated
            else:
                # installed_plugins.json
                mutated = _drop_installed_plugins_entry(path) or mutated
            # Force re-read; mutation funcs already wrote.
            _ = data
            if mutated:
                removed += 1
                _log_removed(tgt.label, tgt.detail)

    return removed


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def uninstall(opts: UninstallOpts) -> int:
    """Drive the full uninstall flow.

    1. Validate flag combos (--nuke-vault requires --purge-vault).
    2. Validate paths (vault must exist when given).
    3. Build the target plan.
    4. Confirm with user (unless ``--yes``).
    5. Apply.
    6. Report summary.

    Returns the number of targets removed (0 on a true no-op idempotent
    re-run).
    """
    # A6: --nuke-vault requires --purge-vault.
    if opts.nuke_vault and opts.purge_vault is None:
        typer.echo("ERROR: --nuke-vault requires --purge-vault PATH", err=True)
        raise typer.Exit(2)

    # A7: vault path must exist.
    if opts.purge_vault is not None and not opts.purge_vault.exists():
        typer.echo(f"ERROR: vault path does not exist: {opts.purge_vault}", err=True)
        raise typer.Exit(2)

    targets = plan_targets(opts)

    if not targets:
        # A11: idempotent no-op.
        typer.echo("paperwiki: nothing to remove (already clean).")
        return 0

    if not opts.yes:
        typer.echo("The following targets will be removed:")
        for tgt in targets:
            suffix = f" ({tgt.detail})" if tgt.detail else ""
            typer.echo(f"  - {tgt.label}{suffix}")
        typer.echo("")
        if not typer.confirm("Continue?", default=False):
            typer.echo("paperwiki uninstall: aborted.")
            raise typer.Exit(1)

    count = apply(targets, opts)

    # Summary line — always shown, terse by default.
    typer.echo(f"paperwiki uninstall: {count} target(s) removed.")
    if not opts.everything and opts.purge_vault is None:
        typer.echo("Open a fresh claude session and run: /plugin install paper-wiki@paper-wiki")
    return count


__all__ = [
    "Target",
    "UninstallOpts",
    "apply",
    "plan_targets",
    "uninstall",
]


if __name__ == "__main__":  # pragma: no cover — manual debugging only
    sys.exit(0)
