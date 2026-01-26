"""Test MCP Server implementation."""
import asyncio
import json
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jarvis.app.mcp.server import MCPServer
from jarvis.app.llm.tools.init_tools import initialize_tools

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def test_mcp_server():
    """Test MCP server functionality."""
    logger.info("=" * 70)
    logger.info("MCP Server Test Suite")
    logger.info("=" * 70)

    # Initialize tools first
    logger.info("\nInitializing tools...")
    initialize_tools()

    # Create MCP server
    logger.info("\nCreating MCP server...")
    mcp_server = MCPServer(name="jarvis-test-mcp", version="0.1.0")

    # Test 1: Initialize
    logger.info("\n" + "=" * 70)
    logger.info("Test 1: Server Initialization")
    logger.info("=" * 70)

    init_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0",
            },
        },
        "id": 1,
    }

    init_response = await mcp_server.handle_request(init_request)
    logger.info("Initialize response:")
    logger.info(json.dumps(init_response, indent=2))

    if "error" in init_response:
        logger.error("✗ Initialization failed: %s", init_response["error"])
        return False
    else:
        logger.info("✓ Server initialized successfully")

    # Test 2: List Tools
    logger.info("\n" + "=" * 70)
    logger.info("Test 2: List Tools")
    logger.info("=" * 70)

    list_tools_request = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 2,
    }

    list_response = await mcp_server.handle_request(list_tools_request)
    logger.info("List tools response:")
    logger.info(json.dumps(list_response, indent=2))

    if "error" in list_response:
        logger.error("✗ List tools failed: %s", list_response["error"])
        return False
    else:
        tools = list_response.get("result", {}).get("tools", [])
        logger.info("✓ Listed %d tools:", len(tools))
        for tool in tools:
            logger.info("  - %s: %s", tool["name"], tool["description"][:60])

    # Test 3: Call Tool (calculator)
    logger.info("\n" + "=" * 70)
    logger.info("Test 3: Call Tool - Calculator")
    logger.info("=" * 70)

    call_tool_request = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "calculator",
            "arguments": {
                "expression": "sqrt(144) + 10",
            },
        },
        "id": 3,
    }

    call_response = await mcp_server.handle_request(call_tool_request)
    logger.info("Call tool response:")
    logger.info(json.dumps(call_response, indent=2))

    if "error" in call_response:
        logger.error("✗ Tool call failed: %s", call_response["error"])
        return False
    else:
        result = call_response.get("result", {})
        is_error = result.get("isError", False)
        content = result.get("content", [])

        if is_error:
            logger.error("✗ Tool execution error: %s", content)
            return False
        else:
            logger.info("✓ Tool executed successfully")
            for item in content:
                logger.info("  Result: %s", item.get("text", ""))

    # Test 4: Call Tool (get_time)
    logger.info("\n" + "=" * 70)
    logger.info("Test 4: Call Tool - Get Time")
    logger.info("=" * 70)

    time_request = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_time",
            "arguments": {
                "format": "human",
            },
        },
        "id": 4,
    }

    time_response = await mcp_server.handle_request(time_request)
    logger.info("Get time response:")

    if "error" in time_response:
        logger.error("✗ Get time failed: %s", time_response["error"])
        return False
    else:
        result = time_response.get("result", {})
        content = result.get("content", [])
        logger.info("✓ Time retrieved successfully")
        for item in content:
            logger.info("  %s", item.get("text", ""))

    # Test 5: Call Tool (execute_code)
    logger.info("\n" + "=" * 70)
    logger.info("Test 5: Call Tool - Execute Code")
    logger.info("=" * 70)

    code_request = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "execute_code",
            "arguments": {
                "code": "print('Hello from MCP!')\nprint('2 ** 10 =', 2 ** 10)",
            },
        },
        "id": 5,
    }

    code_response = await mcp_server.handle_request(code_request)

    if "error" in code_response:
        logger.error("✗ Code execution failed: %s", code_response["error"])
        return False
    else:
        result = code_response.get("result", {})
        content = result.get("content", [])
        logger.info("✓ Code executed successfully")
        for item in content:
            result_text = item.get("text", "")
            if result_text:
                try:
                    result_json = json.loads(result_text)
                    logger.info("  Output: %s", result_json.get("stdout", ""))
                except:
                    logger.info("  Result: %s", result_text[:200])

    # Test 6: Error Handling (invalid tool)
    logger.info("\n" + "=" * 70)
    logger.info("Test 6: Error Handling - Invalid Tool")
    logger.info("=" * 70)

    invalid_request = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "nonexistent_tool",
            "arguments": {},
        },
        "id": 6,
    }

    invalid_response = await mcp_server.handle_request(invalid_request)

    if "error" in invalid_response:
        logger.info("✓ Error properly handled (this is expected)")
        logger.info("  Error: %s", invalid_response["error"])
    else:
        result = invalid_response.get("result", {})
        if result.get("isError"):
            logger.info("✓ Tool returned error status (expected)")
        else:
            logger.warning("⚠ Expected error but got success")

    # Test 7: Ping
    logger.info("\n" + "=" * 70)
    logger.info("Test 7: Ping (Health Check)")
    logger.info("=" * 70)

    ping_request = {
        "jsonrpc": "2.0",
        "method": "ping",
        "id": 7,
    }

    ping_response = await mcp_server.handle_request(ping_request)

    if "error" in ping_response:
        logger.error("✗ Ping failed: %s", ping_response["error"])
        return False
    else:
        logger.info("✓ Ping successful")
        logger.info("  %s", ping_response.get("result", {}))

    # Test 8: Get Tool Manifest
    logger.info("\n" + "=" * 70)
    logger.info("Test 8: Get Tool Manifest")
    logger.info("=" * 70)

    manifest = mcp_server.get_tool_manifest()
    logger.info("Tool manifest:")
    logger.info("  Server: %s v%s", manifest["server"]["name"], manifest["server"]["version"])
    logger.info("  Tools: %d", len(manifest["tools"]))
    for tool in manifest["tools"]:
        logger.info("    - %s (%s)", tool["name"], tool["category"])

    logger.info("\n✓ Manifest retrieved successfully")

    return True


async def main():
    """Run all MCP tests."""
    logger.info("Starting MCP Server Tests")
    logger.info("=" * 70)

    try:
        success = await test_mcp_server()

        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("Test Summary")
        logger.info("=" * 70)
        if success:
            logger.info("✓ All tests PASSED")
        else:
            logger.error("✗ Some tests FAILED")
        logger.info("=" * 70)

        return success

    except Exception as e:
        logger.error("Test suite failed with error: %s", e, exc_info=True)
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
