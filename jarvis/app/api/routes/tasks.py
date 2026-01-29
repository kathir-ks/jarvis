"""Task API routes."""
from fastapi import APIRouter, Depends, HTTPException

from ...models.tasks import SubmitTaskRequest, TaskResponse
from ...services.tasks import TaskService

router = APIRouter()


def get_task_service() -> TaskService:
    return TaskService()


@router.post("", response_model=TaskResponse, status_code=201)
async def submit_task_for_agent(
    agent_id: str,
    payload: SubmitTaskRequest,
    service: TaskService = Depends(get_task_service),
):
    """Submit a new task for an agent (use query param ?agent_id=...)."""
    try:
        return await service.submit_task(agent_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, service: TaskService = Depends(get_task_service)):
    """Get task status and result."""
    try:
        return await service.get_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: str, service: TaskService = Depends(get_task_service)):
    """Request task cancellation."""
    try:
        return await service.cancel_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
