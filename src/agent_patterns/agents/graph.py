"""LangGraph supervisor with specialist routing and approval interrupts."""

from typing import cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from agent_patterns.agents.state import AgentName, AgentState, GraphRoute
from agent_patterns.agents.workers import build_worker

MUTATION_TERMS = frozenset({"delete", "deploy", "execute", "modify", "payment", "write"})
CODE_TERMS = frozenset({"api", "bug", "code", "function", "implement", "python", "test"})


def _words(task: str) -> set[str]:
    return {word.strip(".,:;!?()[]{}").lower() for word in task.split()}


async def plan(state: AgentState) -> AgentState:
    """Select only the specialists needed for the task."""

    words = _words(state["task"])
    planned: list[AgentName] = ["research"]
    if words & CODE_TERMS:
        planned.append("coding")
    if state["risk_level"] == "high" or words & MUTATION_TERMS:
        planned.append("compliance")

    return {
        "planned_agents": planned,
        "completed_agents": [],
        "partial_results": {},
        "iterations": 0,
        "status": "running",
        "audit_log": [f"supervisor:planned:{','.join(planned)}"],
    }


async def supervise(state: AgentState) -> AgentState:
    """Route to an unfinished worker, approval gate, or finalizer."""

    iterations = state.get("iterations", 0) + 1
    if iterations > state["max_iterations"]:
        return {
            "iterations": iterations,
            "next_route": "finalize",
            "status": "failed",
            "result": "Supervisor stopped after reaching the iteration limit.",
            "audit_log": ["supervisor:iteration_limit"],
        }

    completed = set(state.get("completed_agents", []))
    remaining = [agent for agent in state["planned_agents"] if agent not in completed]
    if remaining:
        route: GraphRoute = remaining[0]
    elif _needs_approval(state) and state.get("approval_decision") is None:
        route = "approval"
    else:
        route = "finalize"

    return {
        "iterations": iterations,
        "next_route": route,
        "audit_log": [f"supervisor:routed:{route}"],
    }


def _needs_approval(state: AgentState) -> bool:
    return state["require_approval"] or state["risk_level"] == "high"


def select_route(state: AgentState) -> GraphRoute:
    return state["next_route"]


async def request_approval(state: AgentState) -> AgentState:
    """Suspend execution and consume the decision supplied during resume."""

    decision = interrupt(
        {
            "type": "approval_required",
            "thread_id": state["thread_id"],
            "task": state["task"],
            "completed_agents": state.get("completed_agents", []),
            "risk_level": state["risk_level"],
        }
    )
    if not isinstance(decision, dict) or not isinstance(decision.get("approved"), bool):
        raise ValueError("The approval resume payload must contain an approved boolean")

    approved = cast(bool, decision["approved"])
    feedback_value = decision.get("feedback")
    feedback = str(feedback_value) if feedback_value is not None else None
    return {
        "approval_decision": approved,
        "approval_feedback": feedback,
        "audit_log": ["approval:approved" if approved else "approval:rejected"],
    }


async def finalize(state: AgentState) -> AgentState:
    """Combine specialist output only after policy requirements are satisfied."""

    if state.get("status") == "failed":
        return {}
    if state.get("approval_decision") is False:
        feedback = state.get("approval_feedback") or "No feedback was supplied."
        return {
            "status": "rejected",
            "result": f"Execution was rejected by the reviewer. {feedback}",
            "audit_log": ["run:rejected"],
        }

    ordered_results = [
        state.get("partial_results", {})[agent]
        for agent in state.get("completed_agents", [])
        if agent in state.get("partial_results", {})
    ]
    return {
        "status": "completed",
        "result": "\n\n".join(ordered_results),
        "audit_log": ["run:completed"],
    }


def build_agent_graph(
    checkpointer: BaseCheckpointSaver[str],
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Compile the supervisor with an injected persistence implementation."""

    builder = StateGraph(AgentState)
    builder.add_node("plan", plan)
    builder.add_node("supervisor", supervise)
    # LangGraph's node overloads currently infer Never for async factories even
    # though their runtime contract is Callable[[State], Awaitable[State]].
    builder.add_node("research", build_worker("research"))  # type: ignore[arg-type]
    builder.add_node("coding", build_worker("coding"))  # type: ignore[arg-type]
    builder.add_node("compliance", build_worker("compliance"))  # type: ignore[arg-type]
    builder.add_node("approval", request_approval)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "supervisor")
    builder.add_conditional_edges("supervisor", select_route)
    for worker in ("research", "coding", "compliance"):
        builder.add_edge(worker, "supervisor")
    builder.add_edge("approval", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer, name="production-agent-supervisor")
