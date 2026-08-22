"""Deterministic specialist workers used by the reference graph."""

import asyncio
from collections.abc import Awaitable, Callable

from langgraph.config import get_stream_writer

from agent_patterns.agents.state import AgentName, AgentState

Worker = Callable[[AgentState], Awaitable[AgentState]]


def _response(agent: AgentName, task: str) -> str:
    """Create useful local output without requiring an external model account."""

    if agent == "research":
        return (
            "Research summary: identify authoritative sources, validate assumptions, "
            f"and retain citations for the task: {task}"
        )
    if agent == "coding":
        return (
            "Implementation plan: isolate side effects, add typed interfaces, test failure "
            f"paths, and stage the requested change for: {task}"
        )
    return (
        "Compliance review: apply least privilege, redact sensitive inputs, preserve an "
        f"audit trail, and require approval for mutations related to: {task}"
    )


def build_worker(agent: AgentName) -> Worker:
    """Build a graph node that emits each output token asynchronously."""

    async def worker(state: AgentState) -> AgentState:
        output = _response(agent, state["task"])
        writer = get_stream_writer()
        for token in output.split():
            writer({"type": "token", "agent": agent, "token": f"{token} "})
            await asyncio.sleep(0)

        partial_results = dict(state.get("partial_results", {}))
        partial_results[agent] = output
        return {
            "partial_results": partial_results,
            "completed_agents": [agent],
            "audit_log": [f"{agent}:completed"],
        }

    return worker
