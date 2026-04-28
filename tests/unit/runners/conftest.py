"""Pytest fixtures for runner unit tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _suppress_runner_log_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppress paperwiki runner log output during CLI tests.

    Sets PAPERWIKI_LOG_LEVEL=WARNING so that configure_runner_logging()
    (called from runner main() when invoked via Typer CliRunner) does not
    mix INFO/DEBUG lines into the captured result.output — which would
    break json.loads() assertions.
    """
    monkeypatch.setenv("PAPERWIKI_LOG_LEVEL", "WARNING")
