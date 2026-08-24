# CloakGPT

CloakGPT automates a user-owned ChatGPT browser session with CloakBrowser.
The browser core can start a conversation, continue the last conversation,
and return the assistant's response text.

The MCP server has been removed. A command-line interface will be the public
entry point.

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
