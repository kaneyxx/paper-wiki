"""``paperwiki.runners.doctor`` — one-command install health check.

v0.3.43 D-9.43.3. Aggregates the four probes that v0.3.42 ships
separately (cache + marketplace, install integrity, Python venv,
shell-rc integration) behind a single ``paperwiki doctor`` command.
Replaces the cognitive load of remembering ``status`` vs ``diag`` vs
"is the venv working" with one screen showing every check + a
``healthy/total`` summary.

The runner exposes a pure function ``run_doctor()`` that returns a
structured :class:`DoctorReport`; ``format_doctor_pretty`` and
``format_doctor_json`` render it for the terminal or for automation
respectively. Tests construct ``DoctorReport`` directly or call
``run_doctor`` against monkeypatched paths — no subprocess in unit
tests, no real filesystem outside ``tmp_path``.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from paperwiki._internal.health import check_install_health

__all__ = [
    "DoctorReport",
    "DoctorRow",
    "DoctorSection",
    "format_doctor_json",
    "format_doctor_pretty",
    "run_doctor",
]


# ---------------------------------------------------------------------------
# Markers — kept in sync with hooks/rc-integration.sh and
# runners/uninstall.py. The begin marker is enough to detect block presence
# (idempotent grep, same as paperwiki_rc_install).
# ---------------------------------------------------------------------------

_RC_BEGIN_MARKER = "# >>> paperwiki helpers >>>"


# ---------------------------------------------------------------------------
# Result dataclasses — frozen so consumers can cache / share without
# accidental mutation. ``DoctorRow`` carries ``na`` for "this check
# doesn't apply in the current environment" (e.g. fish shell, opt-out
# env var) so the summary doesn't penalize the user.
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class DoctorRow:
    """One health check — passes/fails, optional action hint, optional n/a."""

    label: str
    ok: bool
    hint: str | None = None
    na: bool = False

    @property
    def healthy(self) -> bool:
        """A row is healthy when it passes OR is not applicable."""
        return self.ok or self.na


@dataclass(slots=True, frozen=True)
class DoctorSection:
    """Group of related rows shown together in the pretty output."""

    name: str
    rows: list[DoctorRow] = field(default_factory=list)

    @property
    def healthy(self) -> int:
        return sum(1 for r in self.rows if r.healthy)

    @property
    def total(self) -> int:
        return len(self.rows)


@dataclass(slots=True, frozen=True)
class DoctorReport:
    """Top-level report aggregating all sections + summary metadata."""

    sections: list[DoctorSection]
    cache_version: str | None
    marketplace_version: str | None
    enabled_in_settings: bool
    enabled_in_settings_local: bool
    bak_count: int
    bak_oldest: str | None
    bak_root: Path

    @property
    def healthy(self) -> int:
        return sum(s.healthy for s in self.sections)

    @property
    def total(self) -> int:
        return sum(s.total for s in self.sections)


# ---------------------------------------------------------------------------
# Helpers — kept module-private and side-effect-free.
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _resolve_cache_version(installed_plugins: Path) -> str | None:
    data = _read_json(installed_plugins)
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        return None
    entries = plugins.get("paper-wiki@paper-wiki")
    if isinstance(entries, list) and entries:
        first = entries[0]
        if isinstance(first, dict):
            ver = first.get("version")
            return str(ver) if ver else None
    if isinstance(entries, dict):  # legacy/hand-edited shape
        ver = entries.get("version")
        return str(ver) if ver else None
    return None


def _resolve_marketplace_version(marketplace_dir: Path) -> str | None:
    plugin_json = marketplace_dir / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        return None
    try:
        data = json.loads(plugin_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    ver = data.get("version")
    return str(ver) if ver else None


def _is_enabled_in(settings_path: Path) -> bool:
    data = _read_json(settings_path)
    enabled = data.get("enabledPlugins")
    return isinstance(enabled, dict) and "paper-wiki@paper-wiki" in enabled


_BAK_FILENAME_RE = re.compile(r"^\d+\.\d+\.\d+\.bak\.\d{8}T\d{6}Z$")
_BAK_TIMESTAMP_RE = re.compile(r"\.bak\.(\d{8})T\d{6}Z$")


def _summarize_bak(bak_root: Path) -> tuple[int, str | None]:
    if not bak_root.is_dir():
        return (0, None)
    matches: list[str] = sorted(
        entry.name
        for entry in bak_root.iterdir()
        if entry.is_dir() and _BAK_FILENAME_RE.match(entry.name)
    )
    if not matches:
        return (0, None)
    oldest = matches[0]
    m = _BAK_TIMESTAMP_RE.search(oldest)
    if m:
        suffix = m.group(1)
        oldest_human = f"{suffix[:4]}-{suffix[4:6]}-{suffix[6:8]}"
    else:
        oldest_human = oldest
    return (len(matches), oldest_human)


@dataclass(slots=True, frozen=True)
class _VenvCheckOutcome:
    """Result of a venv health probe (intermediate value)."""

    venv_present: bool
    python_runs: bool
    python_version: str
    paperwiki_importable: bool


def _default_venv_check(venv_dir: Path, *, timeout: float = 5.0) -> _VenvCheckOutcome:
    """Default subprocess-based venv probe.

    Tests can substitute a faster fake via the ``venv_check`` arg of
    :func:`run_doctor` so they never touch a real Python.

    Each subprocess has a 5s timeout (mirrors ``cli.py:_git_pull``
    D-9.40.4 pattern). Failures are absorbed — the row gets marked
    unhealthy with a hint, not a crash.
    """
    py = venv_dir / "bin" / "python"
    if not py.is_file():
        return _VenvCheckOutcome(False, False, "", False)
    # python --version
    python_runs = False
    python_version = ""
    try:
        res = subprocess.run(  # noqa: S603 — args are literal + resolved path
            [str(py), "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if res.returncode == 0:
            python_runs = True
            python_version = (res.stdout or res.stderr).strip()
    except (subprocess.TimeoutExpired, OSError):
        python_runs = False
    # python -c "import paperwiki"
    paperwiki_importable = False
    if python_runs:
        try:
            res = subprocess.run(  # noqa: S603
                [str(py), "-c", "import paperwiki"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            paperwiki_importable = res.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            paperwiki_importable = False
    return _VenvCheckOutcome(
        venv_present=True,
        python_runs=python_runs,
        python_version=python_version,
        paperwiki_importable=paperwiki_importable,
    )


def _pick_rc_file(home: Path, shell: str | None) -> Path | None:
    """Mirror ``hooks/rc-integration.sh::_pick_rc_file`` for bash/zsh.

    Returns ``None`` for fish/csh/etc — those shells get a "n/a" row in
    the doctor output (they may have their own integration via
    ``paperwiki rc-integration.sh`` v0.3.43 D-9.43.5; this function only
    detects the bash/zsh variant we ship in v0.3.43).
    """
    if not shell:
        return None
    basename = shell.rsplit("/", 1)[-1]
    if basename == "zsh":
        return home / ".zshrc"
    if basename == "bash":
        bash_profile = home / ".bash_profile"
        return bash_profile if bash_profile.is_file() else home / ".bashrc"
    return None


# ---------------------------------------------------------------------------
# Section builders — each returns a ``DoctorSection``.
# ---------------------------------------------------------------------------


def _build_cache_section(
    *,
    cache_version: str | None,
    marketplace_version: str | None,
    enabled_in_settings: bool,
    enabled_in_settings_local: bool,
) -> DoctorSection:
    rows: list[DoctorRow] = []
    rows.append(
        DoctorRow(
            label=f"cache version: {cache_version or '(not registered)'}",
            ok=cache_version is not None,
            hint=None if cache_version is not None else "run /plugin install paper-wiki@paper-wiki",
        )
    )
    rows.append(
        DoctorRow(
            label=f"marketplace version: {marketplace_version or '(not found)'}",
            ok=marketplace_version is not None,
            hint=None
            if marketplace_version is not None
            else "run /plugin marketplace add kaneyxx/paper-wiki",
        )
    )
    enabled_any = enabled_in_settings or enabled_in_settings_local
    rows.append(
        DoctorRow(
            label=(
                f"enabledPlugins: settings.json="
                f"{'yes' if enabled_in_settings else 'no'}  "
                f"settings.local.json="
                f"{'yes' if enabled_in_settings_local else 'no'}"
            ),
            ok=enabled_any,
            hint=None if enabled_any else "run /plugin install paper-wiki@paper-wiki",
        )
    )
    return DoctorSection(name="Cache & marketplace", rows=rows)


def _build_install_integrity_section(
    *,
    home: Path,
    expected_version: str,
    path_env: str | None,
) -> DoctorSection:
    raw_rows = check_install_health(
        home=home,
        expected_version=expected_version,
        path_env=path_env,
    )
    return DoctorSection(
        name="Install integrity",
        rows=[DoctorRow(label=label, ok=ok, hint=hint) for label, ok, hint in raw_rows],
    )


def _build_venv_section(*, venv_dir: Path, outcome: _VenvCheckOutcome) -> DoctorSection:
    rows: list[DoctorRow] = []
    rows.append(
        DoctorRow(
            label=f"venv at {venv_dir}",
            ok=outcome.venv_present,
            hint=None
            if outcome.venv_present
            else "open a fresh Claude Code session — SessionStart bootstraps the venv",
        )
    )
    rows.append(
        DoctorRow(
            label=(
                f"python: {outcome.python_version}"
                if outcome.python_version
                else "python (no version reported)"
            ),
            ok=outcome.python_runs,
            hint=None if outcome.python_runs else "venv may be corrupt; remove and re-bootstrap",
        )
    )
    rows.append(
        DoctorRow(
            label="paperwiki module importable",
            ok=outcome.paperwiki_importable,
            hint=None
            if outcome.paperwiki_importable
            else "re-run ensure-env.sh (e.g., open a fresh Claude session)",
        )
    )
    return DoctorSection(name="Python venv", rows=rows)


def _build_rc_section(
    *,
    home: Path,
    shell: str | None,
    rc_integration_disabled: bool,
) -> DoctorSection:
    if rc_integration_disabled:
        return DoctorSection(
            name="Shell-rc integration",
            rows=[
                DoctorRow(
                    label="auto-source block (PAPERWIKI_NO_RC_INTEGRATION=1, opt-out)",
                    ok=False,
                    na=True,
                )
            ],
        )
    rc_file = _pick_rc_file(home, shell)
    if rc_file is None:
        # Fish, csh, ksh, … — bash-helpers.sh isn't applicable.
        shell_label = (shell or "(unset)").rsplit("/", 1)[-1] or "(unset)"
        return DoctorSection(
            name="Shell-rc integration",
            rows=[
                DoctorRow(
                    label=(
                        f"auto-source block (shell={shell_label}, "
                        "bash-helpers.sh applies to bash/zsh only)"
                    ),
                    ok=False,
                    na=True,
                )
            ],
        )
    block_present = False
    if rc_file.is_file():
        try:
            block_present = _RC_BEGIN_MARKER in rc_file.read_text(encoding="utf-8")
        except OSError:
            block_present = False
    label = f"auto-source block in {rc_file}"
    return DoctorSection(
        name="Shell-rc integration",
        rows=[
            DoctorRow(
                label=label,
                ok=block_present,
                hint=None
                if block_present
                else "open a fresh Claude session — SessionStart writes the rc block",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_doctor(
    *,
    home: Path,
    claude_home: Path,
    bak_root: Path,
    venv_dir: Path,
    marketplace_dir: Path,
    shell: str | None,
    path_env: str | None,
    expected_version: str,
    rc_integration_disabled: bool = False,
    venv_check: Callable[[Path], _VenvCheckOutcome] | None = None,
) -> DoctorReport:
    """Build the full :class:`DoctorReport`.

    Pure with respect to ``home`` / ``claude_home`` / ``bak_root`` /
    ``venv_dir`` / ``marketplace_dir`` (read-only filesystem access)
    and ``shell`` / ``path_env`` (no env mutation). The optional
    ``venv_check`` hook lets tests substitute a fake probe so they
    don't subprocess to a real Python.
    """
    # Cache + marketplace data (top-level fields).
    cache_version = _resolve_cache_version(claude_home / "plugins" / "installed_plugins.json")
    marketplace_version = _resolve_marketplace_version(marketplace_dir)
    enabled_in_settings = _is_enabled_in(claude_home / "settings.json")
    enabled_in_settings_local = _is_enabled_in(claude_home / "settings.local.json")
    bak_count, bak_oldest = _summarize_bak(bak_root)

    # Section builders.
    cache_section = _build_cache_section(
        cache_version=cache_version,
        marketplace_version=marketplace_version,
        enabled_in_settings=enabled_in_settings,
        enabled_in_settings_local=enabled_in_settings_local,
    )
    integrity_section = _build_install_integrity_section(
        home=home,
        expected_version=expected_version,
        path_env=path_env,
    )
    venv_outcome = (venv_check or _default_venv_check)(venv_dir)
    venv_section = _build_venv_section(venv_dir=venv_dir, outcome=venv_outcome)
    rc_section = _build_rc_section(
        home=home,
        shell=shell,
        rc_integration_disabled=rc_integration_disabled,
    )

    return DoctorReport(
        sections=[cache_section, integrity_section, venv_section, rc_section],
        cache_version=cache_version,
        marketplace_version=marketplace_version,
        enabled_in_settings=enabled_in_settings,
        enabled_in_settings_local=enabled_in_settings_local,
        bak_count=bak_count,
        bak_oldest=bak_oldest,
        bak_root=bak_root,
    )


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def format_doctor_pretty(report: DoctorReport) -> str:
    """Multi-section pretty output, with ✓/✗/n/a markers and a summary."""
    lines: list[str] = []
    lines.append("=== paper-wiki — install health ===")
    lines.append("")

    # Top-level cache / marketplace lines (mirrors ``paperwiki status``).
    if report.bak_count == 0:
        bak_summary = f"no backups  (location: {report.bak_root})"
    else:
        bak_summary = (
            f"{report.bak_count} kept; oldest "
            f"{report.bak_oldest or 'unknown'}  (location: {report.bak_root})"
        )

    for section in report.sections:
        lines.append(f"[ {section.name} ]  ({section.healthy}/{section.total} healthy)")
        for row in section.rows:
            mark = "✓" if row.ok else ("·" if row.na else "✗")
            line = f"  {mark} {row.label}"
            if row.hint and not row.healthy:
                line = f"{line}  (action: {row.hint})"
            lines.append(line)
        lines.append("")

    lines.append(f"backups: {bak_summary}")
    lines.append("")
    lines.append(f"overall: {report.healthy}/{report.total} healthy")
    lines.append("=== end paper-wiki doctor ===")
    return "\n".join(lines) + "\n"


def format_doctor_json(report: DoctorReport) -> str:
    """JSON output for automation. Schema is ``@experimental`` until v0.4."""
    payload: dict[str, object] = {
        "cache_version": report.cache_version,
        "marketplace_version": report.marketplace_version,
        "enabled_in_settings": report.enabled_in_settings,
        "enabled_in_settings_local": report.enabled_in_settings_local,
        "bak_count": report.bak_count,
        "bak_oldest": report.bak_oldest,
        "bak_root": str(report.bak_root),
        "healthy": report.healthy,
        "total": report.total,
        "sections": [
            {
                "name": section.name,
                "healthy": section.healthy,
                "total": section.total,
                "rows": [asdict(row) for row in section.rows],
            }
            for section in report.sections
        ],
    }
    return json.dumps(payload, indent=2)
