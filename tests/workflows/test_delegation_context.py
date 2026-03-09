"""
Test Delegation Context Management

Validates context propagation between master and sub-agents:
- DelegationContext model creation and serialization
- Context packaging from master agent state
- Sequential subtask context chaining
- Delegation-aware prompt building
- Delegation result storage in long-term memory
- Capability repository persistence
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from jarvis.app.runtime.delegation_context import (
    DelegationContext,
    DelegationContextManager,
)
from jarvis.app.runtime.master_agent import (
    MasterAgentOrchestrator,
    DEFAULT_DELEGATION_TIMEOUT_SECONDS,
)
from jarvis.app.runtime.task import Task, TaskType, TaskStatus
from jarvis.app.runtime.agent_capabilities import (
    AgentCapabilitiesRegistry,
    STANDARD_CAPABILITIES,
)
from jarvis.app.llm.prompt_builder import PromptBuilder


# ============================================================
# Test DelegationContext Model
# ============================================================


class TestDelegationContextModel:
    """Test DelegationContext Pydantic model."""

    def test_create_minimal_context(self):
        """Test creating context with minimal required fields."""
        ctx = DelegationContext(
            parent_task_description="Research Python best practices",
            subtask_description="Search for Python tutorials online",
        )

        assert ctx.parent_task_description == "Research Python best practices"
        assert ctx.subtask_description == "Search for Python tutorials online"
        assert ctx.subtask_index == 0
        assert ctx.total_subtasks == 1
        assert ctx.parent_short_term_summary == ""
        assert ctx.parent_session_context == {}
        assert ctx.sibling_results == []
        assert ctx.delegation_chain_depth == 1

    def test_create_full_context(self):
        """Test creating context with all fields populated."""
        sibling_results = [
            {"capability": "web_research", "status": "completed", "output_summary": "Found 5 results"},
        ]

        ctx = DelegationContext(
            parent_task_description="Research and code",
            subtask_description="Write code based on research",
            subtask_index=1,
            total_subtasks=2,
            parent_short_term_summary="[user] Please research Python\n[assistant] Searching now...",
            parent_session_context={"last_topic": "Python", "user_preference": "concise"},
            sibling_results=sibling_results,
            master_agent_id="master_001",
            delegation_chain_depth=1,
        )

        assert ctx.subtask_index == 1
        assert ctx.total_subtasks == 2
        assert len(ctx.sibling_results) == 1
        assert ctx.master_agent_id == "master_001"

    def test_context_serialization(self):
        """Test that context can be serialized to/from dict."""
        ctx = DelegationContext(
            parent_task_description="Test task",
            subtask_description="Test subtask",
            sibling_results=[{"capability": "web_research", "status": "completed", "output_summary": "ok"}],
        )

        # Serialize
        data = ctx.model_dump()
        assert isinstance(data, dict)
        assert data["parent_task_description"] == "Test task"
        assert len(data["sibling_results"]) == 1

        # Deserialize
        ctx2 = DelegationContext(**data)
        assert ctx2.parent_task_description == ctx.parent_task_description
        assert ctx2.sibling_results == ctx.sibling_results

    def test_delegation_chain_depth_bounds(self):
        """Test that delegation_chain_depth is bounded (1-5)."""
        # Valid depth
        ctx = DelegationContext(
            parent_task_description="t",
            subtask_description="s",
            delegation_chain_depth=3,
        )
        assert ctx.delegation_chain_depth == 3

        # Depth below minimum should fail
        with pytest.raises(Exception):
            DelegationContext(
                parent_task_description="t",
                subtask_description="s",
                delegation_chain_depth=0,
            )


# ============================================================
# Test DelegationContextManager
# ============================================================


class TestDelegationContextManager:
    """Test context packaging and management."""

    def _make_mock_agent(
        self,
        agent_id: str = "master_001",
        short_term_memory: list | None = None,
        context: dict | None = None,
    ):
        """Create a mock agent entity."""
        agent = MagicMock()
        agent.agent_id = agent_id
        agent.short_term_memory = short_term_memory or []
        agent.context = context or {}
        return agent

    def test_build_context_minimal(self):
        """Test building context from agent with no memory."""
        manager = DelegationContextManager()
        agent = self._make_mock_agent()

        ctx = manager.build_context_for_sub_agent(
            master_agent=agent,
            parent_task_description="Research Python",
            subtask={"description": "Search for tutorials"},
        )

        assert isinstance(ctx, DelegationContext)
        assert ctx.parent_task_description == "Research Python"
        assert ctx.subtask_description == "Search for tutorials"
        assert ctx.parent_short_term_summary == ""
        assert ctx.master_agent_id == "master_001"

    def test_build_context_with_memory(self):
        """Test building context from agent with conversation history."""
        manager = DelegationContextManager()

        memory = [
            {"role": "user", "content": "Help me learn Python"},
            {"role": "assistant", "content": "I'd be happy to help with Python!"},
            {"role": "user", "content": "What are best practices?"},
        ]
        agent = self._make_mock_agent(short_term_memory=memory)

        ctx = manager.build_context_for_sub_agent(
            master_agent=agent,
            parent_task_description="Learn Python",
            subtask={"description": "Research best practices"},
        )

        # Memory should be summarized
        assert "user" in ctx.parent_short_term_summary
        assert "Python" in ctx.parent_short_term_summary

    def test_build_context_with_session_context(self):
        """Test building context preserves relevant session state."""
        manager = DelegationContextManager()

        agent = self._make_mock_agent(
            context={
                "last_topic": "Python",
                "user_name": "Alice",
                "_internal_key": "should_be_filtered",
            }
        )

        ctx = manager.build_context_for_sub_agent(
            master_agent=agent,
            parent_task_description="Task",
            subtask={"description": "Subtask"},
        )

        # Public keys should be included
        assert "last_topic" in ctx.parent_session_context
        assert ctx.parent_session_context["last_topic"] == "Python"

        # Internal keys should be filtered
        assert "_internal_key" not in ctx.parent_session_context

    def test_build_context_with_prior_results(self):
        """Test that prior subtask results are formatted for context."""
        manager = DelegationContextManager()
        agent = self._make_mock_agent()

        prior_results = [
            {
                "status": "completed",
                "result": {"output": "Found 5 Python tutorials"},
                "subtask": {"assigned_capability": "web_research"},
            },
        ]

        ctx = manager.build_context_for_sub_agent(
            master_agent=agent,
            parent_task_description="Research and code",
            subtask={"description": "Write code"},
            subtask_index=1,
            total_subtasks=2,
            prior_results=prior_results,
        )

        assert len(ctx.sibling_results) == 1
        assert ctx.sibling_results[0]["capability"] == "web_research"
        assert ctx.sibling_results[0]["status"] == "completed"
        assert "Python tutorials" in ctx.sibling_results[0]["output_summary"]

    def test_build_context_truncates_long_memory(self):
        """Test that very long memory entries are truncated."""
        manager = DelegationContextManager()

        long_content = "x" * 500
        memory = [{"role": "user", "content": long_content}]
        agent = self._make_mock_agent(short_term_memory=memory)

        ctx = manager.build_context_for_sub_agent(
            master_agent=agent,
            parent_task_description="Task",
            subtask={"description": "Subtask"},
        )

        # Content should be truncated
        assert len(ctx.parent_short_term_summary) < len(long_content)

    @pytest.mark.asyncio
    async def test_store_delegation_result(self):
        """Test storing delegation results in vector memory."""
        manager = DelegationContextManager()

        mock_vector_memory = AsyncMock()

        aggregated_result = {
            "status": "completed",
            "synthesized_response": "Python best practices include...",
            "successful_count": 2,
            "failed_count": 0,
        }

        await manager.store_delegation_result(
            vector_memory=mock_vector_memory,
            agent_id="master_001",
            user_id="user_001",
            task_description="Research Python best practices",
            aggregated_result=aggregated_result,
        )

        # Verify store_knowledge was called
        mock_vector_memory.store_knowledge.assert_called_once()
        call_kwargs = mock_vector_memory.store_knowledge.call_args[1]

        assert "Python best practices" in call_kwargs["content"]
        assert call_kwargs["agent_id"] == "master_001"
        assert call_kwargs["user_id"] == "user_001"
        assert call_kwargs["metadata"]["knowledge_type"] == "delegation_result"
        assert call_kwargs["metadata"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_store_delegation_result_no_memory(self):
        """Test that store_delegation_result handles missing vector memory."""
        manager = DelegationContextManager()

        # Should not raise when vector_memory is None
        await manager.store_delegation_result(
            vector_memory=None,
            agent_id="master_001",
            user_id="user_001",
            task_description="Test",
            aggregated_result={"status": "completed"},
        )


# ============================================================
# Test Delegation-Aware Prompt Building
# ============================================================


class TestDelegationPromptBuilding:
    """Test the PromptBuilder.build_delegation_messages() method."""

    def _make_mock_agent(self):
        """Create a minimal mock agent for prompt building."""
        agent = MagicMock()
        agent.short_term_memory = []
        agent.context = {}
        return agent

    def test_build_delegation_messages_basic(self):
        """Test basic delegation prompt structure."""
        builder = PromptBuilder()
        agent = self._make_mock_agent()

        delegation_context = {
            "parent_task_description": "Research and write code for Python best practices",
            "subtask_description": "Search for Python best practices online",
            "subtask_index": 0,
            "total_subtasks": 2,
            "parent_short_term_summary": "",
            "parent_session_context": {},
            "sibling_results": [],
        }

        messages = builder.build_delegation_messages(
            agent=agent,
            delegation_context=delegation_context,
        )

        # Should have system prompt + task context + user message
        assert len(messages) >= 2

        # First message should be sub-agent system prompt
        assert messages[0]["role"] == "system"
        assert "sub-agent" in messages[0]["content"].lower()

        # Last message should be the subtask
        assert messages[-1]["role"] == "user"
        assert "Python best practices" in messages[-1]["content"]

    def test_build_delegation_messages_with_parent_context(self):
        """Test that parent task context is included."""
        builder = PromptBuilder()
        agent = self._make_mock_agent()

        delegation_context = {
            "parent_task_description": "Build a web scraper for news sites",
            "subtask_description": "Write the HTTP fetching code",
            "subtask_index": 1,
            "total_subtasks": 3,
            "parent_short_term_summary": "[user] I need a news scraper",
            "parent_session_context": {"target_sites": ["bbc.com"]},
            "sibling_results": [],
        }

        messages = builder.build_delegation_messages(
            agent=agent,
            delegation_context=delegation_context,
        )

        # Find the task context message
        all_content = " ".join(m["content"] for m in messages)

        assert "web scraper" in all_content.lower()
        assert "subtask 2 of 3" in all_content.lower()
        assert "news scraper" in all_content  # From parent summary

    def test_build_delegation_messages_with_sibling_results(self):
        """Test that sibling results are included for sequential subtasks."""
        builder = PromptBuilder()
        agent = self._make_mock_agent()

        delegation_context = {
            "parent_task_description": "Research and code",
            "subtask_description": "Write code based on research findings",
            "subtask_index": 1,
            "total_subtasks": 2,
            "parent_short_term_summary": "",
            "parent_session_context": {},
            "sibling_results": [
                {
                    "capability": "web_research",
                    "status": "completed",
                    "output_summary": "Found 3 key approaches: TDD, DDD, and Clean Architecture",
                },
            ],
        }

        messages = builder.build_delegation_messages(
            agent=agent,
            delegation_context=delegation_context,
        )

        # Sibling results should be present
        all_content = " ".join(m["content"] for m in messages)
        assert "Prior Subtasks" in all_content
        assert "TDD" in all_content
        assert "web_research" in all_content

    def test_build_delegation_messages_with_long_term_memory(self):
        """Test that long-term memory is included when available."""
        builder = PromptBuilder()
        agent = self._make_mock_agent()

        delegation_context = {
            "parent_task_description": "Test task",
            "subtask_description": "Test subtask",
            "subtask_index": 0,
            "total_subtasks": 1,
            "parent_short_term_summary": "",
            "parent_session_context": {},
            "sibling_results": [],
        }

        long_term_context = {
            "interactions": [
                {"content": "Previously discussed Python patterns", "score": 0.85},
            ],
            "discoveries": [],
            "knowledge": [],
        }

        messages = builder.build_delegation_messages(
            agent=agent,
            delegation_context=delegation_context,
            long_term_context=long_term_context,
        )

        all_content = " ".join(m["content"] for m in messages)
        assert "Python patterns" in all_content


# ============================================================
# Test Context Propagation in MasterAgentOrchestrator
# ============================================================


class TestMasterContextPropagation:
    """Test that MasterAgentOrchestrator passes context to sub-agents."""

    @pytest.mark.asyncio
    async def test_delegate_passes_context(self):
        """Test that delegation messages include rich context."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "master_001"
        mock_agent.short_term_memory = [
            {"role": "user", "content": "Help me with Python"},
        ]
        mock_agent.context = {"topic": "Python"}

        orchestrator = MasterAgentOrchestrator(
            agent_id="master_001",
            master_agent=mock_agent,
        )
        orchestrator.message_broker = AsyncMock()

        subtask = {
            "subtask_id": "task_001_sub_1",
            "description": "Search for Python tutorials",
            "assigned_capability": "web_research",
        }

        delegation_info = await orchestrator.delegate_to_sub_agent(
            sub_agent_id="sub_001",
            subtask=subtask,
            parent_task_description="Learn Python step by step",
            subtask_index=0,
            total_subtasks=2,
        )

        # Verify message was published
        orchestrator.message_broker.publish.assert_called_once()
        call_args = orchestrator.message_broker.publish.call_args

        # Get the published message
        published_message = call_args[0][1]

        # Context should be populated (not empty)
        context = published_message["context"]
        assert context != {}
        assert context["parent_task_description"] == "Learn Python step by step"
        assert context["subtask_description"] == "Search for Python tutorials"
        assert context["subtask_index"] == 0
        assert context["total_subtasks"] == 2
        assert "Python" in context["parent_short_term_summary"]

    @pytest.mark.asyncio
    async def test_delegate_without_agent_uses_minimal_context(self):
        """Test delegation without master agent entity uses minimal context."""
        orchestrator = MasterAgentOrchestrator(
            agent_id="master_001",
            master_agent=None,  # No agent entity
        )
        orchestrator.message_broker = AsyncMock()

        subtask = {
            "subtask_id": "task_001_sub_1",
            "description": "Test subtask",
        }

        await orchestrator.delegate_to_sub_agent(
            sub_agent_id="sub_001",
            subtask=subtask,
            parent_task_description="Test task",
        )

        published_message = orchestrator.message_broker.publish.call_args[0][1]
        context = published_message["context"]

        # Should have minimal context
        assert context["parent_task_description"] == "Test task"
        assert context["subtask_description"] == "Test subtask"
        assert context["sibling_results"] == []

    @pytest.mark.asyncio
    async def test_delegate_passes_prior_results_for_sequential(self):
        """Test that sequential delegations pass prior results."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "master_001"
        mock_agent.short_term_memory = []
        mock_agent.context = {}

        orchestrator = MasterAgentOrchestrator(
            agent_id="master_001",
            master_agent=mock_agent,
        )
        orchestrator.message_broker = AsyncMock()

        prior_results = [
            {
                "status": "completed",
                "result": {"output": "Research findings about Python"},
                "subtask": {"assigned_capability": "web_research"},
            },
        ]

        subtask = {
            "subtask_id": "task_001_sub_2",
            "description": "Write code based on research",
            "assigned_capability": "code_execution",
        }

        await orchestrator.delegate_to_sub_agent(
            sub_agent_id="sub_002",
            subtask=subtask,
            parent_task_description="Research and code",
            subtask_index=1,
            total_subtasks=2,
            prior_results=prior_results,
        )

        published_message = orchestrator.message_broker.publish.call_args[0][1]
        context = published_message["context"]

        # Should include sibling results
        assert len(context["sibling_results"]) == 1
        assert context["sibling_results"][0]["capability"] == "web_research"
        assert context["sibling_results"][0]["status"] == "completed"


# ============================================================
# Test Capability Repository
# ============================================================


class TestCapabilityPersistence:
    """Test capability registry persistence."""

    def test_registry_with_in_memory_storage(self):
        """Test that providing storage dict disables persistence."""
        registry = AgentCapabilitiesRegistry(storage={})

        registry.register_capability("agent_001", "web_research")

        assert registry.has_capability("agent_001", "web_research")
        # _use_persistence should be False when storage is provided
        assert registry._use_persistence is False

    def test_registry_default_uses_persistence(self):
        """Test that default registry enables persistence."""
        registry = AgentCapabilitiesRegistry()

        assert registry._use_persistence is True

    @pytest.mark.asyncio
    async def test_register_capability_async(self):
        """Test async registration with persistence."""
        registry = AgentCapabilitiesRegistry(storage={})
        # Override to test the async path
        registry._use_persistence = True
        registry._repo = AsyncMock()

        await registry.register_capability_async("agent_001", "web_research")

        assert registry.has_capability("agent_001", "web_research")
        registry._repo.save_capabilities.assert_called_once_with(
            "agent_001", ["web_research"]
        )

    @pytest.mark.asyncio
    async def test_unregister_capability_async(self):
        """Test async unregistration with persistence."""
        registry = AgentCapabilitiesRegistry(storage={})
        registry._use_persistence = True
        registry._repo = AsyncMock()

        # First register
        registry.register_capability("agent_001", "web_research")

        # Then unregister async
        removed = await registry.unregister_capability_async("agent_001", "web_research")

        assert removed is True
        assert not registry.has_capability("agent_001", "web_research")
        registry._repo.save_capabilities.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_register_from_tools_async(self):
        """Test async auto-registration with persistence."""
        registry = AgentCapabilitiesRegistry(storage={})
        registry._use_persistence = True
        registry._repo = AsyncMock()

        registered = await registry.auto_register_from_tools_async(
            "agent_001", ["web_search", "read_url"]
        )

        assert "web_research" in registered
        registry._repo.save_capabilities.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_from_db(self):
        """Test loading capabilities from database."""
        registry = AgentCapabilitiesRegistry(storage={})
        registry._use_persistence = True

        mock_repo = AsyncMock()
        mock_repo.load_all.return_value = {
            "agent_001": ["web_research", "code_execution"],
            "agent_002": ["calculation"],
        }
        registry._repo = mock_repo

        await registry.load_from_db()

        assert registry.has_capability("agent_001", "web_research")
        assert registry.has_capability("agent_001", "code_execution")
        assert registry.has_capability("agent_002", "calculation")
