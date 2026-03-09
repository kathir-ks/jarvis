"""
Agent Capabilities Registry

Defines and manages agent capabilities for delegation and discovery.
Prepares for Phase 4 multi-agent collaboration.
"""
import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentCapability(BaseModel):
    """
    Definition of a capability that an agent possesses.

    Capabilities enable:
    - Discovery: Other agents can find capable agents
    - Delegation: Master agents can delegate to appropriate sub-agents
    - Specialization: Agents can advertise their expertise
    """

    capability_id: str = Field(
        description="Unique identifier for the capability"
    )
    name: str = Field(
        description="Human-readable capability name"
    )
    description: str = Field(
        description="Detailed description of what this capability enables"
    )
    required_tools: list[str] = Field(
        default_factory=list,
        description="Tools required to perform this capability"
    )
    complexity_level: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Complexity level (1=simple, 10=very complex)"
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for categorization (e.g., 'research', 'code', 'web')"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )


# Predefined standard capabilities
STANDARD_CAPABILITIES = {
    "web_research": AgentCapability(
        capability_id="web_research",
        name="Web Research",
        description="Search the web and read URLs to gather information",
        required_tools=["web_search", "read_url"],
        complexity_level=4,
        tags=["research", "web", "information_gathering"],
    ),
    "code_execution": AgentCapability(
        capability_id="code_execution",
        name="Code Execution",
        description="Write and execute Python code to solve problems",
        required_tools=["execute_code"],
        complexity_level=6,
        tags=["code", "programming", "computation"],
    ),
    "calculation": AgentCapability(
        capability_id="calculation",
        name="Mathematical Calculation",
        description="Perform mathematical calculations and evaluations",
        required_tools=["calculator"],
        complexity_level=2,
        tags=["math", "calculation"],
    ),
    "time_awareness": AgentCapability(
        capability_id="time_awareness",
        name="Time Awareness",
        description="Get current time and perform time-based calculations",
        required_tools=["get_time", "calculator"],
        complexity_level=2,
        tags=["time", "scheduling"],
    ),
    "general_assistance": AgentCapability(
        capability_id="general_assistance",
        name="General Assistance",
        description="General-purpose conversational assistance and reasoning",
        required_tools=[],
        complexity_level=3,
        tags=["conversation", "general"],
    ),
    "task_orchestration": AgentCapability(
        capability_id="task_orchestration",
        name="Task Orchestration",
        description="Coordinate multiple tasks and delegate to sub-agents",
        required_tools=[],
        complexity_level=9,
        tags=["orchestration", "master", "delegation"],
    ),
}


class AgentCapabilitiesRegistry:
    """
    Registry for managing agent capabilities.

    Provides:
    - Capability registration per agent
    - Discovery of capable agents
    - Capability matching for delegation
    - MongoDB persistence (write-through with in-memory cache)
    """

    def __init__(self, storage: dict[str, list[str]] | None = None):
        """
        Initialize capabilities registry.

        Args:
            storage: Optional in-memory storage (for testing).
                     If provided, MongoDB persistence is skipped.
        """
        # In-memory cache: agent_id -> list of capability_ids
        self._agent_capabilities: dict[str, list[str]] = storage or {}

        # Capability definitions
        self._capability_definitions: dict[str, AgentCapability] = {
            cap.capability_id: cap
            for cap in STANDARD_CAPABILITIES.values()
        }

        # Repository for persistence (lazy-initialized)
        self._repo: Any = None
        self._use_persistence = storage is None

    def _get_repo(self) -> Any:
        """Lazy-initialize the CapabilityRepository."""
        if self._repo is None and self._use_persistence:
            try:
                from ..db.repositories import CapabilityRepository
                self._repo = CapabilityRepository()
            except Exception as e:
                logger.warning(f"Could not initialize CapabilityRepository: {e}")
                self._use_persistence = False
        return self._repo

    async def load_from_db(self) -> None:
        """
        Load all capabilities from MongoDB into the in-memory cache.

        Call this during application startup to restore persisted state.
        """
        repo = self._get_repo()
        if not repo:
            return

        try:
            all_capabilities = await repo.load_all()
            self._agent_capabilities.update(all_capabilities)
            logger.info(
                f"Loaded capabilities for {len(all_capabilities)} agents from database"
            )
        except Exception as e:
            logger.warning(f"Failed to load capabilities from database: {e}")

    async def _persist(self, agent_id: str) -> None:
        """Write-through: persist agent capabilities to MongoDB."""
        repo = self._get_repo()
        if not repo:
            return

        try:
            capabilities = self._agent_capabilities.get(agent_id, [])
            await repo.save_capabilities(agent_id, capabilities)
        except Exception as e:
            logger.warning(f"Failed to persist capabilities for {agent_id}: {e}")

    def register_capability(
        self,
        agent_id: str,
        capability: AgentCapability | str,
    ) -> None:
        """
        Register a capability for an agent (synchronous, in-memory only).

        For persistence, use ``register_capability_async`` instead, or
        call ``_persist`` after this method in an async context.

        Args:
            agent_id: The agent ID
            capability: Capability object or capability_id string
        """
        if isinstance(capability, str):
            capability_id = capability
            # If it's a standard capability, register it
            if capability_id not in self._capability_definitions:
                logger.warning(
                    f"Capability {capability_id} not found in registry. "
                    "Consider defining it first."
                )
        else:
            capability_id = capability.capability_id
            # Store capability definition
            self._capability_definitions[capability_id] = capability

        # Add to agent's capabilities
        if agent_id not in self._agent_capabilities:
            self._agent_capabilities[agent_id] = []

        if capability_id not in self._agent_capabilities[agent_id]:
            self._agent_capabilities[agent_id].append(capability_id)
            logger.info(
                f"Registered capability '{capability_id}' for agent {agent_id}"
            )

    async def register_capability_async(
        self,
        agent_id: str,
        capability: AgentCapability | str,
    ) -> None:
        """
        Register a capability and persist to MongoDB.

        Args:
            agent_id: The agent ID
            capability: Capability object or capability_id string
        """
        self.register_capability(agent_id, capability)
        await self._persist(agent_id)

    def register_multiple(
        self,
        agent_id: str,
        capabilities: list[AgentCapability | str],
    ) -> None:
        """
        Register multiple capabilities at once.

        Args:
            agent_id: The agent ID
            capabilities: List of capabilities
        """
        for cap in capabilities:
            self.register_capability(agent_id, cap)

    def unregister_capability(
        self,
        agent_id: str,
        capability_id: str,
    ) -> bool:
        """
        Unregister a capability from an agent (synchronous, in-memory only).

        Args:
            agent_id: The agent ID
            capability_id: The capability ID

        Returns:
            True if removed, False if not found
        """
        if agent_id in self._agent_capabilities:
            if capability_id in self._agent_capabilities[agent_id]:
                self._agent_capabilities[agent_id].remove(capability_id)
                logger.info(
                    f"Unregistered capability '{capability_id}' from agent {agent_id}"
                )
                return True
        return False

    async def unregister_capability_async(
        self,
        agent_id: str,
        capability_id: str,
    ) -> bool:
        """
        Unregister a capability and persist the change.

        Args:
            agent_id: The agent ID
            capability_id: The capability ID

        Returns:
            True if removed, False if not found
        """
        removed = self.unregister_capability(agent_id, capability_id)
        if removed:
            await self._persist(agent_id)
        return removed

    def get_agent_capabilities(self, agent_id: str) -> list[AgentCapability]:
        """
        Get all capabilities for an agent.

        Args:
            agent_id: The agent ID

        Returns:
            List of capability objects
        """
        capability_ids = self._agent_capabilities.get(agent_id, [])
        return [
            self._capability_definitions[cap_id]
            for cap_id in capability_ids
            if cap_id in self._capability_definitions
        ]

    def has_capability(self, agent_id: str, capability_id: str) -> bool:
        """
        Check if an agent has a specific capability.

        Args:
            agent_id: The agent ID
            capability_id: The capability ID

        Returns:
            True if agent has the capability
        """
        return capability_id in self._agent_capabilities.get(agent_id, [])

    def find_capable_agents(
        self,
        required_capability: str,
    ) -> list[str]:
        """
        Find all agents with a specific capability.

        Args:
            required_capability: The capability ID to search for

        Returns:
            List of agent IDs
        """
        capable_agents = []
        for agent_id, capabilities in self._agent_capabilities.items():
            if required_capability in capabilities:
                capable_agents.append(agent_id)

        logger.debug(
            f"Found {len(capable_agents)} agents with capability '{required_capability}'"
        )
        return capable_agents

    def find_agents_by_tags(
        self,
        tags: list[str],
        require_all: bool = False,
    ) -> list[str]:
        """
        Find agents by capability tags.

        Args:
            tags: Tags to search for
            require_all: If True, agent must have ALL tags; if False, ANY tag

        Returns:
            List of agent IDs
        """
        matching_agents = set()

        for agent_id, capability_ids in self._agent_capabilities.items():
            agent_tags = set()
            for cap_id in capability_ids:
                if cap_id in self._capability_definitions:
                    agent_tags.update(self._capability_definitions[cap_id].tags)

            if require_all:
                if all(tag in agent_tags for tag in tags):
                    matching_agents.add(agent_id)
            else:
                if any(tag in agent_tags for tag in tags):
                    matching_agents.add(agent_id)

        logger.debug(
            f"Found {len(matching_agents)} agents with tags {tags} "
            f"(require_all={require_all})"
        )
        return list(matching_agents)

    def get_capability_definition(
        self,
        capability_id: str,
    ) -> AgentCapability | None:
        """
        Get capability definition.

        Args:
            capability_id: The capability ID

        Returns:
            Capability object or None
        """
        return self._capability_definitions.get(capability_id)

    def auto_register_from_tools(
        self,
        agent_id: str,
        available_tools: list[str],
    ) -> list[str]:
        """
        Automatically register capabilities based on available tools (sync).

        Args:
            agent_id: The agent ID
            available_tools: List of tool names the agent has access to

        Returns:
            List of registered capability IDs
        """
        registered = []
        tools_set = set(available_tools)

        for cap_id, capability in STANDARD_CAPABILITIES.items():
            required_tools = set(capability.required_tools)

            # If agent has all required tools, register the capability
            if required_tools.issubset(tools_set):
                self.register_capability(agent_id, cap_id)
                registered.append(cap_id)

        logger.info(
            f"Auto-registered {len(registered)} capabilities for agent {agent_id}: "
            f"{registered}"
        )
        return registered

    async def auto_register_from_tools_async(
        self,
        agent_id: str,
        available_tools: list[str],
    ) -> list[str]:
        """
        Automatically register capabilities and persist to MongoDB.

        Args:
            agent_id: The agent ID
            available_tools: List of tool names the agent has access to

        Returns:
            List of registered capability IDs
        """
        registered = self.auto_register_from_tools(agent_id, available_tools)
        if registered:
            await self._persist(agent_id)
        return registered


# Global singleton
_capabilities_registry_instance: AgentCapabilitiesRegistry | None = None


def get_capabilities_registry() -> AgentCapabilitiesRegistry:
    """Get global capabilities registry (singleton)."""
    global _capabilities_registry_instance
    if _capabilities_registry_instance is None:
        _capabilities_registry_instance = AgentCapabilitiesRegistry()
    return _capabilities_registry_instance
