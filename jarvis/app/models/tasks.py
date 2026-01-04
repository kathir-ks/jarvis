"""Task API models."""
from pydantic import BaseModel, Field


class SubmitTaskRequest(BaseModel):
    task_type: str = Field(..., description="Task category")
    task_description: str = Field(..., description="Natural language description")
    task_params: dict = Field(default_factory=dict)
    priority: int = Field(5, ge=1, le=10)
    llm_config: dict | None = None
    tools: list[str] | None = None
    max_duration: int | None = None
    max_retries: int | None = None
    on_complete: str | None = None
    on_failure: str | None = None
    on_progress: str | None = None


class TaskResponse(BaseModel):
    task_id: str
    status: str
    priority: int
    result: dict | None = None
    error: str | None = None
