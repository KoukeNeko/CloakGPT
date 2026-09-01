<img width="1774" height="887" alt="image" src="https://github.com/user-attachments/assets/af353f4c-b3f2-4924-ab12-793927f9bbbb" />

# CloakGPT

[![CI](https://github.com/KoukeNeko/CloakGPT/actions/workflows/ci.yml/badge.svg)](https://github.com/KoukeNeko/CloakGPT/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/KoukeNeko/CloakGPT)](https://github.com/KoukeNeko/CloakGPT/releases/latest)
[![License](https://img.shields.io/github/license/KoukeNeko/CloakGPT)](LICENSE)

**Use your own ChatGPT browser session from the terminal.**

CloakGPT is a local CLI that drives ChatGPT through CloakBrowser. **It does not
use the OpenAI API** — it operates the account you are already signed in to.

- Persistent multi-turn conversations you can return to
- Independent sessions running concurrently in one shared browser
- Model and reasoning-level selection, or leave the page as it is
- Markdown answers with their citation sources
- A portable Agent Skill so coding agents can drive it safely

## Requirements

- 64-bit Linux, macOS, or Windows
- Permission to download and run [CloakBrowser](https://cloakbrowser.dev/), an
  external binary under its own license
- About 500 MB of free space

A ChatGPT account is recommended rather than required. A one-shot `ask` works on
a signed-out profile; persistent sessions and choosing a model or reasoning
level need an account. Signing in is a one-time visible `cloakgpt login`, so
that step needs a graphical desktop.

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

Waiting behavior, the JSONL protocol, concurrency rules, daemon control, and
browser management are documented in [Usage](docs/usage.md).

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
| [Usage](docs/usage.md) | Login, browser management, waiting and JSONL contracts, sessions, page settings |
| [Agent setup](docs/agent-setup.md) | Having a coding agent install and verify CloakGPT for you |
| [Security model](docs/security-model.md) | Trust boundaries and where your data lives |
| [Contributing](CONTRIBUTING.md) | Running from source, tests, building |
| [Legal](docs/legal.md) | Full disclaimer |

## License

CloakGPT is available under the [MIT License](LICENSE). Third-party components
and dependencies retain their respective licenses.

