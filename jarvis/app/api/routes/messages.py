"""Message API routes."""
from fastapi import APIRouter, Depends

from ...models.messages import MessageResponse, SendMessageRequest
from ...services.messages import MessageService

router = APIRouter()


def get_message_service() -> MessageService:
    return MessageService()


@router.post("", response_model=MessageResponse, status_code=201)
async def send_message(
    payload: SendMessageRequest,
    service: MessageService = Depends(get_message_service),
):
    return await service.send_message(payload)


@router.get("/history", response_model=dict)
async def get_message_history(agent_id: str | None = None, thread_id: str | None = None):
    # Placeholder for history fetch
    return {"data": [], "next_cursor": None}
