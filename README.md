# CloakGPT

[![CI](https://github.com/KoukeNeko/CloakGPT/actions/workflows/ci.yml/badge.svg)](https://github.com/KoukeNeko/CloakGPT/actions/workflows/ci.yml)

CloakGPT is a CLI that automates a user-owned ChatGPT session through
CloakBrowser. It can start or continue conversations, select an
available model and reasoning level, report ChatGPT's live page status, and
return the final response with Markdown formatting and citation sources.

## Install a release

The installers download the executable for the current platform, verify its
SHA-256 checksum, install it for the current user, and then download the
external CloakBrowser binary. If the browser download fails, CloakGPT remains
installed and the completion MOTD prints the browser retry and login commands.
When both components install successfully in an interactive terminal, the
installer automatically opens the visible ChatGPT login flow. Non-interactive
installs and incomplete login attempts receive a copyable login command instead.
When custom CloakBrowser path, cache, license, version, channel, or download URL
environment variables are detected, the failure message identifies the
variables that should be checked.

The final MOTD reports the application, browser, and login state. A completed
setup also includes persistent-session quick-start commands; Windows indicates
when a new terminal is required for the updated user `PATH`.

### Linux and macOS

```sh
curl -fsSLO https://raw.githubusercontent.com/KoukeNeko/CloakGPT/main/scripts/install.sh
sh install.sh
rm install.sh
```

The default destination is `~/.local/bin/cloakgpt`. If that directory is not
already on `PATH`, add it to your shell configuration.

### Windows

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/KoukeNeko/CloakGPT/main/scripts/install.ps1 -OutFile install.ps1
powershell -ExecutionPolicy Bypass -File .\install.ps1
Remove-Item .\install.ps1
```

The default destination is `%LOCALAPPDATA%\Programs\CloakGPT\cloakgpt.exe`.
The installer adds that directory to the user `PATH`; open a new terminal after
installation.

Install a specific release or choose another directory:

```sh
CLOAKGPT_VERSION=v1.0.0 CLOAKGPT_INSTALL_DIR="$HOME/bin" sh install.sh
```

```powershell
.\install.ps1 -Version v1.0.0 -InstallDir D:\Tools\CloakGPT
```

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

## Uninstall

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

Set `CLOAKGPT_INSTALL_DIR` or pass Windows `-InstallDir` if a custom destination
was used. Uninstalling preserves the browser profile and conversation state so
that a later installation remains signed in.

## Login

Open the persistent browser profile, sign in to your own ChatGPT account, then
return to the terminal and press Enter:

```sh
cloakgpt login
```

The default user timezone is `Asia/Taipei`. Override it with an IANA timezone:

```sh
cloakgpt login --timezone America/New_York
```

## Manage the external browser

The CloakBrowser Python wrapper and Playwright driver are included in the
CloakGPT executable. The much larger stealth Chromium distribution remains
separate and is downloaded directly from CloakBrowser's official service into
its user cache.

```sh
cloakgpt browser install
cloakgpt browser info --quick
cloakgpt browser update
cloakgpt browser clear-cache
```

These commands delegate to CloakBrowser's official management CLI, including
its platform selection, license handling, and binary verification. Additional
official commands and options are available through:

```sh
cloakgpt browser --help
cloakgpt browser doctor
cloakgpt browser login
cloakgpt browser logout
```

The default browser cache is `~/.cloakbrowser`. Set
`CLOAKBROWSER_CACHE_DIR` to use another location. `clear-cache` removes the
downloaded Chromium distribution, so the next `login`, `ask`, or `continue`
command downloads it again.

## Start and continue a conversation

```sh
cloakgpt ask "Reply only: OK."
cloakgpt continue "Explain your answer."
```

`ask` starts a new conversation and saves its URL. `continue` reopens the most
recent saved conversation. Both commands run headless by default, send the
message, and wait without a response deadline because generation time depends
on the model and prompt. Completion is detected from ChatGPT's active
generation and assistant-turn state; press Ctrl+C to stop manually. Use
`--headed` when you want to observe or debug the browser window:

```sh
cloakgpt ask "Reply only: OK." --headed
```

`login` always uses a visible window so authentication can be completed
interactively.

## Persistent agent sessions

For an agent that needs several turns, open one persistent session:

```sh
cloakgpt session open
```

The command prints a short MOTD to stderr and prints only the session ID to
stdout. Keep that ID and use `ask` for every turn; a separate persistent
`continue` command is unnecessary:

```sh
cloakgpt ask "First question" --session SESSION_ID
cloakgpt ask "Follow-up question" --session SESSION_ID
```

The first message creates a ChatGPT conversation. Later messages reuse the same
live page and browser context. Set `CLOAKGPT_SESSION_ID` to omit `--session`:

```sh
export CLOAKGPT_SESSION_ID=SESSION_ID
cloakgpt ask "Another follow-up"
```

PowerShell equivalent:

```powershell
$env:CLOAKGPT_SESSION_ID = "SESSION_ID"
cloakgpt ask "Another follow-up"
```

Persistent sessions are headless by default. Select a visible browser only when
opening the session:

```sh
cloakgpt session open --headed
```

One daemon owns one persistent browser profile, so its headed/headless mode and
timezone cannot change while it is running. Inspect and cleanly close state with:

```sh
cloakgpt session status SESSION_ID
cloakgpt session close SESSION_ID
cloakgpt daemon status
cloakgpt daemon stop
```

The daemon must be stopped before `cloakgpt login` can open the same persistent
profile. Stopping it preserves session IDs and conversation URLs; after login,
the next session message starts the daemon and restores the conversation.

The watchdog keeps an active page warm for two idle hours. After that it closes
the page to release browser resources but retains the session ID and validated
conversation URL, so the next `ask --session` restores the conversation. Set
`CLOAKGPT_SESSION_TTL_SECONDS` to a positive number of seconds to change the
lease. Browser failures before delivery are retried once on a reconstructed
page; failures after the send click report `delivery state unknown` and are
never automatically resent.

Status is printed to stderr while only the final response is printed to stdout,
so responses can be redirected or piped without status lines:

```text
[status] Opening ChatGPT...
[status] Current page: model=GPT-5.6 Sol, reasoning=high, url=https://chatgpt.com/
[status] Sending message...
[status] Waiting for ChatGPT response (Ctrl+C to stop)...
[status] ChatGPT is responding...
[status] ChatGPT activity: ウェブを検索中
[status] Collecting response and sources...
[status] Response complete.
```

Rendered headings, lists, links, quotes, code blocks, and tables are converted
back to Markdown. Web citation pills and their source carousel are collected in
a numbered `## Sources` section. Duplicate URLs and ChatGPT's `utm_source`
tracking parameter are removed, and answers without citations do not receive an
empty Sources section. Interactive widgets such as weather charts are omitted
when they have no faithful terminal representation; the accompanying text
summary remains in the response.

## Select a model and reasoning level

Use `--model` and/or `--reasoning` with `ask` or `continue`:

```sh
cloakgpt ask "Solve this carefully." --model gpt-5.6-sol --reasoning high
```

Model values:

| CLI value | ChatGPT label |
| --- | --- |
| `gpt-5.6-sol` | GPT-5.6 Sol |
| `gpt-5.5` | GPT-5.5 |
| `o3` | o3 |

Reasoning values:

| CLI value | ChatGPT label |
| --- | --- |
| `fast` | 最速 |
| `medium` | 中程度 |
| `high` | 高い |

Both options default to `None`. Omit an option to keep ChatGPT's current page
setting. Availability depends on the signed-in account and workspace. If a
requested option is unavailable, the CLI reports the visible menu instead of
using a private ChatGPT API.

## User data

Packaged executables store the persistent browser profile and last conversation
URL in the platform's user data directory:

| Platform | Default data directory |
| --- | --- |
| Linux | `$XDG_DATA_HOME/CloakGPT`, or `~/.local/share/CloakGPT` |
| macOS | `~/Library/Application Support/CloakGPT` |
| Windows | `%LOCALAPPDATA%\CloakGPT` |

Set `CLOAKGPT_DATA_DIR` to override this location. Source checkouts retain the
original behavior and store data in the repository unless the environment
variable is set.

## Run from source

Python 3.10 or newer is required. Use a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python cloakgpt.py login
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python cloakgpt.py login
```

## Test and build

The tests mock the browser and do not send messages to ChatGPT:

```sh
python -m unittest discover -s tests -v
```

Build the executable for the current operating system and CPU architecture:

```sh
python -m pip install -r requirements.txt -r requirements-build.txt
python -m PyInstaller --clean --noconfirm cloakgpt.spec
```

The result is written to `dist/`. PyInstaller builds for the host platform, so
the GitHub Actions matrix uses a native runner for each supported target.

`.github/workflows/ci.yml` runs tests on Linux, macOS, and Windows for every
push and pull request. `.github/workflows/release.yml` can be run manually to
produce downloadable workflow artifacts. Pushing a version tag builds all six
executables, generates checksum files, and publishes a GitHub release:

```sh
git tag v1.0.0
git push origin v1.0.0
```

### macOS release signing

The two macOS jobs require these GitHub Actions repository secrets:

| Secret | Value |
| --- | --- |
| `MACOS_CERTIFICATE_P12_BASE64` | Base64-encoded Developer ID Application `.p12` |
| `MACOS_CERTIFICATE_PASSWORD` | Password used when exporting the `.p12` |
| `APPLE_API_KEY_P8_BASE64` | Base64-encoded App Store Connect API key |
| `APPLE_API_KEY_ID` | App Store Connect API key ID |
| `APPLE_API_ISSUER_ID` | App Store Connect API issuer ID |

The workflow imports the certificate into a temporary keychain, passes its
SHA-1 identity to PyInstaller so embedded one-file binaries are signed, submits
the signed executable to Apple's notary service, and removes all temporary
signing material before the job ends. Secret values must never be committed to
the repository.

Use the automation only with an account and websites you are authorized to
access, and follow the applicable service terms.
