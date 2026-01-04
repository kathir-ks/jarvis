"""Task entity with execution state."""
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class TaskType(str, Enum):
    RESEARCH = "RESEARCH"
    EXPLORATION = "EXPLORATION"
    PURCHASE = "PURCHASE"
    BOOKING = "BOOKING"
    CUSTOM = "CUSTOM"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    CANCELLED_REQUESTED = "CANCELLED_REQUESTED"


class Task(BaseModel):
    """Core Task entity."""
    # Identity
    task_id: str = Field(..., alias="_id")
    agent_id: str
    parent_task_id: str | None = None
    
    # Definition
    task_type: TaskType
    task_description: str
    task_params: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(5, ge=1, le=10)
    
    # Execution config
    llm_config: dict[str, Any] | None = None
    tools: list[str] = Field(default_factory=list)
    max_duration: int = 300
    max_retries: int = 3
    retry_count: int = 0
    
    # Callbacks
    on_complete: str | None = None
    on_failure: str | None = None
    on_progress: str | None = None
    
    # State
    status: TaskStatus = TaskStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None
    progress: float = 0.0
    
    # Dependencies (for DAG execution)
    depends_on: list[str] = Field(default_factory=list, description="Task IDs this depends on")
    
    # Lifecycle
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    class Config:
        use_enum_values = True
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}

    def can_execute(self) -> bool:
        """Check if task is ready to execute."""
        return self.status == TaskStatus.PENDING and self.retry_count <= self.max_retries

    def should_cancel(self) -> bool:
        """Check if cancellation requested."""
        return self.status == TaskStatus.CANCELLED_REQUESTED

    def to_mongo_dict(self) -> dict[str, Any]:
        """Convert to MongoDB document."""
        return self.model_dump(by_alias=True, exclude_none=True)
