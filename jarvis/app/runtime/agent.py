"""Agent entity with full state, memory, and lifecycle."""
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class AgentType(str, Enum):
    MASTER = "MASTER"
    SUB_AGENT = "SUB_AGENT"


class AgentStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    ERROR = "ERROR"
    TERMINATED = "TERMINATED"


class AgentMemoryRef(BaseModel):
    """Reference to memory storage locations."""
    short_term_cache_key: str | None = None
    long_term_collection: str = "user_interactions"
    episodic_collection: str = "events"


class AgentConfig(BaseModel):
    """Agent configuration settings."""
    llm_provider: str = "openai"
    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int = 2000
    loop_interval_seconds: int = 1
    checkpoint_interval_seconds: int = 30

    # MCP Configuration (optional)
    mcp_server_url: str | None = None  # If set, agent will use MCP for tools
    mcp_timeout_seconds: int = 30  # Timeout for MCP requests


class Agent(BaseModel):
    """Core Agent entity."""
    # Identity
    agent_id: str = Field(..., alias="_id")
    user_id: str
    agent_type: AgentType
    parent_agent_id: str | None = None
    
    # Configuration
    config: AgentConfig = Field(default_factory=AgentConfig)
    tools_available: list[str] = Field(default_factory=list)
    
    # State
    status: AgentStatus = AgentStatus.IDLE
    context: dict[str, Any] = Field(default_factory=dict, description="Current session context")
    
    # Memory
    memory_ref: AgentMemoryRef = Field(default_factory=AgentMemoryRef)
    short_term_memory: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Recent messages/interactions"
    )
    
    # Task queue metadata
    task_queue_meta: dict[str, Any] = Field(
        default_factory=lambda: {"pending_count": 0, "active_tasks": []},
        description="Task queue state summary"
    )
    
    # Lifecycle
    last_checkpoint: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}

    def can_spawn_sub_agent(self) -> bool:
        """Check if this agent can spawn sub-agents."""
        return self.agent_type == AgentType.MASTER

    def is_active(self) -> bool:
        """Check if agent is in active state."""
        return self.status in [AgentStatus.IDLE, AgentStatus.RUNNING, AgentStatus.WAITING_APPROVAL]

    def to_mongo_dict(self) -> dict[str, Any]:
        """Convert to MongoDB document."""
        data = self.model_dump(by_alias=True, exclude_none=True)
        return data
