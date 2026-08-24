# CloakGPT

[![CI](https://github.com/KoukeNeko/CloakGPT/actions/workflows/ci.yml/badge.svg)](https://github.com/KoukeNeko/CloakGPT/actions/workflows/ci.yml)

CloakGPT is a CLI that automates a user-owned ChatGPT session through
CloakBrowser. It can start conversations, keep persistent agent sessions,
select an available model and reasoning level, report ChatGPT's live page
status, and return the final response with Markdown formatting and citation
sources.

## Table of contents

- [Install a release](#install-a-release)
  - [Linux and macOS](#linux-and-macos)
  - [Windows](#windows)
- [Install the agent skill (recommended)](#install-the-agent-skill-recommended)
- [Release options and assets](#release-options-and-assets)
- [Update CloakGPT](#update-cloakgpt)
- [Instructions for an agent](#instructions-for-an-agent)
- [Uninstall](#uninstall)
- [Login](#login)
- [Manage the external browser](#manage-the-external-browser)
- [Ask ChatGPT](#ask-chatgpt)
- [Persistent agent sessions](#persistent-agent-sessions)
- [Select a model and reasoning level](#select-a-model-and-reasoning-level)
- [User data](#user-data)
- [Run from source](#run-from-source)
- [Test and build](#test-and-build)
  - [macOS release signing](#macos-release-signing)
- [License](#license)
- [Disclaimer](#disclaimer)

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

When no exact version is supplied, an interactive installer asks whether to
install the latest stable or prerelease build. A non-interactive installer uses
the stable channel unless `CLOAKGPT_CHANNEL=prerelease` or
`-Channel prerelease` is supplied explicitly. If the selected channel has no
published release, the installer stops with a clear error.

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
installation. CloakGPT uses the current terminal for CLI input and output; its
persistent-session daemon runs without opening a separate console window.
Windows text I/O is set to UTF-8 even when the terminal initially uses Big5
(code page 950).

## Install the agent skill (recommended)

`skills/use-cloakgpt` follows the portable
[Agent Skills specification](https://openagentskills.dev/docs/specification),
so the same `SKILL.md` works with Claude Code, Codex, Gemini CLI, and other
compatible coding agents. Review the skill before installing it; an agent will
follow its instructions with the permissions available to that agent.

For an interactive installation, run:

```sh
npx -y skills add https://github.com/KoukeNeko/CloakGPT/tree/main/skills/use-cloakgpt -g
```

The installer detects installed coding agents and asks which target to use when
a choice is needed. The person installing the skill does not need to know an
agent slug.

Common slugs and their user-level destinations are:

| Agent | Slug | Expected `SKILL.md` |
| --- | --- | --- |
| Claude Code | `claude-code` | `~/.claude/skills/use-cloakgpt/SKILL.md` |
| Codex | `codex` | `$CODEX_HOME/skills/use-cloakgpt/SKILL.md`, or `~/.codex/skills/use-cloakgpt/SKILL.md` when `CODEX_HOME` is unset |
| Gemini CLI | `gemini-cli` | `~/.gemini/skills/use-cloakgpt/SKILL.md` |

Do not treat a successful installer exit code as proof that the current agent
can discover the skill. Check the native destination and reload or restart the
agent when required.

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
CLOAKGPT_VERSION=v0.1.0-pre.6 CLOAKGPT_INSTALL_DIR="$HOME/bin" sh install.sh
```

```powershell
.\install.ps1 -Version v0.1.0-pre.6 -InstallDir D:\Tools\CloakGPT
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
cloakgpt update --version v0.1.0-pre.6
```

`--channel` and `--version` cannot be combined. Exact versions may upgrade or
downgrade the installed build. Source checkouts do not overwrite themselves;
update those with Git instead.

Before replacement, CloakGPT verifies the release checksum, GitHub asset
digest, embedded version, and bundled Playwright driver. An actual update stops
the session daemon but preserves the browser profile and persistent session
records. Linux and macOS replace the executable immediately. Windows stages a
hidden UTF-8 updater that replaces the executable after the command exits,
rolls back a failed build, and reports its result on the next CloakGPT command.

The external browser remains independently managed. Update it only when needed:

```sh
cloakgpt browser update
```

## Instructions for an agent

Paste the following complete task into the coding agent that should use
CloakGPT. It includes installation, fallback, and verification instead of
assuming that one command succeeded:

<details>
<summary>Show the complete installation prompt</summary>

```text
Install and fully set up CloakGPT and its `use-cloakgpt` Agent Skill on this
machine. Use only the official repository and releases at
https://github.com/KoukeNeko/CloakGPT. Continue autonomously until setup is
complete or the only remaining step requires the user. Do not claim success
merely because an installer returned exit code 0.

Setup is complete only when all of these are true:

- The native CloakGPT executable runs and its exact path is known.
- The external CloakBrowser binary reports ready.
- The user has completed ChatGPT sign-in in CloakGPT's visible browser.
- `use-cloakgpt/SKILL.md` is installed in this runtime's user-level skill path,
  has valid `name` and `description` frontmatter, and is discoverable by the
  runtime.

Follow this procedure:

1. Detect the operating system and architecture. Also identify the agent
   runtime you are currently running in; do not assume Codex. Determine its
   exact `skills --agent` slug and native user-level skills directory. Known
   mappings are Claude Code = `claude-code` and `~/.claude/skills`, Codex =
   `codex` and `CODEX_HOME/skills` when `CODEX_HOME` is set or
   `~/.codex/skills` otherwise, and Gemini CLI = `gemini-cli` and
   `~/.gemini/skills`. For another runtime, inspect `npx -y skills --help` and
   that runtime's local or official documentation instead of guessing.
2. Check whether a working `cloakgpt` executable is already installed. If it
   is, resolve and record its absolute path. Otherwise download, review, and run
   the official installer for the current operating system. Use the release
   channel requested by the user. If no channel was requested, ask the user to
   choose `stable` or `prerelease`; do not silently install a prerelease. Pass
   the selected channel explicitly because an agent terminal may be
   non-interactive:

   Linux or macOS:
   curl -fsSLO https://raw.githubusercontent.com/KoukeNeko/CloakGPT/main/scripts/install.sh
   CLOAKGPT_CHANNEL=CHANNEL sh install.sh
   rm install.sh

   Windows PowerShell:
   Invoke-WebRequest https://raw.githubusercontent.com/KoukeNeko/CloakGPT/main/scripts/install.ps1 -OutFile install.ps1
   powershell -ExecutionPolicy Bypass -File .\install.ps1 -Channel CHANNEL
   Remove-Item .\install.ps1

   Replace `CHANNEL` with the literal `stable` or `prerelease`. If the user
   requested an exact tag, pass `CLOAKGPT_VERSION=TAG` on Linux/macOS or
   `-Version TAG` on Windows instead; an exact tag takes precedence over the
   channel.

   The installer verifies the release checksum and attempts the external
   browser installation. It may immediately open the visible ChatGPT login
   flow. Tell the user what is happening before waiting for that interaction.
   Record the installed executable path from the installer MOTD. If the current
   terminal has stale PATH state, use that absolute path for the rest of setup
   instead of reinstalling.
3. Run `EXECUTABLE --help`. Then run `EXECUTABLE browser info --quick`. If the
   browser is not ready, run `EXECUTABLE browser install` once and inspect again.
   If it still fails, run `EXECUTABLE browser doctor`, report the diagnostic and
   any named `CLOAKBROWSER_*` environment overrides, and stop. Do not invent a
   license value or download a browser binary from another source.
4. Read the source `skills/use-cloakgpt/SKILL.md` before installing it. If a
   skill named `use-cloakgpt` already exists, inspect it first. Overwrite it only
   when it came from this same repository; otherwise stop and report the
   conflict.
5. Install the skill with the cross-agent installer, substituting the literal
   runtime slug for `AGENT_SLUG`:

   npx -y skills add https://github.com/KoukeNeko/CloakGPT/tree/main/skills/use-cloakgpt -g -a AGENT_SLUG -s use-cloakgpt -y

   If Node.js or `npx` is unavailable, use:

   gh skill install KoukeNeko/CloakGPT skills/use-cloakgpt --agent AGENT_SLUG --scope user

   If both installers are unavailable, clone or download the official
   repository into a temporary directory and copy the entire
   `skills/use-cloakgpt` directory into the confirmed native user-level skills
   directory. Preserve the filename exactly as uppercase `SKILL.md`.
6. Run `npx -y skills list -g -a AGENT_SLUG --json` when `npx` is available and
   locate `use-cloakgpt`. Check the runtime's native destination directly and
   read the final installed `SKILL.md`; its YAML frontmatter must contain
   `name: use-cloakgpt` and a non-empty `description`. Some combinations may
   create only `~/.agents/skills/use-cloakgpt`. If the runtime does not discover
   that canonical path, copy the entire canonical directory into its native
   user-level skill directory and verify the final file again.
7. If the installer did not already complete login and the user has not
   confirmed that the saved CloakGPT profile is signed in, determine the user's
   IANA timezone and run `EXECUTABLE login --timezone USER_TIMEZONE`. Ask the
   user when the timezone cannot be determined reliably; do not guess. Tell the
   user to sign in only in the visible ChatGPT browser window and then press
   Enter in the terminal. Never request, enter, expose, or store the user's
   password, cookies, or session tokens. If an existing CloakGPT daemon owns the
   browser profile, inspect its status and ask permission before stopping it;
   stopping preserves session IDs and conversation URLs.
8. Make the runtime rescan its skills. Gemini CLI uses `/skills reload` followed
   by `/skills list`. Claude Code normally detects changes live, but must be
   restarted if its top-level skills directory did not exist when the session
   began. For Codex, ask the user to start a new turn or session, then confirm
   that `use-cloakgpt` appears in the available skills. Follow the documented
   equivalent for another runtime. Do not mark setup complete until discovery
   is confirmed.
9. Do not send a ChatGPT message merely to test setup. Finish by reporting the
   OS and architecture, agent runtime, absolute executable path, browser state,
   login state, skill installer used, final `SKILL.md` path, verified
   frontmatter name, and runtime discovery result. If user interaction, network
   access, filesystem permissions, or a missing tool blocks completion, state
   the exact remaining action and do not describe setup as complete.
```

</details>

The prompt installs the application, external browser, and skill. The skill
itself teaches an agent how to operate the installed CloakGPT CLI.

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
and the platform defaults documented under [User data](#user-data).

When `npx` is available, the script asks the official Agent Skills CLI to
remove `use-cloakgpt` globally from all supported agents, then removes known
native skill paths as a fallback. Restart a running agent after uninstalling so
its in-memory skill list is refreshed.

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

Only one process can own the persistent browser profile. If `ask` or `login`
reports that the profile is already in use (older builds may instead print a
Chromium log ending in `exitCode=21`), first run `cloakgpt daemon status`. Reuse
a known session ID when that daemon owns the intended conversation, or run
`cloakgpt daemon stop` and retry. If no daemon is running, close the existing
CloakGPT Chromium window. Do not delete profile lock files or terminate
unrelated Chrome processes.

If a packaged macOS build reports `Failed to reserve virtual memory for
CodeRange`, its bundled Playwright Node driver was signed without the V8 JIT
entitlements. Installing CloakBrowser again will not repair that executable;
upgrade CloakGPT to a current release. Do not disable Gatekeeper as a workaround.

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
downloaded Chromium distribution, so the next `login` or `ask` command
downloads it again.

## Ask ChatGPT

```sh
cloakgpt ask "Reply only: OK."
```

`ask` starts a new conversation. It runs headless by default, sends the message,
and waits without a response deadline because generation time depends on the
model and prompt. Completion is detected from ChatGPT's active generation and
assistant-turn state; press Ctrl+C to stop manually. Use `--headed` when you
want to observe or debug the browser window:

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
stdout. Keep that ID and use `ask` for every turn:

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

Use `--model` and/or `--reasoning` with `ask`:

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

The bundled Playwright Node driver uses V8 JIT compilation. PyInstaller applies
the minimal exceptions in `macos-entitlements.plist` while signing the collected
executables: `com.apple.security.cs.allow-jit` and
`com.apple.security.cs.allow-unsigned-executable-memory`. Each release job
starts the packaged Playwright driver after signing, verifies both entitlements,
and only then submits the macOS executable for notarization.

## License

CloakGPT is available under the [MIT License](LICENSE). Third-party components
and dependencies retain their respective licenses.

## Disclaimer

CloakGPT is an independent, unofficial interoperability project. It is not
affiliated with, endorsed by, or sponsored by OpenAI or CloakHQ. `OpenAI`,
`ChatGPT`, and `GPT` are trademarks of OpenAI; `CloakBrowser` is a trademark or
product name of CloakHQ. These names identify compatible third-party services
only. Their use does not grant trademark permission or override the applicable
[OpenAI Brand Guidelines](https://openai.com/brand/), which currently state
that the `GPT` brand is not permitted in app, product, developer, or company
names. This notice does not claim a license or exception for this project's
current name.

CloakGPT controls `chatgpt.com` through a user-owned browser session and reads
the rendered response; it does not use the official OpenAI API. OpenAI's
current [Terms of Use](https://openai.com/policies/terms-of-use/) include
restrictions on automatically or programmatically extracting data or output
and on bypassing rate limits, restrictions, protective measures, or safety
mitigations. OpenAI may suspend or terminate access for violations. You are
solely responsible for determining whether each intended use complies with the
terms that apply to your account and region, the
[OpenAI Usage Policies](https://openai.com/policies/usage-policies/), your
organization's rules, third-party rights, and applicable law. This project does
not grant permission to access any account, content, or service and does not
guarantee that browser automation is permitted for a particular use.

The separately downloaded CloakBrowser compiled binary is not covered by
CloakGPT's MIT License. It is governed by the
[CloakBrowser Binary License](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md),
which may impose version-specific subscription requirements and restrictions
on redistribution, embedding, hosted services, and OEM/SaaS use. You are
responsible for obtaining any required CloakBrowser entitlement and complying
with its current terms.

CloakGPT keeps an authenticated browser profile and conversation state in its
local data directory. Treat that directory as sensitive: restrict access and
never share, publish, or commit it. Prompts, uploaded content, and responses are
processed by OpenAI under its
[Privacy Policy](https://openai.com/policies/privacy-policy/) and account data
controls. CloakGPT does not make data sent to ChatGPT private from OpenAI or
from an administrator that controls the ChatGPT account.

AI output can be incomplete, inaccurate, or inappropriate. Review important
results and do not rely on them as the sole source of truth or as a substitute
for qualified professional advice. Website interfaces, upstream software,
provider policies, and detection systems can change without notice, so
availability, compatibility, account continuity, and uninterrupted operation
are not guaranteed.

The software is provided **as is**, without warranty, under the MIT License. To
the maximum extent permitted by law, the authors and copyright holders are not
liable for account restrictions, service interruption, data loss, security
incidents, incorrect output, third-party claims, or other damages arising from
use of the software. This summary is informational and is not legal advice; the
linked governing terms control if this summary differs from them.
