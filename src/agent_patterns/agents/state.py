"""Typed state and routing contracts for the supervisor graph."""

import operator
from typing import Annotated, Any, Literal, TypedDict

AgentName = Literal["log_parser", "incident_retriever", "root_cause", "fix_drafter"]
GraphRoute = Literal[
    "log_parser",
    "incident_retriever",
    "root_cause",
    "fix_drafter",
    "approval",
    "ticket",
    "finalize",
]
RunStatus = Literal["running", "pending_approval", "completed", "rejected", "failed"]


class AgentState(TypedDict, total=False):
    """Checkpointed state shared by the supervisor and specialist workers."""

    thread_id: str
    tenant_id: str
    task: str
    risk_level: Literal["low", "medium", "high"]
    require_approval: bool
    approval_decision: bool | None
    approval_feedback: str | None
    approval_reviewer_id: str | None
    planned_agents: list[AgentName]
    completed_agents: Annotated[list[AgentName], operator.add]
    partial_results: dict[str, str]
    structured_result: dict[str, Any] | None
    error_details: str | None
    total_tokens: int
    audit_log: Annotated[list[str], operator.add]
    iterations: int
    max_iterations: int
    max_steps: int
    next_route: GraphRoute
    status: RunStatus
    result: str | None
    create_ticket: bool
    max_tokens: int
    max_cost_usd: float
    estimated_cost_usd: float
    reserved_tokens: int
    parsed_log: dict[str, Any]
    similar_incidents: list[dict[str, Any]]
    hypotheses: list[dict[str, Any]]
    fix: dict[str, Any]
    ticket: dict[str, Any] | None
    trajectory: Annotated[list[dict[str, Any]], operator.add]
