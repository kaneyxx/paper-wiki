"""SKILL-invoked runner entry points.

Each module in this package is callable via
``python -m paperwiki.runners.<name>``. SKILLs invoke runners; users do
not. The contract is loose by design: runners may evolve freely as long
as the matching SKILL.md is updated in lockstep.
"""

from __future__ import annotations
