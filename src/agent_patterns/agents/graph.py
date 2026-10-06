"""LangGraph supervisor with specialist routing, structured outputs, and failure handling."""

import json
from typing import cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from opentelemetry.trace import Tracer

from agent_patterns.agents.state import AgentName, AgentState, GraphRoute
from agent_patterns.agents.workers import build_worker
from agent_patterns.incident_tools import approval_signature
from agent_patterns.mcp_client import IncidentToolClient
from agent_patterns.providers.base import LLMProvider
from agent_patterns.schemas import (
    StructuredAgentResult,
)

SPECIALISTS: tuple[AgentName, ...] = (
    "log_parser",
    "incident_retriever",
    "root_cause",
    "fix_drafter",
)


async def plan(state: AgentState) -> AgentState:
    """Triage always parses, retrieves, hypothesizes and drafts; logs never set routes."""
    return {
        "planned_agents": list(SPECIALISTS),
        "partial_results": {},
        "total_tokens": 0,
        "iterations": 0,
        "status": "running",
        "audit_log": ["supervisor:planned:triage"],
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
    if "root_cause" in completed and not state.get("hypotheses"):
        route: GraphRoute = "finalize"
    elif remaining and len(completed) >= state["max_steps"]:
        return {
            "status": "failed",
            "next_route": "finalize",
            "error_details": "Maximum specialist steps reached; no action taken.",
            "audit_log": ["supervisor:step_limit"],
        }
    elif remaining:
        route = remaining[0]
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
    return state["create_ticket"] or state["require_approval"] or state["risk_level"] == "high"


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
            "proposed_fix": state.get("fix", {}),
            "ticket_requested": state["create_ticket"],
        }
    )
    if not isinstance(decision, dict) or not isinstance(decision.get("approved"), bool):
        raise ValueError("The approval resume payload must contain an approved boolean")

    approved = cast(bool, decision["approved"])
    feedback_value = decision.get("feedback")
    feedback = str(feedback_value) if feedback_value is not None else None
    reviewer_id = str(decision.get("reviewer_id", "unknown"))
    return {
        "approval_decision": approved,
        "approval_feedback": feedback,
        "approval_reviewer_id": reviewer_id,
        "audit_log": [
            "approval:approved" if approved else "approval:rejected",
            f"approval:reviewer:{reviewer_id}",
        ],
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

    fix = state.get("fix", {})
    final_text = json.dumps({"hypotheses": state.get("hypotheses", []), "fix": fix})
    structured_res = StructuredAgentResult(
        parsed_log=state.get("parsed_log", {}),
        similar_incidents=state.get("similar_incidents", []),
        hypotheses=state.get("hypotheses", []),
        suggested_fix="\n".join(str(fix.get(k, "")) for k in ("summary", "verification", "risks")),
        ticket=state.get("ticket"),
        final_synthesis=final_text,
        tokens_used=state.get("total_tokens", 0),
        estimated_cost_usd=state.get("estimated_cost_usd", 0),
    )
    return {
        "status": "completed",
        "result": final_text,
        "structured_result": structured_res.model_dump(),
        "audit_log": ["run:completed"],
    }


def build_agent_graph(
    checkpointer: BaseCheckpointSaver[str],
    provider: LLMProvider,
    tracer: Tracer,
    tools: IncidentToolClient,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Compile the supervisor with an injected persistence implementation and provider."""
    builder = StateGraph(AgentState)
    builder.add_node("plan", plan)
    builder.add_node("supervisor", supervise)
    for agent in SPECIALISTS:
        builder.add_node(agent, build_worker(agent, provider, tracer, tools))  # type: ignore[arg-type]

    async def ticket(state: AgentState) -> AgentState:
        if not state["create_ticket"] or state.get("approval_decision") is not True:
            return {}
        if len(state["completed_agents"]) >= state["max_steps"]:
            return {
                "status": "failed",
                "error_details": "Step budget exhausted before ticket creation.",
                "audit_log": ["supervisor:step_limit"],
            }
        draft = {"summary": state["fix"]["summary"], "body": json.dumps(state["fix"])}
        signature = approval_signature(tools.secret, state["tenant_id"], state["thread_id"], draft)
        try:
            result = await tools.call(
                "create_ticket_draft",
                {"thread_id": state["thread_id"], **draft, "approval_token": signature},
            )
            return {
                "ticket": result,
                "audit_log": ["ticket:created_after_approval"],
                "trajectory": [{"tool": "create_ticket_draft", "approved": True, "success": True}],
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error_details": f"Ticket persistence failed: {exc}",
                "audit_log": ["ticket:failed"],
                "trajectory": [{"tool": "create_ticket_draft", "approved": True, "success": False}],
            }

    builder.add_node("ticket", ticket)
    builder.add_node("approval", request_approval)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "supervisor")
    builder.add_conditional_edges("supervisor", select_route)
    for worker in SPECIALISTS:
        builder.add_edge(worker, "supervisor")
    builder.add_edge("approval", "ticket")
    builder.add_edge("ticket", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer, name="traceward-incident-supervisor")
