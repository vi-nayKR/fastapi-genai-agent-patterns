"""High-level execution and streaming interface for the supervisor graph."""

import hashlib
import secrets
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
from agent_patterns.mcp_client import IncidentToolClient
from agent_patterns.providers.base import LLMProvider
from agent_patterns.providers.factory import create_provider
from agent_patterns.schemas import (
    AgentEvent,
    AgentRunRequest,
    AgentRunResponse,
    ApprovalRequest,
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
        checkpointer: BaseCheckpointSaver[str] | None = None,
    ) -> None:
        self._tracer = tracer or trace.get_tracer(__name__)
        self._settings = settings or get_settings()
        self._provider = provider or create_provider(self._settings, tracer=self._tracer)
        key = self._settings.reviewer_api_key
        secret = (
            hashlib.sha256((key.get_secret_value() + ":traceward-approval").encode()).hexdigest()
            if key
            else secrets.token_hex(32)
        )
        self._tools = IncidentToolClient(self._settings, secret, self._tracer)
        self._checkpointer = checkpointer or InMemorySaver()
        self._graph = build_agent_graph(
            self._checkpointer,
            provider=self._provider,
            tracer=self._tracer,
            tools=self._tools,
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
            "max_steps": request.max_steps,
            "audit_log": [],
            "completed_agents": [],
            "partial_results": {},
            "total_tokens": 0,
            "reserved_tokens": 0,
            "max_tokens": request.max_tokens,
            "max_cost_usd": request.max_cost_usd,
            "create_ticket": request.create_ticket,
            "trajectory": [],
        }
        async with self._tools.connect(tenant_id):
            return await self._start_connected(initial, thread_id, tenant_id, request)

    async def _start_connected(
        self, initial: AgentState, thread_id: str, tenant_id: str, request: AgentRunRequest
    ) -> AgentRunResponse:
        with self._tracer.start_as_current_span("agent.run") as span:
            span.set_attribute("agent.thread_id", thread_id)
            span.set_attribute("agent.risk_level", request.risk_level)
            span.set_attribute(
                "agent.approval_required",
                request.create_ticket or request.require_approval or request.risk_level == "high",
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
        async with self._tools.connect(tenant_id):
            return await self._resume_connected(thread_id, approval, tenant_id, reviewer_id)

    async def _resume_connected(
        self, thread_id: str, approval: ApprovalRequest, tenant_id: str, reviewer_id: str
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
            "max_steps": request.max_steps,
            "audit_log": [],
            "completed_agents": [],
            "partial_results": {},
            "total_tokens": 0,
            "reserved_tokens": 0,
            "max_tokens": request.max_tokens,
            "max_cost_usd": request.max_cost_usd,
            "create_ticket": request.create_ticket,
            "trajectory": [],
        }
        async with self._tools.connect(tenant_id):
            async for event in self._stream_connected(initial, thread_id, tenant_id):
                yield event

    async def _stream_connected(
        self, initial: AgentState, thread_id: str, tenant_id: str
    ) -> AsyncIterator[AgentEvent]:
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
        if not structured_obj:
            fix = values.get("fix", {})
            structured_obj = StructuredAgentResult(
                parsed_log=values.get("parsed_log", {}),
                similar_incidents=values.get("similar_incidents", []),
                hypotheses=values.get("hypotheses", []),
                suggested_fix="\n".join(
                    str(fix.get(k, "")) for k in ("summary", "verification", "risks")
                ),
                final_synthesis=values.get("result") or "Pending human review.",
                tokens_used=values.get("total_tokens", 0),
                estimated_cost_usd=values.get("estimated_cost_usd", 0),
                ticket=values.get("ticket"),
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
            trajectory=values.get("trajectory", []),
            steps=sum(
                ("agent" in event and "latency_seconds" in event)
                or event.get("tool") == "create_ticket_draft"
                for event in values.get("trajectory", [])
            ),
            tokens_used=values.get("total_tokens", 0),
            estimated_cost_usd=values.get("estimated_cost_usd", 0),
        )
