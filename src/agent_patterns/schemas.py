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
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
    risk_level: Literal["low", "medium", "high"] = "low"
    require_approval: bool = False
    max_iterations: int = Field(default=8, ge=2, le=32)


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


class ActionProposal(StrictModel):
    summary: str = Field(description="Summary of proposed technical changes or response")
    action_type: Literal["read_only", "ticket_update", "system_change", "escalate"] = Field(
        default="read_only", description="Categorization of the action"
    )
    target_resource: str | None = Field(
        default=None,
        description="Resource identifier for mutations (e.g. ticket ID, service name)",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Validated parameters for the proposed action"
    )
    is_mutation: bool = Field(
        default=False, description="Whether the action mutates persistent state"
    )


class ComplianceReview(StrictModel):
    policy_satisfied: bool = Field(
        default=True, description="Whether the request satisfies policy constraints"
    )
    risk_assessment: Literal["low", "medium", "high"] = Field(
        default="low", description="Assessed risk level"
    )
    requires_human_approval: bool = Field(
        default=False, description="Whether human approval is mandated before execution"
    )
    audit_notes: list[str] = Field(
        default_factory=list, description="Security and audit observations"
    )


class StructuredAgentResult(StrictModel):
    research: ResearchFinding | None = None
    action: ActionProposal | None = None
    compliance: ComplianceReview | None = None
    final_synthesis: str = Field(
        description="Consolidated final synthesis across completed specialists"
    )
    tokens_used: int = Field(
        default=0, ge=0, description="Total provider tokens consumed across workers"
    )


class AgentRunResponse(StrictModel):
    thread_id: str
    status: Literal["running", "pending_approval", "completed", "rejected", "failed"]
    task: str
    result: str | None = None
    structured_result: StructuredAgentResult | None = None
    error_details: str | None = None
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
