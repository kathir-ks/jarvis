"""
Agent Directory Service

Enhanced agent discovery with:
- Agent registration with health status and metadata
- Heartbeat monitoring with configurable TTL
- Load-aware agent selection (least-busy first)
- Performance tracking (success rate, avg response time)
- Automatic stale agent detection and cleanup

Replaces the simple capability-based lookup with a production-grade
directory that supports health-aware, load-balanced agent selection.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HEARTBEAT_TTL_SECONDS = 30
DEFAULT_STALE_THRESHOLD_SECONDS = 90


# ---------------------------------------------------------------------------
# Agent health model
# ---------------------------------------------------------------------------

class AgentHealthStatus(str, Enum):
    """Health status of a registered agent."""
    HEALTHY = "healthy"
    BUSY = "busy"
    DEGRADED = "degraded"
    UNRESPONSIVE = "unresponsive"
    TERMINATED = "terminated"


@dataclass
class AgentPerformanceStats:
    """Tracks agent performance metrics for selection decisions."""
    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    total_response_time_ms: float = 0.0
    last_task_at: float = 0.0

    @property
    def success_rate(self) -> float:
        """Success rate as a fraction [0, 1]."""
        if self.total_tasks == 0:
            return 1.0  # Assume healthy until proven otherwise
        return self.successful_tasks / self.total_tasks

    @property
    def avg_response_time_ms(self) -> float:
        """Average response time in milliseconds."""
        if self.successful_tasks == 0:
            return 0.0
        return self.total_response_time_ms / self.successful_tasks

    def record_success(self, response_time_ms: float) -> None:
        """Record a successful task execution."""
        self.total_tasks += 1
        self.successful_tasks += 1
        self.total_response_time_ms += response_time_ms
        self.last_task_at = time.monotonic()

    def record_failure(self) -> None:
        """Record a failed task execution."""
        self.total_tasks += 1
        self.failed_tasks += 1
        self.last_task_at = time.monotonic()


@dataclass
class AgentDirectoryEntry:
    """An entry in the agent directory."""
    agent_id: str
    agent_type: str = "sub_agent"
    capabilities: list[str] = field(default_factory=list)
    health: AgentHealthStatus = AgentHealthStatus.HEALTHY
    active_tasks: int = 0
    max_concurrent_tasks: int = 3
    last_heartbeat: float = field(default_factory=time.monotonic)
    registered_at: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)
    performance: AgentPerformanceStats = field(default_factory=AgentPerformanceStats)

    @property
    def is_available(self) -> bool:
        """Whether the agent can accept new work."""
        return (
            self.health in (AgentHealthStatus.HEALTHY, AgentHealthStatus.BUSY)
            and self.active_tasks < self.max_concurrent_tasks
        )

    @property
    def load_factor(self) -> float:
        """Load as a fraction of capacity [0, 1]."""
        if self.max_concurrent_tasks == 0:
            return 1.0
        return self.active_tasks / self.max_concurrent_tasks

    def update_heartbeat(
        self,
        status: str = "alive",
        active_tasks: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update heartbeat and metadata from a heartbeat message."""
        self.last_heartbeat = time.monotonic()

        if status == "alive":
            self.health = AgentHealthStatus.HEALTHY
        elif status == "busy":
            self.health = AgentHealthStatus.BUSY
        elif status == "degraded":
            self.health = AgentHealthStatus.DEGRADED

        if active_tasks is not None:
            self.active_tasks = active_tasks
        if metadata:
            self.metadata.update(metadata)

    def is_stale(self, threshold_seconds: float = DEFAULT_STALE_THRESHOLD_SECONDS) -> bool:
        """Check if agent hasn't sent a heartbeat within the threshold."""
        return (time.monotonic() - self.last_heartbeat) > threshold_seconds


# ---------------------------------------------------------------------------
# Agent Directory
# ---------------------------------------------------------------------------

class AgentDirectory:
    """
    Agent directory with health-aware discovery and load balancing.

    Provides:
    - register() / unregister() for agent lifecycle
    - heartbeat() for liveness tracking
    - find_agent() for capability+health+load aware selection
    - find_all() for listing all agents matching criteria
    - record_task_outcome() for performance tracking
    - cleanup_stale() for evicting unresponsive agents
    """

    def __init__(
        self,
        heartbeat_ttl: float = DEFAULT_HEARTBEAT_TTL_SECONDS,
        stale_threshold: float = DEFAULT_STALE_THRESHOLD_SECONDS,
    ):
        self._entries: dict[str, AgentDirectoryEntry] = {}
        self._heartbeat_ttl = heartbeat_ttl
        self._stale_threshold = stale_threshold

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        agent_id: str,
        agent_type: str = "sub_agent",
        capabilities: list[str] | None = None,
        max_concurrent_tasks: int = 3,
        metadata: dict[str, Any] | None = None,
    ) -> AgentDirectoryEntry:
        """
        Register an agent in the directory.

        Args:
            agent_id: Unique agent identifier.
            agent_type: Agent type (master, sub_agent).
            capabilities: List of capability IDs.
            max_concurrent_tasks: Max parallel tasks for this agent.
            metadata: Extra metadata (llm_provider, model, etc.).

        Returns:
            The created directory entry.
        """
        entry = AgentDirectoryEntry(
            agent_id=agent_id,
            agent_type=agent_type,
            capabilities=capabilities or [],
            max_concurrent_tasks=max_concurrent_tasks,
            metadata=metadata or {},
        )
        self._entries[agent_id] = entry
        logger.info(
            "Agent %s registered in directory (type=%s, capabilities=%s)",
            agent_id, agent_type, capabilities,
        )
        return entry

    def unregister(self, agent_id: str) -> bool:
        """
        Remove an agent from the directory.

        Args:
            agent_id: Agent to remove.

        Returns:
            True if removed, False if not found.
        """
        if agent_id in self._entries:
            del self._entries[agent_id]
            logger.info("Agent %s unregistered from directory", agent_id)
            return True
        return False

    def get(self, agent_id: str) -> AgentDirectoryEntry | None:
        """Get a specific agent's directory entry."""
        return self._entries.get(agent_id)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def heartbeat(
        self,
        agent_id: str,
        status: str = "alive",
        active_tasks: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Process a heartbeat from an agent.

        Args:
            agent_id: Agent sending the heartbeat.
            status: Health status string (alive, busy, degraded).
            active_tasks: Current active task count.
            metadata: Optional extra data.

        Returns:
            True if agent is registered, False otherwise.
        """
        entry = self._entries.get(agent_id)
        if not entry:
            logger.debug("Heartbeat from unregistered agent %s", agent_id)
            return False

        entry.update_heartbeat(status, active_tasks, metadata)
        return True

    # ------------------------------------------------------------------
    # Discovery / Selection
    # ------------------------------------------------------------------

    def find_agent(
        self,
        capability: str,
        prefer_healthy: bool = True,
        prefer_least_loaded: bool = True,
    ) -> str | None:
        """
        Find the best available agent for a capability.

        Selection strategy:
        1. Filter by capability
        2. Filter by availability (health + capacity)
        3. Sort by load factor (least busy first)
        4. Among tied load, prefer better success rate

        Args:
            capability: Required capability ID.
            prefer_healthy: Only consider healthy/busy agents.
            prefer_least_loaded: Sort by load factor.

        Returns:
            Best agent ID, or None if no suitable agent found.
        """
        candidates = self.find_all(
            capability=capability,
            only_available=prefer_healthy,
        )

        if not candidates:
            return None

        if prefer_least_loaded:
            # Sort by: load_factor (asc), then success_rate (desc)
            candidates.sort(
                key=lambda e: (e.load_factor, -e.performance.success_rate),
            )

        return candidates[0].agent_id

    def find_all(
        self,
        capability: str | None = None,
        only_available: bool = False,
        agent_type: str | None = None,
    ) -> list[AgentDirectoryEntry]:
        """
        Find all agents matching criteria.

        Args:
            capability: Filter by capability.
            only_available: Only agents that can accept work.
            agent_type: Filter by agent type.

        Returns:
            List of matching directory entries.
        """
        results = []

        for entry in self._entries.values():
            # Skip stale agents
            if entry.is_stale(self._stale_threshold):
                continue

            if capability and capability not in entry.capabilities:
                continue

            if only_available and not entry.is_available:
                continue

            if agent_type and entry.agent_type != agent_type:
                continue

            results.append(entry)

        return results

    # ------------------------------------------------------------------
    # Performance tracking
    # ------------------------------------------------------------------

    def record_task_outcome(
        self,
        agent_id: str,
        success: bool,
        response_time_ms: float = 0.0,
    ) -> None:
        """
        Record a task outcome for performance tracking.

        Args:
            agent_id: Agent that executed the task.
            success: Whether the task succeeded.
            response_time_ms: Execution time in ms (for successful tasks).
        """
        entry = self._entries.get(agent_id)
        if not entry:
            return

        if success:
            entry.performance.record_success(response_time_ms)
        else:
            entry.performance.record_failure()

    def increment_active_tasks(self, agent_id: str) -> None:
        """Increment active task count for an agent."""
        entry = self._entries.get(agent_id)
        if entry:
            entry.active_tasks += 1

    def decrement_active_tasks(self, agent_id: str) -> None:
        """Decrement active task count for an agent."""
        entry = self._entries.get(agent_id)
        if entry and entry.active_tasks > 0:
            entry.active_tasks -= 1

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_stale(self) -> list[str]:
        """
        Remove agents that haven't sent a heartbeat within the threshold.

        Returns:
            List of removed agent IDs.
        """
        stale = [
            agent_id
            for agent_id, entry in self._entries.items()
            if entry.is_stale(self._stale_threshold)
        ]

        for agent_id in stale:
            del self._entries[agent_id]
            logger.warning("Evicted stale agent %s from directory", agent_id)

        return stale

    def get_health_summary(self) -> dict[str, Any]:
        """Get a summary of directory health."""
        entries = list(self._entries.values())
        return {
            "total_agents": len(entries),
            "healthy": sum(1 for e in entries if e.health == AgentHealthStatus.HEALTHY),
            "busy": sum(1 for e in entries if e.health == AgentHealthStatus.BUSY),
            "degraded": sum(1 for e in entries if e.health == AgentHealthStatus.DEGRADED),
            "unresponsive": sum(1 for e in entries if e.health == AgentHealthStatus.UNRESPONSIVE),
            "stale": sum(1 for e in entries if e.is_stale(self._stale_threshold)),
        }

    @property
    def agents(self) -> dict[str, AgentDirectoryEntry]:
        """Access the internal entries (for testing / inspection)."""
        return self._entries


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_directory_instance: AgentDirectory | None = None


def get_agent_directory() -> AgentDirectory:
    """Get global agent directory singleton."""
    global _directory_instance
    if _directory_instance is None:
        _directory_instance = AgentDirectory()
    return _directory_instance
