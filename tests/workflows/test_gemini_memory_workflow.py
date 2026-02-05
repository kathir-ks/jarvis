"""
Test 4: Memory-Enhanced Multi-Turn Workflow

Validates:
- Short-term memory retention
- Long-term vector memory storage and retrieval
- Multi-turn conversation coherence
- Context switching capabilities
"""
import pytest
import asyncio
from jarvis.app.runtime.agent_runner import AgentRunner
from .conftest import run_workflow, assert_response_quality


@pytest.mark.asyncio
async def test_short_term_memory_workflow(agent_runner: AgentRunner):
    """
    Test short-term memory retention across multiple turns.

    Workflow:
    1. Store information in conversation
    2. Ask question requiring that information
    3. Verify agent recalls from short-term memory
    """
    # Turn 1: Provide information
    result1 = await run_workflow(
        agent_runner=agent_runner,
        message_content="My project is building an AI agent platform called Jarvis",
        timeout=20.0,
    )
    assert_response_quality(result1, min_length=10)
    print(f"\n✓ Turn 1 completed: {result1['response'][:100]}")

    # Wait a moment for memory to be stored
    await asyncio.sleep(2)

    # Turn 2: Provide more context
    result2 = await run_workflow(
        agent_runner=agent_runner,
        message_content="I prefer using FastAPI for web frameworks",
        timeout=20.0,
    )
    assert_response_quality(result2, min_length=10)
    print(f"✓ Turn 2 completed: {result2['response'][:100]}")

    await asyncio.sleep(2)

    # Turn 3: Query about previous information
    result3 = await run_workflow(
        agent_runner=agent_runner,
        message_content="What framework do I prefer?",
        timeout=25.0,
    )

    # Assert agent recalls FastAPI
    assert_response_quality(
        result3,
        min_length=10,
        should_contain=["fastapi"],
    )
    print(f"✓ Turn 3 completed: {result3['response'][:100]}")

    await asyncio.sleep(2)

    # Turn 4: Query about project name
    result4 = await run_workflow(
        agent_runner=agent_runner,
        message_content="What's my project called?",
        timeout=25.0,
    )

    # Assert agent recalls Jarvis
    assert_response_quality(
        result4,
        min_length=10,
        should_contain=["jarvis"],
    )
    print(f"✓ Turn 4 completed: {result4['response'][:100]}")

    # Verify memory count
    memory_count = len(agent_runner.agent.short_term_memory)
    assert memory_count >= 8, f"Expected at least 8 memory items, got {memory_count}"
    print(f"\n✓ Short-term memory workflow completed with {memory_count} memory items")


@pytest.mark.asyncio
async def test_long_term_memory_workflow(agent_runner: AgentRunner):
    """
    Test long-term vector memory storage and retrieval.

    Workflow:
    1. Have extended conversation (multiple turns)
    2. Wait for vector storage consolidation
    3. Query information from earlier turns
    4. Verify retrieval from vector database
    """
    # Turn 1: Technical preference
    result1 = await run_workflow(
        agent_runner=agent_runner,
        message_content="I'm using MongoDB for my database because I need flexible schemas",
        timeout=20.0,
    )
    assert_response_quality(result1, min_length=10)

    await asyncio.sleep(2)

    # Turn 2: Architecture decision
    result2 = await run_workflow(
        agent_runner=agent_runner,
        message_content="My system uses Redis for pub/sub messaging between agents",
        timeout=20.0,
    )
    assert_response_quality(result2, min_length=10)

    await asyncio.sleep(2)

    # Turn 3: Tool preference
    result3 = await run_workflow(
        agent_runner=agent_runner,
        message_content="I implement tool calling using the OpenAI function calling format",
        timeout=20.0,
    )
    assert_response_quality(result3, min_length=10)

    # Allow time for vector memory consolidation
    await asyncio.sleep(5)

    # Turn 4: Query about database choice
    result4 = await run_workflow(
        agent_runner=agent_runner,
        message_content="What database am I using and why?",
        timeout=30.0,
    )

    assert_response_quality(
        result4,
        min_length=20,
        should_contain=["mongodb"],
    )

    print(f"\n✓ Long-term memory workflow completed")
    print(f"  Final response: {result4['response'][:150]}...")


@pytest.mark.asyncio
async def test_context_switching_workflow(agent_runner: AgentRunner):
    """
    Test agent's ability to switch between different topics and maintain context.

    Workflow:
    1. Discuss topic A
    2. Switch to topic B
    3. Return to topic A and verify recall
    """
    # Topic A: Project details
    result1 = await run_workflow(
        agent_runner=agent_runner,
        message_content="I'm building a task orchestration system with DAG support",
        timeout=20.0,
    )
    assert_response_quality(result1, min_length=10)

    await asyncio.sleep(2)

    # Topic B: Completely different - personal preference
    result2 = await run_workflow(
        agent_runner=agent_runner,
        message_content="By the way, I prefer Python 3.11 or higher for async features",
        timeout=20.0,
    )
    assert_response_quality(result2, min_length=10)

    await asyncio.sleep(2)

    # Topic C: Another switch - technical detail
    result3 = await run_workflow(
        agent_runner=agent_runner,
        message_content="I use Qdrant for vector storage of conversation history",
        timeout=20.0,
    )
    assert_response_quality(result3, min_length=10)

    await asyncio.sleep(2)

    # Return to Topic A
    result4 = await run_workflow(
        agent_runner=agent_runner,
        message_content="What kind of system am I building?",
        timeout=25.0,
    )

    # Should recall task orchestration and DAG
    assert_response_quality(
        result4,
        min_length=20,
        should_contain=["task", "orchestration"],
    )

    print(f"\n✓ Context switching workflow completed")
    print(f"  Final response: {result4['response'][:150]}...")


@pytest.mark.asyncio
async def test_memory_based_personalization(agent_runner: AgentRunner):
    """
    Test agent's ability to personalize responses based on remembered preferences.

    Workflow:
    1. Share preferences and context
    2. Ask general question
    3. Verify agent personalizes answer based on memory
    """
    # Share context
    result1 = await run_workflow(
        agent_runner=agent_runner,
        message_content=(
            "I'm a backend developer focused on async Python. "
            "I love clean architecture and test-driven development."
        ),
        timeout=20.0,
    )
    assert_response_quality(result1, min_length=10)

    await asyncio.sleep(3)

    # Ask general question that should be personalized
    result2 = await run_workflow(
        agent_runner=agent_runner,
        message_content="What programming topics should I focus on learning?",
        timeout=30.0,
    )

    # Should mention Python, async, or architecture
    assert_response_quality(
        result2,
        min_length=50,
        should_contain=["python"],
    )

    print(f"\n✓ Memory-based personalization workflow completed")
    print(f"  Response: {result2['response'][:200]}...")
