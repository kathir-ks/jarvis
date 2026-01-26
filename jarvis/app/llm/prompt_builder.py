"""Prompt construction utilities for agent conversations."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..runtime.agent import Agent


class PromptBuilder:
    """Creates prompt messages for LLM calls."""

    BASE_SYSTEM_PROMPT = (
        "You are Jarvis, an autonomous AI copilot that proactively researches, plans, and coordinates tasks "
        "for your user. Always explain your reasoning, cite facts, and highlight when human approval is required "
        "for purchases or bookings. Provide concise, actionable responses."
    )

    def build_agent_messages(
        self,
        agent: Agent,
        incoming_message: dict[str, Any],
        long_term_context: dict[str, list[Any]] | None = None,
    ) -> list[dict[str, str]]:
        """
        Build chat completion messages using agent context + memory + incoming payload.
        
        Args:
            agent: The agent entity
            incoming_message: The incoming message payload
            long_term_context: Optional long-term memory context from vector store
                              Contains 'interactions', 'discoveries', 'knowledge' lists
        
        Returns:
            List of chat messages for LLM
        """
        system_messages = [
            {"role": "system", "content": self.BASE_SYSTEM_PROMPT},
        ]

        # Add short-term memory (recent interactions)
        memory_text = self._summarize_short_term_memory(agent)
        if memory_text:
            system_messages.append(
                {
                    "role": "system",
                    "content": f"Recent conversation history:\n{memory_text}",
                }
            )

        # Add long-term memory context if available
        if long_term_context:
            long_term_text = self._summarize_long_term_context(long_term_context)
            if long_term_text:
                system_messages.append(
                    {
                        "role": "system",
                        "content": f"Relevant long-term memory:\n{long_term_text}",
                    }
                )

        # Add current agent context
        context_text = self._summarize_context(agent)
        if context_text:
            system_messages.append(
                {
                    "role": "system",
                    "content": f"Current session context:\n{context_text}",
                }
            )

        user_content = self._format_incoming(incoming_message)
        messages = [*system_messages, {"role": "user", "content": user_content}]
        return messages

    def _summarize_short_term_memory(self, agent: Agent) -> str:
        """Create a condensed view of the last few memory entries."""
        if not agent.short_term_memory:
            return ""

        recent = agent.short_term_memory[-5:]
        formatted = []
        for item in recent:
            role = item.get("role") or item.get("type", "note")
            content = item.get("content")
            timestamp = item.get("timestamp")
            # Truncate long content
            if isinstance(content, str) and len(content) > 200:
                content = content[:200] + "..."
            formatted.append(f"[{role}] {content} ({timestamp})")
        return "\n".join(formatted)

    def _summarize_long_term_context(self, context: dict[str, list[Any]]) -> str:
        """Summarize long-term memory context from vector store."""
        parts = []
        
        # Summarize relevant past interactions
        interactions = context.get("interactions", [])
        if interactions:
            parts.append("== Related Past Interactions ==")
            for entry in interactions[:3]:  # Limit to top 3
                content = entry.content if hasattr(entry, 'content') else entry.get('content', '')
                score = entry.score if hasattr(entry, 'score') else entry.get('score', 0)
                if isinstance(content, str) and len(content) > 150:
                    content = content[:150] + "..."
                parts.append(f"- {content} (relevance: {score:.2f})")
        
        # Summarize relevant discoveries
        discoveries = context.get("discoveries", [])
        if discoveries:
            parts.append("\n== Related Discoveries ==")
            for entry in discoveries[:3]:
                content = entry.content if hasattr(entry, 'content') else entry.get('content', '')
                metadata = entry.metadata if hasattr(entry, 'metadata') else entry.get('metadata', {})
                source = metadata.get('source', 'unknown')
                if isinstance(content, str) and len(content) > 150:
                    content = content[:150] + "..."
                parts.append(f"- [{source}] {content}")
        
        # Summarize relevant knowledge
        knowledge = context.get("knowledge", [])
        if knowledge:
            parts.append("\n== Relevant Knowledge ==")
            for entry in knowledge[:3]:
                content = entry.content if hasattr(entry, 'content') else entry.get('content', '')
                metadata = entry.metadata if hasattr(entry, 'metadata') else entry.get('metadata', {})
                knowledge_type = metadata.get('knowledge_type', 'fact')
                confidence = metadata.get('confidence', 1.0)
                if isinstance(content, str) and len(content) > 150:
                    content = content[:150] + "..."
                parts.append(f"- [{knowledge_type}, conf={confidence:.1f}] {content}")
        
        return "\n".join(parts) if parts else ""

    def _summarize_context(self, agent: Agent) -> str:
        """Render agent context dictionary into readable text."""
        if not agent.context:
            return ""

        parts = []
        for key, value in agent.context.items():
            # Skip internal/large values
            if key.startswith("_") or (isinstance(value, str) and len(value) > 100):
                continue
            parts.append(f"- {key}: {value}")
        return "\n".join(parts)

    def _format_incoming(self, message: dict[str, Any]) -> str:
        """Normalize incoming message payload into user content."""
        msg_type = message.get("type", "message")
        body = message.get("content") or message.get("body") or str(message)
        metadata = message.get("metadata") or {}

        # For simple text messages, just return the body
        if msg_type == "message" and not metadata:
            return str(body)

        header = f"Incoming {msg_type} at {self._fmt_time(message.get('received_at'))}"
        meta_text = ""
        if metadata:
            meta_kv = ", ".join(f"{k}={v}" for k, v in metadata.items())
            meta_text = f"\nMetadata: {meta_kv}"

        return f"{header}\n\n{body}{meta_text}"

    @staticmethod
    def _fmt_time(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or datetime.utcnow().isoformat())
