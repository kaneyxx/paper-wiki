"""Tests for the v0.4.2 ``paperwiki update`` post-upgrade migration hint.

Task 9.188 (D-T): when ``paperwiki update`` finishes, it scans the
user's known recipe vaults (parsed from
``$PAPERWIKI_HOME/recipes/*.yaml``) for surviving
``Wiki/sources/<id>.md`` files and emits a single-line hint inside
the existing "Next:" block — both in the "already at <ver>" no-op
branch AND the upgrade summary branch. The hint disappears once the
user runs ``paperwiki wiki-compile`` (which auto-fires the migration,
per Task 9.187).

Behavior contract pinned by these tests:

* Hint emitted exactly once per known vault that still has
  ``Wiki/sources/*.md``.
* Hint suppressed when no recipes exist (fresh install — no false
  positive).
* Hint suppressed when every known vault is already on the v0.4.2
  layout.
* ``PAPERWIKI_NO_AUTO_DETECT=1`` opts out entirely (CI / privacy).
* Recipes that don't carry an ``obsidian.vault_path`` (e.g. plain-
  markdown reporters) are silently skipped.
"""

from __future__ import annotations

from pathlib import Path

from paperwiki._internal.legacy_vault_scan import (
    ENV_NO_AUTO_DETECT,
    scan_known_vaults_for_legacy_sources,
)


def _write_recipe(recipes_dir: Path, name: str, vault_path: Path) -> Path:
    """Write a minimal recipe YAML pointing at ``vault_path``.

    Mirrors the canonical shape: a ``reporters`` list with an entry
    whose ``name == "obsidian"`` and ``config.vault_path`` set.
    """
    recipes_dir.mkdir(parents=True, exist_ok=True)
    path = recipes_dir / name
    path.write_text(
        "name: synthetic\n"
        "sources:\n"
        "  - name: arxiv\n"
        "    config: { categories: [cs.CV] }\n"
        "reporters:\n"
        "  - name: obsidian\n"
        "    config:\n"
        f"      vault_path: {vault_path}\n",
        encoding="utf-8",
    )
    return path


def _seed_legacy(vault: Path) -> None:
    sources = vault / "Wiki" / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "arxiv_2506.13063.md").write_text(
        "---\ncanonical_id: arxiv:2506.13063\n---\nlegacy",
        encoding="utf-8",
    )


def _seed_canonical(vault: Path) -> None:
    papers = vault / "Wiki" / "papers"
    papers.mkdir(parents=True, exist_ok=True)
    (papers / "arxiv_2506.13063.md").write_text(
        "---\ncanonical_id: arxiv:2506.13063\n---\nmigrated",
        encoding="utf-8",
    )


def test_emits_paths_for_legacy_vaults(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A vault with surviving ``Wiki/sources/*.md`` shows up in the
    helper's return value."""
    home = tmp_path / "paperwiki-home"
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_legacy(vault)
    _write_recipe(home / "recipes", "daily.yaml", vault)
    monkeypatch.setenv("PAPERWIKI_HOME", str(home))
    monkeypatch.delenv(ENV_NO_AUTO_DETECT, raising=False)

    legacy_vaults = scan_known_vaults_for_legacy_sources()

    assert legacy_vaults == [vault.resolve()]


def test_no_hint_when_already_migrated(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A vault entirely on v0.4.2 layout (only ``Wiki/papers/``)
    is silently dropped — nothing to migrate."""
    home = tmp_path / "paperwiki-home"
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_canonical(vault)
    _write_recipe(home / "recipes", "daily.yaml", vault)
    monkeypatch.setenv("PAPERWIKI_HOME", str(home))
    monkeypatch.delenv(ENV_NO_AUTO_DETECT, raising=False)

    assert scan_known_vaults_for_legacy_sources() == []


def test_no_hint_for_fresh_install(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Fresh install — no recipes anywhere — must NOT emit a hint."""
    home = tmp_path / "paperwiki-home"
    home.mkdir()
    monkeypatch.setenv("PAPERWIKI_HOME", str(home))
    monkeypatch.delenv(ENV_NO_AUTO_DETECT, raising=False)

    assert scan_known_vaults_for_legacy_sources() == []


def test_respects_no_auto_detect_env(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """``PAPERWIKI_NO_AUTO_DETECT=1`` opts out entirely."""
    home = tmp_path / "paperwiki-home"
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_legacy(vault)
    _write_recipe(home / "recipes", "daily.yaml", vault)
    monkeypatch.setenv("PAPERWIKI_HOME", str(home))
    monkeypatch.setenv(ENV_NO_AUTO_DETECT, "1")

    assert scan_known_vaults_for_legacy_sources() == []


def test_recipes_without_obsidian_reporter_skipped(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A recipe with only the plain-markdown reporter has no
    ``vault_path`` to scan; helper must not crash and must not emit."""
    home = tmp_path / "paperwiki-home"
    recipes = home / "recipes"
    recipes.mkdir(parents=True)
    (recipes / "no_obsidian.yaml").write_text(
        "name: plain\n"
        "sources:\n"
        "  - name: arxiv\n"
        "    config: { categories: [cs.CV] }\n"
        "reporters:\n"
        "  - name: markdown\n"
        "    config:\n"
        "      output_dir: /tmp/out\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PAPERWIKI_HOME", str(home))
    monkeypatch.delenv(ENV_NO_AUTO_DETECT, raising=False)

    assert scan_known_vaults_for_legacy_sources() == []


def test_dedupes_when_two_recipes_point_at_same_vault(
    tmp_path,  # type: ignore[no-untyped-def]
    monkeypatch,
) -> None:
    """Two recipes pointing at the same vault → vault appears once
    in the result list."""
    home = tmp_path / "paperwiki-home"
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    _seed_legacy(vault)
    _write_recipe(home / "recipes", "daily.yaml", vault)
    _write_recipe(home / "recipes", "weekly.yaml", vault)
    monkeypatch.setenv("PAPERWIKI_HOME", str(home))
    monkeypatch.delenv(ENV_NO_AUTO_DETECT, raising=False)

    assert scan_known_vaults_for_legacy_sources() == [vault.resolve()]


def test_malformed_recipe_does_not_crash(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Garbage YAML in ``$PAPERWIKI_HOME/recipes/`` must NOT crash
    ``paperwiki update`` — the helper just skips the broken file
    and proceeds with the others."""
    home = tmp_path / "paperwiki-home"
    recipes = home / "recipes"
    recipes.mkdir(parents=True)
    (recipes / "broken.yaml").write_text("this: is: not: valid: yaml:\n", encoding="utf-8")
    # Plus one valid recipe so we can verify it's still surfaced.
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_legacy(vault)
    _write_recipe(recipes, "daily.yaml", vault)
    monkeypatch.setenv("PAPERWIKI_HOME", str(home))
    monkeypatch.delenv(ENV_NO_AUTO_DETECT, raising=False)

    assert scan_known_vaults_for_legacy_sources() == [vault.resolve()]


def test_placeholder_vault_path_is_skipped(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A bundled template recipe with ``vault_path: <EDIT_ME_BEFORE_USE>``
    must NOT trigger the hint — that placeholder is not a real
    user-configured path."""
    home = tmp_path / "paperwiki-home"
    recipes = home / "recipes"
    recipes.mkdir(parents=True)
    (recipes / "template.yaml").write_text(
        "name: tpl\n"
        "sources:\n"
        "  - name: arxiv\n"
        "    config: { categories: [cs.CV] }\n"
        "reporters:\n"
        "  - name: obsidian\n"
        "    config:\n"
        "      vault_path: <EDIT_ME_BEFORE_USE>\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PAPERWIKI_HOME", str(home))
    monkeypatch.delenv(ENV_NO_AUTO_DETECT, raising=False)

    assert scan_known_vaults_for_legacy_sources() == []


def test_format_migration_hint_empty_returns_empty_string() -> None:
    """Empty input → empty string so callers can append unconditionally."""
    from paperwiki._internal.legacy_vault_scan import format_migration_hint

    assert format_migration_hint([]) == ""


def test_format_migration_hint_renders_user_visible_command(tmp_path: Path) -> None:
    """The hint includes the literal ``paperwiki wiki-compile <vault>``
    command (no slash-form), which is what the user types from a
    fresh terminal — slash-form would be wrong because they're in
    the shell, not Claude Code."""
    from paperwiki._internal.legacy_vault_scan import format_migration_hint

    hint = format_migration_hint([tmp_path / "vault"])

    assert "Vault migration pending" in hint
    assert f"paperwiki wiki-compile {tmp_path / 'vault'}" in hint
    # Reassures the user the move is safe.
    assert "SHA-256" in hint or "backup" in hint.lower()
