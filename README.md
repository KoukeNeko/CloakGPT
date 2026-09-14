<img width="1774" height="887" alt="image" src="https://github.com/user-attachments/assets/af353f4c-b3f2-4924-ab12-793927f9bbbb" />

# CloakGPT

[![CI](https://img.shields.io/github/actions/workflow/status/KoukeNeko/CloakGPT/ci.yml?branch=main&style=for-the-badge&label=CI)](https://github.com/KoukeNeko/CloakGPT/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/KoukeNeko/CloakGPT?style=for-the-badge)](https://github.com/KoukeNeko/CloakGPT/releases/latest)
[![License](https://img.shields.io/github/license/KoukeNeko/CloakGPT?style=for-the-badge)](LICENSE)

**Use your own ChatGPT browser session from the terminal.**

CloakGPT is a local CLI that drives ChatGPT through CloakBrowser. **It does not
use the OpenAI API** — it operates the account you are already signed in to.

- Persistent multi-turn conversations you can return to
- Independent sessions running concurrently in one shared browser
- Model and reasoning-level selection, or leave the page as it is
- Markdown answers with their citation sources
- An OpenAI-compatible HTTP API server (`cloakgpt serve`) for Cline, Cursor, and Open WebUI
- Sign-in on a Linux server without a desktop, through an SSH-tunneled web viewer
- A portable Agent Skill so coding agents can drive it safely

## Requirements

- 64-bit Linux, macOS, or Windows
- Permission to download and run [CloakBrowser](https://cloakbrowser.dev/), an
  external binary under its own license
- About 500 MB of free space

A ChatGPT account is recommended rather than required. A one-shot `ask` works on
a signed-out profile; persistent sessions and choosing a model or reasoning
level need an account. Signing in is a one-time visible `cloakgpt login`. It
needs a graphical desktop or, on a Linux server without one, a VNC web viewer
reached over SSH; see [Sign in on a server without a desktop](#sign-in-on-a-server-without-a-desktop).

A minimal Linux server or container may also lack the shared libraries
CloakBrowser's Chromium needs, which stops the browser from starting even
headless. See [Installation](docs/installation.md#requirements) for the packages.

Python, `pip`, Node.js, and Git are **not** needed to run a packaged release.
Full details, including network and installer tooling, are in
[Installation](docs/installation.md#requirements).

## Install a release

The installers download the executable for the current platform, verify its
SHA-256 checksum, install it for the current user, and then download the
external CloakBrowser binary. If the browser download fails, CloakGPT remains
installed and the completion MOTD prints the browser retry and login commands.
When both components install successfully in an interactive terminal, the
installer automatically opens the visible ChatGPT login flow. Over SSH on a Linux
server without a desktop, that flow is the remote login described below.

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

## Use it

Sign in once, in a visible browser window. Skip this if you only want one-shot
questions on a signed-out profile:

```sh
cloakgpt login
```

Ask a one-shot question. It runs headless and returns Markdown, with a
`## Sources` section when ChatGPT cited anything:

```sh
cloakgpt ask "Summarize the tradeoffs of optimistic locking."
```

Keep a conversation across turns by opening a session once and reusing its ID.
Different session IDs run concurrently through one shared browser:

```sh
SESSION=$(cloakgpt session open)
cloakgpt ask "Explain CRDTs briefly." --session "$SESSION"
cloakgpt ask "Now contrast them with OT." --session "$SESSION"
```

Pick a model or reasoning level only when you mean to; omitting them keeps
whatever the page is already set to:

```sh
cloakgpt ask "Design a rate limiter." --reasoning high --model gpt-5.6-sol
```

Agents should prefer a machine-readable event stream:

```sh
cloakgpt ask "Reply only: OK." --output jsonl
```

### Sign in on a server without a desktop

On Linux without `DISPLAY` or `WAYLAND_DISPLAY`, such as Ubuntu Server or an LXC
container, `cloakgpt login` runs the browser on a temporary virtual display and
serves it through a VNC web viewer bound to `127.0.0.1`. Install a VNC backend
on the server, then run login there:

```sh
sudo apt install tigervnc-standalone-server novnc websockify
cloakgpt login
```

Login prints an SSH tunnel command, such as
`ssh -N -L 6100:127.0.0.1:6100 root@192.168.50.250`, and a viewer address. Run
the tunnel on your own computer, open the address in your browser, and sign in.
The virtual display stops when login finishes; `ask`, sessions, and `serve` stay
headless. Anyone who can open the viewer controls the login, so reach it only
through SSH. KasmVNC, `--remote`/`--local`, and `--port` are covered in
[Remote login](docs/usage.md#remote-login-on-a-headless-server).

### OpenAI-compatible API server

Start a local HTTP server for OpenAI clients such as Cline, Cursor, Open WebUI,
and LangChain:

```sh
cloakgpt serve
```

Configure your client with:

- Base URL: `http://127.0.0.1:8000/v1`
- Model ID: `gpt-5.5` or `gpt-5.6-sol`
- API key: any non-empty value, or the value passed to `--api-key`

Streaming replies start immediately and send keep-alive comments, so clients
with short header timeouts, such as Cline on Node.js, don't give up while the
browser works. Browser progress such as thinking or web search streams as
`delta.reasoning_content`. Follow-up turns in the same client task reuse the
active ChatGPT conversation, and a new task gets a fresh session.

The server listens on `127.0.0.1` by default. `--host 0.0.0.0` shares it with
other devices on your network, and without `--api-key` anyone who can reach it
can send messages through your ChatGPT account, so always set `--api-key` when
binding beyond localhost.

Waiting behavior, the JSONL protocol, concurrency rules, daemon control, server
options, and browser management are documented in [Usage](docs/usage.md).

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

## Security and limitations

CloakGPT is a local, user-level CLI, not a sandbox or an authorization service.
It intentionally drives a signed-in browser profile and can send messages, so
anyone allowed to run it is trusted to operate that profile within the authority
you granted. Session IDs select local conversations; they are not ChatGPT
credentials. The browser profile, daemon metadata, and conversation URLs are
sensitive local data and must not be committed or published.

Full trust boundaries and data locations: [Security model](docs/security-model.md).

CloakGPT is an unofficial browser-automation project. It is not affiliated with
OpenAI, and using it is subject to the terms of the services it automates.
CloakBrowser is a separately downloaded external binary under its own license and
trust boundary. Full text: [Legal](docs/legal.md).

## Documentation

| Page | What it covers |
| --- | --- |
| [Installation](docs/installation.md) | Requirements in full, release channels and assets, updating, uninstalling |
| [Usage](docs/usage.md) | Login and remote login, browser management, waiting and JSONL contracts, sessions, page settings, the API server |
| [Agent setup](docs/agent-setup.md) | Having a coding agent install and verify CloakGPT for you |
| [Security model](docs/security-model.md) | Trust boundaries and where your data lives |
| [Contributing](CONTRIBUTING.md) | Running from source, tests, building |
| [Legal](docs/legal.md) | Full disclaimer |

## License

CloakGPT is available under the [MIT License](LICENSE). Third-party components
and dependencies retain their respective licenses.

