"""High-level execution and streaming interface for the supervisor graph."""

from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, StateSnapshot
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, Tracer

from agent_patterns.agents.graph import build_agent_graph
from agent_patterns.agents.state import AgentState, RunStatus
from agent_patterns.config import Settings, get_settings
from agent_patterns.providers.base import LLMProvider
from agent_patterns.providers.factory import create_provider
from agent_patterns.retrieval.corpus import OPERATIONAL_CORPUS
from agent_patterns.retrieval.hybrid import HybridRetriever
from agent_patterns.schemas import (
    ActionProposal,
    AgentEvent,
    AgentRunRequest,
    AgentRunResponse,
    ApprovalRequest,
    ComplianceReview,
    ResearchFinding,
    StructuredAgentResult,
)


class RunNotFoundError(LookupError):
    """Raised when no checkpoint exists for a requested thread."""


class RunNotPendingApprovalError(ValueError):
    """Raised when a run cannot consume an approval decision."""


class AgentRuntime:
    """Own the compiled graph, provider adapter, and checkpoint-aware operations."""

    def __init__(
        self,
        tracer: Tracer | None = None,
        settings: Settings | None = None,
        provider: LLMProvider | None = None,
        retriever: HybridRetriever | None = None,
        checkpointer: BaseCheckpointSaver[str] | None = None,
    ) -> None:
        self._tracer = tracer or trace.get_tracer(__name__)
        self._settings = settings or get_settings()
        self._provider = provider or create_provider(self._settings, tracer=self._tracer)
        self._retriever = retriever or HybridRetriever(OPERATIONAL_CORPUS, tracer=self._tracer)
        self._checkpointer = checkpointer or InMemorySaver()
        self._graph = build_agent_graph(
            self._checkpointer,
            provider=self._provider,
            tracer=self._tracer,
            retriever=self._retriever,
        )

    async def close(self) -> None:
        """Close provider resources."""
        await self._provider.close()

    @staticmethod
    def _config(thread_id: str, tenant_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": f"{tenant_id}:{thread_id}"}}

    async def start(self, request: AgentRunRequest, *, tenant_id: str) -> AgentRunResponse:
        thread_id = str(uuid4())
        initial: AgentState = {
            "thread_id": thread_id,
            "tenant_id": tenant_id,
            "task": request.task,
            "risk_level": request.risk_level,
            "require_approval": request.require_approval,
            "approval_decision": None,
            "approval_feedback": None,
            "max_iterations": request.max_iterations,
            "audit_log": [],
            "completed_agents": [],
            "partial_results": {},
            "structured_results": {},
            "total_tokens": 0,
        }
        with self._tracer.start_as_current_span("agent.run") as span:
            span.set_attribute("agent.thread_id", thread_id)
            span.set_attribute("agent.risk_level", request.risk_level)
            span.set_attribute(
                "agent.approval_required",
                request.require_approval or request.risk_level == "high",
            )
            await self._graph.ainvoke(initial, self._config(thread_id, tenant_id))
            result = await self.get(thread_id, tenant_id=tenant_id)
            span.set_attribute("agent.status", result.status)
            if result.status == "failed":
                span.set_status(Status(StatusCode.ERROR, "agent run failed"))
            return result

    async def resume(
        self,
        thread_id: str,
        approval: ApprovalRequest,
        *,
        tenant_id: str,
        reviewer_id: str,
    ) -> AgentRunResponse:
        with self._tracer.start_as_current_span("agent.approval.resume") as span:
            span.set_attribute("agent.thread_id", thread_id)
            span.set_attribute("agent.approved", approval.approved)
            snapshot = await self._snapshot(thread_id, tenant_id)
            if not snapshot.interrupts:
                raise RunNotPendingApprovalError("Run is not waiting for approval")

            command: Command[Any] = Command(
                resume={
                    "approved": approval.approved,
                    "feedback": approval.feedback,
                    "reviewer_id": reviewer_id,
                }
            )
            await self._graph.ainvoke(command, self._config(thread_id, tenant_id))
            result = await self.get(thread_id, tenant_id=tenant_id)
            span.set_attribute("agent.status", result.status)
            if result.status == "failed":
                span.set_status(Status(StatusCode.ERROR, "agent run failed"))
            return result

    async def get(self, thread_id: str, *, tenant_id: str) -> AgentRunResponse:
        snapshot = await self._snapshot(thread_id, tenant_id)
        return self._to_response(thread_id, snapshot)

    async def stream(
        self, request: AgentRunRequest, *, tenant_id: str
    ) -> AsyncIterator[AgentEvent]:
        thread_id = str(uuid4())
        initial: AgentState = {
            "thread_id": thread_id,
            "tenant_id": tenant_id,
            "task": request.task,
            "risk_level": request.risk_level,
            "require_approval": request.require_approval,
            "approval_decision": None,
            "approval_feedback": None,
            "max_iterations": request.max_iterations,
            "audit_log": [],
            "completed_agents": [],
            "partial_results": {},
            "structured_results": {},
            "total_tokens": 0,
        }
        with self._tracer.start_as_current_span("agent.run.stream") as span:
            span.set_attribute("agent.thread_id", thread_id)
            yield AgentEvent(type="run_started", thread_id=thread_id)
            stream = self._graph.astream(
                initial,
                self._config(thread_id, tenant_id),
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

            run = await self.get(thread_id, tenant_id=tenant_id)
            span.set_attribute("agent.status", run.status)
            yield AgentEvent(type=run.status, thread_id=thread_id, run=run)

    async def _snapshot(self, thread_id: str, tenant_id: str) -> StateSnapshot:
        snapshot = await self._graph.aget_state(self._config(thread_id, tenant_id))
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
        structured_raw = values.get("structured_result")
        structured_obj = (
            StructuredAgentResult.model_validate(structured_raw) if structured_raw else None
        )
        if not structured_obj and values.get("structured_results"):
            s_map = values["structured_results"]
            r_dict = s_map.get("research")
            a_dict = s_map.get("coding")
            c_dict = s_map.get("compliance")
            structured_obj = StructuredAgentResult(
                research=ResearchFinding.model_validate(r_dict) if r_dict else None,
                action=ActionProposal.model_validate(a_dict) if a_dict else None,
                compliance=ComplianceReview.model_validate(c_dict) if c_dict else None,
                final_synthesis=values.get("result") or "Pending approval by human operator.",
                tokens_used=values.get("total_tokens", 0),
            )
        return AgentRunResponse(
            thread_id=thread_id,
            tenant_id=values.get("tenant_id", "tenant-alpha"),
            status=status,
            task=values["task"],
            result=values.get("result"),
            structured_result=structured_obj,
            error_details=values.get("error_details"),
            completed_agents=values.get("completed_agents", []),
            audit_log=values.get("audit_log", []),
            approval=interrupt_payload,
        )
