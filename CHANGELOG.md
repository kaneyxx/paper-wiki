# Changelog

All notable changes to **paper-wiki** are documented here. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

The plugin protocol stays `@experimental` until v1.0; minor versions
before then may break it.

## [Unreleased]

## [0.4.7] - 2026-05-04

Phase E + post-launch UX hot-fixes from v0.4.6 real-machine smoke.
Closes the gap that left `paperwiki update` (v0.4.4 → v0.4.6) users
with a working binary but broken `--vault`-optional CLI commands
because nothing wrote `~/.config/paper-wiki/config.toml`.

### Added

- **D-V resolver default auto-write on upgrade** (Task 9.212) —
  `paperwiki update` post-upgrade hook now backfills
  `$PAPERWIKI_HOME/config.toml` from a single recipe with
  `obsidian.vault_path`. Idempotent (never clobbers an existing
  file); silent when `recipes/` is empty, multi-recipe (ambiguous),
  or recipe lacks `vault_path`.
- **`config_toml.write_config()`** — sibling of `read_config`,
  used by both 9.212 (auto-create) and 9.213 (setup wizard).
  Refuses to clobber unless `force=True`; refuses to write an
  empty stub.
- **`/paper-wiki:setup` SKILL writes `config.toml`** (Task 9.213) —
  new Step 9c emits the resolver default at the same moment the
  recipe is saved. Mirrors the recipe-overwrite policy on re-run.

### Changed

- **Visible runner errors across the CLI surface** (Task 9.211) —
  7 catch sites in 5 runners (`wiki_graph_query`, `wiki_compile` ×3,
  `wiki_lint`, `extract_paper_images`, `migrate_sources`) now emit
  the actual `PaperWikiError` message text on stderr instead of
  only the bare `<runner>.failed` event line. Loguru's structured
  `error=str(exc)` field is rendered as a hidden `extra` by the
  default sink, so without an explicit `typer.echo` users saw
  opaque event names with no actionable hint. Already-correct
  runners (`digest`, `recipe_validate`, `migrate_recipe`,
  `wiki_query`, `wiki_ingest_plan`) gain regression-pin tests.
- **`paperwiki_diag` bash helper warning text** (Task 9.198) —
  stale-version warning now spells out SPEC §8.1's full 5-step
  upgrade flow inline (`paperwiki update` → `/exit` → `claude` →
  `/plugin install paper-wiki@paper-wiki` → `/exit && claude`)
  instead of the bare "open a new terminal" hint that hid the
  v0.4.0 hardcode bug for two days.

### Fixed

- **`wiki-graph` graceful degradation on empty vault** (Task 9.210) —
  fresh-installed or freshly-wiped vaults (no `Wiki/` subdir) now
  emit `[]` (JSON) or `"No edges matched."` (`--pretty`) and exit 0
  instead of crashing with `PaperWikiError: wiki root missing: ...`.
  Reported by maintainer in v0.4.6 real-machine smoke as the first
  command they ran after upgrading.

### Verified

- 1512 unit tests pass (1460 baseline + 52 new across 9.210/211/196/
  197/198/212/213).
- `ruff check src tests` clean. `ruff format --check src tests` clean.
- `mypy --strict src` clean.
- `claude plugin validate .` clean.

### Internal

- **Regression pins for v0.3.43 fixes** (Tasks 9.196, 9.197) —
  source already correct since v0.3.43 D-9.43.1 (`paperwiki diag`
  flat-array JSON) and D-9.43.4 (`update --check` message order);
  this release adds direct unit pins on the helpers
  (`_read_paper_wiki_entry`, `_print_update_check_plan`,
  `_consume_rc_just_added_stamp`) so future refactors that split
  format from ordering can't quietly regress.

### Notes

- **9.199 (Fish shell support)** remains deferred to v0.5+.
- **9.214 (resolver Rung 2.5 — auto-discover single recipe)**
  deferred — re-evaluate if 9.212/9.213 prove insufficient on
  fresh-install paths.

## [0.4.6] - 2026-05-04

Phase C — `migrate-recipe` hardening (D-W companion + D-Y stamp).
Closes the v0.4 schema-migration gap exposed in v0.4.0 real-machine
smoke (a SKILL session "fixing" the schema error by silently
substituting v0.4 default weights, destroying the user's tuning).

### Added

- **`<recipe>.pre-v04.bak` backup mechanism** (Task 9.189) — schema
  migration now creates a one-shot byte-identical backup adjacent to
  the original recipe. Pre-existing `.pre-v04.bak` blocks
  re-migration with an actionable error pointing the user at
  `--restore` or manual deletion (avoids double-overwrite).
- **`paperwiki migrate-recipe --restore <path>`** flag swaps the
  `<recipe>.pre-v04.bak` content back in place and removes the .bak
  (one-shot, no leftovers). Refuses cleanly when no .bak exists.
- **`map_pre_v04_to_v04_weights` pure mapping** (Task 9.190) — translates
  `keyword`/`category`/`recency` weights to v0.4
  `relevance`/`novelty`/`momentum`/`rigor` axes via:
  - `relevance = clip(keyword + 0.5 * category, 0.4, 0.85)`
  - `novelty = 0.10` (conservative default — "user never opted in")
  - `rigor = 0.05` (same rationale)
  - `momentum = 1 - relevance - novelty - rigor` (residual)
  - `recency` axis silently dropped (it's a filter now, not a scorer
    axis); the recipe's existing recency filter block is preserved.
- **D-Y round-trip stamp** (Task 9.190) — every successful
  `migrate-recipe` run prepends (or replaces) a single
  `# round-trip stamp YYYY-MM-DD vX.Y.Z` comment at the top of the
  YAML so "did the user opt into this version?" is one grep away.
  Multiple consecutive runs replace rather than stack, keeping the
  recipe header tidy.

### Changed

- `migrate_recipe_file` now runs in two tiers: v0.4 schema migration
  first (creates `.pre-v04.bak`, applies mapping), then the existing
  v0.3.17-era keyword migrations (preserves timestamped backups for
  multi-pivot history). The D-Y stamp is applied at the very end so
  even an already-current recipe gains a fresh audit comment.
- Existing `test_clean_recipe_is_noop` was tightened to assert the
  body BELOW the stamp line is byte-identical (the stamp itself is
  the deliberate D-Y mutation).

### Verified (no code change)

- `RecipeSchemaError.__str__` was already locked to use the slash form
  `/paper-wiki:migrate-recipe <path>` since Phase A (v0.4.2 / Task
  9.181). Task 9.191 adds an explicit regression test naming the
  task number as the contract anchor — a future grep for "9.191"
  now surfaces the relevant guard.

### Notes

- Test count: **1460 passed** (1440 baseline + 20 new). `mypy
  --strict`, `ruff check`, `ruff format --check`, and `claude plugin
  validate .` all clean.
- Real-machine smoke (planned post-merge): run `paperwiki
  migrate-recipe ~/.config/paper-wiki/recipes/daily.yaml` on the
  maintainer's already-v04 recipe — expect a body-no-op + fresh
  stamp at the top of the file, no `.pre-v04.bak` created.

## [0.4.5] - 2026-05-04

Phase D — CLI ergonomic alignment per **D-V**. Four runners that
historically required an explicit ``<vault>`` argument now accept it
optionally and fall through a precedence chain that ends in a new
``~/.config/paper-wiki/config.toml`` user config. The two-form CLI
keeps every existing invocation working unchanged.

### Added

- **`paperwiki.config.config_toml`** (Task 9.192) — typed reader for
  ``$PAPERWIKI_HOME/config.toml`` with the v0.4.5 minimal schema
  (``default_vault``, ``default_recipe``). Both fields optional;
  ``extra="ignore"`` for forward-compat against v0.4.6+ extensions;
  tilde-expansion at read time so callers always see absolute paths;
  malformed TOML surfaces as a ``UserError`` that names the offending
  line.
- **`paperwiki.config.vault_resolver`** (Task 9.192) — pure D-V
  precedence-chain resolver: explicit ``Path`` →
  recipe ``obsidian.vault_path`` → ``$PAPERWIKI_DEFAULT_VAULT`` →
  ``config.toml::default_vault`` → ``UserError`` whose message names
  every override path so SKILLs can render the action hint verbatim.

### Changed

- **`paperwiki extract-images <id>`** (Task 9.193) accepts a single
  positional arg (canonical id) when the vault is resolvable from
  env or config. Two-arg form ``extract-images <vault> <id>`` is
  preserved. Disambiguation rule: a single positional containing
  ``:`` is treated as a canonical id; otherwise the CLI rejects with
  a usage hint pointing at the missing canonical id.
- **`paperwiki wiki-graph`** (Task 9.194) makes the vault positional
  optional — ``wiki-graph --papers-citing <slug>`` works once a
  default vault is configured. Resolved vault is validated as an
  existing directory before the query runs (clean error on bad
  paths instead of a noisy stack trace).
- **`paperwiki dedup-list` / `dedup-dismiss` / `gc-dedup-ledger`**
  (Task 9.195) — the ``--vault`` flag is now optional on all three
  commands; absence triggers the same resolver chain. Existing
  invocations with explicit ``--vault`` continue to work
  unchanged.

### Notes

- `wiki-lint`, `wiki-compile`, `digest`, and `migrate-sources`
  intentionally **do not** gain optional vault in this release —
  those four either operate from a recipe (digest) or are
  vault-shape-introspecting (the others), so the ergonomic win is
  smaller. Promotion candidates for v0.4.7+.
- Test count: **1440 passed** (1401 baseline + 22 new across 4
  test files). ``mypy --strict``, ``ruff check``, ``ruff format
  --check``, and ``claude plugin validate .`` all clean.

## [0.4.4] - 2026-05-04

Phase B.1 hot-fix caught on the maintainer's first real-machine
smoke of v0.4.3 (3 vaults out of 30 had `extract-images` output
that didn't follow the per-paper `.md` files into `Wiki/papers/`).

### Fixed

- **`migrate_v04.migrate` now relocates per-paper image
  subdirectories** in addition to `*.md` paper notes. Pre-fix, a
  vault with `Wiki/sources/<id>.md` AND
  `Wiki/sources/<id>/images/teaser.png` would migrate the .md but
  leave the image subdir orphaned at the legacy path. Obsidian
  wikilinks (`[[<id>/images/<file>|700]]`) still resolved via
  vault-index lookup so the user saw nothing visually wrong, but
  the on-disk layout was structurally inconsistent and
  `needs_migration` returned `False` on re-runs (it only checked
  `*.md`), so there was no automatic recovery path. Fix:
  - `MigrationPlan` gains `planned_dir_moves: list[_PlannedDirMove]`
    populated by a new `_enumerate_legacy_subdirs` walk.
  - `needs_migration` returns `True` when EITHER `*.md` files OR
    per-paper subdirs exist (and `Wiki/papers/` is absent).
  - `_make_backup` extends the manifest with a `directories` block
    and uses `shutil.copytree` for recursive snapshots.
  - `migrate` runs a directory-move loop (`shutil.move`) after the
    file-move loop, with a defensive skip when the destination
    already exists (mid-migration retry safety).
  - `restore` walks the new `directories` manifest block and
    `copytree`s subdirs back to their legacy location,
    `rmtree`-ing any partial restore first.
  - 2 new integration tests
    (`test_wiki_compile_migrates_per_paper_image_subdirs`,
    `test_wiki_compile_migrates_only_image_subdirs_no_md`) pin
    both the canonical path and the edge case where ONLY image
    subdirs exist (no surviving `.md`).

### Changed

- **Bumped `paperwiki.__version__` to `0.4.4`** to drive the
  upgrade flow on installations already at 0.4.3. Three SOT
  files: `src/paperwiki/__init__.py`, `pyproject.toml`,
  `.claude-plugin/plugin.json`.

## [0.4.3] - 2026-05-04

Phase B of the v0.4.x release line — storage layout consolidation
(D-T) and anti-hardcode rule extension (D-Z). Same-day micro-bump
from `0.4.2` so the maintainer's `paperwiki update` flow surfaces
Phase B's auto-migration code without a manual marketplace pull.
The 0.4.2 → 0.4.3 transition is purely a version-string bump; the
substantive Phase B changes shipped under the previous line and
are documented in the `[0.4.2]` entry below.

### Changed

- **Bumped `paperwiki.__version__` to `0.4.3`** to drive the
  Claude Code 5-step upgrade flow on the maintainer's vault. No
  source-code changes beyond the three single-source-of-truth
  files (`src/paperwiki/__init__.py`, `pyproject.toml`,
  `.claude-plugin/plugin.json`).

## [0.4.2] - 2026-05-04

Phase A of the v0.4.2 cycle: four hot bugs blocking everyday use,
caught in real-machine smoke during the v0.4.1 → v0.4.2 transition.
Each individually small but together they were the difference between
"v0.4.0 looks shipped" and "the user can finish a typical session
without manual workarounds." Verified end-to-end on the maintainer's
vault before merge.

### Added

- **`paperwiki.config.secrets` module — auto-load
  `${PAPERWIKI_HOME}/secrets.env`** (Task 9.180 / **D-U**). The
  pre-D-U contract required users to manually
  `source ~/.config/paper-wiki/secrets.env` before any runner that
  constructed a source plugin needing API keys (notably the
  `semantic_scholar` `api_key_env` indirection). A naked
  `paperwiki digest` from a fresh shell crashed with
  `UserError("env var PAPERWIKI_S2_API_KEY is unset")`. The new
  loader auto-fires at the top of every CLI entry point that may
  touch user secrets (`digest`, `wiki-query`, `wiki-ingest-plan`).
  Minimal `KEY=VALUE` parser, no `python-dotenv` dependency.
  No-clobber (existing `os.environ[K]` always wins). Mode hygiene
  warning when not `0600`. Idempotent across the process. Opt-out
  via `PAPERWIKI_NO_AUTO_SECRETS=1`.
- **`RecipeSchemaError` exception type** (Task 9.181 / **D-W**).
  Pre-v0.4 recipes (`scorer.config.weights: {keyword, category,
  recency}`) used to crash mid-run inside `CompositeScorer` with a
  generic axes-missing exception. The v0.4.0 SKILL session that hit
  this responded by silently rewriting the user's recipe with v0.4
  defaults, losing the maintainer's intent. The new exception is
  raised at recipe-load time before pydantic validation, exits with
  code `2` (`RECIPE_STALE`, distinct from generic `UserError` exit
  `1`), and contains the literal slash-form action hint
  `/paper-wiki:migrate-recipe <path>` so SKILL pipes auto-route.
  `skills/digest/SKILL.md` now has a "When this fails" stanza
  forbidding default-weight substitution.
- **`EdgeRecord.note` field + frontmatter-link harvest** (Task 9.183).
  `wiki-compile-graph` now harvests typed-list frontmatter
  (`related_concepts`, `topics`, `people`) into edges in addition to
  body wikilinks. Frontmatter-origin edges are tagged
  `note="frontmatter:<field>"` so wiki-lint can flag inconsistencies
  with body prose. Closes the digest-write ↔ graph-read contract
  that was decorative pre-v0.4.2. Body wins on dedup when both body
  and frontmatter point at the same target.

### Fixed

- **`wiki-compile-graph` walks legacy `Wiki/sources/`** when
  `Wiki/papers/` is missing or empty (Task 9.182). Pre-fix, an
  upgraded user with hundreds of source notes saw zero graph activity
  on their first `wiki-graph` query because the v0.4.x compiler only
  walked the typed subdirs (`papers/concepts/topics/people/`). Fix
  bridges the transition window until D-T storage layout
  consolidation lands in Phase B: when `papers/` has zero `.md`,
  `_walk_typed_subdirs` falls back to `sources/`, entities are tagged
  with canonical `entity_type=papers`, `entity_id` prefix is rewritten
  so downstream queries return stable `papers/<id>` paths regardless
  of physical layout, and a one-shot `graph.sources.legacy` warning
  fires per compile (action: "run paperwiki wiki-compile to migrate").
  Real-machine result: the maintainer's 20-file `Wiki/sources/` vault
  now produces 54 edges (was 0) and `--papers-citing vision-multimodal`
  returns 20 papers (was empty).
- **`PaperWikiError` messages reach stderr in CLI runners** (Phase A
  regression fix, caught during real-machine verification). Loguru's
  default format renders the message string verbatim but drops keyword
  `extra` fields; pre-fix,
  `logger.error("digest.failed", error=str(exc), exit_code=...)`
  emitted only the literal `"digest.failed"` and the multi-line
  actionable hint (e.g. `/paper-wiki:migrate-recipe <path>` from
  `RecipeSchemaError`) never reached the user's terminal despite
  the exit code being correct. All three runners that catch
  `PaperWikiError` (`digest`, `wiki-query`, `wiki-ingest-plan`) now
  emit the full message via `typer.echo(str(exc), err=True)` before
  the structured logger line. Test gap closed:
  `test_digest_cli_emits_full_message_on_stderr` runs `paperwiki
  digest` as a real subprocess so loguru's stderr handler is
  exercised end-to-end.

### Changed

- **`_resolve_s2_secrets` error message distinguishes file-missing
  vs key-missing-from-file** (Task 9.180 companion). When the recipe
  declares an `api_key_env` indirection and the env var is unset, the
  message now spells out the exact path
  (`~/.config/paper-wiki/secrets.env`) and the exact key name to add,
  branching on whether the file exists. Matches the D-U auto-load
  contract — the user no longer guesses where the key should live.

### Phase B — Storage layout consolidation (D-T)

Phase B closes the v0.3.x → v0.4.2 vault-layout transition opened
read-side by Phase A's wiki-compile-graph fix (Task 9.182). The
canonical write target for per-paper notes is now
`Wiki/papers/<id>.md` (was `Wiki/sources/<id>.md` in v0.3.x).
Existing vaults are auto-migrated on the first `paperwiki wiki-compile`
run via the existing D-J SHA-256 backup; users don't need to know a
migration exists. Per the maintainer directive *"正常使用者不會想要
繁複的指令"*, no extra flag is required for the common case.

#### Added (Phase B)

- **`PAPERS_SUBDIR`, `LEGACY_PAPERS_SUBDIR`, `CONCEPTS_SUBDIR`
  constants** in `paperwiki.config.layout` (Task 9.184 / **D-Z**).
  Single source of truth for vault subdir names so any future
  relocation is a one-line edit. Companion to D-X (hardcode
  prevention from v0.4.1): D-Z extends the rule to wiki backends —
  the v0.4.0 `_SOURCES_DIRNAME = "sources"` constant in
  `markdown_wiki.py:48` is the same anti-pattern v0.4.1 hot-fixed in
  shell artifacts. CI grep guard pinned by
  `test_d_z_no_hardcoded_subdir_paths_in_backends`.
  `LEGACY_PAPERS_SUBDIR = "sources"` is tagged for v0.5.0 deletion.
  `SOURCES_SUBDIR` (vault root `Sources/`) deleted — Q1 ratified
  that no runner ever wrote to it.
- **`paperwiki wiki-compile` auto-fires `migrate_v04`** (Task 9.187).
  When the vault has populated `Wiki/sources/` AND empty
  `Wiki/papers/`, the compile runner relocates everything via
  `migrate_v04.migrate_if_needed` BEFORE the index rebuild reads
  the backend. Banner printed on stdout (`Migrating
  Wiki/sources/ → Wiki/papers/ (N files, backup at <ts>)`).
  Idempotent on re-run via the existing `needs_migration` guard.
  New `--no-auto-migrate` flag prints the dry-run plan and skips
  the move (the index rebuild still runs against the legacy layout
  via the read-fallback shim).
- **`paperwiki update` post-upgrade migration hint** (Task 9.188).
  When `paperwiki update` finishes, the user-visible "Next:" block
  (in BOTH the no-op "already at <ver>" branch AND the upgrade
  summary branch) gains a single-line hint per known recipe vault
  that still carries `Wiki/sources/<id>.md` files. Hint disappears
  once `paperwiki wiki-compile` migrates them. New
  `paperwiki._internal.legacy_vault_scan` module owns the parse
  + scan; tolerates malformed YAML and bundled placeholder vault
  paths. Opt-out via `PAPERWIKI_NO_AUTO_DETECT=1`.

#### Changed (Phase B)

- **`MarkdownWikiBackend` writes per-paper notes to `Wiki/papers/`**
  (Task 9.185). `upsert_paper` write target switched from
  `Wiki/sources/` to `Wiki/papers/`. `list_sources` walks
  `Wiki/papers/` first AND surfaces any surviving
  `Wiki/sources/<id>.md` (v0.3.x layout) for one release with a
  one-shot `backend.legacy.sources_path` warning per process per
  file. Same-filename dedupe — canonical wins. Drops in v0.5.0.
- **`ObsidianReporter._try_inline_teaser` reads `Wiki/papers/`
  first** (Task 9.185). Falls back silently to `Wiki/sources/`
  for one release. Wikilink shape is unchanged because Obsidian
  resolves vault-relative names by index, not literal path.
- **`extract_paper_images` validates against `Wiki/papers/<id>.md`
  first** (Task 9.186). Falls back to `Wiki/sources/<id>.md` with
  a one-shot `extract_images.legacy.sources_path` warning. Image
  manifest follows wherever the source actually lives so legacy
  vaults keep their figures co-located. **The internal arXiv
  tarball cache (`Wiki/.cache/sources/`) is deliberately not
  renamed** — not user-facing, and renaming would invalidate every
  existing user's tarball cache.
- **`migrate_sources` runner walks `Wiki/papers/` first** (Task
  9.187a). Per-file format-upgrade tool, distinct from the
  directory migration (`migrate_v04`). Same-name dedupe means
  mid-migration vaults migrate once via the canonical copy.
- **SPEC §3 vault-subdir defaults table rewritten** to reflect
  D-T. `Wiki/sources/` documented as read-only legacy until
  v0.5.0; auto-migration steps explicit. SKILL docs (`digest`,
  `wiki-ingest`, `extract-images`, `bio-search`,
  `migrate-sources`, `setup`) and bundled recipe templates
  (`daily-arxiv.yaml`, `biomedical-weekly.yaml`) updated to
  reference `Wiki/papers/`.

## [0.4.1] - 2026-05-01

Hot-fix for a v0.4.0 release-gate regression caught on first
real-machine upgrade. Single bug, single architectural cause.

### Fixed

- **`hooks/ensure-env.sh` and `lib/bash-helpers.sh` no longer hardcode
  the version string** (D-9.45.1). v0.4.0 shipped with `v0.3.44`
  literal embedded in three places in `ensure-env.sh` (the shim
  `EXPECTED_TAG`, the shim heredoc body, and the helper
  `EXPECTED_HELPER_TAG`) plus two places in `lib/bash-helpers.sh`
  (line-1 tag comment, `_PAPERWIKI_HELPER_VERSION` constant). The
  hook's idempotency check is `grep -qF "$EXPECTED_TAG" "$SHIM_PATH"`
  — when the literal `v0.3.44` matched the existing v0.3.44 shim,
  the rewrite was skipped and the user stayed pinned to v0.3.44
  forever even after `/plugin install paper-wiki@paper-wiki` and a
  full TWO-restart cycle.

### Changed

- **Single source of truth: `paperwiki.__version__`** flows to every
  shell artifact via two derivation patterns:
  - `hooks/ensure-env.sh` reads `$PLUGIN_VERSION` (already grep'd
    from `src/paperwiki/__init__.py` at script start) and
    interpolates into `EXPECTED_TAG`, `EXPECTED_HELPER_TAG`, and the
    sed-substitution that writes the shim/helper files.
  - `lib/bash-helpers.sh` is now a TEMPLATE — the line-1 tag and
    `_PAPERWIKI_HELPER_VERSION` use `@PAPERWIKI_VERSION@`
    placeholders. `ensure-env.sh` runs
    `sed "s|@PAPERWIKI_VERSION@|${PLUGIN_VERSION}|g"` as it copies
    the file to `~/.local/lib/paperwiki/bash-helpers.sh`. The
    placeholder is invariant under version bumps — only
    `__version__` ever changes.

### Added

- **Regression test** (`tests/test_smoke.py::test_shell_artifacts_use_version_placeholder`)
  pins the structural lines in both files: any future literal
  `v\d+\.\d+\.\d+` in the tag/version-bearing lines fails CI rather
  than slipping into a release. The eight-place version mirror is
  reduced to one canonical source plus pinning tests for the four
  static mirrors (`__init__.py`, `pyproject.toml`, `plugin.json`,
  and the two shell artifacts).

### Verification gates

- `pytest -q`                           — passing
- `mypy --strict src`                   — clean
- `ruff check src tests`                — clean
- `ruff format --check src tests`       — clean
- `claude plugin validate .`            — passed
- `bash -n hooks/ensure-env.sh`         — syntax OK
- `bash -n lib/bash-helpers.sh`         — syntax OK

## [0.4.0] - 2026-05-01

Minor release shipping the full v0.4.x roadmap as one monolithic
release per **decision D-R**. Three themes land together so the
artifact in the user's vault becomes meaningfully more useful per
session: a queryable typed knowledge graph (Phase 1), Obsidian-native
on-disk conventions (Phase 2), and pipeline observability +
ergonomics (Phase 3). Sixteen tasks (9.156–9.171) + twenty
ratified decisions (D-A through D-S).

The plugin protocol stays `@experimental` until v1.0; v0.4.x adds
new entity types and pipeline hooks but does not change the four
core protocols (`Source` / `Filter` / `Scorer` / `Reporter`).

### Phase 1 — Knowledge-graph foundation

- **Three new typed wiki entities** (D-A): `Concept`, `Topic`,
  `Person` join `Paper` as first-class citizens. Each gets its own
  Pydantic model in `paperwiki.core.models` and a Markdown template
  in `locales/en/templates/{concepts,topics,people}/`. Idea /
  Experiment / Claim are explicitly deferred to v0.5+ (D-A).
- **Hybrid graph layer** (D-B): frontmatter is canonical; the
  materialised query cache lives at `<vault>/Wiki/.graph/{edges,
  citations}.jsonl`. Built on demand by `paperwiki wiki-compile-graph`,
  invisible to Obsidian indexing thanks to the leading-dot prefix.
- **Closed `EdgeType` enum** (D-L): `BUILDS_ON` / `IMPROVES_ON` /
  `SAME_PROBLEM_AS` / `CITES` / `CONTRADICTS` / `EXTENSION` (the
  forward-compat hook reserved for v0.5+ edge classes paired with
  `Edge.subtype`).
- **`wiki-lint --check-graph`**: opt-in extension adding
  `ORPHAN_SOURCE` and `GRAPH_INCONSISTENT` rules so bidirectional
  wikilink integrity is auditable without a new SKILL (D-C).
- **New `wiki-graph` SKILL** + `paperwiki wiki-graph-query` runner:
  `--papers-citing` / `--concepts-in-topic` / `--collaborators-of`
  with `--json` (default) and `--pretty` Markdown table output (D-Q).
- **Migration helper** (D-J): first `paperwiki wiki-compile` after
  v0.4.0 install auto-converts the v0.3.x flat layout to typed
  subdirs `Wiki/{papers,concepts,topics,people}/` (D-I) with a
  SHA-256 manifest backup at
  `<vault>/.paperwiki/migration-backup/<ts>/`. Opt-out via
  `PAPERWIKI_NO_AUTO_MIGRATE=1`. Idempotent. Restorable via
  `paperwiki wiki-compile --restore-migration <ts>`.

### Phase 2 — Obsidian-native polish

- **Properties API frontmatter** on every emitted note (D-D): six
  canonical fields (`tags`, `aliases`, `status`, `cssclasses`,
  `created`, `updated`) plus typed-entity extras. Tags normalise
  arXiv categories (`cs.LG` → `cs/lg`) for nested-tag-friendly
  grouping in Obsidian's tag pane.
- **Obsidian callouts** (`> [!abstract]` / `> [!note]` /
  `> [!warning]`) in digest and analyze output. Default-on via
  `recipes/_defaults.yaml` (D-N) with per-recipe override; the new
  `sources-only` recipe ships with callouts off so plain-Markdown
  consumers stay unaffected.
- **Dataview recipes** (`references/dataview-recipes.md`): seven
  copy-paste DQL queries that work against the Properties API
  contract — recent papers, papers by tag, papers by topic, paper
  count by month, missing summaries, concepts by paper backlinks,
  recently updated notes.
- **Templater opt-in** (`obsidian.templater: true`): the per-paper
  Notes section gets a live `<%* tp.file.last_modified_date(...) %>`
  stamp so Obsidian re-renders the timestamp every time the note
  opens. Default-off because non-Templater users would see the
  syntax as literal text.
- **Obsidian wikilink image embeds** (`![[image|width]]`): all
  reporters that emit images use the wikilink-with-width shape so
  Obsidian renders inline at a sensible width. The plain `markdown`
  reporter still emits no images (vault-agnostic). Regression guard
  in `tests/unit/test_obsidian_image_embeds.py` scans every Python
  source for stray CommonMark image bytes.

### Phase 3 — Pipeline observability + ergonomics

- **Per-stage progress reporting**: every digest run emits stable
  `loguru` start/complete pairs with `elapsed_ms` + per-stage
  counts (`source.fetch.*`, `filter.<name>.*`, `scorer.*`,
  `report.write.*`). The stage names are stable contract surface
  for downstream observability.
- **Run-status ledger** at `<vault>/.paperwiki/run-status.jsonl`
  (D-O): one JSONL row per digest run captures source counts,
  filter drops, final paper count, elapsed_ms, and an error
  class/message when the run failed. Surfaced via
  `paperwiki status --vault <path>` (last 5 entries). Vault-bound
  storage means cross-machine sync (Obsidian Sync, Syncthing, Git)
  carries the run history with the vault.
- **Anti-repetition dedup ledger** at
  `<vault>/.paperwiki/dedup-ledger.jsonl` (D-F + D-M): persistent
  JSONL the dedup filter consults across runs so the digest stops
  re-recommending papers the user has seen. Vault-global scope —
  a paper rejected in one recipe stays out of every recipe's
  output. Auto-engaged when a recipe has both a `dedup` filter and
  an `obsidian` reporter; opt-out via `ledger: false`. Three new
  CLI surfaces: `paperwiki dedup-list` (audit dismissed papers,
  `--format json` for SKILL pipes), `paperwiki dedup-dismiss
  <canonical_id> --title ... --vault ...` (manual rejection with
  optional `--reason`), `paperwiki gc-dedup-ledger --vault ...
  --keep-days N` (manual sweep, defaults to
  `PAPERWIKI_DEDUP_LEDGER_KEEP` or 365 days).
- **arXiv source robustness**: source-level dedup collapses
  cross-listed duplicates inside a single fetch (counted under
  `source.arxiv.duplicates`). The retry-with-backoff path now
  raises a typed `RateLimitError` (subclass of `IntegrationError`)
  on persistent 429 so SKILLs can spot rate-limit failures
  without parsing exception messages.
- **Actionable recipe schema validation** (D-G): bad YAML carries
  line + column from the `MarkedYAMLError` mark; schema violations
  emit one `field.path: reason (got value)` line per error so a
  single run lists every fixable issue. New `paperwiki
  recipe-validate <path>` runner exits 0 on a clean recipe and 1
  with the actionable error list otherwise — wires into editor
  save hooks.
- **wiki-query composite ranking**: the v0.3.x pure-keyword score
  is replaced by a `frequency * recency * tag-match` composite
  with sqrt-damped TF and a 90-day half-life decay against file
  mtime. CLI flags `--weight-frequency` / `--weight-recency` /
  `--weight-tag-match` let recipe authors tune per call. Formula
  documented in `references/wiki-query-ranking.md`.

### Pre-release verification (decision D-S)

- **Synthetic D-S regression baseline**
  (`tests/integration/test_d_s_regression_baseline.py`) feeds 50
  fixture papers (15 vlm + 15 agents keepers, 10 out-of-window,
  10 irrelevant) through the full v0.4.0 pipeline and locks in the
  source/filter/scorer counters + top-K ranking from this commit.
  Future quality regressions fail CI rather than slipping into a
  release.
- The pre-tag *manual* D-S check (real `daily-arxiv` against arXiv's
  live API, comparing v0.3.44 baseline to v0.4.0 candidate with the
  dedup ledger cleared) is documented in
  `references/release-process.md` and is the caller's
  responsibility before pushing the v0.4.0 tag.

### Decisions ratified (D-A through D-S)

Twenty decisions tracked in `tasks/plan.md` §3 and the consensus plan
at `.omc/plans/v0.4.x-consensus-plan.md`:

- **D-A** Concept/Topic/Person only; Idea/Experiment/Claim deferred.
- **D-B** Hybrid graph: frontmatter canonical + sidecar query cache.
- **D-C** Bidirectional wikilink integrity = wiki-lint extension.
- **D-D** Obsidian Properties API as canonical metadata format.
- **D-E** No new LLM API integrations (SPEC §7 boundary).
- **D-F** Anti-repetition ledger; silent drop default.
- **D-G** Recipe authoring stays YAML; v0.4.x adds strict validation.
- **D-H** English-first surface stays English.
- **D-I** Vault layout: typed subdirs `Wiki/{papers,concepts,topics,people}/`.
- **D-J** Default-on auto-migrate + `PAPERWIKI_NO_AUTO_MIGRATE=1` escape.
- **D-K** Auto-extract during digest/analyze + manual `wiki-add`.
- **D-L** Fixed Pydantic enum for graph edge types.
- **D-M** Anti-repetition scope: vault-global.
- **D-N** Recipe flag scope: `recipes/_defaults.yaml` + per-recipe override.
- **D-O** Run-status ledger at `<vault>/.paperwiki/run-status.jsonl`.
- **D-P** SPEC update timing: per-phase incremental.
- **D-Q** wiki-graph output: `--json` (default) + `--pretty`.
- **D-R** v0.4.0 = monolithic release (all 3 phases together).
- **D-S** Rollback trigger = digest output-quality regression
  EXCLUDING dedup-ledger drops.

### Verification gates

- `pytest -q`                           — **1337 passed** (+148 from v0.3.44 baseline 1189)
- `mypy --strict src`                   — clean (65 source files)
- `ruff check src tests`                — clean
- `ruff format --check src tests`       — clean
- `claude plugin validate .`            — passed
- D-S synthetic regression baseline     — locked in
- Pre-tag D-S live-feed check           — caller's responsibility per `references/release-process.md`

## [0.3.44] - 2026-04-30

Patch release fixing two bugs surfaced by v0.3.43 release-gate
verification on the user's real machine. Both are small surface-
level fixes with significant ergonomic impact:

### Fixed

- **`_migrate_legacy_bak` now runs on no-op `paperwiki update`**
  (D-9.44.1). v0.3.43 only ran the legacy-bak migration inside the
  upgrade branch (`if cache_ver != marketplace_ver`). When a user
  upgraded via the v0.3.42 binary (which wrote `.bak` to the old
  in-cache location), then completed the TWO-restart and ran
  `paperwiki update` again, the v0.3.43 binary saw "already at
  0.3.43" and exited BEFORE migration. Result: the in-cache `.bak`
  stayed there forever — until the next `/plugin install` ate it.
  v0.3.44 hoists the migration call BEFORE the no-op-return gate
  so it runs unconditionally as a one-time housekeeping pass on
  every `paperwiki update`. Idempotent — second run finds nothing
  to migrate.

- **`paperwiki_diag` stale-version warning fires regardless of shim
  delegation** (D-9.44.2). v0.3.43 D-9.43.6 added a ⚠ warning when
  the on-disk helper version differs from the in-memory
  `_PAPERWIKI_HELPER_VERSION` constant (typical post-`paperwiki
  update` state until the user opens a new terminal). But the
  warning lived in the inline-fallback branch of
  `_paperwiki_diag_render`, AFTER the shim delegation gate. On a
  healthy install (where the shim is +x and the function shells out
  to `paperwiki diag`), the inline branch never ran — so the
  warning never fired. The 9.155 unit tests passed because the test
  setup didn't seed a +x shim; on real installs, the feature was
  silently dead. v0.3.44 hoists the stale-detection check to the
  TOP of `_paperwiki_diag_render` so it runs regardless of which
  downstream path takes over (CLI delegation OR inline fallback).
  Two new regression tests pin the fix: one with +x shim asserts
  the warning DOES appear before the CLI sentinel; one with
  matching versions asserts no false-positive.

### Decisions ratified

- D-9.44.1 — `_migrate_legacy_bak` runs unconditionally
- D-9.44.2 — stale warning runs before shim delegation

### Lessons learned

- **Test setup must mirror production conditions.** v0.3.43's stale-
  warning unit test seeded a fixture without a +x shim, so the
  inline path ran by accident — the test passed but the feature
  was dead in production. v0.3.44 adds a "shim is +x" test variant
  that pins the actual user-facing path. **Lesson**: when a feature
  has a fast-path/slow-path branch, every test should explicitly
  pin which path it's exercising.

- **Migration logic should be an unconditional housekeeping step.**
  v0.3.43 gated migration on the upgrade event because the
  migration was conceptually tied to "we're doing an upgrade right
  now". But the migration's actual job — moving legacy state to
  the new location — has nothing to do with version drift. It's a
  lifecycle hygiene pass that should run any time `paperwiki
  update` is invoked, regardless of whether a version change
  follows.

### Tests

- 1069 tests passing (+4 vs v0.3.43 baseline of 1065).
- 2 new regression tests for D-9.44.1 (no-op migration + clean
  no-op silence).
- 2 new regression tests for D-9.44.2 (shim+mismatch warning,
  shim+match no-warning).
- The matching-version test reads `_PAPERWIKI_HELPER_VERSION` from
  the worktree helper at test time so it stays correct across
  future version bumps without manual updates.

## [0.3.43] - 2026-04-30

Bug fix + architectural cleanup release. Fixes the v0.3.42 release-gate
`paperwiki diag` double-wrapped JSON list (B1); relocates `.bak`
rollback directories outside the plugin cache so they survive
`/plugin install`; introduces `paperwiki doctor` as the canonical
one-command install-health check; closes three v0.3.42 polish gaps
(message ordering, fish shell support, stale in-memory function
warning).

### Fixed

- **`paperwiki diag` double-wrapped `installed_plugins.json` list**
  (D-9.43.1). v0.3.42's `_read_paper_wiki_entry` wrapped the
  per-plugin entry list in another list, producing `[[{...}]]`
  instead of the correct `[{...}]`. The bug was masked by a unit-
  test fixture using a dict shape (real Claude Code data is a list-
  of-dicts for multi-scope support). Fix updates both the runner
  and the fixture, and adds a regression test pinning the exact
  JSON-output shape so the wrap can never reappear silently. The
  ``paperwiki diag`` and ``paperwiki_diag`` outputs now match the
  inline bash form's pre-v0.3.42 shape.

### Added

- **`paperwiki doctor` one-command install health check** (D-9.43.3).
  Aggregates v0.3.42's three separate probes (`status`, `diag`, the
  implicit "is the venv working" question) behind a single command:

  ```
  paperwiki doctor              # pretty multi-section output
  paperwiki doctor --json       # structured JSON for automation
  paperwiki doctor --strict     # exit 1 on any ✗ row
  ```

  Sections: Cache & marketplace, Install integrity (shared with
  `paperwiki status` via the new `paperwiki._internal.health`
  module), Python venv (subprocess probe with 5s timeout), Shell-rc
  integration (n/a counts as healthy for fish/csh and for
  `PAPERWIKI_NO_RC_INTEGRATION=1` opt-out). The `--json` schema is
  marked `@experimental` until v0.4.

- **Fish shell auto-source support** (D-9.43.5). `hooks/rc-integration.sh`
  now writes a fish-syntax block to `~/.config/fish/config.fish`
  when `$SHELL` ends with `/fish`. The block adds `~/.local/bin`
  to `$fish_user_paths` (so the `paperwiki` shim is discoverable)
  and notes that `paperwiki_diag` (bash form) requires bash/zsh
  while `paperwiki diag` (CLI) works in fish. Honest no-attempt-
  to-source-bash answer beats v0.3.42's silent no-op for fish
  users. Removed by `paperwiki uninstall --everything` alongside
  the bash/zsh blocks.

- **`paperwiki_diag` stale-version warning** (D-9.43.6). When the
  on-disk helper at `~/.local/lib/paperwiki/bash-helpers.sh`
  declares a version tag DIFFERENT from the in-memory
  `_PAPERWIKI_HELPER_VERSION` constant (typical post-`paperwiki
  update` state until the user opens a new terminal), the bash
  function prepends a 2-line ⚠ warning telling the user to open a
  new terminal or `source` the helper. Defensive: missing helper
  → silent skip; matching versions → no warning.

### Changed

- **`.bak` directories relocated outside the plugin cache subdir**
  (D-9.43.2). v0.3.42 wrote `.bak` under
  `~/.claude/plugins/cache/paper-wiki/paper-wiki/<ver>.bak.<ts>/`
  — but `/plugin install` (a normal step in the upgrade flow)
  wipes the cache subdir, so the rollback target disappeared between
  TWO-restart steps. v0.3.43 D-9.43.2 relocates them to
  `~/.local/share/paperwiki/bak/<ver>.bak.<ts>/` (XDG-style). New
  precedence chain for the resolver: `PAPERWIKI_BAK_DIR` >
  `XDG_DATA_HOME/paperwiki/bak` > `$HOME/.local/share/paperwiki/bak`.
  Cross-filesystem-safe `shutil.move` replaces `Path.rename`. The
  v0.3.41 D-9.41.1 "Note: cleared by /plugin install" warning is
  replaced with the positive form ("survive /plugin install") and
  the bak-directory location is printed inline.

  **Migration**: existing `<cache>/<ver>.bak.<ts>/` directories are
  automatically moved to the new location on the next `paperwiki
  update` apply (idempotent, collision-safe — never overwrites an
  existing target). No user action required.

- **`paperwiki update --check` and apply mode print rc-just-added
  AFTER the plan/result, not before** (D-9.43.4). v0.3.42 ran the
  `_consume_rc_just_added_stamp()` call at the top of `update()`,
  which broke the natural reading order (plan → side-note). The
  call now runs at the end of each branch.

- **Refactor: `_check_install_health` extracted to
  `paperwiki._internal.health`**. Both `paperwiki status` and the
  new `paperwiki doctor` consume the shared module — single source
  of truth for the four install-integrity rows (helper present,
  helper tag matches, shim present + tag, ~/.local/bin on PATH).

### Decisions ratified (D-9.43.x)

- D-9.43.1 — fix `paperwiki diag` double-wrapped JSON
- D-9.43.2 — relocate `.bak` outside plugin cache (XDG-style)
- D-9.43.3 — `paperwiki doctor` one-command health check
- D-9.43.4 — `paperwiki update` rc-just-added ordering
- D-9.43.5 — fish shell auto-source block + uninstall parity
- D-9.43.6 — `paperwiki_diag` in-memory vs on-disk version warning

### Lessons learned

- **Test fixtures must match production data shape.** The v0.3.42 B1
  bug existed because the unit-test fixture wrote a dict where Claude
  Code stores a list. Tests that lie about shape can't catch shape
  bugs. v0.3.43 adds explicit "real shape" pin tests that fail-then-
  pass when the shape is wrong.

- **Domain-bounded persistence.** v0.3.42's `.bak` lived under
  Claude Code's plugin cache because that's where the rest of paper-
  wiki's runtime lived — but Claude Code's plugin manager owns that
  directory and we never had a write contract to keep things across
  `/plugin install` cycles. v0.3.43 moves rollback targets into
  paper-wiki's own XDG-style data dir where we DO own the lifecycle.

- **Aggregation > naming.** v0.3.42 shipped `status` + `diag` as
  two distinct probes, expecting users to remember which one to
  use. v0.3.43's `doctor` collapses the cognitive load — one
  command, four sections, one healthy/total summary.

### Tests

- 1065 tests passing (+30 vs v0.3.42 baseline of 1035).
- New: `tests/unit/runners/test_doctor.py` (9 cases),
  `tests/unit/cli/test_doctor_cli.py` (4 cases),
  `tests/unit/cli/test_update_bak_relocation.py` (5 cases).
- New regression coverage in `tests/unit/runners/test_diag.py` (3
  cases pinning single-list shape + multi-scope + legacy dict
  fallback).
- Plus 4 fish-shell tests, 3 stale-version warning tests, 1 update-
  ordering test.

## [0.3.42] - 2026-04-30

Smooth one-touch install/upgrade release. Closes the v0.3.41 release-
gate UX gaps surfaced on the user's real machine: `paperwiki diag`
(with a space) now works as a CLI subcommand; the `paperwiki_diag`
bash function is auto-sourced into fresh terminals via a marker-
delimited block in the user's shell rc; the zsh `BASH_SOURCE` bug
is fixed; and `paperwiki update --check` previews planned actions
without applying them. New users see the helper functions on first
shell session; upgrades preserve the same UX without requiring users
to learn about `source ~/.local/lib/paperwiki/...`.

### Added

- **`paperwiki diag` CLI subcommand** (D-9.42.1). Adds CLI parity with
  the `paperwiki_diag` bash function. The natural typo
  `paperwiki diag --file` (with a space) — which previously returned
  `No such command 'diag'` — now produces the same multi-section
  install-state dump as the bash function. Three modes:

  ```
  paperwiki diag                # print to stdout
  paperwiki diag --file         # write to $HOME/paper-wiki-diag-<UTC-ts>.txt
  paperwiki diag --file PATH    # write to explicit PATH (parents created)
  ```

  Backed by the new `paperwiki.runners.diag.render_diag` pure
  function (D-9.42.4) — single source of truth for both the CLI and
  the bash function (which delegates when the shim is executable,
  falls back to inline when not).

- **Shell-rc auto-source integration** (D-9.42.2). `hooks/ensure-env.sh`
  now writes a marker-delimited block to the user's shell rc on first
  SessionStart so `paperwiki_diag` and other helper functions are
  available in fresh terminals — no manual
  `source ~/.local/lib/paperwiki/bash-helpers.sh` step. Block shape:

  ```bash
  # >>> paperwiki helpers >>> (managed by paperwiki — do not edit between markers)
  [ -f "$HOME/.local/lib/paperwiki/bash-helpers.sh" ] \
      && . "$HOME/.local/lib/paperwiki/bash-helpers.sh"
  # <<< paperwiki helpers <<<
  ```

  Industry-standard pattern (nvm, rvm, conda, miniforge use this
  same approach). Idempotent — re-running ensure-env.sh detects the
  begin marker and skips. User-edited content between markers is
  preserved (warn-only). Opt-out via `PAPERWIKI_NO_RC_INTEGRATION=1`
  for users with strict rc-management (chezmoi, dotfiles repos).
  Shell detection: `$SHELL` ending in `/zsh` → `~/.zshrc`; `/bash` →
  `~/.bash_profile` if exists else `~/.bashrc`; other shells → no-op.
  Removed by `paperwiki uninstall --everything`.

- **`paperwiki update --check` dry-run flag** (D-9.42.5). Previews
  what `paperwiki update` would do without applying any filesystem
  mutations:

  ```
  $ paperwiki update --check
  plan: would upgrade 0.3.41 → 0.3.42
    → would rename cache dir 0.3.41 to 0.3.41.bak.<UTC-timestamp>
    → would drop paper-wiki entry from installed_plugins.json
    → would drop paper-wiki from settings.json enabledPlugins
  Note: .bak directories are cleared by /plugin install — back up
  manually if you need long-term rollback access.
  nothing applied — re-run without --check to apply.
  ```

  Skips the marketplace `git pull` so dry runs are pure-local
  (matches user expectations for a preview command). Always exits 0.

- **Mid-upgrade "between steps" detection** (D-9.42.5 follow-up). When
  `installed_plugins.json` records vX but the cache contains only
  `vX.bak.<ts>` (the half-installed state users reach by skipping the
  TWO-restart guidance), `paperwiki update` and
  `paperwiki update --check` print:

  ```
  paper-wiki: you appear to be mid-upgrade — restart Claude Code and
  run /plugin install paper-wiki@paper-wiki to complete.
  ```

  Helps users recover from the half-finished upgrade flow without
  having to figure out the right next step from logs.

### Fixed

- **`(helper self-path not resolvable: )` bug under zsh** (D-9.42.3).
  v0.3.41 release-gate verification surfaced that
  `_paperwiki_diag_render` rendered an empty path in the
  `--- helper ---` section when the helper was sourced under zsh
  (the default macOS shell). Root cause: the function read
  `${BASH_SOURCE[0]}` at function-call time, but zsh leaves
  `BASH_SOURCE` unset by default. The fix captures the path at
  source time using `${BASH_SOURCE[0]:-$0}` — bash sets
  `BASH_SOURCE[0]` to the file path; zsh sets `$0` to the same
  thing under default options. Single line, no shell-specific
  syntax that would break either parser. Defensive fallback to
  the canonical install path string when both are empty (corrupt
  source, exotic shell).

### Changed

- **`paperwiki_diag` bash function delegates to the CLI when
  available** (D-9.42.4). When `$HOME/.local/bin/paperwiki` exists
  and is executable, the bash function shells out to
  `paperwiki diag` and uses its output directly. Single source of
  truth in Python prevents drift between bash and CLI dumps.
  Fallback to the inline implementation preserves the v0.3.39
  D-9.39.3 contract that `paperwiki_diag` works in degraded states
  (e.g., the shim was uninstalled but the helper is still sourced
  from a previous session).

- **`paperwiki update` first-run UX message** (D-9.42.2 follow-up).
  When `ensure-env.sh` writes the rc auto-source block for the
  first time, it drops a `~/.local/lib/paperwiki/.rc-just-added`
  stamp containing the rc-file path. The next `paperwiki update`
  invocation reads + deletes the stamp and surfaces a one-line
  note to the user:

  ```
  Added auto-source line to ~/.zshrc — open a new terminal or run
  `source <rc-file>` to use paperwiki_diag now.
  ```

  Consume-once semantics — subsequent updates are silent on this
  front. Closes the "the user doesn't know we touched their rc"
  feedback loop.

### Decisions ratified

- **D-9.42.1** `paperwiki diag` is a CLI subcommand with `--file [PATH]`
  semantics matching the bash function.
- **D-9.42.2** ensure-env.sh writes a marker-delimited auto-source
  block to the user shell-rc; opt-out via `PAPERWIKI_NO_RC_INTEGRATION=1`.
- **D-9.42.3** Helper self-path captured at source time using
  `${BASH_SOURCE[0]:-$0}` — works in bash + zsh without shell-specific
  syntax.
- **D-9.42.4** Diag rendering centralized in `src/paperwiki/runners/diag.py`;
  bash function delegates to CLI when shim is executable.
- **D-9.42.5** `paperwiki update --check` dry run + mid-upgrade
  state detection with actionable hints.

### Lessons learned

The v0.3.41 release-gate verification cycle revealed that the
"helper exists but isn't accessible" failure mode applied to all
three v0.3.41 features: `paperwiki diag --file` (because no CLI
subcommand existed), `paperwiki_diag` (because no shell-rc
integration auto-sourced the helper), and the diag's own
`--- helper ---` section (because zsh `BASH_SOURCE` is empty).
v0.3.42's three architectural decisions (CLI subcommand,
shell-rc integration, source-time path capture) all close the
same root-cause gap from different angles.

The **one-touch install/upgrade** goal isn't a feature — it's a
property of the install boundary. v0.3.39–v0.3.41 added powerful
helper functions but left the discoverability + accessibility
boundary untouched, so users had to know about `source` and the
helper's path. v0.3.42 fixes the boundary so the existing
helpers become invisible infrastructure, exactly as SPEC §1
mandates ("End users never see this — it runs silently on first
session").

### Tests

- 4 new tests in `tests/unit/test_bash_helpers.py` for D-9.42.3
  helper-path capture (zsh + bash + canonical fallback) + 3 for
  D-9.42.4 CLI delegation (executable shim / no shim / non-+x shim).
- 8 new tests in `tests/unit/runners/test_diag.py` cover the new
  Python `render_diag` function (sections / fallbacks / domain
  boundary / read-only / no-secrets).
- 6 new tests in `tests/unit/cli/test_diag_cli.py` for the
  `paperwiki diag` CLI subcommand (stdout / file-explicit /
  file-default-path / parent-dir creation / no-secrets / help).
- 15 new tests in `tests/unit/test_rc_integration.py` for the
  shell-rc auto-source helper (`_pick_rc_file` + `paperwiki_rc_install` +
  `paperwiki_rc_uninstall` × shell detection / idempotency / opt-out /
  preservation / removal).
- 3 new tests in `tests/unit/cli/test_uninstall_flags.py` for
  `paperwiki uninstall --everything` rc-block removal (zsh path /
  block-absent / rc-absent).
- 5 new tests in `tests/unit/cli/test_update_self_heal.py` for
  rc-just-added stamp consumption (2) + `--check` mode (3) +
  mid-upgrade detection (3 — apply mode + check mode + healthy state).
- 988 → 1035+ total tests. pytest -q green; mypy --strict clean;
  ruff check + format clean.

## [0.3.41] - 2026-04-29

Post-v0.3.40 polish release. Three small UX fixes that emerged from
release-gate verification: `paperwiki update` now warns about the
`.bak` directory's lifecycle (Claude Code's `/plugin install` wipes
the cache subdir, so `.bak.*` never survives a real upgrade);
`paperwiki status --strict` opt-in flag for CI pipelines that want
helper-state issues to be exit-1 errors instead of warnings;
`paperwiki_diag --file` (no path arg) now defaults to a timestamped
file under `$HOME` instead of failing loudly. No behavior changes,
no version-pin shifts beyond the 0.3.40 → 0.3.41 bump itself.

### Added

- **`paperwiki status --strict` opt-in CI flag** (D-9.41.2). Adds a
  `--strict` boolean option to the status command. Default behavior
  (no flag) is unchanged — exit-0 in every healthy/unhealthy
  combination, preserving the v0.3.40 D-9.40.1 "warn-not-error"
  contract for interactive use. With `--strict`, the command exits
  1 if any of the four install-health rows is unhealthy. This
  resolves the v0.3.40 deferred decision: `--strict` is opt-in
  (CI-friendly) rather than the default (which would have broken
  existing automation pipes through `paperwiki status`).

- **`paperwiki_diag --file` (no path arg) defaults to timestamped
  `$HOME` file** (D-9.41.3). v0.3.40's `paperwiki_diag --file`
  required an explicit path; calling `--file` without a path
  exited 1 with an actionable error. v0.3.41 keeps the explicit-
  path mode unchanged but adds a no-arg default: when invoked as
  `paperwiki_diag --file` (or `paperwiki_diag --file --some-other-
  flag`), the function writes to
  `$HOME/paper-wiki-diag-<UTC-timestamp>.txt` and echoes
  `wrote diag to <path>`. The `$HOME` default is universally
  writable; the timestamp prevents collisions across multiple
  diag invocations. Makes "share the diag" trivially easy:
  `paperwiki_diag --file` then send the printed path.

### Changed

- **`paperwiki update` output now warns about `.bak` directory
  lifecycle** (D-9.41.1). v0.3.40's release-gate verification
  surfaced that Claude Code's `/plugin install` wipes the entire
  `cache/paper-wiki/paper-wiki/` subdirectory before re-extracting
  the new version — including any `.bak.*` directories
  `paperwiki update` left behind. Result: the v0.3.39 D-9.39.1
  rollback story ("`.bak.*` directories preserve the previous
  cache for manual rollback") is functionally void in the
  upgrade path because `/plugin install` wipes them moments
  later. v0.3.41 adds an inline `Note:` line to `paperwiki update`
  output between the "cache backed up" message and the "Next:"
  block, telling users that `.bak` directories are cleared by
  `/plugin install` and they should back up manually for long-
  term rollback access. Messaging-only fix; the runner behavior
  is unchanged. A deeper fix (move `.bak` outside the cache subdir)
  is deferred — it would require changing the rename target,
  which has wider blast radius.

### Decisions ratified

- **D-9.41.1** `paperwiki update` adds a `Note:` line about `.bak`
  lifecycle vs `/plugin install`; messaging-only, no runner
  behavior change. Deeper fix (move `.bak` outside cache subdir)
  deferred.
- **D-9.41.2** `paperwiki status --strict` flag is opt-in
  (default behavior unchanged); resolves the v0.3.40 deferred
  decision in favor of CI-friendly opt-in over default-strict.
- **D-9.41.3** `paperwiki_diag --file` without a path arg
  defaults to `$HOME/paper-wiki-diag-<UTC-timestamp>.txt`;
  explicit-path mode unchanged. Replaces v0.3.40's "fail loudly"
  semantics with a sensible default.

### Lessons learned

The v0.3.40 release-gate verification surfaced that the v0.3.39
`.bak` rollback story is structurally fragile in the upgrade path
because Claude Code's `/plugin install` controls the cache subdir
and wipes its contents. The v0.3.41 messaging fix (D-9.41.1) is a
short-term mitigation; a deeper architectural fix (rename target
outside the wipe-zone) is deferred to a future release. Lesson:
when a feature depends on directories Claude Code's plugin manager
treats as ephemeral, document the lifecycle constraint loudly at
the user-visible layer — the underlying contract is not paperwiki's
to control.

The `paperwiki status --strict` decision (D-9.41.2) followed a
common pattern: a "should we make this strict?" question deferred
during the v0.3.40 build was answered the right way once we had
real-usage data. The v0.3.40 default-warn behavior turned out to
be exactly right for interactive use; CI users who want strict
errors are a smaller and more sophisticated audience that benefits
from an explicit opt-in.

### Tests

- 1 new test in `tests/unit/cli/test_update_self_heal.py`
  (`test_bak_lifecycle_note_appears_before_next_block`) verifies
  the `Note:` line about `.bak` lifecycle appears before the
  `Next:` block in `paperwiki update` output.
- 3 new tests in `tests/unit/cli/test_status_health.py`
  (`TestStatusStrictFlag` class) cover the `--strict` flag:
  exit-0 on healthy install with `--strict`, exit-1 on
  unhealthy install with `--strict`, and default mode
  preserves exit-0 even when unhealthy.
- 2 replacement tests in `tests/unit/test_bash_helpers.py`
  (`test_diag_file_flag_without_arg_uses_default_path` +
  `test_diag_file_flag_default_path_is_timestamped`) replace
  the v0.3.40 `test_diag_file_flag_without_arg_fails_loudly`
  test (now obsolete per D-9.41.3).
- 983 → 988 total tests (+5 net). pytest -q green;
  mypy --strict clean; ruff check + format clean.

## [0.3.40] - 2026-04-29

### Added

- **`paperwiki status` install-health check** (D-9.40.1). The status
  command now appends a 4-row health section after the existing
  4-line state report:

  ```
  install health   : 4/4 healthy
    ✓ helper present
    ✓ helper tag matches
    ✓ shim present + tag matches
    ✓ ~/.local/bin on PATH
  ```

  When unhealthy, ✗ rows include an action hint
  (`(action: restart Claude Code)` or
  `(action: add 'export PATH="$HOME/.local/bin:$PATH"' to your shell rc)`).
  The status command remains exit-0 in every healthy/unhealthy
  combination — warnings are loud but non-fatal, so automation
  pipes through `paperwiki status` aren't broken by helper-state
  issues. This delivers on the v0.3.39 §15.4 R1 retro promise:
  pushing the source-or-die contract from SKILL prose down to the
  runner layer where it always fires regardless of how Claude
  executes the SKILL.

- **`paperwiki_diag` includes `installed_plugins.json` paper-wiki
  entry** (D-9.40.3). The diag dump grew a 7th section between
  cache-versions and recipes that prints just the
  `paper-wiki@paper-wiki` entry from
  `~/.claude/plugins/installed_plugins.json` (or `(not registered)`
  when the file is missing or doesn't have the entry, or
  `(read failed: <msg>)` when the JSON is malformed). Domain-bounded
  scope: never prints other plugins' entries. The v0.3.39 debug
  session needed this exact information to diagnose a half-fail
  install state; now it's one command away.

- **`paperwiki_diag --file <path>` write mode** (D-9.40.5). Optional
  `--file <path>` flag writes the multi-line diag dump to the given
  path (creating parent dirs as needed) and echoes
  `wrote diag to <path>` to stdout. Default mode (no flag) still
  prints to stdout. Makes "share the diag output" trivial:
  `paperwiki_diag --file ~/Desktop/paper-wiki-diag.txt`. `--file`
  without a path arg exits non-zero with an actionable error.

### Changed

- **`paperwiki update` "Next:" message expanded to 5 steps**
  (D-9.40.2). v0.3.39 user feedback called out that the 3-step
  message implied a single Claude Code restart was sufficient, but
  the actual upgrade requires TWO restart cycles. The new message
  spells out both:

  ```
  Next:
    1. Exit any running session: /exit (or Ctrl-D)
    2. Open a fresh session: claude
    3. Inside: /plugin install paper-wiki@paper-wiki
    4. Exit again: /exit
    5. Open another fresh session: claude
       (SessionStart fires ensure-env.sh against the now-registered
        plugin and rewrites the shim/helper to the new version)
  ```

- **Marketplace `git fetch` + `git pull --ff-only` are now
  best-effort** (D-9.40.4). v0.3.39's `_git_pull` aborted
  `paperwiki update` on any non-zero exit, which prevented the
  self-heal path from running on offline first-install or
  corrupt-clone scenarios. v0.3.40 catches `TimeoutExpired`,
  `FileNotFoundError`, and non-zero exit codes; logs at WARN
  level; and falls through to the on-disk clone. 10-second
  timeout per subprocess guards against hanging connections.

### Decisions ratified

- **D-9.40.1** `paperwiki status` adds a 4-row install-health
  section; status command remains exit-0 in all combinations
  (warn-not-error). `--strict` mode deferred to 9.125.
- **D-9.40.2** `paperwiki update` "Next:" message expanded from 3
  to 5 steps to call out both restart cycles required.
- **D-9.40.3** `paperwiki_diag` adds an `installed_plugins.json`
  paper-wiki entry section — domain-bounded (only the paper-wiki
  entry, never other plugins).
- **D-9.40.4** Marketplace `git pull` is best-effort with 10s
  timeout; failures log WARN and fall through to on-disk clone.
- **D-9.40.5** `paperwiki_diag --file <path>` write mode; only
  user-supplied paths, no defaults, no auto-pathing.

### Lessons learned

The v0.3.39 retro identified that the v0.3.38 source-or-die contract
is strong at the lint layer but weak at the user-visible runtime
layer (SessionStart auto-recovery + Claude SKILL pragmatic-reduction
mask the loud-error path). v0.3.40's `paperwiki status` install-health
check (9.114) closes that gap — a contract enforced by the runner
fires deterministically regardless of how Claude executes the SKILL,
and the user sees the ✗ row directly when running `paperwiki status`
from a terminal.

The v0.3.39 release-gate verification surfaced another gap: the
upgrade flow requires TWO Claude Code restart cycles, but the
v0.3.39 "Next:" message implied one. v0.3.40's 5-step message
(D-9.40.2) closes that loop. Lesson: messaging matters as much as
runner correctness — a runner that succeeds while the user
misunderstands the flow is functionally indistinguishable from a
broken runner.

### Tests

- 11 new tests in `tests/unit/cli/test_status_health.py` cover the
  4-row install-health check (6 direct unit tests of
  `_check_install_health` + 5 integration tests via CliRunner).
- 5 new tests extend `tests/unit/cli/test_update_self_heal.py`:
  4 unit tests on `_git_pull` error paths (success / non-zero /
  FileNotFoundError / TimeoutExpired) + 1 integration test
  (offline self-heal completes despite simulated network failure)
  + 1 wording test for the 5-step "Next:" message.
- 9 new tests extend `tests/unit/test_bash_helpers.py`: 5 for
  `installed_plugins.json` section (entry-present / file-missing /
  entry-absent / malformed-JSON / domain-boundary) + 4 for
  `--file` mode (writes file / default stdout / parent-dir
  creation / arg-error).
- 956 → 983 total tests (+27 net). pytest -q green;
  mypy --strict clean; ruff check + format clean.

## [0.3.39] - 2026-04-29

### Fixed

- **`paperwiki update` self-heals when the plugin cache is empty.**
  Until v0.3.38 the runner refused with `paperwiki: no installed
  plugin found at ...` when
  `~/.claude/plugins/cache/paper-wiki/paper-wiki/` had no version
  subdirs — the dev-workflow scenario where Claude Code's
  `installed_plugins.json` half-recorded a version while the cache
  dir was missing. Recovery required four manual bash lines plus a
  Claude Code restart. v0.3.39 collapses that into a single
  `paperwiki update` invocation: when the cache is empty, the
  runner copies the marketplace clone into
  `cache/paper-wiki/paper-wiki/<version>/` automatically before
  the existing diff-and-sync logic runs (D-9.39.1). Strict
  version-only regex `^\d+\.\d+\.\d+$` gates the self-heal —
  caches with `.bak.*`-only contents also self-heal; caches with
  any version dir don't.

- **`paperwiki uninstall --everything` now removes
  `~/.local/lib/paperwiki/`** (D-9.39.2). v0.3.38 introduced this
  helper-install location but didn't update the uninstall runner's
  removal-target list — users running a "full reset" between
  v0.3.38 and v0.3.39 had to `rm -rf ~/.local/lib/paperwiki/`
  manually. The v0.3.38 CHANGELOG flagged this gap explicitly;
  v0.3.39 closes the loop. **The v0.3.38 obsolete-warning
  ("manually `rm -rf ~/.local/lib/paperwiki/` after `--everything`")
  is no longer needed** — `--everything` covers it now.

### Added

- **`paperwiki_diag` helper function** added to
  `lib/bash-helpers.sh` (D-9.39.3). Read-only install-state dump
  callable from any sourced shell:

  ```bash
  $ source ~/.local/lib/paperwiki/bash-helpers.sh
  $ paperwiki_diag
  === paperwiki_diag — install state ===
  --- helper ---
  # paperwiki bash-helpers — v0.3.39 (...)
  --- environment ---
  PATH=/Users/.../local/bin:/usr/bin:/bin
  CLAUDE_PLUGIN_ROOT=...
  --- shim (~/.local/bin/paperwiki) ---
  ...
  --- plugin cache versions (...) ---
  0.3.39
  --- recipes (...) ---
  daily.yaml
  weekly.yaml
  === end paperwiki_diag ===
  ```

  Output is **safe to share** when asking for help — the function
  prints PATH, CLAUDE_PLUGIN_ROOT, helper version, shim status,
  and `ls -1` of the cache + recipes dirs. It does NOT print
  `secrets.env` content, recipe file content, or any tool-call
  output. Function is read-only (no env mutation, no filesystem
  writes), verified by 4 dedicated unit tests.

  **API contract change**: D-9.39.3 supersedes D-9.38.2's "exactly
  three functions" constraint. The helper now exposes four public
  functions; future additions land via a versioned D record and
  bump the helper version tag.

### Decisions ratified

- **D-9.39.1** `paperwiki update` self-heal — gated on strict
  version-regex; `cp -R` from marketplace clone before
  diff-and-sync.
- **D-9.39.2** `--everything` removes `~/.local/lib/paperwiki/`
  parallel to the shim.
- **D-9.39.3** Helper API supersedes D-9.38.2's
  "exactly three functions"; new contract is "header docstring
  is the public-API source of truth, additions land via D record".
- **D-9.39.4** Plan §15.4 R1 retro note placement — append after
  R1 row, mark "(added in v0.3.39)"; CHANGELOG Lessons learned
  echoes it.

### Lessons learned

The v0.3.38 plan §15.4 R1 mitigation prose claimed users would see
a loud restart-Claude-Code error when the helper goes missing.
Today's runtime test
(`mv ~/.local/lib/paperwiki/bash-helpers.sh{,.bak}` + fresh Claude
Code session + `/paper-wiki:status`) showed otherwise: the user
sees nothing unusual. Two compounding reasons:

1. **SessionStart auto-recovers.** Opening a fresh Claude Code
   session triggers `ensure-env.sh`, which re-installs the helper
   from `$CLAUDE_PLUGIN_ROOT/lib/bash-helpers.sh` whenever the
   install target is missing or has a stale tag. The
   "missing helper" state is healed before any SKILL runs.
2. **Claude pragmatically reduces SKILL bash blocks.** Even when
   the helper genuinely is missing, Claude (the model executing
   the SKILL) tends to read the prose, identify the meaningful
   command (`paperwiki status`), and run that directly — skipping
   the source-or-die boilerplate. PATH was already configured by
   a prior shim install, so the meaningful command works.

The v0.3.38 contract still holds at the **lint** layer (subprocess
lint + F6 fixture exercise it directly in a sandbox without
auto-recovery and without Claude's SKILL adherence heuristics).
The **user-visible runtime** contract is much narrower than the
plan claimed.

This doesn't change v0.3.38's design — the source-or-die stanza
is still the right honest-failure posture in SKILL prose. But the
v0.3.39 plan §15.4 retro paragraph (D-9.39.4) records this
honestly so future readers don't treat R1's mitigation prose as
canonical. A v0.3.40+ candidate (9.114) explores pushing the
contract from SKILL prose down to the runner layer, where it
always fires regardless of how Claude executes the SKILL.

### Tests

- 9 new tests in `tests/unit/cli/test_update_self_heal.py` cover
  the four self-heal acceptance cases (empty / .bak-only /
  version-present / marketplace-missing) + 5 sub-cases of the
  `_cache_has_any_version` gating helper.
- 1 new test in `tests/unit/cli/test_uninstall_flags.py` (extended
  the existing `test_uninstall_everything_yes_removes_seven_targets`)
  asserts `~/.local/lib/paperwiki/` is removed by `--everything`.
- 4 new tests in `tests/unit/test_bash_helpers.py` cover
  `paperwiki_diag`: emits all six sections, handles missing dirs
  gracefully, does NOT print secrets, is read-only.
- 943 → 956 total tests (+13 net). pytest -q green; mypy --strict
  clean; ruff check + format clean; claude plugin validate passes.

### Note for v0.3.40+ follow-up

A `paperwiki status` install-health check (logged as 9.114 in
plan §16.6) would push the source-or-die contract from SKILL
prose down to the runner layer — out of scope for the v0.3.39
S-version release.

## [0.3.38] - 2026-04-29

### Changed

- **Shared `lib/bash-helpers.sh` replaces 18 inline PATH guards +
  2 inline `CLAUDE_PLUGIN_ROOT=$(...)` resolvers across 13 SKILLs.**
  Until v0.3.37 every shim-using SKILL inlined `export
  PATH="$HOME/.local/bin:$PATH"` (a 1-line "always-defensive" guard
  that landed in v0.3.34 D-9.34.6), and setup + digest additionally
  inlined the v0.3.34 D-9.34.2 plugin-cache resolver (a 5-line
  pipeline). The duplication wasn't catastrophic, but the v0.3.36
  export-sweep miss (D-9.36.4 had to patch the resolver in 2 places)
  showed the pattern that bites: when the duplicated snippet evolves,
  every copy has to be chased, and a missed copy is a bug.

  v0.3.38 collapses both patterns into three idempotent functions
  exported by `~/.local/lib/paperwiki/bash-helpers.sh` (D-9.38.2):
  `paperwiki_ensure_path` (PATH guard), `paperwiki_resolve_plugin_root`
  (CLAUDE_PLUGIN_ROOT resolver), `paperwiki_bootstrap` (both). Each
  shim-using SKILL now opens its first bash block with the
  `source-or-die` stanza (D-9.38.4) — sourcing the helper, then
  calling the appropriate function. Tier 1 (11 SKILLs with only
  PATH guard) calls `paperwiki_ensure_path`; Tier 2 (setup +
  digest, which also need the resolver) calls
  `paperwiki_bootstrap`; Tier 3 (`analyze`, no shell-out) is
  unchanged. Final state: zero `export PATH=...` and zero
  `CLAUDE_PLUGIN_ROOT=$(` literals across `skills/`.

- **No silent fallback when the helper is missing.** Each SKILL
  bootstrap stanza fails loud with a restart-Claude-Code instruction
  if `~/.local/lib/paperwiki/bash-helpers.sh` is absent (D-9.38.4
  rejects the silent-fallback approach). Honest failure mode: a
  stale Claude Code session that predates the v0.3.38 helper install
  sees broken SKILLs, the user reads the error message ("exit Claude
  Code and re-open — the SessionStart hook installs the helper"),
  restart triggers SessionStart → helper installs → SKILL works.
  Quieter, less-honest fallbacks would let v0.3.38 sessions silently
  use v0.3.37 inline behavior, defeating the upgrade contract.

### Added

- **`hooks/ensure-env.sh` ships the helper to `~/.local/lib/paperwiki/`
  on every SessionStart** (D-9.38.1). Mirrors the existing shim
  install pattern: `EXPECTED_HELPER_TAG`-gated idempotent rewrite,
  byte-identical content via `cat $PLUGIN_ROOT/lib/bash-helpers.sh
  > $HELPER_PATH`, non-blocking on read-only `~/.local/lib/`
  (warning + continue; the SKILL bootstrap stanza handles
  missing-helper at SKILL-time per D-9.38.4).

- **Comprehensive subprocess lint mode in
  `tests/unit/test_skill_bash_snippets_lint.py`** (D-9.38.6).
  Every fenced ```bash block of every shim-using SKILL runs
  end-to-end in a sandboxed HOME tree: smart mock paperwiki shim
  with per-subcommand dispatch, real bash-helpers.sh, stub plugin
  cache, stub vault. Catches the helper-sourcing failure mode
  that the v0.3.36 static lint (`bash -n` syntax-only) couldn't
  see. Audit pass during 9.100 development used **zero**
  `<!-- skip-exec -->` markers — the smart mock shim covered every
  invocation cleanly. The marker is in the contract for future
  blocks that need it (e.g. real-network or interactive-flow
  blocks).

  Side effect: the v0.3.36 placeholder substitution
  (`<X>` → `"<X>"`) had a latent bug — when the placeholder sat
  inside an existing `"..."` literal (e.g. `"<canonical-id>"`),
  nested `""<X>""` parsed as empty-string + redirection. Static
  lint never caught this (it's only a problem under real
  execution). v0.3.38 switches the substitution to
  `<X>` → `__X__` (alphanumeric stub, no redirection hazard).

- **F6 forbidden-pattern fixture** in
  `tests/unit/fixtures/bad_skill.md` (D-9.38.6). A bash block that
  sources `/nonexistent/helper.sh` directly without the
  source-or-die fallback — the regression guard for the
  helper-sourcing failure mode v0.3.38 introduces. The
  fixture-based test asserts the subprocess exits non-zero.

### Decisions ratified

- **D-9.38.1** Helper distribution: `~/.local/lib/paperwiki/
  bash-helpers.sh`, installed by ensure-env.sh on every
  SessionStart. Reject the alternative of shipping the helper
  inside the plugin cache — the resolver itself uses
  `$CLAUDE_PLUGIN_ROOT`, chicken-and-egg.
- **D-9.38.2** Helper API: exactly three idempotent public
  functions (`paperwiki_ensure_path`,
  `paperwiki_resolve_plugin_root`, `paperwiki_bootstrap`).
- **D-9.38.3** Helper carries a `# paperwiki bash-helpers — v0.3.38`
  version tag for the idempotent-rewrite gate.
- **D-9.38.4** Source-or-die SKILL bootstrap stanza — no silent
  fallback. Reject the if/else fallback approach because it would
  silently degrade to v0.3.37 inline behavior under the v0.3.38
  label.
- **D-9.38.5** SKILL sweep tiered into Tier 1 (11 files, PATH-only)
  + Tier 2 (2 files, PATH + resolver) + Tier 3 (analyze, no
  shell-out). Each tier ships as a separate commit for rollback
  granularity.
- **D-9.38.6** Subprocess lint scope: comprehensive (every block,
  not just Block #0). Smart mock paperwiki shim handles all 13
  runner subcommands; `<!-- skip-exec -->` markers exempt blocks
  that genuinely can't run in the sandbox.
- **D-9.38.7** Shim tag and helper tag bump in lockstep to v0.3.38;
  smoke tests pin both.

### Lessons learned

The "shared helper extracted from N inline copies" pattern is a
classic refactor; the lessons are about the *contract* around it,
not the extraction itself. Two surfaced during this work:

1. **Be honest about failure modes.** The first instinct was to
   inline a fallback (`if helper exists, use it; else inline the
   v0.3.37 PATH guard`). That would have silently made v0.3.38 a
   no-op for stale sessions — users on a v0.3.38 install would see
   v0.3.37 behavior with no signal. The source-or-die contract
   (D-9.38.4) is honest: when the upgrade hasn't fully landed, the
   user sees a loud restart instruction, not a quiet downgrade.
   Restart cost is ~5 seconds; the quiet-downgrade alternative
   would have cost weeks of debugging "v0.3.38 didn't actually
   change anything for me".

2. **Comprehensive subprocess lint is cheaper than expected.** The
   plan budgeted ~3-4h for the sandbox + audit. Actual: ~75 minutes
   to build the sandbox + write the test, plus zero
   `<!-- skip-exec -->` markers needed in the audit pass. The smart
   mock shim's per-subcommand dispatch covered every SKILL bash
   invocation cleanly. The one bug surfaced by the audit was the
   v0.3.36 placeholder-substitution bug (latent because static
   lint never executed the blocks), not a SKILL-prose issue. Worth
   the investment — the lint test catches the entire class of
   helper-sourcing regressions, and the helper-tag-bump test pin
   guards against the helper itself drifting.

### Note for future cleanups

`paperwiki uninstall --everything` does NOT yet remove
`~/.local/lib/paperwiki/`. Cleanup deferred to v0.3.39 (logged as
9.105 in plan §15.6). Users doing a full reset between v0.3.38
and v0.3.39 should manually `rm -rf ~/.local/lib/paperwiki/` after
the uninstall; otherwise the v0.3.38 helper file stays on disk.

### Tests

- 12 new unit tests in `tests/unit/test_bash_helpers.py` cover
  the helper's runtime contract.
- 6 new sanity tests in `tests/unit/test_skill_lint_sandbox.py`
  cover the sandbox infrastructure.
- 22 new parametric tests in
  `tests/unit/test_skill_bash_snippets_lint.py::test_bash_blocks_execute_in_sandbox`
  cover every fenced bash block of every shim-using SKILL.
- 1 new `test_fixture_F6_subprocess_fails` regression guard.
- 1 new `test_skip_exec_marker_excludes_block_from_subprocess`
  marker semantics test.
- 2 new smoke tests pin the helper file + ensure-env.sh
  helper-install block.
- 919 → 943 total tests (+44 net). pytest -q green; mypy --strict
  clean; ruff check + format clean; claude plugin validate passes.

## [0.3.37] - 2026-04-28

### Added

- **`RecipeSchema` and `load_recipe` re-exported at the
  `paperwiki.config` package root.** Until v0.3.36 the package
  `__init__.py` was an empty docstring stub, so callers had to
  remember the singular submodule name (`paperwiki.config.recipe`,
  not `paperwiki.config.recipes`). The v0.3.35 setup smoke trace
  showed Claude reaching for the cleaner `from paperwiki.config
  import RecipeSchema` and getting an `ImportError`, then
  self-correcting via package introspection. v0.3.37 makes the
  expected import work — both forms now resolve to the same object
  identity (D-9.37.2):

  ```python
  from paperwiki.config import RecipeSchema, load_recipe          # v0.3.37+
  from paperwiki.config.recipe import RecipeSchema, load_recipe   # also fine
  ```

  The submodule paths still work — re-exports are additive, not
  replacements.

- **`docs/release-history/` directory** bootstrapped with the
  v0.3.35 retro at [`docs/release-history/v0.3.35.md`](docs/release-history/v0.3.35.md).
  This is the new tracked home for per-release retros — the "why"
  behind notable releases — separated from the day-to-day engineering
  plan (`tasks/plan.md`, gitignored) and the user-facing changelog
  (this file). Going forward, retros are written by the release
  author at their discretion; most releases stay well-served by the
  CHANGELOG alone (D-9.37.4). The README "More Documentation" list
  now cross-links to the directory.

### Changed

- **F5 forbidden-pattern retired from the SKILL bash/module-path
  lint.** v0.3.36 introduced F5 to forbid the bare `from
  paperwiki.config import RecipeSchema` because it raised
  `ImportError`. With the v0.3.37 re-export landed, that import is
  valid forever — F5 is now noise, not signal. Coverage moves to
  `tests/unit/config/test_recipe.py::TestPackageRootReExports`,
  which positively asserts both names import from the package root
  and resolve to the same object as the submodule path (D-9.37.3).
  The lint test drops from 75 to 61 parametric items
  (14 SKILLs × 4 patterns + 14 export-check + 14 bash-parse + 5
  fixture tests).

### Decisions ratified

- **D-9.37.1** Release split — Option B. v0.3.37 ships only the
  cosmetic improvements (re-export + retro bootstrap); the structural
  v0.3.36 §13.6 candidates 9.84 (shared `lib/bash-helpers.sh`) and
  9.85 (subprocess-execution lint mode) are deferred to v0.3.38 so
  the helper refactor's blast radius gets release-level risk
  isolation.
- **D-9.37.2** Re-export scope: `RecipeSchema` and `load_recipe`
  only. `PluginSpec` / `instantiate_pipeline` / `STALE_MARKERS` stay
  submodule-only (internal schema details and runner-only helpers,
  not user code).
- **D-9.37.3** F5 lint dropped entirely (not whitelisted, not
  comment-deprecated).
- **D-9.37.4** `docs/release-history/vN.M.P.md` layout for retros;
  v0.3.36 not auto-backfilled (its plan §13 + CHANGELOG entry are
  rich enough).

### Lessons learned

The v0.3.35 setup smoke trace caught Claude confabulating a wrong
module path (`paperwiki.config.recipes`, plural) in the same trace
where it also reached for the bare `from paperwiki.config import
RecipeSchema` (which didn't exist either). v0.3.36 closed the
confabulation hole by pinning the literal correct import in setup
SKILL Step 2 and adding an F5 lint forbidding the broken bare form.
v0.3.37 closes the *other* half of the same UX gap: making the
form Claude (and humans) intuitively reach for actually work. The
lint-then-fix sequence is the right order — we needed the F5 lint
in place to confirm the bare import wasn't sneaking in elsewhere
before deciding it was safe to make valid. Once F5 had a clean
sweep across all 14 SKILLs at v0.3.36 ship time, the v0.3.37
re-export was a small, targeted improvement instead of an
open-ended API change.

### Tests

- 3 new tests in
  `tests/unit/config/test_recipe.py::TestPackageRootReExports`
  (positive-import + identity check + `__all__` shape).
- 1 new smoke test in `tests/test_smoke.py` pinning the
  `docs/release-history/v0.3.35.md` retro file existence + commit-SHA
  cross-reference.
- F5 row removed from
  `tests/unit/test_skill_bash_snippets_lint.py::FORBIDDEN_PATTERNS`
  and from `tests/unit/fixtures/bad_skill.md`. Lint test count drops
  to 61 (was 75). Net: 909 + 4 - 1 = 912 tests target
  (verify on commit gate).
- mypy --strict clean; ruff check + format clean; claude plugin
  validate passes.

## [0.3.36] - 2026-04-28

### Fixed

- **PRIVACY — setup wizard no longer prompts for the Semantic Scholar
  API key inline.** Up through v0.3.35 the setup SKILL's Q3 used
  `AskUserQuestion` ("Paste key now") followed by a free-form
  `Question` to capture the key value, then wrote it into
  `~/.config/paper-wiki/secrets.env`. That meant the raw key landed
  in the Claude session transcript, the auto-memory store, and any
  tool-call log. v0.3.36 collapses Q3 to a two-option choice
  ("I'll add a key later" / "Skip — no key") and routes the wizard
  to *always* write a commented placeholder template at Step 9b. The
  user populates the real key out of band by editing
  `secrets.env` with their own editor (Step 10 prints a verbatim
  five-step `$EDITOR` flow). The wizard never sees the key value
  end-to-end (D-9.36.1).

  **If you ran `/paper-wiki:setup` on v0.3.35 or earlier and pasted
  an S2 API key, rotate that key now.** The forward-only fix can't
  reach into past transcripts — your key text is recorded wherever
  the Claude session was persisted (auto-memory, transcript backups,
  tool-call logs). Issue a fresh key at
  https://www.semanticscholar.org/product/api and replace the value
  in `~/.config/paper-wiki/secrets.env` (R3).

- **`CLAUDE_PLUGIN_ROOT=$(...)` defensive resolver missing
  `export`.** v0.3.34 D-9.34.2 added a defensive resolver to
  `skills/setup/SKILL.md` Step 0 and `skills/digest/SKILL.md` Step 1,
  but both wrote the assignment as a local-scope variable. The
  next `bash` invocation in the same SKILL spawned a child shell
  that saw an empty `$CLAUDE_PLUGIN_ROOT` and `ensure-env.sh`
  exited with `CLAUDE_PLUGIN_ROOT must be set by Claude Code`.
  v0.3.36 prepends `export ` to both sites (D-9.36.4). Two-site
  in-place sweep — refactoring into a shared `lib/` helper would
  need too much indirection for a 5-line copy.

- **Setup SKILL Step 2 import line confabulation.** The fresh-user
  trace showed Claude writing
  `from paperwiki.config.recipes import RecipeSchema` (plural,
  wrong) which raised `ModuleNotFoundError`. The on-disk SKILL
  source did NOT contain that string — Claude was confabulating
  around the bare-backtick `paperwiki.config.recipe_migrations`
  reference. v0.3.36 pins the literal import as a fenced Python
  block in Step 2 so Claude has nothing to confabulate around
  (D-9.36.6):

  ```python
  from paperwiki.config.recipe_migrations import STALE_MARKERS
  ```

- **`bio-search` SKILL drift.** The `paperwiki.runners.fetch_pdf`
  reference (line 75) pointed at a module that was never created;
  the prose qualifier "(when Phase 8 ships)" implies a future API
  but the bare module path tempts Claude to import it. Replaced
  with a neutral `MarkdownWikiBackend.upsert_paper` description
  (Phase 3 sweep, plan §13.3 task 9.76).

### Added

- **Recipe loader graceful-degradation flag for the S2 source.**
  Recipe authors can now mark `semantic_scholar` as key-optional:

  ```yaml
  - name: semantic_scholar
    config:
      api_key_env: PAPERWIKI_S2_API_KEY
      api_key_env_optional: true
  ```

  When the flag is `true` and the env var is unset, the loader
  emits a `logger.warning` ("S2 API key absent; rate-limited to
  ~1 req/s") and constructs the source with `api_key=None`, which
  the source class already accepts (public S2 endpoint at the
  default rate). When the flag is `false` (default — backwards
  compatible), the loader still raises `UserError` so existing
  recipes keep their loud-fail contract. The wizard-emitted recipe
  template and `recipes/weekly-deep-dive.yaml` both opt in so a
  fresh-install user without a key gets a working pipeline (D-9.36.3).

- **SKILL bash-block + module-path lint test.**
  `tests/unit/test_skill_bash_snippets_lint.py` parametrizes across
  every `skills/*/SKILL.md` and asserts five invariants:

  - F1: no `paperwiki.config.recipes` (plural) anywhere
  - F2: no `paperwiki.runners.wiki_ingest` not followed by `_plan`
  - F3: every `CLAUDE_PLUGIN_ROOT=$(...)` has a matching `export`
    within 12 lines (or inline)
  - F4: every fenced ``` ```bash ``` block parses with `bash -n`
  - F5: no `from paperwiki.config import RecipeSchema` (RecipeSchema
    lives at `paperwiki.config.recipe.RecipeSchema`)

  Anti-example citations in Common Rationalizations or Red Flags
  tables can be wrapped in
  `<!-- skip-lint --> ... <!-- /skip-lint -->` markers to be
  exempt from F1/F2/F5. Bash placeholders like `<vault>` are
  pre-quoted before `bash -n` so SKILL prose stays readable while
  the lint still catches real syntax bugs. 75 test items run in
  ~0.14s. A synthetic `tests/unit/fixtures/bad_skill.md` exercises
  every forbidden pattern as a positive-detection check
  (D-9.36.2 + D-9.36.5).

### Changed

- **Setup SKILL Q3, Step 9, Step 10 rewritten** to enforce the new
  privacy contract end-to-end. Q3 collapses to two options; Step 9
  splits into 9a (recipe write) + 9b (secrets.env placeholder
  write, mode 600, never overwrite an existing populated file);
  Step 10 prints the verbatim post-setup `$EDITOR` guidance.
  Common Rationalizations gains a row blocking any future
  "paste the key inline" regression.

- **`recipes/weekly-deep-dive.yaml`** now declares the
  `api_key_env: PAPERWIKI_S2_API_KEY` + `api_key_env_optional: true`
  pair on its `semantic_scholar` source. Behavior matches
  `daily-arxiv` (which the wizard emits): use the key if present,
  fall back gracefully if not.

### Lessons learned

The fresh-user simulation (`paperwiki uninstall --everything
--purge-vault ... --nuke-vault --yes` then `/paper-wiki:setup`) is
worth running before every release. Three of the four v0.3.36
fixes — the privacy regression, the export sweep, and the
module-path drift — were caught in a single trace from that
simulation. Static contract tests (D-9.36.5 forbidden-pattern
list) are the cheapest way to keep those fixes from regressing,
because the bugs all share a structural shape (SKILL prose drifts
from on-disk reality) that a parametric test naturally catches at
~500ms CI cost. Subprocess-execution mode (option (b) from
D-9.36.2) stays deferred (9.85) — static lint catches ~80% of the
class for ~5% of the implementation cost.

### Tests

- 3 new tests in `tests/unit/config/test_recipe.py` covering the
  graceful-degradation matrix (optional×env-set,
  optional×env-unset, required×env-unset).
- 75 test items in the new
  `tests/unit/test_skill_bash_snippets_lint.py` (parametric across
  14 SKILLs × 5 invariants minus skip-lint exemptions, plus 5
  fixture-based positive-detection tests).
- 909 total tests green; mypy --strict clean; ruff check + format
  clean.

## [0.3.35] - 2026-04-28

### Added

- **Flag-driven `paperwiki uninstall`** that can do a complete
  fresh-user reset in one command. The previous `paperwiki uninstall`
  only handled the plugin layer (~30% of paper-wiki's footprint);
  users testing fresh installs had to follow up with a 5-command
  manual sequence (`paperwiki uninstall` + 4× `rm -rf` + 1× python
  edit of `settings.json`). v0.3.35 collapses that into:

  ```
  paperwiki uninstall                                          # plugin layer (unchanged default)
  paperwiki uninstall --everything --yes                       # + config root + shim + marketplace
  paperwiki uninstall --everything --purge-vault PATH --yes    # + paperwiki vault content
  paperwiki uninstall --everything --purge-vault PATH --nuke-vault --yes   # + rm -rf vault
  ```

  Flags compose. `--purge-vault PATH` is surgical (removes only
  paperwiki-created `Daily/`, `Wiki/`, `.digest-archive/`,
  `.vault.lock`, `Welcome.md`); `--nuke-vault` upgrades it to
  `rm -rf PATH` for a complete vault wipe. `--yes` / `-y` skips the
  confirmation prompt; `--verbose` / `-v` logs each removal.

- **Idempotent re-runs.** A second `paperwiki uninstall --everything
  --yes` after a clean wipe exits 0 with `nothing to remove` instead
  of erroring on missing targets.

- **Vault handling separation.** Vault content is its own
  `--purge-vault PATH` flag rather than a default behaviour — the
  user must point at the vault explicitly to opt into vault changes.
  This keeps the safe-default behaviour exactly the same as v0.3.34.

### Changed

- **`paperwiki uninstall` orchestration moved** from `cli.py` (inline
  helpers) to a new `paperwiki.runners.uninstall` module. The CLI
  handler is now a thin flag-collector that builds an `UninstallOpts`
  and delegates. Tests can drive the orchestrator directly via
  `tmp_path` fixtures without needing to monkeypatch `cli` constants.

- **README "Uninstall" section** rewritten to document the four flags,
  with a "Fresh-user reset" recipe block calling out the
  one-command wipe.

- **`skills/uninstall/SKILL.md`** Step 1 now describes the
  flag-driven uninstall (plugin / `--everything` / `--purge-vault` /
  `--nuke-vault`) and adds a "Fresh-user reset" Step 1b. Dropped the
  prose that told users to `rm -rf ~/.config/paper-wiki/` manually —
  that's now `--everything`.

### Lessons learned

The previous `paperwiki uninstall` semantics (plugin layer only) were
honest but incomplete: the word "uninstall" implies "remove every
paper-wiki trace from this machine", which is what users actually
want when they fresh-test or switch machines. v0.3.35 keeps the
safe-by-default contract (no flag = no surprise destruction) while
making the full reset a one-liner. The flag-driven design beats a
separate `paperwiki nuke` subcommand because flags compose: you can
opt into the user-config wipe without touching a vault, or vice
versa, without learning a second command.

### Tests

- 14 new tests in `tests/unit/cli/test_uninstall_flags.py` and
  `tests/unit/cli/test_uninstall_idempotent.py` covering A1-A12 and
  re-run idempotency. Updated 1 pre-existing test
  (`TestCliUninstall.test_uninstall_removes_cache_and_json`) to
  monkeypatch `Path.home()` and pass `--yes` for the new prompt.
- 831 total tests green; mypy --strict clean; ruff check + format
  clean.

## [0.3.34] - 2026-04-28

### Fixed

- **SKILL sweep (14 files)**: Replaced all 19 stale
  `${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.X` invocations
  with `paperwiki <subcommand>` shim calls guarded by
  `export PATH="$HOME/.local/bin:$PATH"` (Flavour-A, -B, and -C patterns
  eliminated). Also dropped `.venv/.installed` stamp checks in digest and
  setup SKILLs; replaced with `paperwiki status` readiness gate.

- **digest Step 7b**: Dropped phantom `--fold-citations` flag (never
  implemented in `wiki_ingest_plan.py`). Citation folding is implicit
  inside `--auto-bootstrap`; the runner has never had a separate
  citation-folding flag. Replaced the slash-command chain with a single
  `paperwiki wiki-ingest "$VAULT_PATH" "<canonical-id>" --auto-bootstrap`
  bash block.

- **`paperwiki diagnostics` subcommand (Task 9.59)**: Wired
  `runners.diagnostics.main` into the Typer app as
  `app.command(name="diagnostics")` so `paperwiki diagnostics` now works
  via the shim consistently across setup and bio-search SKILLs.

- **Shim tag bump**: `hooks/ensure-env.sh` EXPECTED_TAG and heredoc body
  updated from `v0.3.33` → `v0.3.34` so existing shims are overwritten on
  first SessionStart after upgrade.

### Added

- **Regression test** `tests/unit/test_skills_md_no_legacy_venv.py`:
  71 parametric tests across all 14 `skills/*/SKILL.md` files asserting
  no legacy `python -m paperwiki.runners.` invocations, no `--fold-citations`
  flag, and that `wiki-ingest` SKILLs use `--auto-bootstrap`.

## [0.3.33] - 2026-04-28

### Fixed

User-smoke of v0.3.32's `/paper-wiki:digest daily` SKILL silently routed
to the bundled starter recipe instead of the user's personal recipe at
`~/.config/paper-wiki/recipes/daily.yaml`. Result: 0 recommendations
plus a digest written into the user's UNRELATED Obsidian vault as a
fresh `Daily/` folder. Three orthogonal fixes ship in v0.3.33:

- **SKILL Step 1 hardening (skills/digest/SKILL.md).** v0.3.32 described
  recipe resolution as prose ("personal first, then bundled"). Claude
  executed it by running `ls recipes/` with cwd that drifted into the
  plugin cache (`${CLAUDE_PLUGIN_ROOT}/recipes/`), listed the bundled
  starters, and picked `daily-arxiv.yaml` because it looked closest to
  "daily". **Fix**: replaced the prose with an explicit bash snippet
  that uses an absolute-path lookup against
  `${PAPERWIKI_HOME:-${PAPERWIKI_CONFIG_DIR:-$HOME/.config/paper-wiki}}/recipes/`,
  forbids `ls` / `find` / `cd` / relative paths in the lead, and emits
  a mandatory `echo "Using recipe: $RECIPE"` for visibility. Step 4
  now passes `"$RECIPE"` to the runner instead of a `<recipe-path>`
  placeholder so the dependency on Step 1 is explicit. Added one
  Common Rationalizations row + one Red Flags STOP-signal bullet so
  Claude treats `ls recipes/` as an interrupt.

- **Starter recipe defang (recipes/*.yaml).** `daily-arxiv.yaml` shipped
  with `vault_path: ~/Documents/Obsidian-Vault` and
  `output_dir: ~/paper-wiki/digests` as the bundled defaults. When the
  SKILL fell through to the bundled starter, the runner happily wrote
  into the user's UNRELATED vault. **Fix**: replaced every real default
  in `daily-arxiv.yaml`, `weekly-deep-dive.yaml`,
  `biomedical-weekly.yaml`, and `sources-only.yaml` with the
  placeholder `<EDIT_ME_BEFORE_USE>` (covers reporter `vault_path` /
  `output_dir` and dedup `vault_paths`). The runner now fails loud at
  path resolution if the placeholder reaches it. The example doc at
  `docs/example-recipes/personal-johnny-decimal.yaml` is intentionally
  left as-is — it documents a real layout pattern users adapt.

- **Shim tag bump (hooks/ensure-env.sh).** Bumped the shim
  tag-line to `# paperwiki shim — v0.3.33 (...)`. Body content
  (PYTHONPATH fallback, shared venv, self-bootstrap) carries over
  unchanged from v0.3.32. The tag bump triggers ensure-env.sh's
  idempotent grep guard so existing shims get rewritten on first
  SessionStart after upgrade.

### Lessons learned

SKILL prose is unreliable when ambiguity space exists. "Personal first,
then bundled" reads well to a human but lets Claude rationalize a
shorter path (literal `ls recipes/`) that produces the wrong answer.
Explicit bash snippets — with the resolution variables named, the
search order encoded as `if/elif`, and forbidden tools called out in
the lead — beat resolution-order narrative every time. Bundled
starter recipes must never carry real path defaults; placeholders
that fail loud are safer than friendly defaults that silently clobber
unrelated user state.

### Tests

- 9 new unit tests in `tests/unit/skills/test_digest_skill_md.py`
  pinning the explicit-bash Step 1 contract (CONFIG_ROOT precedence,
  personal-first ordering, alias mapping, mandatory visibility echo,
  forbidden-tool lead, no naked `ls recipes/` in Process steps,
  Step 4 uses `$RECIPE`, rationalizations + red-flags coverage).
- 5 new unit tests in `tests/unit/recipes/test_starter_recipes.py`
  pinning the EDIT_ME defang for every starter recipe + flagship
  `daily-arxiv.yaml` regression check against the real Obsidian-Vault
  default that caused v0.3.32.
- Updated 3 smoke-test pins for the v0.3.33 shim tag-line and the
  manifest version.
- 744 total tests green; mypy --strict clean; ruff check + format
  clean.

## [0.3.32] - 2026-04-28

### Fixed

Three bugs caught in the v0.3.31 user smoke that prevented the
defence-in-depth from actually engaging:

- **Shim tag-line wasn't bumped from v0.3.29** when v0.3.31 added
  PYTHONPATH to the heredoc body. ensure-env.sh's idempotent guard
  uses the tag-line as the rewrite trigger; with the same tag,
  existing shims kept the OLD body without PYTHONPATH. **Fix**: bumped
  tag to `# paperwiki shim — v0.3.32 (shared venv + self-bootstrap +
  PYTHONPATH fallback).` Now ensure-env.sh sees a stale tag on
  upgrade and rewrites the shim with the new content.

- **`uv venv "$VENV_DIR"` ran unconditionally**, failing with `A
  virtual environment already exists at <path>. Use --clear to replace
  it.` whenever ensure-env.sh re-ran on a populated venv (e.g. after
  manual `rm .installed` to force a re-bootstrap). **Fix**: guard
  with `[ ! -d "$VENV_DIR" ]` — the venv is created once and reused,
  matching the v0.3.29 design intent. The pip-fallback branch already
  had this guard.

- **Prong B (`paperwiki update` pre-rename uninstall) was a silent
  no-op for uv users** because uv-created venvs ship WITHOUT pip by
  default (uv philosophy: use `uv pip` not pip directly). The v0.3.31
  helper called `<venv>/bin/python -m pip uninstall paperwiki -y`
  which exited non-zero with `No module named pip` for uv users.
  **Fix**: prefer `uv pip uninstall --python <venv> paperwiki` when
  `uv` is on PATH; fall back to `python -m pip` for legacy
  pip-bootstrapped venvs. Now Prong B actually engages on the dominant
  paper-wiki install path (uv).

### Tests

- Updated 2 smoke tests pinning the new shim tag-line.
- 730 total tests green; mypy --strict clean; ruff check + format
  clean.

## [0.3.31] - 2026-04-28

### Fixed

- **`paperwiki <X>` after upgrade hit `ModuleNotFoundError: No module
  named 'paperwiki'`** — design flaw introduced in v0.3.29 (Task 9.31)
  surfaced in v0.3.30 user smoke. The shared venv at
  `${PAPERWIKI_HOME}/venv` carried an editable install of `paperwiki`
  whose `.pth` file referenced
  `~/.claude/plugins/cache/paper-wiki/paper-wiki/<old-ver>/src`. When
  `paperwiki update` renamed `<old-ver>` → `<old-ver>.bak.<ts>`, the
  `.pth` path became stale — the next `paperwiki <X>` call from a
  fresh terminal couldn't import `paperwiki.cli`.

  **Two-pronged defence in depth (v0.3.31)**:

  1. **Shim PYTHONPATH fallback (v0.3.31-A)**: `~/.local/bin/paperwiki`
     now exports `PYTHONPATH="<latest-cache>/src"` before exec'ing
     the venv binary. Even when the editable-install `.pth` is stale,
     the latest cache's `src/` is on `sys.path` and `paperwiki`
     resolves cleanly.
  2. **Pre-rename uninstall (v0.3.31-B)**: `paperwiki update` now
     calls `pip uninstall paperwiki -y` against the shared venv
     BEFORE renaming the cache dir. This removes the soon-to-be-stale
     `.pth` cleanly so the next SessionStart's editable re-install is
     the only source of truth.

  Manual recovery for users on v0.3.29 / v0.3.30 hitting this bug:

  ```bash
  rm -f ~/.config/paper-wiki/venv/.installed
  CLAUDE_PLUGIN_ROOT=~/.claude/plugins/cache/paper-wiki/paper-wiki/<latest> \
    bash ~/.claude/plugins/cache/paper-wiki/paper-wiki/<latest>/hooks/ensure-env.sh
  ```

  Or just upgrade to v0.3.31 — the new shim self-heals.

### Tests

- 1 new smoke test pinning shim `PYTHONPATH=$CACHE_ROOT/$LATEST/src`
  contract (`test_ensure_env_shim_sets_pythonpath_to_latest_src`).
- 2 new `TestCliUpdateUninstallsStaleEditableInstall` tests pinning
  the pre-rename uninstall flow + the no-venv-yet noop path.
- 730 total tests green; mypy --strict clean; ruff check + format
  clean.

## [0.3.30] - 2026-04-28

### Fixed

- **`paperwiki <subcommand>` was BROKEN for every runner-backed
  subcommand** (regression from v0.3.27 / Task 9.29 — caught only in
  v0.3.30 user smoke when `paperwiki where` returned `Missing command.
  Try 'paperwiki where --help' for help.`). Root cause: cli.py used
  `app.add_typer(_X_app, name="X")` to mirror runners as parent
  subcommands. `add_typer` wraps the sub-app in a `click.Group` that
  REQUIRES a sub-command — single-command auto-promotion does NOT
  apply. Every invocation that didn't include `--help` (the help
  printer exits early before the group dispatcher runs) failed:
  `paperwiki digest`, `paperwiki wiki-ingest`, `paperwiki gc-archive`,
  `paperwiki gc-bak`, `paperwiki where`, etc. — all 11 of them.

  v0.3.27's CLI surface tests only checked `<name> --help` exit code,
  which masked the bug because Typer's `--help` short-circuits the
  group routing.

  **Fix**: replaced every `app.add_typer(_X_app, name="X")` with
  `app.command(name="X")(_X_main)` — re-registers each runner's
  `main` callable directly as a parent-app command, bypassing the
  click.Group wrapper. Each runner module still ships its own
  standalone Typer app for `python -m paperwiki.runners.<name>`
  invocation; only the parent-app wiring changed.

  Verified all 11 subcommands now route correctly via
  `paperwiki <name>` (with or without args).

### Tests

- **CI green again on narrow terminals** (Rich `--help` line-wrap
  fix): three `TestCli::test_help_lists_*_flags` tests in
  `tests/unit/runners/test_gc_bak.py`,
  `tests/unit/runners/test_gc_digest_archive.py`, and
  `tests/unit/runners/test_where.py` were passing locally (wide
  terminal) but failing in CI (narrow terminal) because Rich wrapped
  long flag names like `--keep-recent` across lines, breaking the
  literal substring assertion. Fixed by passing
  `env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"}` to
  CliRunner so Rich uses plain wide-format output for the help text.
- `tests/unit/test_cli.py::TestCliRunnerImports` renamed to
  `test_all_runner_mains_importable` and updated to import `_main`
  callables instead of `_app` Typer apps (matches the new wiring).
- 727 total tests green; mypy --strict clean; ruff check + format
  clean.

### Migration

- Upgrade is straightforward: `paperwiki update` then `/exit + claude`
  + `/plugin install paper-wiki@paper-wiki`.
- v0.3.29 users hit the `Missing command` error — running v0.3.30 is
  the only way out short of `python -m paperwiki.runners.<X>`
  (long-form workaround that still works).
- v0.3.28 users skipping straight to v0.3.30 also need the v0.3.29
  one-time migration: legacy per-version `.venv` is COPIED to
  `${PAPERWIKI_HOME}/venv` then symlinked.

## [0.3.29] - 2026-04-28

### Changed

- **Centralised paper-wiki venv at `${PAPERWIKI_HOME}/venv`** (Task 9.31,
  D-9.31.1 — D-9.31.4). Previously each plugin version lived under its
  own `~/.claude/plugins/cache/paper-wiki/paper-wiki/<ver>/.venv/`. The
  v0.3.28 user smoke surfaced two pain points: (1) `/reload-plugins`
  never bootstraps the venv (only SessionStart does), so the first
  `paperwiki <X>` call after upgrade crashed with
  `.venv/bin/paperwiki: No such file or directory`; (2) `.bak/` cache
  directories accumulated forever with no cleanup path. Both addressed
  in this release.

  All paper-wiki user state now co-locates under one root:

  ```
  ${PAPERWIKI_HOME:-~/.config/paper-wiki}/
  ├── recipes/         # YAML recipes (existing v0.3.4+)
  ├── secrets.env      # API keys (existing v0.3.4+)
  └── venv/            # NEW — shared venv across plugin versions
  ```

  Override via `$PAPERWIKI_HOME` (preferred), or the legacy
  `$PAPERWIKI_CONFIG_DIR` (still honored as alias for backward compat),
  or finer-grained `$PAPERWIKI_VENV_DIR` for users who want config in
  the default but venv elsewhere.

  `${CLAUDE_PLUGIN_ROOT}/.venv` is now a **symlink** to
  `${PAPERWIKI_HOME}/venv`, so existing SKILL invocations
  (`${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.X`)
  keep working without changes.

  Migration on first v0.3.29 upgrade: any legacy per-version `.venv/`
  directory is COPIED to the shared path (preserving already-synced
  deps), then replaced with the symlink. No re-sync needed.

### Added

- **Self-bootstrapping `~/.local/bin/paperwiki` shim** (Task 9.32 /
  D-9.32.1). When the shared venv is missing, the shim now inline-invokes
  `${CLAUDE_PLUGIN_ROOT}/hooks/ensure-env.sh` before exec, so users
  hitting the `/reload-plugins` UX trap still get a working
  `paperwiki <X>` from a fresh terminal. One-time cost ~5-10s on the
  first cold run after a brand-new install; subsequent calls are
  fast-path noop. The shim respects the full env-var precedence chain
  (`PAPERWIKI_VENV_DIR > PAPERWIKI_HOME > PAPERWIKI_CONFIG_DIR > default`).

- **`paperwiki gc-bak` runner + `PAPERWIKI_BAK_KEEP=3` retention**
  (Task 9.33 / D-9.33.1 — D-9.33.3). Power users no longer have to
  manually `rm -rf` historic cache directories.

  ```
  paperwiki gc-bak [--keep-recent N] [--max-age-days N]
                   [--dry-run] [-v]
  ```

  - Default `--keep-recent` resolves from `$PAPERWIKI_BAK_KEEP`
    (fallback `3`). Rationale for 3: 1 = no rollback target;
    2 = single-step rollback; 3 = current + two backup targets,
    covering "I forgot which version I came from" cases.
  - Combined modes: when both `--keep-recent` and `--max-age-days`
    are passed, a `.bak` is removed only if it falls outside the
    recent-N window AND is older than the age threshold (intersection
    — preserves recent-but-old caches you might still need).
  - Filename pattern guard
    (`^\d+\.\d+\.\d+\.bak\.\d{8}T\d{6}Z$`) — user-added directories
    in the cache root are surfaced under `skipped_unrecognized` and
    never touched.
  - `paperwiki update` now auto-prunes after a successful upgrade,
    keeping the most-recent N `.bak` directories per
    `$PAPERWIKI_BAK_KEEP`. `PAPERWIKI_BAK_KEEP=0` is the escape hatch
    (preserve all `.bak`, useful for power users who manage retention
    themselves).
  - JSON output mirrors the v0.3.28 `gc-archive` shape.

- **`paperwiki where` CLI subcommand** (Task 9.35 / D-9.31.5). Prints
  every paper-wiki path on disk with sizes:

  ```
  $ paperwiki where
  config + venv (PAPERWIKI_HOME): /Users/.../paper-wiki  (252.8 MB)
    ├── recipes/        (3 files, 12.4 KB)
    ├── secrets.env     (256 B)
    └── venv/           (252.4 MB, deps for 0.3.29)
  plugin cache                  : /Users/.../paper-wiki  (38.2 MB)
    ├── 0.3.29/        (current)
    ├── 0.3.28.bak.20260428T150731Z
    ├── 0.3.27.bak.20260301T120000Z
    └── 0.3.26.bak.20260101T000000Z
  marketplace clone             : /Users/.../paper-wiki  (8.1 MB)
  shim                          : /Users/.../paperwiki  (562 B)

  total disk used: 299.1 MB
  ```

  `--json` emits the same data as a machine-parseable shape for
  cron / scripting. Replaces the user's mental "where is everything?"
  check with one command. Pairs with `paperwiki gc-bak --dry-run` for
  pre-cleanup audit and `paperwiki uninstall` + `rm -rf
  $PAPERWIKI_HOME` for the full nuke recipe.

- **`paperwiki status` 4th line: `bak directories : N kept; oldest <date>`**
  surfaces the retention state at a glance so users see the cleanup
  history without having to invoke `where` or `gc-bak`.

- **3 new internal helpers** in `paperwiki._internal.paths`:
  `resolve_paperwiki_home()`, `resolve_paperwiki_venv_dir()`,
  `resolve_paperwiki_recipes_dir()` — single source of truth for the
  env-var precedence chain consumed by both Python runners and bash
  hooks.

### Documentation

- README "Upgrading" section calls out explicitly that
  **`/reload-plugins` is INSUFFICIENT** for first-run-after-version-change
  (paired with the `.venv/bin/paperwiki: No such file or directory`
  troubleshooting row, D-9.34.1).
- README new section "Where paper-wiki keeps your stuff (v0.3.29+)"
  documents the single-root layout, `PAPERWIKI_HOME` override, and
  `paperwiki where` workflow. Notes the trade-off for dotfiles
  managers / Time Machine users (the venv lives under `~/.config/`,
  add to ignore list / exclude from backup if needed).
- README troubleshooting gains 3 new rows covering the venv-missing
  symptom, `.bak/` accumulation cleanup, and the `paperwiki where`
  inventory command.
- `skills/update/SKILL.md` Process Step 3 spells out the
  `/reload-plugins` insufficiency with the exact failure mode users
  will encounter.
- `skills/uninstall/SKILL.md` notes the deeper-clean recipe
  (`paperwiki gc-bak --keep-recent 0` + `rm -rf $PAPERWIKI_HOME`)
  paired with `paperwiki where` as the safe inventory step.

### Tests

- 14 new unit tests in `tests/unit/_internal/test_paths.py` for the
  full env-var precedence chain (default, `PAPERWIKI_HOME` override,
  legacy `PAPERWIKI_CONFIG_DIR` alias, finer-grained
  `PAPERWIKI_VENV_DIR`, empty-string handling, `~` expansion).
- 8 new integration tests in `tests/integration/test_venv_migration.py`
  pinning the legacy → shared migration end-to-end (real-dir → symlink,
  copy semantics, idempotency, all override paths).
- 16 new unit tests in `tests/unit/runners/test_gc_bak.py` covering
  filename guard, keep-recent N, max-age-days, combined modes,
  dry-run, idempotency, missing cache root, CLI exit codes,
  `PAPERWIKI_BAK_KEEP` env var honoring.
- 13 new unit tests in `tests/unit/runners/test_where.py` covering
  PathReport sizing, build_where_report aggregation, JSON output
  shape, missing-path graceful handling.
- 4 new unit tests in `tests/unit/test_cli.py` (auto-prune in
  `update`, status 4th line, expanded subcommand surface to 14
  commands).
- 2 new smoke tests in `tests/test_smoke.py` pin the v0.3.29 shim
  tag-line + self-bootstrap branch + env-var precedence chain.

## [0.3.28] - 2026-04-28

### Added

- **`paperwiki gc-archive` runner** (Task 9.30 / D-9.30.*). Cleans up
  old `<vault>/.digest-archive/<YYYY-MM-DD>-paper-digest.md` files
  written by the markdown reporter. Power users hate hidden-directory
  growth — this is the explicit user-driven GC tool. Sizing context:
  ~30-50 KB per file, ~11-18 MB per year, ~55-90 MB per 5 years.

  Surface:

  ```
  paperwiki gc-archive [--vault <path>] [--max-age-days N]
                       [--dry-run] [--gzip] [-v]
  ```

  Behavior:

  - **D-9.30.1**: when `--vault` is omitted, auto-discovers from
    `~/.config/paper-wiki/recipes/daily.yaml` (prefers obsidian
    reporter's `vault_path`; falls back to deriving from the markdown
    reporter's `output_dir` ending in `/.digest-archive`). Discovery
    failure exits 2 with a clear message.
  - **D-9.30.2**: scope locked to `<vault>/.digest-archive/` only.
    Filename pattern guard (`^\d{4}-\d{2}-\d{2}-paper-digest\.md(\.gz)?$`)
    skips anything that doesn't match — user-added notes, `.icloud`
    sync stubs, `.DS_Store`, etc. surface in `skipped_unrecognized`
    and are never touched.
  - **D-9.30.3**: `--max-age-days` defaults to `365` (1 year). Common
    values documented in `--help`: 90 / 365 / 730.
  - `--dry-run` reports what would happen without mutating disk.
  - `--gzip` compresses old files in place (`<file>.md` →
    `<file>.md.gz`); reversible via `gunzip`. Already-gzipped files
    are kept (no double-gzip).
  - Idempotent. Re-running emits empty `removed` / `gzipped` lists.
  - Missing `.digest-archive/` is a clean no-op (AC-9.30.7).

  JSON output to stdout includes `vault`, `archive_dir`,
  `max_age_days`, `mode`, `dry_run`, `removed`, `gzipped`, `kept`,
  `skipped_unrecognized`, `errors`.

- **`MarkdownReporter.archive_retention_days: int | None = None`**
  recipe field (Task 9.30 (a)). Documents the user's intended retention
  window. Reporter intentionally does NOT GC at emit time — the field
  is informational metadata that future revisions of `gc-archive` can
  read to default `--max-age-days` from the recipe.

- **`paperwiki gc-archive` exposed as a CLI subcommand** (Task 9.30
  (c)) via `app.add_typer` plumbing in `paperwiki.cli`. Continues the
  v0.3.27 surface-symmetry pattern.

### Tests

- 20 new unit tests in `tests/unit/runners/test_gc_digest_archive.py`
  covering filename pattern guard, age threshold gating, dry-run,
  gzip mode, idempotency, missing-archive no-op, vault auto-discovery
  (4 paths), CLI exit codes, and the documented `--max-age-days = 365`
  default.
- 3 new tests in `tests/unit/plugins/reporters/test_markdown.py`
  covering the new `archive_retention_days` field accepts default
  `None`, accepts explicit int, and emit-time behavior unchanged.
- Integration smoke (`tests/integration/test_cli_smoke.py`) extended
  to include `gc-archive` in the expected CLI surface and to assert
  `python -m paperwiki.runners.gc_digest_archive --help` exits 0.

## [0.3.27] - 2026-04-28

### Added

- **CLI/SKILL surface symmetry** (Task 9.29). Every paper-wiki operation
  is now invocable from BOTH `/paper-wiki:<name>` (Claude Code) AND
  `paperwiki <name>` (terminal). The user explicitly requested
  "兩頭都能執行" — power users on cron / remote shells now get the same
  pipeline a Claude session does.

  **6 new CLI subcommands** added via `app.add_typer` plumbing in
  `src/paperwiki/cli.py`:

  - `paperwiki digest <recipe>`
  - `paperwiki wiki-ingest <vault> <id>`
  - `paperwiki wiki-lint <vault>`
  - `paperwiki wiki-compile <vault>`
  - `paperwiki extract-images <vault> <id>`
  - `paperwiki migrate-sources <vault>`

  **1 deterministic CLI** for wiki search:

  - `paperwiki wiki-query <vault> <q>` — substring search by default
    (D-9.29.1). The runner now emits a one-line stderr footer pointing
    at `/paper-wiki:wiki-query` for LLM-driven Q&A; stdout stays
    JSON-clean so the SKILL's subprocess parsing is unaffected.

  **3 new SKILLs** as thin CLI wrappers (D-9.29.2):

  - `/paper-wiki:status` → `paperwiki status` (3-line install report).
  - `/paper-wiki:update` → `paperwiki update` (refresh + clean).
  - `/paper-wiki:uninstall` → prints redirect to `paperwiki uninstall`
    from a fresh terminal. Does NOT shell out from inside Claude (the
    active session would lose its SKILLs and runners mid-execution).

- **Each runner's `@app.command()` decorator now uses an explicit
  `name="<cli-name>"`** so the `paperwiki <X> --help` and
  `python -m paperwiki.runners.<X> --help` invocations both surface the
  cli-friendly hyphenated name. Existing `python -m paperwiki.runners.<X>`
  invocations remain backward-compatible (Typer's single-command
  auto-promotion preserves the no-subcommand-required behavior).

- **`if __name__ == "__main__"` block** in `paperwiki.cli` so
  `python -m paperwiki.cli` works from a clean subprocess (matters for
  the new integration smoke test — and for any user who hasn't put
  `~/.local/bin` on PATH yet).

### Changed

- **README "SKILLs" section gains 3 new rows** (status / update /
  uninstall) plus a brand-new **CLI vs SKILL surface symmetry**
  triage table that documents which operations are mirrored, which
  stay SKILL-only (analyze / bio-search — LLM-shaped), and which stay
  CLI-only (none anymore — but uninstall is "CLI does the work, SKILL
  prints the redirect").

### Out of scope (logged for future)

- **9.31 candidate**: `/paper-wiki:status` SKILL surfacing version
  drift between marketplace clone, cache, and pip-installed
  `paperwiki` console-script. Plan was to defer until users report
  surprise (D-9.29.3); v0.3.27 keeps the SKILL focused on the cache /
  marketplace / enabledPlugins triple.

### Tests

- 14 new unit tests in `tests/unit/test_cli.py`:
  - `TestCliSubcommandSurface` (12 tests) — pins the 11-command
    CLI surface and that each `paperwiki <name> --help` exits 0.
  - `TestCliRunnerImports` (1 test) — sanity check that cli.py
    imports each runner's Typer app at module load.
- 1 new unit test in `tests/unit/runners/test_wiki_query.py`:
  - `test_emits_skill_redirect_footer_to_stderr` — pins the v0.3.27
    contract: stdout JSON parseable + stderr carries the SKILL pointer.
- New integration smoke test `tests/integration/test_cli_smoke.py`:
  - Subprocess test that `python -m paperwiki.cli --help` lists every
    expected subcommand.
  - Parametrized `paperwiki <name> --help` exit-0 check (11 commands).
  - Parametrized `python -m paperwiki.runners.<X> --help` exit-0 check
    (8 runners) — pins backward compat for the existing module-runner
    invocation path.

## [0.3.26] - 2026-04-28

### Fixed

- **Digest callout no longer fabricates topic relevance** (Task 9.28).
  v0.3.17 added `topic_strength_threshold` filtering to
  `MarkdownWikiBackend.upsert_paper` so weak single-keyword matches
  would NOT pollute the wiki concept's `sources:` frontmatter — but the
  obsidian reporter's per-paper `> [!info] Metadata` callout
  (`Matched topics:` line) read `rec.matched_topics` directly without
  applying the same gate. Result on the 2026-04-28 fresh-vault smoke:
  three audio / RGB-T / hallucination papers showed
  `[[biomedical-pathology]]` in their callout despite the wiki backend
  correctly excluding them — the callout claimed a relevance the rest
  of the system disagreed with.

  Extracted the v0.3.17 inline filter into a module-level helper
  `paperwiki.plugins.backends.markdown_wiki.filter_topics_by_strength`
  that both the backend (`upsert_paper`) and reporter
  (`render_obsidian_digest` / `_render_recommendation`) now call. The
  callout's `Matched topics` line is gated by the new
  `ObsidianReporter.topic_strength_threshold` field (recipe-level),
  default `0.3` so the gate matches `wiki_topic_strength_threshold`
  out of the box (D-9.28.1, D-9.28.2). Backward-compatible: legacy
  Recommendations whose `score.notes` lacks `topic_strengths`
  (hand-built fixtures, non-composite scorers) keep all matched
  topics.

### Added

- **`topic_strength_threshold` recipe field on `obsidian` reporter**.
  Conservative readers who want zero single-keyword leakage can set
  `topic_strength_threshold: 0.6` in `~/.config/paper-wiki/recipes/<name>.yaml`
  (under the obsidian reporter block). The default `0.3` keeps the
  callout consistent with the wiki backend's frontmatter gate.

### Documentation

- Users on stale recipes (installed ≤ v0.3.16) still see the
  2026-04-28 leak even after this fix because the underlying recipe
  contains keywords like `foundation model` that trip generic-keyword
  matches at strength 0.5 (above the default 0.3 threshold). **Two-pronged
  fix**: (a) v0.3.26 catches future leaks at the display layer, (b)
  running `/paper-wiki:migrate-recipe` (shipped in v0.3.23) drops the
  stale keywords surgically. Both prongs recommended for users
  upgrading from v0.3.16 or earlier.

### Tests

- 7 new unit tests for `filter_topics_by_strength` (helper extraction,
  threshold gating, backward compat, malformed-payload defense).
- 5 new unit tests for `render_obsidian_digest` callout filtering
  (incl. the 2026-04-28 leak reproducer using strength-0.5 single-keyword
  match against threshold 0.6).
- 3 new unit tests for `ObsidianReporter.__init__` accepting and
  propagating the new field.

## [0.3.25] - 2026-04-28

### Fixed

- **`paperwiki update` had THREE silent no-op bugs** — `_cache_version()`,
  `_drop_from_installed_plugins()`, and `_drop_from_enabled_plugins()`
  in `src/paperwiki/cli.py` all assumed the underlying JSON used a
  `list[dict]` shape, but Claude Code 2.1.119 actually uses a
  `dict[plugin_id, ...]` shape:
  - `installed_plugins.json["plugins"]` = `dict[plugin_id, list[install_entry]]`
  - `settings.json["enabledPlugins"]` and
    `settings.local.json["enabledPlugins"]` = `dict[plugin_id, bool]`
  
  So `paperwiki update` always saw "no install detected" (cache version
  returned `None`) and never cleaned `installed_plugins.json` or
  `settings.json` enabledPlugins. The cache rename worked because that
  ran on disk; the JSON cleanup never did. Result: every "successful"
  `paperwiki update` left stale entries that caused `/plugin install`
  to short-circuit "already installed globally" (the very thing
  `paperwiki update` was built to prevent).

  Rewrote all three functions against the real Claude Code 2.1.119
  schema. Test fixtures updated to use real shapes.

### Tests

- Existing `tests/unit/test_cli.py` fixtures rewritten to use real
  dict shapes (was `list[{"name": ..., "id": ...}]` — wrong).
- Regression coverage: `paperwiki update` against a state with
  paper-wiki present in all three shape-correct files actually drops
  all three entries.

## [0.3.24] - 2026-04-28

### Changed

- **`paperwiki update` first-line wording trimmed.** Was
  `paper-wiki upgraded marketplace 0.3.20 → 0.3.23` (with the awkward
  `marketplace (not installed)` placeholder when nothing was cached).
  Now `paper-wiki: 0.3.20 → 0.3.23` (or `paper-wiki: not installed →
  0.3.23` when no current install). Concise X → Y format that matches
  the user's mental model of what an upgrade message should look like.

## [0.3.23] - 2026-04-28

### Fixed

- **Task 9.19 — `s2.parse.skip` log noise silenced.** Four "sparse record"
  branches in `_parse_entry` (missing title/abstract, bad publication date,
  no authors, no usable id) downgraded from `WARNING` to `DEBUG`. The
  `model validation` branch stays at `WARNING` — that indicates a real schema
  mismatch, not a normal sparse S2 record. A single `INFO` summary line
  (`s2.parse.skipped_summary`) is now emitted at the end of each fetch when
  at least one entry was skipped, carrying per-reason counts for power users
  running `--verbose`. Users running daily digests no longer see 3+ spurious
  WARNING lines on every run.

### Added

- **Task 9.20 — digest SKILL surfaces per-paper extract-images summary.**
  Process Step 7a now always emits a per-paper summary block after running
  extract-images for each top-N paper, using four outcome classifications:
  success-with-figures / success-no-figures / skipped-non-arxiv /
  failed-with-error. No image extraction failure is silently absorbed.
  Users see exactly which paper had what result and why.

- **Task 9.21 — `paperwiki migrate-recipe` CLI subcommand and runner.**
  New `paperwiki.runners.migrate_recipe` module and `paperwiki migrate-recipe`
  CLI subcommand surgically update stale personal recipes to the latest
  template keywords without re-running the full setup wizard. The initial
  migration table covers v0.3.17 (drops `foundation model` from
  `biomedical-pathology`). Always idempotent; creates a timestamped backup
  before any write. The `/paper-wiki:migrate-recipe` SKILL and slash command
  wrap the runner with a dry-run-first flow and AskUserQuestion confirmation.
  Setup SKILL Branch 1 ("Keep current config") now runs a stale-keyword
  heuristic and offers a fifth option to migrate immediately.

### Changed

- **Task 9.23 — digest SKILL "Score reasoning" is now interpretive, not
  transcriptive.** Process Step 8 contract updated: Score reasoning must be
  1–2 sentences that explain WHY the paper scores the way it does, acknowledge
  specific limits (e.g. "rigor held back by brand-new arXiv"), and cite
  specific topic matches. Restating the four sub-score numbers verbatim is
  explicitly forbidden. New Common Rationalizations rows and a Red Flag pin
  the contract against drift.

### Tests

- 6 new tests (3 × 9.19 unit, 2 × 9.21 smoke + 4 × 9.21 config/runner, 1 × 9.20 smoke,
  1 × 9.23 smoke).

## [0.3.22] - 2026-04-28

### Changed

- **`paperwiki update` output trimmed** for cleaner UX. Removed the
  trailing two-line technical explanation about `/plugin install`'s
  short-circuit / cleared JSON entries — the next-steps list above
  carries the actionable info; the explanation read like internal
  debug rationale leaking into user-facing output.

## [0.3.21] - 2026-04-28

### Fixed

- **`paperwiki` command not found after install** (Task 9.27). v0.3.20 shipped
  the `paperwiki` console-script entry-point but the venv that contains it
  (`~/.claude/plugins/cache/paper-wiki/paper-wiki/<version>/.venv/bin/paperwiki`)
  is not on the user's PATH, causing `zsh: command not found: paperwiki` when
  trying to use the v0.3.20 upgrade flow.

### Added

- **Auto-installed `~/.local/bin/paperwiki` shim** (Task 9.27).
  `hooks/ensure-env.sh` now installs a version-agnostic shim at
  `~/.local/bin/paperwiki` on every Claude Code SessionStart. The shim
  auto-discovers the latest installed plugin version so future paper-wiki
  upgrades update the venv binary AND the shim invocation seamlessly.
  If `~/.local/bin` is not on the user's PATH, a one-time warning is emitted
  with the exact line to add to their shell rc (non-blocking; marker file
  `~/.local/bin/.paperwiki-path-warned` prevents repeated noise).
  Existing manually-installed shims are preserved — the hook rewrites only
  on stale/missing/foreign content (tag-line grep guard).

### Tests

- `tests/test_smoke.py`: four new tests pin the shim emission block in
  `hooks/ensure-env.sh` — static tag check, idempotency guard pattern,
  PATH-warning marker, and a full integration run in a temp HOME directory.

## [0.3.20] - 2026-04-28

### Added

- **3-priority image extraction** (Task 9.25). `paperwiki._internal.arxiv_source`
  now extracts figures via three cascading strategies:
  (1) figure dirs in the arXiv source tarball (existing, now with min-size filter
  `>200px` on at least one axis preserving v0.3.16 commit `c7d5df4`);
  (2) standalone PDFs at the tarball root converted to PNG via PyMuPDF (new);
  (3) caption-aware crops of the compiled paper PDF when TikZ is detected and
  fewer than 2 figures were found via P1+P2 (new). New runtime dependency:
  `pymupdf>=1.24` (AGPL, compatible with GPL-3.0). The `extract_paper_images`
  runner now writes `Wiki/sources/<id>/images/index.md` with per-figure source
  class (`arxiv-source` / `pdf-figure` / `tikz-cropped`) and emits a `sources`
  sub-dict in its JSON output. Recovers figures from ~80% of arXiv papers (vs
  ~30% on v0.3.19). Reference: github.com/juliye2025/evil-read-arxiv.
- **`paperwiki` console-script** (Task 9.26). New `src/paperwiki/cli.py` exposes
  `paperwiki update`, `paperwiki status`, and `paperwiki uninstall` subcommands.
  `paperwiki update` ends the manual JSON-cleanup ritual every release has
  required: it refreshes the marketplace clone, compares versions, and on drift
  renames the stale cache to `<ver>.bak.<UTC-timestamp>` and prunes
  `installed_plugins.json` plus both `settings.json` / `settings.local.json`
  `enabledPlugins` entries so the subsequent `/plugin install` does a real
  install without the "already installed globally" short-circuit.
  README "Upgrading" section rewritten to lead with `paperwiki update` as the
  primary path; manual flow retained as a fallback footnote.

### Tests

- `tests/unit/_internal/test_arxiv_source.py`: adds Priority-2 root-PDF,
  Priority-3 TikZ-crop, min-size filter, and `_has_tikz` fixtures (12 new).
- `tests/unit/runners/test_extract_paper_images.py`: adds `TestIndexManifest`
  covering `index.md` presence and `sources` JSON field (3 new).
- `tests/unit/test_cli.py` (new): 6 CLI-flow tests via `typer.testing.CliRunner`
  for stale-cache upgrade, up-to-date no-op, missing marketplace clone (exit 2),
  corrupt JSON (exit 1), `status` output, and `uninstall` teardown.
- Smoke tests pin CLI surface (`test_paperwiki_cli_help_lists_subcommands`),
  module imports, `ExtractResult.sources`, and pyproject declarations.

## [0.3.19] - 2026-04-27

### Added

- **Inline figures in Detailed reports** (Task 9.22). Detailed report synthesis
  now embeds the first 1-2 alphabetically-sorted figures from
  `Wiki/sources/<id>/images/` via `![[Wiki/sources/<id>/images/<file>|600]]`
  inside the synthesized block, between Key takeaways and Score reasoning.
  Distinct from the existing card teaser (`|700`) before the Abstract — both
  placements are intentional. Figures are silently skipped for papers with no
  extracted images (e.g. `paperclip:` / `s2:` ids with no arXiv source bundle).
- 5 new smoke tests pin both contracts (inline figures + `auto_ingest_top`
  gating).

### Changed

- **Detailed report synthesis gated by `auto_ingest_top`** (Task 9.24). Only
  the top-N papers (where N = `auto_ingest_top`) get the full Detailed report
  block (Why this matters + Key takeaways + inline figures + Score reasoning).
  Papers ranked below the threshold get a single-line teaser:
  `_Run /paper-wiki:analyze <id> for a deep dive into this paper, or
  /paper-wiki:wiki-ingest <id> to fold it into your concept articles._`
  Setting `auto_ingest_top: 0` makes ALL papers show the teaser (no synthesis).
  Users who want all-paper synthesis can set `auto_ingest_top` to their full
  `top_k` value.

## [0.3.18] - 2026-04-27

### Added

- **Vault advisory lock** (Task 9.17). New `src/paperwiki/_internal/locking.py`
  provides the `acquire_vault_lock(vault_path)` async context manager. All
  mutating runners (`wiki_ingest_plan`, `wiki_compile`, `migrate_sources`) and
  `ObsidianReporter` (when `wiki_backend=True`) acquire the lock before writing
  to `Wiki/`. Concurrent runs now fail immediately with `VaultLockError` (exit
  code 1) instead of producing interleaved partial state.
- **Today's Overview synthesized last** (Task 9.18). The digest SKILL Process
  reorders Steps 7–9: auto-chain (extract-images + wiki-ingest) → per-paper
  Detailed report synthesis → Today's Overview synthesis. The overview is now
  the final LLM pass so it can reference concepts and figures produced by the
  earlier steps. A new Common Rationalizations note ("Do this last") anchors
  the contract.
- Unit tests for `acquire_vault_lock`: lock file creation, sequential
  re-acquisition, parent-dir creation, release-on-exception.
- Smoke tests `test_vault_lock_module_exists` and
  `test_digest_skill_overview_synthesis_comes_after_auto_chain_and_per_paper`
  pin both contracts.

## [0.3.17] - 2026-04-27

### Added

- **Concept-matching threshold** (Task 9.9). `CompositeScorer.score()` now
  serialises per-topic strengths into `ScoreBreakdown.notes["topic_strengths"]`
  as a JSON `dict[str, float]`. `MarkdownWikiBackend.upsert_paper()` accepts a
  new `topic_strength_threshold` parameter (default `0.0`); topics whose
  per-topic strength falls below the threshold are excluded from
  `related_concepts` frontmatter. `ObsidianReporter` exposes
  `wiki_topic_strength_threshold` (default `0.3`) and plumbs it through to
  `upsert_paper`.
- **Auto-stub UX** (Task 9.12). `AUTO_CREATED_SENTINEL_BODY` is now a
  two-paragraph sentinel: the first paragraph marks the stub as intentionally
  empty and names `/paper-wiki:wiki-ingest` as the next step; the second
  paragraph points at `/paper-wiki:wiki-lint` for discovery. The wiki-lint
  SKILL Process Step 2 and the wiki-ingest SKILL Auto-bootstrap section mirror
  this wording so users see a consistent explanation across all surfaces.
- **Setup SKILL keyword hygiene**: the Biomedical & Pathology topic drops
  `foundation model` (cross-domain noise) and collapses duplicate WSI variants
  (`whole-slide image` / `whole slide image`) to a single entry. A new Common
  Rationalizations row warns against generic cross-domain keywords.
- Unit tests for per-topic strength emission (`test_composite_scorer_emits_per_topic_strengths`,
  `test_unmatched_topic_has_zero_strength`) and threshold filtering
  (`test_topic_strength_threshold_filters_matched_topics`,
  `test_zero_threshold_keeps_all_matched_topics`,
  `test_missing_topic_strengths_falls_back_to_all_topics`).
- Smoke tests `test_composite_scorer_emits_per_topic_strengths`,
  `test_wiki_upsert_source_filters_by_topic_strength`,
  `test_wiki_ingest_sentinel_body_explains_next_step`,
  `test_wiki_lint_explains_auto_stub_intent`, and
  `test_setup_skill_biomedical_keywords_exclude_generic_terms`.

## [0.3.16] - 2026-04-27

### Added

- **Per-paper Detailed report synthesis** (Task 9.4). The digest SKILL
  Process Step 9 now fills each `<!-- paper-wiki:per-paper-slot:{id} -->`
  marker with a synthesized Detailed report: "Why this matters" framing,
  2–4 "Key takeaways" bullets from the abstract (never invented), and a
  "Score reasoning" line. Claims must cite `#N` markers; batched prompts
  are the default to amortize cost.
- **Auto-chain image extraction** (Task 9.5). The digest SKILL auto-chain
  now runs `extract_paper_images` **before** `wiki-ingest` for each top-N
  `arxiv:` paper, so figures are on disk when `_try_inline_teaser` is
  invoked on the next digest run. Non-arXiv ids are skipped with a one-line
  reason; failures do not abort the digest.
- Smoke tests `test_digest_skill_describes_per_paper_synthesis` and
  `test_digest_skill_chains_extract_images` pin both contracts.

## [0.3.15] - 2026-04-27

### Added

- **Centralized logger configuration** (`src/paperwiki/_internal/logging.py`).
  New `configure_runner_logging(*, verbose, default_level)` function resets
  loguru's sinks and re-configures a single stderr sink at INFO by default.
  Honors `PAPERWIKI_LOG_LEVEL` env var as the highest-priority override so CI
  and hooks can silence runners with one variable.
- **`--verbose / -v` flag** on every runner (`digest`, `wiki_ingest_plan`,
  `wiki_compile`, `wiki_query`, `wiki_lint`, `extract_paper_images`,
  `migrate_sources`, `diagnostics`). Passing `--verbose` enables DEBUG-level
  logging; default remains INFO (no debug noise on normal runs).
- **Unit tests** `tests/unit/_internal/test_logging.py` pin the three
  configure contracts: INFO default, `--verbose` enables DEBUG, and
  `PAPERWIKI_LOG_LEVEL=WARNING` silences INFO.

### Fixed

- Chatty internal modules (`paperwiki.plugins.filters.dedup`,
  `paperwiki._internal.arxiv_source`) are now disabled at INFO level by
  default; they only surface output when `--verbose` is passed or
  `PAPERWIKI_LOG_LEVEL=DEBUG` is set.

## [0.3.14] - 2026-04-27

### Added

- **`tests/integration/test_full_digest_auto_chain.py` end-to-end smoke test.**
  Single test that drives the full digest → auto-chain pipeline against a
  tmp vault using stubbed sources (Option B: in-process `StubSource`,
  no recipe YAML or network calls). Asserts every contract added in
  v0.3.6–v0.3.13: daily digest file on disk, `<!-- paper-wiki:overview-slot -->`
  marker, per-paper slot markers, Wiki source stubs, `wiki_ingest_plan`
  subprocess exits 0, JSON has `created_stubs` + `folded_citations`, concepts
  already seen fold instead of re-stub, idempotent `sources:` lists (no
  duplicates), no DEBUG/WARNING in subprocess stderr, and full test runtime
  < 15 s. Acts as a CI hard gate so future releases can't silently regress
  the pipeline.

## [0.3.13] - 2026-04-27

### Fixed

- **4-minute hang in digest auto-chain.** Previously, after the runner created
  stubs, the SKILL had to Read each pre-existing concept file and run `Edit` to
  fold the source citation in — when this hit Edit's "File must be read first"
  pre-condition and LLM retry loops, it could hang for minutes. The runner now
  folds citations atomically as part of `--auto-bootstrap`, eliminating the
  SKILL-side Edit dance.

### Added

- **`folded_citations: list[str]` field in `wiki_ingest_plan` JSON output.**
  Lists concept names whose `sources:` list was updated with this source's
  canonical_id (idempotent — no-op if already present).

### Changed

- **wiki-ingest SKILL Step 4 split into 4 (auto-bootstrap path) and 4b
  (manual path).** Auto-bootstrap path: just report runner's
  `folded_citations`, no LLM work. Manual path: existing
  prose-synthesis flow (unchanged). Step 5 already had the
  auto-bootstrap-skip clause from v0.3.11.

### Tests

- 7 new unit tests pin the citation-folding contract: append,
  idempotence, body preservation, frontmatter preservation,
  `last_synthesized` bump, empty-vault no-op, combined with
  `created_stubs`.
- 1 smoke test pins the SKILL contract that the auto-chain path no
  longer Edits files.

## [0.3.12] - 2026-04-27

### Fixed

- **Quiet runner DEBUG noise leaking to user transcript.** The
  `wiki_ingest_plan` runner emitted a `logger.debug(
  "wiki_ingest_plan.stub_created", ...)` per stub created. With loguru's
  default DEBUG level, this leaked into every digest auto-chain run as
  three lines per paper of `2026-... | DEBUG | __main__:_bootstrap_
  missing_concepts:217 - wiki_ingest_plan.stub_created`. The
  `created_stubs` field in the JSON output already conveys the same
  information; deleted the redundant log call.
- **Quiet `dedup.vault.missing` warnings on fresh-vault first-run.**
  (Plan Task 9.11 partial.) When a recipe references vault subdirs that
  don't exist yet (the dominant case during first-time setup), the
  dedup loader logged WARNING for each missing path — three scary lines
  before the real work even started. Downgraded to DEBUG; a real
  misconfiguration still surfaces as zero dedup entries which the
  digest SKILL Red Flags catch.

## [0.3.11] - 2026-04-27

### Fixed

- **wiki-ingest SKILL now actually invokes the runner with
  `--auto-bootstrap`** when called by digest auto-chain. v0.3.9 added
  the flag to the runner; v0.3.10 made digest pass `--auto-bootstrap`
  in the SKILL prose; but the wiki-ingest SKILL.md Step 2 still showed
  the runner CLI shape WITHOUT the flag, so the LLM dropped the flag
  when invoking the runner — falling back to `<<PYEOF python -c ...`
  inline blocks to manually create stubs (the very black magic v0.3.9
  was supposed to replace). Step 2 now explicitly says "append
  `--auto-bootstrap` to the CLI when caller passed the flag", and Step 5
  explicitly says "if you used `--auto-bootstrap` in Step 2, SKIP this
  step entirely; do NOT write inline Python".
- **CI `ruff format --check`**: `_stub_constants.py` and
  `test_wiki_ingest_plan_auto_bootstrap.py` (added in v0.3.9) failed
  format check on the v0.3.10 release. Reformatted both files.

### Tests

- `test_wiki_ingest_skill_appends_auto_bootstrap_flag_to_runner_cli`
  pins Step 2's flag-append pattern.
- `test_wiki_ingest_skill_forbids_inline_python_fallback` pins Step 5's
  no-inline-Python contract so the v0.3.7 black-magic regression can't
  resurface.

## [0.3.10] - 2026-04-27

### Fixed

- **digest SKILL no longer asks "shall I chain wiki-ingest?"** when
  `auto_ingest_top: N` is set. The recipe field IS the user's
  pre-approval — re-prompting every digest defeats the configuration.
  v0.3.10 makes the contract imperative ("**immediately and without
  asking the user**") and adds a Common Rationalizations row killing
  the "I'll ask first to be safe" instinct.

### Tests

- New `test_digest_skill_forbids_asking_before_auto_chain` pins the
  contract.

## [0.3.9] - 2026-04-27

### Fixed

- **`wiki-ingest` runner now actually accepts `--auto-bootstrap`** as advertised by the
  SKILL since v0.3.7. Previously the runner ignored the flag entirely; the SKILL fell back
  to writing inline Python (`asyncio.run(MarkdownWikiBackend.upsert_concept(...))` blocks)
  to manually create stubs, which was fragile and bypassed runner architecture per SPEC §6.
  Auto-chained digest invocations now go through the proper runner path.

### Added

- **`paperwiki.runners._stub_constants` module** exposes `AUTO_CREATED_SENTINEL_BODY` and
  `AUTO_CREATED_FRONTMATTER_FIELDS` as a single source of truth — wiki-ingest writes them,
  future wiki-lint changes (Task 9.12) will detect them, no string-literal drift possible.

### Changed

- **`skills/wiki-ingest/SKILL.md`** Process simplified: the runner now handles
  `--auto-bootstrap` directly. No inline-Python fallback fragments required.
- **`skills/digest/SKILL.md`** Step 8 (auto-chain wiki-ingest): the chained command
  invokes the runner directly with `--auto-bootstrap`; no `<<PY ... PY>>` blocks.

### Tests

- `test_wiki_ingest_plan_auto_bootstrap_creates_stubs_for_missing_concepts` — with empty
  `Wiki/concepts/`, invoking the runner with `auto_bootstrap=True` for a source that
  suggests N concepts creates N stub files, each with `auto_created: true` frontmatter and
  the sentinel body.
- `test_wiki_ingest_plan_auto_bootstrap_then_updates_concepts` — after stubs are created,
  the update loop folds the source's `canonical_id` into each stub's `sources:` list;
  output plan has both `created_stubs` and `affected_concepts` populated.
- `test_wiki_ingest_plan_auto_bootstrap_skips_existing_concepts` — pre-existing concept
  (without `auto_created`) is NOT given `auto_created: true`; user content preserved.
- `test_wiki_ingest_plan_without_auto_bootstrap_preserves_existing_safeguard` — without
  the flag, fresh vault returns `affected_concepts: []`, `suggested_concepts: [...]`, no
  files created.
- `test_stub_constants_module_exposes_sentinel_and_frontmatter` — asserts the constants
  module exists and exposes both `AUTO_CREATED_SENTINEL_BODY` and
  `AUTO_CREATED_FRONTMATTER_FIELDS`.
- `test_wiki_ingest_runner_accepts_auto_bootstrap_flag` — `python -m
  paperwiki.runners.wiki_ingest_plan --help` shows `--auto-bootstrap` in help text.

## [0.3.8] - 2026-04-27

### Fixed

- **`.claude-plugin/plugin.json` was missing the `"skills": "./skills/"` declaration**
  that Claude Code uses to locate SKILL files. Without it, `/plugin install` could
  leave the metadata in an inconsistent state (cache populated but slash commands
  unresolvable), leading to the "already installed globally" + "Unknown command" failure
  mode reported repeatedly during 0.3.5–0.3.7 upgrades. With the declaration in place,
  the standard `/plugin uninstall paper-wiki@paper-wiki` +
  `/plugin install paper-wiki@paper-wiki` flow works without any manual cache cleanup.

### Documentation

- **README's upgrade section rewritten** to describe the standard flow:
  `/plugin uninstall paper-wiki@paper-wiki` + `/plugin install paper-wiki@paper-wiki` +
  fully exit + start a fresh `claude` session (not `claude -c`). Removed the manual
  `rm -rf` cache instructions that were workarounds for the bug above.
- Troubleshooting row for "already installed but Unknown command" updated: the cure is
  now the standard uninstall + reinstall flow; manual JSON editing is mentioned only as
  a last-resort fallback.

### Tests

- `test_plugin_manifest_declares_skills_directory` — pins the `"skills"` declaration
  so future refactors cannot accidentally drop it.
- `test_readme_documents_standard_upgrade_flow` — asserts README contains the literal
  `/plugin uninstall` and `/plugin install` commands and the `claude -c` warning.
- `test_readme_does_not_recommend_manual_cache_nuke` — asserts README does not tell
  users to `rm -rf` the plugin cache as part of normal upgrades.

### Note

The previous v0.3.5–0.3.7 workarounds (`rm -rf ~/.claude/plugins/cache/paper-wiki/`
and manual `installed_plugins.json` edits) were diagnostic workarounds for the missing
`"skills"` declaration — not best practice. Existing users upgrading to 0.3.8 should
NOT need to nuke; the standard uninstall + reinstall flow above is sufficient.

### Deferred to v0.3.9

- Task 9.4 (per-paper Detailed report synthesis) and Task 9.5 (auto image extraction)
  were originally planned for v0.3.8 but are pushed to v0.3.9 so this release stays
  small and focused on the upgrade-UX fix.

## [0.3.7] - 2026-04-27

### Added

- **digest SKILL now synthesizes the "Today's Overview" callout** instead of
  leaving an empty slot. After the deterministic runner writes the digest
  skeleton, the SKILL re-reads the file and replaces
  `<!-- paper-wiki:overview-slot -->` with 60–200 words of cross-paper prose
  covering top trends, quality / score distribution, and suggested reading
  order — every claim cited with `#N` paper-index markers. New SKILL Common
  Rationalizations + Red Flags pin the contract: don't claim a trend from one
  paper; don't skip `#N` cites; don't invent topics not in the digest.
- **`--auto-bootstrap` mode for `wiki-ingest` SKILL.** When invoked with this
  flag (only by digest auto-chain — manual `/paper-wiki:wiki-ingest <id>` keeps
  the existing confirmation prompt), missing concept articles are auto-stubbed
  with `auto_created: true` frontmatter + sentinel body before the normal update
  loop runs. Net effect: fresh-vault digests no longer dead-end on paper #1 with
  `affected_concepts: []` — auto-chain creates stubs for top-N papers and folds
  source citations in.
- **`wiki-lint` SKILL surfaces concept articles with `auto_created: true`** in a
  dedicated "Needs review (auto-created stubs)" section, separate from
  broken-link / orphan reports. Users can prune en masse via the sentinel body
  string or remove with `rm <vault>/Wiki/concepts/<name>.md`.
- **Tests**: `test_wiki_ingest_skill_describes_auto_bootstrap_mode`,
  `test_digest_skill_passes_auto_bootstrap_to_wiki_ingest`,
  `test_wiki_lint_skill_surfaces_auto_created_stubs`,
  `test_digest_skill_describes_overview_synthesis` — 4 new smoke tests pin the
  contracts.

## [0.3.6] - 2026-04-27

### Fixed

- **99 stale `/paperwiki:` slash-command references** replaced with the correct
  `/paper-wiki:` namespace (with hyphen) across `src/`, `skills/`, `recipes/`,
  `docs/`, `SPEC.md`, and `.claude/commands/` — 26 files in total. Commands like
  `/paperwiki:setup` would have failed at runtime because the Claude Code plugin
  is registered as `paper-wiki`, not `paperwiki`. CHANGELOG entries (this file)
  are intentionally exempt — they describe historical reality.

### Heads-up

- **Source stubs in existing user vaults** (`<vault>/Wiki/sources/<id>.md`)
  generated by paper-wiki ≤ 0.3.5 may contain stale `/paperwiki:` strings baked
  into the body. Run `/paper-wiki:migrate-sources` to upgrade them, or accept
  they will remain until you next analyze each paper.

### Changed

- **Obsidian reporter no longer emits prose placeholder text** in the
  "Today's Overview" callout or each paper's "Detailed report" section. Both are
  now empty machine-targetable HTML-comment markers:
  `<!-- paper-wiki:overview-slot -->` and
  `<!-- paper-wiki:per-paper-slot:{canonical_id} -->`. Subsequent digest SKILL
  synthesis passes (planned for v0.3.7 and v0.3.8) will replace these markers
  with synthesized content. Net effect: digests no longer mislead users with
  "Run SKILL after this runner" text — they contain empty slots until SKILL
  synthesis lands.

### Added

- **Regression test `test_no_stale_paperwiki_namespace`** scans `src/`,
  `skills/`, `recipes/`, `docs/`, `SPEC.md`, and `.claude/commands/` for the bad
  `/paperwiki:` pattern; fails with a `file:line` breakdown if any reappear.
  `CHANGELOG.md` is exempt.
- **Three new obsidian reporter contract tests**:
  `test_obsidian_reporter_emits_overview_slot_marker`,
  `test_obsidian_reporter_emits_per_paper_slot_markers`, and
  `test_obsidian_reporter_does_not_emit_legacy_placeholder_prose` — pin the new
  HTML-comment slot skeleton so future changes cannot silently regress to prose
  stubs.

## [0.3.5] - 2026-04-26

### Documentation

- **README rewritten for v0.3.x reality.** Slash-command namespace corrected
  to `/paper-wiki:` throughout (was `/paperwiki:` in 13 places). First-run
  walkthrough now leads with the interactive setup wizard (rather than the
  v0.2-era manual bash flow). Added paperclip MCP user-scope + OAuth setup,
  advanced `PAPERWIKI_CONFIG_DIR` note promoted to Install section, rich digest
  output description (`### Detailed report`, inline figures, Obsidian callouts),
  `auto_ingest_top` chaining note in SKILLs table, and operational
  troubleshooting table for plugin cache mismatches, MCP hot-reload, and
  pre-v0.3.4 wizard schema bugs.

## [0.3.4] - 2026-04-26

### Fixed

- **setup SKILL was violating the AskUserQuestion schema in multiple ways** — too
  many options (auto-split into "Topics (1)/(2)" tabs), missing `header` field
  (caused garbage chip labels like "Custom kw"), manually added redundant "Other"
  / "Cancel" options (Claude Code injects these automatically), and faked
  multi-select via re-prompting instead of using `multiSelect: true`. Each branch
  now provides a fully-specified AskUserQuestion call with `header` (≤ 12 chars),
  per-option `description`, and proper `multiSelect` flag where applicable.

### Changed

- **Topic selection collapsed from 10 fine-grained options to 4 themed buckets**
  (Vision & Multimodal / Biomedical & Pathology / Agents & Reasoning / NLP &
  Language) with `multiSelect: true`. Custom keywords now go through Claude
  Code's auto-provided "Other" input rather than a separate follow-up question.
  Each bucket maps to a curated keyword list and arXiv category set in the
  resulting recipe.

## [0.3.3] - 2026-04-26

### Changed

- **setup SKILL now uses Claude Code's AskUserQuestion tool for every choice** —
  provides a structured selection UI instead of plain prose options. Eight
  explicit call points cover: already-configured detection (4 options), edit-one-piece
  drill-down (5 options), Q1 vault path (auto-detected candidates + Other),
  Q2 topics multi-select (10 options, re-prompted until Done), Q3 S2 API key
  (3 options), Q4 auto-ingest depth (4 options), Q5 paperclip (3 options),
  and final save confirmation (3 options). Aligns with the OMC convention.

## [0.3.2] — 2026-04-26

### Changed (BREAKING for personal config)

- **User config dir renamed** from `~/.config/paperwiki/` to
  `~/.config/paper-wiki/` for XDG and plugin-name consistency (the
  plugin is named `paper-wiki`, so the config dir now matches).
  Migrate with:
  ```bash
  mv ~/.config/paperwiki ~/.config/paper-wiki
  ```
  This is a hard cut — no migration shim. paper-wiki is pre-1.0 with
  effectively one user (the dev).

### Added

- **`PAPERWIKI_CONFIG_DIR` environment variable** — override the config
  directory location; useful for dotfiles workflows or non-standard
  setups (e.g. `~/dotfiles/paper-wiki/`). Resolution priority:
  1. `$PAPERWIKI_CONFIG_DIR` — if set, use as-is
  2. `$XDG_CONFIG_HOME/paper-wiki` — if `XDG_CONFIG_HOME` is set
  3. `~/.config/paper-wiki` — default fallback

## [0.3.1] — 2026-04-25

### Fixed
- **`PaperclipSource` rewritten against the real paperclip 0.2.x CLI.**
  v0.3.0 shipped a plugin built against an assumed `--json` flag and
  imaginary `--source biorxiv,pmc` arguments — the real CLI has no JSON
  output and uses `-T TYPE`, `--journal NAME`, `--since Nd` instead.
  The plugin now follows paperclip's actual two-step flow:
  1. `paperclip search QUERY -n N [--since Nd] [--journal NAME] [-T TYPE]`
     captures a session id of the form `[s_<hex>]` from stdout.
  2. `paperclip results <session_id> --save <tmpfile.csv>` exports the
     structured CSV (`title,authors,id,source,date,url,abstract`).
  Recipe config keys for `PaperclipSource` change from `sources: [...]`
  to `since_days: int`, `journal: str`, `document_type: str`.
- **Empty paperclip abstracts no longer drop the paper.** Real CSV
  exports frequently ship empty `abstract` cells; the plugin now
  substitutes `_(no abstract available from paperclip)_` so dedup,
  scoring, and the wiki backend keep the entry while making the gap
  visible to the user.
- `recipes/biomedical-weekly.yaml` config keys updated to match the
  real CLI surface area (`since_days: 7` replacing the imaginary
  `sources: [biorxiv, medrxiv, pmc]` list).

### Verified end-to-end
- Live smoke test against real paperclip 0.2.0 with the query
  `"CRISPR base editing"`: 3/3 hits parsed cleanly; one had a real
  abstract, two used the placeholder.
- `diagnostics.mcp_servers` correctly enumerates `claude mcp list`
  output on a real machine.

## [0.3.0] — 2026-04-25

### Phase 7 — Paperclip integration (optional)

#### Added
- **`paperwiki.runners.diagnostics`** gains an `mcp_servers: list[str]`
  field. The runner shells out to `claude mcp list` (resolved via
  `shutil.which`) and parses the registered server names. Failures
  (missing CLI, non-zero exit, race conditions) fold into `issues`
  rather than crashing.
- **`PaperclipSource`** plugin (`paperwiki.plugins.sources.paperclip`)
  wraps the third-party paperclip CLI as a paper-wiki `Source`. Maps
  hits' canonical ids to `arxiv:<id>` when the paper exposes one
  (so dedup converges with `ArxivSource`), `paperclip:bio_<id>` for
  bioRxiv/medRxiv, and `paperclip:pmc_<id>` for PubMed Central. Tests
  mock at `asyncio.create_subprocess_exec` and never shell out for
  real.
- Recipes can now name `paperclip` like any other source plugin.
- New bundled recipe **`recipes/biomedical-weekly.yaml`** demonstrates
  paperclip + dedup + `wiki_backend: true` for a weekly biomedical
  preprint pull.
- New SKILL **`paperwiki:bio-search`** (six-section anatomy) +
  `.claude/commands/bio-search.md`. Walks Claude through paperclip
  MCP-driven biomedical search with optional handoff to
  `/paperwiki:wiki-ingest`. Fails gracefully when the MCP server is
  not registered.
- New documentation **`docs/paperclip-setup.md`** covers CLI install,
  authentication, MCP registration, removal, and troubleshooting.
- README Quick Start gains an "Optional: biomedical literature"
  subsection.

#### Changed
- `setup` SKILL surfaces the diagnostics `mcp_servers` field. When
  `paperclip` is missing it offers the registration command verbatim
  but **never auto-runs** `claude mcp add` — auth is sensitive and
  paperclip may be on a metered tier. Two new Red Flags pin this.

## [0.2.0] — 2026-04-25

### Phase 6.3 — Wiki / dedup integration

#### Added
- `MarkdownVaultKeyLoader` now recognizes both the modern
  `canonical_id` frontmatter field and the list-typed `sources:` field
  used by concept articles. Concepts contribute their listed source
  ids to the dedup union automatically, so a paper that has been
  folded into a concept article never re-surfaces in the digest.
- `wiki_lint` gains a sixth code, **`DANGLING_SOURCE`** (severity
  `info`), raised when a `Wiki/sources/` file is not referenced by
  any concept's `sources` list. The lint message points the user at
  `/paperwiki:wiki-ingest` to fold the source in.
- `ObsidianReporter` accepts a `wiki_backend: bool` flag (default
  `False`). When `True`, each top-K recommendation is also persisted
  as a per-paper source file under `Wiki/sources/` via
  `MarkdownWikiBackend.upsert_paper`. The daily digest is unchanged.
- `recipes/daily-arxiv.yaml` documents the new opt-in with a
  commented `wiki_backend: true` line so users can discover the
  feature without it triggering on first run.
- New integration test `tests/integration/test_digest_wiki_handoff.py`
  pins down the digest ➜ wiki backend ➜ wiki_lint contract end-to-end.

#### Changed
- `analyze` SKILL writes per-paper notes under `{vault}/Sources/`
  (the `SOURCES_SUBDIR` default) rather than the legacy
  `{paper_subdir}` placeholder. After writing, it now hands off to
  `/paperwiki:wiki-ingest` so the source folds into concept articles
  immediately. Frontmatter requirements bump to `canonical_id`,
  `title`, `tags`, `status`, and `confidence`.

### Phase 6.2 — Wiki backend implementation

#### Added
- `MarkdownWikiBackend` (`paperwiki.plugins.backends.markdown_wiki`)
  persists papers as `Wiki/sources/<id>.md` and synthesized topic
  articles as `Wiki/concepts/<name>.md` with frontmatter that mirrors
  the Karpathy / kytmanov LLM-Wiki reference (`status`, `confidence`,
  `sources`, `related_concepts`, `last_synthesized`).
- Four wiki runners shipped under `paperwiki.runners`:
  - `wiki_query` — keyword search across concepts + sources, ranked
    by TF-IDF on title and tags. Returns ≤ 10 hits as JSON.
  - `wiki_lint` — health check covering `ORPHAN_CONCEPT`, `STALE`,
    `OVERSIZED`, `BROKEN_LINK`, and `STATUS_MISMATCH` (later joined
    by `DANGLING_SOURCE`).
  - `wiki_compile` — deterministic rebuild of `Wiki/index.md`.
  - `wiki_ingest_plan` — given a new source id, returns the affected
    concepts and suggested new concepts a SKILL should synthesize.
- Four matching SKILLs (`wiki-query`, `wiki-lint`, `wiki-compile`,
  `wiki-ingest`) plus slash commands so the runners are first-class
  user surfaces.
- End-to-end integration test `tests/integration/test_wiki_flow.py`
  walks the full backend ➜ runners path.
- New `docs/wiki.md` documenting the four operations, the layout
  contract, and the frontmatter convention.

### Phase 6.1 — Vault layout cleanup

#### Changed (BREAKING)
- `ObsidianReporter` default `daily_subdir` changed from `"10_Daily"`
  to `"Daily"`. The numeric prefix was a Johnny.Decimal / PARA
  convention inherited from `evil-read-arxiv`; paper-wiki should not
  impose a personal-knowledge-management style on users who do not
  follow one. Defaults are now friendly; users who do use PARA can
  override `daily_subdir` per-recipe.
- Bundled recipes (`recipes/daily-arxiv.yaml`,
  `recipes/weekly-deep-dive.yaml`) updated to demonstrate the friendly
  defaults; an inline comment shows how Johnny.Decimal users override.

#### Added
- `paperwiki.config.layout` module with three default subdir constants
  (`DAILY_SUBDIR`, `SOURCES_SUBDIR`, `WIKI_SUBDIR`) used by reporters
  and the upcoming wiki backend.
- `Wiki/.drafts/` added to `.gitignore` for the upcoming wiki feature.

### Migration from earlier installs

If you have an existing setup that relied on the old default
`10_Daily` subdir, either:

- **Keep the numeric prefix**: pin `daily_subdir: 10_Daily` in your
  recipe's `obsidian` reporter config, or
- **Migrate to the friendly default**: `mv ~/Vault/10_Daily
  ~/Vault/Daily` and let the new default pick up.

The dedup filter scans recursively and reads frontmatter, so renaming
the directory does not break dedup.

## [0.1.0] — 2026-04-25

### Added
- Initial release. Phases 0 through 5 of the foundation plan:
  plugin scaffolding, core domain models and protocols, async pipeline
  orchestrator, source plugins (arXiv, Semantic Scholar), filter
  plugins (recency, relevance, dedup), composite scorer, reporters
  (Markdown, Obsidian-flavored), recipe system, runners (digest,
  diagnostics), and three SKILLs (setup, digest, analyze).
- 281 tests, 93% coverage.
