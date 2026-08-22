"""Transport models shared by API routes."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base API model that rejects accidental, undocumented fields."""

    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: Literal["healthy"] = "healthy"
    service: str
    version: str
    environment: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReadinessResponse(StrictModel):
    status: Literal["ready"] = "ready"
    checks: dict[str, Literal["up", "degraded"]]
