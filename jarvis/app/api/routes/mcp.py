"""MCP API routes for external tool access."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ...mcp.server import MCPServer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["MCP"])

# Global MCP server instance
_mcp_server: MCPServer | None = None


def get_mcp_server() -> MCPServer:
    """Get or create the MCP server instance."""
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPServer(name="jarvis-mcp-server", version="0.1.0")
    return _mcp_server


@router.post("/")
async def handle_mcp_request(request: Request) -> JSONResponse:
    """Handle MCP JSON-RPC requests.

    This endpoint accepts JSON-RPC 2.0 formatted requests following the MCP protocol.

    Example request:
    ```json
    {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 1
    }
    ```

    Args:
        request: FastAPI request object

    Returns:
        JSON-RPC response
    """
    try:
        # Parse request body
        request_data = await request.json()

        # Get MCP server
        mcp_server = get_mcp_server()

        # Handle request
        response_data = await mcp_server.handle_request(request_data)

        return JSONResponse(content=response_data)

    except ValueError as e:
        logger.error("Invalid JSON in MCP request: %s", e)
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "error": {
                    "code": -32700,
                    "message": "Parse error",
                },
            },
            status_code=400,
        )
    except Exception as e:
        logger.exception("Error processing MCP request: %s", e)
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                },
            },
            status_code=500,
        )


@router.get("/manifest")
async def get_tool_manifest() -> dict[str, Any]:
    """Get the complete tool manifest.

    Returns all available tools with their schemas in a single response.
    Useful for clients that want to understand all capabilities at once.

    Returns:
        Tool manifest dictionary
    """
    try:
        mcp_server = get_mcp_server()
        manifest = mcp_server.get_tool_manifest()
        return manifest
    except Exception as e:
        logger.exception("Error getting tool manifest: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for MCP server.

    Returns:
        Health status
    """
    return {
        "status": "ok",
        "service": "mcp-server",
    }
