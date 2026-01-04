"""Message service stubs."""
import uuid

from ..models.messages import MessageResponse, SendMessageRequest


class MessageService:
    async def send_message(self, payload: SendMessageRequest) -> MessageResponse:
        message_id = str(uuid.uuid4())
        status = "APPROVAL_REQUESTED" if payload.requires_approval else "DELIVERED"
        return MessageResponse(message_id=message_id, status=status, requires_approval=payload.requires_approval)
