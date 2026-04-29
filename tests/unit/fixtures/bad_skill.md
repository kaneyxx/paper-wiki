---
name: bad-skill
description: Synthetic fixture for the SKILL bash/module-path lint test (D-9.36.5, slimmed in v0.3.37 D-9.37.3). DO NOT register as a real skill. Each section embeds one forbidden pattern so the lint catches the contract regression.
---

# bad-skill (lint fixture)

This file is consumed only by `tests/unit/test_skill_bash_snippets_lint.py`
to verify the lint detects each forbidden pattern. It deliberately
violates F1, F2, F3, F4, and F6. (F5 was retired in v0.3.37 — see the
test module docstring for the rationale.)

## Process

### F1 — wrong module name (plural `recipes`)

```python
from paperwiki.config.recipes import STALE_MARKERS
```

### F2 — wrong runner name (bare `wiki_ingest`)

```python
from paperwiki.runners.wiki_ingest import main
```

### F3 — bare `CLAUDE_PLUGIN_ROOT=$(...)` without `export`

```bash
if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    CLAUDE_PLUGIN_ROOT=$(ls -d /tmp/cache/*/)
fi
echo "$CLAUDE_PLUGIN_ROOT"
```

### F4 — `bash -n` parse failure

```bash
if [ -z "${X:-}"
    echo "missing then keyword"
fi
```

### F6 — helper-sourcing failure (v0.3.38 D-9.38.6 — subprocess only)

This block sources a non-existent helper without the source-or-die
fallback per D-9.38.4. The static lint doesn't catch it (the bash
parses fine), but the subprocess execution mode must — exit non-zero
when the helper is missing.

```bash
source /nonexistent/helper.sh
paperwiki_bootstrap
```
