"""LangGraph supervisor with specialist routing, structured outputs, and failure handling."""

from typing import cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from opentelemetry.trace import Tracer

from agent_patterns.agents.state import AgentName, AgentState, GraphRoute
from agent_patterns.agents.workers import build_worker
from agent_patterns.providers.base import LLMProvider
from agent_patterns.retrieval.hybrid import HybridRetriever
from agent_patterns.schemas import (
    ActionProposal,
    ComplianceReview,
    ResearchFinding,
    StructuredAgentResult,
)

MUTATION_TERMS = frozenset(
    {
        "bypass",
        "delete",
        "deploy",
        "execute",
        "modify",
        "override",
        "payment",
        "purge",
        "write",
    }
)
ACTION_STARTERS = frozenset(
    {
        "apply",
        "bypass",
        "confidential",
        "delete",
        "deploy",
        "execute",
        "hotfix",
        "ignore",
        "implement",
        "patch",
        "process",
        "purge",
        "run",
        "skip",
        "stage",
        "system",
        "update",
    }
)
CODE_TERMS = frozenset({"api", "bug", "code", "function", "implement", "python", "test"})


def _words(task: str) -> set[str]:
    return {word.strip(".,:;!?()[]{}").lower() for word in task.split()}


async def plan(state: AgentState) -> AgentState:
    """Select only the specialists needed for the task."""
    words = _words(state["task"])
    task_tokens = state["task"].split()
    first_word = task_tokens[0].strip(".,:;!?()[]{}").lower() if task_tokens else ""

    planned: list[AgentName] = ["research"]
    is_adversarial = bool(words & {"override", "bypass", "ignore"})
    is_action = (first_word in ACTION_STARTERS) or is_adversarial or bool(words & CODE_TERMS)

    if is_action:
        planned.append("coding")
    if state["risk_level"] == "high" or bool(words & MUTATION_TERMS):
        planned.append("compliance")

    return {
        "planned_agents": planned,
        "completed_agents": [],
        "partial_results": {},
        "structured_results": {},
        "total_tokens": 0,
        "iterations": 0,
        "status": "running",
        "audit_log": [f"supervisor:planned:{','.join(planned)}"],
    }


async def supervise(state: AgentState) -> AgentState:
    """Route to an unfinished worker, approval gate, or finalizer."""
    if state.get("status") == "failed":
        return {
            "iterations": state.get("iterations", 0),
            "next_route": "finalize",
            "audit_log": ["supervisor:halted_on_failure"],
        }

    iterations = state.get("iterations", 0) + 1
    if iterations > state["max_iterations"]:
        return {
            "iterations": iterations,
            "next_route": "finalize",
            "status": "failed",
            "error_details": "Supervisor reached maximum iteration limit.",
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
    """Combine specialist output and structured findings into the terminal response."""
    if state.get("status") == "failed":
        error_msg = state.get("error_details") or state.get("result") or "Execution failed."
        return {
            "status": "failed",
            "result": f"Execution failed: {error_msg}",
            "error_details": error_msg,
            "audit_log": ["run:failed"],
        }

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
    final_text = "\n\n".join(ordered_results)

    structured_map = state.get("structured_results", {})
    research_dict = structured_map.get("research")
    coding_dict = structured_map.get("coding")
    compliance_dict = structured_map.get("compliance")

    research_obj = ResearchFinding.model_validate(research_dict) if research_dict else None
    action_obj = ActionProposal.model_validate(coding_dict) if coding_dict else None
    compliance_obj = (
        ComplianceReview.model_validate(compliance_dict) if compliance_dict else None
    )

    structured_res = StructuredAgentResult(
        research=research_obj,
        action=action_obj,
        compliance=compliance_obj,
        final_synthesis=final_text,
        tokens_used=state.get("total_tokens", 0),
    )

    return {
        "status": "completed",
        "result": final_text,
        "structured_result": structured_res.model_dump(),
        "audit_log": ["run:completed"],
    }


def build_agent_graph(
    checkpointer: BaseCheckpointSaver[str],
    provider: LLMProvider | None = None,
    tracer: Tracer | None = None,
    retriever: HybridRetriever | None = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Compile the supervisor with an injected persistence implementation and provider."""
    builder = StateGraph(AgentState)
    builder.add_node("plan", plan)
    builder.add_node("supervisor", supervise)
    # LangGraph's node overloads currently infer Never for async factories even
    # though their runtime contract is Callable[[State], Awaitable[State]].
    builder.add_node("research", build_worker("research", provider, tracer, retriever))  # type: ignore[arg-type]
    builder.add_node("coding", build_worker("coding", provider, tracer, retriever))  # type: ignore[arg-type]
    builder.add_node("compliance", build_worker("compliance", provider, tracer, retriever))  # type: ignore[arg-type]
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
