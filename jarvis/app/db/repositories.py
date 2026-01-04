"""MongoDB repositories for agents and tasks."""
import logging
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from ..db.mongo import get_mongo_db
from .agent import Agent, AgentStatus
from .task import Task, TaskStatus

logger = logging.getLogger(__name__)


class AgentRepository:
    """Repository for Agent CRUD operations."""

    def __init__(self):
        self.db = get_mongo_db()
        self.collection: AsyncIOMotorCollection = self.db["agents"]

    async def create(self, agent: Agent) -> Agent:
        """Insert new agent."""
        doc = agent.to_mongo_dict()
        result = await self.collection.insert_one(doc)
        logger.info(f"Created agent {agent.agent_id}")
        return agent

    async def get_by_id(self, agent_id: str) -> Agent | None:
        """Fetch agent by ID."""
        doc = await self.collection.find_one({"_id": agent_id})
        if not doc:
            return None
        return Agent(**doc)

    async def update(self, agent: Agent) -> Agent:
        """Update existing agent."""
        agent.updated_at = datetime.utcnow()
        doc = agent.to_mongo_dict()
        await self.collection.update_one(
            {"_id": agent.agent_id},
            {"$set": doc}
        )
        logger.info(f"Updated agent {agent.agent_id}")
        return agent

    async def update_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update agent status."""
        await self.collection.update_one(
            {"_id": agent_id},
            {"$set": {"status": status.value, "updated_at": datetime.utcnow()}}
        )

    async def checkpoint(self, agent_id: str, context: dict[str, Any], task_queue_meta: dict[str, Any]) -> None:
        """Save agent checkpoint."""
        await self.collection.update_one(
            {"_id": agent_id},
            {
                "$set": {
                    "context": context,
                    "task_queue_meta": task_queue_meta,
                    "last_checkpoint": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }
            }
        )
        logger.debug(f"Checkpointed agent {agent_id}")

    async def get_by_user(self, user_id: str) -> list[Agent]:
        """Get all agents for a user."""
        cursor = self.collection.find({"user_id": user_id})
        agents = []
        async for doc in cursor:
            agents.append(Agent(**doc))
        return agents

    async def get_sub_agents(self, parent_agent_id: str) -> list[Agent]:
        """Get all sub-agents of a parent."""
        cursor = self.collection.find({"parent_agent_id": parent_agent_id})
        agents = []
        async for doc in cursor:
            agents.append(Agent(**doc))
        return agents

    async def delete(self, agent_id: str) -> None:
        """Delete agent."""
        await self.collection.delete_one({"_id": agent_id})
        logger.info(f"Deleted agent {agent_id}")


class TaskRepository:
    """Repository for Task CRUD operations."""

    def __init__(self):
        self.db = get_mongo_db()
        self.collection: AsyncIOMotorCollection = self.db["tasks"]

    async def create(self, task: Task) -> Task:
        """Insert new task."""
        doc = task.to_mongo_dict()
        await self.collection.insert_one(doc)
        logger.info(f"Created task {task.task_id} for agent {task.agent_id}")
        return task

    async def get_by_id(self, task_id: str) -> Task | None:
        """Fetch task by ID."""
        doc = await self.collection.find_one({"_id": task_id})
        if not doc:
            return None
        return Task(**doc)

    async def update(self, task: Task) -> Task:
        """Update task."""
        doc = task.to_mongo_dict()
        await self.collection.update_one(
            {"_id": task.task_id},
            {"$set": doc}
        )
        return task

    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: dict[str, Any] | None = None,
        error: str | None = None
    ) -> None:
        """Update task status and result."""
        update_doc: dict[str, Any] = {"status": status.value}
        
        if status == TaskStatus.RUNNING and not await self._has_started(task_id):
            update_doc["started_at"] = datetime.utcnow()
        
        if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            update_doc["completed_at"] = datetime.utcnow()
        
        if result is not None:
            update_doc["result"] = result
        
        if error is not None:
            update_doc["error"] = error
        
        await self.collection.update_one(
            {"_id": task_id},
            {"$set": update_doc}
        )

    async def _has_started(self, task_id: str) -> bool:
        """Check if task has started_at timestamp."""
        doc = await self.collection.find_one({"_id": task_id}, {"started_at": 1})
        return doc and doc.get("started_at") is not None

    async def increment_retry(self, task_id: str) -> None:
        """Increment retry count."""
        await self.collection.update_one(
            {"_id": task_id},
            {"$inc": {"retry_count": 1}}
        )

    async def get_pending_tasks(self, agent_id: str, limit: int = 10) -> list[Task]:
        """Get pending tasks for agent ordered by priority."""
        cursor = self.collection.find(
            {"agent_id": agent_id, "status": TaskStatus.PENDING.value}
        ).sort([("priority", -1), ("created_at", 1)]).limit(limit)
        
        tasks = []
        async for doc in cursor:
            tasks.append(Task(**doc))
        return tasks

    async def get_by_agent(self, agent_id: str) -> list[Task]:
        """Get all tasks for an agent."""
        cursor = self.collection.find({"agent_id": agent_id})
        tasks = []
        async for doc in cursor:
            tasks.append(Task(**doc))
        return tasks

    async def cancel_task(self, task_id: str) -> None:
        """Mark task for cancellation."""
        await self.collection.update_one(
            {"_id": task_id},
            {"$set": {"status": TaskStatus.CANCELLED_REQUESTED.value}}
        )

    async def delete(self, task_id: str) -> None:
        """Delete task."""
        await self.collection.delete_one({"_id": task_id})
