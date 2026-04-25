"""Pytest configuration shared across the paper-wiki test suite."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure ``src/`` is importable when tests run from the repo root before the
# package is installed editable.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
