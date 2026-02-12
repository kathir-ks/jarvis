"""Unit tests for Agent and Task models."""
from __future__ import annotations

from datetime import datetime

import pytest

from jarvis.app.runtime.agent import (
    Agent,
    AgentConfig,
    AgentMemoryRef,
    AgentStatus,
    AgentType,
)
from jarvis.app.runtime.task import (
    Task,
    TaskStatus,
    TaskType,
)


# ---------------------------------------------------------------------------
# Test: Agent model
# ---------------------------------------------------------------------------

class TestAgentModel:
    """Test Agent Pydantic model."""

    def test_create_master_agent(self):
        agent = Agent(
            _id="agent-1",
            user_id="user-1",
            agent_type=AgentType.MASTER,
        )
        assert agent.agent_id == "agent-1"
        assert agent.user_id == "user-1"
        assert agent.agent_type == AgentType.MASTER
        assert agent.status == AgentStatus.IDLE
        assert agent.can_spawn_sub_agent() is True

    def test_create_sub_agent(self):
        agent = Agent(
            _id="sub-1",
            user_id="user-1",
            agent_type=AgentType.SUB_AGENT,
            parent_agent_id="agent-1",
        )
        assert agent.parent_agent_id == "agent-1"
        assert agent.can_spawn_sub_agent() is False

    def test_is_active_states(self):
        for status in [AgentStatus.IDLE, AgentStatus.RUNNING, AgentStatus.WAITING_APPROVAL]:
            agent = Agent(_id="a", user_id="u", agent_type=AgentType.MASTER, status=status)
            assert agent.is_active() is True

        for status in [AgentStatus.ERROR, AgentStatus.TERMINATED]:
            agent = Agent(_id="a", user_id="u", agent_type=AgentType.MASTER, status=status)
            assert agent.is_active() is False

    def test_default_config(self):
        agent = Agent(_id="a", user_id="u", agent_type=AgentType.MASTER)
        assert agent.config.llm_provider == "openai"
        assert agent.config.model == "gpt-4"
        assert agent.config.temperature == 0.7
        assert agent.config.loop_interval_seconds == 1
        assert agent.config.checkpoint_interval_seconds == 30

    def test_custom_config(self):
        config = AgentConfig(
            llm_provider="gemini",
            model="gemini-2.0-flash",
            temperature=0.3,
            max_tokens=4096,
        )
        agent = Agent(_id="a", user_id="u", agent_type=AgentType.MASTER, config=config)
        assert agent.config.llm_provider == "gemini"
        assert agent.config.max_tokens == 4096

    def test_mcp_config(self):
        config = AgentConfig(
            mcp_server_url="http://localhost:8000/mcp",
            mcp_timeout_seconds=60,
        )
        assert config.mcp_server_url == "http://localhost:8000/mcp"
        assert config.mcp_timeout_seconds == 60

    def test_short_term_memory_default(self):
        agent = Agent(_id="a", user_id="u", agent_type=AgentType.MASTER)
        assert agent.short_term_memory == []

    def test_to_mongo_dict(self):
        agent = Agent(
            _id="agent-1",
            user_id="user-1",
            agent_type=AgentType.MASTER,
            tools_available=["calculator"],
        )
        doc = agent.to_mongo_dict()
        assert doc["_id"] == "agent-1"
        assert doc["user_id"] == "user-1"
        assert "calculator" in doc["tools_available"]

    def test_context_dict(self):
        agent = Agent(
            _id="a", user_id="u", agent_type=AgentType.MASTER,
            context={"topic": "AI", "step": 3},
        )
        assert agent.context["topic"] == "AI"
        assert agent.context["step"] == 3


# ---------------------------------------------------------------------------
# Test: AgentConfig
# ---------------------------------------------------------------------------

class TestAgentConfig:
    """Test AgentConfig defaults and validation."""

    def test_defaults(self):
        config = AgentConfig()
        assert config.llm_provider == "openai"
        assert config.model == "gpt-4"
        assert config.temperature == 0.7
        assert config.max_tokens == 2000
        assert config.mcp_server_url is None
        assert config.mcp_timeout_seconds == 30


# ---------------------------------------------------------------------------
# Test: Task model
# ---------------------------------------------------------------------------

class TestTaskModel:
    """Test Task Pydantic model."""

    def test_create_task(self):
        task = Task(
            _id="task-1",
            agent_id="agent-1",
            task_type=TaskType.RESEARCH,
            task_description="Research AI trends",
        )
        assert task.task_id == "task-1"
        assert task.task_type == TaskType.RESEARCH
        assert task.status == TaskStatus.PENDING

    def test_can_execute(self):
        task = Task(
            _id="t", agent_id="a",
            task_type=TaskType.CUSTOM,
            task_description="test",
            status=TaskStatus.PENDING,
        )
        assert task.can_execute() is True

        task.status = TaskStatus.RUNNING
        assert task.can_execute() is False

    def test_should_cancel(self):
        task = Task(
            _id="t", agent_id="a",
            task_type=TaskType.CUSTOM,
            task_description="test",
            status=TaskStatus.CANCELLED_REQUESTED,
        )
        assert task.should_cancel() is True

        task.status = TaskStatus.RUNNING
        assert task.should_cancel() is False

    def test_task_with_dependencies(self):
        task = Task(
            _id="t2", agent_id="a",
            task_type=TaskType.CUSTOM,
            task_description="depends on t1",
            depends_on=["t1"],
        )
        assert task.depends_on == ["t1"]

    def test_task_priority(self):
        task = Task(
            _id="t", agent_id="a",
            task_type=TaskType.RESEARCH,
            task_description="high priority",
            priority=9,
        )
        assert task.priority == 9

    def test_task_retry_config(self):
        task = Task(
            _id="t", agent_id="a",
            task_type=TaskType.CUSTOM,
            task_description="retriable",
            max_retries=5,
            retry_count=2,
        )
        assert task.max_retries == 5
        assert task.retry_count == 2

    def test_task_types(self):
        for tt in [TaskType.RESEARCH, TaskType.EXPLORATION, TaskType.PURCHASE,
                    TaskType.BOOKING, TaskType.CUSTOM]:
            task = Task(_id="t", agent_id="a", task_type=tt, task_description="x")
            assert task.task_type == tt

    def test_to_mongo_dict(self):
        task = Task(
            _id="task-1",
            agent_id="agent-1",
            task_type=TaskType.RESEARCH,
            task_description="test",
        )
        doc = task.to_mongo_dict()
        assert doc["_id"] == "task-1"
        assert doc["agent_id"] == "agent-1"
