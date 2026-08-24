#!/bin/sh
set -eu

install_dir="${CLOAKGPT_INSTALL_DIR:-$HOME/.local/bin}"
executable="$install_dir/cloakgpt"

if [ -f "$executable" ]; then
    rm -f "$executable"
    echo "Removed $executable"
else
    echo "CloakGPT is not installed at $executable"
fi

echo "Browser profile and conversation state were preserved."
