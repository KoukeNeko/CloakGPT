---
name: use-cloakgpt
description: Use, update, or completely uninstall CloakGPT when the user asks an agent to operate their signed-in ChatGPT browser session, manage persistent conversations or page settings, preserve returned Markdown and sources, update the packaged CLI, or remove CloakGPT data; not for ordinary questions the agent can answer directly.
---

# Use CloakGPT

Use CloakGPT as a user-authorized browser client. Sending a prompt changes an
external ChatGPT conversation, so submit only messages the user requested.

## Choose the operation

- For repeated messages in one agent task, run `cloakgpt session open` once,
  capture the session ID from stdout, and retain it for later turns. The MOTD and
  status are on stderr.
- Send every persistent turn with `cloakgpt ask <question> --session <ID>`.
  The first message creates a ChatGPT conversation; later messages reuse the
  same live page.
- Use `cloakgpt ask <question>` without a session for a one-shot new
  conversation.
- Prefer the installed `cloakgpt` command. In a source checkout where it is not
  installed, use that checkout's virtual-environment Python with `cloakgpt.py`.
- Pass the question as one argument. Use the shell's safe argument quoting; do
  not interpolate the question into executable shell syntax.

## Preserve page settings by default

Omit `--model` and `--reasoning` unless the user explicitly requests them.
Omission preserves ChatGPT's current page settings.

Supported model values are:

- `gpt-5.6-sol`
- `gpt-5.5`
- `o3`

Supported reasoning values are:

- `fast`
- `medium`
- `high`

Pass `--timezone <IANA timezone>` when the user's timezone is known and needs to
be explicit. Do not guess a timezone. The CLI's configured default applies when
the option is omitted.

Examples:

```sh
cloakgpt ask "Summarize the tradeoffs."
cloakgpt session open
cloakgpt ask "Now give me a concrete example." --session SESSION_ID --reasoning high
cloakgpt ask "What is the weather today?" --timezone Asia/Taipei
```

## Run and collect the response

- Keep the default headless mode for normal work. For a persistent session, add
  `--headed` only to `session open`; browser mode cannot change while its daemon
  is running.
- Reuse one session ID throughout the same agent task. Do not open multiple
  sessions speculatively or stop the shared daemon.
- A two-hour idle lease closes a warm page but preserves its session and
  conversation URL. The next message restores it. Do not present restoration as
  the exact same live page after the lease expired.
- Do not impose an arbitrary response timeout. ChatGPT generation and web search
  can take an unknown amount of time. Keep waiting while the process reports
  progress; stop with Ctrl+C only at the user's request or when cancellation is
  otherwise required.
- In ordinary text mode, read progress from stderr and the completed answer
  from stdout. Do not return `[status]` lines as part of the answer.
- For agent-driven calls, prefer `cloakgpt ask ... --output jsonl`. Every status
  callback is immediately flushed as one stdout line. Parse every JSON line by
  `type`: surface or retain each `status.message` in order, use only
  `result.answer` as the completed response, and treat `error.message` plus the
  nonzero exit as failure. When the runtime has a line-oriented stdout monitor,
  run the command through it; Claude Code's Monitor is one example. If such a
  monitor is unavailable, run the command in the foreground and keep waiting
  instead of assuming that changing streams can force the runtime UI to update.
- Preserve the returned Markdown. When the answer contains `## Sources`, retain
  those links and do not invent, rewrite, or remove citations.
- Report a nonzero exit and its concise error instead of presenting partial
  output as a completed ChatGPT answer.

## Recover from setup and session failures

Use the least invasive recovery step:

1. If the `cloakgpt` command is missing, tell the user to install CloakGPT from
   its official repository. Do not download an executable from another source.
2. If the browser binary is missing, run `cloakgpt browser install`.
3. If installation still fails, inspect with `cloakgpt browser info --quick` or
   `cloakgpt browser doctor`, then report the diagnostic and any named
   environment variable. Do not guess credentials or license values.
4. If ChatGPT requires authentication, ask the user to complete
   `cloakgpt login` in its visible browser window. A running daemon owns the same
   profile, so obtain permission to stop it first; stopping preserves session
   IDs and conversation URLs. Never enter, request, or expose their ChatGPT
   password, cookies, or session tokens.
5. If CloakGPT says the browser profile is already in use, or an older build
   dumps a Chromium error ending in `exitCode=21`, run `cloakgpt daemon status`.
   Reuse the known session ID if that daemon owns the intended conversation;
   otherwise obtain permission before stopping it. If no daemon is running,
   ask the user to close the CloakGPT Chromium window. Do not delete profile
   lock files or terminate unrelated Chrome processes.
6. For a headless page-state failure, retry once with `--headed` only when a
   visible diagnostic run is acceptable. Persistent sessions require stopping
   the daemon before changing browser mode; do not stop it without permission.

## Update CloakGPT

Checking is read-only and may be done when the installed version matters:

```sh
cloakgpt --version
cloakgpt update --check --json
```

Install an update only when the user requested it or approved the mutation.
`cloakgpt update` preserves the current build's stable or prerelease channel.
Use `--channel stable`, `--channel prerelease`, or `--version TAG` only when the
user selected that target; `--channel` and `--version` are mutually exclusive.

An actual update verifies the downloaded release, stops the daemon, and
preserves the browser profile and persistent session records. Tell the user if
stopping an active daemon will close a warm browser page. On Windows, the
command stages a hidden updater and replacement finishes just after the command
exits. Verify the result with `cloakgpt --version`; if it still reports the old
version, retry briefly for up to 10 seconds and report any update failure shown
by the next invocation.

Self-update works only for packaged releases. If a source checkout refuses it,
do not overwrite files or run `git pull` across uncommitted changes; report the
checkout and update it through its normal Git workflow when authorized.
CloakBrowser is separate. Run `cloakgpt browser update` only when the user also
requested a browser update or a diagnosed compatibility problem requires it.

## Completely uninstall CloakGPT

Run a complete uninstall only when the user explicitly requests it. If they
have not already confirmed the destructive scope, explain that it permanently
deletes the ChatGPT browser profile and cookies, conversation/session state,
CloakBrowser downloads and cached license data, the executable, and all
installed `use-cloakgpt` skill copies, then obtain confirmation.

Use the official script from the CloakGPT repository. In a non-interactive
agent terminal, add the confirmation flag only after the user has approved the
complete removal.

Linux and macOS:

```sh
curl -fsSLO https://raw.githubusercontent.com/KoukeNeko/CloakGPT/main/scripts/uninstall.sh
sh uninstall.sh --yes
rm uninstall.sh
```

Windows:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/KoukeNeko/CloakGPT/main/scripts/uninstall.ps1 -OutFile uninstall.ps1
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -Yes
Remove-Item .\uninstall.ps1
```

The script stops the daemon, uses the Agent Skills CLI when available, removes
known skill paths as a fallback, and honors the documented CloakGPT directory
environment overrides. Report any safety refusal or skill-removal warning; do
not claim a complete uninstall while one remains. Because the current skill is
deleted during the operation, finish verification from these already-loaded
instructions and tell the user to restart their agent so its in-memory skill
list is refreshed.

Do not run `browser clear-cache`, log out, delete the profile, or overwrite
`CLOAKGPT_DATA_DIR` unless the user explicitly requests that destructive state
change. Do not commit or display browser profiles, conversation state, cookies,
signing material, or secret environment variables.
