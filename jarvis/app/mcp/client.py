"""MCP client for discovering and invoking tools from MCP servers."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .protocol import MCPError, MCPMethod, MCPRequest, MCPResponse

logger = logging.getLogger(__name__)


class MCPClient:
    """Client for interacting with MCP servers (local or remote)."""

    def __init__(self, server_url: str, timeout_seconds: int = 30):
        """
        Initialize MCP client.

        Args:
            server_url: Base URL of the MCP server (e.g., "http://localhost:8000/api/mcp")
            timeout_seconds: Request timeout in seconds
        """
        self.server_url = server_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.client: httpx.AsyncClient | None = None
        self._tools_cache: list[dict[str, Any]] | None = None

    async def __aenter__(self):
        """Context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.close()

    async def connect(self):
        """Establish connection to MCP server."""
        if not self.client:
            self.client = httpx.AsyncClient(timeout=self.timeout_seconds)
            logger.info("MCP client connected to %s", self.server_url)

    async def close(self):
        """Close connection to MCP server."""
        if self.client:
            await self.client.aclose()
            self.client = None
            logger.info("MCP client disconnected")

    async def initialize(self) -> dict[str, Any]:
        """
        Initialize connection with MCP server.

        Returns:
            Server information including capabilities
        """
        request = MCPRequest(
            method=MCPMethod.GET_SERVER_INFO,
            params={"clientVersion": "1.0.0"},
            id="init",
        )

        response = await self._send_request(request)
        return response.result or {}

    async def list_tools(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """
        List all available tools from MCP server.

        Args:
            force_refresh: If True, bypass cache and fetch fresh tool list

        Returns:
            List of tool definitions in OpenAI format
        """
        # Return cached tools if available
        if self._tools_cache is not None and not force_refresh:
            return self._tools_cache

        request = MCPRequest(
            method=MCPMethod.LIST_TOOLS,
            params={},
            id="list",
        )

        response = await self._send_request(request)
        tools = response.result.get("tools", []) if response.result else []

        # Cache the tools
        self._tools_cache = tools
        logger.info("Discovered %d tools from MCP server", len(tools))

        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a tool via MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool execution result

        Raises:
            MCPError: If tool execution fails
        """
        request = MCPRequest(
            method=MCPMethod.CALL_TOOL,
            params={
                "name": name,
                "arguments": arguments,
            },
            id=f"call_{name}",
        )

        response = await self._send_request(request)

        # Check for execution errors
        if response.result and not response.result.get("success", False):
            error_msg = response.result.get("error", "Tool execution failed")
            raise MCPError(code=-32603, message=error_msg)

        return response.result or {}

    async def ping(self) -> bool:
        """
        Ping MCP server to check connectivity.

        Returns:
            True if server is reachable and responsive
        """
        try:
            request = MCPRequest(
                method=MCPMethod.PING,
                params={},
                id="ping",
            )

            response = await self._send_request(request)
            return response.result.get("status") == "ok" if response.result else False

        except Exception as e:
            logger.warning("MCP ping failed: %s", e)
            return False

    async def _send_request(self, request: MCPRequest) -> MCPResponse:
        """
        Send JSON-RPC request to MCP server.

        Args:
            request: MCP request object

        Returns:
            MCP response object

        Raises:
            MCPError: If request fails or server returns error
        """
        if not self.client:
            await self.connect()

        try:
            request_data = request.to_dict()
            logger.debug("MCP request: %s", request_data)

            resp = await self.client.post(self.server_url, json=request_data)
            resp.raise_for_status()
            response_data = resp.json()

            logger.debug("MCP response: %s", response_data)

            # Parse response
            response = MCPResponse.from_dict(response_data)

            # Check for errors
            if response.error:
                raise response.error

            return response

        except httpx.HTTPStatusError as e:
            logger.error("MCP HTTP error: %s", e)
            raise MCPError(
                code=-32603,
                message=f"HTTP request failed: {str(e)}",
            ) from e

        except Exception as e:
            logger.error("MCP request failed: %s", e, exc_info=True)
            raise MCPError(
                code=-32603,
                message=f"Request failed: {str(e)}",
            ) from e

    def get_cached_tools(self) -> list[dict[str, Any]] | None:
        """
        Get cached tool definitions without making a network request.

        Returns:
            Cached tools or None if cache is empty
        """
        return self._tools_cache
