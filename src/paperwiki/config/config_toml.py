"""Read ``~/.config/paper-wiki/config.toml`` (Task 9.192 / decision **D-V**).

The user-level config file is intentionally minimal in v0.4.5 — two
top-level keys only:

.. code-block:: toml

    default_vault = "~/Documents/Paper-Wiki"
    default_recipe = "~/.config/paper-wiki/recipes/daily.yaml"

Both keys are optional. The reader returns a :class:`ConfigToml` model
with ``None`` for unset fields so callers (notably
:func:`paperwiki.config.vault_resolver.resolve_vault`) can blend the
config with higher-priority sources.

Why a TOML file and not YAML / JSON?

* TOML is the Python ecosystem default for user config (PEP 518/621).
* No third-party dependency: ``tomllib`` lives in the stdlib since
  Python 3.11, which is paper-wiki's minimum.
* User-friendly diff — line-oriented, no significant indentation.

Forward-compat: unknown top-level keys are ignored at parse time so a
v0.4.6+ paper-wiki release can add fields without breaking older
readers that happen to read the same file (e.g. when a user installs
multiple paper-wiki versions side-by-side).

Tilde expansion happens at read time so callers always see absolute
:class:`pathlib.Path` instances.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from paperwiki._internal.paths import resolve_paperwiki_home
from paperwiki.core.errors import UserError

CONFIG_FILENAME = "config.toml"


class ConfigToml(BaseModel):
    """Typed view of ``$PAPERWIKI_HOME/config.toml`` (D-V minimal schema).

    Both fields default to ``None`` so a missing file behaves identically
    to a present-but-empty file. The :func:`read_config` helper expands
    any tilde in path values so consumers never have to call
    ``Path.expanduser()`` themselves.
    """

    # ``extra="ignore"`` is the forward-compat lever — unknown top-level
    # keys (likely added in v0.4.6+) silently pass through without
    # raising on older readers.
    model_config = ConfigDict(extra="ignore")

    default_vault: Path | None = None
    default_recipe: Path | None = None


def _resolve_config_path() -> Path:
    """Return the canonical ``$PAPERWIKI_HOME/config.toml`` location."""
    return resolve_paperwiki_home() / CONFIG_FILENAME


def _expand_path_field(raw: object) -> Path:
    """Coerce a raw TOML string into an expanded :class:`Path`.

    TOML decoder gives us ``str``; we tilde-expand and return an
    absolute-when-tilde-present Path. Non-string inputs raise a
    :class:`UserError` so a malformed TOML payload does not crash the
    whole resolver mid-run.
    """
    if not isinstance(raw, str):
        raise UserError(f"config.toml: expected string path, got {type(raw).__name__}")
    return Path(raw).expanduser()


def read_config(*, path: Path | None = None) -> ConfigToml:
    """Parse ``$PAPERWIKI_HOME/config.toml`` (or the supplied path).

    Parameters
    ----------
    path:
        Override the file location. Tests pass a fixture path here;
        runners pass nothing and let the resolver pick the canonical
        location under ``$PAPERWIKI_HOME``.

    Returns
    -------
    ConfigToml
        Model populated from the file, or an empty model when the file
        is absent (the fresh-install case — resolver falls back).

    Raises
    ------
    UserError
        Only when the file exists but TOML parsing fails. Missing files
        and unknown keys are silent (forward-compat).
    """
    target = path if path is not None else _resolve_config_path()
    if not target.exists():
        return ConfigToml()

    try:
        raw_text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserError(f"config.toml: cannot read {target}: {exc}") from exc

    try:
        data = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError as exc:
        # ``TOMLDecodeError`` carries the offending line in its message
        # (Python 3.11+). Surface it verbatim so users can fix the file
        # without trial-and-error — see the matching unit test.
        line = _extract_line_number(exc)
        raise UserError(f"config.toml: malformed TOML at {target} (line {line}): {exc}") from exc

    # Tilde-expand path-like fields before pydantic coerces them.
    if "default_vault" in data:
        data["default_vault"] = _expand_path_field(data["default_vault"])
    if "default_recipe" in data:
        data["default_recipe"] = _expand_path_field(data["default_recipe"])

    return ConfigToml(**data)


def _extract_line_number(exc: tomllib.TOMLDecodeError) -> str:
    """Pull a line number out of a ``TOMLDecodeError`` message.

    Python's ``tomllib`` formats the error as ``"... at line N column M"``
    in its ``__str__``; we surface the integer when present so the
    UserError message is more helpful than the bare exception text.
    """
    msg = str(exc)
    marker = "line "
    idx = msg.find(marker)
    if idx == -1:
        return "?"
    rest = msg[idx + len(marker) :]
    digits = rest.split(",", 1)[0].split(" ", 1)[0].strip().rstrip(":")
    return digits or "?"


__all__ = [
    "CONFIG_FILENAME",
    "ConfigToml",
    "read_config",
]
