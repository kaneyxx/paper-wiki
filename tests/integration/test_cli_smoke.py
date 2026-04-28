"""Integration smoke test for the ``paperwiki`` console-script.

v0.3.27 (Task 9.29 / D-9.29.2) added 7 runner Typer apps plus the
existing 3 lifecycle commands (`update` / `status` / `uninstall`) and
the v0.3.21 `migrate-recipe` to the `paperwiki` console-script via
`app.add_typer`. This test exercises the subprocess path end-to-end so
a regression in module load order, runner renames, or Typer wiring
surfaces in CI rather than at user install time.

Each subcommand is invoked with `--help` to keep the test deterministic
(no recipe / vault state required) and fast (< 5 s for 11 invocations).
The assertion floor is intentionally low: each `--help` exit 0 + the
subcommand name appears in the parent `--help` listing. Anything
deeper would re-test the runner unit tests already cover.

Hard floor: this file runs in CI on every commit. A failure here
means `paperwiki <name>` from a fresh terminal is broken.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

_EXPECTED_COMMANDS: tuple[str, ...] = (
    "update",
    "status",
    "uninstall",
    "migrate-recipe",
    "digest",
    "wiki-ingest",
    "wiki-lint",
    "wiki-compile",
    "wiki-query",
    "extract-images",
    "migrate-sources",
    "gc-archive",
    "gc-bak",
    "where",
)


def _run_paperwiki(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke ``python -m paperwiki.cli ...`` as a subprocess.

    Uses the Python interpreter currently running pytest so the venv
    matches; no PATH lookup risk.
    """
    return subprocess.run(
        [sys.executable, "-m", "paperwiki.cli", *args],
        capture_output=True,
        text=True,
        timeout=10,
        env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"},
    )


class TestParentSurface:
    def test_paperwiki_help_lists_every_subcommand(self) -> None:
        result = _run_paperwiki("--help")
        assert result.returncode == 0, result.stderr
        for name in _EXPECTED_COMMANDS:
            assert name in result.stdout, (
                f"`paperwiki {name}` missing from `paperwiki --help` output"
            )


class TestSubcommandHelp:
    """Each subcommand's ``--help`` exits 0 from a clean subprocess."""

    @pytest.mark.parametrize("name", _EXPECTED_COMMANDS)
    def test_subcommand_help_exits_clean(self, name: str) -> None:
        result = _run_paperwiki(name, "--help")
        assert result.returncode == 0, (
            f"`paperwiki {name} --help` exited {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestPythonModuleParity:
    """Each renamed runner remains invocable as ``python -m paperwiki.runners.<X>``.

    v0.3.27 changed `@app.command()` to `@app.command(name="<cli-X>")` on
    7 runners. Typer's single-command auto-promotion should preserve the
    `python -m paperwiki.runners.<X>` invocation pattern, but this test
    pins the contract.
    """

    @pytest.mark.parametrize(
        "runner_module",
        [
            "paperwiki.runners.digest",
            "paperwiki.runners.wiki_ingest_plan",
            "paperwiki.runners.wiki_lint",
            "paperwiki.runners.wiki_compile",
            "paperwiki.runners.wiki_query",
            "paperwiki.runners.extract_paper_images",
            "paperwiki.runners.migrate_sources",
            "paperwiki.runners.migrate_recipe",
            "paperwiki.runners.gc_digest_archive",
            "paperwiki.runners.gc_bak",
            "paperwiki.runners.where",
        ],
    )
    def test_python_dash_m_help_still_works(self, runner_module: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", runner_module, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"},
        )
        assert result.returncode == 0, (
            f"`python -m {runner_module} --help` exited {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
