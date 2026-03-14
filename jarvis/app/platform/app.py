"""Communication Platform — FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI

from ..lite.memory_broker import InMemoryMessageBroker
from ..runtime.agent_directory import AgentDirectory
from .api import router, set_service
from .service import CommunicationPlatformService


def create_platform_app(
    broker: InMemoryMessageBroker | None = None,
    directory: AgentDirectory | None = None,
) -> FastAPI:
    """Create and configure the Communication Platform FastAPI app.

    If *broker* or *directory* are not provided, fresh in-memory instances
    are created.  This makes the platform fully self-contained — no Redis,
    MongoDB, or Qdrant required.
    """
    broker = broker or InMemoryMessageBroker()
    directory = directory or AgentDirectory()

    service = CommunicationPlatformService(broker=broker, directory=directory)

    app = FastAPI(
        title="Jarvis Communication Platform",
        description="Multi-agent messaging and discovery service",
        version="0.1.0",
    )
    app.include_router(router)

    # Store references so entry-point scripts can access them
    app.state.broker = broker  # type: ignore[attr-defined]
    app.state.directory = directory  # type: ignore[attr-defined]
    app.state.service = service  # type: ignore[attr-defined]

    set_service(service)

    return app
