"""Unit tests for paperwiki._internal.logging."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from paperwiki._internal.logging import configure_runner_logging

if TYPE_CHECKING:
    import pytest


class TestConfigureRunnerLoggingDefault:
    def test_default_level_is_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """AC-9.15.7: default level is INFO — DEBUG lines must not appear."""
        configure_runner_logging(verbose=False)

        logger.debug("should-not-appear-debug")
        logger.info("should-appear-info")

        captured = capsys.readouterr()
        assert "should-not-appear-debug" not in captured.err, (
            "DEBUG line must not appear when verbose=False"
        )
        assert "should-appear-info" in captured.err, "INFO line must appear at default level"


class TestConfigureRunnerLoggingVerbose:
    def test_verbose_emits_debug(self, capsys: pytest.CaptureFixture[str]) -> None:
        """AC-9.15.8: --verbose enables DEBUG."""
        configure_runner_logging(verbose=True)

        logger.debug("debug-visible-in-verbose")
        logger.info("info-visible-in-verbose")

        captured = capsys.readouterr()
        assert "debug-visible-in-verbose" in captured.err, (
            "DEBUG line must appear when verbose=True"
        )
        assert "info-visible-in-verbose" in captured.err, "INFO line must appear when verbose=True"


class TestConfigureRunnerLoggingEnvOverride:
    def test_paperwiki_log_level_warning_silences_info(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-9.15.6: PAPERWIKI_LOG_LEVEL=WARNING silences INFO."""
        monkeypatch.setenv("PAPERWIKI_LOG_LEVEL", "WARNING")
        configure_runner_logging(verbose=False)

        logger.debug("debug-should-not-appear")
        logger.info("info-should-not-appear")
        logger.warning("warning-should-appear")

        captured = capsys.readouterr()
        assert "debug-should-not-appear" not in captured.err
        assert "info-should-not-appear" not in captured.err
        assert "warning-should-appear" in captured.err
