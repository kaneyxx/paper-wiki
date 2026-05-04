"""Task 9.196 (was 9.150 / D-9.43.1) — direct unit pin for the diag
JSON-shape contract.

The integration test in :mod:`tests.unit.runners.test_diag` covers
the regression at the ``render_diag`` boundary, but the actual fix
lives in :func:`paperwiki.runners.diag._read_paper_wiki_entry`. A
direct unit test pins the helper's contract so a future refactor
that breaks the function (without breaking the higher-level renderer
output) still trips a CI failure.

Three regression invariants pinned here:

1. **List input passes through unchanged.** Real Claude Code stores
   ``installed_plugins.json`` entries as a list of per-scope dicts;
   the function must NOT re-wrap it.
2. **Dict input is coerced to a single-element list** (defensive path
   for legacy / hand-edited fixtures).
3. **Output is always JSON-parseable as a flat list** — never a
   list-of-lists.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from paperwiki.runners.diag import _read_paper_wiki_entry

if TYPE_CHECKING:
    from pathlib import Path


def _write_installed_plugins(path: Path, entry: object) -> None:
    """Helper: write a stub ``installed_plugins.json`` file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"plugins": {"paper-wiki@paper-wiki": entry}}, indent=2),
        encoding="utf-8",
    )


def test_list_entry_passes_through_unchanged(tmp_path: Path) -> None:
    """Real Claude Code shape: list of per-scope dicts.

    The function must emit a flat JSON list with exactly the input
    dicts — no extra wrapping.
    """
    installed = tmp_path / "installed_plugins.json"
    real_shape = [
        {"version": "0.4.7", "scope": "user"},
        {"version": "0.4.7", "scope": "project"},
    ]
    _write_installed_plugins(installed, real_shape)

    out = _read_paper_wiki_entry(installed)
    parsed = json.loads(out)

    assert parsed == real_shape, (
        f"list input must pass through unchanged; got {parsed!r}"
    )
    assert isinstance(parsed, list)
    # Defense-in-depth: confirm it is NOT a list-of-lists.
    assert not all(isinstance(item, list) for item in parsed)


def test_dict_entry_coerced_to_single_element_list(tmp_path: Path) -> None:
    """Legacy / hand-edited fixtures may store a dict instead of a list.

    The function must wrap it in a single-element list so the output
    shape stays uniform — but it must NOT double-wrap (i.e. produce
    ``[[<dict>]]``).
    """
    installed = tmp_path / "installed_plugins.json"
    legacy_shape = {"version": "0.4.7", "scope": "user"}
    _write_installed_plugins(installed, legacy_shape)

    out = _read_paper_wiki_entry(installed)
    parsed = json.loads(out)

    assert parsed == [legacy_shape], (
        f"dict input must coerce to a single-element list; got {parsed!r}"
    )
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert isinstance(parsed[0], dict)


def test_missing_file_returns_not_registered(tmp_path: Path) -> None:
    """Pin the not-JSON sentinel for a missing file."""
    out = _read_paper_wiki_entry(tmp_path / "does-not-exist.json")
    assert out == "(not registered)"


def test_malformed_json_returns_read_failed_marker(tmp_path: Path) -> None:
    """Pin the not-JSON sentinel for a corrupt file."""
    bad = tmp_path / "installed_plugins.json"
    bad.write_text("{this is not json", encoding="utf-8")

    out = _read_paper_wiki_entry(bad)
    assert out.startswith("(read failed:")


def test_missing_paper_wiki_key_returns_not_registered(tmp_path: Path) -> None:
    """File exists, parses, but has no paper-wiki entry."""
    other = tmp_path / "installed_plugins.json"
    other.write_text(
        json.dumps({"plugins": {"other-plugin@other": [{"version": "1.0"}]}}),
        encoding="utf-8",
    )

    out = _read_paper_wiki_entry(other)
    assert out == "(not registered)"


def test_output_is_always_indent_two_when_json(tmp_path: Path) -> None:
    """The contract: when JSON, output uses ``indent=2`` (matches the
    bash form's expected shape per D-9.43.1)."""
    installed = tmp_path / "installed_plugins.json"
    _write_installed_plugins(installed, [{"version": "0.4.7"}])

    out = _read_paper_wiki_entry(installed)
    # ``[\n  {\n`` is the unmistakable indent=2 list-of-dict opener.
    assert out.startswith("[\n  {\n"), (
        f"expected indent=2 JSON shape, got:\n{out!r}"
    )
