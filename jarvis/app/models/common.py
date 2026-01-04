"""Common response and pagination models."""
from typing import Any
from pydantic import BaseModel, Field


class ErrorInfo(BaseModel):
    code: str = Field(..., description="Machine readable error code")
    message: str = Field(..., description="Human friendly error message")


class ResponseEnvelope(BaseModel):
    request_id: str | None = Field(None, description="Request correlation id")
    data: Any | None = Field(None, description="Payload data")
    error: ErrorInfo | None = Field(None, description="Error details if any")


class PaginatedResponse(BaseModel):
    data: list[Any]
    next_cursor: str | None = None
