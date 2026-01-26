"""MCP protocol message definitions.

Based on JSON-RPC 2.0 with MCP-specific extensions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from enum import Enum


class MCPMethod(str, Enum):
    """MCP protocol methods."""

    # Tool discovery
    LIST_TOOLS = "tools/list"

    # Tool execution
    CALL_TOOL = "tools/call"

    # Server info
    GET_SERVER_INFO = "initialize"

    # Health check
    PING = "ping"


@dataclass
class MCPRequest:
    """MCP request message following JSON-RPC 2.0 format."""

    jsonrpc: str = "2.0"
    method: str = ""
    params: dict[str, Any] | None = None
    id: str | int | None = None  # None for notifications

    def is_notification(self) -> bool:
        """Check if this is a notification (no response expected)."""
        return self.id is None

    def to_dict(self) -> dict[str, Any]:
        """Convert request to dictionary."""
        req = {
            "jsonrpc": self.jsonrpc,
            "method": self.method,
        }

        if self.params is not None:
            req["params"] = self.params

        if self.id is not None:
            req["id"] = self.id

        return req


@dataclass
class MCPError:
    """MCP error object."""

    code: int
    message: str
    data: dict[str, Any] | None = None

    # Standard JSON-RPC error codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # MCP-specific error codes
    TOOL_NOT_FOUND = -32001
    TOOL_EXECUTION_ERROR = -32002
    TOOL_TIMEOUT = -32003


@dataclass
class MCPResponse:
    """MCP response message following JSON-RPC 2.0 format."""

    jsonrpc: str = "2.0"
    id: str | int | None = None
    result: dict[str, Any] | None = None
    error: MCPError | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert response to dictionary."""
        resp = {"jsonrpc": self.jsonrpc}

        if self.id is not None:
            resp["id"] = self.id

        if self.error:
            resp["error"] = {
                "code": self.error.code,
                "message": self.error.message,
            }
            if self.error.data:
                resp["error"]["data"] = self.error.data
        else:
            resp["result"] = self.result or {}

        return resp


@dataclass
class ToolListResult:
    """Result for tools/list method."""

    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ToolCallParams:
    """Parameters for tools/call method."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallResult:
    """Result for tools/call method."""

    content: list[dict[str, Any]] = field(default_factory=list)
    isError: bool = False

    @classmethod
    def success(cls, result: Any) -> ToolCallResult:
        """Create a success result."""
        return cls(
            content=[{
                "type": "text",
                "text": str(result) if not isinstance(result, str) else result,
            }],
            isError=False,
        )

    @classmethod
    def error(cls, error_msg: str) -> ToolCallResult:
        """Create an error result."""
        return cls(
            content=[{
                "type": "text",
                "text": error_msg,
            }],
            isError=True,
        )


@dataclass
class ServerInfo:
    """Server information returned by initialize method."""

    name: str
    version: str
    protocolVersion: str = "2024-11-05"
    capabilities: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "protocolVersion": self.protocolVersion,
            "serverInfo": {
                "name": self.name,
                "version": self.version,
            },
            "capabilities": self.capabilities,
        }
