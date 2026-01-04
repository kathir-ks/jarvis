"""Agent runtime loop with Redis pub/sub, task execution, and checkpointing."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from ..db.redis_client import get_redis_client
from ..db.repositories import AgentRepository, TaskRepository
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
        
        # Messaging
        self.message_broker = MessageBroker()
        self.redis = get_redis_client()
        
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
        """Handle individual message (placeholder for LLM processing)."""
        # TODO: Parse message, call LLM, execute tools, respond
        logger.info(f"Handling message: {message}")
        
        # Update short-term memory
        if self.agent:
            self.agent.short_term_memory.append({
                "type": "message",
                "content": message,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Keep only last 50 messages in short-term memory
            if len(self.agent.short_term_memory) > 50:
                self.agent.short_term_memory = self.agent.short_term_memory[-50:]

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
        
        logger.info(f"Agent {self.agent_id} terminated")
