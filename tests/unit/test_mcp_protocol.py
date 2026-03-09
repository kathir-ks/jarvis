"""Unit tests for MCP protocol definitions and server."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarvis.app.mcp.protocol import (
    MCPError,
    MCPMethod,
    MCPRequest,
    MCPResponse,
    ServerInfo,
    ToolCallResult,
)


# ---------------------------------------------------------------------------
# Test: MCPRequest
# ---------------------------------------------------------------------------

class TestMCPRequest:
    """Test MCPRequest dataclass."""

    def test_basic_request(self):
        req = MCPRequest(method="tools/list", id="1")
        assert req.jsonrpc == "2.0"
        assert req.method == "tools/list"
        assert req.id == "1"

    def test_to_dict(self):
        req = MCPRequest(method="ping", params={"key": "val"}, id="2")
        d = req.to_dict()
        assert d["jsonrpc"] == "2.0"
        assert d["method"] == "ping"
        assert d["params"] == {"key": "val"}
        assert d["id"] == "2"

    def test_to_dict_without_optional_fields(self):
        req = MCPRequest(method="ping")
        d = req.to_dict()
        assert "params" not in d
        assert "id" not in d

    def test_is_notification(self):
        notification = MCPRequest(method="notify")
        assert notification.is_notification() is True

        request = MCPRequest(method="call", id="1")
        assert request.is_notification() is False


# ---------------------------------------------------------------------------
# Test: MCPResponse
# ---------------------------------------------------------------------------

class TestMCPResponse:
    """Test MCPResponse dataclass."""

    def test_success_response(self):
        resp = MCPResponse(id="1", result={"tools": []})
        d = resp.to_dict()
        assert d["id"] == "1"
        assert d["result"] == {"tools": []}
        assert "error" not in d

    def test_error_response(self):
        error = MCPError(code=-32601, message="Method not found")
        resp = MCPResponse(id="1", error=error)
        d = resp.to_dict()
        assert d["error"]["code"] == -32601
        assert d["error"]["message"] == "Method not found"

    def test_empty_result_defaults_to_empty_dict(self):
        resp = MCPResponse(id="1")
        d = resp.to_dict()
        assert d["result"] == {}


# ---------------------------------------------------------------------------
# Test: MCPError
# ---------------------------------------------------------------------------

class TestMCPError:
    """Test MCPError codes."""

    def test_standard_error_codes(self):
        assert MCPError.PARSE_ERROR == -32700
        assert MCPError.INVALID_REQUEST == -32600
        assert MCPError.METHOD_NOT_FOUND == -32601
        assert MCPError.INVALID_PARAMS == -32602
        assert MCPError.INTERNAL_ERROR == -32603

    def test_mcp_specific_error_codes(self):
        assert MCPError.TOOL_NOT_FOUND == -32001
        assert MCPError.TOOL_EXECUTION_ERROR == -32002
        assert MCPError.TOOL_TIMEOUT == -32003


# ---------------------------------------------------------------------------
# Test: MCPMethod
# ---------------------------------------------------------------------------

class TestMCPMethod:
    """Test MCPMethod enum values."""

    def test_method_values(self):
        assert MCPMethod.LIST_TOOLS == "tools/list"
        assert MCPMethod.CALL_TOOL == "tools/call"
        assert MCPMethod.GET_SERVER_INFO == "initialize"
        assert MCPMethod.PING == "ping"


# ---------------------------------------------------------------------------
# Test: ServerInfo
# ---------------------------------------------------------------------------

class TestServerInfo:
    """Test ServerInfo dataclass."""

    def test_to_dict(self):
        info = ServerInfo(
            name="jarvis-mcp",
            version="0.1.0",
            capabilities={"tools": {"listChanged": False}},
        )
        d = info.to_dict()
        assert d["serverInfo"]["name"] == "jarvis-mcp"
        assert d["serverInfo"]["version"] == "0.1.0"
        assert d["protocolVersion"] == "2024-11-05"
        assert d["capabilities"]["tools"]["listChanged"] is False


# ---------------------------------------------------------------------------
# Test: ToolCallResult
# ---------------------------------------------------------------------------

class TestToolCallResult:
    """Test ToolCallResult factory methods."""

    def test_success_result(self):
        result = ToolCallResult.success("42")
        assert result.isError is False
        assert result.content[0]["text"] == "42"
        assert result.content[0]["type"] == "text"

    def test_error_result(self):
        result = ToolCallResult.error("Something went wrong")
        assert result.isError is True
        assert result.content[0]["text"] == "Something went wrong"

    def test_success_with_non_string(self):
        result = ToolCallResult.success({"value": 42})
        assert "42" in result.content[0]["text"]
