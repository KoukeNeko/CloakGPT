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

## Use it

Sign in once, in a visible browser window:

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
