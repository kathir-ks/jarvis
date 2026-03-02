"""Tests for the Agent Directory Service.

Covers:
- Agent registration and unregistration
- Heartbeat processing and stale detection
- Health-aware, load-balanced agent selection
- Performance tracking
- Stale agent cleanup
"""
import time
import pytest

from jarvis.app.runtime.agent_directory import (
    AgentDirectory,
    AgentDirectoryEntry,
    AgentHealthStatus,
    AgentPerformanceStats,
)


class TestAgentPerformanceStats:

    def test_initial_stats(self):
        stats = AgentPerformanceStats()
        assert stats.total_tasks == 0
        assert stats.success_rate == 1.0  # Assume healthy
        assert stats.avg_response_time_ms == 0.0

    def test_record_success(self):
        stats = AgentPerformanceStats()
        stats.record_success(150.0)
        assert stats.total_tasks == 1
        assert stats.successful_tasks == 1
        assert stats.success_rate == 1.0
        assert stats.avg_response_time_ms == 150.0

    def test_record_failure(self):
        stats = AgentPerformanceStats()
        stats.record_failure()
        assert stats.total_tasks == 1
        assert stats.failed_tasks == 1
        assert stats.success_rate == 0.0

    def test_mixed_outcomes(self):
        stats = AgentPerformanceStats()
        stats.record_success(100.0)
        stats.record_success(200.0)
        stats.record_failure()
        assert stats.total_tasks == 3
        assert stats.success_rate == pytest.approx(2 / 3)
        assert stats.avg_response_time_ms == 150.0


class TestAgentDirectoryEntry:

    def test_is_available_when_healthy(self):
        entry = AgentDirectoryEntry(agent_id="a1")
        assert entry.is_available is True

    def test_not_available_when_at_capacity(self):
        entry = AgentDirectoryEntry(
            agent_id="a1",
            active_tasks=3,
            max_concurrent_tasks=3,
        )
        assert entry.is_available is False

    def test_not_available_when_unresponsive(self):
        entry = AgentDirectoryEntry(
            agent_id="a1",
            health=AgentHealthStatus.UNRESPONSIVE,
        )
        assert entry.is_available is False

    def test_load_factor(self):
        entry = AgentDirectoryEntry(
            agent_id="a1",
            active_tasks=1,
            max_concurrent_tasks=4,
        )
        assert entry.load_factor == 0.25

    def test_is_stale(self):
        entry = AgentDirectoryEntry(agent_id="a1")
        # Force last_heartbeat to be old
        entry.last_heartbeat = time.monotonic() - 100
        assert entry.is_stale(threshold_seconds=90) is True

    def test_not_stale(self):
        entry = AgentDirectoryEntry(agent_id="a1")
        assert entry.is_stale(threshold_seconds=90) is False

    def test_update_heartbeat(self):
        entry = AgentDirectoryEntry(agent_id="a1")
        old_heartbeat = entry.last_heartbeat

        entry.update_heartbeat(status="busy", active_tasks=2, metadata={"cpu": 75})
        assert entry.health == AgentHealthStatus.BUSY
        assert entry.active_tasks == 2
        assert entry.metadata["cpu"] == 75
        assert entry.last_heartbeat >= old_heartbeat


class TestAgentDirectory:

    @pytest.fixture
    def directory(self):
        return AgentDirectory(heartbeat_ttl=30, stale_threshold=60)

    def test_register_agent(self, directory):
        entry = directory.register(
            agent_id="agent_1",
            capabilities=["web_research"],
        )
        assert entry.agent_id == "agent_1"
        assert "web_research" in entry.capabilities

    def test_unregister_agent(self, directory):
        directory.register(agent_id="agent_1")
        assert directory.unregister("agent_1") is True
        assert directory.get("agent_1") is None

    def test_unregister_nonexistent(self, directory):
        assert directory.unregister("ghost") is False

    def test_heartbeat_updates_entry(self, directory):
        directory.register(agent_id="agent_1")
        result = directory.heartbeat("agent_1", status="busy", active_tasks=3)
        assert result is True

        entry = directory.get("agent_1")
        assert entry.health == AgentHealthStatus.BUSY
        assert entry.active_tasks == 3

    def test_heartbeat_unregistered_agent(self, directory):
        assert directory.heartbeat("ghost") is False

    def test_find_agent_by_capability(self, directory):
        directory.register(agent_id="a1", capabilities=["web_research"])
        directory.register(agent_id="a2", capabilities=["code_execution"])

        result = directory.find_agent("web_research")
        assert result == "a1"

    def test_find_agent_returns_none_when_no_match(self, directory):
        directory.register(agent_id="a1", capabilities=["web_research"])
        assert directory.find_agent("code_execution") is None

    def test_find_agent_prefers_least_loaded(self, directory):
        directory.register(agent_id="a1", capabilities=["web_research"])
        directory.register(agent_id="a2", capabilities=["web_research"])

        # Make a1 busier
        directory.get("a1").active_tasks = 2
        directory.get("a2").active_tasks = 0

        result = directory.find_agent("web_research", prefer_least_loaded=True)
        assert result == "a2"

    def test_find_agent_skips_stale(self, directory):
        directory.register(agent_id="a1", capabilities=["web_research"])
        # Make a1 stale
        directory.get("a1").last_heartbeat = time.monotonic() - 200

        assert directory.find_agent("web_research") is None

    def test_find_all_with_filters(self, directory):
        directory.register(agent_id="a1", agent_type="master", capabilities=["web_research"])
        directory.register(agent_id="a2", agent_type="sub_agent", capabilities=["web_research"])
        directory.register(agent_id="a3", agent_type="sub_agent", capabilities=["code_execution"])

        # Filter by type
        results = directory.find_all(agent_type="sub_agent")
        assert len(results) == 2

        # Filter by capability
        results = directory.find_all(capability="web_research")
        assert len(results) == 2

        # Both filters
        results = directory.find_all(capability="web_research", agent_type="sub_agent")
        assert len(results) == 1
        assert results[0].agent_id == "a2"

    def test_record_task_outcome(self, directory):
        directory.register(agent_id="a1")
        directory.record_task_outcome("a1", success=True, response_time_ms=250.0)
        directory.record_task_outcome("a1", success=False)

        entry = directory.get("a1")
        assert entry.performance.total_tasks == 2
        assert entry.performance.successful_tasks == 1
        assert entry.performance.failed_tasks == 1

    def test_increment_decrement_active_tasks(self, directory):
        directory.register(agent_id="a1")
        directory.increment_active_tasks("a1")
        directory.increment_active_tasks("a1")
        assert directory.get("a1").active_tasks == 2

        directory.decrement_active_tasks("a1")
        assert directory.get("a1").active_tasks == 1

        # Should not go below 0
        directory.decrement_active_tasks("a1")
        directory.decrement_active_tasks("a1")
        assert directory.get("a1").active_tasks == 0

    def test_cleanup_stale_agents(self, directory):
        directory.register(agent_id="a1")
        directory.register(agent_id="a2")

        # Make a1 stale
        directory.get("a1").last_heartbeat = time.monotonic() - 200

        removed = directory.cleanup_stale()
        assert "a1" in removed
        assert directory.get("a1") is None
        assert directory.get("a2") is not None

    def test_health_summary(self, directory):
        directory.register(agent_id="a1")
        directory.register(agent_id="a2")
        directory.get("a2").health = AgentHealthStatus.DEGRADED

        summary = directory.get_health_summary()
        assert summary["total_agents"] == 2
        assert summary["healthy"] == 1
        assert summary["degraded"] == 1

    def test_find_agent_prefers_better_success_rate(self, directory):
        """When load is equal, prefer agent with better success rate."""
        directory.register(agent_id="a1", capabilities=["web_research"])
        directory.register(agent_id="a2", capabilities=["web_research"])

        # a1 has worse success rate
        directory.get("a1").performance.record_success(100.0)
        directory.get("a1").performance.record_failure()
        directory.get("a1").performance.record_failure()

        # a2 has perfect success rate
        directory.get("a2").performance.record_success(100.0)

        result = directory.find_agent("web_research")
        assert result == "a2"
