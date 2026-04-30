# paperwiki rc-integration — v0.3.42 D-9.42.2 (shell-rc auto-source).
#
# Sourced by ``hooks/ensure-env.sh`` at SessionStart and by
# ``paperwiki uninstall --everything`` (via the runner). Provides three
# public functions:
#
#   _pick_rc_file         — print the right rc path for $SHELL, or empty
#   paperwiki_rc_install  — idempotent install of the marker block
#   paperwiki_rc_uninstall — remove the block (preserves rest of rc)
#
# And one internal helper:
#
#   _paperwiki_rc_block   — print the marker-delimited block content
#
# Industry-standard pattern (nvm, rvm, conda, miniforge): a marker-
# delimited block lets the installer own its footprint without
# touching unrelated user content. The opt-out env var
# ``PAPERWIKI_NO_RC_INTEGRATION=1`` covers users with strict rc
# discipline (chezmoi, dotfiles repos).
#
# This file MUST be safe to source from any shell ($SHELL detection
# is done at function-call time, not source-time). All public function
# names are paperwiki-namespaced. No side effects at source time.

# ---------------------------------------------------------------------------
# Markers — the begin/end lines that delimit our managed block. The
# trailing parenthetical is documentation for users who open their rc
# file and wonder where this came from.
# ---------------------------------------------------------------------------
_PAPERWIKI_RC_BEGIN="# >>> paperwiki helpers >>> (managed by paperwiki — do not edit between markers)"
_PAPERWIKI_RC_END="# <<< paperwiki helpers <<<"

_pick_rc_file() {
    # Echo the rc-file path to use for the current $SHELL, or empty for
    # unsupported shells. The caller (paperwiki_rc_install /
    # paperwiki_rc_uninstall) treats empty output as "no-op".
    #
    # Shell selection per D-9.42.2:
    #   /zsh           → $HOME/.zshrc
    #   /bash on macOS → $HOME/.bash_profile if exists, else .bashrc
    #   /bash on Linux → $HOME/.bashrc
    #   anything else  → empty (warn-only, never fail)
    local shell_basename="${SHELL##*/}"
    case "$shell_basename" in
        zsh)
            echo "$HOME/.zshrc"
            ;;
        bash)
            # Prefer ~/.bash_profile when it exists (macOS convention),
            # otherwise fall back to ~/.bashrc (Linux convention). The
            # existence-check makes the choice deterministic across
            # platforms without hard-coding a uname check.
            if [ -f "$HOME/.bash_profile" ]; then
                echo "$HOME/.bash_profile"
            else
                echo "$HOME/.bashrc"
            fi
            ;;
        *)
            # Unsupported shells (fish, csh, tcsh, ksh, dash, …) — emit
            # nothing. Caller treats empty as no-op + warn.
            echo ""
            ;;
    esac
}

_paperwiki_rc_block() {
    # Print the canonical marker-delimited block content (without
    # surrounding blank lines — those are inserted by the install
    # function so we can detect a missing block via marker presence
    # alone).
    cat <<'BLOCK_EOF'
# >>> paperwiki helpers >>> (managed by paperwiki — do not edit between markers)
[ -f "$HOME/.local/lib/paperwiki/bash-helpers.sh" ] \
    && . "$HOME/.local/lib/paperwiki/bash-helpers.sh"
# <<< paperwiki helpers <<<
BLOCK_EOF
}

paperwiki_rc_install() {
    # Idempotently write the marker block to the user's shell rc.
    # First-run: append the block. Subsequent runs: detect the begin
    # marker and skip. Opt-out via PAPERWIKI_NO_RC_INTEGRATION=1.
    #
    # Returns 0 in every path (including no-op / opt-out / unsupported
    # shell) so SessionStart never fails on rc integration.
    if [ "${PAPERWIKI_NO_RC_INTEGRATION:-}" = "1" ]; then
        return 0
    fi
    local rc
    rc=$(_pick_rc_file)
    if [ -z "$rc" ]; then
        # Unsupported shell — silent no-op. Future task may add an
        # ensure-env.sh-side warn for first-time users on fish/csh.
        return 0
    fi
    # Idempotent: skip if begin marker already present.
    if [ -f "$rc" ] && grep -qF "$_PAPERWIKI_RC_BEGIN" "$rc" 2>/dev/null; then
        return 0
    fi
    # Ensure trailing newline before our block so it lands on its own
    # paragraph (if rc exists and doesn't end with newline, add one).
    if [ -f "$rc" ] && [ -n "$(tail -c1 "$rc" 2>/dev/null)" ]; then
        printf "\n" >> "$rc"
    fi
    {
        echo
        _paperwiki_rc_block
        echo
    } >> "$rc"
}

paperwiki_rc_uninstall() {
    # Remove the marker block from the user's shell rc, preserving
    # everything else. No-op when the rc doesn't exist or the block
    # is absent. Returns 0 in every path.
    local rc
    rc=$(_pick_rc_file)
    if [ -z "$rc" ] || [ ! -f "$rc" ]; then
        return 0
    fi
    if ! grep -qF "$_PAPERWIKI_RC_BEGIN" "$rc" 2>/dev/null; then
        return 0
    fi
    # awk-based filter: skip lines from begin marker to end marker
    # (inclusive). Writes to a tmp file, then atomically replaces the
    # original — survives a partial-write crash without corrupting
    # the user's rc.
    local tmp
    tmp=$(mktemp "${rc}.paperwiki.XXXXXX")
    awk -v begin="$_PAPERWIKI_RC_BEGIN" -v end="$_PAPERWIKI_RC_END" '
        $0 == begin { in_block = 1; next }
        in_block && $0 == end { in_block = 0; next }
        !in_block { print }
    ' "$rc" > "$tmp"
    mv "$tmp" "$rc"
}
