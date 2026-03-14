"""Lightweight agent event loop — no MongoDB, Redis, or Qdrant required.

Reuses existing components via constructor injection:
- ``Agent`` / ``AgentConfig`` for state
- ``PromptBuilder`` for prompt construction
- ``AgentCommunicationHub`` for inter-agent messaging
- ``AgentDirectory`` for agent discovery
- Any ``LLMProvider`` (Gemini, OpenAI, etc.)

All memory is kept in-process on the ``Agent`` object.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from ..llm.base import LLMProvider
from ..llm.prompt_builder import PromptBuilder
from ..runtime.agent import Agent, AgentStatus
from ..runtime.agent_communication import (
    AgentCommunicationHub,
    AgentMessage,
    MessageType,
)
from ..runtime.agent_directory import AgentDirectory

logger = logging.getLogger(__name__)


class LiteAgentRunner:
    """Lightweight agent runner for infrastructure-free operation.

    Supports:
    - Interactive ``chat()`` for direct user interaction
    - Background ``run()`` event loop that listens for broker messages
    - Inter-agent communication via an injected ``AgentCommunicationHub``
    - Agent directory registration and heartbeats
    """

    def __init__(
        self,
        agent: Agent,
        broker: Any,  # MessageBrokerProtocol — duck typed
        llm_provider: LLMProvider,
        directory: AgentDirectory,
        prompt_builder: PromptBuilder | None = None,
    ) -> None:
        self.agent = agent
        self.broker = broker
        self.llm_provider = llm_provider
        self.directory = directory
        self.prompt_builder = prompt_builder or PromptBuilder()

        # Communication hub — wired to the shared broker
        self.comm_hub = AgentCommunicationHub(
            agent_id=agent.agent_id,
            message_broker=broker,  # type: ignore[arg-type]
        )

        # Event-loop bookkeeping
        self._running = False
        self._run_task: asyncio.Task | None = None
        self._turn_count = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Register in directory, start comm hub, then launch event loop."""
        self.directory.register(
            agent_id=self.agent.agent_id,
            agent_type=self.agent.agent_type,
            capabilities=self.agent.tools_available,
            metadata={
                "model": self.agent.config.model,
                "provider": self.agent.config.llm_provider,
            },
            user_id=self.agent.user_id,
        )

        # Register a handler for incoming peer messages so the agent
        # auto-responds via the LLM.
        self.comm_hub.on_message(MessageType.PEER_MESSAGE, self._handle_incoming_message)
        self.comm_hub.on_message(MessageType.BROADCAST, self._handle_incoming_message)
        self.comm_hub.on_message(MessageType.REQUEST, self._handle_request)

        # Start listening on broker (registers subscriber callbacks)
        await self.comm_hub.start()

        self.agent.status = AgentStatus.RUNNING
        self._running = True
        logger.info("LiteAgentRunner started for %s (user=%s)", self.agent.agent_id, self.agent.user_id)

    async def run(self) -> None:
        """Run the background event loop (heartbeat only).

        Message handling is driven by the ``InMemoryMessageBroker`` pushing
        messages into the ``AgentCommunicationHub`` callbacks, so the loop
        itself only needs to send periodic heartbeats.
        """
        await self.start()
        try:
            while self._running:
                # Heartbeat
                self.directory.heartbeat(
                    agent_id=self.agent.agent_id,
                    status="alive",
                    active_tasks=0,
                )
                await asyncio.sleep(self.agent.config.loop_interval_seconds)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        await self.comm_hub.stop()
        self.directory.unregister(self.agent.agent_id)
        self.agent.status = AgentStatus.IDLE
        logger.info("LiteAgentRunner stopped for %s", self.agent.agent_id)

    # ------------------------------------------------------------------
    # Interactive chat
    # ------------------------------------------------------------------

    async def chat(self, user_message: str) -> str:
        """Send a message to the agent and get a response (no broker)."""
        self._turn_count += 1
        msg = {"content": user_message, "type": "message"}

        messages = self.prompt_builder.build_agent_messages(self.agent, msg)

        result = await self.llm_provider.chat(messages, {
            "max_tokens": self.agent.config.max_tokens,
            "temperature": self.agent.config.temperature,
        })

        response = result.content or "(empty response)"
        self._record_interaction(user_message, response)
        return response

    # ------------------------------------------------------------------
    # Incoming message handlers
    # ------------------------------------------------------------------

    async def _handle_incoming_message(self, msg: AgentMessage) -> None:
        """Process an incoming peer/broadcast message via the LLM."""
        content = msg.content.get("text") or msg.content.get("content", "")
        if not content:
            return

        logger.info(
            "Agent %s received %s from %s",
            self.agent.agent_id, msg.message_type.value, msg.sender_id,
        )

        # Build a prompt incorporating the incoming message
        incoming = {
            "content": f"[Message from agent {msg.sender_id}]: {content}",
            "type": "agent_message",
            "sender_id": msg.sender_id,
        }
        messages = self.prompt_builder.build_agent_messages(self.agent, incoming)

        result = await self.llm_provider.chat(messages, {
            "max_tokens": self.agent.config.max_tokens,
            "temperature": self.agent.config.temperature,
        })

        response_text = result.content or ""
        self._record_interaction(incoming["content"], response_text)

        # Send response back to sender
        if msg.sender_id:
            await self.comm_hub.send(
                recipient_id=msg.sender_id,
                content={"text": response_text, "in_reply_to": msg.message_id},
                message_type=MessageType.PEER_RESPONSE,
            )

    async def _handle_request(self, msg: AgentMessage) -> None:
        """Handle a request-response message via the LLM."""
        content = msg.content.get("text") or msg.content.get("content", "")
        if not content:
            return

        incoming = {
            "content": f"[Request from agent {msg.sender_id}]: {content}",
            "type": "agent_request",
            "sender_id": msg.sender_id,
        }
        messages = self.prompt_builder.build_agent_messages(self.agent, incoming)

        result = await self.llm_provider.chat(messages, {
            "max_tokens": self.agent.config.max_tokens,
            "temperature": self.agent.config.temperature,
        })

        response_text = result.content or ""
        self._record_interaction(incoming["content"], response_text)

        await self.comm_hub.respond(msg, {"text": response_text})

    # ------------------------------------------------------------------
    # Memory helpers
    # ------------------------------------------------------------------

    def _record_interaction(self, user_text: str, assistant_text: str) -> None:
        """Append to short-term memory and update context."""
        now = datetime.utcnow().isoformat()
        self.agent.short_term_memory.append(
            {"role": "user", "content": user_text, "timestamp": now},
        )
        self.agent.short_term_memory.append(
            {"role": "assistant", "content": assistant_text, "timestamp": now},
        )

        # Trim to last 50 entries
        if len(self.agent.short_term_memory) > 50:
            self.agent.short_term_memory = self.agent.short_term_memory[-50:]

        self._turn_count += 0  # already incremented in chat()
        self.agent.context["last_response"] = assistant_text[:200]
        self.agent.context["last_interaction_at"] = now
        self.agent.context["turn_count"] = self._turn_count
