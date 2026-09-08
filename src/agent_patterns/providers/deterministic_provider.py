"""Deterministic provider fixture for local development and zero-network testing."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Tracer
from pydantic import BaseModel

from agent_patterns.providers.base import (
    LLMProvider,
    ProviderResponse,
    ProviderUsage,
)
from agent_patterns.schemas import (
    ActionProposal,
    ComplianceReview,
    ResearchFinding,
)


class DeterministicProvider(LLMProvider):
    """Deterministic model double producing schema-valid outputs without external calls."""

    def __init__(self, tracer: Tracer | None = None) -> None:
        self._tracer = tracer or trace.get_tracer(__name__)

    async def close(self) -> None:
        """No-op cleanup for the in-memory double."""
        pass

    def _extract_task(self, messages: list[dict[str, str]]) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return "general operational task"

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: type[BaseModel] | None = None,
        request_timeout: float | None = None,
    ) -> ProviderResponse:
        """Return deterministic, schema-valid data based on the requested model schema."""
        del request_timeout
        with self._tracer.start_as_current_span("provider.chat.completions") as span:
            span.set_attribute("provider.name", "deterministic")
            span.set_attribute("provider.model", "deterministic-fixture")
            span.set_attribute("provider.streaming", False)

            task = self._extract_task(messages)
            structured_result: Any = None
            content: str

            if response_schema is ResearchFinding:
                finding = ResearchFinding(
                    summary=(
                        "Research summary: identify authoritative sources, validate assumptions, "
                        f"and retain citations for the task: {task}"
                    ),
                    citations=["DOC-SEC-402", "RUNBOOK-OP-12"],
                    confidence="high",
                    abstain=False,
                )
                structured_result = finding
                content = finding.summary
            elif response_schema is ActionProposal:
                is_payment = "payment" in task.lower() or "deploy" in task.lower()
                proposal = ActionProposal(
                    summary=(
                        "Implementation plan: isolate side effects, add typed interfaces, "
                        f"test failure paths, and stage the requested change for: {task}"
                    ),
                    action_type="ticket_update" if is_payment else "read_only",
                    target_resource="TICKET-592" if is_payment else None,
                    parameters={"action": "stage_deployment"} if is_payment else {},
                    is_mutation=is_payment,
                )
                structured_result = proposal
                content = proposal.summary
            elif response_schema is ComplianceReview:
                is_payment = "payment" in task.lower() or "deploy" in task.lower()
                compliance_summary = (
                    "Compliance review: apply least privilege, redact sensitive inputs, "
                    "preserve an audit trail, and require approval for mutations "
                    f"related to: {task}"
                )
                review = ComplianceReview(
                    policy_satisfied=True,
                    risk_assessment="high" if is_payment else "low",
                    requires_human_approval=is_payment,
                    audit_notes=[
                        "Applied least privilege checks.",
                        compliance_summary,
                    ],
                )
                structured_result = review
                content = review.audit_notes[-1]
            elif response_schema is not None:
                content = f"Deterministic response for {response_schema.__name__}: {task}"
                try:
                    structured_result = response_schema.model_validate_json(
                        f'{{"summary": "{content}"}}'
                    )
                except Exception:
                    structured_result = None
            else:
                content = f"Deterministic output for task: {task}"

            words = content.split()
            usage = ProviderUsage(
                prompt_tokens=len(task.split()),
                completion_tokens=len(words),
                total_tokens=len(task.split()) + len(words),
            )
            span.set_attribute("llm.usage.prompt_tokens", usage.prompt_tokens)
            span.set_attribute("llm.usage.completion_tokens", usage.completion_tokens)
            span.set_attribute("llm.usage.total_tokens", usage.total_tokens)
            span.set_attribute("provider.status", "success")

            return ProviderResponse(
                content=content,
                usage=usage,
                model="deterministic-fixture",
                structured=structured_result,
            )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        request_timeout: float | None = None,
    ) -> AsyncIterator[str]:
        """Stream tokens asynchronously for deterministic testing."""
        del request_timeout
        with self._tracer.start_as_current_span("provider.chat.completions.stream") as span:
            span.set_attribute("provider.name", "deterministic")
            span.set_attribute("provider.model", "deterministic-fixture")
            span.set_attribute("provider.streaming", True)

            task = self._extract_task(messages)
            content = (
                "Implementation plan: isolate side effects, add typed interfaces, "
                f"test failure paths, and stage the requested change for: {task}"
            )
            for word in content.split():
                yield f"{word} "
                await asyncio.sleep(0)
