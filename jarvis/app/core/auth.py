"""Simple API key authentication middleware."""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .settings import get_settings

logger = logging.getLogger(__name__)

# Paths that never require authentication
_PUBLIC_PATHS = frozenset({
    "/health",
    "/version",
    "/openapi.json",
    "/docs",
    "/redoc",
})


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests that lack a valid ``X-API-Key`` header.

    When ``JARVIS_API_KEYS`` is empty the middleware is effectively a
    no-op (all requests pass through).  This keeps the development
    experience frictionless while allowing production deployments to
    lock down access.
    """

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        valid_keys = {
            k.strip() for k in settings.api_keys.split(",") if k.strip()
        }

        # If no keys are configured, authentication is disabled
        if not valid_keys:
            return await call_next(request)

        # Public paths are always accessible
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key", "")
        if api_key not in valid_keys:
            logger.warning(
                "Rejected request to %s — invalid or missing API key", request.url.path,
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)
