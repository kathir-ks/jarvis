"""Agent runtime loop with Redis pub/sub, task execution, and checkpointing.

Phase 4.6 enhancements:
- AgentCommunicationHub for peer-to-peer and topic-based messaging
- Heartbeat broadcasting for agent health monitoring
- Timeout enforcement on delegated task execution
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING

from ..db.redis_client import get_redis_client
from ..db.repositories import AgentRepository, TaskRepository
from ..db.vector_memory import VectorMemoryService, get_vector_memory_service
from ..llm.prompt_builder import PromptBuilder
from ..llm.router import LLMRouter
from ..llm.tool_registry import get_tool_registry, ToolRegistry
from ..mcp.client import MCPClient
from ..messaging.broker import MessageBroker
from ..tasks.task_executors import submit_task_to_celery
from .agent import Agent, AgentStatus, AgentType
from .agent_communication import (
    AgentCommunicationHub,
    AgentMessage,
    MessageType,
    send_heartbeat,
)
from .agent_directory import get_agent_directory
from .dag_executor import DAGExecutor
from .task import Task, TaskStatus
from .master_agent import MasterAgentOrchestrator

if TYPE_CHECKING:
    from ..services.agents import AgentService

logger = logging.getLogger(__name__)

# Max seconds a delegated subtask may run before forced timeout
DELEGATION_EXECUTION_TIMEOUT_SECONDS = 300


class AgentRunner:
    """Agent event loop with message handling, task execution, and state persistence."""

    def __init__(self, agent_id: str, agent_service: "AgentService | None" = None):
        self.agent_id = agent_id
        self.running = False

        # Repositories
        self.agent_repo = AgentRepository()
        self.task_repo = TaskRepository()

        # Messaging / LLM
        self.message_broker = MessageBroker()
        self.redis = get_redis_client()
        self.llm_router = LLMRouter()
        self.prompt_builder = PromptBuilder()
        self.tool_registry = get_tool_registry()

        # MCP Client (optional - initialized if agent has mcp_server_url)
        self.mcp_client: MCPClient | None = None

        # Vector Memory (long-term)
        self.vector_memory: VectorMemoryService | None = None

        # Master Agent Orchestrator (initialized for MASTER agents in run())
        self.master_orchestrator: MasterAgentOrchestrator | None = None
        self._agent_service = agent_service

        # Communication hub for peer-to-peer and topic messaging
        self.comm_hub: AgentCommunicationHub | None = None

        # Agent directory for health-aware discovery
        self.agent_directory = get_agent_directory()

        # State
        self.agent: Agent | None = None
        self.last_checkpoint_time: datetime | None = None
        self._last_heartbeat_time: datetime | None = None

        # Thread-safe message queue (replaces plain list)
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        # Track background tasks for proper lifecycle management
        self._background_tasks: set[asyncio.Task] = set()

    async def run(self):
        """Main event loop for agent."""
        self.running = True

        # Load agent state from DB
        self.agent = await self.agent_repo.get_by_id(self.agent_id)
        if not self.agent:
            logger.error(f"Agent {self.agent_id} not found in database")
            return

        if not self.agent.is_active():
            logger.warning(f"Agent {self.agent_id} is not active (status: {self.agent.status})")
            return

        logger.info(f"Agent {self.agent_id} starting event loop (type: {self.agent.agent_type})")

        # Initialize master orchestrator for MASTER agents
        if self.agent.agent_type == AgentType.MASTER:
            self.master_orchestrator = MasterAgentOrchestrator(
                agent_id=self.agent_id,
                agent_service=self._agent_service,
                llm_router=self.llm_router,
                user_id=self.agent.user_id,
                master_agent=self.agent,
                vector_memory=self.vector_memory,
            )
            logger.info(f"Master orchestrator initialized for agent {self.agent_id}")

        # Initialize MCP client if configured
        if self.agent.config.mcp_server_url:
            try:
                self.mcp_client = MCPClient(
                    server_url=self.agent.config.mcp_server_url,
                    timeout_seconds=self.agent.config.mcp_timeout_seconds,
                )
                await self.mcp_client.connect()
                server_info = await self.mcp_client.initialize()
                server_name = server_info.get("serverInfo", {}).get("name", "unknown")
                server_version = server_info.get("serverInfo", {}).get("version", "unknown")
                logger.info(
                    f"Agent {self.agent_id} connected to MCP server: %s v%s at %s",
                    server_name,
                    server_version,
                    self.agent.config.mcp_server_url,
                )
            except Exception as e:
                logger.warning(f"MCP client initialization failed (falling back to direct tool registry): {e}")
                self.mcp_client = None

        # Initialize vector memory
        try:
            self.vector_memory = get_vector_memory_service()
            await self.vector_memory.initialize_collections()
            logger.info(f"Agent {self.agent_id} vector memory initialized")

            # Update master orchestrator with vector memory reference
            if self.master_orchestrator:
                self.master_orchestrator._vector_memory = self.vector_memory
        except Exception as e:
            logger.warning(f"Vector memory initialization failed (continuing without): {e}")
            self.vector_memory = None

        # Update status to RUNNING
        await self.agent_repo.update_status(self.agent_id, AgentStatus.RUNNING)

        # Register in agent directory for health-aware discovery
        agent_capabilities = list(self.agent.tools_available) if self.agent.tools_available else []
        self.agent_directory.register(
            agent_id=self.agent_id,
            agent_type=self.agent.agent_type if self.agent.agent_type else "sub_agent",
            capabilities=agent_capabilities,
            metadata={
                "llm_provider": self.agent.config.llm_provider,
                "model": self.agent.config.model,
                "user_id": self.agent.user_id,
            },
        )

        # Initialize communication hub for peer-to-peer messaging
        self.comm_hub = AgentCommunicationHub(
            agent_id=self.agent_id,
            message_broker=self.message_broker,
        )

        # Register handler for peer messages
        self.comm_hub.on_message(MessageType.PEER_MESSAGE, self._handle_peer_message)
        self.comm_hub.on_message(MessageType.REQUEST, self._handle_request_message)

        # Start message listener as a tracked background task
        self._spawn_background_task(self._listen_for_messages())

        # Main loop
        loop_interval = self.agent.config.loop_interval_seconds
        checkpoint_interval = self.agent.config.checkpoint_interval_seconds

        try:
            while self.running:
                try:
                    # 1. Process pending messages
                    await self._process_messages()

                    # 2. Poll and execute pending tasks
                    await self._execute_pending_tasks()

                    # 3. Checkpoint if needed
                    await self._checkpoint_if_needed(checkpoint_interval)

                    # 4. Send heartbeat (every 15 seconds)
                    await self._send_heartbeat_if_needed()

                    # 5. Sleep before next iteration
                    await asyncio.sleep(loop_interval)

                except Exception as e:
                    logger.error(f"Error in agent {self.agent_id} loop: {e}", exc_info=True)
                    await self.agent_repo.update_status(self.agent_id, AgentStatus.ERROR)
                    await asyncio.sleep(5)  # Back off on error
        finally:
            # Unregister from directory
            self.agent_directory.unregister(self.agent_id)

            # Stop communication hub
            if self.comm_hub:
                await self.comm_hub.stop()

            # Cancel all background tasks on exit
            await self._cancel_background_tasks()

    def _spawn_background_task(self, coro) -> asyncio.Task:
        """Create a tracked background task with automatic cleanup and restart."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _on_done(t: asyncio.Task):
            self._background_tasks.discard(t)
            if not t.cancelled() and t.exception():
                logger.error(
                    f"Background task for agent {self.agent_id} failed: {t.exception()}"
                )
                # Restart the message listener if it dies
                if self.running:
                    logger.info(f"Restarting message listener for agent {self.agent_id}")
                    self._spawn_background_task(self._listen_for_messages())

        task.add_done_callback(_on_done)
        return task

    async def _cancel_background_tasks(self):
        """Cancel all tracked background tasks."""
        for task in list(self._background_tasks):
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

    async def _listen_for_messages(self):
        """Subscribe to agent inbox and queue messages."""
        channel = f"agent:{self.agent_id}:inbox"

        async def message_handler(message_data: Any):
            logger.info(f"Agent {self.agent_id} received message: {message_data}")
            await self._message_queue.put(
                {"data": message_data, "received_at": datetime.utcnow()}
            )

        try:
            await self.message_broker.subscribe(channel, message_handler)
        except asyncio.CancelledError:
            logger.debug(f"Message listener for agent {self.agent_id} cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in message listener for agent {self.agent_id}: {e}")
            raise  # Let _spawn_background_task handle restart

    async def _process_messages(self):
        """Process queued messages from the async queue."""
        # Drain all available messages without blocking
        messages_to_process: list[dict[str, Any]] = []
        while not self._message_queue.empty():
            try:
                msg = self._message_queue.get_nowait()
                messages_to_process.append(msg)
            except asyncio.QueueEmpty:
                break

        for msg in messages_to_process:
            try:
                await self._handle_message(msg)
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

    async def _handle_message(self, message: dict[str, Any]):
        """Handle individual message via LLM + tool orchestration."""
        if not self.agent:
            return

        payload = self._normalize_message(message)

        # Check if this is a delegation request (for SUB_AGENT)
        if payload.get("type") == "delegation_request":
            if self.agent.agent_type == AgentType.SUB_AGENT:
                await self._handle_delegation_request(payload)
                return
            else:
                logger.warning(
                    f"Non-sub-agent {self.agent_id} received delegation request - ignoring"
                )
                return

        user_content = payload.get("content") or str(payload)
        logger.info("Agent %s handling message: %s", self.agent_id, payload)

        # Retrieve long-term context from vector memory
        long_term_context = None
        if self.vector_memory:
            try:
                long_term_context = await self.vector_memory.get_recent_context(
                    user_id=self.agent.user_id,
                    agent_id=self.agent_id,
                    query=user_content if isinstance(user_content, str) else None,
                    interaction_limit=5,
                    discovery_limit=3,
                    knowledge_limit=3,
                )
                logger.debug("Retrieved long-term context: %d interactions, %d discoveries, %d knowledge",
                            len(long_term_context.get("interactions", [])),
                            len(long_term_context.get("discoveries", [])),
                            len(long_term_context.get("knowledge", [])))
            except Exception as e:
                logger.warning("Failed to retrieve long-term context: %s", e)

        # Build prompt with both short-term and long-term memory
        llm_messages = self.prompt_builder.build_agent_messages(
            self.agent,
            payload,
            long_term_context=long_term_context,
        )
        llm_config = await self._build_llm_config()

        # Execute tool-calling loop (shared with delegation handler)
        llm_response, assistant_text, iteration, tool_calls_made = (
            await self._run_tool_calling_loop(llm_messages, llm_config)
        )

        if llm_response is None:
            return  # LLM call failed entirely; error already logged

        # Update short-term memory with user + assistant exchange
        await self._append_memory(
            role="user",
            content=user_content,
            metadata={"message_type": payload.get("type")},
        )
        await self._append_memory(
            role="assistant",
            content=assistant_text,
            metadata={
                "provider": llm_response.provider,
                "model": llm_response.model,
                "iterations": iteration,
            },
        )

        # Store interaction in long-term vector memory
        if self.vector_memory:
            try:
                # Store user message
                await self.vector_memory.store_interaction(
                    content=user_content if isinstance(user_content, str) else json.dumps(user_content),
                    user_id=self.agent.user_id,
                    agent_id=self.agent_id,
                    interaction_type="user_message",
                    metadata={"message_type": payload.get("type")},
                )
                # Store assistant response
                await self.vector_memory.store_interaction(
                    content=assistant_text,
                    user_id=self.agent.user_id,
                    agent_id=self.agent_id,
                    interaction_type="assistant_response",
                    metadata={
                        "provider": llm_response.provider,
                        "model": llm_response.model,
                        "iterations": iteration,
                    },
                )
                logger.debug("Stored interaction in vector memory")
            except Exception as e:
                logger.warning("Failed to store interaction in vector memory: %s", e)

        # Persist quick context hints
        self.agent.context["last_response"] = assistant_text
        self.agent.context["last_interaction_at"] = datetime.utcnow().isoformat()

        # Respond back if a reply channel is provided
        reply_channel = payload.get("reply_channel")
        if reply_channel:
            await self.message_broker.publish(
                reply_channel,
                {
                    "type": "agent_response",
                    "agent_id": self.agent_id,
                    "content": assistant_text,
                    "metadata": {
                        "provider": llm_response.provider,
                        "model": llm_response.model,
                        "iterations": iteration,
                    },
                },
            )

    async def _run_tool_calling_loop(
        self,
        llm_messages: list[dict[str, Any]],
        llm_config: dict[str, Any],
        max_iterations: int = 10,
    ) -> tuple[Any | None, str, int, list[dict[str, Any]]]:
        """
        Execute the LLM tool-calling loop until a final text response or iteration limit.

        This is the single shared implementation used by both regular message handling
        and sub-agent delegation handling.

        Args:
            llm_messages: Conversation messages to send to the LLM.
            llm_config: LLM configuration dict (provider, model, tools, etc.).
            max_iterations: Maximum rounds of tool calling before stopping.

        Returns:
            Tuple of (llm_response, assistant_text, iterations_used, tool_calls_made).
            llm_response is None if the very first LLM call failed.
        """
        iteration = 0
        assistant_text = ""
        llm_response = None
        tool_calls_made: list[dict[str, Any]] = []

        while iteration < max_iterations:
            iteration += 1

            try:
                llm_response = await self.llm_router.call(llm_messages, llm_config)
            except Exception as exc:
                logger.error(
                    "LLM call failed for agent %s (iteration %d): %s",
                    self.agent_id, iteration, exc, exc_info=True,
                )
                if iteration == 1:
                    # First call failed — surface error to memory and bail out
                    await self._append_memory(
                        role="assistant",
                        content=f"Error while generating response: {exc}",
                    )
                    return None, "", iteration, tool_calls_made
                # Subsequent calls: return what we have so far
                break

            # Check if LLM wants to call tools
            if llm_response.tool_calls:
                logger.info(
                    "Agent %s LLM requested %d tool calls",
                    self.agent_id, len(llm_response.tool_calls),
                )

                # Add assistant message with tool calls to history
                llm_messages.append({
                    "role": "assistant",
                    "content": llm_response.content or "",
                    "tool_calls": llm_response.tool_calls,
                })

                # Execute each tool call
                for tool_call in llm_response.tool_calls:
                    tool_result_content = await self._execute_single_tool(tool_call)

                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": tool_call["function"]["name"],
                        "content": tool_result_content,
                    })
                    tool_calls_made.append({
                        "name": tool_call["function"]["name"],
                        "args": (
                            json.loads(tool_call["function"]["arguments"])
                            if isinstance(tool_call["function"]["arguments"], str)
                            else tool_call["function"]["arguments"]
                        ),
                    })

                # Continue loop to let LLM process tool results
                continue

            # No tool calls — we have the final response
            assistant_text = llm_response.content or ""
            logger.info("Agent %s completed response after %d iterations", self.agent_id, iteration)
            break

        if iteration >= max_iterations:
            logger.warning(
                "Agent %s hit max tool calling iterations (%d)",
                self.agent_id, max_iterations,
            )
            assistant_text = (
                (llm_response.content if llm_response else "")
                or "I apologize, but I reached the maximum number of tool calls."
            )

        return llm_response, assistant_text, iteration, tool_calls_made

    async def _execute_single_tool(self, tool_call: dict[str, Any]) -> str:
        """
        Execute a single tool call (via MCP or direct registry) and return result JSON.

        Args:
            tool_call: Tool call dict with 'id', 'function.name', 'function.arguments'.

        Returns:
            JSON string with tool result or error.
        """
        tool_name = tool_call["function"]["name"]
        tool_args_str = tool_call["function"]["arguments"]

        try:
            tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
        except json.JSONDecodeError as e:
            logger.error("Failed to parse tool arguments: %s", e)
            return json.dumps({"error": f"Invalid JSON arguments: {str(e)}"})

        logger.info("Executing tool: %s with args: %s", tool_name, tool_args)

        if self.mcp_client:
            try:
                mcp_result = await self.mcp_client.call_tool(tool_name, tool_args)
                logger.info("Tool %s completed via MCP", tool_name)
                return json.dumps(mcp_result.get("result", {}))
            except Exception as mcp_error:
                logger.warning("MCP tool %s failed: %s", tool_name, mcp_error)
                return json.dumps({"error": f"MCP tool execution failed: {str(mcp_error)}"})
        else:
            tool_result = await self.tool_registry.execute(tool_name, tool_args)
            if tool_result.success:
                logger.info(
                    "Tool %s completed successfully in %.2fms",
                    tool_name, tool_result.execution_time_ms,
                )
                return json.dumps(tool_result.result)
            else:
                logger.warning("Tool %s failed: %s", tool_name, tool_result.error)
                return json.dumps({"error": tool_result.error})

    async def _handle_delegation_request(self, payload: dict[str, Any]) -> None:
        """
        Handle a delegation request from a master agent.

        Executes the delegated subtask using the shared tool-calling loop and sends
        the result back to the master agent via the reply channel.
        """
        if not self.agent:
            return

        delegation_id = payload.get("delegation_id")
        master_agent_id = payload.get("master_agent_id")
        task_info = payload.get("task", {})
        reply_channel = payload.get("reply_channel")
        delegation_context = payload.get("context", {})

        logger.info(
            f"Sub-agent {self.agent_id} handling delegation {delegation_id} "
            f"from master {master_agent_id}"
        )

        start_time = datetime.utcnow()
        subtask_description = task_info.get("description", "")

        # Determine execution timeout from the delegation request
        task_timeout = task_info.get("timeout_seconds", DELEGATION_EXECUTION_TIMEOUT_SECONDS)

        try:
            # Execute with timeout enforcement
            result_message = await asyncio.wait_for(
                self._execute_delegation(
                    delegation_id=delegation_id,
                    task_info=task_info,
                    delegation_context=delegation_context,
                    start_time=start_time,
                ),
                timeout=task_timeout,
            )

        except asyncio.TimeoutError:
            execution_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.error(
                f"Delegation {delegation_id} timed out after {task_timeout}s"
            )
            result_message = {
                "type": "delegation_result",
                "delegation_id": delegation_id,
                "sub_agent_id": self.agent_id,
                "status": "failed",
                "result": {
                    "subtask_id": task_info.get("subtask_id"),
                    "output": "",
                    "tool_calls": [],
                    "execution_time_ms": execution_time_ms,
                },
                "error": f"Execution timed out after {task_timeout}s",
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Delegation {delegation_id} failed: {e}", exc_info=True)
            execution_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            result_message = {
                "type": "delegation_result",
                "delegation_id": delegation_id,
                "sub_agent_id": self.agent_id,
                "status": "failed",
                "result": {
                    "subtask_id": task_info.get("subtask_id"),
                    "output": "",
                    "tool_calls": [],
                    "execution_time_ms": execution_time_ms,
                },
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Publish result to reply channel
        if reply_channel:
            await self.message_broker.publish(reply_channel, result_message)
        else:
            logger.warning(f"No reply channel for delegation {delegation_id}")

    async def _execute_pending_tasks(self):
        """Fetch and execute pending tasks using DAG executor."""
        # Get pending tasks for this agent
        tasks = await self.task_repo.get_pending_tasks(self.agent_id, limit=25)

        if not tasks:
            return

        logger.info(f"Agent {self.agent_id} found {len(tasks)} pending tasks")

        # Execute with DAG respecting dependencies
        dag_executor = DAGExecutor(tasks, max_concurrent=5)

        async def task_executor(task: Task) -> dict[str, Any]:
            """Execute single task."""
            # Check for cancellation
            if task.should_cancel():
                await self.task_repo.update_status(
                    task.task_id,
                    TaskStatus.CANCELLED,
                    error="Cancelled by user"
                )
                return {"status": "CANCELLED"}

            # Submit to Celery for execution
            await self.task_repo.update_status(task.task_id, TaskStatus.RUNNING)

            try:
                result = await submit_task_to_celery(task)
                await self.task_repo.update_status(
                    task.task_id,
                    TaskStatus.COMPLETED,
                    result=result
                )
                return result
            except Exception as e:
                logger.error(f"Task {task.task_id} execution failed: {e}")
                await self.task_repo.increment_retry(task.task_id)

                # Check if retries exhausted
                task_updated = await self.task_repo.get_by_id(task.task_id)
                if task_updated and task_updated.retry_count >= task_updated.max_retries:
                    await self.task_repo.update_status(
                        task.task_id,
                        TaskStatus.FAILED,
                        error=str(e)
                    )
                else:
                    # Reset to PENDING for retry
                    await self.task_repo.update_status(task.task_id, TaskStatus.PENDING)

                raise

        # Execute DAG
        try:
            results = await dag_executor.execute(task_executor)
            logger.info(f"Completed {len(results)} tasks for agent {self.agent_id}")
        except Exception as e:
            logger.error(f"DAG execution error for agent {self.agent_id}: {e}")

    async def _checkpoint_if_needed(self, interval_seconds: int):
        """Checkpoint agent state if interval elapsed."""
        now = datetime.utcnow()

        if self.last_checkpoint_time is None:
            should_checkpoint = True
        else:
            should_checkpoint = (now - self.last_checkpoint_time).total_seconds() >= interval_seconds

        if should_checkpoint and self.agent:
            await self._checkpoint()

    async def _checkpoint(self):
        """Save agent state to database."""
        if not self.agent:
            return

        # Update task queue metadata
        pending_tasks = await self.task_repo.get_pending_tasks(self.agent_id, limit=100)
        self.agent.task_queue_meta = {
            "pending_count": len(pending_tasks),
            "active_tasks": [t.task_id for t in pending_tasks[:10]]
        }

        # Persist checkpoint
        await self.agent_repo.checkpoint(
            self.agent_id,
            self.agent.context,
            self.agent.task_queue_meta
        )

        self.last_checkpoint_time = datetime.utcnow()
        logger.debug(f"Checkpointed agent {self.agent_id}")

    def stop(self):
        """Stop the agent loop gracefully."""
        self.running = False
        logger.info(f"Agent {self.agent_id} stopping")

    async def terminate(self):
        """Terminate agent and cleanup."""
        self.stop()

        # Cancel in-flight background tasks
        await self._cancel_background_tasks()

        if self.agent:
            await self._checkpoint()
            await self.agent_repo.update_status(self.agent_id, AgentStatus.TERMINATED)

        # Close MCP client if active
        if self.mcp_client:
            await self.mcp_client.close()

        logger.info(f"Agent {self.agent_id} terminated")

    async def _build_llm_config(self, include_tools: bool = True) -> dict[str, Any]:
        if not self.agent:
            return {}

        config = {
            "provider": self.agent.config.llm_provider,
            "model": self.agent.config.model,
            "temperature": self.agent.config.temperature,
            "max_tokens": self.agent.config.max_tokens,
        }

        # Add tools if agent has tools configured
        if include_tools:
            # Get tools from MCP client if available, otherwise use direct registry
            if self.mcp_client:
                try:
                    all_tools = await self.mcp_client.list_tools()
                    logger.debug("Retrieved %d tools from MCP server", len(all_tools))
                except Exception as e:
                    logger.warning("Failed to list tools from MCP server: %s (falling back to registry)", e)
                    all_tools = self.tool_registry.get_openai_tools()
            else:
                all_tools = self.tool_registry.get_openai_tools()

            # Filter to specific tools if tools_available is configured
            if self.agent.tools_available:
                allowed_tool_names = set(self.agent.tools_available)
                filtered_tools = []
                for t in all_tools:
                    # Handle both OpenAI format {function: {name: "..."}} and MCP format {name: "..."}
                    tool_name = t.get("function", {}).get("name") or t.get("name")
                    if tool_name in allowed_tool_names:
                        filtered_tools.append(t)
                if filtered_tools:
                    config["tools"] = filtered_tools
            else:
                # Otherwise, provide all registered tools
                if all_tools:
                    config["tools"] = all_tools

        return config

    async def _append_memory(self, role: str, content: Any, metadata: dict[str, Any] | None = None):
        """Append entry to short-term memory with size limit."""
        if not self.agent:
            return

        entry = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.agent.short_term_memory.append(entry)

        if len(self.agent.short_term_memory) > 50:
            self.agent.short_term_memory = self.agent.short_term_memory[-50:]

    async def _execute_delegation(
        self,
        delegation_id: str,
        task_info: dict[str, Any],
        delegation_context: dict[str, Any],
        start_time: datetime,
    ) -> dict[str, Any]:
        """
        Execute the core delegation work (LLM + tools).

        Separated from _handle_delegation_request so it can be wrapped
        with asyncio.wait_for for timeout enforcement.
        """
        subtask_description = task_info.get("description", "")

        # Retrieve long-term context from vector memory
        long_term_context = None
        if self.vector_memory:
            try:
                long_term_context = await self.vector_memory.get_recent_context(
                    user_id=self.agent.user_id,
                    agent_id=self.agent_id,
                    query=subtask_description,
                    interaction_limit=3,
                    discovery_limit=2,
                    knowledge_limit=2,
                )
                logger.debug(
                    f"Delegation {delegation_id}: retrieved long-term context "
                    f"({len(long_term_context.get('interactions', []))} interactions)"
                )
            except Exception as e:
                logger.warning(f"Failed to retrieve long-term context for delegation: {e}")

        # Build prompt using delegation context
        if delegation_context:
            llm_messages = self.prompt_builder.build_delegation_messages(
                agent=self.agent,
                delegation_context=delegation_context,
                long_term_context=long_term_context,
            )
        else:
            llm_messages = self.prompt_builder.build_agent_messages(
                self.agent,
                {"content": subtask_description, "type": "delegation"},
                long_term_context=long_term_context,
            )

        llm_config = await self._build_llm_config()

        # Execute with shared tool-calling loop
        _llm_response, final_response, _iteration, tool_calls_made = (
            await self._run_tool_calling_loop(llm_messages, llm_config)
        )

        execution_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

        logger.info(
            f"Delegation {delegation_id} completed in {execution_time_ms:.0f}ms "
            f"with {len(tool_calls_made)} tool calls"
        )

        return {
            "type": "delegation_result",
            "delegation_id": delegation_id,
            "sub_agent_id": self.agent_id,
            "status": "completed",
            "result": {
                "subtask_id": task_info.get("subtask_id"),
                "output": final_response,
                "tool_calls": tool_calls_made,
                "execution_time_ms": execution_time_ms,
            },
            "error": None,
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def _handle_peer_message(self, msg: AgentMessage) -> None:
        """Handle an incoming peer-to-peer message via the communication hub."""
        if not self.agent:
            return

        content = msg.content.get("text", "") or msg.content.get("message", "")
        logger.info(
            "Agent %s received peer message from %s: %s",
            self.agent_id, msg.sender_id, content[:100],
        )

        # Process like a regular message but with peer context
        peer_payload = {
            "content": content,
            "type": "peer_message",
            "sender_id": msg.sender_id,
            "reply_channel": msg.reply_to,
        }
        await self._message_queue.put(
            {"data": peer_payload, "received_at": datetime.utcnow()}
        )

    async def _handle_request_message(self, msg: AgentMessage) -> None:
        """Handle an incoming request message (request-response pattern)."""
        if not self.agent or not self.comm_hub:
            return

        content = msg.content.get("text", "") or msg.content.get("question", "")
        logger.info(
            "Agent %s received request from %s: %s",
            self.agent_id, msg.sender_id, content[:100],
        )

        # Build a quick LLM response for the request
        llm_messages = self.prompt_builder.build_agent_messages(
            self.agent,
            {"content": content, "type": "peer_request", "sender_id": msg.sender_id},
        )
        llm_config = await self._build_llm_config()
        _, response_text, _, _ = await self._run_tool_calling_loop(
            llm_messages, llm_config, max_iterations=5,
        )

        # Send response back
        await self.comm_hub.respond(msg, {"text": response_text})

    async def _send_heartbeat_if_needed(self) -> None:
        """Send a heartbeat every 15 seconds for health monitoring."""
        now = datetime.utcnow()
        if (
            self._last_heartbeat_time
            and (now - self._last_heartbeat_time).total_seconds() < 15
        ):
            return

        pending_count = 0
        if self.agent and self.agent.task_queue_meta:
            pending_count = self.agent.task_queue_meta.get("pending_count", 0)

        status = "busy" if pending_count > 0 else "alive"

        try:
            await send_heartbeat(
                agent_id=self.agent_id,
                broker=self.message_broker,
                status=status,
                metadata={"pending_tasks": pending_count},
            )
            # Also update the directory directly
            self.agent_directory.heartbeat(
                agent_id=self.agent_id,
                status=status,
                active_tasks=pending_count,
            )
            self._last_heartbeat_time = now
        except Exception as e:
            logger.debug("Failed to send heartbeat: %s", e)

    def _normalize_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Normalize pending message structure."""
        if not message:
            return {"content": "", "type": "message"}

        payload = message.get("data") or {}
        if isinstance(payload, str):
            payload = self._safe_parse(payload)

        payload.setdefault("received_at", message.get("received_at") or datetime.utcnow())
        return payload

    @staticmethod
    def _safe_parse(raw: str) -> dict[str, Any]:
        """Best-effort parsing for message payloads."""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        try:
            import ast
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return {"content": raw}
