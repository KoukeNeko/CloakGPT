"""A minimal Model Context Protocol (MCP) server using FastMCP."""

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("example-python-mcp")


@mcp.tool()
def greet(name: str) -> str:
    """Return a friendly greeting for the supplied name."""
    return f"Hello, {name}!"


@mcp.tool()
def add(first: float, second: float) -> float:
    """Add two numbers."""
    return first + second


if __name__ == "__main__":
    mcp.run(transport="stdio")
