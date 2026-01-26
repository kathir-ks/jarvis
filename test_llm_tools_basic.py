"""Basic test for LLM and tool integration without database dependencies."""
import asyncio
import json
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jarvis.app.core.settings import get_settings
from jarvis.app.llm.router import LLMRouter
from jarvis.app.llm.tools.init_tools import initialize_tools
from jarvis.app.llm.tool_registry import get_tool_registry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def test_tool_registry():
    """Test that tools are registered correctly."""
    logger.info("=" * 70)
    logger.info("Test 1: Tool Registry")
    logger.info("=" * 70)

    # Initialize tools
    initialize_tools()
    registry = get_tool_registry()

    # List all tools
    tools = registry.list_tools()
    logger.info("Registered %d tools:", len(tools))
    for tool in tools:
        logger.info("  - %s (%s): %s", tool.name, tool.category.value, tool.description[:60])

    # Test tool execution
    logger.info("\n Testing calculator tool...")
    result = await registry.execute("calculator", {"expression": "2 + 2"})
    if result.success:
        logger.info("✓ Calculator result: %s", result.result)
    else:
        logger.error("✗ Calculator failed: %s", result.error)

    # Test OpenAI schema conversion
    logger.info("\n Testing OpenAI schema conversion...")
    openai_tools = registry.get_openai_tools()
    logger.info("✓ Converted %d tools to OpenAI format", len(openai_tools))
    if openai_tools:
        logger.info("  Sample tool schema: %s", json.dumps(openai_tools[0], indent=2)[:200])

    return len(tools) > 0


async def test_llm_with_tools():
    """Test LLM integration with tool calling."""
    logger.info("\n" + "=" * 70)
    logger.info("Test 2: LLM with Tool Calling")
    logger.info("=" * 70)

    # Verify settings
    settings = get_settings()
    if not settings.openai_api_key and not settings.gemini_api_key:
        logger.error("No LLM API keys configured! Set JARVIS_OPENAI_API_KEY or JARVIS_GEMINI_API_KEY")
        return False

    logger.info("LLM Provider: %s", settings.default_llm_provider)
    logger.info("LLM Model: %s", settings.default_llm_model)

    # Initialize LLM router
    llm_router = LLMRouter()
    registry = get_tool_registry()

    # Prepare messages
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant with access to tools. Use tools when needed to help the user.",
        },
        {
            "role": "user",
            "content": "What is the square root of 144? Use the calculator tool to find out.",
        },
    ]

    # Prepare config with tools
    config = {
        "provider": settings.default_llm_provider,
        "model": settings.default_llm_model,
        "temperature": 0.7,
        "max_tokens": 500,
        "tools": registry.get_openai_tools(),
    }

    # Test 1: Simple LLM call with tools
    logger.info("\n Calling LLM with tools available...")
    response = await llm_router.call(messages, config)

    logger.info("✓ LLM Response:")
    logger.info("  Provider: %s", response.provider)
    logger.info("  Model: %s", response.model)
    logger.info("  Content: %s", response.content[:200] if response.content else "(no content)")
    logger.info("  Finish Reason: %s", response.finish_reason)

    if response.tool_calls:
        logger.info("  Tool Calls: %d", len(response.tool_calls))
        for i, tc in enumerate(response.tool_calls):
            logger.info("    [%d] %s", i + 1, tc["function"]["name"])
            logger.info("        Args: %s", tc["function"]["arguments"][:100])

        # Execute tool calls
        logger.info("\n Executing tool calls...")
        for tool_call in response.tool_calls:
            tool_name = tool_call["function"]["name"]
            tool_args_str = tool_call["function"]["arguments"]

            try:
                tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                logger.info("  Executing: %s(%s)", tool_name, json.dumps(tool_args))

                tool_result = await registry.execute(tool_name, tool_args)

                if tool_result.success:
                    logger.info("  ✓ Result: %s", json.dumps(tool_result.result))
                else:
                    logger.error("  ✗ Error: %s", tool_result.error)
            except Exception as e:
                logger.error("  ✗ Exception: %s", e)

        # Continue conversation with tool results
        logger.info("\n Continuing conversation with tool results...")
        messages.append({
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": response.tool_calls,
        })

        # Add tool results
        for tool_call in response.tool_calls:
            tool_name = tool_call["function"]["name"]
            tool_args_str = tool_call["function"]["arguments"]
            tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
            tool_result = await registry.execute(tool_name, tool_args)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": tool_name,
                "content": json.dumps(tool_result.result) if tool_result.success else json.dumps({"error": tool_result.error}),
            })

        # Get final response
        final_response = await llm_router.call(messages, config)
        logger.info("✓ Final Response: %s", final_response.content[:300])

        return True
    else:
        logger.info("  No tool calls (LLM may have answered directly)")
        return True


async def test_code_execution_tool():
    """Test the code execution tool."""
    logger.info("\n" + "=" * 70)
    logger.info("Test 3: Code Execution Tool")
    logger.info("=" * 70)

    registry = get_tool_registry()

    # Test 1: Simple print
    logger.info("\n Test 1: Simple print")
    result = await registry.execute("execute_code", {
        "code": "print('Hello from Jarvis!')\nprint('2 + 2 =', 2 + 2)",
    })

    if result.success:
        logger.info("✓ Code execution successful")
        logger.info("  Output: %s", result.result.get("stdout"))
    else:
        logger.error("✗ Code execution failed: %s", result.error)

    # Test 2: Math operations (math is already available in globals)
    logger.info("\n Test 2: Math with output")
    result = await registry.execute("execute_code", {
        "code": """
# Note: math module is already available in safe_globals
result = math.sqrt(144)
print(f'Square root of 144 is {result}')
print(f'Pi is approximately {math.pi:.4f}')
""",
    })

    if result.success:
        logger.info("✓ Math code successful")
        logger.info("  Output: %s", result.result.get("stdout"))
    else:
        logger.error("✗ Math code failed: %s", result.error)

    # Test 3: Error handling
    logger.info("\n Test 3: Error handling")
    result = await registry.execute("execute_code", {
        "code": "x = 1 / 0  # This will raise an error",
    })

    # Check if error was caught (either in result.success=False OR in result.result.error)
    if not result.success or (result.result and result.result.get("error")):
        error_info = result.error or result.result.get("error")
        logger.info("✓ Error properly caught: %s", error_info)
    else:
        logger.warning("⚠ Expected an error but got success: %s", result.result)

    return True


async def main():
    """Run all tests."""
    logger.info("Starting Basic LLM and Tools Integration Test")
    logger.info("=" * 70)

    try:
        # Test 1: Tool Registry
        test1 = await test_tool_registry()

        # Test 2: Code Execution
        test2 = await test_code_execution_tool()

        # Test 3: LLM with Tools (requires API key)
        test3 = await test_llm_with_tools()

        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("Test Summary")
        logger.info("=" * 70)
        logger.info("Tool Registry: %s", "✓ PASS" if test1 else "✗ FAIL")
        logger.info("Code Execution: %s", "✓ PASS" if test2 else "✗ FAIL")
        logger.info("LLM Integration: %s", "✓ PASS" if test3 else "✗ FAIL")
        logger.info("=" * 70)

        return test1 and test2 and test3

    except Exception as e:
        logger.error("Test failed with error: %s", e, exc_info=True)
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
