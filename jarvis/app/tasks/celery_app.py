"""Celery app configuration."""
from celery import Celery

from ..core.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "jarvis",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=settings.task_max_duration_seconds,
    task_time_limit=settings.task_max_duration_seconds + 30,
    task_default_retry_delay=60,
    task_max_retries=settings.task_max_retries,
)
