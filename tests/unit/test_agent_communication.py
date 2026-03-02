"""Tests for the Agent Communication Protocol and Hub.

Covers:
- AgentMessage creation, serialization, TTL/expiry
- AgentCommunicationHub send/broadcast/topic
- Request-response with correlation
- Message handler registration and dispatch
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from jarvis.app.runtime.agent_communication import (
    AgentMessage,
    AgentCommunicationHub,
    MessageType,
    MessagePriority,
    send_heartbeat,
)


# ---------------------------------------------------------------------------
# AgentMessage model tests
# ---------------------------------------------------------------------------

class TestAgentMessage:
    """Tests for the AgentMessage Pydantic model."""

    def test_create_message_with_defaults(self):
        msg = AgentMessage(
            message_type=MessageType.PEER_MESSAGE,
            sender_id="agent_1",
            content={"text": "hello"},
        )
        assert msg.sender_id == "agent_1"
        assert msg.message_type == MessageType.PEER_MESSAGE
        assert msg.content == {"text": "hello"}
        assert msg.message_id.startswith("msg_")
        assert msg.priority == MessagePriority.NORMAL
        assert msg.ttl_seconds == 300

    def test_message_not_expired(self):
        msg = AgentMessage(
            message_type=MessageType.PEER_MESSAGE,
            sender_id="agent_1",
            ttl_seconds=300,
        )
        assert not msg.is_expired()

    def test_message_expired(self):
        past = (datetime.utcnow() - timedelta(seconds=400)).isoformat()
        msg = AgentMessage(
            message_type=MessageType.PEER_MESSAGE,
            sender_id="agent_1",
            timestamp=past,
            ttl_seconds=300,
        )
        assert msg.is_expired()

    def test_message_no_ttl_never_expires(self):
        past = (datetime.utcnow() - timedelta(days=30)).isoformat()
        msg = AgentMessage(
            message_type=MessageType.PEER_MESSAGE,
            sender_id="agent_1",
            timestamp=past,
            ttl_seconds=0,
        )
        assert not msg.is_expired()

    def test_message_serialization_roundtrip(self):
        msg = AgentMessage(
            message_type=MessageType.BROADCAST,
            sender_id="agent_1",
            content={"key": "value"},
            topic="updates",
        )
        data = msg.model_dump()
        restored = AgentMessage.model_validate(data)
        assert restored.message_id == msg.message_id
        assert restored.sender_id == "agent_1"
        assert restored.topic == "updates"
        assert restored.content == {"key": "value"}

    def test_all_message_types_valid(self):
        """Ensure all MessageType values can be used."""
        for mt in MessageType:
            msg = AgentMessage(
                message_type=mt,
                sender_id="test",
            )
            assert msg.message_type == mt


# ---------------------------------------------------------------------------
# AgentCommunicationHub tests
# ---------------------------------------------------------------------------

class TestAgentCommunicationHub:
    """Tests for the AgentCommunicationHub."""

    @pytest.fixture
    def mock_broker(self):
        broker = MagicMock()
        broker.publish = AsyncMock(return_value="entry_123")
        broker.subscribe = AsyncMock()
        return broker

    @pytest.fixture
    def hub(self, mock_broker):
        return AgentCommunicationHub(
            agent_id="agent_A",
            message_broker=mock_broker,
        )

    @pytest.mark.asyncio
    async def test_send_peer_message(self, hub, mock_broker):
        msg = await hub.send(
            recipient_id="agent_B",
            content={"text": "hello"},
        )
        assert msg.sender_id == "agent_A"
        assert msg.recipient_id == "agent_B"
        assert msg.message_type == MessageType.PEER_MESSAGE
        assert msg.content == {"text": "hello"}

        # Verify broker was called with correct channel
        mock_broker.publish.assert_called_once()
        call_args = mock_broker.publish.call_args
        assert call_args[0][0] == "agent:agent_B:inbox"

    @pytest.mark.asyncio
    async def test_send_with_custom_priority(self, hub, mock_broker):
        msg = await hub.send(
            recipient_id="agent_B",
            content={"urgent": True},
            priority=MessagePriority.URGENT,
        )
        assert msg.priority == MessagePriority.URGENT

    @pytest.mark.asyncio
    async def test_broadcast_to_all(self, hub, mock_broker):
        msg = await hub.broadcast(content={"event": "task_complete"})
        assert msg.message_type == MessageType.BROADCAST

        call_args = mock_broker.publish.call_args
        assert call_args[0][0] == "broadcast:all"

    @pytest.mark.asyncio
    async def test_broadcast_to_topic(self, hub, mock_broker):
        msg = await hub.broadcast(
            content={"update": "new data"},
            topic="research_updates",
        )
        assert msg.message_type == MessageType.TOPIC_EVENT
        assert msg.topic == "research_updates"

        call_args = mock_broker.publish.call_args
        assert call_args[0][0] == "topic:research_updates"

    def test_subscribe_topic(self, hub):
        hub.subscribe_topic("events")
        assert "events" in hub.get_subscribed_topics()

    def test_unsubscribe_topic(self, hub):
        hub.subscribe_topic("events")
        hub.unsubscribe_topic("events")
        assert "events" not in hub.get_subscribed_topics()

    def test_handler_registration(self, hub):
        handler = AsyncMock()
        hub.on_message(MessageType.PEER_MESSAGE, handler)
        assert MessageType.PEER_MESSAGE in hub._handlers
        assert handler in hub._handlers[MessageType.PEER_MESSAGE]

    @pytest.mark.asyncio
    async def test_respond_to_message(self, hub, mock_broker):
        original = AgentMessage(
            message_type=MessageType.REQUEST,
            sender_id="agent_B",
            recipient_id="agent_A",
            correlation_id="req_abc123",
            reply_to="agent:agent_B:inbox",
        )

        response = await hub.respond(original, {"answer": 42})
        assert response.message_type == MessageType.RESPONSE
        assert response.correlation_id == "req_abc123"
        assert response.in_reply_to == original.message_id
        assert response.recipient_id == "agent_B"

    @pytest.mark.asyncio
    async def test_stop_cancels_pending_requests(self, hub):
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        hub._pending_requests["req_123"] = future

        await hub.stop()

        assert future.cancelled()
        assert len(hub._pending_requests) == 0


# ---------------------------------------------------------------------------
# Heartbeat tests
# ---------------------------------------------------------------------------

class TestHeartbeat:

    @pytest.mark.asyncio
    async def test_send_heartbeat(self):
        broker = MagicMock()
        broker.publish = AsyncMock(return_value="entry_456")

        await send_heartbeat(
            agent_id="agent_1",
            broker=broker,
            status="alive",
            metadata={"tasks": 3},
        )

        broker.publish.assert_called_once()
        channel, payload = broker.publish.call_args[0]
        assert channel == "system:heartbeats"
        assert payload["message_type"] == "heartbeat"
        assert payload["sender_id"] == "agent_1"
        assert payload["content"]["status"] == "alive"
