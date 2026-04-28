"""``paperwiki.runners.where`` — print every paperwiki path on disk + sizes.

Task 9.35 / D-9.31.5 (v0.3.29). Replaces the user's mental "where is
everything?" check with one command. Pairs cleanly with `paperwiki
status` (state) and `paperwiki gc-bak` / `paperwiki gc-archive`
(cleanup).

CLI
---
::

    paperwiki where [--json] [-v]

Default output is a human-readable indented tree showing each
paperwiki location with its existence + recursive size + a synthesised
oldest/active version where applicable. ``--json`` emits the same
data as a machine-parseable shape for cron / scripting.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import typer

from paperwiki._internal.logging import configure_runner_logging
from paperwiki._internal.paths import (
    resolve_paperwiki_home,
    resolve_paperwiki_recipes_dir,
    resolve_paperwiki_venv_dir,
)
from paperwiki.runners.gc_bak import BAK_FILENAME_RE

app = typer.Typer(
    add_completion=False,
    help="Print every paperwiki path on disk with sizes.",
    no_args_is_help=False,
)


# ---------------------------------------------------------------------------
# Default-path resolvers (computed at call time, not import time, so test
# monkeypatching of $HOME takes effect).
# ---------------------------------------------------------------------------


def default_cache_root() -> Path:
    return Path.home() / ".claude" / "plugins" / "cache" / "paper-wiki" / "paper-wiki"


def default_marketplace_clone() -> Path:
    return Path.home() / ".claude" / "plugins" / "marketplaces" / "paper-wiki"


def default_shim_path() -> Path:
    return Path.home() / ".local" / "bin" / "paperwiki"


_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


# ---------------------------------------------------------------------------
# Sizing helpers
# ---------------------------------------------------------------------------


def _dir_size_bytes(path: Path) -> int:
    """Return recursive file-size sum for a directory (no symlink follow)."""
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


def _format_size(size_bytes: int) -> str:
    """Format byte count with the largest sensible unit."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    units = ("KB", "MB", "GB", "TB")
    value = float(size_bytes)
    for unit in units:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PB"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PathReport:
    """Per-path summary used by :class:`WhereReport`."""

    label: str
    path: str
    exists: bool
    size_bytes: int
    size_human: str

    @classmethod
    def from_path(cls, path: Path, *, label: str) -> PathReport:
        path_str = str(path)
        if not path.exists():
            return cls(label=label, path=path_str, exists=False, size_bytes=0, size_human="0 B")
        try:
            size = _dir_size_bytes(path) if path.is_dir() else path.stat().st_size
        except OSError:
            size = 0
        return cls(
            label=label,
            path=path_str,
            exists=True,
            size_bytes=size,
            size_human=_format_size(size),
        )


@dataclass(slots=True)
class WhereReport:
    """Aggregate report returned by :func:`build_where_report`."""

    paperwiki_home: PathReport
    recipes_dir: PathReport
    secrets_path: PathReport
    venv_dir: PathReport
    cache_root: PathReport
    cache_active_version: str | None
    cache_bak_versions: list[str]
    marketplace_clone: PathReport
    shim_path: PathReport
    total_disk_used_bytes: int = 0
    total_disk_used_human: str = "0 B"

    def to_json_dict(self) -> dict[str, object]:
        """Serialisable shape with `PathReport` instances flattened."""
        return {
            "paperwiki_home": asdict(self.paperwiki_home),
            "recipes_dir": asdict(self.recipes_dir),
            "secrets_path": asdict(self.secrets_path),
            "venv_dir": asdict(self.venv_dir),
            "cache_root": asdict(self.cache_root),
            "cache_active_version": self.cache_active_version,
            "cache_bak_versions": list(self.cache_bak_versions),
            "marketplace_clone": asdict(self.marketplace_clone),
            "shim_path": asdict(self.shim_path),
            "total_disk_used_bytes": self.total_disk_used_bytes,
            "total_disk_used_human": self.total_disk_used_human,
        }


# ---------------------------------------------------------------------------
# Cache version detection
# ---------------------------------------------------------------------------


def _scan_cache_versions(cache_root: Path) -> tuple[str | None, list[str]]:
    """Return (active_version, bak_versions) for ``cache_root``.

    Active = lexicographically largest version-shaped dir. Bak = sorted
    list of `<ver>.bak.<ts>` dirs (newest last after asc sort).
    """
    if not cache_root.is_dir():
        return None, []
    active_candidates: list[str] = []
    bak: list[str] = []
    for entry in cache_root.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if _VERSION_RE.match(name):
            active_candidates.append(name)
        elif BAK_FILENAME_RE.match(name):
            bak.append(name)
    active = max(active_candidates, key=_version_sort_key) if active_candidates else None
    return active, sorted(bak)


def _version_sort_key(name: str) -> tuple[int, ...]:
    """Sort key for "X.Y.Z" version strings — tuple-of-ints comparison."""
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return ()


# ---------------------------------------------------------------------------
# Build + format
# ---------------------------------------------------------------------------


def build_where_report() -> WhereReport:
    """Compose the full :class:`WhereReport` for the current environment."""
    paperwiki_home = resolve_paperwiki_home()
    recipes = resolve_paperwiki_recipes_dir()
    venv = resolve_paperwiki_venv_dir()
    secrets = paperwiki_home / "secrets.env"

    cache_root = default_cache_root()
    marketplace_clone = default_marketplace_clone()
    shim = default_shim_path()
    cache_active, cache_bak = _scan_cache_versions(cache_root)

    home_report = PathReport.from_path(paperwiki_home, label="config + venv (PAPERWIKI_HOME)")
    recipes_report = PathReport.from_path(recipes, label="recipes")
    secrets_report = PathReport.from_path(secrets, label="secrets")
    venv_report = PathReport.from_path(venv, label="venv")
    cache_root_report = PathReport.from_path(cache_root, label="plugin cache")
    marketplace_report = PathReport.from_path(marketplace_clone, label="marketplace clone")
    shim_report = PathReport.from_path(shim, label="shim")

    # Aggregate disk usage. The home report covers recipes + secrets + venv
    # already (they live under it). We sum mutually-exclusive top-level
    # paths: home + cache + marketplace + shim.
    total = (
        home_report.size_bytes
        + cache_root_report.size_bytes
        + marketplace_report.size_bytes
        + shim_report.size_bytes
    )

    return WhereReport(
        paperwiki_home=home_report,
        recipes_dir=recipes_report,
        secrets_path=secrets_report,
        venv_dir=venv_report,
        cache_root=cache_root_report,
        cache_active_version=cache_active,
        cache_bak_versions=cache_bak,
        marketplace_clone=marketplace_report,
        shim_path=shim_report,
        total_disk_used_bytes=total,
        total_disk_used_human=_format_size(total),
    )


def _line(label: str, value: str, *, width: int = 31) -> str:
    """Aligned ``label : value`` line for the human report."""
    return f"{label:<{width}}: {value}"


def format_human_report(report: WhereReport) -> str:
    """Render :class:`WhereReport` as the documented indented tree."""
    lines: list[str] = []

    def _section(report_path: PathReport) -> str:
        if report_path.exists:
            return f"{report_path.path}  ({report_path.size_human})"
        return f"{report_path.path}  (missing)"

    lines.append(_line("config + venv (PAPERWIKI_HOME)", _section(report.paperwiki_home)))
    lines.append(f"  ├── recipes/        {_recipes_summary(report.recipes_dir)}")
    lines.append(f"  ├── secrets.env     {_secrets_summary(report.secrets_path)}")
    lines.append(f"  └── venv/           {_venv_summary(report.venv_dir)}")
    lines.append(_line("plugin cache", _section(report.cache_root)))
    if report.cache_active_version:
        lines.append(f"  ├── {report.cache_active_version}/        (current)")
    elif report.cache_root.exists:
        lines.append("  ├── (no active cache version detected)")
    # Newer first when displayed in reverse.
    lines.extend(f"  ├── {bak}" for bak in reversed(report.cache_bak_versions))
    lines.append(_line("marketplace clone", _section(report.marketplace_clone)))
    lines.append(_line("shim", _section(report.shim_path)))
    lines.append("")
    lines.append(f"total disk used: {report.total_disk_used_human}")
    return "\n".join(lines) + "\n"


def _recipes_summary(report_path: PathReport) -> str:
    if not report_path.exists:
        return "(missing)"
    try:
        count = sum(1 for _ in Path(report_path.path).glob("*.yaml"))
    except OSError:
        count = 0
    return f"({count} files, {report_path.size_human})"


def _secrets_summary(report_path: PathReport) -> str:
    if not report_path.exists:
        return "(missing)"
    return f"({report_path.size_human})"


def _venv_summary(report_path: PathReport) -> str:
    if not report_path.exists:
        return "(missing)"
    stamp = Path(report_path.path) / ".installed"
    version = ""
    if stamp.is_file():
        try:
            version = stamp.read_text(encoding="utf-8").strip()
        except OSError:
            version = ""
    if version:
        return f"({report_path.size_human}, deps for {version})"
    return f"({report_path.size_human})"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@app.command(name="where")
def main(
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit JSON instead of human-readable indented tree.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG-level logging."),
    ] = False,
) -> None:
    """Print every paperwiki path on disk with sizes."""
    configure_runner_logging(verbose=verbose)

    report = build_where_report()

    if json_output:
        typer.echo(json.dumps(report.to_json_dict(), indent=2))
    else:
        typer.echo(format_human_report(report), nl=False)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    app()
    sys.exit(0)


__all__ = [
    "PathReport",
    "WhereReport",
    "app",
    "build_where_report",
    "default_cache_root",
    "default_marketplace_clone",
    "default_shim_path",
    "format_human_report",
]
