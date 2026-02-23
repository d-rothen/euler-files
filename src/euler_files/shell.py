"""Shell integration: generate shell functions for eval."""

from __future__ import annotations


def generate_shell_init(shell: str = "bash") -> str:
    """Generate a shell function that wraps euler-files sync with eval."""
    if shell in ("bash", "zsh"):
        return _BASH_ZSH_INIT
    elif shell == "fish":
        return _FISH_INIT
    else:
        return _BASH_ZSH_INIT


_BASH_ZSH_INIT = """\
# euler-files shell integration
# Usage: ef [command] [options]
# Default command is 'sync' (with eval)
ef() {
    local cmd="${1:-sync}"
    shift 2>/dev/null || true

    case "$cmd" in
        sync)
            eval "$(euler-files sync "$@")"
            ;;
        *)
            euler-files "$cmd" "$@"
            ;;
    esac
}"""

_FISH_INIT = """\
# euler-files shell integration
# Usage: ef [command] [options]
# Default command is 'sync' (with eval)
function ef
    if test (count $argv) -eq 0
        eval (euler-files sync)
        return
    end

    set cmd $argv[1]
    set -e argv[1]

    switch $cmd
        case sync
            eval (euler-files sync $argv)
        case '*'
            euler-files $cmd $argv
    end
end"""
