"""Pydantic request/response models for the Communication Platform API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class RegisterAgentRequest(BaseModel):
    agent_id: str
    user_id: str = ""
    agent_type: str = "sub_agent"
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UnregisterAgentRequest(BaseModel):
    agent_id: str


class SendMessageRequest(BaseModel):
    from_id: str
    to_id: str
    message_type: str = "peer_message"
    content: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = 300


class BroadcastRequest(BaseModel):
    from_id: str
    content: dict[str, Any] = Field(default_factory=dict)
    topic: str = ""


class HeartbeatRequest(BaseModel):
    agent_id: str
    status: str = "alive"
    active_tasks: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class AgentInfo(BaseModel):
    agent_id: str
    user_id: str = ""
    agent_type: str = "sub_agent"
    capabilities: list[str] = Field(default_factory=list)
    health: str = "healthy"
    active_tasks: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class RegisterAgentResponse(BaseModel):
    ok: bool = True
    agent_id: str
    message: str = "registered"


class UnregisterAgentResponse(BaseModel):
    ok: bool = True
    agent_id: str
    message: str = "unregistered"


class SendMessageResponse(BaseModel):
    ok: bool = True
    message_id: str


class BroadcastResponse(BaseModel):
    ok: bool = True
    message_id: str


class HeartbeatResponse(BaseModel):
    ok: bool = True
    acknowledged: bool = True


class DirectoryResponse(BaseModel):
    agents: list[AgentInfo]
    total: int


class HealthResponse(BaseModel):
    status: str = "ok"
    total_agents: int = 0
    healthy: int = 0
    busy: int = 0
    degraded: int = 0
