"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime settings.

    Environment variables use the ``AGENT_PATTERNS_`` prefix. For example,
    ``AGENT_PATTERNS_ENVIRONMENT=production`` changes the deployment mode.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AGENT_PATTERNS_",
        extra="ignore",
        frozen=True,
    )

    service_name: str = "fastapi-genai-agent-patterns"
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_prefix: str = "/api/v1"
    checkpoint_database_url: str | None = None
    reviewer_api_key: SecretStr | None = None
    reviewer_id: str = Field(default="local-reviewer", min_length=1, max_length=128)
    tenant_id: str = Field(default="tenant-alpha", min_length=1, max_length=128)
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = Field(default=3600, ge=1)
    cache_vector_dimensions: int = Field(default=128, ge=8, le=4096)
    cache_semantic_distance_threshold: float = Field(default=0.12, ge=0.0, le=2.0)
    cache_required: bool = True
    dependency_timeout_seconds: float = Field(default=0.5, gt=0.0, le=30.0)
    otlp_endpoint: str | None = None
    provider_mode: Literal["deterministic", "openai"] = "deterministic"
    provider_api_key: str | None = None
    provider_base_url: str = "https://api.openai.com/v1"
    provider_model: str = "gpt-4o-mini"
    provider_timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    provider_max_retries: int = Field(default=2, ge=0, le=5)

    @model_validator(mode="after")
    def require_deployment_security(self) -> "Settings":
        if self.environment in {"staging", "production"}:
            if not self.checkpoint_database_url:
                raise ValueError("checkpoint_database_url is required outside local/test")
            if not self.reviewer_api_key or not self.reviewer_api_key.get_secret_value():
                raise ValueError("reviewer_api_key is required outside local/test")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings object per process."""

    return Settings()
