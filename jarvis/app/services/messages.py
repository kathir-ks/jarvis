"""Message service — publishes messages to agent inboxes via Redis Streams."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from ..messaging.broker import MessageBroker
from ..models.messages import MessageResponse, SendMessageRequest

logger = logging.getLogger(__name__)


class MessageService:
    """Delivers inter-agent and user-to-agent messages through Redis Streams."""

    def __init__(self, broker: MessageBroker | None = None):
        self._broker = broker or MessageBroker()

    async def send_message(self, payload: SendMessageRequest) -> MessageResponse:
        message_id = str(uuid.uuid4())
        status = "APPROVAL_REQUESTED" if payload.requires_approval else "DELIVERED"

        stream_key = f"agent:{payload.to_agent_id}:inbox"
        message: dict[str, Any] = {
            "message_id": message_id,
            "type": payload.message_type,
            "from_agent_id": payload.from_agent_id,
            "to_agent_id": payload.to_agent_id,
            "body": payload.message_body,
            "metadata": payload.metadata,
            "requires_approval": payload.requires_approval,
            "status": status,
        }

        await self._broker.publish(stream_key, message)
        logger.info(
            "Message %s published to %s (status=%s)", message_id, stream_key, status,
        )

        return MessageResponse(
            message_id=message_id,
            status=status,
            requires_approval=payload.requires_approval,
        )

    async def get_history(
        self,
        agent_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if not agent_id:
            return {"data": [], "next_cursor": None}

        stream_key = f"agent:{agent_id}:inbox"
        messages = await self._broker.replay(stream_key, start_id="0", count=limit)

        return {"data": messages, "next_cursor": None}
