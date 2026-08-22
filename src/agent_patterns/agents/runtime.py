"""High-level execution and streaming interface for the supervisor graph."""

from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, StateSnapshot
from opentelemetry import trace
from opentelemetry.trace import Tracer

from agent_patterns.agents.graph import build_agent_graph
from agent_patterns.agents.state import AgentState, RunStatus
from agent_patterns.schemas import (
    AgentEvent,
    AgentRunRequest,
    AgentRunResponse,
    ApprovalRequest,
)


class RunNotFoundError(LookupError):
    """Raised when no checkpoint exists for a requested thread."""


class RunNotPendingApprovalError(ValueError):
    """Raised when a run cannot consume an approval decision."""


class AgentRuntime:
    """Own the compiled graph and expose checkpoint-aware operations."""

    def __init__(self, tracer: Tracer | None = None) -> None:
        self._tracer = tracer or trace.get_tracer(__name__)
        self._checkpointer = InMemorySaver()
        self._graph = build_agent_graph(self._checkpointer, self._tracer)

    @staticmethod
    def _config(thread_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": thread_id}}

    async def start(self, request: AgentRunRequest) -> AgentRunResponse:
        thread_id = request.thread_id or str(uuid4())
        initial: AgentState = {
            "thread_id": thread_id,
            "task": request.task,
            "risk_level": request.risk_level,
            "require_approval": request.require_approval,
            "approval_decision": None,
            "approval_feedback": None,
            "max_iterations": request.max_iterations,
            "audit_log": [],
            "completed_agents": [],
        }
        with self._tracer.start_as_current_span("agent.run") as span:
            span.set_attribute("agent.thread_id", thread_id)
            span.set_attribute("agent.risk_level", request.risk_level)
            span.set_attribute("agent.approval_required", request.require_approval)
            await self._graph.ainvoke(initial, self._config(thread_id))
            result = await self.get(thread_id)
            span.set_attribute("agent.status", result.status)
            return result

    async def resume(
        self,
        thread_id: str,
        approval: ApprovalRequest,
    ) -> AgentRunResponse:
        with self._tracer.start_as_current_span("agent.approval.resume") as span:
            span.set_attribute("agent.thread_id", thread_id)
            span.set_attribute("agent.approved", approval.approved)
            snapshot = await self._snapshot(thread_id)
            if not snapshot.interrupts:
                raise RunNotPendingApprovalError("Run is not waiting for approval")

            command: Command[Any] = Command(
                resume={"approved": approval.approved, "feedback": approval.feedback}
            )
            await self._graph.ainvoke(command, self._config(thread_id))
            result = await self.get(thread_id)
            span.set_attribute("agent.status", result.status)
            return result

    async def get(self, thread_id: str) -> AgentRunResponse:
        snapshot = await self._snapshot(thread_id)
        return self._to_response(thread_id, snapshot)

    async def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        thread_id = request.thread_id or str(uuid4())
        initial: AgentState = {
            "thread_id": thread_id,
            "task": request.task,
            "risk_level": request.risk_level,
            "require_approval": request.require_approval,
            "approval_decision": None,
            "approval_feedback": None,
            "max_iterations": request.max_iterations,
            "audit_log": [],
            "completed_agents": [],
        }
        with self._tracer.start_as_current_span("agent.run.stream") as span:
            span.set_attribute("agent.thread_id", thread_id)
            yield AgentEvent(type="run_started", thread_id=thread_id)
            stream = self._graph.astream(
                initial,
                self._config(thread_id),
                stream_mode=["custom", "updates"],
            )
            async for mode, raw_event in stream:
                if mode == "custom" and isinstance(raw_event, dict):
                    yield AgentEvent(
                        type="token",
                        thread_id=thread_id,
                        agent=raw_event.get("agent"),
                        token=raw_event.get("token"),
                    )

            run = await self.get(thread_id)
            span.set_attribute("agent.status", run.status)
            yield AgentEvent(type=run.status, thread_id=thread_id, run=run)

    async def _snapshot(self, thread_id: str) -> StateSnapshot:
        snapshot = await self._graph.aget_state(self._config(thread_id))
        if not snapshot.values:
            raise RunNotFoundError(f"Run {thread_id} was not found")
        return snapshot

    @staticmethod
    def _to_response(thread_id: str, snapshot: StateSnapshot) -> AgentRunResponse:
        values = cast(dict[str, Any], snapshot.values)
        interrupt_payload = (
            cast(dict[str, Any], snapshot.interrupts[0].value) if snapshot.interrupts else None
        )
        status: RunStatus = (
            "pending_approval"
            if snapshot.interrupts
            else cast(RunStatus, values.get("status", "running"))
        )
        return AgentRunResponse(
            thread_id=thread_id,
            status=status,
            task=values["task"],
            result=values.get("result"),
            completed_agents=values.get("completed_agents", []),
            audit_log=values.get("audit_log", []),
            approval=interrupt_payload,
        )
