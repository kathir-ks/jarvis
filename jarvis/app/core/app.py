"""FastAPI application factory."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import ApiKeyMiddleware
from .logging import configure_logging
from .settings import get_settings
from ..api.routes import agents, health, messages, tasks, mcp
from ..llm.tools.init_tools import initialize_tools


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    # Initialize built-in tools at startup
    initialize_tools()

    app = FastAPI(title=settings.app_name, version="0.1.0")

    # API key authentication (no-op when JARVIS_API_KEYS is empty)
    app.add_middleware(ApiKeyMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(agents.router, prefix="/agents", tags=["agents"])
    app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
    app.include_router(messages.router, prefix="/messages", tags=["messages"])
    app.include_router(mcp.router)  # MCP has its own prefix

    return app
