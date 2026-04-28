---
description: Surgically update a personal recipe to the latest template keywords (removes stale broad terms like 'foundation model' from biomedical-pathology without re-running the full setup wizard)
---

Invoke the paper-wiki migrate-recipe SKILL.

Always dry-run first to show the user the proposed keyword changes:

```
${CLAUDE_PLUGIN_ROOT}/.venv/bin/python -m paperwiki.runners.migrate_recipe \
  ~/.config/paper-wiki/recipes/daily.yaml --dry-run
```

If `applied_changes` is non-empty, surface the diff and ask the user
to confirm (via AskUserQuestion) before applying. Then re-run without
`--dry-run`. The runner preserves all user-added keywords and creates
a timestamped backup automatically.

After the migration, suggest `/paper-wiki:digest` to verify the updated
recipe no longer routes unrelated papers into the migrated bucket.
