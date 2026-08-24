# Python Example MCP Server

This is a minimal [Model Context Protocol](https://modelcontextprotocol.io/) server written in Python. It exposes two tools over the standard input/output transport:

- `greet(name: str)` returns a greeting.
- `add(first: float, second: float)` returns the sum of two numbers.
- `get_page_title(url: str, timezone: str)` opens a public URL with
  CloakBrowser and returns its title. Pass the caller's IANA timezone, such as
  `Asia/Taipei`.
- `ask_chatgpt(question: str, timezone: str)` sends a question to ChatGPT via
  the Japanese `質問してみましょう` placeholder and returns its response text. It
  uses a persistent local profile; sign in to your own ChatGPT account before
  using it.

## Setup

Requires Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

```powershell
python server.py
```

The process uses stdio, so it will wait for an MCP client instead of displaying an interactive prompt.

On its first web request, CloakBrowser downloads its Chromium binary (about
200 MB). Use this tool only for URLs you are authorized to access.

`ask_chatgpt` opens a visible browser and sends the supplied text to
`chatgpt.com`. It is fixed to the Japanese interface so the expected input
placeholder is `質問してみましょう`; it will fail if the page is not in that locale
or the account needs to be signed in. The saved browser session is stored in
`chatgpt-profile`.

## Manual ChatGPT integration test

This script sends one prompt and waits for the assistant response. The first
run may require you to sign in in the browser window.

```powershell
.\.venv\Scripts\python.exe manual_test_chatgpt.py "Reply only: OK."
```

## Add it to a client

Configure your MCP client with this command (replace the path with the absolute path to this project):

```json
{
  "mcpServers": {
    "example-python-mcp": {
      "command": "D:\\Documents\\Github\\CloakGPT\\.venv\\Scripts\\python.exe",
      "args": ["D:\\Documents\\Github\\CloakGPT\\server.py"]
    }
  }
}
```
