"""MCP Server implementation for Jarvis.

Exposes tools via the Model Context Protocol, allowing external clients
to discover and invoke Jarvis tools in a standardized way.
"""
from __future__ import annotations

import logging
import json
from typing import Any

from .protocol import (
    MCPRequest,
    MCPResponse,
    MCPError,
    MCPMethod,
    ToolListResult,
    ToolCallParams,
    ToolCallResult,
    ServerInfo,
)
from ..llm.tool_registry import get_tool_registry, ToolRegistry

logger = logging.getLogger(__name__)


class MCPServer:
    """MCP protocol server for tool discovery and execution."""

    def __init__(self, name: str = "jarvis-mcp-server", version: str = "0.1.0"):
        """Initialize MCP server.

        Args:
            name: Server name
            version: Server version
        """
        self.name = name
        self.version = version
        self.tool_registry: ToolRegistry = get_tool_registry()
        self.initialized = False

        logger.info("MCP Server initialized: %s v%s", name, version)

    async def handle_request(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """Handle an MCP request and return a response.

        Args:
            request_data: Raw request dictionary

        Returns:
            Response dictionary
        """
        try:
            # Parse request
            request = self._parse_request(request_data)

            # Handle request
            if request.method == MCPMethod.GET_SERVER_INFO:
                result = await self._handle_initialize(request)
            elif request.method == MCPMethod.LIST_TOOLS:
                result = await self._handle_list_tools(request)
            elif request.method == MCPMethod.CALL_TOOL:
                result = await self._handle_call_tool(request)
            elif request.method == MCPMethod.PING:
                result = await self._handle_ping(request)
            else:
                # Method not found
                return MCPResponse(
                    id=request.id,
                    error=MCPError(
                        code=MCPError.METHOD_NOT_FOUND,
                        message=f"Method not found: {request.method}",
                    ),
                ).to_dict()

            # Build response
            response = MCPResponse(id=request.id, result=result)
            return response.to_dict()

        except ValueError as e:
            logger.error("Invalid request: %s", e)
            return MCPResponse(
                error=MCPError(
                    code=MCPError.INVALID_REQUEST,
                    message=str(e),
                ),
            ).to_dict()
        except Exception as e:
            logger.exception("Error handling MCP request: %s", e)
            return MCPResponse(
                error=MCPError(
                    code=MCPError.INTERNAL_ERROR,
                    message=f"Internal server error: {str(e)}",
                ),
            ).to_dict()

    def _parse_request(self, data: dict[str, Any]) -> MCPRequest:
        """Parse and validate an MCP request.

        Args:
            data: Raw request data

        Returns:
            Parsed MCPRequest

        Raises:
            ValueError: If request is invalid
        """
        if data.get("jsonrpc") != "2.0":
            raise ValueError("Invalid JSON-RPC version")

        method = data.get("method")
        if not method:
            raise ValueError("Missing method field")

        return MCPRequest(
            jsonrpc="2.0",
            method=method,
            params=data.get("params"),
            id=data.get("id"),
        )

    async def _handle_initialize(self, request: MCPRequest) -> dict[str, Any]:
        """Handle initialize request.

        Returns server information and capabilities.
        """
        self.initialized = True

        server_info = ServerInfo(
            name=self.name,
            version=self.version,
            capabilities={
                "tools": {
                    "listChanged": False,  # Tools don't change dynamically
                },
            },
        )

        logger.info("MCP server initialized")
        return server_info.to_dict()

    async def _handle_list_tools(self, request: MCPRequest) -> dict[str, Any]:
        """Handle tools/list request.

        Returns list of available tools in MCP format.
        """
        tools = self.tool_registry.list_tools()

        # Convert to MCP tool format
        mcp_tools = []
        for tool in tools:
            mcp_tool = {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            }

            # Build input schema from tool parameters
            for param in tool.parameters:
                prop_schema = {
                    "type": param.type,
                    "description": param.description,
                }

                if param.enum:
                    prop_schema["enum"] = param.enum

                if param.default is not None:
                    prop_schema["default"] = param.default

                mcp_tool["inputSchema"]["properties"][param.name] = prop_schema

                if param.required:
                    mcp_tool["inputSchema"]["required"].append(param.name)

            mcp_tools.append(mcp_tool)

        logger.info("Listed %d tools via MCP", len(mcp_tools))
        return {"tools": mcp_tools}

    async def _handle_call_tool(self, request: MCPRequest) -> dict[str, Any]:
        """Handle tools/call request.

        Executes a tool and returns the result.
        """
        if not request.params:
            raise ValueError("Missing parameters for tools/call")

        # Parse parameters
        tool_name = request.params.get("name")
        if not tool_name:
            raise ValueError("Missing tool name")

        tool_args = request.params.get("arguments", {})

        logger.info("MCP tool call: %s with args %s", tool_name, tool_args)

        # Execute tool
        try:
            result = await self.tool_registry.execute(tool_name, tool_args)

            if result.success:
                # Format successful result
                result_content = result.result
                if isinstance(result_content, dict):
                    result_text = json.dumps(result_content, indent=2)
                else:
                    result_text = str(result_content)

                return {
                    "content": [
                        {
                            "type": "text",
                            "text": result_text,
                        }
                    ],
                    "isError": False,
                }
            else:
                # Format error result
                error_msg = result.error or "Unknown error"
                logger.error("Tool execution failed: %s", error_msg)

                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: {error_msg}",
                        }
                    ],
                    "isError": True,
                }

        except Exception as e:
            logger.exception("Error executing tool %s: %s", tool_name, e)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Tool execution error: {str(e)}",
                    }
                ],
                "isError": True,
            }

    async def _handle_ping(self, request: MCPRequest) -> dict[str, Any]:
        """Handle ping request for health checks."""
        return {"status": "ok", "timestamp": ""}

    def get_tool_manifest(self) -> dict[str, Any]:
        """Get the complete tool manifest for MCP clients.

        Returns:
            Dictionary containing all tool definitions
        """
        tools = self.tool_registry.list_tools()

        manifest = {
            "server": {
                "name": self.name,
                "version": self.version,
            },
            "tools": [],
        }

        for tool in tools:
            tool_def = {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category.value,
                "parameters": [
                    {
                        "name": p.name,
                        "type": p.type,
                        "description": p.description,
                        "required": p.required,
                        "default": p.default,
                        "enum": p.enum,
                    }
                    for p in tool.parameters
                ],
            }
            manifest["tools"].append(tool_def)

        return manifest
