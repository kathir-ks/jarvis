"""Communication Platform Service — business logic for message routing.

Wraps a message broker and agent directory to provide a self-contained
multi-agent messaging backend.  Used by the platform API and also usable
directly in single-process demos.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from ..runtime.agent_directory import AgentDirectory, AgentDirectoryEntry
from ..runtime.agent_communication import AgentMessage, MessageType, MessagePriority

logger = logging.getLogger(__name__)


class CommunicationPlatformService:
    """High-level service wrapping broker + directory."""

    def __init__(self, broker: Any, directory: AgentDirectory) -> None:
        self.broker = broker
        self.directory = directory

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    async def register_agent(
        self,
        agent_id: str,
        user_id: str = "",
        agent_type: str = "sub_agent",
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentDirectoryEntry:
        """Register an agent in the directory."""
        entry = self.directory.register(
            agent_id=agent_id,
            agent_type=agent_type,
            capabilities=capabilities,
            metadata=metadata,
            user_id=user_id,
        )
        logger.info("Platform: agent %s registered (user=%s)", agent_id, user_id)
        return entry

    async def unregister_agent(self, agent_id: str) -> bool:
        """Remove an agent from the directory."""
        removed = self.directory.unregister(agent_id)
        if removed:
            logger.info("Platform: agent %s unregistered", agent_id)
        return removed

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_message(
        self,
        from_id: str,
        to_id: str,
        message_type: str = "peer_message",
        content: dict[str, Any] | None = None,
        ttl_seconds: int = 300,
    ) -> str:
        """Route a message from one agent to another via the broker.

        Returns the broker-assigned message ID.
        """
        msg = AgentMessage(
            message_type=MessageType(message_type),
            sender_id=from_id,
            recipient_id=to_id,
            content=content or {},
            priority=MessagePriority.NORMAL,
            ttl_seconds=ttl_seconds,
        )
        inbox = f"agent:{to_id}:inbox"
        msg_id = await self.broker.publish(inbox, msg.model_dump())
        logger.debug("Platform: routed %s -> %s (id=%s)", from_id, to_id, msg_id)
        return msg_id

    async def broadcast(
        self,
        from_id: str,
        content: dict[str, Any] | None = None,
        topic: str = "",
    ) -> str:
        """Broadcast a message to all agents or a topic."""
        msg = AgentMessage(
            message_type=MessageType.TOPIC_EVENT if topic else MessageType.BROADCAST,
            sender_id=from_id,
            content=content or {},
            topic=topic,
        )
        channel = f"topic:{topic}" if topic else "broadcast:all"
        msg_id = await self.broker.publish(channel, msg.model_dump())
        logger.debug("Platform: broadcast from %s (topic=%s, id=%s)", from_id, topic, msg_id)
        return msg_id

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def heartbeat(
        self,
        agent_id: str,
        status: str = "alive",
        active_tasks: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Process a heartbeat from an agent."""
        return self.directory.heartbeat(
            agent_id=agent_id,
            status=status,
            active_tasks=active_tasks,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_agents(
        self,
        user_id: str | None = None,
        capability: str | None = None,
    ) -> list[AgentDirectoryEntry]:
        """List agents, optionally filtered by user or capability."""
        return self.directory.find_all(
            capability=capability,
            user_id=user_id,
        )

    def get_health(self) -> dict[str, Any]:
        """Return directory health summary."""
        summary = self.directory.get_health_summary()
        summary["status"] = "ok"
        return summary
