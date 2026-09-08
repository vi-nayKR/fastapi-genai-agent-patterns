"""Specialist workers with provider integration, structured outputs, and failure handling."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

from langgraph.config import get_stream_writer
from opentelemetry import trace
from opentelemetry.trace import Tracer
from pydantic import BaseModel

from agent_patterns.agents.state import AgentName, AgentState
from agent_patterns.providers.base import LLMProvider, ProviderError
from agent_patterns.providers.deterministic_provider import DeterministicProvider
from agent_patterns.schemas import ActionProposal, ComplianceReview, ResearchFinding

Worker = Callable[[AgentState], Awaitable[AgentState]]


def _system_prompt(agent: AgentName) -> str:
    if agent == "research":
        return (
            "You are an enterprise research specialist. Synthesize verified facts, cite "
            "authoritative documents, evaluate confidence, and explicitly abstain if unsupported."
        )
    if agent == "coding":
        return (
            "You are an operations and systems specialist. Propose bounded technical actions, "
            "isolate side effects, identify affected resources, and distinguish mutations."
        )
    return (
        "You are a compliance and security specialist. Enforce least privilege, assess risk, "
        "and determine whether mutations mandate explicit human authorization."
    )


def _schema_for_agent(agent: AgentName) -> type[BaseModel]:
    if agent == "research":
        return ResearchFinding
    if agent == "coding":
        return ActionProposal
    return ComplianceReview


def build_worker(
    agent: AgentName,
    provider: LLMProvider | None = None,
    tracer: Tracer | None = None,
) -> Worker:
    """Build a graph node that calls the model provider and emits structured tokens."""
    resolved_tracer = tracer or trace.get_tracer(__name__)
    active_provider: LLMProvider = provider or DeterministicProvider(tracer=resolved_tracer)
    schema = _schema_for_agent(agent)

    async def worker(state: AgentState) -> AgentState:
        with resolved_tracer.start_as_current_span(f"agent.worker.{agent}") as span:
            span.set_attribute("agent.name", agent)
            span.set_attribute("agent.thread_id", state["thread_id"])

            # If an earlier specialist failed, avoid executing subsequent nodes
            if state.get("status") == "failed":
                return {}

            messages = [
                {"role": "system", "content": _system_prompt(agent)},
                {"role": "user", "content": state["task"]},
            ]

            try:
                response = await active_provider.generate(
                    messages,
                    response_schema=schema,
                )
            except ProviderError as exc:
                span.record_exception(exc)
                span.set_attribute("agent.status", "failed")
                # Do NOT silently fall back in real provider mode; fail explicitly
                return {
                    "status": "failed",
                    "error_details": (
                        f"Provider failure ({exc.__class__.__name__}) in {agent} worker: {exc}"
                    ),
                    "audit_log": [f"{agent}:failed:{exc.__class__.__name__}"],
                }
            except Exception as exc:
                span.record_exception(exc)
                span.set_attribute("agent.status", "failed")
                return {
                    "status": "failed",
                    "error_details": f"Unexpected error in {agent} worker: {exc}",
                    "audit_log": [f"{agent}:failed:unexpected"],
                }

            writer = get_stream_writer()
            for token in response.content.split():
                writer({"type": "token", "agent": agent, "token": f"{token} "})
                await asyncio.sleep(0)

            partial_results = dict(state.get("partial_results", {}))
            partial_results[agent] = response.content

            structured_results = dict(state.get("structured_results", {}))
            if response.structured is not None:
                if hasattr(response.structured, "model_dump"):
                    dumped = response.structured.model_dump()
                    structured_results[agent] = cast(dict[str, object], dumped)
                else:
                    structured_results[agent] = cast(dict[str, object], response.structured)

            tokens = state.get("total_tokens", 0) + response.usage.total_tokens
            span.set_attribute("agent.output_tokens", len(response.content.split()))

            return {
                "partial_results": partial_results,
                "structured_results": structured_results,
                "total_tokens": tokens,
                "completed_agents": [agent],
                "audit_log": [f"{agent}:completed"],
            }

    return worker
