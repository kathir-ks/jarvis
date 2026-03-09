"""Prompt construction utilities for agent conversations."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ..runtime.agent import Agent
from ..runtime.workspace_bootstrap import get_workspace_bootstrap
from .token_counter import get_token_counter
from ..runtime.memory_selector import get_memory_selector

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Creates prompt messages for LLM calls."""

    BASE_SYSTEM_PROMPT = (
        "You are Jarvis, an autonomous AI copilot that proactively researches, plans, and coordinates tasks "
        "for your user. Always explain your reasoning, cite facts, and highlight when human approval is required "
        "for purchases or bookings. Provide concise, actionable responses."
    )

    def __init__(self):
        """Initialize prompt builder with token counter and memory selector."""
        self.token_counter = get_token_counter()
        self.memory_selector = get_memory_selector()
        self.workspace_bootstrap = get_workspace_bootstrap()

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
        # Build system prompt with workspace bootstrap (agent identity + persona)
        system_prompt = self.workspace_bootstrap.build_system_prompt(
            agent_id=agent.agent_id,
            base_prompt=self.BASE_SYSTEM_PROMPT,
        )
        system_messages = [
            {"role": "system", "content": system_prompt},
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

    def build_agent_messages_with_budget(
        self,
        agent: Agent,
        incoming_message: dict[str, Any],
        long_term_context: dict[str, list[Any]] | None = None,
        model: str = "gpt-4",
        tools: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        """
        Build chat completion messages with token budget management.

        Uses intelligent memory selection and token-aware truncation to ensure
        messages fit within model context window.

        Args:
            agent: The agent entity
            incoming_message: The incoming message payload
            long_term_context: Optional long-term memory context from vector store
            model: Model name for token counting
            tools: Optional tool definitions for budget calculation

        Returns:
            List of chat messages for LLM, guaranteed to fit in context window
        """
        # Get token budget breakdown
        budget = self.token_counter.get_token_budget_breakdown(model)

        logger.info(
            f"Building prompt with budget - Model: {model}, "
            f"Total window: {budget['total_window']}, "
            f"Available: {budget['available']}"
        )

        # Build system prompt
        system_messages = [
            {"role": "system", "content": self.BASE_SYSTEM_PROMPT},
        ]

        # Format incoming message
        user_content = self._format_incoming(incoming_message)

        # Calculate tool tokens if provided
        tool_tokens = 0
        if tools:
            tool_tokens = self.token_counter.estimate_tool_tokens(tools, model)
            logger.debug(f"Tool tokens: {tool_tokens}")

        # Calculate remaining budget after system prompt, tools, and current message
        system_tokens = self.token_counter.count_messages_tokens(system_messages, model)
        current_msg_tokens = self.token_counter.count_tokens(user_content, model)

        remaining_budget = (
            budget["available"]
            - system_tokens
            - tool_tokens
            - current_msg_tokens
            - budget["reserve"]
        )

        logger.debug(
            f"Token allocation - System: {system_tokens}, Tools: {tool_tokens}, "
            f"Current: {current_msg_tokens}, Remaining: {remaining_budget}"
        )

        # Allocate remaining budget between short-term and long-term memory
        short_term_budget = int(remaining_budget * 0.55)  # 55% for short-term
        long_term_budget = int(remaining_budget * 0.45)   # 45% for long-term

        # Select relevant short-term memories within budget
        if agent.short_term_memory:
            selected_memories = self.memory_selector.select_short_term_memories(
                memories=agent.short_term_memory,
                query=user_content,
                max_count=10,
                max_tokens=short_term_budget,
                estimate_tokens_func=lambda m: self.token_counter.count_tokens(m, model),
            )

            if selected_memories:
                memory_text = self._format_selected_memories(selected_memories)
                memory_tokens = self.token_counter.count_tokens(memory_text, model)
                logger.debug(
                    f"Selected {len(selected_memories)} memories "
                    f"using {memory_tokens}/{short_term_budget} tokens"
                )

                system_messages.append({
                    "role": "system",
                    "content": f"Recent conversation history:\n{memory_text}",
                })

        # Add long-term memory context if available
        if long_term_context:
            long_term_text = self._summarize_long_term_context_with_budget(
                context=long_term_context,
                max_tokens=long_term_budget,
                model=model,
            )

            if long_term_text:
                long_term_tokens = self.token_counter.count_tokens(long_term_text, model)
                logger.debug(
                    f"Long-term memory using {long_term_tokens}/{long_term_budget} tokens"
                )

                system_messages.append({
                    "role": "system",
                    "content": f"Relevant long-term memory:\n{long_term_text}",
                })

        # Add current agent context (with budget constraint)
        context_text = self._summarize_context(agent)
        if context_text:
            context_tokens = self.token_counter.count_tokens(context_text, model)
            # Truncate if too large
            if context_tokens > budget["reserve"]:
                context_text = context_text[: budget["reserve"] * 4]  # Approx 4 chars/token
                context_text += "..."

            system_messages.append({
                "role": "system",
                "content": f"Current session context:\n{context_text}",
            })

        # Build final messages
        messages = [*system_messages, {"role": "user", "content": user_content}]

        # Verify we're within budget
        total_tokens = self.token_counter.count_messages_tokens(messages, model)
        total_with_tools = total_tokens + tool_tokens

        if total_with_tools > budget["available"]:
            logger.warning(
                f"Prompt exceeds budget ({total_with_tools} > {budget['available']}). "
                "Applying emergency truncation."
            )
            messages = self._emergency_truncate(messages, budget["available"], model)

        final_tokens = self.token_counter.count_messages_tokens(messages, model)
        logger.info(
            f"Final prompt: {final_tokens} tokens "
            f"(+{tool_tokens} tools = {final_tokens + tool_tokens} total)"
        )

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

    def _format_selected_memories(self, memories: list[dict[str, Any]]) -> str:
        """
        Format selected memories for prompt inclusion.

        Args:
            memories: Selected memory items

        Returns:
            Formatted string representation
        """
        if not memories:
            return ""

        formatted = []
        for item in memories:
            role = item.get("role") or item.get("type", "note")
            content = item.get("content")
            timestamp = item.get("timestamp")

            # Keep full content (already selected within budget)
            formatted.append(f"[{role}] {content} ({timestamp})")

        return "\n".join(formatted)

    def _summarize_long_term_context_with_budget(
        self,
        context: dict[str, list[Any]],
        max_tokens: int,
        model: str,
    ) -> str:
        """
        Summarize long-term memory context within token budget.

        Args:
            context: Long-term context dict
            max_tokens: Maximum tokens to use
            model: Model name for token counting

        Returns:
            Formatted summary within budget
        """
        parts = []
        tokens_used = 0

        # Helper to add part if it fits
        def add_part_if_fits(part: str) -> bool:
            nonlocal tokens_used
            part_tokens = self.token_counter.count_tokens(part, model)
            if tokens_used + part_tokens <= max_tokens:
                parts.append(part)
                tokens_used += part_tokens
                return True
            return False

        # Add interactions
        interactions = context.get("interactions", [])
        if interactions and add_part_if_fits("== Related Past Interactions =="):
            for entry in interactions[:5]:  # Up to 5 interactions
                content = entry.content if hasattr(entry, "content") else entry.get("content", "")
                score = entry.score if hasattr(entry, "score") else entry.get("score", 0)

                # Truncate if needed
                if isinstance(content, str) and len(content) > 200:
                    content = content[:200] + "..."

                interaction_str = f"- {content} (relevance: {score:.2f})"
                if not add_part_if_fits(interaction_str):
                    break  # Stop if we run out of budget

        # Add discoveries
        discoveries = context.get("discoveries", [])
        if discoveries and add_part_if_fits("\n== Related Discoveries =="):
            for entry in discoveries[:3]:
                content = entry.content if hasattr(entry, "content") else entry.get("content", "")
                metadata = entry.metadata if hasattr(entry, "metadata") else entry.get("metadata", {})
                source = metadata.get("source", "unknown")

                if isinstance(content, str) and len(content) > 150:
                    content = content[:150] + "..."

                discovery_str = f"- [{source}] {content}"
                if not add_part_if_fits(discovery_str):
                    break

        # Add knowledge
        knowledge = context.get("knowledge", [])
        if knowledge and add_part_if_fits("\n== Relevant Knowledge =="):
            for entry in knowledge[:3]:
                content = entry.content if hasattr(entry, "content") else entry.get("content", "")
                metadata = entry.metadata if hasattr(entry, "metadata") else entry.get("metadata", {})
                knowledge_type = metadata.get("knowledge_type", "fact")

                if isinstance(content, str) and len(content) > 150:
                    content = content[:150] + "..."

                knowledge_str = f"- [{knowledge_type}] {content}"
                if not add_part_if_fits(knowledge_str):
                    break

        logger.debug(f"Long-term summary used {tokens_used}/{max_tokens} tokens")
        return "\n".join(parts) if parts else ""

    def _emergency_truncate(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        model: str,
    ) -> list[dict[str, str]]:
        """
        Emergency truncation when prompt exceeds budget.

        Removes oldest memories first, preserving system prompt and current message.

        Args:
            messages: Current messages
            max_tokens: Maximum allowed tokens
            model: Model name

        Returns:
            Truncated messages
        """
        # Separate system, memory, and user messages
        system_msg = messages[0] if messages else None
        user_msg = messages[-1] if messages else None
        middle_messages = messages[1:-1] if len(messages) > 2 else []

        if not system_msg or not user_msg:
            return messages

        # Start with just system and user
        truncated = [system_msg, user_msg]
        current_tokens = self.token_counter.count_messages_tokens(truncated, model)

        # Add middle messages from most recent to oldest until we hit budget
        for msg in reversed(middle_messages):
            msg_tokens = self.token_counter.count_tokens(msg, model)
            if current_tokens + msg_tokens <= max_tokens:
                # Insert before user message
                truncated.insert(-1, msg)
                current_tokens += msg_tokens
            else:
                logger.warning("Dropping message to fit budget")

        logger.info(
            f"Emergency truncation: {len(messages)} → {len(truncated)} messages, "
            f"{current_tokens}/{max_tokens} tokens"
        )

        return truncated

    def build_delegation_messages(
        self,
        agent: Agent,
        delegation_context: dict[str, Any],
        long_term_context: dict[str, list[Any]] | None = None,
    ) -> list[dict[str, str]]:
        """
        Build prompt messages for sub-agent delegation execution.

        Unlike normal conversation prompts, delegation prompts:
        - Use a sub-agent-specific system prompt that clarifies the agent's role
        - Include the parent task description for broader context
        - Include results from sibling subtasks (for sequential workflows)
        - Include the master's conversation summary for continuity

        Args:
            agent: The sub-agent entity
            delegation_context: DelegationContext dict containing:
                - parent_task_description: The overall task
                - subtask_description: This agent's focused task
                - parent_short_term_summary: Master's conversation history
                - parent_session_context: Master's session state
                - sibling_results: Results from prior subtasks
                - subtask_index: Position in sequence
                - total_subtasks: Total subtask count
            long_term_context: Optional long-term memory from vector store

        Returns:
            List of chat messages for LLM
        """
        parent_task = delegation_context.get("parent_task_description", "")
        subtask = delegation_context.get("subtask_description", "")
        subtask_index = delegation_context.get("subtask_index", 0)
        total_subtasks = delegation_context.get("total_subtasks", 1)
        parent_summary = delegation_context.get("parent_short_term_summary", "")
        parent_context = delegation_context.get("parent_session_context", {})
        sibling_results = delegation_context.get("sibling_results", [])

        # Build sub-agent-specific system prompt
        system_prompt = (
            "You are a specialized sub-agent within the Jarvis AI platform. "
            "You have been delegated a specific subtask as part of a larger task. "
            "Focus on completing your subtask thoroughly and accurately. "
            "Provide detailed, actionable results that can be integrated with "
            "other sub-agents' work."
        )

        system_messages = [
            {"role": "system", "content": system_prompt},
        ]

        # Add parent task context so the sub-agent understands the bigger picture
        if parent_task:
            task_context = (
                f"== Overall Task ==\n"
                f"You are working on subtask {subtask_index + 1} of {total_subtasks}.\n"
                f"The user's original request: {parent_task}"
            )
            system_messages.append(
                {"role": "system", "content": task_context}
            )

        # Add master's conversation summary for continuity
        if parent_summary:
            system_messages.append({
                "role": "system",
                "content": f"== Master Agent Conversation History ==\n{parent_summary}",
            })

        # Add results from sibling subtasks (critical for sequential workflows)
        if sibling_results:
            sibling_text = self._format_sibling_results(sibling_results)
            if sibling_text:
                system_messages.append({
                    "role": "system",
                    "content": f"== Results from Prior Subtasks ==\n{sibling_text}",
                })

        # Add parent session context if available
        if parent_context:
            ctx_parts = []
            for key, value in parent_context.items():
                ctx_parts.append(f"- {key}: {value}")
            if ctx_parts:
                system_messages.append({
                    "role": "system",
                    "content": f"== Session Context ==\n" + "\n".join(ctx_parts),
                })

        # Add long-term memory if available
        if long_term_context:
            long_term_text = self._summarize_long_term_context(long_term_context)
            if long_term_text:
                system_messages.append({
                    "role": "system",
                    "content": f"Relevant long-term memory:\n{long_term_text}",
                })

        # The subtask description becomes the user message
        messages = [*system_messages, {"role": "user", "content": subtask}]

        logger.info(
            f"Built delegation prompt: {len(messages)} messages, "
            f"subtask {subtask_index + 1}/{total_subtasks}"
        )

        return messages

    def _format_sibling_results(
        self,
        sibling_results: list[dict[str, Any]],
    ) -> str:
        """
        Format results from previously completed sibling subtasks.

        Args:
            sibling_results: List of result dicts with capability, status, output_summary

        Returns:
            Formatted string for prompt inclusion
        """
        if not sibling_results:
            return ""

        parts = []
        for i, result in enumerate(sibling_results, 1):
            capability = result.get("capability", "unknown")
            status = result.get("status", "unknown")
            output = result.get("output_summary", "")

            if status == "completed" and output:
                parts.append(
                    f"Subtask {i} ({capability}) - Completed:\n{output}"
                )
            elif status in ("failed", "timeout"):
                error = result.get("error", "Unknown error")
                parts.append(
                    f"Subtask {i} ({capability}) - {status}: {error}"
                )

        return "\n\n".join(parts)

    @staticmethod
    def _fmt_time(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or datetime.utcnow().isoformat())
