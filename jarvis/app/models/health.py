"""Healthcheck response model."""
from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: str
    version: str
