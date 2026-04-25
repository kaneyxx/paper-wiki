#!/usr/bin/env bash
# Idempotent virtualenv bootstrap for paper-wiki.
#
# Runs on SessionStart. On first invocation it creates ${CLAUDE_PLUGIN_ROOT}/.venv
# and installs the plugin's Python dependencies via `uv` (preferred) or stdlib
# `venv` + `pip` as a fallback. Subsequent invocations no-op once the
# `.installed` stamp exists.
set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT must be set by Claude Code}"
VENV="${PLUGIN_ROOT}/.venv"
STAMP="${VENV}/.installed"

if [ -f "${STAMP}" ]; then
  exit 0
fi

cd "${PLUGIN_ROOT}"

if command -v uv >/dev/null 2>&1; then
  uv venv "${VENV}"
  uv pip install --python "${VENV}/bin/python" -e .
else
  python3 -m venv "${VENV}"
  "${VENV}/bin/pip" install --upgrade pip
  "${VENV}/bin/pip" install -e .
fi

touch "${STAMP}"
