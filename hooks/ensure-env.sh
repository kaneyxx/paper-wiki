#!/usr/bin/env bash
# Idempotent virtualenv bootstrap for paper-wiki (v0.3.29+).
#
# Manages a SHARED venv at ${PAPERWIKI_VENV_DIR:-${PAPERWIKI_HOME:-${PAPERWIKI_CONFIG_DIR:-$HOME/.config/paper-wiki}}/venv}.
# Migrates legacy per-version venvs from <= v0.3.28 by copying once to
# the shared path, then symlinking ${CLAUDE_PLUGIN_ROOT}/.venv to the
# shared path so existing SKILL invocations keep working unchanged
# (Task 9.31 / D-9.31.1 — D-9.31.4).
#
# Runs on SessionStart. Subsequent invocations no-op once the
# ${VENV}/.installed stamp matches this cache version's __version__.
set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT must be set by Claude Code}"

# ---------------------------------------------------------------------------
# Resolve paths via the same precedence chain as
# paperwiki._internal.paths (PAPERWIKI_VENV_DIR > PAPERWIKI_HOME >
# PAPERWIKI_CONFIG_DIR > default).
# ---------------------------------------------------------------------------
PAPERWIKI_HOME_RESOLVED="${PAPERWIKI_HOME:-${PAPERWIKI_CONFIG_DIR:-$HOME/.config/paper-wiki}}"
VENV_DIR="${PAPERWIKI_VENV_DIR:-$PAPERWIKI_HOME_RESOLVED/venv}"
SYMLINK="${PLUGIN_ROOT}/.venv"
STAMP="${VENV_DIR}/.installed"

# Read this cache version from ${PLUGIN_ROOT}/src/paperwiki/__init__.py.
# Falls back to "unknown" so the strict equality below never accidentally
# matches an empty stamp file.
PLUGIN_VERSION=$(grep -E '^__version__' "${PLUGIN_ROOT}/src/paperwiki/__init__.py" 2>/dev/null \
  | sed -n 's/.*"\([^"]*\)".*/\1/p' | head -1)
PLUGIN_VERSION="${PLUGIN_VERSION:-unknown}"

# ---------------------------------------------------------------------------
# Install ~/.local/bin/paperwiki shim (version-agnostic, self-bootstrap).
# Runs every SessionStart — not gated on the venv stamp — so users get
# the shim even after the venv was already installed in a prior session.
# Only rewrites if the file is missing or does not carry our tag line
# (idempotent grep guard).
# ---------------------------------------------------------------------------
SHIM_DIR="$HOME/.local/bin"
SHIM_PATH="$SHIM_DIR/paperwiki"
EXPECTED_TAG="# paperwiki shim — v0.3.29 (shared venv + self-bootstrap)."

mkdir -p "$SHIM_DIR"
if ! [ -f "$SHIM_PATH" ] || ! grep -qF "$EXPECTED_TAG" "$SHIM_PATH" 2>/dev/null; then
  cat > "$SHIM_PATH" <<'SHIM_EOF'
#!/usr/bin/env bash
# paperwiki shim — v0.3.29 (shared venv + self-bootstrap).
set -euo pipefail
CACHE_ROOT="$HOME/.claude/plugins/cache/paper-wiki/paper-wiki"
PAPERWIKI_HOME_RESOLVED="${PAPERWIKI_HOME:-${PAPERWIKI_CONFIG_DIR:-$HOME/.config/paper-wiki}}"
VENV_DIR="${PAPERWIKI_VENV_DIR:-$PAPERWIKI_HOME_RESOLVED/venv}"
LATEST=$(ls -1 "$CACHE_ROOT" 2>/dev/null \
  | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1)
if [ -z "$LATEST" ]; then
  echo "paperwiki: no installed plugin found at $CACHE_ROOT" >&2
  echo "Install via /plugin install paper-wiki@paper-wiki." >&2
  exit 1
fi
if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "paperwiki: shared venv missing at $VENV_DIR; bootstrapping..." >&2
  CLAUDE_PLUGIN_ROOT="$CACHE_ROOT/$LATEST" \
    bash "$CACHE_ROOT/$LATEST/hooks/ensure-env.sh" >&2
fi
# v0.3.31-A: PYTHONPATH=<latest>/src guarantees `paperwiki` module
# resolves even when the venv's editable-install .pth points at a
# stale path (e.g. after `paperwiki update` rename of the cache dir).
PYTHONPATH="$CACHE_ROOT/$LATEST/src${PYTHONPATH:+:$PYTHONPATH}" \
  exec "$VENV_DIR/bin/paperwiki" "$@"
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
# Migration (Task 9.31): if ${PLUGIN_ROOT}/.venv exists as a real
# directory (legacy per-version venv from <= v0.3.28) and the shared
# venv doesn't yet exist, COPY the legacy venv to the shared path
# (preserving already-synced deps), then replace the legacy path with
# the symlink. Saves the user from re-running uv sync on first
# v0.3.29 upgrade.
#
# Runs BEFORE the idempotent-skip check so subsequent runs see the
# new symlink-based layout.
# ---------------------------------------------------------------------------
if [ -d "$SYMLINK" ] && [ ! -L "$SYMLINK" ]; then
  if [ ! -d "$VENV_DIR" ]; then
    echo "paperwiki: migrating legacy per-version venv to shared path $VENV_DIR..." >&2
    mkdir -p "$(dirname "$VENV_DIR")"
    cp -R "$SYMLINK" "$VENV_DIR"
  fi
  rm -rf "$SYMLINK"
  ln -sfn "$VENV_DIR" "$SYMLINK"
fi

# ---------------------------------------------------------------------------
# Idempotent skip: stamp matches THIS plugin version AND symlink is in
# place. No re-install needed. Runs AFTER migration so that a clean
# v0.3.28 -> v0.3.29 upgrade with a matching stamp inside the
# now-migrated venv exits cleanly without retrying the bootstrap.
# ---------------------------------------------------------------------------
if [ -f "$STAMP" ] \
  && [ -L "$SYMLINK" ] \
  && [ "$(cat "$STAMP" 2>/dev/null || echo "")" = "$PLUGIN_VERSION" ]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Bootstrap shared venv. uv handles existing venvs gracefully; pip
# fallback is for users without uv installed.
# ---------------------------------------------------------------------------
mkdir -p "$(dirname "$VENV_DIR")"

if command -v uv >/dev/null 2>&1; then
  uv venv "$VENV_DIR"
  uv pip install --python "$VENV_DIR/bin/python" -e "$PLUGIN_ROOT"
else
  if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip
  fi
  "$VENV_DIR/bin/pip" install -e "$PLUGIN_ROOT"
fi

# Atomic symlink replace (works whether $SYMLINK is missing or already
# a symlink to a different target).
ln -sfn "$VENV_DIR" "$SYMLINK"

# Stamp this version so the next SessionStart can skip cleanly.
echo "$PLUGIN_VERSION" > "$STAMP"
