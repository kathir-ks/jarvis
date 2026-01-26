"""Test Gemini API with tool calling integration."""
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


async def test_gemini_basic():
    """Test basic Gemini chat without tools."""
    logger.info("=" * 70)
    logger.info("Test 1: Basic Gemini Chat (No Tools)")
    logger.info("=" * 70)

    settings = get_settings()
    if not settings.gemini_api_key:
        logger.error("❌ No Gemini API key configured!")
        logger.error("Set JARVIS_GEMINI_API_KEY environment variable")
        return False

    llm_router = LLMRouter()

    messages = [
        {
            "role": "user",
            "content": "Hello! Please respond with a simple greeting.",
        }
    ]

    config = {
        "provider": "gemini",
        "model": settings.default_gemini_model,
        "temperature": 0.7,
        "max_tokens": 100,
    }

    try:
        response = await llm_router.call(messages, config)

        logger.info("✓ Gemini Response:")
        logger.info("  Provider: %s", response.provider)
        logger.info("  Model: %s", response.model)
        logger.info("  Content: %s", response.content)
        logger.info("  Finish Reason: %s", response.finish_reason)

        if response.usage:
            logger.info("  Tokens: %d total", response.usage.get("total_tokens", 0))

        return True

    except Exception as e:
        logger.error("❌ Gemini API call failed: %s", e, exc_info=True)
        return False


async def test_gemini_with_tools():
    """Test Gemini with tool calling."""
    logger.info("\n" + "=" * 70)
    logger.info("Test 2: Gemini with Tool Calling")
    logger.info("=" * 70)

    settings = get_settings()
    if not settings.gemini_api_key:
        logger.error("❌ No Gemini API key configured!")
        return False

    # Initialize tools
    initialize_tools()

    llm_router = LLMRouter()
    registry = get_tool_registry()

    # Test with calculator tool
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant with access to tools. Use tools when needed to help the user.",
        },
        {
            "role": "user",
            "content": "What is the square root of 256? Use the calculator tool to find out.",
        },
    ]

    config = {
        "provider": "gemini",
        "model": settings.default_gemini_model,
        "temperature": 0.3,
        "max_tokens": 500,
        "tools": registry.get_openai_tools(),
    }

    try:
        logger.info("\n📤 Calling Gemini with tools available...")
        response = await llm_router.call(messages, config)

        logger.info("✓ Gemini Response:")
        logger.info("  Provider: %s", response.provider)
        logger.info("  Model: %s", response.model)
        logger.info("  Content: %s", response.content[:200] if response.content else "(no content)")
        logger.info("  Finish Reason: %s", response.finish_reason)

        if response.tool_calls:
            logger.info("  🔧 Tool Calls: %d", len(response.tool_calls))

            for i, tc in enumerate(response.tool_calls):
                logger.info("\n  Tool Call #%d:", i + 1)
                logger.info("    Function: %s", tc["function"]["name"])

                # Parse arguments
                args = tc["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except:
                        pass

                logger.info("    Arguments: %s", json.dumps(args, indent=6))

                # Execute the tool
                tool_name = tc["function"]["name"]
                logger.info("\n  ⚙️ Executing tool: %s", tool_name)

                tool_result = await registry.execute(tool_name, args)

                if tool_result.success:
                    logger.info("  ✓ Tool Result: %s", json.dumps(tool_result.result, indent=4))

                    # Continue conversation with tool result
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": response.tool_calls,
                    })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": tool_name,
                        "content": json.dumps(tool_result.result),
                    })

                    # Get final response
                    logger.info("\n📤 Getting final response from Gemini...")
                    final_response = await llm_router.call(messages, config)

                    logger.info("✓ Final Response:")
                    logger.info("  %s", final_response.content)

                else:
                    logger.error("  ❌ Tool execution failed: %s", tool_result.error)

            return True

        else:
            logger.warning("⚠️ No tool calls (Gemini may have answered directly)")
            logger.info("  Response: %s", response.content)
            return True

    except Exception as e:
        logger.error("❌ Gemini tool calling failed: %s", e, exc_info=True)
        return False


async def test_gemini_multi_tool():
    """Test Gemini with multiple tool calls."""
    logger.info("\n" + "=" * 70)
    logger.info("Test 3: Gemini with Multiple Tools")
    logger.info("=" * 70)

    settings = get_settings()
    if not settings.gemini_api_key:
        logger.error("❌ No Gemini API key configured!")
        return False

    # Initialize tools
    initialize_tools()

    llm_router = LLMRouter()
    registry = get_tool_registry()

    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant. Use tools when you need to get information or perform calculations.",
        },
        {
            "role": "user",
            "content": "What is 15 * 23, and what time is it right now in UTC?",
        },
    ]

    config = {
        "provider": "gemini",
        "model": settings.default_gemini_model,
        "temperature": 0.3,
        "max_tokens": 500,
        "tools": registry.get_openai_tools(),
    }

    try:
        logger.info("\n📤 Asking Gemini a multi-part question...")
        response = await llm_router.call(messages, config)

        logger.info("✓ Gemini Response:")

        if response.tool_calls:
            logger.info("  🔧 Tool Calls: %d", len(response.tool_calls))

            # Execute all tool calls
            tool_results = []
            for tc in response.tool_calls:
                tool_name = tc["function"]["name"]
                args = tc["function"]["arguments"]

                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except:
                        pass

                logger.info("\n  Executing: %s(%s)", tool_name, json.dumps(args))

                tool_result = await registry.execute(tool_name, args)

                if tool_result.success:
                    logger.info("  ✓ Result: %s", json.dumps(tool_result.result))
                    tool_results.append((tc, tool_result))
                else:
                    logger.error("  ❌ Failed: %s", tool_result.error)

            # Continue conversation
            messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": response.tool_calls,
            })

            for tc, result in tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tc["function"]["name"],
                    "content": json.dumps(result.result),
                })

            # Get final answer
            logger.info("\n📤 Getting final synthesized answer...")
            final_response = await llm_router.call(messages, config)

            logger.info("✓ Final Answer:")
            logger.info("  %s", final_response.content)

            return True

        else:
            logger.info("  Response without tools: %s", response.content)
            return True

    except Exception as e:
        logger.error("❌ Test failed: %s", e, exc_info=True)
        return False


async def main():
    """Run all Gemini tests."""
    logger.info("Starting Gemini + Tools Integration Tests")
    logger.info("=" * 70)

    # Check for API key
    settings = get_settings()
    if not settings.gemini_api_key:
        logger.error("\n❌ GEMINI API KEY NOT CONFIGURED!")
        logger.error("\nTo configure:")
        logger.error("1. Get an API key from: https://aistudio.google.com/app/apikey")
        logger.error("2. Set environment variable:")
        logger.error("   export JARVIS_GEMINI_API_KEY='your-key-here'")
        logger.error("   OR add to .env file:")
        logger.error("   JARVIS_GEMINI_API_KEY=your-key-here")
        logger.error("\n" + "=" * 70)
        return False

    logger.info("✓ Gemini API Key: %s", settings.gemini_api_key[:20] + "...")
    logger.info("✓ Model: %s", settings.default_gemini_model)
    logger.info("")

    try:
        # Test 1: Basic chat
        test1 = await test_gemini_basic()

        # Test 2: Single tool call
        test2 = await test_gemini_with_tools()

        # Test 3: Multiple tools
        test3 = await test_gemini_multi_tool()

        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("Test Summary")
        logger.info("=" * 70)
        logger.info("Basic Chat:        %s", "✓ PASS" if test1 else "❌ FAIL")
        logger.info("Tool Calling:      %s", "✓ PASS" if test2 else "❌ FAIL")
        logger.info("Multiple Tools:    %s", "✓ PASS" if test3 else "❌ FAIL")
        logger.info("=" * 70)

        return test1 and test2 and test3

    except Exception as e:
        logger.error("Test suite failed: %s", e, exc_info=True)
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
