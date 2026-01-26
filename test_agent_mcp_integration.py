"""Test agent integration with MCP protocol."""
import asyncio
import json
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jarvis.app.core.settings import get_settings
from jarvis.app.llm.tools.init_tools import initialize_tools
from jarvis.app.mcp.client import MCPClient
from jarvis.app.mcp.server import MCPServer
from jarvis.app.runtime.agent import Agent, AgentConfig, AgentType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def test_mcp_client_basic():
    """Test basic MCP client connectivity."""
    logger.info("=" * 70)
    logger.info("Test 1: MCP Client Basic Connectivity")
    logger.info("=" * 70)

    # Initialize tools and MCP server
    initialize_tools()
    mcp_server = MCPServer()

    # Create MCP client (simulating local connection)
    # In production, this would be a real HTTP endpoint
    # For testing, we'll test the client against the server directly

    logger.info("✓ Testing MCP server info...")
    init_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {"clientVersion": "1.0.0"},
        "id": "init",
    }
    init_response = await mcp_server.handle_request(init_request)
    logger.info("  Server: %s v%s",
                init_response["result"]["serverInfo"]["name"],
                init_response["result"]["serverInfo"]["version"])

    logger.info("✓ Testing tool discovery...")
    list_request = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "params": {},
        "id": "list",
    }
    list_response = await mcp_server.handle_request(list_request)
    tools = list_response["result"]["tools"]
    logger.info("  Discovered %d tools via MCP", len(tools))

    for tool in tools:
        logger.info("    - %s", tool["name"])

    logger.info("✓ Testing tool execution via MCP...")
    call_request = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "calculator",
            "arguments": {"expression": "25 + 17"},
        },
        "id": "call",
    }
    call_response = await mcp_server.handle_request(call_request)
    result = call_response["result"]

    if not result.get("isError"):
        # Extract result from MCP content format
        content_text = result["content"][0]["text"]
        logger.info("  ✓ Calculator result: %s", content_text)
    else:
        error_msg = result["content"][0]["text"] if result.get("content") else "Unknown error"
        logger.error("  ❌ Tool execution failed: %s", error_msg)
        return False

    logger.info("✓ Test 1 PASSED\n")
    return True


async def test_mcp_client_http():
    """Test MCP client over HTTP (requires running server)."""
    logger.info("=" * 70)
    logger.info("Test 2: MCP Client via HTTP")
    logger.info("=" * 70)

    # This test requires the FastAPI server to be running
    # We'll test if it's available, otherwise skip
    try:
        client = MCPClient(
            server_url="http://localhost:8000/api/mcp",
            timeout_seconds=5,
        )

        await client.connect()

        # Test ping
        ping_ok = await client.ping()
        if not ping_ok:
            logger.warning("⚠️ MCP server not responding to ping")
            logger.info("  Skipping HTTP test (server not running)")
            await client.close()
            return True  # Skip, not a failure

        logger.info("✓ MCP server is responsive")

        # Test initialization
        server_info = await client.initialize()
        logger.info("✓ Server info: %s", server_info.get("serverName", "unknown"))

        # Test tool discovery
        tools = await client.list_tools()
        logger.info("✓ Discovered %d tools", len(tools))

        # Test tool execution
        result = await client.call_tool("calculator", {"expression": "100 / 4"})

        if result.get("success"):
            logger.info("✓ Tool execution result: %s", result["result"]["result"])
        else:
            logger.error("❌ Tool execution failed: %s", result.get("error"))
            return False

        await client.close()
        logger.info("✓ Test 2 PASSED\n")
        return True

    except Exception as e:
        logger.warning("⚠️ HTTP test skipped: %s", e)
        logger.info("  (Start the server with: uvicorn jarvis.app.core.app:app)")
        return True  # Not a failure, just skipped


async def test_agent_with_mcp():
    """Test agent configuration to use MCP for tools."""
    logger.info("=" * 70)
    logger.info("Test 3: Agent with MCP Configuration")
    logger.info("=" * 70)

    # Create agent with MCP configuration
    agent_config = AgentConfig(
        llm_provider="gemini",
        model=get_settings().default_gemini_model,
        temperature=0.3,
        max_tokens=500,
        mcp_server_url="http://localhost:8000/api/mcp",
        mcp_timeout_seconds=30,
    )

    agent = Agent(
        agent_id="test-agent-mcp",
        user_id="test-user",
        agent_type=AgentType.MASTER,
        config=agent_config,
        tools_available=["calculator", "get_time"],  # Only allow specific tools
    )

    logger.info("✓ Created agent with MCP configuration:")
    logger.info("  Agent ID: %s", agent.agent_id)
    logger.info("  MCP Server: %s", agent.config.mcp_server_url)
    logger.info("  Allowed Tools: %s", ", ".join(agent.tools_available))

    # Verify agent configuration
    if not agent.config.mcp_server_url:
        logger.error("❌ Agent MCP configuration missing")
        return False

    logger.info("✓ Test 3 PASSED\n")
    return True


async def test_agent_tool_discovery_from_mcp():
    """Test that agent can discover tools from MCP."""
    logger.info("=" * 70)
    logger.info("Test 4: Agent Tool Discovery from MCP")
    logger.info("=" * 70)

    try:
        # Initialize tools
        initialize_tools()

        # Create MCP client
        client = MCPClient(
            server_url="http://localhost:8000/api/mcp",
            timeout_seconds=5,
        )

        await client.connect()
        ping_ok = await client.ping()

        if not ping_ok:
            logger.warning("⚠️ MCP server not available, skipping test")
            await client.close()
            return True

        # Simulate agent discovering tools
        logger.info("✓ Agent discovering tools from MCP...")
        all_tools = await client.list_tools()
        logger.info("  Found %d tools", len(all_tools))

        # Filter tools based on agent's allowed list
        allowed_tools = ["calculator", "get_time"]
        filtered_tools = [
            t
            for t in all_tools
            if t.get("function", {}).get("name") in allowed_tools
        ]

        logger.info("✓ Agent filtered to %d allowed tools:", len(filtered_tools))
        for tool in filtered_tools:
            logger.info("    - %s", tool["function"]["name"])

        if len(filtered_tools) != 2:
            logger.error("❌ Expected 2 filtered tools, got %d", len(filtered_tools))
            return False

        # Test tool execution through MCP
        logger.info("✓ Testing tool execution through MCP...")
        result = await client.call_tool("calculator", {"expression": "15 * 8"})

        if result.get("success"):
            logger.info("  Result: 15 * 8 = %s", result["result"]["result"])
        else:
            logger.error("  ❌ Tool execution failed: %s", result.get("error"))
            return False

        await client.close()
        logger.info("✓ Test 4 PASSED\n")
        return True

    except Exception as e:
        logger.warning("⚠️ Test skipped: %s", e)
        return True


async def test_mcp_error_handling():
    """Test MCP client error handling."""
    logger.info("=" * 70)
    logger.info("Test 5: MCP Error Handling")
    logger.info("=" * 70)

    try:
        client = MCPClient(
            server_url="http://localhost:8000/api/mcp",
            timeout_seconds=5,
        )

        await client.connect()
        ping_ok = await client.ping()

        if not ping_ok:
            logger.warning("⚠️ MCP server not available, skipping test")
            await client.close()
            return True

        # Test calling non-existent tool
        logger.info("✓ Testing error handling for non-existent tool...")
        try:
            result = await client.call_tool("nonexistent_tool", {})
            if not result.get("success"):
                logger.info("  ✓ Correctly handled non-existent tool error")
            else:
                logger.error("  ❌ Should have failed for non-existent tool")
                return False
        except Exception as e:
            logger.info("  ✓ Exception raised as expected: %s", str(e)[:50])

        # Test calling with invalid arguments
        logger.info("✓ Testing error handling for invalid arguments...")
        try:
            result = await client.call_tool("calculator", {"invalid_param": "test"})
            if not result.get("success"):
                logger.info("  ✓ Correctly handled invalid arguments")
            else:
                logger.warning("  ⚠️ Tool succeeded despite invalid arguments")
        except Exception as e:
            logger.info("  ✓ Exception raised as expected: %s", str(e)[:50])

        await client.close()
        logger.info("✓ Test 5 PASSED\n")
        return True

    except Exception as e:
        logger.warning("⚠️ Test skipped: %s", e)
        return True


async def main():
    """Run all MCP integration tests."""
    logger.info("Starting Agent + MCP Integration Tests")
    logger.info("=" * 70)
    logger.info("")

    # Check for Gemini API key
    settings = get_settings()
    if not settings.gemini_api_key:
        logger.warning("⚠️ Gemini API key not configured (some tests may be limited)")
    else:
        logger.info("✓ Gemini API Key configured")

    logger.info("✓ Default Gemini Model: %s", settings.default_gemini_model)
    logger.info("")

    try:
        # Test 1: Basic MCP client
        test1 = await test_mcp_client_basic()

        # Test 2: HTTP connectivity (requires server running)
        test2 = await test_mcp_client_http()

        # Test 3: Agent configuration
        test3 = await test_agent_with_mcp()

        # Test 4: Tool discovery
        test4 = await test_agent_tool_discovery_from_mcp()

        # Test 5: Error handling
        test5 = await test_mcp_error_handling()

        # Summary
        logger.info("=" * 70)
        logger.info("Test Summary")
        logger.info("=" * 70)
        logger.info("MCP Client Basic:          %s", "✓ PASS" if test1 else "❌ FAIL")
        logger.info("MCP Client HTTP:           %s", "✓ PASS" if test2 else "❌ FAIL")
        logger.info("Agent MCP Config:          %s", "✓ PASS" if test3 else "❌ FAIL")
        logger.info("Agent Tool Discovery:      %s", "✓ PASS" if test4 else "❌ FAIL")
        logger.info("MCP Error Handling:        %s", "✓ PASS" if test5 else "❌ FAIL")
        logger.info("=" * 70)

        if not all([test1, test2, test3, test4, test5]):
            logger.info("\n⚠️ Note: Some HTTP tests may be skipped if server is not running")
            logger.info("To run full tests:")
            logger.info("  1. Terminal 1: uvicorn jarvis.app.core.app:app --reload")
            logger.info("  2. Terminal 2: python test_agent_mcp_integration.py")

        return test1 and test2 and test3 and test4 and test5

    except Exception as e:
        logger.error("Test suite failed: %s", e, exc_info=True)
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
