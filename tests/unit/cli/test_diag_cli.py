"""Unit tests for the ``paperwiki diag`` CLI subcommand (v0.3.42 D-9.42.1).

Pre-v0.3.42, ``paperwiki_diag`` existed only as a bash function in
``lib/bash-helpers.sh``. Users had to ``source`` the helper before
calling it; the natural ``paperwiki diag --file`` typo (with a space)
returned ``Error: No such command 'diag'``. v0.3.42 D-9.42.1 closes
this gap by adding a Typer subcommand backed by
``paperwiki.runners.diag.render_diag``.

Tests run via :class:`CliRunner` against ``paperwiki.cli.app`` and pin:
- stdout mode (no ``--file``)
- explicit-path file mode (``--file PATH``)
- default-path file mode (``--file`` with no arg) — timestamped under HOME
- the same secret-leak / domain-boundary guarantees as the bash version
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paperwiki.cli import app


@pytest.fixture
def diag_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Stage a fake HOME / claude-home tree, pointed-at via Path.home() patch."""
    home = tmp_path / "home"
    home.mkdir()
    claude_home = home / ".claude"
    claude_home.mkdir()
    # Ensure render_diag's defaults resolve under tmp_path.
    monkeypatch.setattr(Path, "home", lambda: home)
    return {"home": home, "claude_home": claude_home}


def test_diag_default_mode_prints_to_stdout(diag_env: dict[str, Path]) -> None:
    """``paperwiki diag`` (no flag) writes the multi-section dump to stdout."""
    result = CliRunner().invoke(app, ["diag"])
    assert result.exit_code == 0, result.output
    out = result.output
    # Header + footer.
    assert "=== paperwiki_diag — install state ===" in out
    assert "=== end paperwiki_diag ===" in out
    # All seven section dividers.
    for section in (
        "--- helper ---",
        "--- environment ---",
        "--- shim ",
        "--- plugin cache versions ",
        "--- installed_plugins.json (paper-wiki entry) ---",
        "--- recipes ",
    ):
        assert section in out, f"missing section {section!r}\n{out}"


def test_diag_file_flag_with_explicit_path(diag_env: dict[str, Path], tmp_path: Path) -> None:
    """``paperwiki diag --file <path>`` writes to <path> and echoes confirmation."""
    target = tmp_path / "out" / "diag.txt"
    result = CliRunner().invoke(app, ["diag", "--file", str(target)])
    assert result.exit_code == 0, result.output
    assert target.is_file(), f"expected file at {target}"
    content = target.read_text(encoding="utf-8")
    assert "=== paperwiki_diag — install state ===" in content
    # Stdout shows the path written.
    assert f"wrote diag to {target}" in result.output


def test_diag_file_flag_creates_parent_dirs(diag_env: dict[str, Path], tmp_path: Path) -> None:
    """``--file`` mode mkdir-p's missing parents (mirrors bash behaviour)."""
    target = tmp_path / "deep" / "nested" / "dir" / "diag.txt"
    assert not target.parent.exists()
    result = CliRunner().invoke(app, ["diag", "--file", str(target)])
    assert result.exit_code == 0, result.output
    assert target.is_file()


def test_diag_file_flag_without_arg_uses_timestamped_default(
    diag_env: dict[str, Path],
) -> None:
    """``paperwiki diag --file`` (no path) writes to ``$HOME/paper-wiki-diag-<ts>.txt``."""
    home = diag_env["home"]
    result = CliRunner().invoke(app, ["diag", "--file"])
    assert result.exit_code == 0, result.output
    candidates = list(home.glob("paper-wiki-diag-*.txt"))
    assert len(candidates) == 1, candidates
    # ``date +%Y%m%dT%H%M%SZ`` shape: 8 digits, T, 6 digits, Z.
    assert re.match(r"^paper-wiki-diag-\d{8}T\d{6}Z\.txt$", candidates[0].name), (
        f"default filename must be timestamped; got {candidates[0].name!r}"
    )
    # The wrote-diag confirmation echoes the chosen path.
    assert f"wrote diag to {candidates[0]}" in result.output


def test_diag_does_not_dump_secrets_env(
    diag_env: dict[str, Path],
) -> None:
    """CLI mode must not leak ``secrets.env`` content (mirrors bash invariant)."""
    home = diag_env["home"]
    config_dir = home / ".config" / "paper-wiki"
    config_dir.mkdir(parents=True)
    (config_dir / "secrets.env").write_text(
        "PAPERWIKI_S2_API_KEY=DO_NOT_LEAK_42\n", encoding="utf-8"
    )
    result = CliRunner().invoke(app, ["diag"])
    assert result.exit_code == 0, result.output
    assert "DO_NOT_LEAK_42" not in result.output
    assert "PAPERWIKI_S2_API_KEY" not in result.output


def test_diag_subcommand_appears_in_help(diag_env: dict[str, Path]) -> None:
    """``paperwiki --help`` lists ``diag`` so users discover it."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "diag" in result.output, (
        "the diag subcommand must surface in the top-level help, "
        f"otherwise the v0.3.41 'No such command' bug recurs:\n{result.output}"
    )
