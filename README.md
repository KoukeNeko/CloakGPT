# Python Example MCP Server

This is a minimal [Model Context Protocol](https://modelcontextprotocol.io/) server written in Python. It exposes two tools over the standard input/output transport:

- `greet(name: str)` returns a greeting.
- `add(first: float, second: float)` returns the sum of two numbers.

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
