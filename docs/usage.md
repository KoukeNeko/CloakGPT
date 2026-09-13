# Usage

Full reference for driving CloakGPT from a terminal or an agent: signing in,
managing the external browser, one-shot questions, persistent sessions, and
page settings. The README shows the short version of each.

## Login

Open the persistent browser profile and sign in to your own ChatGPT account:

```sh
cloakgpt login
```

CloakGPT saves the session and closes the browser once the sign-in completes.
You can also press Enter in the terminal to finish earlier, or close the browser
window. If the profile is already signed in, for example when you open it to
switch accounts, the browser stays open until you press Enter.

The default user timezone is `Asia/Taipei`. Override it with an IANA timezone:

```sh
cloakgpt login --timezone America/New_York
```

### Remote login on a headless server

On Linux without a desktop (no `DISPLAY` or `WAYLAND_DISPLAY`), such as Ubuntu
Server or an LXC container, `login` runs the browser in a temporary virtual
display. You reach that display through a web viewer on your own computer. Only
the login uses it: afterwards `ask`, sessions, and `serve` run headless as usual
and use the same profile.

Install one VNC backend on the server first. TigerVNC with noVNC comes from the
distribution's packages:

```sh
sudo apt install tigervnc-standalone-server novnc websockify
```

KasmVNC also works; install its package from the
[KasmVNC releases](https://github.com/kasmtech/KasmVNC/releases). When both are
installed, TigerVNC is used unless you pass `--vnc kasmvnc`.

Run `login` on the server. It prints an SSH tunnel command and a viewer address:

```text
$ cloakgpt login
Remote ChatGPT login is ready (tigervnc, display :100).

On your own computer, open an SSH tunnel:
  ssh -N -L 6100:127.0.0.1:6100 root@192.168.50.250
Then open this address in your browser:
  http://127.0.0.1:6100/vnc.html?autoconnect=1&resize=remote
```

Run the tunnel command on your own computer, open the address, and sign in inside
the browser you see there. The viewer listens only on the server's `127.0.0.1`,
so the SSH tunnel is the only way to reach it. The virtual display and viewer stop
when login finishes, when you press Ctrl+C, or when the SSH session drops.

To have every SSH connection open the tunnel, add a `LocalForward` to
`~/.ssh/config` on your computer:

```sshconfig
Host cloakgpt
    HostName 192.168.50.250
    User root
    LocalForward 6100 127.0.0.1:6100
```

VS Code Remote-SSH users can instead forward the port from the **Ports** panel.

| Option | Effect |
| --- | --- |
| `--remote` | Use the web viewer even when a desktop is detected. |
| `--local` | Always open a window on this machine's desktop. |
| `--vnc auto\|tigervnc\|kasmvnc` | Choose the VNC backend (default `auto`). |
| `--port N` | Use this viewer port on `127.0.0.1` instead of the first free port from 6100. Keep it the same as the port in your tunnel. |

Anyone who can open the viewer controls the browser and your ChatGPT login. The
viewer has no password of its own, so only SSH protects it. On a server shared
with other accounts, those accounts can also reach `127.0.0.1` while login is
running. Never expose the viewer port on a public interface. See
[Security model](security-model.md#remote-login).

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
depends on the model and prompt. Completion is detected from ChatGPT's
assistant-turn state: the turn must stop generating and show its copy control;
press Ctrl+C to stop manually. Stopping
disconnects the client, and the daemon cancels the request it was waiting on and
closes that browser page rather than finishing work nobody is reading. The
message may already have reached ChatGPT, so check the conversation before
resending it.

What is bounded is inactivity. Growing response text or a changed activity label
restarts a 15-minute stall window, so a long generation is never interrupted,
while a page that goes completely inert reports an unknown delivery state and
releases its browser page instead of pinning the daemon's browser open. Set
`CLOAKGPT_RESPONSE_STALL_SECONDS` to another number of seconds, or to `0` to
wait indefinitely.

ChatGPT sometimes loses a long reply, most often one that searches the web for
many minutes. Its page then shows a notice where the answer should be, such as
`接続が中断されました。回答の完了を待っています`, or
`メッセージ配信がタイムアウトしました。もう一度お試しください。` beside a retry
button. While ChatGPT still shows its stop button next to such a notice, it is
retrying on its own and CloakGPT keeps waiting. Once ChatGPT stops retrying,
CloakGPT reports an error that quotes the notice and names the conversation,
instead of returning the notice as the answer. The prompt already reached
ChatGPT, so check that conversation before resending. If a long research prompt
keeps failing this way, ask smaller questions.

Use `--headed` when you want to observe or debug the browser window:

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

`login` always uses a visible browser, either a local window or the
[remote login](#remote-login-on-a-headless-server) viewer, so authentication
can be completed interactively.

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

## OpenAI-compatible API server

Run a local OpenAI-compatible HTTP API server to connect external coding tools
like Cline, Cursor, Open WebUI, and LangChain to your ChatGPT browser session:

```sh
cloakgpt serve
```

### CLI Options

| Flag | Default | Description |
| --- | --- | --- |
| `--host HOST` | `127.0.0.1` | Network interface to bind (use `0.0.0.0` for LAN access) |
| `--port PORT` | `8000` | Port to listen on |
| `--api-key KEY` | None | Require Bearer token authentication (`Authorization: Bearer <KEY>`) |
| `--session ID` | None | Pin all requests to a persistent session ID |
| `--stateless` | Disabled | Force `send_once` on every request instead of smart session continuity |
| `--model MODEL` | Default | Override default ChatGPT model (`gpt-5.5`, `gpt-5.6-sol`, etc.) |
| `--reasoning LEVEL` | Default | Override default reasoning effort (`fast`, `medium`, `high`) |
| `--headed` | Headless | Display the browser window during automation |
| `--timezone TZ` | `Asia/Taipei` | IANA timezone for the browser environment |

### Client Configuration (e.g. Cline)

In your tool's OpenAI-compatible settings:
- **API Provider**: `OpenAI Compatible`
- **Base URL**: `http://127.0.0.1:8000/v1` (or `http://<LAN-IP>:8000/v1`)
- **API Key**: any non-empty string (or your `--api-key` value)
- **Model ID**: `gpt-5.5` or `gpt-5.6-sol`

### Key Capabilities

1. **Anti-Timeout Fast SSE Handshake**: Sends `HTTP 200` and initial role chunk in under 100ms, accompanied by periodic `: keep-alive` comments to prevent Node.js / `undici` client connect timeouts (10s limit).
2. **Real-time Thinking Streaming**: Browser progress updates (e.g., `ChatGPT activity: 思考中...`, web search) stream as `delta.reasoning_content` chunks into Cline's Thinking dropdown.
3. **Smart Session Continuity**: Reuses the active ChatGPT tab for follow-up turns in the same task and incrementally inputs only new messages, saving 10-15s per turn. Starting a new task in Cline automatically isolates into a fresh session.
