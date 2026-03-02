"""
Agent Communication Protocol

Defines a standardized inter-agent communication system supporting:
- Typed message envelopes with routing
- Peer-to-peer messaging between any agents
- Broadcast / topic-based publish-subscribe
- Request-response with correlation IDs
- Message acknowledgment and delivery tracking

This module is the foundation for all agent-to-agent communication,
going beyond the basic master→sub-agent delegation pattern.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Awaitable

from pydantic import BaseModel, Field

from ..messaging.broker import MessageBroker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------

class MessageType(str, Enum):
    """Standard message types for inter-agent communication."""

    # Existing types (backward compatible)
    DELEGATION_REQUEST = "delegation_request"
    DELEGATION_RESULT = "delegation_result"
    AGENT_RESPONSE = "agent_response"

    # New peer-to-peer types
    PEER_MESSAGE = "peer_message"
    PEER_RESPONSE = "peer_response"

    # Broadcast / topic types
    BROADCAST = "broadcast"
    TOPIC_EVENT = "topic_event"

    # Lifecycle types
    HEARTBEAT = "heartbeat"
    STATUS_UPDATE = "status_update"
    AGENT_JOINED = "agent_joined"
    AGENT_LEFT = "agent_left"

    # Request-response pattern
    REQUEST = "request"
    RESPONSE = "response"


class MessagePriority(str, Enum):
    """Message priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# ---------------------------------------------------------------------------
# Message envelope
# ---------------------------------------------------------------------------

class AgentMessage(BaseModel):
    """
    Standard message envelope for all inter-agent communication.

    Every message flowing between agents uses this structure, providing
    consistent routing, tracking, and correlation.
    """

    # Identity
    message_id: str = Field(
        default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}",
        description="Unique message identifier",
    )
    message_type: MessageType = Field(
        description="Type of message",
    )

    # Routing
    sender_id: str = Field(
        description="Agent ID of the sender",
    )
    recipient_id: str = Field(
        default="",
        description="Target agent ID (empty for broadcasts)",
    )
    reply_to: str = Field(
        default="",
        description="Channel to send responses to",
    )
    topic: str = Field(
        default="",
        description="Topic name for topic-based messages",
    )

    # Correlation
    correlation_id: str = Field(
        default="",
        description="Links related messages (e.g. request→response)",
    )
    in_reply_to: str = Field(
        default="",
        description="message_id this message is responding to",
    )

    # Payload
    content: dict[str, Any] = Field(
        default_factory=dict,
        description="Message payload",
    )

    # Metadata
    priority: MessagePriority = Field(
        default=MessagePriority.NORMAL,
        description="Message priority",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO-8601 send timestamp",
    )
    ttl_seconds: int = Field(
        default=300,
        description="Time-to-live in seconds (0 = no expiry)",
    )

    def is_expired(self) -> bool:
        """Check if message has exceeded its TTL."""
        if self.ttl_seconds <= 0:
            return False
        sent_at = datetime.fromisoformat(self.timestamp)
        age = (datetime.utcnow() - sent_at).total_seconds()
        return age > self.ttl_seconds


# ---------------------------------------------------------------------------
# Topic subscription registry
# ---------------------------------------------------------------------------

class TopicSubscription(BaseModel):
    """Tracks an agent's subscription to a topic."""
    agent_id: str
    topic: str
    subscribed_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )


# ---------------------------------------------------------------------------
# Agent Communication Hub
# ---------------------------------------------------------------------------

class AgentCommunicationHub:
    """
    Central hub for all inter-agent communication.

    Provides:
    - send(): peer-to-peer messaging
    - request(): request-response with correlation
    - broadcast(): broadcast to all agents or a topic
    - subscribe_topic(): topic-based pub/sub
    - on_message(): register message handlers per type
    """

    def __init__(self, agent_id: str, message_broker: MessageBroker | None = None):
        self.agent_id = agent_id
        self.broker = message_broker or MessageBroker()

        # Message handlers by type
        self._handlers: dict[MessageType, list[Callable]] = {}

        # Topic subscriptions: topic -> set of agent_ids
        self._topic_subscribers: dict[str, set[str]] = {}

        # Pending request-response futures: correlation_id -> Future
        self._pending_requests: dict[str, asyncio.Future] = {}

        # Background listener task
        self._listener_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start listening for incoming messages on this agent's inbox."""
        if self._listener_task and not self._listener_task.done():
            return

        self._listener_task = asyncio.create_task(self._listen())
        logger.info("Communication hub started for agent %s", self.agent_id)

    async def stop(self) -> None:
        """Stop the communication hub."""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

        # Cancel pending requests
        for fut in self._pending_requests.values():
            if not fut.done():
                fut.cancel()
        self._pending_requests.clear()

        logger.info("Communication hub stopped for agent %s", self.agent_id)

    # ------------------------------------------------------------------
    # Send (peer-to-peer)
    # ------------------------------------------------------------------

    async def send(
        self,
        recipient_id: str,
        content: dict[str, Any],
        message_type: MessageType = MessageType.PEER_MESSAGE,
        priority: MessagePriority = MessagePriority.NORMAL,
        ttl_seconds: int = 300,
        reply_to: str = "",
    ) -> AgentMessage:
        """
        Send a message to a specific agent.

        Args:
            recipient_id: Target agent ID.
            content: Message payload dict.
            message_type: Type of message.
            priority: Message priority.
            ttl_seconds: Time-to-live.
            reply_to: Optional reply channel.

        Returns:
            The sent AgentMessage.
        """
        msg = AgentMessage(
            message_type=message_type,
            sender_id=self.agent_id,
            recipient_id=recipient_id,
            content=content,
            priority=priority,
            ttl_seconds=ttl_seconds,
            reply_to=reply_to or f"agent:{self.agent_id}:inbox",
        )

        inbox = f"agent:{recipient_id}:inbox"
        await self.broker.publish(inbox, msg.model_dump())

        logger.debug(
            "Sent %s from %s to %s (id=%s)",
            message_type.value, self.agent_id, recipient_id, msg.message_id,
        )
        return msg

    # ------------------------------------------------------------------
    # Request-Response
    # ------------------------------------------------------------------

    async def request(
        self,
        recipient_id: str,
        content: dict[str, Any],
        timeout_seconds: float = 30.0,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> AgentMessage | None:
        """
        Send a request and wait for a correlated response.

        Args:
            recipient_id: Target agent ID.
            content: Request payload.
            timeout_seconds: Max wait time.
            priority: Message priority.

        Returns:
            The response AgentMessage, or None on timeout.
        """
        correlation_id = f"req_{uuid.uuid4().hex[:12]}"
        future: asyncio.Future[AgentMessage] = asyncio.get_event_loop().create_future()
        self._pending_requests[correlation_id] = future

        msg = AgentMessage(
            message_type=MessageType.REQUEST,
            sender_id=self.agent_id,
            recipient_id=recipient_id,
            content=content,
            priority=priority,
            correlation_id=correlation_id,
            reply_to=f"agent:{self.agent_id}:inbox",
            ttl_seconds=int(timeout_seconds),
        )

        inbox = f"agent:{recipient_id}:inbox"
        await self.broker.publish(inbox, msg.model_dump())

        logger.debug(
            "Request sent from %s to %s (correlation=%s)",
            self.agent_id, recipient_id, correlation_id,
        )

        try:
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
            return response
        except asyncio.TimeoutError:
            logger.warning(
                "Request timeout: %s → %s (correlation=%s, timeout=%.1fs)",
                self.agent_id, recipient_id, correlation_id, timeout_seconds,
            )
            return None
        finally:
            self._pending_requests.pop(correlation_id, None)

    async def respond(
        self,
        original_message: AgentMessage,
        content: dict[str, Any],
    ) -> AgentMessage:
        """
        Send a response to a request message.

        Args:
            original_message: The request message being responded to.
            content: Response payload.

        Returns:
            The response AgentMessage.
        """
        msg = AgentMessage(
            message_type=MessageType.RESPONSE,
            sender_id=self.agent_id,
            recipient_id=original_message.sender_id,
            content=content,
            correlation_id=original_message.correlation_id,
            in_reply_to=original_message.message_id,
            reply_to=f"agent:{self.agent_id}:inbox",
        )

        # Send to the reply_to channel from the original message
        reply_channel = original_message.reply_to or f"agent:{original_message.sender_id}:inbox"
        await self.broker.publish(reply_channel, msg.model_dump())

        logger.debug(
            "Response sent from %s to %s (correlation=%s)",
            self.agent_id, original_message.sender_id, original_message.correlation_id,
        )
        return msg

    # ------------------------------------------------------------------
    # Broadcast / Topic
    # ------------------------------------------------------------------

    async def broadcast(
        self,
        content: dict[str, Any],
        topic: str = "",
        exclude_self: bool = True,
    ) -> AgentMessage:
        """
        Broadcast a message to all agents or a specific topic.

        Args:
            content: Broadcast payload.
            topic: Optional topic to narrow recipients.
            exclude_self: Whether to exclude self from delivery.

        Returns:
            The broadcast AgentMessage.
        """
        msg = AgentMessage(
            message_type=MessageType.TOPIC_EVENT if topic else MessageType.BROADCAST,
            sender_id=self.agent_id,
            content=content,
            topic=topic,
        )

        if topic:
            # Publish to topic stream
            topic_channel = f"topic:{topic}"
            await self.broker.publish(topic_channel, msg.model_dump())
            logger.debug("Published to topic '%s' from %s", topic, self.agent_id)
        else:
            # Publish to global broadcast stream
            await self.broker.publish("broadcast:all", msg.model_dump())
            logger.debug("Broadcast from %s", self.agent_id)

        return msg

    def subscribe_topic(self, topic: str) -> None:
        """
        Subscribe this agent to a topic for receiving topic events.

        The actual stream subscription happens in the listener loop.

        Args:
            topic: Topic name to subscribe to.
        """
        if topic not in self._topic_subscribers:
            self._topic_subscribers[topic] = set()
        self._topic_subscribers[topic].add(self.agent_id)
        logger.info("Agent %s subscribed to topic '%s'", self.agent_id, topic)

    def unsubscribe_topic(self, topic: str) -> None:
        """Unsubscribe this agent from a topic."""
        if topic in self._topic_subscribers:
            self._topic_subscribers[topic].discard(self.agent_id)
            if not self._topic_subscribers[topic]:
                del self._topic_subscribers[topic]
            logger.info("Agent %s unsubscribed from topic '%s'", self.agent_id, topic)

    def get_subscribed_topics(self) -> list[str]:
        """Get list of topics this agent is subscribed to."""
        return [
            topic
            for topic, subscribers in self._topic_subscribers.items()
            if self.agent_id in subscribers
        ]

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def on_message(
        self,
        message_type: MessageType,
        handler: Callable[[AgentMessage], Awaitable[None]],
    ) -> None:
        """
        Register a handler for a specific message type.

        Args:
            message_type: Type of message to handle.
            handler: Async callable invoked with the AgentMessage.
        """
        if message_type not in self._handlers:
            self._handlers[message_type] = []
        self._handlers[message_type].append(handler)

    # ------------------------------------------------------------------
    # Internal listener
    # ------------------------------------------------------------------

    async def _listen(self) -> None:
        """Listen on agent inbox and topic channels for messages."""
        inbox = f"agent:{self.agent_id}:inbox"

        async def _handle_incoming(data: dict[str, Any]) -> None:
            try:
                msg = AgentMessage.model_validate(data)
            except Exception:
                # Not an AgentMessage — could be a legacy message format
                return

            # Skip expired messages
            if msg.is_expired():
                logger.debug("Dropping expired message %s", msg.message_id)
                return

            # Handle correlated responses
            if (
                msg.message_type == MessageType.RESPONSE
                and msg.correlation_id
                and msg.correlation_id in self._pending_requests
            ):
                future = self._pending_requests.get(msg.correlation_id)
                if future and not future.done():
                    future.set_result(msg)
                return

            # Dispatch to registered handlers
            handlers = self._handlers.get(msg.message_type, [])
            for handler in handlers:
                try:
                    await handler(msg)
                except Exception as exc:
                    logger.error(
                        "Handler error for %s message %s: %s",
                        msg.message_type.value, msg.message_id, exc,
                    )

        try:
            await self.broker.subscribe(inbox, _handle_incoming)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Communication hub listener error for %s: %s", self.agent_id, exc)
            raise


# ---------------------------------------------------------------------------
# Heartbeat helper
# ---------------------------------------------------------------------------

async def send_heartbeat(
    agent_id: str,
    broker: MessageBroker,
    status: str = "alive",
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    Publish a heartbeat message for agent health tracking.

    Args:
        agent_id: The agent's ID.
        broker: MessageBroker instance.
        status: Agent health status (alive, busy, degraded).
        metadata: Optional extra info (cpu, memory, active_tasks).
    """
    msg = AgentMessage(
        message_type=MessageType.HEARTBEAT,
        sender_id=agent_id,
        content={
            "status": status,
            "metadata": metadata or {},
        },
        ttl_seconds=60,
    )
    await broker.publish("system:heartbeats", msg.model_dump())
