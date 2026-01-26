"""Example MCP client demonstrating tool discovery and invocation.

This shows how external applications can interact with the Jarvis MCP server
to discover and use available tools.
"""
import asyncio
import json
import logging
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


class MCPClient:
    """Simple MCP client for testing."""

    def __init__(self, base_url: str = "http://localhost:8000/mcp"):
        """Initialize MCP client.

        Args:
            base_url: Base URL of the MCP server
        """
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
        self.request_id = 0

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    def _next_id(self) -> int:
        """Get next request ID."""
        self.request_id += 1
        return self.request_id

    async def _send_request(self, method: str, params: dict | None = None) -> dict:
        """Send JSON-RPC request to MCP server.

        Args:
            method: MCP method name
            params: Method parameters

        Returns:
            Response dictionary
        """
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._next_id(),
        }

        if params:
            request["params"] = params

        logger.debug("Sending request: %s", json.dumps(request, indent=2))

        response = await self.client.post(self.base_url, json=request)
        response.raise_for_status()

        result = response.json()
        logger.debug("Received response: %s", json.dumps(result, indent=2))

        return result

    async def initialize(self) -> dict:
        """Initialize connection with MCP server."""
        return await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {
                    "name": "jarvis-mcp-client",
                    "version": "0.1.0",
                },
            },
        )

    async def list_tools(self) -> list[dict]:
        """List all available tools.

        Returns:
            List of tool definitions
        """
        response = await self._send_request("tools/list")
        return response.get("result", {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Call a tool.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        response = await self._send_request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        return response.get("result", {})


async def demo_mcp_client():
    """Demonstrate MCP client usage."""
    logger.info("=" * 70)
    logger.info("MCP Client Demo")
    logger.info("=" * 70)
    logger.info("\nNOTE: This requires the Jarvis server to be running.")
    logger.info("Start server with: uvicorn jarvis.app.core.app:app --reload")
    logger.info("=" * 70)

    client = MCPClient()

    try:
        # Initialize
        logger.info("\n1. Initializing connection...")
        init_response = await client.initialize()
        server_info = init_response.get("result", {}).get("serverInfo", {})
        logger.info("✓ Connected to: %s v%s", server_info.get("name"), server_info.get("version"))

        # List tools
        logger.info("\n2. Discovering available tools...")
        tools = await client.list_tools()
        logger.info("✓ Found %d tools:", len(tools))
        for tool in tools:
            logger.info("  - %s", tool["name"])
            logger.info("    %s", tool["description"])

        # Use calculator
        logger.info("\n3. Using calculator tool...")
        calc_result = await client.call_tool(
            "calculator",
            {"expression": "2 ** 16 + 1000"},
        )

        if not calc_result.get("isError"):
            content = calc_result.get("content", [])[0].get("text", "")
            result_data = json.loads(content)
            logger.info("✓ Calculation result: %s = %s",
                       result_data["expression"],
                       result_data["result"])
        else:
            logger.error("✗ Calculator error: %s", calc_result)

        # Get time
        logger.info("\n4. Getting current time...")
        time_result = await client.call_tool(
            "get_time",
            {"format": "human"},
        )

        if not time_result.get("isError"):
            content = time_result.get("content", [])[0].get("text", "")
            time_data = json.loads(content)
            logger.info("✓ Current time: %s", time_data["formatted"])
        else:
            logger.error("✗ Time error: %s", time_result)

        # Execute code
        logger.info("\n5. Executing Python code...")
        code_result = await client.call_tool(
            "execute_code",
            {
                "code": """
# Calculate fibonacci numbers
def fib(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a

for i in range(10):
    print(f'fib({i}) = {fib(i)}')
""",
            },
        )

        if not code_result.get("isError"):
            content = code_result.get("content", [])[0].get("text", "")
            code_data = json.loads(content)
            logger.info("✓ Code execution output:")
            for line in code_data["stdout"].strip().split("\n"):
                logger.info("  %s", line)
        else:
            logger.error("✗ Code execution error: %s", code_result)

        logger.info("\n" + "=" * 70)
        logger.info("✓ MCP Client Demo Complete")
        logger.info("=" * 70)

    except httpx.ConnectError:
        logger.error("\n✗ Cannot connect to MCP server at http://localhost:8000/mcp")
        logger.error("Please start the Jarvis server first:")
        logger.error("  uvicorn jarvis.app.core.app:create_app --factory --reload")
    except Exception as e:
        logger.exception("Error in MCP client demo: %s", e)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(demo_mcp_client())
