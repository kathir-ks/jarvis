"""Communication Platform REST API — FastAPI router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .models import (
    AgentInfo,
    BroadcastRequest,
    BroadcastResponse,
    DirectoryResponse,
    HealthResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    RegisterAgentRequest,
    RegisterAgentResponse,
    SendMessageRequest,
    SendMessageResponse,
    UnregisterAgentRequest,
    UnregisterAgentResponse,
)
from .service import CommunicationPlatformService

router = APIRouter(prefix="/api/v1")

# The service instance is set at app startup via ``set_service()``.
_service: CommunicationPlatformService | None = None


def set_service(svc: CommunicationPlatformService) -> None:
    """Wire the platform service into the router (called by app factory)."""
    global _service
    _service = svc


def _svc() -> CommunicationPlatformService:
    if _service is None:
        raise HTTPException(503, "Platform service not initialised")
    return _service


# ------------------------------------------------------------------
# Agent registration
# ------------------------------------------------------------------

@router.post("/agents/register", response_model=RegisterAgentResponse)
async def register_agent(req: RegisterAgentRequest):
    await _svc().register_agent(
        agent_id=req.agent_id,
        user_id=req.user_id,
        agent_type=req.agent_type,
        capabilities=req.capabilities,
        metadata=req.metadata,
    )
    return RegisterAgentResponse(agent_id=req.agent_id)


@router.post("/agents/unregister", response_model=UnregisterAgentResponse)
async def unregister_agent(req: UnregisterAgentRequest):
    removed = await _svc().unregister_agent(req.agent_id)
    if not removed:
        raise HTTPException(404, f"Agent {req.agent_id} not found")
    return UnregisterAgentResponse(agent_id=req.agent_id)


# ------------------------------------------------------------------
# Messaging
# ------------------------------------------------------------------

@router.post("/messages/send", response_model=SendMessageResponse)
async def send_message(req: SendMessageRequest):
    msg_id = await _svc().send_message(
        from_id=req.from_id,
        to_id=req.to_id,
        message_type=req.message_type,
        content=req.content,
        ttl_seconds=req.ttl_seconds,
    )
    return SendMessageResponse(message_id=msg_id)


@router.post("/messages/broadcast", response_model=BroadcastResponse)
async def broadcast(req: BroadcastRequest):
    msg_id = await _svc().broadcast(
        from_id=req.from_id,
        content=req.content,
        topic=req.topic,
    )
    return BroadcastResponse(message_id=msg_id)


# ------------------------------------------------------------------
# Heartbeat
# ------------------------------------------------------------------

@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(req: HeartbeatRequest):
    ack = await _svc().heartbeat(
        agent_id=req.agent_id,
        status=req.status,
        active_tasks=req.active_tasks,
        metadata=req.metadata,
    )
    return HeartbeatResponse(acknowledged=ack)


# ------------------------------------------------------------------
# Directory
# ------------------------------------------------------------------

@router.get("/directory/agents", response_model=DirectoryResponse)
async def list_agents(
    user_id: str | None = Query(None),
    capability: str | None = Query(None),
):
    entries = _svc().list_agents(user_id=user_id, capability=capability)
    agents = [
        AgentInfo(
            agent_id=e.agent_id,
            user_id=e.user_id,
            agent_type=e.agent_type,
            capabilities=e.capabilities,
            health=e.health.value,
            active_tasks=e.active_tasks,
            metadata=e.metadata,
        )
        for e in entries
    ]
    return DirectoryResponse(agents=agents, total=len(agents))


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
async def health():
    h = _svc().get_health()
    return HealthResponse(
        status=h.get("status", "ok"),
        total_agents=h.get("total_agents", 0),
        healthy=h.get("healthy", 0),
        busy=h.get("busy", 0),
        degraded=h.get("degraded", 0),
    )
