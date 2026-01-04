"""Health check router."""
from fastapi import APIRouter

from ...models.health import HealthStatus

router = APIRouter()


@router.get("/health", response_model=HealthStatus, tags=["health"])
async def health_check():
    return HealthStatus(status="ok", version="0.1.0")


@router.get("/version", response_model=dict, tags=["health"])
async def version():
    return {"version": "0.1.0"}
