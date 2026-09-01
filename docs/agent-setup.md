# Agent setup

How to have a coding agent install and verify CloakGPT for a user, from a
machine where it is not installed yet. Once CloakGPT is installed and the
`use-cloakgpt` skill is loaded, the skill itself is what tells an agent how to
operate it; this page covers only the bootstrap that happens before that.

See also: [Installation](installation.md) for doing the same thing by hand.

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
   password, cookies, or session tokens. An idle CloakGPT daemon does not hold
   the profile. If login reports that the profile is in use, inspect daemon
   status and ask permission before stopping an active request; stopping
   preserves session IDs and conversation URLs.
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
