"""Unit tests for ``lib/bash-helpers.sh`` (v0.3.38 D-9.38.2).

The helper is sourced by every shim-using SKILL via the
``source-or-die`` stanza (D-9.38.4). Its three public functions —
``paperwiki_ensure_path``, ``paperwiki_resolve_plugin_root``, and
``paperwiki_bootstrap`` — must be idempotent and side-effect-free
beyond the documented exports. These tests run each function in a
fresh ``bash -c`` subprocess with `env=` overrides for ``HOME`` and
``PATH`` so the assertions don't depend on the developer's real
environment.

The smoke-test pin in ``tests/test_smoke.py`` covers file-existence
and tag-line checks; here we exercise the runtime contract.
"""

from __future__ import annotations

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


def test_helper_declares_three_public_functions(tmp_path: Path) -> None:
    """``declare -F`` lists exactly the documented public surface."""
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
