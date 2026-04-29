# paperwiki bash-helpers — v0.3.38 (PATH guard + CLAUDE_PLUGIN_ROOT resolver).
#
# This file is meant to be `source`d by SKILL bash blocks, NOT executed
# directly. There is no shebang because POSIX sourcing ignores the
# interpreter header — the active shell processes the file.
#
# Install location: ensure-env.sh installs this file at every
# SessionStart to ``$HOME/.local/lib/paperwiki/bash-helpers.sh``.
# SKILLs source it via the `source-or-die` stanza documented at
# tasks/plan.md §15.2 D-9.38.4 — failure to source emits a loud
# restart-Claude-Code instruction (no silent fallback).
#
# Public functions (D-9.38.2):
#   paperwiki_ensure_path         idempotent ``$HOME/.local/bin`` PATH prepend
#   paperwiki_resolve_plugin_root  idempotent CLAUDE_PLUGIN_ROOT resolver
#   paperwiki_bootstrap            convenience wrapper that calls both
#
# Each function is idempotent: a second invocation in the same shell
# is a cheap no-op. SKILLs that need only one half (most need only
# the PATH guard) call the targeted function directly; SKILLs that
# need the plugin-cache resolver (currently setup + digest) call
# ``paperwiki_bootstrap``.

paperwiki_ensure_path() {
    # Prepend $HOME/.local/bin to PATH if missing. Idempotent —
    # repeated calls don't double-up. We compare the colon-padded
    # PATH against ":<dir>:" so prefix/suffix entries match correctly
    # without requiring `[[ ]]` (POSIX-friendly for the active shell).
    case ":${PATH:-}:" in
        *":$HOME/.local/bin:"*) : ;;  # already present, no-op
        *) export PATH="$HOME/.local/bin${PATH:+:$PATH}" ;;
    esac
}

paperwiki_resolve_plugin_root() {
    # Set and export CLAUDE_PLUGIN_ROOT to the highest-version
    # paper-wiki plugin cache directory. Preserves an existing
    # non-empty value (idempotent — useful for nested SKILL invocations
    # where Claude Code already supplied the env var).
    if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
        return 0
    fi
    # Resolve the highest-version cache dir defensively. The pipeline
    # mirrors the inline form that lived in skills/setup/SKILL.md and
    # skills/digest/SKILL.md before v0.3.38 collapsed it here:
    #   - ls -d expands the glob into one dir per line (with trailing /)
    #   - grep -v '\.bak\.' skips backup dirs left by paperwiki update
    #   - sort -V | tail -1 picks the highest version
    #   - sed strips the trailing /
    local resolved
    resolved=$(
        ls -d "$HOME/.claude/plugins/cache/paper-wiki/paper-wiki/"*/ 2>/dev/null \
            | grep -v '\.bak\.' \
            | sort -V \
            | tail -1 \
            | sed 's:/$::'
    )
    if [ -n "$resolved" ]; then
        export CLAUDE_PLUGIN_ROOT="$resolved"
    fi
}

paperwiki_bootstrap() {
    # Convenience wrapper: ensure PATH + resolve CLAUDE_PLUGIN_ROOT.
    # SKILLs that need both (setup, digest) call this. SKILLs that
    # need only the PATH guard call paperwiki_ensure_path directly.
    paperwiki_ensure_path
    paperwiki_resolve_plugin_root
}
