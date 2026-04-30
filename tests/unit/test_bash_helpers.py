"""Unit tests for ``lib/bash-helpers.sh`` (v0.3.38 D-9.38.2 + v0.3.39 D-9.39.3).

The helper is sourced by every shim-using SKILL via the
``source-or-die`` stanza (D-9.38.4). Its four public functions —
``paperwiki_ensure_path``, ``paperwiki_resolve_plugin_root``,
``paperwiki_bootstrap``, and ``paperwiki_diag`` (added in v0.3.39
D-9.39.3, superseding the v0.3.38 "exactly three functions"
constraint) — must be idempotent and side-effect-free beyond the
documented exports. ``paperwiki_diag`` is additionally read-only
(no env mutation, no filesystem writes, no secret content). These
tests run each function in a fresh ``bash -c`` subprocess with
``env=`` overrides for ``HOME`` and ``PATH`` so the assertions
don't depend on the developer's real environment.

The smoke-test pin in ``tests/test_smoke.py`` covers file-existence
and tag-line checks; here we exercise the runtime contract.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELPER_PATH = _REPO_ROOT / "lib" / "bash-helpers.sh"
_BASH_PATH = shutil.which("bash")


pytestmark = pytest.mark.skipif(_BASH_PATH is None, reason="bash not on PATH")


def _run_bash(
    script: str,
    *,
    env_overrides: dict[str, str],
    base_path: str = "/usr/bin:/bin",
) -> subprocess.CompletedProcess[str]:
    """Run ``script`` in a clean ``bash -c`` subprocess.

    Uses the absolute bash path resolved at module load time so the
    child env's restricted PATH (which the helper modifies) doesn't
    interfere with executable resolution. The base PATH stays minimal
    so assertions reflect what the helper adds, not what the
    developer's shell already had on PATH.
    """
    assert _BASH_PATH is not None  # guarded by pytestmark
    env = {"PATH": base_path}
    env.update(env_overrides)
    return subprocess.run(
        [_BASH_PATH, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_helper_file_exists() -> None:
    assert _HELPER_PATH.is_file(), f"missing helper at {_HELPER_PATH}"


def test_helper_parses_with_bash_n() -> None:
    """``bash -n`` exits 0 — syntax-only parse."""
    assert _BASH_PATH is not None  # guarded by pytestmark
    proc = subprocess.run(
        [_BASH_PATH, "-n", str(_HELPER_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"bash -n failed:\n{proc.stderr}"


def test_helper_declares_four_public_functions(tmp_path: Path) -> None:
    """``declare -F`` lists exactly the documented public surface (v0.3.39 D-9.39.3)."""
    proc = _run_bash(
        f"source {_HELPER_PATH}; declare -F | awk '{{print $3}}'",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    declared = set(proc.stdout.split())
    assert {
        "paperwiki_ensure_path",
        "paperwiki_resolve_plugin_root",
        "paperwiki_bootstrap",
        "paperwiki_diag",
    } <= declared, f"missing public functions; declared = {declared!r}"


# ---------------------------------------------------------------------------
# paperwiki_ensure_path
# ---------------------------------------------------------------------------


def test_ensure_path_prepends_when_missing(tmp_path: Path) -> None:
    proc = _run_bash(
        f'source {_HELPER_PATH}; paperwiki_ensure_path; echo "$PATH"',
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"{tmp_path}/.local/bin:/usr/bin:/bin"


def test_ensure_path_idempotent(tmp_path: Path) -> None:
    """Two calls in a row don't double-up the prefix."""
    proc = _run_bash(
        f'source {_HELPER_PATH}; paperwiki_ensure_path; paperwiki_ensure_path; echo "$PATH"',
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"{tmp_path}/.local/bin:/usr/bin:/bin"


def test_ensure_path_no_op_when_already_present(tmp_path: Path) -> None:
    """If ``$HOME/.local/bin`` is already on PATH the helper is a no-op."""
    base = f"{tmp_path}/.local/bin:/usr/bin:/bin"
    proc = _run_bash(
        f'source {_HELPER_PATH}; paperwiki_ensure_path; echo "$PATH"',
        env_overrides={"HOME": str(tmp_path)},
        base_path=base,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == base


# ---------------------------------------------------------------------------
# paperwiki_resolve_plugin_root
# ---------------------------------------------------------------------------


def _build_fake_cache(tmp_path: Path, *versions: str) -> None:
    """Create a fake plugin cache tree under ``tmp_path``."""
    cache_root = tmp_path / ".claude" / "plugins" / "cache" / "paper-wiki" / "paper-wiki"
    cache_root.mkdir(parents=True, exist_ok=True)
    for version in versions:
        (cache_root / version).mkdir(parents=True, exist_ok=True)


def test_resolve_picks_highest_version(tmp_path: Path) -> None:
    _build_fake_cache(tmp_path, "0.3.36", "0.3.37", "0.3.38")
    proc = _run_bash(
        f"unset CLAUDE_PLUGIN_ROOT; "
        f"source {_HELPER_PATH}; "
        f'paperwiki_resolve_plugin_root; echo "$CLAUDE_PLUGIN_ROOT"',
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    expected_suffix = "paper-wiki/0.3.38"
    assert proc.stdout.strip().endswith(expected_suffix), (
        f"expected suffix {expected_suffix!r}, got {proc.stdout.strip()!r}"
    )


def test_resolve_skips_bak_directories(tmp_path: Path) -> None:
    """Backup dirs left by ``paperwiki update`` (suffixed ``.bak.<ts>``) skip."""
    _build_fake_cache(tmp_path, "0.3.37", "0.3.36.bak.20260428")
    proc = _run_bash(
        f"unset CLAUDE_PLUGIN_ROOT; "
        f"source {_HELPER_PATH}; "
        f'paperwiki_resolve_plugin_root; echo "$CLAUDE_PLUGIN_ROOT"',
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    resolved = proc.stdout.strip()
    assert resolved.endswith("paper-wiki/0.3.37"), resolved
    assert ".bak." not in resolved


def test_resolve_preserves_existing_non_empty_value(tmp_path: Path) -> None:
    """An already-set CLAUDE_PLUGIN_ROOT is not overwritten."""
    _build_fake_cache(tmp_path, "0.3.38")
    proc = _run_bash(
        f'export CLAUDE_PLUGIN_ROOT="/preset/value"; '
        f"source {_HELPER_PATH}; "
        f'paperwiki_resolve_plugin_root; echo "$CLAUDE_PLUGIN_ROOT"',
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "/preset/value"


def test_resolve_leaves_unset_when_no_cache(tmp_path: Path) -> None:
    """No cache dir → CLAUDE_PLUGIN_ROOT stays unset (stays empty)."""
    proc = _run_bash(
        f"unset CLAUDE_PLUGIN_ROOT; "
        f"source {_HELPER_PATH}; "
        f"paperwiki_resolve_plugin_root; "
        f'echo "VAR=${{CLAUDE_PLUGIN_ROOT-UNSET}}"',
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "VAR=UNSET", (
        f"expected the var to remain unset; got {proc.stdout.strip()!r}"
    )


# ---------------------------------------------------------------------------
# paperwiki_bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_calls_both(tmp_path: Path) -> None:
    """paperwiki_bootstrap runs ensure_path AND resolve in one call."""
    _build_fake_cache(tmp_path, "0.3.38")
    proc = _run_bash(
        f"unset CLAUDE_PLUGIN_ROOT; "
        f"source {_HELPER_PATH}; "
        f"paperwiki_bootstrap; "
        f'echo "PATH=$PATH"; echo "ROOT=$CLAUDE_PLUGIN_ROOT"',
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert f"PATH={tmp_path}/.local/bin:/usr/bin:/bin" in out, out
    assert f"ROOT={tmp_path}/.claude/plugins/cache/paper-wiki/paper-wiki/0.3.38" in out, out


def test_bootstrap_idempotent(tmp_path: Path) -> None:
    """Repeated bootstrap calls don't double-prefix PATH or change ROOT."""
    _build_fake_cache(tmp_path, "0.3.38")
    proc = _run_bash(
        f"unset CLAUDE_PLUGIN_ROOT; "
        f"source {_HELPER_PATH}; "
        f"paperwiki_bootstrap; paperwiki_bootstrap; paperwiki_bootstrap; "
        f'echo "PATH=$PATH"',
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    # Single prefix, despite three calls.
    assert proc.stdout.strip() == f"PATH={tmp_path}/.local/bin:/usr/bin:/bin"


# ---------------------------------------------------------------------------
# paperwiki_diag (v0.3.39 D-9.39.3)
# ---------------------------------------------------------------------------


def test_diag_emits_all_seven_sections(tmp_path: Path) -> None:
    """``paperwiki_diag`` produces a seven-section dump under controlled HOME.

    v0.3.40 D-9.40.3 added a 7th section for the
    ``installed_plugins.json`` paper-wiki entry between cache-versions and
    recipes.
    """
    _build_fake_cache(tmp_path, "0.3.38", "0.3.39")
    # Seed shim + recipes so the dump shows real content.
    shim_dir = tmp_path / ".local" / "bin"
    shim_dir.mkdir(parents=True)
    shim = shim_dir / "paperwiki"
    shim.write_text(
        "#!/usr/bin/env bash\n# paperwiki shim — v0.3.39 (test)\n",
        encoding="utf-8",
    )
    recipes_dir = tmp_path / ".config" / "paper-wiki" / "recipes"
    recipes_dir.mkdir(parents=True)
    (recipes_dir / "daily.yaml").write_text("name: daily\n", encoding="utf-8")
    (recipes_dir / "weekly.yaml").write_text("name: weekly\n", encoding="utf-8")

    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    # Header + footer.
    assert "=== paperwiki_diag — install state ===" in out
    assert "=== end paperwiki_diag ===" in out
    # Seven section dividers (v0.3.40 D-9.40.3 added installed_plugins.json).
    for section in (
        "--- helper ---",
        "--- environment ---",
        "--- shim ",
        "--- plugin cache versions ",
        "--- installed_plugins.json (paper-wiki entry) ---",
        "--- recipes ",
    ):
        assert section in out, f"missing section {section!r} in diag output"
    # Helper version tag echoed (head -1 of the helper file).
    assert "paperwiki bash-helpers" in out
    # Cache versions listed.
    assert "0.3.38" in out
    assert "0.3.39" in out
    # Recipes listed.
    assert "daily.yaml" in out
    assert "weekly.yaml" in out
    # PATH + CLAUDE_PLUGIN_ROOT echoed.
    assert "PATH=" in out
    assert "CLAUDE_PLUGIN_ROOT=" in out


def test_diag_handles_missing_dirs_gracefully(tmp_path: Path) -> None:
    """``paperwiki_diag`` doesn't crash when shim/cache/recipes don't exist."""
    # No cache, no shim, no recipes — bare HOME.
    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "(not installed)" in out  # shim missing
    assert "(directory does not exist)" in out  # cache + recipes missing


def test_diag_does_not_dump_secrets(tmp_path: Path) -> None:
    """``paperwiki_diag`` MUST NOT print ``secrets.env`` content (D-9.39.3 R2)."""
    config_dir = tmp_path / ".config" / "paper-wiki"
    config_dir.mkdir(parents=True)
    (config_dir / "secrets.env").write_text(
        "export PAPERWIKI_S2_API_KEY=SUPER_SECRET_KEY_123\n",
        encoding="utf-8",
    )
    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert "SUPER_SECRET_KEY_123" not in proc.stdout, (
        "paperwiki_diag must NEVER print secrets.env content (D-9.39.3 R2)"
    )
    assert "PAPERWIKI_S2_API_KEY" not in proc.stdout, (
        "paperwiki_diag must not name secret env vars from secrets.env"
    )


def test_diag_is_read_only(tmp_path: Path) -> None:
    """``paperwiki_diag`` must not mutate state (no env changes, no file writes)."""
    _build_fake_cache(tmp_path, "0.3.38")
    # Capture state before.
    before_listing = sorted(p.name for p in tmp_path.rglob("*"))

    diff_check = (
        'echo "PATH_CHANGED=$([ \\"$PATH\\" = \\"$orig_path\\" ] '
        '&& echo no || echo yes)"; '
        'echo "ROOT_CHANGED=$([ \\"${CLAUDE_PLUGIN_ROOT:-}\\" = \\"$orig_root\\" ] '
        '&& echo no || echo yes)"'
    )
    proc = _run_bash(
        f"source {_HELPER_PATH}; "
        f"orig_path=$PATH; "
        f"orig_root=${{CLAUDE_PLUGIN_ROOT:-}}; "
        f"paperwiki_diag > /dev/null; "
        f"{diff_check}",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert "PATH_CHANGED=no" in proc.stdout, "paperwiki_diag mutated PATH"
    assert "ROOT_CHANGED=no" in proc.stdout, "paperwiki_diag mutated CLAUDE_PLUGIN_ROOT"

    # Filesystem unchanged.
    after_listing = sorted(p.name for p in tmp_path.rglob("*"))
    assert before_listing == after_listing, "paperwiki_diag mutated the filesystem under HOME"


# ---------------------------------------------------------------------------
# v0.3.40 D-9.40.3: paperwiki_diag prints installed_plugins.json paper-wiki entry
# ---------------------------------------------------------------------------


def _seed_installed_plugins(
    tmp_path: Path, *, paper_wiki_version: str | None = None, extra_plugin: bool = False
) -> Path:
    """Stage ``$HOME/.claude/plugins/installed_plugins.json``.

    When ``paper_wiki_version`` is given, seeds a paper-wiki@paper-wiki
    entry at that version. When None, the JSON file exists but the
    paper-wiki key is absent. ``extra_plugin`` adds a sibling plugin
    entry to verify domain-bounded printing (D-9.40.3).
    """
    plugins_dir = tmp_path / ".claude" / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    path = plugins_dir / "installed_plugins.json"
    plugins: dict[str, object] = {}
    if paper_wiki_version is not None:
        plugins["paper-wiki@paper-wiki"] = [
            {
                "scope": "user",
                "version": paper_wiki_version,
                "gitCommitSha": "deadbeefcafe",
                "installPath": str(
                    plugins_dir / "cache" / "paper-wiki" / "paper-wiki" / paper_wiki_version
                ),
            }
        ]
    if extra_plugin:
        plugins["other-plugin@other-source"] = [{"scope": "user", "version": "1.2.3"}]
    path.write_text(
        json.dumps({"version": 2, "plugins": plugins}),
        encoding="utf-8",
    )
    return path


def test_diag_prints_installed_plugins_entry_when_present(tmp_path: Path) -> None:
    """When the paper-wiki entry exists, diag prints its keys (D-9.40.3 case a/b)."""
    _seed_installed_plugins(tmp_path, paper_wiki_version="0.3.40")

    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    # Section header.
    assert "--- installed_plugins.json (paper-wiki entry) ---" in out
    # Entry keys appear (version + gitCommitSha + installPath per D-9.40.3).
    assert "0.3.40" in out
    assert "deadbeefcafe" in out
    assert "installPath" in out


def test_diag_shows_not_registered_when_file_missing(tmp_path: Path) -> None:
    """When installed_plugins.json doesn't exist, diag prints (not registered) (D-9.40.3 case c)."""
    # Don't seed the file at all.
    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "--- installed_plugins.json (paper-wiki entry) ---" in out
    # Pull out the installed-plugins section to scope the assertion.
    section = out.split("--- installed_plugins.json (paper-wiki entry) ---", 1)[1].split("---", 1)[
        0
    ]
    assert "(not registered)" in section


def test_diag_shows_not_registered_when_paper_wiki_entry_absent(tmp_path: Path) -> None:
    """When the file exists but paper-wiki key is absent, diag prints (not registered).

    D-9.40.3: same fallback for missing-file and missing-entry cases.
    """
    # File present, paper-wiki entry absent, sibling plugin present.
    _seed_installed_plugins(tmp_path, paper_wiki_version=None, extra_plugin=True)

    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    section = out.split("--- installed_plugins.json (paper-wiki entry) ---", 1)[1].split("---", 1)[
        0
    ]
    assert "(not registered)" in section


def test_diag_handles_malformed_installed_plugins_json(tmp_path: Path) -> None:
    """When the file is unparseable JSON, diag prints (read failed: <msg>) (D-9.40.3 case d)."""
    plugins_dir = tmp_path / ".claude" / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (plugins_dir / "installed_plugins.json").write_text("{ not valid json", encoding="utf-8")

    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    section = out.split("--- installed_plugins.json (paper-wiki entry) ---", 1)[1].split("---", 1)[
        0
    ]
    assert "read failed" in section.lower(), (
        f"expected read-failed fallback in installed-plugins section:\n{section!r}"
    )


def test_diag_does_not_print_other_plugin_entries(tmp_path: Path) -> None:
    """Domain-bounded scope: diag prints ONLY the paper-wiki entry (D-9.40.3)."""
    _seed_installed_plugins(tmp_path, paper_wiki_version="0.3.40", extra_plugin=True)
    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    # Sibling plugin must NOT leak into the diag output.
    assert "other-plugin@other-source" not in out
    assert "other-plugin" not in out


# ---------------------------------------------------------------------------
# v0.3.40 D-9.40.5: paperwiki_diag --file <path> write mode
# ---------------------------------------------------------------------------


def test_diag_file_flag_writes_full_dump_to_path(tmp_path: Path) -> None:
    """``--file <path>`` writes all 7 sections to the file + confirmation to stdout."""
    _build_fake_cache(tmp_path, "0.3.40")
    out_file = tmp_path / "diag.txt"

    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag --file {out_file}",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    # Stdout shows confirmation only — the dump went to the file.
    assert f"wrote diag to {out_file}" in proc.stdout
    # No section headers in stdout (they all went to the file).
    assert "=== paperwiki_diag" not in proc.stdout

    # File contains the full 7-section dump.
    content = out_file.read_text(encoding="utf-8")
    assert "=== paperwiki_diag — install state ===" in content
    assert "=== end paperwiki_diag ===" in content
    for section in (
        "--- helper ---",
        "--- environment ---",
        "--- shim ",
        "--- plugin cache versions ",
        "--- installed_plugins.json (paper-wiki entry) ---",
        "--- recipes ",
    ):
        assert section in content, f"missing {section!r} in file content"


def test_diag_default_mode_still_prints_to_stdout(tmp_path: Path) -> None:
    """No flag → behaves as today (prints full dump to stdout)."""
    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert "=== paperwiki_diag — install state ===" in proc.stdout
    assert "=== end paperwiki_diag ===" in proc.stdout
    # No "wrote diag to" line in stdout-only mode.
    assert "wrote diag to" not in proc.stdout


def test_diag_file_flag_creates_parent_dirs(tmp_path: Path) -> None:
    """``--file`` with a path whose parent doesn't exist creates parents."""
    out_file = tmp_path / "deeply" / "nested" / "subdir" / "diag.txt"
    assert not out_file.parent.exists()

    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag --file {out_file}",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert out_file.is_file()
    assert "=== paperwiki_diag — install state ===" in out_file.read_text(encoding="utf-8")


def test_diag_file_flag_without_arg_uses_default_path(tmp_path: Path) -> None:
    """v0.3.41 D-9.41.3: ``--file`` without a path defaults to ``$HOME/paper-wiki-diag-<ts>.txt``.

    Replaces v0.3.40's "fail loudly" semantics — see plan §18.3 task
    9.126. The default location lives in ``$HOME`` (universally
    writable across macOS / Linux); the filename includes a UTC
    timestamp so each invocation produces a unique file (no
    overwrite surprises).
    """
    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag --file",
        env_overrides={"HOME": str(tmp_path)},
    )
    # Default-path mode succeeds (no error exit).
    assert proc.returncode == 0, (
        f"--file without arg must succeed using default path; got "
        f"exit {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    # Confirmation echoed to stdout.
    assert "wrote diag to" in proc.stdout
    # A file matching the default-path pattern was written.
    candidates = list(tmp_path.glob("paper-wiki-diag-*.txt"))
    assert len(candidates) == 1, (
        f"expected exactly one default-path file in $HOME; got {candidates}"
    )
    # File contains the full diag dump.
    content = candidates[0].read_text(encoding="utf-8")
    assert "=== paperwiki_diag — install state ===" in content


def test_diag_file_flag_default_path_is_timestamped(tmp_path: Path) -> None:
    """Default filename matches ``paper-wiki-diag-<YYYYMMDDTHHMMSSZ>.txt``."""
    import re as _re

    proc = _run_bash(
        f"source {_HELPER_PATH}; paperwiki_diag --file",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    candidates = list(tmp_path.glob("paper-wiki-diag-*.txt"))
    assert len(candidates) == 1, candidates
    # ``date +%Y%m%dT%H%M%SZ`` shape: 8 digits, T, 6 digits, Z.
    assert _re.match(r"^paper-wiki-diag-\d{8}T\d{6}Z\.txt$", candidates[0].name), (
        f"default filename must be timestamped; got {candidates[0].name!r}"
    )
