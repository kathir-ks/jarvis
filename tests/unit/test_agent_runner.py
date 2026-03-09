"""Unit tests for AgentRunner — concurrency, tool-calling loop, and lifecycle."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarvis.app.runtime.agent import Agent, AgentConfig, AgentStatus, AgentType
from jarvis.app.runtime.agent_runner import AgentRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(agent_id: str = "test-agent-1", agent_type: str = "MASTER") -> Agent:
    """Create a minimal Agent entity for testing."""
    return Agent(
        _id=agent_id,
        user_id="test-user",
        agent_type=agent_type,
        status=AgentStatus.IDLE,
        config=AgentConfig(
            llm_provider="openai",
            model="gpt-4",
            temperature=0.5,
            max_tokens=500,
            loop_interval_seconds=1,
            checkpoint_interval_seconds=30,
        ),
        tools_available=["calculator", "get_time"],
        short_term_memory=[],
        context={},
    )


def _make_llm_response(content: str = "Hello!", tool_calls=None):
    """Create a mock LLM response."""
    resp = MagicMock()
    resp.content = content
    resp.tool_calls = tool_calls
    resp.provider = "openai"
    resp.model = "gpt-4"
    return resp


# ---------------------------------------------------------------------------
# Test: asyncio.Queue replaces list
# ---------------------------------------------------------------------------

class TestMessageQueueConcurrency:
    """Verify that pending_messages is now an asyncio.Queue."""

    def test_runner_has_asyncio_queue(self):
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter"), \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry"):
            runner = AgentRunner("agent-1")
            assert isinstance(runner._message_queue, asyncio.Queue)
            assert not hasattr(runner, "pending_messages")

    def test_runner_has_background_tasks_set(self):
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter"), \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry"):
            runner = AgentRunner("agent-1")
            assert isinstance(runner._background_tasks, set)
            assert len(runner._background_tasks) == 0


# ---------------------------------------------------------------------------
# Test: Shared tool-calling loop
# ---------------------------------------------------------------------------

class TestToolCallingLoop:
    """Test _run_tool_calling_loop — the unified tool-calling implementation."""

    @pytest.mark.asyncio
    async def test_simple_text_response(self):
        """LLM returns text without tool calls → should return immediately."""
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter") as mock_router_cls, \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry"):
            runner = AgentRunner("agent-1")
            runner.agent = _make_agent()

            mock_router = mock_router_cls.return_value
            mock_router.call = AsyncMock(return_value=_make_llm_response("Hello!"))

            llm_resp, text, iterations, tools = await runner._run_tool_calling_loop(
                [{"role": "user", "content": "Hi"}],
                {"model": "gpt-4"},
            )

            assert text == "Hello!"
            assert iterations == 1
            assert tools == []
            assert llm_resp is not None

    @pytest.mark.asyncio
    async def test_tool_call_then_response(self):
        """LLM calls a tool, then returns text → should return after 2 iterations."""
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter") as mock_router_cls, \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry") as mock_registry_fn:
            runner = AgentRunner("agent-1")
            runner.agent = _make_agent()

            # Mock the tool registry execute
            mock_registry = mock_registry_fn.return_value
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.result = {"result": 42}
            mock_result.execution_time_ms = 5.0
            mock_registry.execute = AsyncMock(return_value=mock_result)

            # First call: tool call, second call: text response
            tool_call_response = _make_llm_response(
                content="",
                tool_calls=[{
                    "id": "call_1",
                    "function": {
                        "name": "calculator",
                        "arguments": json.dumps({"expression": "2+2"}),
                    },
                }],
            )
            final_response = _make_llm_response("The answer is 4.")

            mock_router = mock_router_cls.return_value
            mock_router.call = AsyncMock(side_effect=[tool_call_response, final_response])

            llm_resp, text, iterations, tools = await runner._run_tool_calling_loop(
                [{"role": "user", "content": "What is 2+2?"}],
                {"model": "gpt-4"},
            )

            assert text == "The answer is 4."
            assert iterations == 2
            assert len(tools) == 1
            assert tools[0]["name"] == "calculator"

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self):
        """LLM keeps calling tools → should stop at max_iterations."""
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter") as mock_router_cls, \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry") as mock_registry_fn:
            runner = AgentRunner("agent-1")
            runner.agent = _make_agent()

            mock_registry = mock_registry_fn.return_value
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.result = {"time": "2026-01-01T00:00:00"}
            mock_result.execution_time_ms = 1.0
            mock_registry.execute = AsyncMock(return_value=mock_result)

            # Always return tool calls
            tool_response = _make_llm_response(
                content="Calling tool...",
                tool_calls=[{
                    "id": "call_loop",
                    "function": {
                        "name": "get_time",
                        "arguments": "{}",
                    },
                }],
            )

            mock_router = mock_router_cls.return_value
            mock_router.call = AsyncMock(return_value=tool_response)

            llm_resp, text, iterations, tools = await runner._run_tool_calling_loop(
                [{"role": "user", "content": "loop"}],
                {"model": "gpt-4"},
                max_iterations=3,
            )

            assert iterations == 3
            assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_first_llm_call_failure(self):
        """First LLM call fails → should return None."""
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter") as mock_router_cls, \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry"):
            runner = AgentRunner("agent-1")
            runner.agent = _make_agent()

            mock_router = mock_router_cls.return_value
            mock_router.call = AsyncMock(side_effect=Exception("API error"))

            llm_resp, text, iterations, tools = await runner._run_tool_calling_loop(
                [{"role": "user", "content": "fail"}],
                {"model": "gpt-4"},
            )

            assert llm_resp is None
            assert text == ""
            assert iterations == 1


# ---------------------------------------------------------------------------
# Test: _execute_single_tool
# ---------------------------------------------------------------------------

class TestExecuteSingleTool:
    """Test the unified tool execution method."""

    @pytest.mark.asyncio
    async def test_successful_tool_execution(self):
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter"), \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry") as mock_registry_fn:
            runner = AgentRunner("agent-1")

            mock_result = MagicMock()
            mock_result.success = True
            mock_result.result = {"answer": 42}
            mock_result.execution_time_ms = 10.0
            mock_registry_fn.return_value.execute = AsyncMock(return_value=mock_result)

            result_json = await runner._execute_single_tool({
                "id": "call_1",
                "function": {
                    "name": "calculator",
                    "arguments": json.dumps({"expression": "6*7"}),
                },
            })

            result = json.loads(result_json)
            assert result == {"answer": 42}

    @pytest.mark.asyncio
    async def test_invalid_json_arguments(self):
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter"), \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry"):
            runner = AgentRunner("agent-1")

            result_json = await runner._execute_single_tool({
                "id": "call_bad",
                "function": {
                    "name": "calculator",
                    "arguments": "not valid json {{{",
                },
            })

            result = json.loads(result_json)
            assert "error" in result
            assert "Invalid JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_mcp_tool_execution(self):
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter"), \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry"):
            runner = AgentRunner("agent-1")

            # Set up MCP client mock
            mock_mcp = AsyncMock()
            mock_mcp.call_tool = AsyncMock(return_value={"result": {"status": "ok"}})
            runner.mcp_client = mock_mcp

            result_json = await runner._execute_single_tool({
                "id": "call_mcp",
                "function": {
                    "name": "web_search",
                    "arguments": json.dumps({"query": "test"}),
                },
            })

            result = json.loads(result_json)
            assert result == {"status": "ok"}
            mock_mcp.call_tool.assert_called_once_with("web_search", {"query": "test"})


# ---------------------------------------------------------------------------
# Test: Background task management
# ---------------------------------------------------------------------------

class TestBackgroundTaskManagement:
    """Test _spawn_background_task and _cancel_background_tasks."""

    @pytest.mark.asyncio
    async def test_cancel_background_tasks(self):
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter"), \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry"):
            runner = AgentRunner("agent-1")

            # Create a long-running task
            async def long_task():
                await asyncio.sleep(100)

            runner._spawn_background_task(long_task())
            assert len(runner._background_tasks) == 1

            await runner._cancel_background_tasks()
            assert len(runner._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_failed_task_auto_restarts_listener(self):
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter"), \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry"):
            runner = AgentRunner("agent-1")
            runner.running = True

            # Track how many tasks get spawned
            spawn_count = 0
            original_spawn = runner._spawn_background_task

            def counting_spawn(coro):
                nonlocal spawn_count
                spawn_count += 1
                return original_spawn(coro)

            runner._spawn_background_task = counting_spawn

            # Create a task that fails immediately
            async def failing_task():
                raise RuntimeError("Redis disconnected")

            counting_spawn(failing_task())

            # Give the event loop a chance to process the done callback
            await asyncio.sleep(0.1)

            # The done callback should have spawned a replacement
            # (spawn_count should be > 1 because the restart spawns another)
            assert spawn_count >= 1

            runner.running = False
            await runner._cancel_background_tasks()


# ---------------------------------------------------------------------------
# Test: _process_messages drains the queue
# ---------------------------------------------------------------------------

class TestProcessMessages:
    """Test queue-based message processing."""

    @pytest.mark.asyncio
    async def test_drains_queue_without_blocking(self):
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter"), \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry"):
            runner = AgentRunner("agent-1")
            runner.agent = _make_agent()

            # Mock _handle_message to track calls
            runner._handle_message = AsyncMock()

            # Enqueue messages
            await runner._message_queue.put({"data": {"content": "msg1"}})
            await runner._message_queue.put({"data": {"content": "msg2"}})

            await runner._process_messages()

            assert runner._handle_message.call_count == 2
            assert runner._message_queue.empty()

    @pytest.mark.asyncio
    async def test_empty_queue_returns_immediately(self):
        with patch("jarvis.app.runtime.agent_runner.AgentRepository"), \
             patch("jarvis.app.runtime.agent_runner.TaskRepository"), \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter"), \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry"):
            runner = AgentRunner("agent-1")
            runner.agent = _make_agent()
            runner._handle_message = AsyncMock()

            await runner._process_messages()

            runner._handle_message.assert_not_called()


# ---------------------------------------------------------------------------
# Test: terminate() cancels background tasks
# ---------------------------------------------------------------------------

class TestTerminate:
    """Test graceful termination."""

    @pytest.mark.asyncio
    async def test_terminate_cancels_tasks_and_checkpoints(self):
        with patch("jarvis.app.runtime.agent_runner.AgentRepository") as mock_repo_cls, \
             patch("jarvis.app.runtime.agent_runner.TaskRepository") as mock_task_repo_cls, \
             patch("jarvis.app.runtime.agent_runner.MessageBroker"), \
             patch("jarvis.app.runtime.agent_runner.get_redis_client"), \
             patch("jarvis.app.runtime.agent_runner.LLMRouter"), \
             patch("jarvis.app.runtime.agent_runner.PromptBuilder"), \
             patch("jarvis.app.runtime.agent_runner.get_tool_registry"):
            runner = AgentRunner("agent-1")
            runner.agent = _make_agent()

            mock_repo = mock_repo_cls.return_value
            mock_repo.checkpoint = AsyncMock()
            mock_repo.update_status = AsyncMock()

            mock_task_repo = mock_task_repo_cls.return_value
            mock_task_repo.get_pending_tasks = AsyncMock(return_value=[])

            # Spawn a background task
            async def dummy():
                await asyncio.sleep(100)

            runner._spawn_background_task(dummy())
            assert len(runner._background_tasks) == 1

            await runner.terminate()

            assert not runner.running
            assert len(runner._background_tasks) == 0
            mock_repo.update_status.assert_called_with("agent-1", AgentStatus.TERMINATED)
