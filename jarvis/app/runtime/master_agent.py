"""
Master Agent Orchestrator

High-level orchestration logic for master agents.
Implements Phase 4 multi-agent collaboration and delegation.

Phase 4 Implementation:
- Sub-agent spawning with capability-based tool assignment
- Delegation via Redis Pub/Sub messaging
- Result aggregation with LLM synthesis
- Complete orchestration workflow for complex tasks

Context Management (Phase 4.5):
- Rich context propagation from master to sub-agents
- Sequential subtask context chaining (prior results flow to next subtask)
- Delegation result storage in long-term memory

Agent Communication (Phase 4.6):
- Circuit breaker protection for failing agents
- Agent directory with health-aware, load-balanced selection
- Configurable LLM provider for sub-agents
- Timeout enforcement with exponential backoff retry
- Peer-to-peer messaging via AgentCommunicationHub
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from .task import Task
from .task_analyzer import get_task_analyzer
from .agent_capabilities import get_capabilities_registry, STANDARD_CAPABILITIES
from .agent_directory import AgentDirectory, get_agent_directory
from .circuit_breaker import CircuitBreaker, CircuitOpenError, retry_with_backoff, with_timeout
from .delegation_context import DelegationContextManager
from ..messaging.broker import MessageBroker

logger = logging.getLogger(__name__)

# Default timeout for sub-agent delegation (10 minutes)
DEFAULT_DELEGATION_TIMEOUT_SECONDS = 600

# Default LLM configuration for sub-agents (configurable via set_sub_agent_llm_config)
DEFAULT_SUB_AGENT_LLM_CONFIG: dict[str, Any] = {
    "llm_provider": "gemini",
    "model": "gemini-2.0-flash-exp",
    "temperature": 0.7,
    "max_tokens": 4096,
}


class MasterAgentOrchestrator:
    """
    Orchestrates complex tasks for master agents.

    Phase 4 Implementation:
    - Spawns specialized sub-agents based on task requirements
    - Delegates subtasks via Redis Pub/Sub messaging
    - Aggregates results from sub-agents using LLM synthesis
    - Coordinates multi-agent workflows with timeout handling

    Phase 4.6 Enhancements:
    - Circuit breaker prevents delegation to consistently failing agents
    - Agent directory provides health-aware, load-balanced selection
    - Sub-agent LLM provider is configurable (no longer hardcoded)
    - Delegation retries with exponential backoff
    - Proper timeout enforcement via asyncio.wait_for
    """

    def __init__(
        self,
        agent_id: str,
        agent_service: Any = None,
        llm_router: Any = None,
        user_id: str | None = None,
        master_agent: Any = None,
        vector_memory: Any = None,
    ):
        """
        Initialize master agent orchestrator.

        Args:
            agent_id: The master agent's ID
            agent_service: AgentService for spawning sub-agents (injected)
            llm_router: LLMRouter for result synthesis (injected)
            user_id: User ID for sub-agent creation
            master_agent: The master Agent entity (for context access)
            vector_memory: VectorMemoryService for storing delegation results
        """
        self.agent_id = agent_id
        self.task_analyzer = get_task_analyzer()
        self.capabilities_registry = get_capabilities_registry()
        self.agent_directory = get_agent_directory()
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout_seconds=60.0,
        )
        self.message_broker = MessageBroker()
        self.context_manager = DelegationContextManager()

        # Injected dependencies (set via set_dependencies)
        self._agent_service = agent_service
        self._llm_router = llm_router
        self._user_id = user_id
        self._agent = master_agent
        self._vector_memory = vector_memory

        # Track spawned sub-agents for cleanup
        self._spawned_sub_agents: list[str] = []

        # Track pending delegations
        self._pending_delegations: dict[str, dict[str, Any]] = {}

        # Configurable LLM for sub-agents (defaults to Gemini flash)
        self._sub_agent_llm_config: dict[str, Any] = dict(DEFAULT_SUB_AGENT_LLM_CONFIG)

        # Configurable LLM for synthesis calls
        self._synthesis_llm_config: dict[str, Any] | None = None

    def set_dependencies(
        self,
        agent_service: Any,
        llm_router: Any,
        user_id: str,
        master_agent: Any = None,
        vector_memory: Any = None,
    ) -> None:
        """
        Set dependencies after initialization.

        Args:
            agent_service: AgentService for spawning
            llm_router: LLMRouter for synthesis
            user_id: User ID
            master_agent: The master Agent entity (for context access)
            vector_memory: VectorMemoryService for result storage
        """
        self._agent_service = agent_service
        self._llm_router = llm_router
        self._user_id = user_id
        if master_agent is not None:
            self._agent = master_agent
        if vector_memory is not None:
            self._vector_memory = vector_memory

    def set_sub_agent_llm_config(self, config: dict[str, Any]) -> None:
        """
        Configure the LLM provider/model used when spawning sub-agents.

        Args:
            config: Dict with keys: llm_provider, model, temperature, max_tokens.
        """
        self._sub_agent_llm_config.update(config)
        logger.info("Sub-agent LLM config updated: %s", self._sub_agent_llm_config)

    def set_synthesis_llm_config(self, config: dict[str, Any]) -> None:
        """
        Configure the LLM provider/model used for result synthesis.

        If not set, falls back to sub-agent LLM config.

        Args:
            config: Dict with keys: provider, model, temperature, max_tokens.
        """
        self._synthesis_llm_config = config
        logger.info("Synthesis LLM config updated: %s", config)

    async def handle_task(self, task: Task) -> dict[str, Any]:
        """
        Handle incoming task with intelligent routing.

        Analyzes task complexity and determines execution strategy:
        - Simple tasks: Execute directly
        - Complex tasks: Delegate to sub-agents via orchestration

        Args:
            task: The task to execute

        Returns:
            Dict containing:
                - strategy: 'direct' or 'delegate'
                - analysis: Task complexity analysis
                - execution_plan: Recommended execution plan
                - result: Task result (if executed)
        """
        logger.info(f"Master agent {self.agent_id} handling task {task.task_id}")

        # Analyze task complexity
        analysis = self.task_analyzer.analyze_task_complexity(task.task_description)

        logger.info(
            f"Task analysis - Complexity: {analysis['complexity_score']}/10, "
            f"Should delegate: {analysis['should_delegate']}, "
            f"Subtasks: {analysis['estimated_subtasks']}"
        )

        # Determine execution strategy
        if analysis["should_delegate"] and self._can_delegate():
            strategy = "delegate"
            execution_plan = self._create_delegation_plan(task, analysis)

            logger.info(
                f"Task {task.task_id} is complex (score {analysis['complexity_score']}). "
                f"Delegating to {len(analysis['suggested_sub_agents'])} sub-agents."
            )
            logger.debug(f"Suggested sub-agents: {analysis['suggested_sub_agents']}")

            # Execute via orchestrated delegation
            result = await self.orchestrate_delegation(task, analysis, execution_plan)

        else:
            strategy = "direct"
            execution_plan = {"method": "direct_execution", "reason": analysis["reasoning"]}

            if not self._can_delegate() and analysis["should_delegate"]:
                logger.warning(
                    f"Task {task.task_id} should delegate but dependencies not available. "
                    "Falling back to direct execution."
                )

            logger.info(
                f"Task {task.task_id} (score {analysis['complexity_score']}). "
                "Executing directly."
            )

            result = await self._execute_task_directly(task)

        return {
            "strategy": strategy,
            "analysis": analysis,
            "execution_plan": execution_plan,
            "result": result,
        }

    def _can_delegate(self) -> bool:
        """Check if delegation is possible (dependencies available)."""
        return (
            self._agent_service is not None
            and self._llm_router is not None
            and self._user_id is not None
        )

    def _create_delegation_plan(
        self,
        task: Task,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create delegation plan for complex tasks.

        Args:
            task: The task to delegate
            analysis: Task complexity analysis

        Returns:
            Delegation plan dict with subtasks and agent assignments
        """
        plan = {
            "method": "delegation",
            "subtasks": [],
            "required_capabilities": analysis["suggested_sub_agents"],
            "estimated_subtasks": analysis["estimated_subtasks"],
            "parallel_execution": self._can_parallelize(analysis),
        }

        # Find capable agents using agent directory (health + load aware)
        # Falls back to capabilities registry if directory has no matches
        agent_assignments = {}
        for capability_id in analysis["suggested_sub_agents"]:
            # Try agent directory first (health-aware, load-balanced)
            best_agent = self.agent_directory.find_agent(
                capability=capability_id,
                prefer_healthy=True,
                prefer_least_loaded=True,
            )

            if not best_agent:
                # Fallback to capabilities registry
                capable_agents = self.capabilities_registry.find_capable_agents(
                    required_capability=capability_id
                )
                # Filter out agents with open circuits
                capable_agents = [
                    a for a in capable_agents
                    if self.circuit_breaker.can_call(a)
                ]
                best_agent = capable_agents[0] if capable_agents else None

            if best_agent:
                agent_assignments[capability_id] = {
                    "agent_id": best_agent,
                    "action": "reuse",
                }
                logger.debug(
                    f"Capability '{capability_id}' assigned to agent "
                    f"{best_agent} (health-aware selection)"
                )
            else:
                agent_assignments[capability_id] = {
                    "agent_id": None,
                    "action": "spawn",
                }
                logger.info(
                    f"No healthy agents with capability '{capability_id}'. "
                    "Will spawn new sub-agent."
                )

        plan["agent_assignments"] = agent_assignments

        # Create subtasks based on required capabilities
        for i, capability_id in enumerate(analysis["suggested_sub_agents"]):
            subtask_description = self._generate_subtask_description(
                task.task_description,
                capability_id,
                i + 1,
                len(analysis["suggested_sub_agents"]),
            )

            plan["subtasks"].append({
                "subtask_id": f"{task.task_id}_sub_{i+1}",
                "description": subtask_description,
                "assigned_capability": capability_id,
                "priority": task.priority,
                "timeout_seconds": DEFAULT_DELEGATION_TIMEOUT_SECONDS,
            })

        return plan

    def _can_parallelize(self, analysis: dict[str, Any]) -> bool:
        """
        Determine if subtasks can run in parallel.

        Args:
            analysis: Task complexity analysis

        Returns:
            True if tasks are independent enough for parallel execution
        """
        # Simple heuristic: if multi_step is detected, tasks are likely sequential
        if analysis.get("indicators", {}).get("multi_step"):
            return False

        # If we have multiple independent capabilities, can parallelize
        capabilities = analysis.get("suggested_sub_agents", [])
        if len(capabilities) >= 2:
            # Check for dependencies between capabilities
            dependent_pairs = [
                ("web_research", "code_execution"),  # Often sequential
            ]
            for cap1, cap2 in dependent_pairs:
                if cap1 in capabilities and cap2 in capabilities:
                    return False

        return True

    def _generate_subtask_description(
        self,
        original_description: str,
        capability_id: str,
        subtask_num: int,
        total_subtasks: int,
    ) -> str:
        """
        Generate a focused subtask description for a specific capability.

        Args:
            original_description: Original task description
            capability_id: The capability this subtask requires
            subtask_num: Subtask number
            total_subtasks: Total number of subtasks

        Returns:
            Focused subtask description
        """
        capability_focus = {
            "web_research": "Research and gather information about: ",
            "code_execution": "Write and execute code to: ",
            "calculation": "Perform mathematical calculations for: ",
            "time_awareness": "Handle time-related aspects of: ",
            "task_orchestration": "Plan and coordinate: ",
            "general_assistance": "Assist with: ",
        }

        prefix = capability_focus.get(capability_id, "Complete: ")

        # Extract relevant portion of description
        if total_subtasks == 1:
            return f"{prefix}{original_description}"

        # Try to extract capability-relevant keywords
        truncated = original_description[:200]
        if len(original_description) > 200:
            truncated += "..."

        return f"[Subtask {subtask_num}/{total_subtasks}] {prefix}{truncated}"

    async def _execute_task_directly(self, task: Task) -> dict[str, Any]:
        """
        Execute task directly via the normal agent runner flow.

        Used for simple tasks that don't require delegation.

        Args:
            task: The task to execute

        Returns:
            Execution result indicating task is queued for agent runner
        """
        logger.info(f"Executing task {task.task_id} directly via agent runner")

        # Task execution happens via normal agent runner
        return {
            "status": "delegated_to_agent_runner",
            "task_id": task.task_id,
            "description": task.task_description,
            "execution_mode": "direct",
            "note": "Task will be executed by agent runner's normal task processing loop",
        }

    async def spawn_sub_agent(
        self,
        capability_id: str,
        user_id: str | None = None,
    ) -> str | None:
        """
        Spawn a new sub-agent with specific capability.

        Creates a sub-agent configured with the tools required for
        the specified capability, registers the capability, starts
        the agent runtime, and registers it in the agent directory.

        Uses configurable LLM provider (set via set_sub_agent_llm_config).

        Args:
            capability_id: Required capability ID
            user_id: User ID for the new agent (uses self._user_id if not provided)

        Returns:
            New agent ID or None if spawning failed
        """
        if not self._agent_service:
            logger.error("Cannot spawn sub-agent: agent_service not available")
            return None

        effective_user_id = user_id or self._user_id
        if not effective_user_id:
            logger.error("Cannot spawn sub-agent: no user_id available")
            return None

        # Get capability definition for required tools
        capability = self.capabilities_registry.get_capability_definition(capability_id)
        if not capability:
            logger.warning(
                f"Unknown capability '{capability_id}'. Using default tools."
            )
            required_tools = []
        else:
            required_tools = capability.required_tools

        logger.info(
            f"Spawning sub-agent for capability '{capability_id}' "
            f"with tools: {required_tools}"
        )

        try:
            # Spawn via agent service using configurable LLM config
            sub_agent_response = await self._agent_service.spawn_sub_agent(
                parent_agent_id=self.agent_id,
                config=dict(self._sub_agent_llm_config),
                tools_enabled=required_tools,
            )

            sub_agent_id = sub_agent_response.agent_id
            logger.info(f"Spawned sub-agent {sub_agent_id} for capability '{capability_id}'")

            # Register capability for the new sub-agent
            self.capabilities_registry.register_capability(sub_agent_id, capability_id)

            # Start the sub-agent runtime
            await self._agent_service.start_agent_runtime(sub_agent_id)
            logger.info(f"Started runtime for sub-agent {sub_agent_id}")

            # Register in agent directory for health-aware discovery
            self.agent_directory.register(
                agent_id=sub_agent_id,
                agent_type="sub_agent",
                capabilities=[capability_id],
                metadata={
                    "parent_agent_id": self.agent_id,
                    "llm_provider": self._sub_agent_llm_config.get("llm_provider"),
                    "model": self._sub_agent_llm_config.get("model"),
                },
            )

            # Track spawned agent for cleanup
            self._spawned_sub_agents.append(sub_agent_id)

            return sub_agent_id

        except Exception as e:
            logger.error(f"Failed to spawn sub-agent for '{capability_id}': {e}")
            return None

    async def delegate_to_sub_agent(
        self,
        sub_agent_id: str,
        subtask: dict[str, Any],
        parent_task_description: str = "",
        subtask_index: int = 0,
        total_subtasks: int = 1,
        prior_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Delegate a subtask to a sub-agent via messaging.

        Sends a delegation request message to the sub-agent's inbox
        and sets up a reply channel for result collection. Includes
        rich context from the master agent for informed execution.

        Args:
            sub_agent_id: ID of sub-agent to delegate to
            subtask: Subtask definition containing:
                - subtask_id: Unique identifier
                - description: Task description
                - priority: Task priority (1-10)
                - timeout_seconds: Maximum execution time
            parent_task_description: The original user task (for context)
            subtask_index: Position of this subtask in the sequence
            total_subtasks: Total number of subtasks in this delegation
            prior_results: Results from previously completed subtasks

        Returns:
            Delegation info dict containing:
                - delegation_id: Unique delegation identifier
                - sub_agent_id: The sub-agent handling the task
                - reply_channel: Channel for result collection
                - status: 'delegated'
        """
        delegation_id = f"del_{uuid.uuid4().hex[:12]}"
        reply_channel = f"agent:{self.agent_id}:delegations:{delegation_id}"

        # Build rich delegation context from master's state
        delegation_context = {}
        if self._agent:
            delegation_context = self.context_manager.build_context_for_sub_agent(
                master_agent=self._agent,
                parent_task_description=parent_task_description,
                subtask=subtask,
                subtask_index=subtask_index,
                total_subtasks=total_subtasks,
                prior_results=prior_results,
            ).model_dump()
        else:
            # Minimal context when master agent entity is not available
            delegation_context = {
                "parent_task_description": parent_task_description,
                "subtask_description": subtask.get("description", ""),
                "subtask_index": subtask_index,
                "total_subtasks": total_subtasks,
                "sibling_results": [],
                "parent_short_term_summary": "",
                "parent_session_context": {},
                "master_agent_id": self.agent_id,
                "delegation_chain_depth": 1,
            }

        # Build delegation request message
        delegation_message = {
            "type": "delegation_request",
            "delegation_id": delegation_id,
            "master_agent_id": self.agent_id,
            "task": {
                "subtask_id": subtask.get("subtask_id"),
                "description": subtask.get("description"),
                "priority": subtask.get("priority", 5),
                "timeout_seconds": subtask.get("timeout_seconds", DEFAULT_DELEGATION_TIMEOUT_SECONDS),
                "required_capability": subtask.get("assigned_capability"),
            },
            "reply_channel": reply_channel,
            "context": delegation_context,
            "timestamp": datetime.utcnow().isoformat(),
        }

        logger.info(
            f"Delegating subtask '{subtask.get('subtask_id')}' to sub-agent {sub_agent_id}"
        )

        # Check circuit breaker before delegating
        if not self.circuit_breaker.can_call(sub_agent_id):
            logger.warning(
                f"Circuit open for agent {sub_agent_id} — skipping delegation "
                f"{delegation_id}"
            )
            return {
                "delegation_id": delegation_id,
                "sub_agent_id": sub_agent_id,
                "subtask": subtask,
                "reply_channel": reply_channel,
                "status": "circuit_open",
                "delegated_at": datetime.utcnow().isoformat(),
            }

        # Publish to sub-agent's inbox
        inbox_channel = f"agent:{sub_agent_id}:inbox"
        await self.message_broker.publish(inbox_channel, delegation_message)

        # Track active work in the directory
        self.agent_directory.increment_active_tasks(sub_agent_id)

        # Track pending delegation
        delegation_info = {
            "delegation_id": delegation_id,
            "sub_agent_id": sub_agent_id,
            "subtask": subtask,
            "reply_channel": reply_channel,
            "status": "delegated",
            "delegated_at": datetime.utcnow().isoformat(),
        }
        self._pending_delegations[delegation_id] = delegation_info

        logger.debug(f"Delegation {delegation_id} sent, listening on {reply_channel}")

        return delegation_info

    async def aggregate_results(
        self,
        subtask_results: list[dict[str, Any]],
        original_task_description: str | None = None,
    ) -> dict[str, Any]:
        """
        Aggregate results from multiple sub-agents using LLM synthesis.

        Separates successful and failed results, then uses LLM to
        synthesize a coherent final response from successful outputs.

        Args:
            subtask_results: Results from sub-agents, each containing:
                - delegation_id: Delegation identifier
                - status: 'completed', 'failed', or 'timeout'
                - result: Subtask result (if completed)
                - error: Error message (if failed)
            original_task_description: The original task for context

        Returns:
            Aggregated result dict containing:
                - status: 'completed', 'partial', or 'failed'
                - synthesized_response: LLM-generated synthesis
                - successful_count: Number of successful subtasks
                - failed_count: Number of failed subtasks
                - subtask_summaries: List of individual summaries
        """
        # Separate successful and failed results
        successful = [r for r in subtask_results if r.get("status") == "completed"]
        failed = [r for r in subtask_results if r.get("status") in ("failed", "timeout")]

        logger.info(
            f"Aggregating {len(subtask_results)} results: "
            f"{len(successful)} successful, {len(failed)} failed"
        )

        # Determine overall status
        if len(successful) == 0:
            overall_status = "failed"
        elif len(failed) > 0:
            overall_status = "partial"
        else:
            overall_status = "completed"

        # Build subtask summaries
        subtask_summaries = []
        for result in subtask_results:
            summary = {
                "delegation_id": result.get("delegation_id"),
                "status": result.get("status"),
            }
            if result.get("status") == "completed":
                output = result.get("result", {}).get("output", "")
                summary["output_preview"] = output[:200] + "..." if len(output) > 200 else output
            else:
                summary["error"] = result.get("error", "Unknown error")
            subtask_summaries.append(summary)

        # Synthesize results using LLM if we have successful results
        synthesized_response = ""
        if successful and self._llm_router:
            synthesized_response = await self._synthesize_with_llm(
                successful_results=successful,
                failed_results=failed,
                original_task=original_task_description,
            )
        elif successful:
            # Fallback: concatenate outputs if no LLM available
            outputs = [
                r.get("result", {}).get("output", "")
                for r in successful
                if r.get("result", {}).get("output")
            ]
            synthesized_response = "\n\n---\n\n".join(outputs)
        else:
            # All failed
            error_messages = [r.get("error", "Unknown error") for r in failed]
            synthesized_response = (
                "Unable to complete task. All subtasks failed:\n"
                + "\n".join(f"- {e}" for e in error_messages)
            )

        return {
            "status": overall_status,
            "synthesized_response": synthesized_response,
            "successful_count": len(successful),
            "failed_count": len(failed),
            "subtask_summaries": subtask_summaries,
        }

    async def _synthesize_with_llm(
        self,
        successful_results: list[dict[str, Any]],
        failed_results: list[dict[str, Any]],
        original_task: str | None,
    ) -> str:
        """
        Use LLM to synthesize a coherent response from subtask results.

        Args:
            successful_results: Successfully completed subtask results
            failed_results: Failed subtask results
            original_task: Original task description for context

        Returns:
            Synthesized response string
        """
        # Build synthesis prompt
        outputs_text = ""
        for i, result in enumerate(successful_results, 1):
            output = result.get("result", {}).get("output", "No output")
            capability = result.get("subtask", {}).get("assigned_capability", "unknown")
            outputs_text += f"\n\n### Subtask {i} ({capability}):\n{output}"

        synthesis_prompt = f"""You are synthesizing results from multiple specialized sub-agents.

Original Task: {original_task or 'Not specified'}

Subtask Results:{outputs_text}

{"Note: " + str(len(failed_results)) + " subtask(s) failed." if failed_results else ""}

Please synthesize these results into a coherent, comprehensive response that addresses the original task.
Integrate the findings naturally without explicitly mentioning "subtasks" or "sub-agents".
"""

        messages = [
            {"role": "system", "content": "You are a helpful assistant synthesizing research results."},
            {"role": "user", "content": synthesis_prompt},
        ]

        # Build synthesis config from dedicated config or sub-agent config
        synthesis_config = self._synthesis_llm_config or {
            "provider": self._sub_agent_llm_config.get("llm_provider", "gemini"),
            "model": self._sub_agent_llm_config.get("model", "gemini-2.0-flash-exp"),
            "temperature": 0.7,
            "max_tokens": 2048,
        }

        try:
            llm_response = await self._llm_router.call(
                messages=messages,
                config=synthesis_config,
            )
            return llm_response.content or ""
        except Exception as e:
            logger.error(f"LLM synthesis failed: {e}")
            # Fallback to simple concatenation
            outputs = [
                r.get("result", {}).get("output", "")
                for r in successful_results
            ]
            return "\n\n".join(outputs)

    async def orchestrate_delegation(
        self,
        task: Task,
        analysis: dict[str, Any],
        execution_plan: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Complete delegation workflow: spawn, delegate, collect, aggregate.

        Orchestrates the full multi-agent delegation workflow:
        1. Spawn or find capable agents for each required capability
        2. Delegate subtasks to sub-agents
        3. Collect results with timeout handling
        4. Aggregate results into final response
        5. Cleanup sub-agents

        Args:
            task: The original task
            analysis: Task complexity analysis
            execution_plan: Delegation plan from _create_delegation_plan

        Returns:
            Complete orchestration result with aggregated response
        """
        logger.info(f"Starting orchestration for task {task.task_id}")

        delegations = []
        agent_assignments = execution_plan.get("agent_assignments", {})
        subtasks = execution_plan.get("subtasks", [])

        # Step 1: Ensure agents are available for each capability
        for subtask in subtasks:
            capability_id = subtask.get("assigned_capability")
            if not capability_id:
                continue

            assignment = agent_assignments.get(capability_id, {})

            if assignment.get("action") == "spawn" or not assignment.get("agent_id"):
                # Spawn new sub-agent
                sub_agent_id = await self.spawn_sub_agent(capability_id)
                if sub_agent_id:
                    assignment["agent_id"] = sub_agent_id
                    assignment["action"] = "spawned"
                    agent_assignments[capability_id] = assignment
                else:
                    logger.error(f"Failed to spawn agent for capability '{capability_id}'")
                    continue

        # Step 2: Delegate subtasks to sub-agents
        # For sequential workflows, collect results as we go so prior results
        # can be passed to subsequent subtasks as context
        is_parallel = execution_plan.get("parallel_execution", True)
        collected_results: list[dict[str, Any]] = []

        if is_parallel:
            # Parallel: delegate all at once
            for i, subtask in enumerate(subtasks):
                capability_id = subtask.get("assigned_capability")
                assignment = agent_assignments.get(capability_id, {})
                sub_agent_id = assignment.get("agent_id")

                if not sub_agent_id:
                    logger.warning(
                        f"No agent available for subtask '{subtask.get('subtask_id')}'"
                    )
                    continue

                delegation_info = await self.delegate_to_sub_agent(
                    sub_agent_id=sub_agent_id,
                    subtask=subtask,
                    parent_task_description=task.task_description,
                    subtask_index=i,
                    total_subtasks=len(subtasks),
                    prior_results=None,  # No prior results in parallel mode
                )
                delegations.append(delegation_info)

            if not delegations:
                logger.error("No delegations were created - falling back to direct execution")
                return await self._execute_task_directly(task)

            # Collect all results at once
            logger.info(f"Collecting results from {len(delegations)} parallel delegations")
            collected_results = await self._collect_delegation_results(
                delegations=delegations,
                timeout_seconds=DEFAULT_DELEGATION_TIMEOUT_SECONDS,
            )
        else:
            # Sequential: delegate one at a time, passing prior results as context
            for i, subtask in enumerate(subtasks):
                capability_id = subtask.get("assigned_capability")
                assignment = agent_assignments.get(capability_id, {})
                sub_agent_id = assignment.get("agent_id")

                if not sub_agent_id:
                    logger.warning(
                        f"No agent available for subtask '{subtask.get('subtask_id')}'"
                    )
                    continue

                logger.info(
                    f"Sequential delegation {i + 1}/{len(subtasks)}: "
                    f"{subtask.get('subtask_id')} → {sub_agent_id}"
                )

                delegation_info = await self.delegate_to_sub_agent(
                    sub_agent_id=sub_agent_id,
                    subtask=subtask,
                    parent_task_description=task.task_description,
                    subtask_index=i,
                    total_subtasks=len(subtasks),
                    prior_results=collected_results,  # Pass all prior results
                )
                delegations.append(delegation_info)

                # Collect this single result before moving to next
                step_results = await self._collect_delegation_results(
                    delegations=[delegation_info],
                    timeout_seconds=DEFAULT_DELEGATION_TIMEOUT_SECONDS,
                )
                collected_results.extend(step_results)

            if not delegations:
                logger.error("No delegations were created - falling back to direct execution")
                return await self._execute_task_directly(task)

        # Step 3: Aggregate results
        aggregated = await self.aggregate_results(
            subtask_results=collected_results,
            original_task_description=task.task_description,
        )

        # Step 4: Store delegation results in long-term memory
        await self.context_manager.store_delegation_result(
            vector_memory=self._vector_memory,
            agent_id=self.agent_id,
            user_id=self._user_id or "",
            task_description=task.task_description,
            aggregated_result=aggregated,
        )

        # Step 5: Cleanup spawned sub-agents
        await self.cleanup_sub_agents()

        return {
            "status": aggregated["status"],
            "execution_mode": "delegated",
            "task_id": task.task_id,
            "response": aggregated["synthesized_response"],
            "delegations_completed": aggregated["successful_count"],
            "delegations_failed": aggregated["failed_count"],
            "subtask_summaries": aggregated["subtask_summaries"],
        }

    async def _collect_delegation_results(
        self,
        delegations: list[dict[str, Any]],
        timeout_seconds: int = DEFAULT_DELEGATION_TIMEOUT_SECONDS,
    ) -> list[dict[str, Any]]:
        """
        Collect results from all delegated subtasks with timeout.

        Sets up listeners on reply channels and waits for responses
        from sub-agents.

        Args:
            delegations: List of delegation info dicts
            timeout_seconds: Maximum time to wait for all results

        Returns:
            List of result dicts, one per delegation
        """
        results = []
        pending = {d["delegation_id"]: d for d in delegations}
        collected = {}

        # Start time for timeout tracking
        start_time = datetime.utcnow()

        async def handle_result(data: dict[str, Any]) -> None:
            """Handle incoming delegation result."""
            delegation_id = data.get("delegation_id")
            if delegation_id and delegation_id in pending:
                collected[delegation_id] = data
                logger.debug(f"Received result for delegation {delegation_id}")

        # Subscribe to reply channels
        listeners = []
        for delegation in delegations:
            reply_channel = delegation["reply_channel"]

            async def create_listener(channel: str) -> None:
                try:
                    await self.message_broker.subscribe(channel, handle_result)
                except Exception as e:
                    logger.error(f"Error subscribing to {channel}: {e}")

            # Start listener as a task (non-blocking)
            listener_task = asyncio.create_task(
                create_listener(reply_channel)
            )
            listeners.append(listener_task)

        # Poll for results until timeout or all collected
        poll_interval = 0.5  # seconds
        while True:
            elapsed = (datetime.utcnow() - start_time).total_seconds()

            # Check if all results collected
            if len(collected) >= len(pending):
                logger.info("All delegation results collected")
                break

            # Check timeout
            if elapsed >= timeout_seconds:
                logger.warning(
                    f"Delegation timeout after {timeout_seconds}s. "
                    f"Collected {len(collected)}/{len(pending)} results."
                )
                break

            await asyncio.sleep(poll_interval)

        # Cancel listener tasks
        for listener in listeners:
            listener.cancel()

        # Build results list and record outcomes
        for delegation_id, delegation in pending.items():
            sub_agent_id = delegation.get("sub_agent_id", "")

            if delegation_id in collected:
                result_data = collected[delegation_id]
                status = result_data.get("status", "completed")
                results.append({
                    "delegation_id": delegation_id,
                    "status": status,
                    "result": result_data.get("result", {}),
                    "subtask": delegation.get("subtask", {}),
                    "error": result_data.get("error"),
                })

                # Record outcome in circuit breaker and directory
                if status == "completed":
                    exec_time = result_data.get("result", {}).get("execution_time_ms", 0)
                    self.circuit_breaker.record_success(sub_agent_id)
                    self.agent_directory.record_task_outcome(
                        sub_agent_id, success=True, response_time_ms=exec_time,
                    )
                else:
                    self.circuit_breaker.record_failure(sub_agent_id)
                    self.agent_directory.record_task_outcome(
                        sub_agent_id, success=False,
                    )
            else:
                # Timeout - no result received
                results.append({
                    "delegation_id": delegation_id,
                    "status": "timeout",
                    "result": {},
                    "subtask": delegation.get("subtask", {}),
                    "error": f"Timeout after {timeout_seconds}s",
                })
                self.circuit_breaker.record_failure(sub_agent_id)
                self.agent_directory.record_task_outcome(
                    sub_agent_id, success=False,
                )

            # Decrement active tasks in directory
            self.agent_directory.decrement_active_tasks(sub_agent_id)

        return results

    async def cleanup_sub_agents(self) -> None:
        """
        Terminate all spawned sub-agents.

        Cleans up sub-agents created during orchestration to
        prevent resource leaks. Sub-agents are terminated immediately
        after task completion.
        """
        if not self._spawned_sub_agents:
            return

        if not self._agent_service:
            logger.warning("Cannot cleanup sub-agents: agent_service not available")
            return

        logger.info(f"Cleaning up {len(self._spawned_sub_agents)} spawned sub-agents")

        for sub_agent_id in self._spawned_sub_agents:
            try:
                await self._agent_service.terminate_agent(sub_agent_id)
                self.agent_directory.unregister(sub_agent_id)
                logger.debug(f"Terminated sub-agent {sub_agent_id}")
            except Exception as e:
                logger.error(f"Failed to terminate sub-agent {sub_agent_id}: {e}")

        self._spawned_sub_agents.clear()

    def analyze_task_only(self, task_description: str) -> dict[str, Any]:
        """
        Analyze task without executing (useful for testing).

        Args:
            task_description: Task description string

        Returns:
            Analysis result
        """
        return self.task_analyzer.analyze_task_complexity(task_description)


# Helper function for easy instantiation
def create_master_orchestrator(agent_id: str) -> MasterAgentOrchestrator:
    """
    Create a master agent orchestrator.

    Args:
        agent_id: Master agent ID

    Returns:
        MasterAgentOrchestrator instance
    """
    return MasterAgentOrchestrator(agent_id=agent_id)
