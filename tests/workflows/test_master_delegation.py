"""
Test Master-Sub-Agent Delegation Workflow

Validates Phase 4 multi-agent collaboration:
- Task complexity analysis
- Sub-agent spawning
- Delegation via messaging
- Result aggregation
- Full orchestration workflow
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from jarvis.app.runtime.master_agent import (
    MasterAgentOrchestrator,
    DEFAULT_DELEGATION_TIMEOUT_SECONDS,
)
from jarvis.app.runtime.task import Task, TaskType, TaskStatus
from jarvis.app.runtime.task_analyzer import TaskComplexityAnalyzer
from jarvis.app.runtime.agent_capabilities import (
    AgentCapabilitiesRegistry,
    STANDARD_CAPABILITIES,
)


# ============================================================
# Test Task Analysis
# ============================================================


class TestTaskAnalysis:
    """Test complexity analysis and delegation decisions."""

    def test_complex_task_triggers_delegation(self):
        """
        Test that complex tasks (score >= 5) are flagged for delegation.
        """
        orchestrator = MasterAgentOrchestrator(agent_id="master_001")

        # Complex task: requires web research and code execution
        complex_task = (
            "Search for Python best practices and write a script "
            "to demonstrate them step by step"
        )
        analysis = orchestrator.analyze_task_only(complex_task)

        assert analysis["complexity_score"] >= 5, (
            f"Expected score >= 5 for complex task, got {analysis['complexity_score']}"
        )
        assert analysis["should_delegate"] is True, (
            "Expected should_delegate=True for complex task"
        )
        assert len(analysis["suggested_sub_agents"]) >= 2, (
            "Expected at least 2 suggested sub-agents for complex task"
        )

    def test_simple_task_no_delegation(self):
        """
        Test that simple tasks (score < 5) are NOT flagged for delegation.
        """
        orchestrator = MasterAgentOrchestrator(agent_id="master_001")

        # Simple task: just a calculation
        simple_task = "What is 25 + 17?"
        analysis = orchestrator.analyze_task_only(simple_task)

        assert analysis["complexity_score"] < 5, (
            f"Expected score < 5 for simple task, got {analysis['complexity_score']}"
        )
        assert analysis["should_delegate"] is False, (
            "Expected should_delegate=False for simple task"
        )

    def test_multi_step_task_detection(self):
        """
        Test that multi-step tasks are detected correctly.
        """
        analyzer = TaskComplexityAnalyzer()

        multi_step_task = (
            "First, search for Python tutorials. "
            "Then, summarize the top 3 results. "
            "Finally, write a comparison."
        )
        analysis = analyzer.analyze_task_complexity(multi_step_task)

        assert analysis["indicators"]["multi_step"] is True, (
            "Expected multi_step indicator to be True"
        )
        assert analysis["estimated_subtasks"] >= 3, (
            "Expected at least 3 estimated subtasks"
        )

    def test_web_research_capability_suggested(self):
        """
        Test that web research capability is suggested for search tasks.
        """
        analyzer = TaskComplexityAnalyzer()

        search_task = "Search online for the latest Python 3.13 features"
        analysis = analyzer.analyze_task_complexity(search_task)

        assert analysis["indicators"]["requires_web"] is True
        assert "web_research" in analysis["suggested_sub_agents"]

    def test_code_execution_capability_suggested(self):
        """
        Test that code execution capability is suggested for coding tasks.
        """
        analyzer = TaskComplexityAnalyzer()

        code_task = "Write and execute Python code to calculate Fibonacci numbers"
        analysis = analyzer.analyze_task_complexity(code_task)

        assert analysis["indicators"]["requires_code"] is True
        assert "code_execution" in analysis["suggested_sub_agents"]


# ============================================================
# Test Sub-Agent Spawning
# ============================================================


class TestSubAgentSpawning:
    """Test sub-agent creation and capability registration."""

    @pytest.mark.asyncio
    async def test_spawn_sub_agent_success(self):
        """
        Test successful sub-agent spawning with valid capability.
        """
        # Create mock agent service
        mock_agent_service = AsyncMock()
        mock_agent_service.spawn_sub_agent.return_value = MagicMock(
            agent_id="sub_agent_001"
        )
        mock_agent_service.start_agent_runtime = AsyncMock()

        orchestrator = MasterAgentOrchestrator(
            agent_id="master_001",
            agent_service=mock_agent_service,
            user_id="test_user",
        )

        # Spawn sub-agent for web research
        sub_agent_id = await orchestrator.spawn_sub_agent("web_research")

        assert sub_agent_id == "sub_agent_001"
        mock_agent_service.spawn_sub_agent.assert_called_once()
        mock_agent_service.start_agent_runtime.assert_called_once_with("sub_agent_001")

        # Verify capability was registered
        assert orchestrator.capabilities_registry.has_capability(
            "sub_agent_001", "web_research"
        )

    @pytest.mark.asyncio
    async def test_spawn_without_agent_service_fails(self):
        """
        Test that spawning fails gracefully when agent_service is not available.
        """
        orchestrator = MasterAgentOrchestrator(
            agent_id="master_001",
            agent_service=None,  # No agent service
            user_id="test_user",
        )

        sub_agent_id = await orchestrator.spawn_sub_agent("web_research")

        assert sub_agent_id is None

    @pytest.mark.asyncio
    async def test_spawn_unknown_capability(self):
        """
        Test spawning with unknown capability still works (empty tools).
        """
        mock_agent_service = AsyncMock()
        mock_agent_service.spawn_sub_agent.return_value = MagicMock(
            agent_id="sub_agent_002"
        )
        mock_agent_service.start_agent_runtime = AsyncMock()

        orchestrator = MasterAgentOrchestrator(
            agent_id="master_001",
            agent_service=mock_agent_service,
            user_id="test_user",
        )

        # Spawn with unknown capability
        sub_agent_id = await orchestrator.spawn_sub_agent("unknown_capability")

        assert sub_agent_id == "sub_agent_002"
        # Should still spawn, just with empty tools


# ============================================================
# Test Delegation
# ============================================================


class TestDelegation:
    """Test message-based delegation to sub-agents."""

    @pytest.mark.asyncio
    async def test_delegate_to_sub_agent(self):
        """
        Test that delegation message is sent correctly.
        """
        orchestrator = MasterAgentOrchestrator(agent_id="master_001")

        # Mock the message broker
        orchestrator.message_broker = AsyncMock()

        subtask = {
            "subtask_id": "task_001_sub_1",
            "description": "Search for Python tutorials",
            "priority": 8,
            "timeout_seconds": 300,
            "assigned_capability": "web_research",
        }

        delegation_info = await orchestrator.delegate_to_sub_agent(
            sub_agent_id="sub_agent_001",
            subtask=subtask,
        )

        # Verify delegation info
        assert "delegation_id" in delegation_info
        assert delegation_info["sub_agent_id"] == "sub_agent_001"
        assert delegation_info["status"] == "delegated"
        assert "reply_channel" in delegation_info

        # Verify message was published
        orchestrator.message_broker.publish.assert_called_once()
        call_args = orchestrator.message_broker.publish.call_args

        # Check channel
        channel = call_args[0][0]
        assert channel == "agent:sub_agent_001:inbox"

        # Check message structure
        message = call_args[0][1]
        assert message["type"] == "delegation_request"
        assert message["delegation_id"] == delegation_info["delegation_id"]
        assert message["master_agent_id"] == "master_001"
        assert message["task"]["subtask_id"] == "task_001_sub_1"

    @pytest.mark.asyncio
    async def test_delegation_tracking(self):
        """
        Test that delegations are tracked in pending_delegations.
        """
        orchestrator = MasterAgentOrchestrator(agent_id="master_001")
        orchestrator.message_broker = AsyncMock()

        subtask = {
            "subtask_id": "task_001_sub_1",
            "description": "Test subtask",
        }

        delegation_info = await orchestrator.delegate_to_sub_agent(
            sub_agent_id="sub_agent_001",
            subtask=subtask,
        )

        delegation_id = delegation_info["delegation_id"]
        assert delegation_id in orchestrator._pending_delegations
        assert orchestrator._pending_delegations[delegation_id]["status"] == "delegated"


# ============================================================
# Test Result Aggregation
# ============================================================


class TestResultAggregation:
    """Test aggregation of sub-agent results."""

    @pytest.mark.asyncio
    async def test_aggregate_all_successful(self):
        """
        Test aggregation when all subtasks succeed.
        """
        orchestrator = MasterAgentOrchestrator(agent_id="master_001")

        subtask_results = [
            {
                "delegation_id": "del_001",
                "status": "completed",
                "result": {"output": "Research results about Python"},
                "subtask": {"assigned_capability": "web_research"},
            },
            {
                "delegation_id": "del_002",
                "status": "completed",
                "result": {"output": "Code execution result: [1, 1, 2, 3, 5]"},
                "subtask": {"assigned_capability": "code_execution"},
            },
        ]

        aggregated = await orchestrator.aggregate_results(
            subtask_results=subtask_results,
            original_task_description="Research Python and write code",
        )

        assert aggregated["status"] == "completed"
        assert aggregated["successful_count"] == 2
        assert aggregated["failed_count"] == 0
        assert len(aggregated["subtask_summaries"]) == 2

    @pytest.mark.asyncio
    async def test_aggregate_partial_failure(self):
        """
        Test aggregation when some subtasks fail.
        """
        orchestrator = MasterAgentOrchestrator(agent_id="master_001")

        subtask_results = [
            {
                "delegation_id": "del_001",
                "status": "completed",
                "result": {"output": "Research successful"},
                "subtask": {"assigned_capability": "web_research"},
            },
            {
                "delegation_id": "del_002",
                "status": "failed",
                "result": {},
                "error": "Code execution timed out",
                "subtask": {"assigned_capability": "code_execution"},
            },
        ]

        aggregated = await orchestrator.aggregate_results(
            subtask_results=subtask_results,
        )

        assert aggregated["status"] == "partial"
        assert aggregated["successful_count"] == 1
        assert aggregated["failed_count"] == 1

    @pytest.mark.asyncio
    async def test_aggregate_all_failed(self):
        """
        Test aggregation when all subtasks fail.
        """
        orchestrator = MasterAgentOrchestrator(agent_id="master_001")

        subtask_results = [
            {
                "delegation_id": "del_001",
                "status": "timeout",
                "result": {},
                "error": "Timeout after 600s",
            },
            {
                "delegation_id": "del_002",
                "status": "failed",
                "result": {},
                "error": "Agent crashed",
            },
        ]

        aggregated = await orchestrator.aggregate_results(
            subtask_results=subtask_results,
        )

        assert aggregated["status"] == "failed"
        assert aggregated["successful_count"] == 0
        assert aggregated["failed_count"] == 2
        assert "Unable to complete task" in aggregated["synthesized_response"]


# ============================================================
# Test Full Orchestration
# ============================================================


class TestEndToEndDelegation:
    """Test complete delegation workflow."""

    @pytest.mark.asyncio
    async def test_can_delegate_check(self):
        """
        Test _can_delegate returns correct values based on dependencies.
        """
        # Without dependencies
        orchestrator = MasterAgentOrchestrator(agent_id="master_001")
        assert orchestrator._can_delegate() is False

        # With partial dependencies
        orchestrator._agent_service = MagicMock()
        assert orchestrator._can_delegate() is False

        # With all dependencies
        orchestrator._llm_router = MagicMock()
        orchestrator._user_id = "test_user"
        assert orchestrator._can_delegate() is True

    @pytest.mark.asyncio
    async def test_handle_task_simple_direct_execution(self):
        """
        Test that simple tasks are executed directly.
        """
        mock_agent_service = AsyncMock()
        mock_llm_router = AsyncMock()

        orchestrator = MasterAgentOrchestrator(
            agent_id="master_001",
            agent_service=mock_agent_service,
            llm_router=mock_llm_router,
            user_id="test_user",
        )

        simple_task = Task(
            task_id="task_001",
            agent_id="master_001",
            task_description="Calculate 2 + 2",
            task_type=TaskType.CUSTOM,
            status=TaskStatus.PENDING,
            priority=5,
        )

        result = await orchestrator.handle_task(simple_task)

        assert result["strategy"] == "direct"
        assert result["analysis"]["should_delegate"] is False

    @pytest.mark.asyncio
    async def test_cleanup_sub_agents(self):
        """
        Test that spawned sub-agents are cleaned up after orchestration.
        """
        mock_agent_service = AsyncMock()

        orchestrator = MasterAgentOrchestrator(
            agent_id="master_001",
            agent_service=mock_agent_service,
            user_id="test_user",
        )

        # Simulate spawned agents
        orchestrator._spawned_sub_agents = ["sub_001", "sub_002"]

        await orchestrator.cleanup_sub_agents()

        # Verify terminate was called for each
        assert mock_agent_service.terminate_agent.call_count == 2
        mock_agent_service.terminate_agent.assert_any_call("sub_001")
        mock_agent_service.terminate_agent.assert_any_call("sub_002")

        # Verify tracking is cleared
        assert len(orchestrator._spawned_sub_agents) == 0


# ============================================================
# Test Capabilities Registry
# ============================================================


class TestCapabilitiesRegistry:
    """Test agent capabilities registry."""

    def test_standard_capabilities_defined(self):
        """
        Test that standard capabilities are properly defined.
        """
        expected_capabilities = [
            "web_research",
            "code_execution",
            "calculation",
            "time_awareness",
            "general_assistance",
            "task_orchestration",
        ]

        for cap_id in expected_capabilities:
            assert cap_id in STANDARD_CAPABILITIES, (
                f"Expected capability '{cap_id}' in STANDARD_CAPABILITIES"
            )

    def test_find_capable_agents(self):
        """
        Test finding agents by capability.
        """
        registry = AgentCapabilitiesRegistry()

        # Register agents with capabilities
        registry.register_capability("agent_001", "web_research")
        registry.register_capability("agent_002", "web_research")
        registry.register_capability("agent_003", "code_execution")

        # Find web_research agents
        capable = registry.find_capable_agents("web_research")
        assert len(capable) == 2
        assert "agent_001" in capable
        assert "agent_002" in capable

        # Find code_execution agents
        capable = registry.find_capable_agents("code_execution")
        assert len(capable) == 1
        assert "agent_003" in capable

    def test_auto_register_from_tools(self):
        """
        Test automatic capability registration based on tools.
        """
        registry = AgentCapabilitiesRegistry()

        # Agent with web tools
        tools = ["web_search", "read_url"]
        registered = registry.auto_register_from_tools("agent_001", tools)

        assert "web_research" in registered

        # Agent with code tool
        tools = ["execute_code"]
        registered = registry.auto_register_from_tools("agent_002", tools)

        assert "code_execution" in registered

    def test_get_capability_definition(self):
        """
        Test retrieving capability definitions.
        """
        registry = AgentCapabilitiesRegistry()

        capability = registry.get_capability_definition("web_research")
        assert capability is not None
        assert capability.name == "Web Research"
        assert "web_search" in capability.required_tools

        # Unknown capability
        capability = registry.get_capability_definition("unknown")
        assert capability is None
