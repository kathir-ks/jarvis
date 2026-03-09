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

    default_llm_provider: str = Field("openai", description="Default LLM provider")
    default_llm_model: str = Field("gpt-4o-mini", description="Default LLM model name")
    openai_api_key: str | None = Field(None, description="OpenAI API key for LLM calls")
    gemini_api_key: str | None = Field(None, description="Google Gemini API key for LLM calls")
    gemini_api_keys: str | None = Field(
        None,
        description="Comma-separated Gemini API keys for multi-account rotation",
    )
    default_gemini_model: str = Field("gemini-2.0-flash-exp", description="Default Gemini model name")
    gemini_requests_per_key_per_model: int = Field(
        20, description="Max requests per Gemini key per model per day",
    )
    gemini_max_models_per_key: int = Field(
        3, description="Max distinct models a single Gemini key may use per day",
    )

    anthropic_api_key: str | None = Field(None, description="Anthropic API key for Claude models")
    default_anthropic_model: str = Field("claude-sonnet-4-20250514", description="Default Anthropic model name")

    openrouter_api_key: str | None = Field(None, description="OpenRouter API key (free tier available)")
    default_openrouter_model: str = Field(
        "meta-llama/llama-3.1-8b-instruct:free",
        description="Default OpenRouter model (use :free suffix for free models)",
    )

    api_keys: str = Field("", description="Comma-separated API keys for authentication (empty = no auth)")

    max_concurrent_tasks_per_user: int = Field(25, description="Task concurrency guard per user")
    task_max_duration_seconds: int = Field(300, description="Default task timeout")
    task_max_retries: int = Field(3, description="Default task retries")

    jwt_secret: str = Field("dev-secret", description="JWT secret for stub auth")
    cors_origins: list[str] = Field(default_factory=lambda: ["*"], description="Allowed CORS origins")

    class Config:
        env_prefix = "JARVIS_"
        case_sensitive = False
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
