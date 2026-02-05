"""
Shared fixtures for Gemini workflow tests.
"""
import asyncio
import pytest
from datetime import datetime
from typing import Any, AsyncGenerator

from jarvis.app.runtime.agent import Agent, AgentConfig, AgentType, AgentStatus
from jarvis.app.runtime.agent_runner import AgentRunner
from jarvis.app.runtime.task import Task, TaskType, TaskStatus
from jarvis.app.db.repositories import AgentRepository, TaskRepository
from jarvis.app.db.mongo import get_mongo_client
from jarvis.app.db.vector_memory import VectorMemoryService
from jarvis.app.llm.router import LLMRouter
from jarvis.app.llm.prompt_builder import PromptBuilder
from jarvis.app.messaging.broker import MessageBroker


@pytest.fixture
async def test_agent_config() -> AgentConfig:
    """Create test agent configuration for Gemini."""
    return AgentConfig(
        llm_provider="gemini",
        model="gemini-2.0-flash-exp",
        temperature=0.7,
        max_tokens=8192,
        loop_interval=1.0,
        checkpoint_interval=30.0,
        max_tool_retries=3,
    )


@pytest.fixture
async def agent_repository() -> AsyncGenerator[AgentRepository, None]:
    """Create agent repository with test database."""
    client = await get_mongo_client()
    db = client.jarvis_test
    repo = AgentRepository(db)
    yield repo
    # Cleanup
    await db.agents.delete_many({})


@pytest.fixture
async def task_repository() -> AsyncGenerator[TaskRepository, None]:
    """Create task repository with test database."""
    client = await get_mongo_client()
    db = client.jarvis_test
    repo = TaskRepository(db)
    yield repo
    # Cleanup
    await db.tasks.delete_many({})


@pytest.fixture
async def vector_memory() -> VectorMemoryService:
    """Create vector memory service for testing."""
    return VectorMemoryService()


@pytest.fixture
async def message_broker() -> MessageBroker:
    """Create message broker for testing."""
    return MessageBroker()


@pytest.fixture
async def test_agent(
    test_agent_config: AgentConfig,
    agent_repository: AgentRepository,
) -> AsyncGenerator[Agent, None]:
    """Create a test agent with Gemini configuration."""
    agent = Agent(
        agent_id=f"test_agent_{datetime.utcnow().timestamp()}",
        user_id="test_user",
        name="Test Gemini Agent",
        description="Test agent for Gemini workflow validation",
        agent_type=AgentType.SUB_AGENT,
        status=AgentStatus.IDLE,
        config=test_agent_config,
        tools_available=[
            "calculator",
            "get_time",
            "execute_code",
            "web_search",
            "read_url",
        ],
        short_term_memory=[],
        context={},
    )

    # Save to database
    await agent_repository.create(agent)
    yield agent

    # Cleanup
    await agent_repository.delete(agent.agent_id)


@pytest.fixture
async def agent_runner(
    test_agent: Agent,
    agent_repository: AgentRepository,
    task_repository: TaskRepository,
    vector_memory: VectorMemoryService,
    message_broker: MessageBroker,
) -> AsyncGenerator[AgentRunner, None]:
    """Create agent runner for testing."""
    llm_router = LLMRouter()
    prompt_builder = PromptBuilder()

    runner = AgentRunner(
        agent=test_agent,
        agent_repo=agent_repository,
        task_repo=task_repository,
        vector_memory=vector_memory,
        message_broker=message_broker,
        llm_router=llm_router,
        prompt_builder=prompt_builder,
    )

    yield runner

    # Cleanup
    if runner.running:
        await runner.stop()


async def run_workflow(
    agent_runner: AgentRunner,
    message_content: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    Run a workflow by sending a message and waiting for response.

    Args:
        agent_runner: The agent runner instance
        message_content: The message to send to the agent
        timeout: Maximum time to wait for response

    Returns:
        dict containing:
            - response: The final agent response
            - tool_calls: List of tool calls made
            - iterations: Number of LLM iterations
            - duration: Total execution time
    """
    start_time = datetime.utcnow()

    # Send message to agent's inbox
    message = {
        "role": "user",
        "content": message_content,
        "timestamp": datetime.utcnow().isoformat(),
    }

    await agent_runner.message_broker.send_message(
        agent_id=agent_runner.agent.agent_id,
        message=message,
    )

    # Start agent runner if not already running
    if not agent_runner.running:
        asyncio.create_task(agent_runner.start())

    # Wait for response (poll agent's memory)
    response = None
    iterations = 0
    tool_calls = []

    elapsed = 0.0
    while elapsed < timeout:
        await asyncio.sleep(0.5)
        elapsed = (datetime.utcnow() - start_time).total_seconds()

        # Check short-term memory for assistant response
        if agent_runner.agent.short_term_memory:
            last_item = agent_runner.agent.short_term_memory[-1]
            if last_item.get("role") == "assistant":
                response = last_item.get("content")
                break

        # Count iterations and tool calls
        for item in agent_runner.agent.short_term_memory:
            if item.get("role") == "assistant":
                iterations += 1
            if "tool_calls" in item:
                tool_calls.extend(item["tool_calls"])

    duration = (datetime.utcnow() - start_time).total_seconds()

    return {
        "response": response,
        "tool_calls": tool_calls,
        "iterations": iterations,
        "duration": duration,
        "memory": agent_runner.agent.short_term_memory,
    }


def assert_tool_usage(
    workflow_result: dict[str, Any],
    expected_tools: list[str],
    min_calls: int = 1,
) -> None:
    """
    Assert that expected tools were called during workflow.

    Args:
        workflow_result: Result from run_workflow()
        expected_tools: List of tool names that should have been called
        min_calls: Minimum number of tool calls expected
    """
    tool_calls = workflow_result.get("tool_calls", [])
    called_tools = {call.get("function", {}).get("name") for call in tool_calls}

    assert len(tool_calls) >= min_calls, (
        f"Expected at least {min_calls} tool calls, got {len(tool_calls)}"
    )

    for tool in expected_tools:
        assert tool in called_tools, (
            f"Expected tool '{tool}' to be called, but it wasn't. "
            f"Called tools: {called_tools}"
        )


def assert_response_quality(
    workflow_result: dict[str, Any],
    min_length: int = 10,
    should_contain: list[str] | None = None,
) -> None:
    """
    Assert response quality metrics.

    Args:
        workflow_result: Result from run_workflow()
        min_length: Minimum response length in characters
        should_contain: Keywords that should appear in response
    """
    response = workflow_result.get("response", "")

    assert response, "No response received from agent"
    assert len(response) >= min_length, (
        f"Response too short: {len(response)} chars (expected >= {min_length})"
    )

    if should_contain:
        for keyword in should_contain:
            assert keyword.lower() in response.lower(), (
                f"Expected keyword '{keyword}' not found in response"
            )


@pytest.fixture
async def cleanup_agent(agent_repository: AgentRepository, test_agent: Agent):
    """Cleanup fixture to ensure agent is deleted after test."""
    yield
    try:
        await agent_repository.delete(test_agent.agent_id)
    except Exception:
        pass  # Agent might already be deleted
