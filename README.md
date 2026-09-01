<img width="1774" height="887" alt="image" src="https://github.com/user-attachments/assets/af353f4c-b3f2-4924-ab12-793927f9bbbb" />

# CloakGPT

[![CI](https://github.com/KoukeNeko/CloakGPT/actions/workflows/ci.yml/badge.svg)](https://github.com/KoukeNeko/CloakGPT/actions/workflows/ci.yml)

CloakGPT is a CLI that automates a user-owned ChatGPT session through
CloakBrowser. It can start conversations, keep persistent agent sessions, run
different sessions concurrently in one shared browser, select an available
model and reasoning level, report ChatGPT's live page status, and return the
final response with Markdown formatting and citation sources.

## Requirements

- 64-bit Linux, macOS, or Windows
- A ChatGPT account you can sign in to at `chatgpt.com`
- A graphical desktop for the one-time visible `cloakgpt login`
- Permission to download and run [CloakBrowser](https://cloakbrowser.dev/), an
  external binary under its own license
- About 500 MB of free space

Python, `pip`, Node.js, and Git are **not** needed to run a packaged release.
Full details, including network and installer tooling, are in
[Installation](docs/installation.md#requirements).

## Install a release

The installers download the executable for the current platform, verify its
SHA-256 checksum, install it for the current user, and then download the
external CloakBrowser binary. If the browser download fails, CloakGPT remains
installed and the completion MOTD prints the browser retry and login commands.
When both components install successfully in an interactive terminal, the
installer automatically opens the visible ChatGPT login flow.

Choosing a prerelease, pinning an exact version, changing the install
directory, updating, and uninstalling are all covered in
[Installation](docs/installation.md).

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

Want a coding agent to perform the whole installation and verify it? Hand it the
task in [Agent setup](docs/agent-setup.md).

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

Only one process can own the persistent browser profile at a time. Session
browsers close after every completed response, and an idle daemon does not hold
the profile. If `ask` or `login` still reports that it is in use (older builds
may instead print a Chromium log ending in `exitCode=21`), run
`cloakgpt daemon status`. Wait for an active request or stop the daemon and
retry. If `daemon stop` reports that requests are still running and they can no
longer finish, use `cloakgpt daemon stop --force`. If no daemon is running,
close the existing CloakGPT Chromium window. Do not delete profile lock files or
terminate unrelated Chrome processes.

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
and puts no limit on how long a response may take, because generation time
depends on the model and prompt. Completion is detected from ChatGPT's active
generation and assistant-turn state; press Ctrl+C to stop manually. Stopping
disconnects the client, and the daemon cancels the request it was waiting on and
closes that browser page rather than finishing work nobody is reading. The
message may already have reached ChatGPT, so check the conversation before
resending it.

What is bounded is inactivity. Growing response text or a changed activity label
restarts a 15-minute stall window, so a long generation is never interrupted,
while a page that goes completely inert reports an unknown delivery state and
releases its browser page instead of pinning the daemon's browser open. Set
`CLOAKGPT_RESPONSE_STALL_SECONDS` to another number of seconds, or to `0` to
wait indefinitely. Use `--headed` when you want to observe or debug the browser
window:

```sh
cloakgpt ask "Reply only: OK." --headed
```

### Asking without signing in

A one-shot `ask` works on a signed-out profile. ChatGPT then picks the model
itself, so `--model` and `--reasoning` are rejected rather than ignored, and the
reported page status reads `signed-out default`. ChatGPT serves signed-out
visitors one of two composers and CloakGPT drives either.

Persistent sessions still need an account. A signed-out conversation is not
addressable the way `--session` requires, so a session request on a signed-out
profile fails with a message pointing at `cloakgpt login` instead of sending
anything.

Every `ask`, including a one-shot new conversation, goes through one local
daemon and one persistent browser context. Different persistent session IDs and
independent one-shot calls open separate pages and may generate responses at the
same time; CloakGPT does not impose a page-count limit. Calls using the same
session ID remain FIFO so each follow-up sees the preceding turn's saved
conversation URL. A completed request closes only its own page. Chromium closes
after the last active or waiting request finishes, while the daemon remains
ready without holding the profile. The daemon's configured browser mode and
timezone apply to every request.

Text output keeps progress on stderr and writes only the completed answer to
stdout. Agent runtimes that monitor stdout one line at a time can request a
machine-readable event stream instead:

```sh
cloakgpt ask "Reply only: OK." --output jsonl
```

Every emitted status is immediately flushed as its own JSON line. Each line has
`type` set to `status`, `result`, or `error`. `status` events contain `message`;
the single successful `result` contains the complete Markdown `answer`. An
`error` event is followed by a nonzero exit code. This makes progress observable
through stdout-only monitors without mixing human status prefixes into the
answer.

Run JSONL mode directly in the foreground when live progress matters. Do not
pipe it through `grep`, `tail`, command substitution, or another filter that
keeps only the `result` line; doing so hides the status stream during long
responses. Agents should consume every line as it arrives, show or retain each
`status.message`, and finish with `result.answer`.

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

The first message creates a ChatGPT conversation. CloakGPT saves its validated
conversation URL under the local session ID. Every message opens that URL in a
fresh page, waits for the complete answer, saves the current URL, and closes
only that request's page. Other sessions in the shared browser continue running;
the browser context closes when the final request finishes. This preserves
follow-up conversation state without keeping Chromium running while the daemon
is idle. Set `CLOAKGPT_SESSION_ID` to omit `--session`:

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

One daemon owns the browser profile. Requests for different session IDs and
one-shot conversations run on independent pages without an application-level
page limit. Requests sharing one session ID are serialized in arrival order.
The daemon's configured headed/headless mode and timezone cannot change while
it is running. Inspect and cleanly close state with:

```sh
cloakgpt session status SESSION_ID
cloakgpt session close SESSION_ID
cloakgpt daemon status
cloakgpt daemon stop
cloakgpt daemon stop --force
```

`daemon status` reports whether the browser is running plus the active, queued,
and open-page counts. `session status` reports that session's running and queued
request counts.

A daemon starts on demand and does not always exist, so `daemon status` treats
its absence as an answer rather than a failure: it prints `{"running": false}`
and exits successfully, and a reachable daemon reports `"running": true`
alongside the rest of its state. Stopping a daemon that is already stopped
likewise succeeds, reporting `"already_stopped": true`. A daemon that is running
but cannot be reached remains an error, and names the process to end.

`daemon stop` waits a short while for running requests to finish. If any are
still running it refuses to stop and leaves the daemon serving them, so a long
response is never cut off by accident. `daemon stop --force` closes the browser
and abandons whatever is left, and reports the count as `abandoned_requests`.
Use it when a request can no longer finish, for example after the client that
started it exited.

An idle daemon does not own the browser profile, so `cloakgpt login` can open it
without discarding session IDs. Do not start login while a session request is
active. If login reports that the profile is already in use, wait for that
request or stop the daemon; stopping preserves session IDs and conversation
URLs.

Browser failures before delivery are retried once on a reconstructed page.
Failures after the send click report `delivery state unknown` and are never
automatically resent. The request's page is closed in both success and error
paths without closing pages owned by other active sessions.

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

## Security model

CloakGPT is a local user-level CLI, not a sandbox or an authorization service.
It intentionally controls a signed-in ChatGPT browser profile and can send
messages. A user or agent permitted to execute `cloakgpt` under the same
operating-system account is therefore trusted to operate that profile only
within the authority the user granted.

Persistent session IDs select local conversations; they are not ChatGPT
credentials or daemon authentication keys. The daemon uses a separate random
authentication key stored in the CloakGPT data directory. On POSIX systems,
metadata files containing that key are written with mode `0600`. The browser
profile, daemon metadata, session IDs, and conversation URLs should still be
treated as sensitive local data and must not be committed or published.

Official installers download a platform asset and its `.sha256` file from the
project's GitHub Release, then verify the checksum before installation. macOS
release assets are Developer ID signed and notarized. Windows assets are not
currently code-signed, so Windows may display a warning. CloakBrowser is a
separately downloaded external binary governed by its own license and security
boundary; see [Install a release](#install-a-release) and
[Disclaimer](#disclaimer).

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
