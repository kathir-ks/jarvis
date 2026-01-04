"""Utility helpers."""
import uuid


def generate_correlation_id() -> str:
    """Generate unique correlation ID."""
    return str(uuid.uuid4())
