"""Unit tests for paperwiki.core.errors.

The error hierarchy classifies every failure into a small, stable set of
buckets so the runner can pick a deterministic exit code without sniffing
exception messages.
"""

from __future__ import annotations

import pytest

from paperwiki.core.errors import (
    IntegrationError,
    PaperWikiError,
    PluginError,
    UserError,
)


class TestErrorHierarchy:
    def test_paperwiki_error_is_root(self) -> None:
        assert issubclass(UserError, PaperWikiError)
        assert issubclass(IntegrationError, PaperWikiError)
        assert issubclass(PluginError, PaperWikiError)

    def test_paperwiki_error_inherits_from_exception(self) -> None:
        assert issubclass(PaperWikiError, Exception)

    def test_user_error_does_not_shadow_system_error(self) -> None:
        # We deliberately avoid the name 'SystemError' which is a builtin.
        # Make sure none of our names collide with builtins.
        assert PaperWikiError.__name__ not in {"SystemError", "OSError", "Exception"}
        assert UserError.__name__ != "SystemError"
        assert IntegrationError.__name__ != "SystemError"


class TestExitCodes:
    def test_user_error_exit_code_is_1(self) -> None:
        assert UserError.exit_code == 1

    def test_integration_error_exit_code_is_2(self) -> None:
        assert IntegrationError.exit_code == 2

    def test_plugin_error_exit_code_is_2(self) -> None:
        assert PluginError.exit_code == 2

    def test_base_paperwiki_error_exit_code_is_2(self) -> None:
        # The default for an unclassified error is "system-style".
        assert PaperWikiError.exit_code == 2


class TestRaiseAndCatch:
    def test_user_error_carries_message(self) -> None:
        with pytest.raises(UserError, match="bad config"):
            raise UserError("bad config: missing 'vault_path'")

    def test_integration_error_carries_message(self) -> None:
        with pytest.raises(IntegrationError, match="rate limit"):
            raise IntegrationError("Semantic Scholar rate limit hit")

    def test_plugin_error_carries_message(self) -> None:
        with pytest.raises(PluginError, match="missing 'fetch'"):
            raise PluginError("ArxivSource missing 'fetch' method")

    def test_user_error_caught_as_paperwiki_error(self) -> None:
        with pytest.raises(PaperWikiError):
            raise UserError("anything")

    def test_paperwiki_error_with_cause(self) -> None:
        original = ValueError("boom")
        with pytest.raises(IntegrationError) as excinfo:
            raise IntegrationError("wrapped") from original
        assert excinfo.value.__cause__ is original
