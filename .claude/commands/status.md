---
description: Show paper-wiki install state — cached version, marketplace clone version, and enabledPlugins state across both settings files
---

Invoke the paper-wiki status SKILL.

Run the console-script and forward the output verbatim to the user:

```
paperwiki status
```

Fallback if `paperwiki` is not on PATH:

```
${CLAUDE_PLUGIN_ROOT}/.venv/bin/paperwiki status
```

The CLI prints three lines (cache version / marketplace ver /
enabledPlugins). Do NOT re-format. If the user asks for interpretation
(e.g. "what does it mean?"), suggest `/paper-wiki:update` when the
cache and marketplace versions differ, or `/plugin enable
paper-wiki@paper-wiki` when both `enabledPlugins` flags are `no`.
