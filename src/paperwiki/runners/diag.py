"""``paperwiki.runners.diag`` — render the install-state diag dump.

v0.3.42 D-9.42.1 + D-9.42.4. Single source of truth for the diag
output: the ``paperwiki diag`` CLI subcommand calls :func:`render_diag`
directly; ``paperwiki_diag`` bash function in ``lib/bash-helpers.sh``
delegates to the CLI when ``$HOME/.local/bin/paperwiki`` is executable
(D-9.42.4) and falls back to its inline implementation otherwise.

The renderer is a **pure function** — no filesystem writes, no env
mutation, no subprocess spawning. It mirrors the bash function's
seven-section dump:

1. Header
2. ``--- helper ---`` (bash-helpers.sh first line, or ``(not installed)``)
3. ``--- environment ---`` (PATH + CLAUDE_PLUGIN_ROOT)
4. ``--- shim ---`` (paperwiki shim first 2 lines, or ``(not installed)``)
5. ``--- plugin cache versions ---`` (``ls -1`` of cache subdir)
6. ``--- installed_plugins.json (paper-wiki entry) ---`` (domain-bounded
   read of Claude Code's plugin registry — only paper-wiki entry, never
   other plugins, per D-9.40.3)
7. ``--- recipes ---`` (recipe-file names; never content, per D-9.39.3 R2)
8. Footer

Output is **safe to share** when asking for help: prints PATH, the
helper's own version tag, the shim's first two lines, ``ls -1`` of the
cache + recipes dirs, and the paper-wiki entry from
installed_plugins.json. **Never** prints secrets.env, recipe contents,
or other plugins' entries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = ["DiagSections", "render_diag"]


@dataclass(slots=True, frozen=True)
class DiagSections:
    """Materialised diag-dump sections (intermediate value object).

    Splitting the data-collection step from the formatting step keeps
    :func:`render_diag` testable in isolation and lets future callers
    (e.g., a JSON-mode CLI flag) reuse the same data.
    """

    helper_line: str
    """First line of the bash-helpers.sh file, or ``(not installed)``."""

    path_env: str
    """``$PATH`` value as supplied by caller, or ``(unset)``."""

    plugin_root: str
    """``$CLAUDE_PLUGIN_ROOT`` value as supplied by caller, or ``(unset)``."""

    shim_lines: str
    """First two lines of the paperwiki shim, or ``(not installed)``."""

    cache_versions: str
    """Multi-line ``ls -1`` of cache versions, ``(empty)``, or ``(directory does not exist)``."""

    installed_plugins_entry: str
    """JSON-formatted paper-wiki entry, ``(not registered)``, or ``(read failed: ...)``."""

    recipes: str
    """Multi-line recipe filenames, ``(empty)``, or ``(directory does not exist)``."""

    shim_path: Path
    """Path used for the ``--- shim ---`` section header."""

    cache_root: Path
    """Path used for the ``--- plugin cache versions ---`` section header."""

    recipes_dir: Path
    """Path used for the ``--- recipes ---`` section header."""


def _read_helper_line(helper_path: Path) -> str:
    """First line of bash-helpers.sh, or ``(not installed)`` placeholder."""
    if not helper_path.is_file():
        return "(not installed)"
    try:
        with helper_path.open(encoding="utf-8") as fh:
            line = fh.readline().rstrip("\n")
    except OSError as exc:
        return f"(read failed: {exc})"
    return line


def _read_shim_lines(shim_path: Path) -> str:
    """First two lines of the paperwiki shim, joined by ``\\n``."""
    if not shim_path.is_file():
        return "(not installed)"
    try:
        with shim_path.open(encoding="utf-8") as fh:
            line1 = fh.readline().rstrip("\n")
            line2 = fh.readline().rstrip("\n")
    except OSError as exc:
        return f"(read failed: {exc})"
    if line2:
        return f"{line1}\n{line2}"
    return line1


def _list_cache_versions(cache_root: Path) -> str:
    """``ls -1`` of cache subdirs, sorted, or fallback placeholders."""
    if not cache_root.is_dir():
        return "(directory does not exist)"
    entries = sorted(p.name for p in cache_root.iterdir())
    if not entries:
        return "(empty)"
    return "\n".join(entries)


def _read_paper_wiki_entry(installed_plugins: Path) -> str:
    """Domain-bounded read of installed_plugins.json (D-9.40.3 invariant).

    Returns:
        - JSON-formatted paper-wiki entry (indent=2) when present —
          always a JSON list (one dict per scope, the real Claude Code
          shape).
        - ``(not registered)`` when file missing or entry absent
        - ``(read failed: <msg>)`` when JSON malformed or unreadable

    v0.3.43 D-9.43.1: real Claude Code data stores per-plugin entries
    as a list-of-dicts (one entry per scope). v0.3.42 wrapped that
    list in another list, producing ``[[{...}]]`` in the diag output.
    The fix passes the list through unchanged. A defensive coercion
    handles a hypothetical legacy/hand-edited dict shape so the output
    stays a list and the function never crashes.
    """
    if not installed_plugins.is_file():
        return "(not registered)"
    try:
        data = json.loads(installed_plugins.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"(read failed: {exc})"
    plugins = data.get("plugins", {}) if isinstance(data, dict) else {}
    entry = plugins.get("paper-wiki@paper-wiki")
    if entry is None:
        return "(not registered)"
    # Domain boundary: serialize ONLY the paper-wiki entry.
    # v0.3.43 D-9.43.1: real shape is a list — pass through directly.
    # Defensive: if a legacy/hand-edited fixture stored a dict, coerce
    # to a single-element list so the output stays a list (parseable,
    # matches the bash form's expected shape).
    if not isinstance(entry, list):
        entry = [entry]
    return json.dumps(entry, indent=2)


def _list_recipes(recipes_dir: Path) -> str:
    """``ls -1`` of recipe filenames, sorted, or fallback placeholders.

    NEVER reads recipe contents (D-9.39.3 R2).
    """
    if not recipes_dir.is_dir():
        return "(directory does not exist)"
    entries = sorted(p.name for p in recipes_dir.iterdir())
    if not entries:
        return "(empty)"
    return "\n".join(entries)


def collect_sections(
    *,
    home: Path,
    claude_home: Path,
    helper_path: Path | None = None,
    path_env: str | None = None,
    plugin_root: str | None = None,
) -> DiagSections:
    """Gather the seven sections without formatting.

    Pure data-collection. Formatting lives in :func:`render_diag`.
    Defaults match the canonical install layout established by
    ``hooks/ensure-env.sh``:

    - helper at ``$HOME/.local/lib/paperwiki/bash-helpers.sh``
    - shim at ``$HOME/.local/bin/paperwiki``
    - cache root at ``~/.claude/plugins/cache/paper-wiki/paper-wiki``
    - installed_plugins at ``~/.claude/plugins/installed_plugins.json``
    - recipes at ``$HOME/.config/paper-wiki/recipes``
    """
    helper = (
        helper_path
        if helper_path is not None
        else home / ".local" / "lib" / "paperwiki" / "bash-helpers.sh"
    )
    shim = home / ".local" / "bin" / "paperwiki"
    cache_root = claude_home / "plugins" / "cache" / "paper-wiki" / "paper-wiki"
    installed = claude_home / "plugins" / "installed_plugins.json"
    recipes = home / ".config" / "paper-wiki" / "recipes"

    return DiagSections(
        helper_line=_read_helper_line(helper),
        path_env=path_env if path_env is not None else "(unset)",
        plugin_root=plugin_root if plugin_root is not None else "(unset)",
        shim_lines=_read_shim_lines(shim),
        cache_versions=_list_cache_versions(cache_root),
        installed_plugins_entry=_read_paper_wiki_entry(installed),
        recipes=_list_recipes(recipes),
        shim_path=shim,
        cache_root=cache_root,
        recipes_dir=recipes,
    )


def render_diag(
    *,
    home: Path,
    claude_home: Path,
    helper_path: Path | None = None,
    path_env: str | None = None,
    plugin_root: str | None = None,
) -> str:
    """Render the multi-section diag dump as a single string.

    Args:
        home: User's HOME directory (for shim, helper, recipes resolution).
        claude_home: Claude Code's data root (typically ``$HOME/.claude``).
        helper_path: Override path to bash-helpers.sh (defaults to
            ``$HOME/.local/lib/paperwiki/bash-helpers.sh``). Useful for
            tests and callers that source from a non-standard location.
        path_env: Value to render in ``--- environment --- PATH=…``.
            Caller is responsible for passing ``os.environ.get("PATH")``
            (or a substitute) — :func:`render_diag` itself reads no env.
        plugin_root: Value to render in
            ``--- environment --- CLAUDE_PLUGIN_ROOT=…``. Same contract
            as ``path_env``.

    Returns:
        The full multi-section diag dump as a string ending with a
        trailing newline.

    The function is pure: same args produce the same output, no
    filesystem writes occur, no env vars are read or set.
    """
    sections = collect_sections(
        home=home,
        claude_home=claude_home,
        helper_path=helper_path,
        path_env=path_env,
        plugin_root=plugin_root,
    )

    parts = [
        "=== paperwiki_diag — install state ===",
        "--- helper ---",
        sections.helper_line,
        "",
        "--- environment ---",
        f"PATH={sections.path_env}",
        f"CLAUDE_PLUGIN_ROOT={sections.plugin_root}",
        "",
        f"--- shim ({sections.shim_path}) ---",
        sections.shim_lines,
        "",
        f"--- plugin cache versions ({sections.cache_root}) ---",
        sections.cache_versions,
        "",
        "--- installed_plugins.json (paper-wiki entry) ---",
        sections.installed_plugins_entry,
        "",
        f"--- recipes ({sections.recipes_dir}) ---",
        sections.recipes,
        "=== end paperwiki_diag ===",
    ]
    return "\n".join(parts) + "\n"
