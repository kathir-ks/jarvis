"""Base adapter interface."""
from abc import ABC, abstractmethod
from typing import Any


class BaseAdapter(ABC):
    """Standard interface for platform integrations."""

    @abstractmethod
    async def authenticate(self, credentials: dict) -> str:
        """Authenticate and return auth token."""
        pass

    @abstractmethod
    async def search(self, query: str) -> list[dict[str, Any]]:
        """Search platform with query."""
        pass

    @abstractmethod
    async def get_details(self, item_id: str) -> dict[str, Any]:
        """Get detailed item information."""
        pass

    @abstractmethod
    async def perform_action(self, action_type: str, params: dict) -> dict[str, Any]:
        """Perform platform action."""
        pass
