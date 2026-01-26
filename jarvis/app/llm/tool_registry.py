"""Tool registry with schema definitions and execution."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    """Categories of tools."""
    WEB = "web"
    CODE = "code"
    DATA = "data"
    SYSTEM = "system"
    COMMUNICATION = "communication"


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""
    name: str
    type: str  # "string", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


@dataclass
class ToolDefinition:
    """Complete tool definition with schema."""
    name: str
    description: str
    category: ToolCategory
    parameters: list[ToolParameter] = field(default_factory=list)
    returns: str = "object"
    returns_description: str = ""
    requires_approval: bool = False
    timeout_seconds: int = 30

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_mcp_schema(self) -> dict[str, Any]:
        """Convert to MCP tool format."""
        input_schema = {
            "type": "object",
            "properties": {},
            "required": [],
        }

        for param in self.parameters:
            input_schema["properties"][param.name] = {
                "type": param.type,
                "description": param.description,
            }
            if param.required:
                input_schema["required"].append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": input_schema,
        }


@dataclass
class ToolResult:
    """Result of tool execution."""
    tool_name: str
    success: bool
    result: Any = None
    error: str | None = None
    execution_time_ms: float = 0.0


# Type for tool handler functions
ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class ToolRegistry:
    """Registry of available tools with schema validation and execution."""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
    ) -> None:
        """Register a tool with its definition and handler."""
        self._tools[definition.name] = definition
        self._handlers[definition.name] = handler
        logger.info("Registered tool: %s", definition.name)

    def unregister(self, name: str) -> bool:
        """Unregister a tool. Returns True if found and removed."""
        if name in self._tools:
            del self._tools[name]
            del self._handlers[name]
            logger.info("Unregistered tool: %s", name)
            return True
        return False

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get tool definition by name."""
        return self._tools.get(name)

    def list_tools(self, category: ToolCategory | None = None) -> list[ToolDefinition]:
        """List all registered tools, optionally filtered by category."""
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Get all tools in OpenAI function calling format."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def get_mcp_tools(self) -> list[dict[str, Any]]:
        """Get all tools in MCP format."""
        return [tool.to_mcp_schema() for tool in self._tools.values()]

    async def execute(
        self,
        tool_name: str,
        params: dict[str, Any],
        timeout: float | None = None,
    ) -> ToolResult:
        """Execute a registered tool with timeout handling."""
        import time
        start_time = time.perf_counter()

        if tool_name not in self._tools:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool '{tool_name}' not registered",
            )

        definition = self._tools[tool_name]
        handler = self._handlers[tool_name]

        # Validate required parameters
        for param in definition.parameters:
            if param.required and param.name not in params:
                return ToolResult(
                    tool_name=tool_name,
                    success=False,
                    error=f"Missing required parameter: {param.name}",
                )

        # Apply defaults
        for param in definition.parameters:
            if param.name not in params and param.default is not None:
                params[param.name] = param.default

        # Execute with timeout
        effective_timeout = timeout or definition.timeout_seconds

        try:
            result = await asyncio.wait_for(
                handler(params),
                timeout=effective_timeout,
            )
            execution_time = (time.perf_counter() - start_time) * 1000

            return ToolResult(
                tool_name=tool_name,
                success=True,
                result=result,
                execution_time_ms=execution_time,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool execution timed out after {effective_timeout}s",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:
            logger.error("Tool %s execution failed: %s", tool_name, e, exc_info=True)
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=str(e),
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )


# Singleton instance
_tool_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get or create the singleton tool registry."""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry
