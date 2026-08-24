#!/bin/sh
set -eu

confirmed=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        -y | --yes) confirmed=true ;;
        -h | --help)
            echo "Usage: sh uninstall.sh [--yes]"
            echo "Permanently remove CloakGPT, its browser data, and use-cloakgpt skills."
            exit 0
            ;;
        *)
            echo "error: unknown option: $1" >&2
            exit 2
            ;;
    esac
    shift
done

if [ -z "${HOME:-}" ] || [ ! -d "$HOME" ]; then
    echo "error: HOME must identify an existing user directory" >&2
    exit 1
fi

cloakgpt_home_dir=$(cd "$HOME" && pwd -P)
cloakgpt_working_dir=$(pwd -P)

expand_path() {
    case "$1" in
        "~") printf '%s\n' "$cloakgpt_home_dir" ;;
        "~/"*) printf '%s/%s\n' "$cloakgpt_home_dir" "${1#~/}" ;;
        /*) printf '%s\n' "$1" ;;
        *) printf '%s/%s\n' "$cloakgpt_working_dir" "$1" ;;
    esac
}

install_dir=$(expand_path "${CLOAKGPT_INSTALL_DIR:-$cloakgpt_home_dir/.local/bin}")
executable="$install_dir/cloakgpt"

if [ -n "${CLOAKGPT_DATA_DIR:-}" ]; then
    data_dir=$(expand_path "$CLOAKGPT_DATA_DIR")
else
    case "$(uname -s)" in
        Darwin)
            data_dir="$cloakgpt_home_dir/Library/Application Support/CloakGPT"
            ;;
        *)
            data_root=$(expand_path "${XDG_DATA_HOME:-$cloakgpt_home_dir/.local/share}")
            data_dir="$data_root/CloakGPT"
            ;;
    esac
fi
browser_cache_dir=$(expand_path "${CLOAKBROWSER_CACHE_DIR:-$cloakgpt_home_dir/.cloakbrowser}")
codex_skills_root=$(expand_path "${CODEX_HOME:-$cloakgpt_home_dir/.codex}")

resolve_existing_path() {
    if [ -d "$1" ]; then
        (cd "$1" && pwd -P)
    else
        target_parent=$(dirname "$1")
        target_name=$(basename "$1")
        resolved_parent=$(cd "$target_parent" && pwd -P)
        printf '%s/%s\n' "$resolved_parent" "$target_name"
    fi
}

assert_safe_tree() {
    target=$1
    label=$2
    resolved=$(resolve_existing_path "$target") || {
        echo "error: cannot resolve $label at $target" >&2
        exit 1
    }

    case "$resolved" in
        /)
            echo "error: refusing to remove filesystem root for $label" >&2
            exit 1
            ;;
    esac

    for protected in "$cloakgpt_home_dir" "$cloakgpt_working_dir" "$install_dir"; do
        if [ "$resolved" = "$protected" ]; then
            echo "error: refusing to remove protected directory $resolved for $label" >&2
            exit 1
        fi
        case "$protected/" in
            "$resolved/"*)
                echo "error: refusing to remove $resolved because it contains $protected" >&2
                exit 1
                ;;
        esac
    done
}

remove_tree() {
    target=$1
    label=$2
    if [ ! -e "$target" ] && [ ! -L "$target" ]; then
        return
    fi
    assert_safe_tree "$target" "$label"
    rm -rf "$target"
    echo "Removed $label: $target"
}

for planned_tree in \
    "$data_dir" \
    "$browser_cache_dir" \
    "$cloakgpt_home_dir/.aider-desk/skills/use-cloakgpt" \
    "$cloakgpt_home_dir/.agents/skills/use-cloakgpt" \
    "$cloakgpt_home_dir/.claude/skills/use-cloakgpt" \
    "$cloakgpt_home_dir/.config/agents/skills/use-cloakgpt" \
    "$cloakgpt_home_dir/.gemini/skills/use-cloakgpt" \
    "$cloakgpt_home_dir/.openclaw/skills/use-cloakgpt" \
    "$codex_skills_root/skills/use-cloakgpt"
do
    if [ -e "$planned_tree" ] || [ -L "$planned_tree" ]; then
        assert_safe_tree "$planned_tree" "planned uninstall target"
    fi
done

if [ "$confirmed" != true ]; then
    if [ ! -t 0 ]; then
        echo "error: complete uninstall requires an interactive confirmation or --yes" >&2
        exit 1
    fi
    echo "WARNING: This permanently removes CloakGPT and all local CloakGPT data."
    echo "ChatGPT cookies/session, conversation state, CloakBrowser downloads and"
    echo "license data, and installed use-cloakgpt Agent Skills will be deleted."
    printf "Type REMOVE to continue: "
    IFS= read -r answer
    if [ "$answer" != "REMOVE" ]; then
        echo "Uninstall cancelled."
        exit 0
    fi
fi

if [ -x "$executable" ]; then
    "$executable" daemon stop >/dev/null 2>&1 || true
fi

skill_cli_failed=false
if command -v npx >/dev/null 2>&1; then
    if npx -y skills remove use-cloakgpt --global --agent '*' --yes; then
        echo "Removed use-cloakgpt through the Agent Skills CLI."
    else
        skill_cli_failed=true
        echo "warning: Agent Skills CLI removal failed; removing known paths directly" >&2
    fi
fi

for skill_dir in \
    "$cloakgpt_home_dir/.aider-desk/skills/use-cloakgpt" \
    "$cloakgpt_home_dir/.agents/skills/use-cloakgpt" \
    "$cloakgpt_home_dir/.claude/skills/use-cloakgpt" \
    "$cloakgpt_home_dir/.config/agents/skills/use-cloakgpt" \
    "$cloakgpt_home_dir/.gemini/skills/use-cloakgpt" \
    "$cloakgpt_home_dir/.openclaw/skills/use-cloakgpt" \
    "$codex_skills_root/skills/use-cloakgpt"
do
    remove_tree "$skill_dir" "Agent Skill"
done

remove_tree "$data_dir" "CloakGPT user data"
remove_tree "$browser_cache_dir" "CloakBrowser cache and license data"

if [ -f "$executable" ] || [ -L "$executable" ]; then
    rm -f "$executable"
    echo "Removed executable: $executable"
else
    echo "CloakGPT executable was not present at $executable"
fi

if [ "$skill_cli_failed" = true ]; then
    echo "warning: known skill paths were removed, but the Agent Skills CLI could not verify every runtime" >&2
fi

echo "CloakGPT complete uninstall finished."
