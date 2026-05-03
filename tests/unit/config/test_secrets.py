"""Unit tests for ``paperwiki.config.secrets`` (Task 9.180 / D-U).

The secrets loader is the choke point that lets ``paperwiki digest`` (and
other runners that touch user-provided API keys) work from a clean shell
without the user manually running ``source ~/.config/paper-wiki/secrets.env``
beforehand. These tests pin every acceptance bullet from
``tasks/todo.md::Task 9.180`` so the loader can't regress silently.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Sandbox each test's env so secrets-loader assertions stay independent.

    Every key the loader might write or read is cleared up-front; tests that
    need a value set it explicitly. ``PAPERWIKI_NO_AUTO_SECRETS`` is removed
    so opt-out tests can re-set it without inheriting suite-wide state. The
    process-lifetime idempotency guard is also reset so each test sees a
    fresh "first call" — production code never resets, but the test suite
    must.
    """
    for var in (
        "PAPERWIKI_HOME",
        "PAPERWIKI_CONFIG_DIR",
        "PAPERWIKI_NO_AUTO_SECRETS",
        "PAPERWIKI_S2_API_KEY",
        "PAPERWIKI_FOO_KEY",
        "PAPERWIKI_BAR_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    from paperwiki.config import secrets as secrets_mod

    secrets_mod.reset_for_testing()
    yield
    secrets_mod.reset_for_testing()


def _write_secrets(home: Path, body: str, *, mode: int = 0o600) -> Path:
    """Write a ``secrets.env`` under ``home`` and chmod it to ``mode``."""
    home.mkdir(parents=True, exist_ok=True)
    path = home / "secrets.env"
    path.write_text(body, encoding="utf-8")
    path.chmod(mode)
    return path


# ---------------------------------------------------------------------------
# Happy path — basic parsing
# ---------------------------------------------------------------------------


def test_load_secrets_env_sets_environment_variables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``KEY=VALUE`` rows in secrets.env are exported into ``os.environ``."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    _write_secrets(tmp_path, "PAPERWIKI_FOO_KEY=foobarbaz\n")

    from paperwiki.config.secrets import load_secrets_env

    loaded = load_secrets_env()

    assert os.environ["PAPERWIKI_FOO_KEY"] == "foobarbaz"
    assert loaded is not None
    assert loaded.name == "secrets.env"


def test_load_secrets_env_strips_double_and_single_quotes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Values wrapped in matching quotes have the quotes stripped."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    _write_secrets(
        tmp_path,
        "PAPERWIKI_FOO_KEY=\"double quoted\"\nPAPERWIKI_BAR_KEY='single quoted'\n",
    )

    from paperwiki.config.secrets import load_secrets_env

    load_secrets_env()

    assert os.environ["PAPERWIKI_FOO_KEY"] == "double quoted"
    assert os.environ["PAPERWIKI_BAR_KEY"] == "single quoted"


def test_load_secrets_env_honors_export_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lines like ``export KEY=value`` (real shell syntax) parse correctly."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    _write_secrets(tmp_path, "export PAPERWIKI_FOO_KEY=shell_export_value\n")

    from paperwiki.config.secrets import load_secrets_env

    load_secrets_env()

    assert os.environ["PAPERWIKI_FOO_KEY"] == "shell_export_value"


def test_load_secrets_env_skips_comments_and_blank_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank lines and ``#``-prefixed comments do not raise or write env vars."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    _write_secrets(
        tmp_path,
        "# top comment\n\nPAPERWIKI_FOO_KEY=keep_me\n   # indented comment\n\n",
    )

    from paperwiki.config.secrets import load_secrets_env

    load_secrets_env()

    assert os.environ["PAPERWIKI_FOO_KEY"] == "keep_me"


def test_load_secrets_env_does_not_override_existing_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-existing ``os.environ[K]`` wins over the secrets.env value.

    Rationale: explicit shell-exported values reflect the operator's
    intent (e.g. one-off override). A loader that clobbers them would
    surprise users who exported a key for testing.
    """
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    monkeypatch.setenv("PAPERWIKI_FOO_KEY", "from_shell")
    _write_secrets(tmp_path, "PAPERWIKI_FOO_KEY=from_file\n")

    from paperwiki.config.secrets import load_secrets_env

    load_secrets_env()

    assert os.environ["PAPERWIKI_FOO_KEY"] == "from_shell"


# ---------------------------------------------------------------------------
# Opt-out / absence
# ---------------------------------------------------------------------------


def test_load_secrets_env_noop_when_opted_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PAPERWIKI_NO_AUTO_SECRETS=1`` short-circuits before file read."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    monkeypatch.setenv("PAPERWIKI_NO_AUTO_SECRETS", "1")
    _write_secrets(tmp_path, "PAPERWIKI_FOO_KEY=should_not_load\n")

    from paperwiki.config.secrets import load_secrets_env

    loaded = load_secrets_env()

    assert "PAPERWIKI_FOO_KEY" not in os.environ
    assert loaded is None


def test_load_secrets_env_returns_none_when_file_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing ``secrets.env`` is the common fresh-install case — no error."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    # No secrets file written.

    from paperwiki.config.secrets import load_secrets_env

    loaded = load_secrets_env()

    assert loaded is None


# ---------------------------------------------------------------------------
# File mode warning (must be 0600)
# ---------------------------------------------------------------------------


def test_load_secrets_env_warns_when_mode_not_0600(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Loose file modes get a single info-level warning, not a hard error.

    The acceptance criteria call this "info-level, non-blocking" — the
    loader still proceeds because forcing chmod 0600 in CI environments
    where umask differs would block legitimate runs.
    """
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    _write_secrets(
        tmp_path,
        "PAPERWIKI_FOO_KEY=ok\n",
        mode=0o644,
    )

    # ``loguru`` doesn't go through ``logging.getLogger`` by default — bind
    # a propagator so caplog can see the warning. The implementation must
    # use ``logger.warning("secrets.mode.loose", ...)``.
    import logging

    from loguru import logger

    from paperwiki.config.secrets import load_secrets_env

    handler_id = logger.add(
        lambda msg: logging.getLogger("paperwiki.secrets.test").warning(msg),
        level="INFO",
    )
    try:
        with caplog.at_level(logging.WARNING, logger="paperwiki.secrets.test"):
            load_secrets_env()
    finally:
        logger.remove(handler_id)

    # Loader still applied the env var.
    assert os.environ["PAPERWIKI_FOO_KEY"] == "ok"
    # And emitted the warning.
    assert any("secrets.mode.loose" in rec.message for rec in caplog.records)


def test_load_secrets_env_does_not_warn_when_mode_is_0600(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tight 0600 mode is the expected default — no warning emitted."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    _write_secrets(tmp_path, "PAPERWIKI_FOO_KEY=ok\n", mode=0o600)

    import logging

    from loguru import logger

    handler_id = logger.add(
        lambda msg: logging.getLogger("paperwiki.secrets.test").warning(msg),
        level="INFO",
    )
    try:
        with caplog.at_level(logging.WARNING, logger="paperwiki.secrets.test"):
            from paperwiki.config.secrets import load_secrets_env

            load_secrets_env()
    finally:
        logger.remove(handler_id)

    assert not any("secrets.mode.loose" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Idempotency / repeat invocations
# ---------------------------------------------------------------------------


def test_load_secrets_env_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling the loader twice doesn't double-warn or re-clobber env.

    ``RunContext`` plus several entry points all call into the loader, so
    the second-and-later invocations must be effective no-ops.
    """
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))
    _write_secrets(tmp_path, "PAPERWIKI_FOO_KEY=first\n")

    from paperwiki.config.secrets import load_secrets_env

    first = load_secrets_env()
    # Even if a subsequent shell-export hits this var, the loader must
    # not re-overwrite it on the second invocation — first call wins,
    # subsequent calls are no-ops.
    os.environ["PAPERWIKI_FOO_KEY"] = "user_changed"
    second = load_secrets_env()

    assert first is not None
    # Implementation may return ``None`` on second call (cached no-op) or
    # the same path; both are acceptable as long as env was not touched.
    assert second is None or second == first
    assert os.environ["PAPERWIKI_FOO_KEY"] == "user_changed"
