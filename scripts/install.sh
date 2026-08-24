#!/bin/sh
set -eu

repository="KoukeNeko/CloakGPT"
version="${CLOAKGPT_VERSION:-latest}"
install_dir="${CLOAKGPT_INSTALL_DIR:-$HOME/.local/bin}"

case "$version" in
    latest | v*) ;;
    *) version="v$version" ;;
esac

case "$(uname -s)-$(uname -m)" in
    Linux-x86_64 | Linux-amd64)
        asset="cloakgpt-linux-x86_64"
        ;;
    Linux-aarch64 | Linux-arm64)
        asset="cloakgpt-linux-arm64"
        ;;
    Darwin-x86_64 | Darwin-amd64)
        asset="cloakgpt-macos-x86_64"
        ;;
    Darwin-arm64 | Darwin-aarch64)
        asset="cloakgpt-macos-arm64"
        ;;
    *)
        echo "error: unsupported platform: $(uname -s) $(uname -m)" >&2
        exit 1
        ;;
esac

if ! command -v curl >/dev/null 2>&1; then
    echo "error: curl is required" >&2
    exit 1
fi

if [ "$version" = "latest" ]; then
    download_base="https://github.com/$repository/releases/latest/download"
else
    download_base="https://github.com/$repository/releases/download/$version"
fi

temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/cloakgpt.XXXXXX")
cleanup() {
    rm -f "$temp_dir/$asset" "$temp_dir/$asset.sha256"
    rmdir "$temp_dir" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

echo "Downloading $asset ($version)..."
curl --fail --location --silent --show-error \
    --output "$temp_dir/$asset" "$download_base/$asset"
curl --fail --location --silent --show-error \
    --output "$temp_dir/$asset.sha256" "$download_base/$asset.sha256"

expected=$(awk 'NR == 1 { print $1 }' "$temp_dir/$asset.sha256")
if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$temp_dir/$asset" | awk '{ print $1 }')
else
    actual=$(shasum -a 256 "$temp_dir/$asset" | awk '{ print $1 }')
fi

if [ "$expected" != "$actual" ]; then
    echo "error: SHA-256 checksum mismatch" >&2
    exit 1
fi

mkdir -p "$install_dir"
install -m 755 "$temp_dir/$asset" "$install_dir/cloakgpt"
executable="$install_dir/cloakgpt"

echo "Installed cloakgpt to $executable"
echo "Installing the external CloakBrowser binary..."
browser_installed=false
if "$executable" browser install; then
    browser_installed=true
    echo "CloakBrowser installed successfully."
else
    echo "warning: CloakBrowser installation failed; CloakGPT remains installed." >&2
    browser_overrides=""
    for name in \
        CLOAKBROWSER_BINARY_PATH \
        CLOAKBROWSER_CACHE_DIR \
        CLOAKBROWSER_DOWNLOAD_URL \
        CLOAKBROWSER_LICENSE_KEY \
        CLOAKBROWSER_RELEASE_CHANNEL \
        CLOAKBROWSER_VERSION
    do
        eval "value=\${$name:-}"
        if [ -n "$value" ]; then
            browser_overrides="${browser_overrides}${browser_overrides:+, }$name"
        fi
    done
    if [ -n "$browser_overrides" ]; then
        echo "warning: check the detected environment overrides: $browser_overrides" >&2
    fi
    echo "Retry with: '$executable' browser install" >&2
fi

login_state="NOT STARTED"
if [ "$browser_installed" = true ]; then
    if [ -t 0 ] && [ -t 1 ]; then
        echo
        echo "CloakGPT and CloakBrowser are ready. Opening ChatGPT login..."
        if "$executable" login; then
            login_state="FLOW COMPLETED"
        else
            login_state="INCOMPLETE"
            echo "warning: ChatGPT login did not complete; run it again from the MOTD command." >&2
        fi
    else
        login_state="WAITING FOR INTERACTIVE TERMINAL"
    fi
else
    login_state="WAITING FOR CLOAKBROWSER"
fi

on_path=true
case ":$PATH:" in
    *":$install_dir:"*) ;;
    *) on_path=false ;;
esac

echo
echo "============================================================"
if [ "$browser_installed" = true ] && [ "$login_state" = "FLOW COMPLETED" ]; then
    echo "  CloakGPT is ready"
else
    echo "  CloakGPT installation needs one more step"
fi
echo "============================================================"
echo "  Application : READY"
echo "  Release     : $version ($asset)"
echo "  Installed at: $executable"
if [ "$browser_installed" = true ]; then
    echo "  Browser     : READY"
else
    echo "  Browser     : NEEDS SETUP"
fi
echo "  Login       : $login_state"
echo "------------------------------------------------------------"

if [ "$browser_installed" != true ]; then
    echo "  Next steps"
    echo "    1. '$executable' browser install"
    echo "    2. '$executable' login"
elif [ "$login_state" != "FLOW COMPLETED" ]; then
    echo "  Next step"
    echo "    '$executable' login"
else
    echo "  Quick start"
    echo "    session_id=\$('$executable' session open)"
    echo "    '$executable' ask --session \"\$session_id\" \"Hello\""
fi

if [ "$on_path" != true ]; then
    echo "------------------------------------------------------------"
    echo "  PATH notice"
    echo "    Add $install_dir to PATH to run: cloakgpt"
fi
echo "============================================================"
