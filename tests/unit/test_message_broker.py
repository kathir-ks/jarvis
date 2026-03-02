"""Unit tests for the Redis Streams MessageBroker."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarvis.app.messaging.broker import (
    MessageBroker,
    DEFAULT_MAX_STREAM_LENGTH,
    MAX_DELIVERY_ATTEMPTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_broker(mock_redis=None):
    """Create a MessageBroker with a mocked Redis client."""
    with patch("jarvis.app.messaging.broker.get_redis_client") as mock_get:
        if mock_redis is None:
            mock_redis = AsyncMock()
        mock_get.return_value = mock_redis
        broker = MessageBroker()
    return broker, mock_redis


# ---------------------------------------------------------------------------
# Test: Publish
# ---------------------------------------------------------------------------

class TestPublish:
    """Test message publishing to Redis Streams."""

    @pytest.mark.asyncio
    async def test_publish_serializes_and_adds_to_stream(self):
        broker, mock_redis = _make_broker()
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")

        entry_id = await broker.publish(
            "agent:abc:inbox",
            {"type": "message", "content": "hello"},
        )

        assert entry_id == "1234567890-0"
        mock_redis.xadd.assert_called_once()

        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "agent:abc:inbox"
        payload = json.loads(call_args[0][1]["payload"])
        assert payload["type"] == "message"
        assert payload["content"] == "hello"

    @pytest.mark.asyncio
    async def test_publish_respects_maxlen(self):
        broker, mock_redis = _make_broker()
        mock_redis.xadd = AsyncMock(return_value="1-0")

        await broker.publish("ch", {"key": "val"})

        call_kwargs = mock_redis.xadd.call_args[1]
        assert call_kwargs["maxlen"] == DEFAULT_MAX_STREAM_LENGTH
        assert call_kwargs["approximate"] is True


# ---------------------------------------------------------------------------
# Test: Deserialize
# ---------------------------------------------------------------------------

class TestDeserialize:
    """Test message deserialization from Redis Streams format."""

    def test_deserialize_json_string(self):
        result = MessageBroker._deserialize('{"foo": "bar"}')
        assert result == {"foo": "bar"}

    def test_deserialize_bytes(self):
        result = MessageBroker._deserialize(b'{"foo": "bar"}')
        assert result == {"foo": "bar"}

    def test_deserialize_dict_with_payload(self):
        result = MessageBroker._deserialize({"payload": '{"content": "hi"}'})
        assert result == {"content": "hi"}

    def test_deserialize_dict_without_payload(self):
        result = MessageBroker._deserialize({"some": "data"})
        assert result == {"some": "data"}

    def test_deserialize_non_json_string(self):
        result = MessageBroker._deserialize("plain text")
        assert result == {"raw": "plain text"}

    def test_deserialize_other_type(self):
        result = MessageBroker._deserialize(42)
        assert result == {"raw": 42}


# ---------------------------------------------------------------------------
# Test: Replay
# ---------------------------------------------------------------------------

class TestReplay:
    """Test message replay from Redis Streams."""

    @pytest.mark.asyncio
    async def test_replay_returns_deserialized_messages(self):
        broker, mock_redis = _make_broker()
        mock_redis.xrange = AsyncMock(return_value=[
            ("1-0", {"payload": '{"type": "msg", "content": "first"}'}),
            ("2-0", {"payload": '{"type": "msg", "content": "second"}'}),
        ])

        messages = await broker.replay("agent:abc:inbox", start_id="0", count=10)

        assert len(messages) == 2
        assert messages[0]["content"] == "first"
        assert messages[0]["_stream_id"] == "1-0"
        assert messages[1]["content"] == "second"

    @pytest.mark.asyncio
    async def test_replay_empty_stream(self):
        broker, mock_redis = _make_broker()
        mock_redis.xrange = AsyncMock(return_value=[])

        messages = await broker.replay("empty-stream")

        assert messages == []


# ---------------------------------------------------------------------------
# Test: Subscribe simple mode
# ---------------------------------------------------------------------------

class TestSubscribeSimple:
    """Test simple (non-group) stream subscription."""

    @pytest.mark.asyncio
    async def test_subscribe_calls_callback_for_new_messages(self):
        broker, mock_redis = _make_broker()

        received = []

        async def callback(data):
            received.append(data)

        # Simulate xread returning messages then nothing
        call_count = 0

        async def mock_xread(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    ("agent:1:inbox", [
                        ("1-0", {"payload": '{"content": "hello"}'}),
                        ("2-0", {"payload": '{"content": "world"}'}),
                    ])
                ]
            # After first batch, raise to exit the loop
            raise asyncio.CancelledError()

        mock_redis.xread = mock_xread

        with pytest.raises(asyncio.CancelledError):
            await broker._subscribe_simple("agent:1:inbox", callback)

        assert len(received) == 2
        assert received[0]["content"] == "hello"
        assert received[1]["content"] == "world"


# ---------------------------------------------------------------------------
# Test: Dead-letter handling
# ---------------------------------------------------------------------------

class TestDeadLetter:
    """Test dead-letter stream for failed messages."""

    @pytest.mark.asyncio
    async def test_move_to_dead_letter(self):
        broker, mock_redis = _make_broker()
        mock_redis.xrange = AsyncMock(return_value=[
            ("42-0", {"payload": '{"content": "bad msg"}'}),
        ])
        mock_redis.xadd = AsyncMock(return_value="dl-1")
        mock_redis.xack = AsyncMock()

        await broker._move_to_dead_letter("agent:1:inbox", "grp", "42-0")

        # Should have written to dead-letter stream
        dl_call = mock_redis.xadd.call_args
        assert "dead_letter" in dl_call[0][0]
        assert dl_call[0][1]["original_id"] == "42-0"

        # Should have acknowledged the original message
        mock_redis.xack.assert_called_once_with("agent:1:inbox", "grp", "42-0")
