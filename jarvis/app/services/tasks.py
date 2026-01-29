"""Task service with repository integration."""
import uuid
from datetime import datetime

from ..core.settings import get_settings
from ..db.repositories import TaskRepository
from ..models.tasks import SubmitTaskRequest, TaskResponse
from ..runtime.task import Task, TaskStatus, TaskType


class TaskService:
    def __init__(self):
        self.repo = TaskRepository()
        self.settings = get_settings()

    async def submit_task(self, agent_id: str, payload: SubmitTaskRequest) -> TaskResponse:
        """Submit new task for agent."""
        task_id = str(uuid.uuid4())
        
        # Apply defaults from settings
        max_duration = payload.max_duration or self.settings.task_max_duration_seconds
        max_retries = payload.max_retries or self.settings.task_max_retries
        
        # Create task entity
        task = Task(
            task_id=task_id,
            agent_id=agent_id,
            task_type=TaskType(payload.task_type),
            task_description=payload.task_description,
            task_params=payload.task_params,
            priority=payload.priority,
            llm_config=payload.llm_config,
            tools=payload.tools or [],
            max_duration=max_duration,
            max_retries=max_retries,
            on_complete=payload.on_complete,
            on_failure=payload.on_failure,
            on_progress=payload.on_progress,
            status=TaskStatus.PENDING,
        )
        
        # Persist to DB
        await self.repo.create(task)
        
        return TaskResponse(
            task_id=task.task_id,
            status=task.status,
            priority=task.priority,
        )

    async def get_task(self, task_id: str) -> TaskResponse:
        """Fetch task status and result."""
        task = await self.repo.get_by_id(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        return TaskResponse(
            task_id=task.task_id,
            status=task.status,
            priority=task.priority,
            result=task.result,
            error=task.error,
        )

    async def cancel_task(self, task_id: str) -> TaskResponse:
        """Request task cancellation."""
        await self.repo.cancel_task(task_id)
        
        task = await self.repo.get_by_id(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        return TaskResponse(
            task_id=task.task_id,
            status=task.status,
            priority=task.priority,
        )
