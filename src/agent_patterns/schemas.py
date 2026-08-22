"""Transport models shared by API routes."""

from datetime import UTC, datetime
from typing import Any, Literal

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


class AgentRunRequest(StrictModel):
    task: str = Field(min_length=3, max_length=10_000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
    risk_level: Literal["low", "medium", "high"] = "low"
    require_approval: bool = False
    max_iterations: int = Field(default=8, ge=2, le=32)


class ApprovalRequest(StrictModel):
    approved: bool
    feedback: str | None = Field(default=None, max_length=2_000)


class AgentRunResponse(StrictModel):
    thread_id: str
    status: Literal["running", "pending_approval", "completed", "rejected", "failed"]
    task: str
    result: str | None = None
    completed_agents: list[Literal["research", "coding", "compliance"]] = Field(
        default_factory=list
    )
    audit_log: list[str] = Field(default_factory=list)
    approval: dict[str, Any] | None = None


class AgentEvent(StrictModel):
    type: Literal[
        "run_started", "token", "running", "pending_approval", "completed", "rejected", "failed"
    ]
    thread_id: str
    agent: str | None = None
    token: str | None = None
    run: AgentRunResponse | None = None
