"""Discover known vaults that still carry v0.3.x ``Wiki/sources/`` data.

Task 9.188 / decision **D-T** (v0.4.2). When ``paperwiki update``
finishes, the user-visible "Next:" block gains a single-line hint
per vault that hasn't yet run the v0.3.x → v0.4.2 layout migration:

    Vault migration pending — run:
      paperwiki wiki-compile <vault>
    from a fresh terminal (idempotent; uses SHA-256 backup).

The hint is observational — it never modifies the user's files. The
actual migration runs on the user's command via Task 9.187's
auto-fire path inside ``paperwiki wiki-compile``.

Behavior contract:

* **Search path**: ``${PAPERWIKI_HOME}/recipes/*.yaml`` (resolves
  through :func:`paperwiki._internal.paths.resolve_paperwiki_home`).
* **Vault extraction**: parses each recipe's ``reporters`` list,
  picks the entry whose ``name == "obsidian"``, reads
  ``config.vault_path``. Recipes without an Obsidian reporter
  contribute no vault.
* **Legacy detection**: ``<vault>/Wiki/sources/*.md`` non-empty AND
  the path is a directory.
* **Dedupe**: two recipes pointing at the same vault produce one
  entry in the output list (sorted, resolved).
* **Opt-out**: ``PAPERWIKI_NO_AUTO_DETECT=1`` short-circuits before
  any filesystem scan. Same shape as the secrets-loader opt-out
  (D-U, Phase A).
* **Robustness**: malformed YAML, missing ``vault_path``, or vaults
  that no longer exist on disk are silently skipped — the update
  flow MUST NOT crash on garbage in the recipes dir.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from paperwiki._internal.paths import resolve_paperwiki_home

ENV_NO_AUTO_DETECT = "PAPERWIKI_NO_AUTO_DETECT"
RECIPES_SUBDIR = "recipes"
LEGACY_VAULT_GLOB = "Wiki/sources/*.md"


def _extract_vault_path(recipe_path: Path) -> Path | None:
    """Return the obsidian-reporter ``vault_path`` from a recipe, or None.

    Tolerates malformed YAML / missing keys / wrong types — callers
    of :func:`scan_known_vaults_for_legacy_sources` must NEVER see
    an exception bubble up from here.
    """
    try:
        data: Any = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.debug(
            "legacy_vault_scan.parse_failed path={path} err={err}",
            path=str(recipe_path),
            err=str(exc),
        )
        return None

    if not isinstance(data, dict):
        return None
    reporters = data.get("reporters")
    if not isinstance(reporters, list):
        return None
    for reporter in reporters:
        if not isinstance(reporter, dict):
            continue
        if reporter.get("name") != "obsidian":
            continue
        config = reporter.get("config")
        if not isinstance(config, dict):
            continue
        raw = config.get("vault_path")
        if not isinstance(raw, str) or not raw.strip():
            return None
        # Reject placeholder strings shipped by template recipes —
        # the bundled ``recipes/daily-arxiv.yaml`` has
        # ``vault_path: <EDIT_ME_BEFORE_USE>`` and we don't want
        # that bogus value to land in the hint.
        if raw.strip().startswith("<") and raw.strip().endswith(">"):
            return None
        return Path(raw).expanduser()
    return None


def _has_legacy_files(vault: Path) -> bool:
    legacy_dir = vault / "Wiki" / "sources"
    if not legacy_dir.is_dir():
        return False
    return any(legacy_dir.glob("*.md"))


def scan_known_vaults_for_legacy_sources() -> list[Path]:
    """Return resolved paths of known vaults that still carry legacy
    ``Wiki/sources/*.md`` files. Order: deterministic (sorted).

    See module docstring for the full behavior contract.
    """
    if os.environ.get(ENV_NO_AUTO_DETECT) == "1":
        return []

    recipes_dir = resolve_paperwiki_home() / RECIPES_SUBDIR
    if not recipes_dir.is_dir():
        return []

    seen: set[Path] = set()
    for recipe_path in sorted(recipes_dir.glob("*.yaml")):
        vault = _extract_vault_path(recipe_path)
        if vault is None:
            continue
        try:
            resolved = vault.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        if not _has_legacy_files(resolved):
            continue
        seen.add(resolved)

    return sorted(seen)


def format_migration_hint(vaults: list[Path]) -> str:
    """Render the user-visible hint string for a non-empty vault
    list. Empty list → empty string (callers can append blindly)."""
    if not vaults:
        return ""
    lines: list[str] = ["", "Vault migration pending (v0.3.x → v0.4.2) — run:"]
    lines.extend(f"  paperwiki wiki-compile {vault}" for vault in vaults)
    lines.append("from a fresh terminal (idempotent; SHA-256 backup at")
    lines.append("``<vault>/.paperwiki/migration-backup/<ts>/``).")
    return "\n".join(lines)


__all__ = [
    "ENV_NO_AUTO_DETECT",
    "LEGACY_VAULT_GLOB",
    "RECIPES_SUBDIR",
    "format_migration_hint",
    "scan_known_vaults_for_legacy_sources",
]
