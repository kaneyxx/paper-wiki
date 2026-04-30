# paperwiki bash-helpers — v0.3.40 (PATH guard + CLAUDE_PLUGIN_ROOT resolver).
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
# Public functions (D-9.38.2 expanded by D-9.39.3):
#   paperwiki_ensure_path         idempotent ``$HOME/.local/bin`` PATH prepend
#   paperwiki_resolve_plugin_root  idempotent CLAUDE_PLUGIN_ROOT resolver
#   paperwiki_bootstrap            convenience wrapper that calls both
#   paperwiki_diag                 read-only install-state diagnostic dump
#
# v0.3.39 D-9.39.3 supersedes the v0.3.38 "exactly three functions"
# constraint. Going forward: this header is the public-API contract;
# new functions land via a versioned D record and bump the version
# tag above. Internal helpers stay underscore-prefixed
# (``_paperwiki_*``) and may change without notice.
#
# Each function is idempotent: a second invocation in the same shell
# is a cheap no-op. SKILLs that need only one half (most need only
# the PATH guard) call the targeted function directly; SKILLs that
# need the plugin-cache resolver (currently setup + digest) call
# ``paperwiki_bootstrap``. ``paperwiki_diag`` is for ad-hoc debug
# (not invoked by SKILLs); its output is safe to share when asking
# for help — does NOT dump secrets, recipe contents, or transcripts.

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

_paperwiki_diag_render() {
    # Internal helper — emits the full diag dump to stdout. Split from
    # ``paperwiki_diag`` (v0.3.40 D-9.40.5) so the public function can
    # redirect to a file via ``--file <path>`` without duplicating the
    # body. Underscore-prefix marks this as private API; downstream
    # callers must use ``paperwiki_diag``.
    local helper_self="${BASH_SOURCE[0]}"
    local shim_path="$HOME/.local/bin/paperwiki"
    local cache_root="$HOME/.claude/plugins/cache/paper-wiki/paper-wiki"
    local installed_plugins="$HOME/.claude/plugins/installed_plugins.json"
    local recipes_dir="$HOME/.config/paper-wiki/recipes"

    echo "=== paperwiki_diag — install state ==="
    echo "--- helper ---"
    if [ -f "$helper_self" ]; then
        head -1 "$helper_self"
    else
        echo "(helper self-path not resolvable: $helper_self)"
    fi
    echo
    echo "--- environment ---"
    echo "PATH=${PATH:-(unset)}"
    echo "CLAUDE_PLUGIN_ROOT=${CLAUDE_PLUGIN_ROOT:-(unset)}"
    echo
    echo "--- shim ($shim_path) ---"
    if [ -f "$shim_path" ]; then
        head -2 "$shim_path"
    else
        echo "(not installed)"
    fi
    echo
    echo "--- plugin cache versions ($cache_root) ---"
    if [ -d "$cache_root" ]; then
        ls -1 "$cache_root" 2>/dev/null || echo "(empty)"
    else
        echo "(directory does not exist)"
    fi
    echo
    # v0.3.40 D-9.40.3: domain-bounded read of Claude Code's
    # installed_plugins.json — print ONLY the paper-wiki entry. The file
    # itself is Claude Code's domain (we never write it); this section
    # exists because the v0.3.39 debug session needed exactly this
    # information to diagnose a half-fail (file recorded a version +
    # gitCommitSha + installPath that didn't match the on-disk cache).
    # Defensive: file-missing AND entry-missing both yield "(not registered)";
    # malformed JSON yields "(read failed: <msg>)" — never crashes the
    # diag function.
    echo "--- installed_plugins.json (paper-wiki entry) ---"
    if [ -f "$installed_plugins" ]; then
        python3 - "$installed_plugins" <<'PYEOF'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
    plugins = data.get("plugins", {}) if isinstance(data, dict) else {}
    entry = plugins.get("paper-wiki@paper-wiki")
    if entry is None:
        print("(not registered)")
    else:
        print(json.dumps(entry, indent=2))
except Exception as exc:  # noqa: BLE001 — defensive catch-all per D-9.40.3
    print(f"(read failed: {exc})")
PYEOF
    else
        echo "(not registered)"
    fi
    echo
    echo "--- recipes ($recipes_dir) ---"
    if [ -d "$recipes_dir" ]; then
        ls -1 "$recipes_dir" 2>/dev/null || echo "(empty)"
    else
        echo "(directory does not exist)"
    fi
    echo "=== end paperwiki_diag ==="
}

paperwiki_diag() {
    # paper-wiki install-state diagnostic dump (v0.3.39 D-9.39.3 +
    # v0.3.40 D-9.40.5).
    #
    # Read-only on the install state — no env mutation, no secret
    # content, no writes EXCEPT the user-supplied ``--file <path>``.
    # Output is safe to share when asking for help: prints PATH (not
    # secret), CLAUDE_PLUGIN_ROOT (already public via SKILL prose),
    # the helper's own version tag, the shim's first lines, and
    # ``ls -1`` of two known directories. Does NOT print secrets.env,
    # recipe contents, or any tool-call output.
    #
    # Modes:
    #   paperwiki_diag                        Print full dump to stdout (default).
    #   paperwiki_diag --file <path>          Atomic-write the full dump to <path>
    #                                         (creating parent dirs as needed) and
    #                                         echo "wrote diag to <path>" to stdout.
    # v0.3.41 D-9.41.3: ``--file`` without a path arg defaults to a
    # timestamped file under ``$HOME`` (universally writable). The
    # ``--*`` guard ensures ``--file --some-other-flag`` doesn't
    # consume the second flag as a path. Explicit-path mode unchanged.
    local output_path=""
    case "${1:-}" in
        --file)
            shift
            if [ -z "${1:-}" ] || [[ "$1" == --* ]]; then
                output_path="$HOME/paper-wiki-diag-$(date -u +%Y%m%dT%H%M%SZ).txt"
            else
                output_path="$1"
                shift
            fi
            ;;
    esac

    if [ -n "$output_path" ]; then
        # Best-effort parent-dir creation. ``mkdir -p`` succeeds when
        # the dir already exists, so this is idempotent. The file
        # write itself happens inside a subshell with stdout
        # redirected — atomic from the caller's POV (no partial-write
        # midstate visible on stdout).
        local parent_dir
        parent_dir=$(dirname "$output_path")
        mkdir -p "$parent_dir" || {
            echo "paperwiki_diag: failed to create parent dir: $parent_dir" >&2
            return 1
        }
        _paperwiki_diag_render > "$output_path"
        echo "wrote diag to $output_path"
    else
        _paperwiki_diag_render
    fi
}
