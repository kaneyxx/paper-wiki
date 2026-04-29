"""Shared pytest fixtures for ``tests/unit/``.

Currently exposes a session-scoped ``sandbox_home`` fixture that
materializes the v0.3.38 SKILL-bash-lint sandbox tree (D-9.38.6).
Other unit-test directories with their own ``conftest.py``
(e.g. ``tests/unit/runners/``) keep their per-directory fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tests/unit/skill_lint_sandbox.py is a sibling module of this conftest;
# add the parent dir to sys.path so the import resolves without
# requiring an __init__.py turning tests/unit into a package.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from skill_lint_sandbox import build_sandbox  # noqa: E402 — sys.path mutation above


@pytest.fixture(scope="session")
def sandbox_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped sandbox HOME for the SKILL bash subprocess lint.

    Built once per pytest invocation for speed. Tests must NOT mutate
    the tree — if a test needs custom state, it should `shutil.copytree`
    into a per-test ``tmp_path`` first.
    """
    tmp_path = tmp_path_factory.mktemp("skill_lint_sandbox")
    return build_sandbox(tmp_path)
