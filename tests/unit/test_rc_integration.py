"""Unit tests for ``hooks/rc-integration.sh`` (v0.3.42 D-9.42.2).

The rc-integration helper writes a marker-delimited block to the user's
shell-rc file (``~/.zshrc`` / ``~/.bashrc`` / ``~/.bash_profile``) so
``paperwiki_diag`` and other helper functions are auto-sourced into
fresh terminals — no manual ``source ~/.local/lib/paperwiki/...``
needed. ``ensure-env.sh`` calls ``paperwiki_rc_install`` on
SessionStart; ``paperwiki uninstall --everything`` calls
``paperwiki_rc_uninstall``.

The helper exposes four functions:

- ``_pick_rc_file`` — print the right rc path for $SHELL, or empty
- ``_paperwiki_rc_block`` — print the canonical marker-block content
- ``paperwiki_rc_install`` — idempotent install of the block
- ``paperwiki_rc_uninstall`` — remove the block (preserves rest of rc)

Tests run in ``bash -c`` subprocesses with controlled $HOME / $SHELL so
the assertions don't touch the developer's real rc files.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RC_INTEGRATION = _REPO_ROOT / "hooks" / "rc-integration.sh"
_BASH_PATH = shutil.which("bash")

pytestmark = pytest.mark.skipif(_BASH_PATH is None, reason="bash not on PATH")


def _run(
    script: str,
    *,
    env_overrides: dict[str, str],
    base_path: str = "/usr/bin:/bin",
) -> subprocess.CompletedProcess[str]:
    """Run ``script`` in a clean ``bash -c`` subprocess."""
    assert _BASH_PATH is not None
    env = {"PATH": base_path}
    env.update(env_overrides)
    return subprocess.run(
        [_BASH_PATH, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_rc_integration_file_exists() -> None:
    assert _RC_INTEGRATION.is_file(), f"missing {_RC_INTEGRATION}"


def test_rc_integration_parses_with_bash_n() -> None:
    """``bash -n`` syntax-only parse passes."""
    assert _BASH_PATH is not None
    proc = subprocess.run(
        [_BASH_PATH, "-n", str(_RC_INTEGRATION)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# 9.138 — _pick_rc_file: shell detection
# ---------------------------------------------------------------------------


def test_pick_rc_zsh_returns_zshrc(tmp_path: Path) -> None:
    """``SHELL=/bin/zsh`` → ``$HOME/.zshrc``."""
    proc = _run(
        f"source {_RC_INTEGRATION}; _pick_rc_file",
        env_overrides={"SHELL": "/bin/zsh", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(tmp_path / ".zshrc")


def test_pick_rc_bash_with_existing_bash_profile(tmp_path: Path) -> None:
    """``SHELL=/bin/bash`` + existing ``~/.bash_profile`` → ``~/.bash_profile``."""
    bash_profile = tmp_path / ".bash_profile"
    bash_profile.write_text("# pre-existing\n", encoding="utf-8")
    proc = _run(
        f"source {_RC_INTEGRATION}; _pick_rc_file",
        env_overrides={"SHELL": "/usr/bin/bash", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(bash_profile)


def test_pick_rc_bash_without_bash_profile(tmp_path: Path) -> None:
    """``SHELL=/bin/bash`` + no ``~/.bash_profile`` → ``~/.bashrc``."""
    proc = _run(
        f"source {_RC_INTEGRATION}; _pick_rc_file",
        env_overrides={"SHELL": "/bin/bash", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(tmp_path / ".bashrc")


def test_pick_rc_unsupported_shell_returns_empty(tmp_path: Path) -> None:
    """``SHELL=/usr/bin/fish`` → empty stdout (caller no-ops on empty)."""
    proc = _run(
        f"source {_RC_INTEGRATION}; _pick_rc_file",
        env_overrides={"SHELL": "/usr/local/bin/fish", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_pick_rc_unset_shell_returns_empty(tmp_path: Path) -> None:
    """Unset $SHELL → empty stdout (defensive)."""
    proc = _run(
        f"source {_RC_INTEGRATION}; unset SHELL; _pick_rc_file",
        env_overrides={"HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


# ---------------------------------------------------------------------------
# 9.139 — paperwiki_rc_install: idempotent block-write
# ---------------------------------------------------------------------------


_BEGIN_MARKER = "# >>> paperwiki helpers >>>"
_END_MARKER = "# <<< paperwiki helpers <<<"


def test_rc_install_writes_block_to_fresh_zshrc(tmp_path: Path) -> None:
    """First-run write creates ``.zshrc`` and adds the marker block."""
    proc = _run(
        f"source {_RC_INTEGRATION}; paperwiki_rc_install",
        env_overrides={"SHELL": "/bin/zsh", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    rc = tmp_path / ".zshrc"
    assert rc.is_file()
    content = rc.read_text(encoding="utf-8")
    assert _BEGIN_MARKER in content
    assert _END_MARKER in content
    assert "$HOME/.local/lib/paperwiki/bash-helpers.sh" in content


def test_rc_install_is_idempotent(tmp_path: Path) -> None:
    """Second invocation does NOT double-write the block."""
    proc1 = _run(
        f"source {_RC_INTEGRATION}; paperwiki_rc_install",
        env_overrides={"SHELL": "/bin/zsh", "HOME": str(tmp_path)},
    )
    assert proc1.returncode == 0, proc1.stderr
    proc2 = _run(
        f"source {_RC_INTEGRATION}; paperwiki_rc_install",
        env_overrides={"SHELL": "/bin/zsh", "HOME": str(tmp_path)},
    )
    assert proc2.returncode == 0, proc2.stderr
    rc = tmp_path / ".zshrc"
    content = rc.read_text(encoding="utf-8")
    assert content.count(_BEGIN_MARKER) == 1, (
        f"marker should appear exactly once after two installs:\n{content}"
    )
    assert content.count(_END_MARKER) == 1


def test_rc_install_preserves_existing_rc_content(tmp_path: Path) -> None:
    """User's existing rc content must be preserved (block is appended)."""
    rc = tmp_path / ".zshrc"
    rc.write_text("# user's custom alias\nalias ll='ls -la'\n", encoding="utf-8")
    proc = _run(
        f"source {_RC_INTEGRATION}; paperwiki_rc_install",
        env_overrides={"SHELL": "/bin/zsh", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    content = rc.read_text(encoding="utf-8")
    assert "alias ll='ls -la'" in content
    assert _BEGIN_MARKER in content


def test_rc_install_opt_out_via_env_var(tmp_path: Path) -> None:
    """``PAPERWIKI_NO_RC_INTEGRATION=1`` → skip write entirely (no rc file)."""
    proc = _run(
        f"source {_RC_INTEGRATION}; paperwiki_rc_install",
        env_overrides={
            "SHELL": "/bin/zsh",
            "HOME": str(tmp_path),
            "PAPERWIKI_NO_RC_INTEGRATION": "1",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / ".zshrc").exists(), "opt-out env var must prevent rc file creation"


def test_rc_install_no_op_when_shell_unsupported(tmp_path: Path) -> None:
    """Unsupported shell → silent no-op, no rc file created anywhere."""
    proc = _run(
        f"source {_RC_INTEGRATION}; paperwiki_rc_install",
        env_overrides={
            "SHELL": "/usr/local/bin/fish",
            "HOME": str(tmp_path),
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert list(tmp_path.iterdir()) == [], (
        f"unsupported shell must leave $HOME untouched; saw: {list(tmp_path.iterdir())}"
    )


# ---------------------------------------------------------------------------
# 9.140 — paperwiki_rc_uninstall: remove the block
# ---------------------------------------------------------------------------


def test_rc_uninstall_removes_block_preserving_other_content(
    tmp_path: Path,
) -> None:
    """Uninstall strips the marker block but keeps the rest of the rc."""
    rc = tmp_path / ".zshrc"
    # Install first.
    proc1 = _run(
        f"source {_RC_INTEGRATION}; "
        # Append user content so the file isn't empty before install.
        f"echo \"alias ll='ls -la'\" > {rc}; "
        f"paperwiki_rc_install",
        env_overrides={"SHELL": "/bin/zsh", "HOME": str(tmp_path)},
    )
    assert proc1.returncode == 0, proc1.stderr
    assert _BEGIN_MARKER in rc.read_text(encoding="utf-8")
    # Now uninstall.
    proc2 = _run(
        f"source {_RC_INTEGRATION}; paperwiki_rc_uninstall",
        env_overrides={"SHELL": "/bin/zsh", "HOME": str(tmp_path)},
    )
    assert proc2.returncode == 0, proc2.stderr
    content = rc.read_text(encoding="utf-8")
    assert _BEGIN_MARKER not in content
    assert _END_MARKER not in content
    # User's alias preserved.
    assert "alias ll='ls -la'" in content


def test_rc_uninstall_no_op_when_block_absent(tmp_path: Path) -> None:
    """Uninstall on an rc without the block is a silent no-op."""
    rc = tmp_path / ".zshrc"
    rc.write_text("# user content\n", encoding="utf-8")
    proc = _run(
        f"source {_RC_INTEGRATION}; paperwiki_rc_uninstall",
        env_overrides={"SHELL": "/bin/zsh", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert rc.read_text(encoding="utf-8") == "# user content\n"


def test_rc_uninstall_no_op_when_rc_absent(tmp_path: Path) -> None:
    """Uninstall when rc file doesn't exist is a silent no-op."""
    proc = _run(
        f"source {_RC_INTEGRATION}; paperwiki_rc_uninstall",
        env_overrides={"SHELL": "/bin/zsh", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / ".zshrc").exists()
