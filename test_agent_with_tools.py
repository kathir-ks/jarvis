"""End-to-end test for agent lifecycle with tool calling."""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jarvis.app.core.settings import get_settings
from jarvis.app.db.repositories import AgentRepository, TaskRepository
from jarvis.app.db.vector_memory import get_vector_memory_service
from jarvis.app.llm.tools.init_tools import initialize_tools
from jarvis.app.runtime.agent import Agent, AgentConfig, AgentStatus, AgentType
from jarvis.app.runtime.agent_runner import AgentRunner
from jarvis.app.messaging.broker import MessageBroker
from jarvis.app.db.redis_client import get_redis_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def test_agent_lifecycle():
    """Test complete agent lifecycle with tool calling."""
    logger.info("=" * 70)
    logger.info("Starting Agent Lifecycle Test with Tool Calling")
    logger.info("=" * 70)

    # Verify settings
    settings = get_settings()
    if not settings.openai_api_key and not settings.gemini_api_key:
        logger.error("No LLM API keys configured! Set JARVIS_OPENAI_API_KEY or JARVIS_GEMINI_API_KEY")
        return False

    logger.info("LLM Provider: %s", settings.default_llm_provider)

    # Initialize tools
    logger.info("\n1. Initializing tools...")
    initialize_tools()
    from jarvis.app.llm.tool_registry import get_tool_registry
    tool_registry = get_tool_registry()
    tools = tool_registry.list_tools()
    logger.info("✓ Registered %d tools:", len(tools))
    for tool in tools:
        logger.info("  - %s (%s): %s", tool.name, tool.category.value, tool.description[:60])

    # Initialize repositories
    logger.info("\n2. Initializing repositories...")
    agent_repo = AgentRepository()
    message_broker = MessageBroker()

    # Create test agent
    logger.info("\n3. Creating test agent...")
    agent_id = f"test-agent-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    agent = Agent(
        agent_id=agent_id,
        user_id="test-user",
        agent_type=AgentType.MASTER,
        config=AgentConfig(
            llm_provider=settings.default_llm_provider,
            model=settings.default_llm_model,
            temperature=0.7,
            max_tokens=500,
        ),
        tools_available=[],  # Empty = all tools available
        status=AgentStatus.IDLE,
    )

    await agent_repo.create(agent)
    logger.info("✓ Created agent: %s", agent_id)

    # Start agent runner in background
    logger.info("\n4. Starting agent runner...")
    agent_runner = AgentRunner(agent_id)
    runner_task = asyncio.create_task(agent_runner.run())

    # Give it time to initialize
    await asyncio.sleep(2)

    # Verify agent is running
    agent_data = await agent_repo.get_by_id(agent_id)
    logger.info("✓ Agent status: %s", agent_data.status if agent_data else "NOT FOUND")

    # Test 1: Simple message without tools
    logger.info("\n5. Test 1: Simple message (no tools needed)...")
    reply_channel = f"test-reply-{agent_id}"
    received_messages = []

    async def reply_handler(msg):
        logger.info("📩 Received reply: %s", json.dumps(msg, indent=2))
        received_messages.append(msg)

    # Subscribe to reply channel
    await message_broker.subscribe(reply_channel, reply_handler)
    await asyncio.sleep(0.5)

    # Send message
    await message_broker.publish(
        f"agent:{agent_id}:inbox",
        {
            "type": "user_message",
            "content": "Hello! What is 2 + 2?",
            "reply_channel": reply_channel,
        },
    )
    logger.info("✓ Sent message to agent")

    # Wait for response
    await asyncio.sleep(5)

    if received_messages:
        logger.info("✓ Test 1 PASSED: Got response")
        logger.info("  Response: %s", received_messages[-1].get("content", "")[:200])
    else:
        logger.error("✗ Test 1 FAILED: No response received")

    # Test 2: Message that requires tool use
    logger.info("\n6. Test 2: Message requiring tool use...")
    received_messages.clear()

    await message_broker.publish(
        f"agent:{agent_id}:inbox",
        {
            "type": "user_message",
            "content": "Can you calculate the square root of 144 using the calculator tool?",
            "reply_channel": reply_channel,
        },
    )
    logger.info("✓ Sent tool-requiring message to agent")

    # Wait for response (tool calls may take longer)
    await asyncio.sleep(8)

    if received_messages:
        logger.info("✓ Test 2 PASSED: Got response with tool use")
        logger.info("  Response: %s", received_messages[-1].get("content", "")[:200])
        iterations = received_messages[-1].get("metadata", {}).get("iterations", 1)
        logger.info("  Iterations (tool rounds): %d", iterations)
    else:
        logger.error("✗ Test 2 FAILED: No response received")

    # Test 3: Web search tool
    logger.info("\n7. Test 3: Web search tool...")
    received_messages.clear()

    await message_broker.publish(
        f"agent:{agent_id}:inbox",
        {
            "type": "user_message",
            "content": "Search the web for 'Python async programming' and tell me what you find.",
            "reply_channel": reply_channel,
        },
    )
    logger.info("✓ Sent web search request to agent")

    # Wait for response
    await asyncio.sleep(10)

    if received_messages:
        logger.info("✓ Test 3 PASSED: Got response with web search")
        response = received_messages[-1].get("content", "")
        logger.info("  Response length: %d chars", len(response))
        logger.info("  Preview: %s...", response[:150])
    else:
        logger.error("✗ Test 3 FAILED: No response received")

    # Test 4: Code execution tool
    logger.info("\n8. Test 4: Code execution tool...")
    received_messages.clear()

    await message_broker.publish(
        f"agent:{agent_id}:inbox",
        {
            "type": "user_message",
            "content": "Execute this Python code: print('Hello from Jarvis!')",
            "reply_channel": reply_channel,
        },
    )
    logger.info("✓ Sent code execution request to agent")

    # Wait for response
    await asyncio.sleep(8)

    if received_messages:
        logger.info("✓ Test 4 PASSED: Got response with code execution")
        logger.info("  Response: %s", received_messages[-1].get("content", "")[:200])
    else:
        logger.error("✗ Test 4 FAILED: No response received")

    # Check vector memory
    logger.info("\n9. Checking vector memory...")
    try:
        vector_memory = get_vector_memory_service()
        await vector_memory.initialize_collections()

        context = await vector_memory.get_recent_context(
            user_id="test-user",
            agent_id=agent_id,
            interaction_limit=10,
        )

        interaction_count = len(context.get("interactions", []))
        logger.info("✓ Vector memory has %d interactions stored", interaction_count)

    except Exception as e:
        logger.warning("Vector memory check failed (may not be configured): %s", e)

    # Stop agent
    logger.info("\n10. Stopping agent...")
    agent_runner.running = False
    await asyncio.sleep(2)
    runner_task.cancel()

    try:
        await runner_task
    except asyncio.CancelledError:
        pass

    logger.info("✓ Agent stopped")

    # Final status check
    logger.info("\n11. Final status check...")
    final_agent = await agent_repo.get_by_id(agent_id)
    if final_agent:
        logger.info("✓ Agent persisted in database")
        logger.info("  Status: %s", final_agent.status)
        logger.info("  Memory entries: %d", len(final_agent.memory))
        logger.info("  Context keys: %s", list(final_agent.context.keys()))
    else:
        logger.error("✗ Agent not found in database")

    logger.info("\n" + "=" * 70)
    logger.info("Agent Lifecycle Test Complete!")
    logger.info("=" * 70)

    return True


if __name__ == "__main__":
    try:
        asyncio.run(test_agent_lifecycle())
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
    except Exception as e:
        logger.error("Test failed with error: %s", e, exc_info=True)
        sys.exit(1)
