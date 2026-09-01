# Installation

Reference for installing, updating, and removing CloakGPT. The README covers
the common path; this page covers the requirements in full, the release
channels and assets, how updating works, and complete removal.

## Requirements

For a packaged release:

| Requirement | Details |
| --- | --- |
| Operating system | 64-bit Linux, macOS, or Windows on an architecture listed under [Release options and assets](#release-options-and-assets). CloakBrowser is downloaded separately, so its current platform availability is checked during `cloakgpt browser install`. |
| Network | HTTPS access to GitHub Releases and API, CloakBrowser's official download/license service, and `chatgpt.com`. A TLS-intercepting network must provide its trusted PEM bundle through `SSL_CERT_FILE`. |
| Account | A user-owned ChatGPT account that can sign in at `chatgpt.com`. Available models, reasoning levels, and web search depend on that account and ChatGPT's current product rules. A one-shot `ask` also works signed out, with the limits described under [Ask ChatGPT](usage.md#ask-chatgpt). |
| External browser | Permission to download and use CloakBrowser under its separate terms. A license key may be required by the selected CloakBrowser build or plan; `cloakgpt browser info --quick` reports the local state. |
| Interactive login | A graphical desktop session is required for the initial visible `cloakgpt login` flow. Normal `ask` commands are headless by default after login is saved. |
| Storage | Plan for at least 500 MB of free space. The CloakGPT executable is separate from the external Chromium download, which CloakBrowser currently describes as approximately 200 MB cached; profiles and multiple cached browser versions need additional space. |
| Installer tooling | Linux/macOS: a POSIX shell, standard utilities including `awk`, `mktemp`, and `install`, `curl`, and either `sha256sum` or `shasum`. Windows: PowerShell with `Invoke-WebRequest` and `Get-FileHash`. |

Current CI builds and tests on Ubuntu 24.04, macOS 15, Windows Server 2025
(x86-64), and Windows 11 ARM. These are verified environments, not a formal
minimum-version guarantee for the independently downloaded Chromium binary.

The packaged executable already contains Python, the CloakBrowser Python
wrapper, Playwright, and the CA certificates used by the updater. Python,
`pip`, Node.js, `npx`, and Git are **not** required to run CloakGPT. CloakBrowser
itself remains an external binary with its own
[availability, license, and usage terms](https://cloakbrowser.dev/).

Installing the recommended agent skill additionally needs Node.js/`npx`, the
GitHub CLI fallback, or a compatible agent's manual skill-install mechanism.
Running from source and building a packaged executable are described in
[Contributing](../CONTRIBUTING.md).

## Release options and assets

Select a release channel in a non-interactive shell:

```sh
CLOAKGPT_CHANNEL=prerelease sh install.sh
```

```powershell
.\install.ps1 -Channel prerelease
```

Valid channels are `stable` and `prerelease`. Non-interactive installs default
to `stable`; interactive installs show a numbered choice. To install an exact
tag or choose another directory, use:

```sh
CLOAKGPT_VERSION=v0.1.1-pre.1 CLOAKGPT_INSTALL_DIR="$HOME/bin" sh install.sh
```

```powershell
.\install.ps1 -Version v0.1.1-pre.1 -InstallDir D:\Tools\CloakGPT
```

An exact `CLOAKGPT_VERSION` or `-Version` takes precedence over the channel.
The legacy value `latest` means the latest stable release.

The release workflow produces these native executables:

| Platform | Architecture | Release asset |
| --- | --- | --- |
| Linux | x86-64 | `cloakgpt-linux-x86_64` |
| Linux | ARM64 | `cloakgpt-linux-arm64` |
| macOS | Intel | `cloakgpt-macos-x86_64` |
| macOS | Apple Silicon | `cloakgpt-macos-arm64` |
| Windows | x86-64 | `cloakgpt-windows-x86_64.exe` |
| Windows | ARM64 | `cloakgpt-windows-arm64.exe` |

The macOS executables are signed with a Developer ID Application certificate
and notarized by Apple. The Windows executable is not currently code-signed, so
Windows may display a warning when it is opened for the first time.

## Update CloakGPT

Packaged releases contain their exact version, channel, and platform asset.
Display the installed build or check for an update without changing files:

```sh
cloakgpt --version
cloakgpt update --check
cloakgpt update --check --json
```

Install the latest release from the current build's channel:

```sh
cloakgpt update
```

A prerelease stays on the prerelease channel and a stable build stays on the
stable channel unless one is selected explicitly:

```sh
cloakgpt update --channel stable
cloakgpt update --channel prerelease
cloakgpt update --version v0.1.1-pre.1
```

`--channel` and `--version` cannot be combined. Exact versions may upgrade or
downgrade the installed build. Source checkouts do not overwrite themselves;
update those with Git instead.

Every `update` run also compares the `use-cloakgpt` skill installed for your
agents against the one that build ships. A copy that differs is reported; in an
interactive terminal you are asked whether to refresh it, and anywhere else the
reinstall command is printed instead. CloakGPT never rewrites an agent's skill
without that answer, because an agent follows those instructions as given.
Refreshing delegates to the official skills CLI, and the agent has to be
restarted afterwards to reload it. `--json` reports the same state under a
`skill` key.

Before replacement, CloakGPT verifies the release checksum, GitHub asset
digest, embedded version, and bundled Playwright driver. An actual update stops
the session daemon but preserves the browser profile and persistent session
records. Linux and macOS replace the executable immediately. Windows stages a
hidden UTF-8 updater that replaces the executable after the command exits,
rolls back a failed build, and reports its result on the next CloakGPT command.

Updater HTTPS requests verify GitHub with a CA bundle included in the packaged
executable. Networks whose TLS proxy uses a private root can point the updater
to an administrator-provided PEM bundle with `SSL_CERT_FILE`. Do not disable
certificate verification. If an older CloakGPT build cannot reach GitHub well
enough to self-update, rerun the official installer to bootstrap the current
release; installation preserves the existing browser profile and session data.

The external browser remains independently managed. Update it only when needed:

```sh
cloakgpt browser update
```

## Uninstall

The official uninstaller performs a **complete, irreversible removal**. It
stops the daemon and deletes the CloakGPT executable, ChatGPT browser profile
and cookies, conversation/session state, CloakBrowser downloads and cached
license data, and every installed `use-cloakgpt` Agent Skill it can find. A
later installation will require downloading the browser and signing in again.

Linux and macOS:

```sh
curl -fsSLO https://raw.githubusercontent.com/KoukeNeko/CloakGPT/main/scripts/uninstall.sh
sh uninstall.sh
rm uninstall.sh
```

Windows:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/KoukeNeko/CloakGPT/main/scripts/uninstall.ps1 -OutFile uninstall.ps1
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
Remove-Item .\uninstall.ps1
```

The scripts show this warning and require typing `REMOVE`. For an already
confirmed non-interactive removal, pass `--yes` on Linux/macOS or `-Yes` on
Windows. Set `CLOAKGPT_INSTALL_DIR` or pass Windows `-InstallDir` if a custom
executable destination was used. The uninstaller also honors
`CLOAKGPT_DATA_DIR`, `CLOAKBROWSER_CACHE_DIR`, `CODEX_HOME`, `XDG_DATA_HOME`,
and the platform defaults documented under [User data](../README.md#user-data).

When `npx` is available, the script asks the official Agent Skills CLI to find
and remove every global `use-cloakgpt` agent link, then removes known native
skill paths as a fallback. Restart a running agent after uninstalling so its
in-memory skill list is refreshed.
