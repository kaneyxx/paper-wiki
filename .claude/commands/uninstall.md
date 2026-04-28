---
description: Print the safe paper-wiki uninstall path. Claude cannot safely tear itself out from inside its own session, so the redirect points the user at `paperwiki uninstall` from a fresh terminal.
---

Invoke the paper-wiki uninstall SKILL.

Tell the user:

```
paper-wiki cannot safely uninstall itself from inside Claude Code —
the active session would lose its SKILLs and runners mid-execution.

Run this from a fresh terminal (NOT inside `claude`):

    paperwiki uninstall

The CLI removes the plugin cache, prunes `installed_plugins.json`,
and clears `enabledPlugins` in both `settings.json` and
`settings.local.json`. Reinstall any time with:

    claude
    /plugin install paper-wiki@paper-wiki
```

Do NOT actually invoke `paperwiki uninstall` from inside Claude — the
SKILL only prints the redirect by design (D-9.29.2).
