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

# ---------------------------------------------------------------------------
# Install ~/.local/bin/paperwiki shim (version-agnostic, always picks latest).
# Runs every SessionStart — not gated on the venv stamp — so users get the
# shim even after the venv was already installed in a prior session.
# Only rewrites if the file is missing or does not carry our tag line.
# ---------------------------------------------------------------------------
SHIM_DIR="$HOME/.local/bin"
SHIM_PATH="$SHIM_DIR/paperwiki"
EXPECTED_TAG="# paperwiki — shim that always invokes the latest installed venv binary."

mkdir -p "$SHIM_DIR"
if ! [ -f "$SHIM_PATH" ] || ! grep -qF "$EXPECTED_TAG" "$SHIM_PATH" 2>/dev/null; then
  cat > "$SHIM_PATH" <<'SHIM_EOF'
#!/usr/bin/env bash
# paperwiki — shim that always invokes the latest installed venv binary.
set -euo pipefail
CACHE_ROOT="$HOME/.claude/plugins/cache/paper-wiki/paper-wiki"
LATEST=$(ls -1 "$CACHE_ROOT" 2>/dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1)
if [ -z "$LATEST" ]; then
  echo "paperwiki: no installed plugin found at $CACHE_ROOT" >&2
  echo "Install via /plugin install paper-wiki@paper-wiki in Claude Code first." >&2
  exit 1
fi
exec "$CACHE_ROOT/$LATEST/.venv/bin/paperwiki" "$@"
SHIM_EOF
  chmod +x "$SHIM_PATH"
fi

# Warn once if ~/.local/bin is not on PATH (non-blocking).
case ":$PATH:" in
  *":$SHIM_DIR:"*) ;;
  *)
    if ! [ -f "$SHIM_DIR/.paperwiki-path-warned" ]; then
      echo "paperwiki: shim installed at $SHIM_PATH but $SHIM_DIR is not on your PATH." >&2
      echo "  Add this to your shell rc: export PATH=\"\$HOME/.local/bin:\$PATH\"" >&2
      touch "$SHIM_DIR/.paperwiki-path-warned"
    fi
    ;;
esac

# ---------------------------------------------------------------------------
# Venv bootstrap — idempotent, skipped once the .installed stamp exists.
# ---------------------------------------------------------------------------
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
