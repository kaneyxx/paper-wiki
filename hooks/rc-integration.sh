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
    # Shell selection per D-9.42.2 + v0.3.43 D-9.43.5 (fish):
    #   /zsh           → $HOME/.zshrc
    #   /bash on macOS → $HOME/.bash_profile if exists, else .bashrc
    #   /bash on Linux → $HOME/.bashrc
    #   /fish          → $HOME/.config/fish/config.fish (v0.3.43+)
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
        fish)
            # v0.3.43 D-9.43.5: fish shell support. Fish can't source
            # bash-helpers.sh (different syntax), so the block we
            # write is fish-syntax — adds ~/.local/bin to
            # $fish_user_paths and notes that paperwiki_diag (bash
            # form) requires bash/zsh; paperwiki diag (CLI) works
            # in fish via the shim.
            echo "$HOME/.config/fish/config.fish"
            ;;
        *)
            # Unsupported shells (csh, tcsh, ksh, dash, …) — emit
            # nothing. Caller treats empty as no-op + warn.
            echo ""
            ;;
    esac
}

_paperwiki_rc_block() {
    # Print the canonical marker-delimited block content for the rc file
    # at $1 (or, if missing, fall back to bash/zsh block).
    #
    # v0.3.43 D-9.43.5: fish gets a different block (fish-syntax,
    # PATH-only — no `source` of bash). Detection is by filename suffix
    # (.fish) so the function stays shell-agnostic at call time.
    local rc_file="${1:-}"
    if [[ "$rc_file" == *.fish ]]; then
        cat <<'BLOCK_EOF'
# >>> paperwiki helpers >>> (managed by paperwiki — do not edit between markers)
if test -d "$HOME/.local/bin"
    fish_add_path -aP "$HOME/.local/bin"
end
# Note: paperwiki_diag (bash form) requires bash/zsh; use `paperwiki diag` (CLI) in fish.
# <<< paperwiki helpers <<<
BLOCK_EOF
        return 0
    fi
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
        # ensure-env.sh-side warn for first-time users on csh/tcsh.
        return 0
    fi
    # v0.3.43 D-9.43.5: fish's config.fish lives under ~/.config/fish/,
    # which may not exist on a fresh install. Create the parent dir
    # before testing for file presence; for bash/zsh the parent is
    # always $HOME so this mkdir is cheap.
    mkdir -p "$(dirname "$rc")" 2>/dev/null || true
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
        _paperwiki_rc_block "$rc"
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
