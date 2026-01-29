"""Agent service with repository integration."""
import uuid
from datetime import datetime

from ..db.repositories import AgentRepository
from ..models.agents import AgentResponse, CreateAgentRequest
from ..runtime.agent import Agent, AgentConfig, AgentStatus, AgentType
from ..runtime.agent_runner import AgentRunner


class AgentService:
    def __init__(self):
        self.repo = AgentRepository()
        self.active_runners: dict[str, AgentRunner] = {}

    async def create_agent(self, payload: CreateAgentRequest, user_id: str = "default_user") -> AgentResponse:
        """Create new agent and optionally start its runtime."""
        agent_id = str(uuid.uuid4())
        
        # Validate parent if sub-agent
        if payload.agent_type == "SUB_AGENT" and payload.parent_agent_id:
            parent = await self.repo.get_by_id(payload.parent_agent_id)
            if not parent or not parent.can_spawn_sub_agent():
                raise ValueError("Invalid parent agent or parent cannot spawn sub-agents")
        
        # Create agent entity
        agent = Agent(
            agent_id=agent_id,
            user_id=user_id,
            agent_type=AgentType(payload.agent_type),
            parent_agent_id=payload.parent_agent_id,
            config=AgentConfig(**payload.config) if payload.config else AgentConfig(),
            tools_available=payload.tools_enabled or [],
            status=AgentStatus.IDLE,
        )
        
        # Persist to DB
        await self.repo.create(agent)
        
        return AgentResponse(
            agent_id=agent.agent_id,
            agent_type=agent.agent_type,
            status=agent.status,
            parent_agent_id=agent.parent_agent_id,
            user_id=agent.user_id,
            config=agent.config.model_dump(),
            tools_available=agent.tools_available,
        )

    async def get_agent(self, agent_id: str) -> AgentResponse:
        """Fetch agent by ID."""
        agent = await self.repo.get_by_id(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")
        
        return AgentResponse(
            agent_id=agent.agent_id,
            agent_type=agent.agent_type,
            status=agent.status,
            parent_agent_id=agent.parent_agent_id,
            user_id=agent.user_id,
            config=agent.config.model_dump(),
            tools_available=agent.tools_available,
        )

    async def start_agent_runtime(self, agent_id: str) -> None:
        """Start agent event loop in background."""
        if agent_id in self.active_runners:
            raise ValueError(f"Agent {agent_id} is already running")
        
        runner = AgentRunner(agent_id)
        self.active_runners[agent_id] = runner
        
        # Start in background (non-blocking)
        import asyncio
        asyncio.create_task(runner.run())

    async def stop_agent_runtime(self, agent_id: str) -> None:
        """Stop agent event loop."""
        runner = self.active_runners.get(agent_id)
        if runner:
            runner.stop()
            del self.active_runners[agent_id]

    async def terminate_agent(self, agent_id: str) -> None:
        """Terminate agent completely."""
        runner = self.active_runners.get(agent_id)
        if runner:
            await runner.terminate()
            del self.active_runners[agent_id]
        else:
            # Just update status if not running
            await self.repo.update_status(agent_id, AgentStatus.TERMINATED)

    async def checkpoint_agent(self, agent_id: str) -> None:
        """Force checkpoint for agent."""
        agent = await self.repo.get_by_id(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")
        
        await self.repo.checkpoint(agent_id, agent.context, agent.task_queue_meta)

    async def spawn_sub_agent(
        self,
        parent_agent_id: str,
        config: dict,
        tools_enabled: list[str] | None = None
    ) -> AgentResponse:
        """Spawn a sub-agent from a master agent."""
        parent = await self.repo.get_by_id(parent_agent_id)
        if not parent or not parent.can_spawn_sub_agent():
            raise ValueError("Parent must be a MASTER agent")
        
        payload = CreateAgentRequest(
            agent_type="SUB_AGENT",
            parent_agent_id=parent_agent_id,
            config=config,
            tools_enabled=tools_enabled,
        )
        
        return await self.create_agent(payload, user_id=parent.user_id)
