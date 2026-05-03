"""Auto-load ``${PAPERWIKI_HOME}/secrets.env`` into ``os.environ`` (D-U).

Task 9.180 / decision **D-U** (v0.4.2).

The pre-v0.4.2 contract required users to manually run::

    source ~/.config/paper-wiki/secrets.env

before invoking any runner that constructed a source plugin needing API
keys (notably ``semantic_scholar``). A naked ``paperwiki digest`` from a
fresh shell crashed with ``UserError("env var PAPERWIKI_S2_API_KEY is
unset")`` — a footgun for users who didn't read the SKILL prelude.

D-U codifies an automatic loader: every CLI entry point that may touch
user secrets calls :func:`load_secrets_env` before plugin instantiation.
The loader is intentionally minimal — no ``python-dotenv`` dependency —
because the file format we need to support is the same trivial subset
that ``source <file>`` evaluates: ``KEY=VALUE`` rows, optional ``export``
prefix, single- or double-quoted values, ``#`` comments, blank lines.

Behavior contract:

* **Search path**: ``${PAPERWIKI_HOME}/secrets.env`` (resolves through
  :func:`paperwiki._internal.paths.resolve_paperwiki_home`).
* **No-clobber**: an existing ``os.environ[K]`` always wins over the
  file value — explicit shell exports reflect operator intent.
* **Mode hygiene**: file mode is checked once; non-``0600`` triggers a
  single ``loguru.warning("secrets.mode.loose", ...)`` but the load
  proceeds (CI environments with quirky umasks shouldn't fail hard).
* **Opt-out**: ``PAPERWIKI_NO_AUTO_SECRETS=1`` short-circuits before
  any file I/O. Useful for tests and for users who manage secrets via
  another mechanism (1Password CLI, direnv, ...).
* **Idempotent**: a process-wide guard ensures the second-and-later
  calls are no-ops, even if more env vars have been set in between.
* **Absent-file silence**: missing ``secrets.env`` is the fresh-install
  case and never raises — callers that need a key still surface the
  same ``UserError`` they did before from
  :func:`paperwiki.config.recipe._resolve_s2_secrets`.

The loader returns the path it loaded for diagnostic / observability
purposes (``where`` runner, integration tests). Returns ``None`` when
the file was skipped or absent.
"""

from __future__ import annotations

import os
import stat
import threading
from pathlib import Path

from loguru import logger

from paperwiki._internal.paths import resolve_paperwiki_home

ENV_OPT_OUT = "PAPERWIKI_NO_AUTO_SECRETS"
SECRETS_FILENAME = "secrets.env"
EXPECTED_MODE = 0o600

_LOAD_LOCK = threading.Lock()
_LOADED_PATH: Path | None = None
_LOAD_INVOKED: bool = False


def _parse_line(line: str) -> tuple[str, str] | None:
    """Parse a single secrets.env line into ``(key, value)`` or ``None``.

    Returns ``None`` for blank lines, comments, or syntactically
    malformed rows (rather than raising — partial loads are friendlier
    for users than a hard fail mid-file).
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    if "=" not in stripped:
        return None
    key, _, raw_value = stripped.partition("=")
    key = key.strip()
    value = raw_value.strip()
    if not key:
        return None
    # Strip matching quote pairs only — preserve unmatched quotes verbatim
    # so values like ``KEY=he"llo`` round-trip unchanged.
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in ('"', "'")
    ):
        value = value[1:-1]
    return key, value


def _resolve_secrets_path() -> Path:
    """Resolve the canonical secrets file path under ``$PAPERWIKI_HOME``.

    Splitting this out makes the search-path overrideable for tests
    without leaking the env-var lookup into callers.
    """
    return resolve_paperwiki_home() / SECRETS_FILENAME


def _maybe_warn_loose_mode(path: Path) -> None:
    """Emit a single ``secrets.mode.loose`` warning when mode > ``0600``.

    Only the user-permission bits matter (``stat.S_IRWXU``). On macOS the
    OS sometimes adds a ``S_IFREG`` flag that we mask off before
    comparing. Group/world bits are the actual hazard.
    """
    try:
        actual_mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:  # pragma: no cover — defensive guard
        logger.debug("secrets.mode.stat_failed path={path} err={err}", path=path, err=str(exc))
        return
    if actual_mode != EXPECTED_MODE:
        logger.warning(
            "secrets.mode.loose path={path} mode={mode:#o} expected={expected:#o}",
            path=path,
            mode=actual_mode,
            expected=EXPECTED_MODE,
        )


def load_secrets_env(*, path: Path | None = None) -> Path | None:
    """Load ``$PAPERWIKI_HOME/secrets.env`` into ``os.environ`` (idempotent).

    Returns the path that was loaded, or ``None`` if the load was a
    no-op (opt-out, file missing, or already-loaded in this process).

    Parameters
    ----------
    path:
        Override the secrets file path. Tests pass a fixture path here;
        runners pass nothing and let the resolver pick the canonical
        location under ``$PAPERWIKI_HOME``.

    Behavior:
        * ``PAPERWIKI_NO_AUTO_SECRETS=1`` → return ``None`` immediately.
        * Missing file → return ``None`` (silent — fresh install).
        * Existing ``os.environ[K]`` is preserved (no-clobber).
        * Mode != ``0600`` → single warning, load proceeds.
        * Second-and-later invocations short-circuit to ``None``.
    """
    global _LOADED_PATH, _LOAD_INVOKED

    if os.environ.get(ENV_OPT_OUT) == "1":
        return None

    with _LOAD_LOCK:
        if _LOAD_INVOKED:
            # Idempotent — a previous call already either loaded or
            # logged-and-skipped. Don't re-emit warnings or re-overwrite.
            return None
        _LOAD_INVOKED = True

        secrets_path = path if path is not None else _resolve_secrets_path()
        if not secrets_path.exists():
            return None

        _maybe_warn_loose_mode(secrets_path)

        try:
            text = secrets_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "secrets.read_failed path={path} err={err}",
                path=secrets_path,
                err=str(exc),
            )
            return None

        applied = 0
        for raw_line in text.splitlines():
            parsed = _parse_line(raw_line)
            if parsed is None:
                continue
            key, value = parsed
            # No-clobber: keep explicit shell exports.
            if key in os.environ:
                continue
            os.environ[key] = value
            applied += 1

        logger.debug(
            "secrets.loaded path={path} applied={applied}",
            path=secrets_path,
            applied=applied,
        )
        _LOADED_PATH = secrets_path
        return secrets_path


def reset_for_testing() -> None:
    """Clear the idempotency guard. Tests call this between scenarios.

    Production code never calls this — the guard is a process-lifetime
    invariant for runners.
    """
    global _LOADED_PATH, _LOAD_INVOKED
    with _LOAD_LOCK:
        _LOADED_PATH = None
        _LOAD_INVOKED = False


__all__ = [
    "ENV_OPT_OUT",
    "EXPECTED_MODE",
    "SECRETS_FILENAME",
    "load_secrets_env",
    "reset_for_testing",
]
