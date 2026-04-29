---
name: bad-skill
description: Synthetic fixture for the v0.3.36 SKILL bash/module-path lint test. DO NOT register as a real skill. Each section embeds one forbidden pattern from D-9.36.5 so the lint catches the contract regression.
---

# bad-skill (lint fixture)

This file is consumed only by `tests/unit/test_skill_bash_snippets_lint.py`
to verify the lint detects each forbidden pattern. It deliberately
violates F1, F2, F3, F4, and F5.

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

### F5 — wrong RecipeSchema import (no `.recipe.` segment)

```python
from paperwiki.config import RecipeSchema
```
