"""Tool registry stub."""
from typing import Callable


class ToolRegistry:
    """Registry of available tools."""

    def __init__(self):
        self.tools: dict[str, Callable] = {}

    def register(self, name: str, handler: Callable) -> None:
        """Register a tool handler."""
        self.tools[name] = handler

    async def execute(self, tool_name: str, params: dict) -> dict:
        """Execute a registered tool."""
        if tool_name not in self.tools:
            raise ValueError(f"Tool {tool_name} not registered")
        handler = self.tools[tool_name]
        return await handler(params)
