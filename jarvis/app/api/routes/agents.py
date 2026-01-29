"""Agent API routes."""
from fastapi import APIRouter, Depends, HTTPException

from ...models.agents import AgentResponse, CreateAgentRequest
from ...services.agents import AgentService

router = APIRouter()


def get_agent_service() -> AgentService:
    return AgentService()


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    payload: CreateAgentRequest,
    service: AgentService = Depends(get_agent_service),
):
    """Create a new agent (master or sub-agent)."""
    try:
        return await service.create_agent(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, service: AgentService = Depends(get_agent_service)):
    """Get agent state and configuration."""
    try:
        return await service.get_agent(agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{agent_id}/start", status_code=204)
async def start_agent(agent_id: str, service: AgentService = Depends(get_agent_service)):
    """Start agent event loop."""
    try:
        await service.start_agent_runtime(agent_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{agent_id}/stop", status_code=204)
async def stop_agent(agent_id: str, service: AgentService = Depends(get_agent_service)):
    """Stop agent event loop."""
    await service.stop_agent_runtime(agent_id)


@router.post("/{agent_id}/checkpoint", status_code=204)
async def checkpoint_agent(agent_id: str, service: AgentService = Depends(get_agent_service)):
    """Force checkpoint agent state."""
    try:
        await service.checkpoint_agent(agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{agent_id}/terminate", status_code=204)
async def terminate_agent(agent_id: str, service: AgentService = Depends(get_agent_service)):
    """Terminate agent permanently."""
    await service.terminate_agent(agent_id)


@router.post("/{agent_id}/spawn", response_model=AgentResponse, status_code=201)
async def spawn_sub_agent(
    agent_id: str,
    config: dict,
    tools_enabled: list[str] | None = None,
    service: AgentService = Depends(get_agent_service),
):
    """Spawn a sub-agent from a master agent."""
    try:
        return await service.spawn_sub_agent(agent_id, config, tools_enabled)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
