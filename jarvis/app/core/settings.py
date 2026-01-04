"""Application settings loaded from environment variables."""
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = Field("jarvis-mvp", description="Service name")
    environment: str = Field("local", description="Deployment environment")

    api_host: str = Field("0.0.0.0", description="API bind host")
    api_port: int = Field(8000, description="API bind port")

    mongo_dsn: str = Field("mongodb://mongodb:27017", description="Mongo connection string")
    mongo_db: str = Field("jarvis", description="Mongo database name")

    redis_url: str = Field("redis://redis:6379/0", description="Redis connection URL")

    qdrant_url: str = Field("http://qdrant:6333", description="Qdrant HTTP endpoint")

    max_concurrent_tasks_per_user: int = Field(25, description="Task concurrency guard per user")
    task_max_duration_seconds: int = Field(300, description="Default task timeout")
    task_max_retries: int = Field(3, description="Default task retries")

    jwt_secret: str = Field("dev-secret", description="JWT secret for stub auth")
    cors_origins: list[str] = Field(default_factory=lambda: ["*"], description="Allowed CORS origins")

    class Config:
        env_prefix = "JARVIS_"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
