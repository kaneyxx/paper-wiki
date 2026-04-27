---
description: Upgrade existing Wiki/sources/<id>.md files to the current section-organized format
---

Invoke the paper-wiki migrate-sources SKILL.

Always dry-run first to show the user the migration plan before
rewriting:

```
${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.migrate_sources <vault> --dry-run
```

If the dry-run reports `migrated > 0`, surface the list of files
to be migrated (the JSON `migrated_paths` field), confirm with the
user, then re-run without `--dry-run`. The runner preserves user
content in `## Notes`, `## Key Takeaways`, and `## Figures` —
trust it; do not skip files yourself.

After the migration, suggest `/paper-wiki:wiki-lint` and
`/paper-wiki:wiki-compile` to verify the upgraded files pass health
checks and refresh the wiki index.
