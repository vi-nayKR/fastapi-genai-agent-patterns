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
    status: Literal["ready", "degraded"] = "ready"
    checks: dict[str, Literal["up", "degraded"]]


class AgentRunRequest(StrictModel):
    task: str = Field(min_length=3, max_length=10_000)
    risk_level: Literal["low", "medium", "high"] = "low"
    require_approval: bool = False
    max_iterations: int = Field(default=8, ge=2, le=32)
    max_steps: int = Field(default=6, ge=1, le=32)
    create_ticket: bool = False
    max_tokens: int = Field(default=16000, ge=1, le=100000)
    max_cost_usd: float = Field(default=0.20, gt=0, le=10)


class ApprovalRequest(StrictModel):
    approved: bool
    feedback: str | None = Field(default=None, max_length=2_000)


class ResearchFinding(StrictModel):
    summary: str = Field(description="Executive summary of findings or authoritative context")
    citations: list[str] = Field(
        default_factory=list,
        description="Authoritative reference IDs or policy document sections",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        default="high", description="Assessed confidence based on available evidence"
    )
    abstain: bool = Field(
        default=False,
        description="True if query cannot be answered from authoritative sources",
    )


class StructuredAgentResult(StrictModel):
    final_synthesis: str = Field(
        description="Consolidated final synthesis across completed specialists"
    )
    tokens_used: int = Field(
        default=0, ge=0, description="Total provider tokens consumed across workers"
    )
    parsed_log: dict[str, Any] = Field(default_factory=dict)
    similar_incidents: list[dict[str, Any]] = Field(default_factory=list)
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    suggested_fix: str = ""
    ticket: dict[str, Any] | None = None
    estimated_cost_usd: float = 0


class AgentRunResponse(StrictModel):
    thread_id: str
    tenant_id: str = "tenant-alpha"
    status: Literal["running", "pending_approval", "completed", "rejected", "failed"]
    task: str
    result: str | None = None
    structured_result: StructuredAgentResult | None = None
    error_details: str | None = None
    completed_agents: list[
        Literal["log_parser", "incident_retriever", "root_cause", "fix_drafter"]
    ] = Field(default_factory=list)
    audit_log: list[str] = Field(default_factory=list)
    approval: dict[str, Any] | None = None
    trajectory: list[dict[str, Any]] = Field(default_factory=list)
    steps: int = 0
    tokens_used: int = 0
    estimated_cost_usd: float = 0


class Hypothesis(StrictModel):
    label: str
    explanation: str
    incident_ids: list[str]


class RootCauseReport(StrictModel):
    hypotheses: list[Hypothesis] = Field(max_length=3)
    abstain: bool = False


class FixDraft(StrictModel):
    summary: str = Field(min_length=1, max_length=1000)
    verification: str
    risks: str


class FixQuality(StrictModel):
    score: int = Field(ge=1, le=5)
    rationale: str


class AgentEvent(StrictModel):
    type: Literal[
        "run_started", "token", "running", "pending_approval", "completed", "rejected", "failed"
    ]
    thread_id: str
    agent: str | None = None
    token: str | None = None
    run: AgentRunResponse | None = None


class CacheLookupRequest(StrictModel):
    namespace: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=20_000)


class CachePutRequest(CacheLookupRequest):
    response: Any


class CacheLookupResponse(StrictModel):
    hit: bool
    source: Literal["exact", "semantic"] | None = None
    distance: float | None = None
    matched_prompt: str | None = None
    response: Any = None


class CacheEvictionResponse(StrictModel):
    deleted: int = Field(ge=0)


class CacheStatsResponse(StrictModel):
    exact_hits: int = 0
    semantic_hits: int = 0
    misses: int = 0
    writes: int = 0
    exact_evictions: int = 0
    namespace_evictions: int = 0
