"""Central path resolution for paperwiki — single source of truth for
``$PAPERWIKI_HOME`` and the resources that live under it (recipes,
secrets, shared venv).

Task 9.31 / D-9.31.1 — D-9.31.2 (v0.3.29). All paperwiki user state
co-locates under one root so users can inspect / clean / sync the
entire footprint with one command. The default root is
``~/.config/paper-wiki/`` — see plan §11 for the rationale.

Env-var precedence chain (highest to lowest)::

    PAPERWIKI_VENV_DIR   # finer-grained override for venv only
    PAPERWIKI_HOME       # canonical root (v0.3.29+)
    PAPERWIKI_CONFIG_DIR # legacy alias from v0.3.4+
    (default)            # ~/.config/paper-wiki

Empty strings are treated as unset so that
``PAPERWIKI_HOME="" PAPERWIKI_CONFIG_DIR=/legacy paperwiki status`` does
the right thing (falls through to the legacy var).
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_HOME: Path = Path.home() / ".config" / "paper-wiki"


def _env_path(name: str) -> Path | None:
    """Return ``Path(os.environ[name])`` or ``None`` if unset/empty.

    Empty strings are treated as unset because shell users sometimes
    set ``export PAPERWIKI_HOME=""`` to "clear" a variable, and we
    want that to behave like ``unset PAPERWIKI_HOME`` rather than
    pinning the cwd as the home dir.
    """
    raw = os.environ.get(name)
    if not raw:
        return None
    return Path(raw).expanduser()


def resolve_paperwiki_home() -> Path:
    """Return the canonical ``$PAPERWIKI_HOME`` (v0.3.29).

    Honors ``PAPERWIKI_HOME`` first; falls back to the legacy
    ``PAPERWIKI_CONFIG_DIR`` (v0.3.4 - v0.3.28); defaults to
    ``~/.config/paper-wiki/``.

    Returns the absolute, ``~``-expanded path. The directory may not
    exist yet — callers create it on demand.
    """
    return _env_path("PAPERWIKI_HOME") or _env_path("PAPERWIKI_CONFIG_DIR") or DEFAULT_HOME


def resolve_paperwiki_venv_dir() -> Path:
    """Return the shared venv directory (v0.3.29+).

    Default: ``${PAPERWIKI_HOME}/venv`` (so the venv co-locates with
    recipes + secrets under one root). The optional
    ``PAPERWIKI_VENV_DIR`` env var overrides for users who want config
    in the default but venv elsewhere (e.g. on a different disk).
    """
    return _env_path("PAPERWIKI_VENV_DIR") or (resolve_paperwiki_home() / "venv")


def resolve_paperwiki_recipes_dir() -> Path:
    """Return the recipes directory.

    Always ``${PAPERWIKI_HOME}/recipes``. There is intentionally no
    separate override — the whole point of v0.3.29's single-root
    design is that you point ``PAPERWIKI_HOME`` once and everything
    follows.
    """
    return resolve_paperwiki_home() / "recipes"


__all__ = [
    "DEFAULT_HOME",
    "resolve_paperwiki_home",
    "resolve_paperwiki_recipes_dir",
    "resolve_paperwiki_venv_dir",
]
