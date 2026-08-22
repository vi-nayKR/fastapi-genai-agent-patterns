"""Typed state and routing contracts for the supervisor graph."""

import operator
from typing import Annotated, Literal, TypedDict

AgentName = Literal["research", "coding", "compliance"]
GraphRoute = Literal["research", "coding", "compliance", "approval", "finalize"]
RunStatus = Literal["running", "pending_approval", "completed", "rejected", "failed"]


class AgentState(TypedDict, total=False):
    """Checkpointed state shared by the supervisor and specialist workers."""

    thread_id: str
    task: str
    risk_level: Literal["low", "medium", "high"]
    require_approval: bool
    approval_decision: bool | None
    approval_feedback: str | None
    planned_agents: list[AgentName]
    completed_agents: Annotated[list[AgentName], operator.add]
    partial_results: dict[str, str]
    audit_log: Annotated[list[str], operator.add]
    iterations: int
    max_iterations: int
    next_route: GraphRoute
    status: RunStatus
    result: str | None
