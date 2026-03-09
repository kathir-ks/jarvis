"""
Delegation Context Management

Manages context packaging, propagation, and storage for master-subagent
delegation workflows. Ensures sub-agents receive relevant context from
their master agent and can share results with sibling subtasks.

Key responsibilities:
- Build context packages for sub-agents (parent task, memory, session state)
- Chain sequential subtask results for dependent workflows
- Store delegation outcomes in long-term memory
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Maximum length for context summaries to avoid token bloat
MAX_MEMORY_SUMMARY_LENGTH = 500
MAX_SIBLING_RESULT_LENGTH = 300
MAX_SESSION_CONTEXT_ITEMS = 10


class DelegationContext(BaseModel):
    """
    Context package passed from master to sub-agent during delegation.

    Contains everything a sub-agent needs to understand its role within
    the broader task, including the parent task scope, relevant history,
    and results from sibling subtasks.
    """

    # Task scope
    parent_task_description: str = Field(
        description="Full description of the original task from the user"
    )
    subtask_description: str = Field(
        description="Focused description of this specific subtask"
    )
    subtask_index: int = Field(
        default=0,
        description="Position of this subtask in the execution sequence"
    )
    total_subtasks: int = Field(
        default=1,
        description="Total number of subtasks in this delegation"
    )

    # Parent agent context
    parent_short_term_summary: str = Field(
        default="",
        description="Summary of the master agent's recent conversation history"
    )
    parent_session_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Relevant session state from the master agent"
    )

    # Sibling subtask results (for sequential workflows)
    sibling_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Results from previously completed sibling subtasks"
    )

    # Metadata
    master_agent_id: str = Field(
        default="",
        description="ID of the master agent orchestrating this delegation"
    )
    delegation_chain_depth: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Depth in the delegation hierarchy (1 = direct sub-agent)"
    )
    delegated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Timestamp when delegation was created"
    )


class DelegationContextManager:
    """
    Manages context packaging, propagation, and storage for delegation workflows.

    Used by MasterAgentOrchestrator to build context packages for sub-agents
    and store delegation outcomes for future reference.
    """

    def build_context_for_sub_agent(
        self,
        master_agent: Any,
        parent_task_description: str,
        subtask: dict[str, Any],
        subtask_index: int = 0,
        total_subtasks: int = 1,
        prior_results: list[dict[str, Any]] | None = None,
    ) -> DelegationContext:
        """
        Build a context package for a sub-agent from the master's state.

        Extracts relevant information from the master agent's memory and
        session context, and includes results from prior subtasks if this
        is a sequential workflow.

        Args:
            master_agent: The master Agent entity (with memory and context)
            parent_task_description: The original task description
            subtask: The subtask definition dict
            subtask_index: Position of this subtask (0-based)
            total_subtasks: Total number of subtasks
            prior_results: Results from previously completed subtasks

        Returns:
            DelegationContext with packaged context for the sub-agent
        """
        # Summarize master's recent conversation history
        short_term_summary = self._summarize_short_term_memory(master_agent)

        # Extract relevant session context (skip internal/large values)
        session_context = self._extract_session_context(master_agent)

        # Format prior sibling results for context
        sibling_results = self._format_sibling_results(prior_results or [])

        context = DelegationContext(
            parent_task_description=parent_task_description,
            subtask_description=subtask.get("description", ""),
            subtask_index=subtask_index,
            total_subtasks=total_subtasks,
            parent_short_term_summary=short_term_summary,
            parent_session_context=session_context,
            sibling_results=sibling_results,
            master_agent_id=getattr(master_agent, "agent_id", ""),
            delegation_chain_depth=1,
        )

        logger.info(
            f"Built delegation context for subtask {subtask_index + 1}/{total_subtasks} "
            f"(parent_memory_len={len(short_term_summary)}, "
            f"sibling_results={len(sibling_results)})"
        )

        return context

    def _summarize_short_term_memory(self, agent: Any) -> str:
        """
        Create a condensed summary of the agent's recent conversation.

        Focuses on the most recent and relevant interactions to give
        the sub-agent conversational context without token bloat.

        Args:
            agent: Agent entity with short_term_memory

        Returns:
            Condensed summary string
        """
        memory = getattr(agent, "short_term_memory", None)
        if not memory:
            return ""

        # Take the most recent entries (up to 8)
        recent = memory[-8:]
        parts = []

        for item in recent:
            role = item.get("role") or item.get("type", "note")
            content = item.get("content", "")

            if not content:
                continue

            # Truncate individual entries
            if isinstance(content, str) and len(content) > 150:
                content = content[:150] + "..."

            parts.append(f"[{role}] {content}")

        summary = "\n".join(parts)

        # Enforce overall length limit
        if len(summary) > MAX_MEMORY_SUMMARY_LENGTH:
            summary = summary[:MAX_MEMORY_SUMMARY_LENGTH] + "\n[...truncated]"

        return summary

    def _extract_session_context(self, agent: Any) -> dict[str, Any]:
        """
        Extract relevant session context from the agent.

        Filters out internal keys and large values to keep the context
        package lightweight.

        Args:
            agent: Agent entity with context dict

        Returns:
            Filtered session context dict
        """
        context = getattr(agent, "context", None)
        if not context:
            return {}

        filtered = {}
        count = 0

        for key, value in context.items():
            if count >= MAX_SESSION_CONTEXT_ITEMS:
                break

            # Skip internal keys
            if key.startswith("_"):
                continue

            # Skip overly large string values
            if isinstance(value, str) and len(value) > 200:
                filtered[key] = value[:200] + "..."
                count += 1
                continue

            # Skip complex nested objects
            if isinstance(value, (list, dict)) and len(str(value)) > 300:
                continue

            filtered[key] = value
            count += 1

        return filtered

    def _format_sibling_results(
        self,
        prior_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Format results from previously completed sibling subtasks.

        Keeps only the essential information (capability, status, output summary)
        to pass as context to the next subtask in a sequential workflow.

        Args:
            prior_results: Raw results from completed subtasks

        Returns:
            Formatted list of sibling result summaries
        """
        formatted = []

        for result in prior_results:
            status = result.get("status", "unknown")
            capability = result.get("subtask", {}).get(
                "assigned_capability", "unknown"
            )
            output = result.get("result", {}).get("output", "")

            # Truncate output for context
            if isinstance(output, str) and len(output) > MAX_SIBLING_RESULT_LENGTH:
                output = output[:MAX_SIBLING_RESULT_LENGTH] + "..."

            formatted.append({
                "capability": capability,
                "status": status,
                "output_summary": output,
            })

        return formatted

    async def store_delegation_result(
        self,
        vector_memory: Any,
        agent_id: str,
        user_id: str,
        task_description: str,
        aggregated_result: dict[str, Any],
    ) -> None:
        """
        Store a completed delegation workflow result in long-term memory.

        Enables future tasks to discover and build on past delegation outcomes
        via semantic search in the vector store.

        Args:
            vector_memory: VectorMemoryService instance
            agent_id: The master agent's ID
            user_id: The user's ID
            task_description: Original task description
            aggregated_result: The aggregated result from all subtasks
        """
        if not vector_memory:
            logger.debug("No vector memory available, skipping result storage")
            return

        status = aggregated_result.get("status", "unknown")
        response = aggregated_result.get("synthesized_response", "")
        successful = aggregated_result.get("successful_count", 0)
        failed = aggregated_result.get("failed_count", 0)

        # Build a knowledge entry for the delegation outcome
        knowledge_content = (
            f"Delegation result for task: {task_description}\n"
            f"Status: {status} ({successful} succeeded, {failed} failed)\n"
            f"Response: {response[:500]}"
        )

        try:
            await vector_memory.store_knowledge(
                content=knowledge_content,
                agent_id=agent_id,
                knowledge_type="delegation_result",
                confidence=1.0 if status == "completed" else 0.5,
                metadata={
                    "user_id": user_id,
                    "task_description": task_description[:200],
                    "status": status,
                    "successful_count": successful,
                    "failed_count": failed,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            logger.info(
                f"Stored delegation result in long-term memory "
                f"(task={task_description[:50]}..., status={status})"
            )
        except Exception as e:
            logger.error(f"Failed to store delegation result: {e}")
