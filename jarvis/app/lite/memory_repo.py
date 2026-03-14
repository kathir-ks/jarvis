"""In-memory agent repository — dict-backed replacement for MongoDB.

Provides the same async method signatures as ``AgentRepository`` so that
components expecting a repository can work without a database connection.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import Any

from ..runtime.agent import Agent, AgentStatus

logger = logging.getLogger(__name__)


class InMemoryAgentRepository:
    """Dict-backed agent repository for infrastructure-free operation."""

    def __init__(self) -> None:
        self._agents: dict[str, dict[str, Any]] = {}

    async def create(self, agent: Agent) -> Agent:
        """Persist agent (in memory)."""
        self._agents[agent.agent_id] = agent.model_dump(by_alias=True)
        logger.debug("Created agent %s in memory repo", agent.agent_id)
        return agent

    async def get_by_id(self, agent_id: str) -> Agent | None:
        """Retrieve agent by ID."""
        data = self._agents.get(agent_id)
        if data is None:
            return None
        return Agent.model_validate(copy.deepcopy(data))

    async def update(self, agent: Agent) -> Agent:
        """Update agent state."""
        self._agents[agent.agent_id] = agent.model_dump(by_alias=True)
        return agent

    async def update_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update agent status."""
        if agent_id in self._agents:
            self._agents[agent_id]["status"] = status.value if isinstance(status, AgentStatus) else status
            self._agents[agent_id]["updated_at"] = datetime.utcnow().isoformat()

    async def checkpoint(
        self,
        agent_id: str,
        context: dict[str, Any],
        task_queue_meta: dict[str, Any],
    ) -> None:
        """Save agent checkpoint."""
        if agent_id in self._agents:
            self._agents[agent_id]["context"] = context
            self._agents[agent_id]["task_queue_meta"] = task_queue_meta
            self._agents[agent_id]["last_checkpoint"] = datetime.utcnow().isoformat()

    async def get_by_user(self, user_id: str) -> list[Agent]:
        """Retrieve all agents belonging to a user."""
        results = []
        for data in self._agents.values():
            if data.get("user_id") == user_id:
                results.append(Agent.model_validate(copy.deepcopy(data)))
        return results

    async def get_sub_agents(self, parent_agent_id: str) -> list[Agent]:
        """Retrieve sub-agents of a parent agent."""
        results = []
        for data in self._agents.values():
            if data.get("parent_agent_id") == parent_agent_id:
                results.append(Agent.model_validate(copy.deepcopy(data)))
        return results

    async def delete(self, agent_id: str) -> None:
        """Remove agent from memory."""
        self._agents.pop(agent_id, None)
