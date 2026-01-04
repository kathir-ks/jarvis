"""Message API models."""
from pydantic import BaseModel, Field


class SendMessageRequest(BaseModel):
    from_agent_id: str = Field(...)
    to_agent_id: str = Field(...)
    message_type: str = Field(...)
    message_body: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    requires_approval: bool = False


class MessageResponse(BaseModel):
    message_id: str
    status: str
    requires_approval: bool
