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

echo "Installed cloakgpt to $install_dir/cloakgpt"
case ":$PATH:" in
    *":$install_dir:"*) ;;
    *) echo "Add $install_dir to PATH before running cloakgpt." ;;
esac
