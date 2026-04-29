"""Sanity tests for the v0.3.38 SKILL-lint sandbox (D-9.38.6).

These cover the contract documented in plan §15.3 task 9.99:

- The smart mock ``paperwiki`` shim returns valid JSON for
  ``diagnostics``.
- ``paperwiki status`` exits 0 with the documented sandbox banner.
- The helper file in the sandbox is byte-identical to
  ``lib/bash-helpers.sh`` (no transcoding, no line-ending drift).

The lint test (``test_skill_bash_snippets_lint.py``, task 9.100)
trusts these invariants implicitly; if any of these break, the
parametric subprocess lint will fail in opaque ways. Catch the
infrastructure regression here, fast and named.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from skill_lint_sandbox import build_sandbox

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELPER_SOURCE = _REPO_ROOT / "lib" / "bash-helpers.sh"
_BASH_PATH = shutil.which("bash")

pytestmark = pytest.mark.skipif(_BASH_PATH is None, reason="bash not on PATH")


def _sandbox_env(home: Path) -> dict[str, str]:
    """Build the env dict used by every subprocess test below."""
    return {
        "HOME": str(home),
        "PATH": f"{home}/.local/bin:/usr/bin:/bin",
    }


def test_build_sandbox_returns_existing_directory(tmp_path: Path) -> None:
    home = build_sandbox(tmp_path)
    assert home.is_dir()
    assert (home / ".local" / "bin" / "paperwiki").is_file()
    assert (home / ".local" / "lib" / "paperwiki" / "bash-helpers.sh").is_file()
    assert (home / ".config" / "paper-wiki" / "recipes" / "daily.yaml").is_file()


def test_smart_shim_diagnostics_returns_valid_json(sandbox_home: Path) -> None:
    """``paperwiki diagnostics`` must emit parseable JSON with status=healthy."""
    assert _BASH_PATH is not None
    proc = subprocess.run(
        [_BASH_PATH, "-c", "paperwiki diagnostics"],
        capture_output=True,
        text=True,
        check=False,
        env=_sandbox_env(sandbox_home),
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == "healthy"
    assert data["shim_version"] == "v0.3.38"
    assert "mcp_servers" in data


def test_smart_shim_status_exits_zero(sandbox_home: Path) -> None:
    assert _BASH_PATH is not None
    proc = subprocess.run(
        [_BASH_PATH, "-c", "paperwiki status"],
        capture_output=True,
        text=True,
        check=False,
        env=_sandbox_env(sandbox_home),
    )
    assert proc.returncode == 0, proc.stderr
    assert "v0.3.38 (sandbox)" in proc.stdout


def test_smart_shim_dispatches_runner_subcommands(sandbox_home: Path) -> None:
    """Every shim-using SKILL exercises one of these subcommands."""
    assert _BASH_PATH is not None
    for sub in (
        "digest",
        "wiki-ingest",
        "wiki-lint",
        "wiki-compile",
        "wiki-query",
        "extract-images",
        "migrate-recipe",
        "migrate-sources",
        "update",
        "uninstall",
        "gc-archive",
        "gc-bak",
        "where",
    ):
        proc = subprocess.run(
            [_BASH_PATH, "-c", f"paperwiki {sub} arg1 arg2"],
            capture_output=True,
            text=True,
            check=False,
            env=_sandbox_env(sandbox_home),
        )
        assert proc.returncode == 0, (
            f"smart shim should exit 0 for `paperwiki {sub}` "
            f"(got {proc.returncode}; stderr={proc.stderr!r})"
        )
        assert sub in proc.stdout, (
            f"smart shim stdout for `paperwiki {sub}` should mention the "
            f"subcommand name; got {proc.stdout!r}"
        )


def test_helper_in_sandbox_is_byte_identical(sandbox_home: Path) -> None:
    """The helper file must be a verbatim copy of ``lib/bash-helpers.sh``."""
    sandbox_helper = sandbox_home / ".local" / "lib" / "paperwiki" / "bash-helpers.sh"
    assert sandbox_helper.read_bytes() == _HELPER_SOURCE.read_bytes(), (
        "sandbox helper must be byte-identical to repo helper "
        "(transcoding would silently break the source-or-die stanza)"
    )


def test_stub_plugin_cache_has_ensure_env_no_op(sandbox_home: Path) -> None:
    """The setup SKILL Step 0 ``bash $CLAUDE_PLUGIN_ROOT/hooks/ensure-env.sh``
    line must succeed in the sandbox — the stub is a no-op.
    """
    stub = (
        sandbox_home
        / ".claude"
        / "plugins"
        / "cache"
        / "paper-wiki"
        / "paper-wiki"
        / "0.3.38"
        / "hooks"
        / "ensure-env.sh"
    )
    assert stub.is_file()

    assert _BASH_PATH is not None
    proc = subprocess.run(
        [_BASH_PATH, str(stub)],
        capture_output=True,
        text=True,
        check=False,
        env=_sandbox_env(sandbox_home),
    )
    assert proc.returncode == 0, proc.stderr
