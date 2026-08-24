# CloakGPT

CloakGPT automates a user-owned ChatGPT browser session with CloakBrowser.
The CLI can start a conversation, continue the last conversation, select an
available reasoning level, and print the assistant's response text.

## Setup

Requires Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

CloakBrowser downloads its Chromium binary on first use. The browser profile
is stored in `chatgpt-profile`, and the last conversation URL is stored in
`.chatgpt-conversation-url`; both are excluded from Git.

## Login

Open the persistent browser profile, sign in to your own ChatGPT account, then
return to the terminal and press Enter:

```powershell
.\.venv\Scripts\python.exe cloakgpt.py login
```

The default user timezone is `Asia/Taipei`. Override it with an IANA timezone:

```powershell
.\.venv\Scripts\python.exe cloakgpt.py login --timezone America/New_York
```

## Start a conversation

```powershell
.\.venv\Scripts\python.exe cloakgpt.py ask "Reply only: OK."
```

The command opens a visible browser, sends the message, waits for the response
to finish, prints the response text, and saves the conversation URL.

## Continue the conversation

```powershell
.\.venv\Scripts\python.exe cloakgpt.py continue "Explain your answer."
```

This reopens the conversation saved by the most recent `ask` command.

## Select a reasoning level

Use `--reasoning` with either `ask` or `continue`:

```powershell
.\.venv\Scripts\python.exe cloakgpt.py ask "Solve this carefully." --reasoning high
```

Supported CLI values map to the three reasoning options currently exposed by
the advanced composer menu:

| CLI value | ChatGPT label |
| --- | --- |
| `fast` | 最速 |
| `medium` | 中程度 |
| `high` | 高い |

Omit `--reasoning` to keep ChatGPT's current selection. Availability depends
on the signed-in account's plan and workspace settings. If a requested level
is unavailable, the CLI reports the visible model menu instead of changing a
private ChatGPT API.

Other options:

```text
--timezone IANA_NAME   User's timezone; default: Asia/Taipei
--timeout SECONDS      Maximum UI/response wait; default: 120
```

## Tests

The tests mock the browser and do not send messages to ChatGPT:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Use the automation only with an account and websites you are authorized to
access, and follow the applicable service terms.
