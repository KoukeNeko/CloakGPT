---
name: use-cloakgpt
description: Use the local CloakGPT CLI to ask ChatGPT through the user's signed-in browser session or continue its most recently saved conversation. Apply when the user explicitly wants an agent to send a prompt to ChatGPT, preserve ChatGPT model/reasoning settings, select supported settings, or return ChatGPT's Markdown answer and cited sources; do not use for ordinary questions that the agent can answer directly.
---

# Use CloakGPT

Use CloakGPT as a user-authorized browser client. Sending a prompt changes an
external ChatGPT conversation, so submit only messages the user requested.

## Choose the operation

- For repeated messages in one agent task, run `cloakgpt session open` once,
  capture the session ID from stdout, and retain it for later turns. The MOTD and
  status are on stderr.
- Send every persistent turn with `cloakgpt ask <question> --session <ID>`.
  The first message creates a ChatGPT conversation; later messages continue on
  the same live page. Do not use `continue` with a persistent session.
- Use `cloakgpt ask <question>` without a session for a one-shot new
  conversation.
- Use `cloakgpt continue <question>` without a session only for the legacy most
  recently saved one-shot conversation.
- Do not silently substitute `ask` for a failed `continue`; explain that no saved
  conversation is available and let the user decide whether to start one.
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
- Read progress from stderr and the completed answer from stdout. Do not return
  `[status]` lines as part of the answer.
- Preserve the returned Markdown. When the answer contains `## Sources`, retain
  those links and do not invent, rewrite, or remove citations.
- Report a nonzero exit and its concise error instead of presenting partial
  output as a completed ChatGPT answer.

## Recover from setup and session failures

Use the least invasive recovery step:

1. If the browser binary is missing, run `cloakgpt browser install`.
2. If installation still fails, inspect with `cloakgpt browser info --quick` or
   `cloakgpt browser doctor`, then report the diagnostic and any named
   environment variable. Do not guess credentials or license values.
3. If ChatGPT requires authentication, ask the user to complete
   `cloakgpt login` in its visible browser window. A running daemon owns the same
   profile, so obtain permission to stop it first; stopping preserves session
   IDs and conversation URLs. Never enter, request, or expose their ChatGPT
   password, cookies, or session tokens.
4. For a headless page-state failure, retry once with `--headed` only when a
   visible diagnostic run is acceptable. Persistent sessions require stopping
   the daemon before changing browser mode; do not stop it without permission.

Do not run `browser clear-cache`, log out, delete the profile, or overwrite
`CLOAKGPT_DATA_DIR` unless the user explicitly requests that destructive state
change. Do not commit or display browser profiles, conversation state, cookies,
signing material, or secret environment variables.
