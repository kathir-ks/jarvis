"""Agent API models."""
from pydantic import BaseModel, Field


class CreateAgentRequest(BaseModel):
    agent_type: str = Field(..., description="MASTER or SUB_AGENT")
    parent_agent_id: str | None = Field(None, description="Parent agent id for sub-agents")
    config: dict = Field(default_factory=dict)
    tools_enabled: list[str] | None = Field(None, description="Tool names to enable")


class AgentResponse(BaseModel):
    agent_id: str
    agent_type: str
    status: str
    parent_agent_id: str | None = None
    user_id: str | None = None
    config: dict = Field(default_factory=dict)
    tools_available: list[str] = Field(default_factory=list)
