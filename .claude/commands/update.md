---
description: Refresh the paper-wiki marketplace clone and clean stale cache + JSON entries so the next /plugin install does a real upgrade. Replaces the manual rm-rf + JSON-edit ritual.
---

Invoke the paper-wiki update SKILL.

Run the console-script and forward output verbatim:

```
paperwiki update
```

Fallback if `paperwiki` is not on PATH:

```
${CLAUDE_PLUGIN_ROOT}/.venv/bin/paperwiki update
```

If the output is `paper-wiki is already at <version>`, you're done.
Otherwise the CLI prints a `Next:` list with three steps — emphasise
to the user that steps 1–2 require a brand-new terminal/session, not
just `claude -c`. The plugin cache is loaded at session start, so
without a fresh process the new version's SKILLs and runners are not
picked up.

Do NOT manually edit `installed_plugins.json` or `settings.json` —
the CLI handles all three files atomically.
