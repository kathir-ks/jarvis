"""Agent runtime loop with Redis pub/sub, task execution, and checkpointing."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from ..db.redis_client import get_redis_client
from ..db.repositories import AgentRepository, TaskRepository
from ..db.vector_memory import VectorMemoryService, get_vector_memory_service
from ..llm.prompt_builder import PromptBuilder
from ..llm.router import LLMRouter
from ..llm.tool_registry import get_tool_registry, ToolRegistry
from ..mcp.client import MCPClient
from ..messaging.broker import MessageBroker
from ..tasks.task_executors import submit_task_to_celery
from .agent import Agent, AgentStatus
from .dag_executor import DAGExecutor
from .task import Task, TaskStatus

logger = logging.getLogger(__name__)


class AgentRunner:
    """Agent event loop with message handling, task execution, and state persistence."""

    def __init__(self, agent_id: str):
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

        # State
        self.agent: Agent | None = None
        self.last_checkpoint_time: datetime | None = None
        self.pending_messages: list[dict[str, Any]] = []

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
        except Exception as e:
            logger.warning(f"Vector memory initialization failed (continuing without): {e}")
            self.vector_memory = None
        
        # Update status to RUNNING
        await self.agent_repo.update_status(self.agent_id, AgentStatus.RUNNING)
        
        # Start message listener in background
        asyncio.create_task(self._listen_for_messages())
        
        # Main loop
        loop_interval = self.agent.config.loop_interval_seconds
        checkpoint_interval = self.agent.config.checkpoint_interval_seconds
        
        while self.running:
            try:
                # 1. Process pending messages
                await self._process_messages()
                
                # 2. Poll and execute pending tasks
                await self._execute_pending_tasks()
                
                # 3. Checkpoint if needed
                await self._checkpoint_if_needed(checkpoint_interval)
                
                # 4. Sleep before next iteration
                await asyncio.sleep(loop_interval)
                
            except Exception as e:
                logger.error(f"Error in agent {self.agent_id} loop: {e}", exc_info=True)
                await self.agent_repo.update_status(self.agent_id, AgentStatus.ERROR)
                await asyncio.sleep(5)  # Back off on error

    async def _listen_for_messages(self):
        """Subscribe to agent inbox and queue messages."""
        channel = f"agent:{self.agent_id}:inbox"
        
        async def message_handler(message_data: Any):
            logger.info(f"Agent {self.agent_id} received message: {message_data}")
            self.pending_messages.append({"data": message_data, "received_at": datetime.utcnow()})
        
        try:
            await self.message_broker.subscribe(channel, message_handler)
        except Exception as e:
            logger.error(f"Error in message listener for agent {self.agent_id}: {e}")

    async def _process_messages(self):
        """Process queued messages."""
        if not self.pending_messages:
            return
        
        messages_to_process = self.pending_messages[:]
        self.pending_messages.clear()
        
        for msg in messages_to_process:
            try:
                await self._handle_message(msg)
            except Exception as e:
                logger.error(f"Error processing message: {e}")

    async def _handle_message(self, message: dict[str, Any]):
        """Handle individual message via LLM + tool orchestration."""
        if not self.agent:
            return

        payload = self._normalize_message(message)
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

        # Tool calling loop - LLM may need multiple rounds to complete tool calls
        max_iterations = 10
        iteration = 0
        assistant_text = ""

        while iteration < max_iterations:
            iteration += 1

            try:
                llm_response = await self.llm_router.call(llm_messages, llm_config)
            except Exception as exc:
                logger.error("LLM call failed for agent %s (iteration %d): %s",
                           self.agent_id, iteration, exc, exc_info=True)
                await self._append_memory(
                    role="assistant",
                    content=f"Error while generating response: {exc}",
                )
                return

            # Check if LLM wants to call tools
            if llm_response.tool_calls:
                logger.info("Agent %s LLM requested %d tool calls",
                          self.agent_id, len(llm_response.tool_calls))

                # Add assistant message with tool calls to history
                llm_messages.append({
                    "role": "assistant",
                    "content": llm_response.content or "",
                    "tool_calls": llm_response.tool_calls,
                })

                # Execute each tool call
                for tool_call in llm_response.tool_calls:
                    tool_name = tool_call["function"]["name"]
                    tool_args_str = tool_call["function"]["arguments"]

                    try:
                        # Parse arguments (they come as JSON string)
                        tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                    except json.JSONDecodeError as e:
                        logger.error("Failed to parse tool arguments: %s", e)
                        tool_result_content = json.dumps({
                            "error": f"Invalid JSON arguments: {str(e)}",
                        })
                    else:
                        # Execute tool (via MCP if available, otherwise direct registry)
                        logger.info("Executing tool: %s with args: %s", tool_name, tool_args)

                        if self.mcp_client:
                            # Execute via MCP protocol
                            try:
                                mcp_result = await self.mcp_client.call_tool(tool_name, tool_args)
                                tool_result_content = json.dumps(mcp_result.get("result", {}))
                                logger.info("Tool %s completed via MCP", tool_name)
                            except Exception as mcp_error:
                                tool_result_content = json.dumps({
                                    "error": f"MCP tool execution failed: {str(mcp_error)}",
                                })
                                logger.warning("MCP tool %s failed: %s", tool_name, mcp_error)
                        else:
                            # Execute via direct tool registry
                            tool_result = await self.tool_registry.execute(tool_name, tool_args)

                            if tool_result.success:
                                tool_result_content = json.dumps(tool_result.result)
                                logger.info("Tool %s completed successfully in %.2fms",
                                          tool_name, tool_result.execution_time_ms)
                            else:
                                tool_result_content = json.dumps({
                                    "error": tool_result.error,
                                })
                                logger.warning("Tool %s failed: %s", tool_name, tool_result.error)

                    # Add tool result to message history
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": tool_name,
                        "content": tool_result_content,
                    })

                # Continue loop to let LLM process tool results
                continue

            # No tool calls - we have the final response
            assistant_text = llm_response.content
            logger.info("Agent %s completed response after %d iterations", self.agent_id, iteration)
            break

        if iteration >= max_iterations:
            logger.warning("Agent %s hit max tool calling iterations (%d)",
                         self.agent_id, max_iterations)
            assistant_text = llm_response.content or "I apologize, but I reached the maximum number of tool calls."

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
