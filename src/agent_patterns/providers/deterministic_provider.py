"""Deterministic provider fixture for local development and zero-network testing."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any, Literal

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

QUESTION_STARTERS = frozenset(
    {"what", "who", "can", "is", "how", "why", "which", "where", "retrieve"}
)
UNANSWERABLE_TOPICS = frozenset(
    {
        "bitcoin",
        "crypto",
        "wallet",
        "compensation",
        "salary",
        "bonus bracket",
        "apache mesos",
        "mesos",
        "equity purchase",
        "ipo window",
        "parking permit",
    }
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

            # Isolate original user query from injected retrieval passages and prior findings
            query_content = task.split("Retrieved authoritative documentation:")[0]
            query_content = query_content.split("Prior Research Findings:")[0]
            q_lower = query_content.lower()

            task_tokens = query_content.split()
            filtered_tokens = [
                t for t in task_tokens if not t.startswith("[tenant:") and not t.endswith("]")
            ]
            first_word = (
                filtered_tokens[0].strip(".,:;!?()[]{}").lower() if filtered_tokens else ""
            )
            is_q = first_word in QUESTION_STARTERS

            action_type: Literal["read_only", "ticket_update", "system_change", "escalate"]
            if is_q and not any(k in q_lower for k in ("override", "bypass")):
                action_type = "read_only"
                is_mutation = False
            else:
                is_mutation = any(
                    k in q_lower
                    for k in (
                        "deploy",
                        "delete",
                        "purge",
                        "migration",
                        "hotfix",
                        "patch",
                        "stage",
                        "credit",
                        "payout",
                        "payment",
                    )
                ) or (
                    "refund" in q_lower
                    and any(
                        v in q_lower
                        for v in ("apply", "execute", "process", "mark", "pre-approved")
                    )
                )
                if not is_mutation:
                    action_type = "read_only"
                elif any(k in q_lower for k in ("ticket", "refund", "invoice", "credit", "payout")):
                    action_type = "ticket_update"
                else:
                    action_type = "system_change"

            if response_schema is ResearchFinding:
                has_retrieved_context = "Retrieved authoritative documentation:" in task
                if has_retrieved_context:
                    is_unanswerable = any(topic in q_lower for topic in UNANSWERABLE_TOPICS)
                    is_cross_tenant = (
                        ("tenant beta" in q_lower and "[tenant: tenant-alpha]" in task)
                        or ("tenant alpha" in q_lower and "[tenant: tenant-beta]" in task)
                    )
                    doc_ids = list(dict.fromkeys(re.findall(r"\[(DOC-[A-Za-z0-9-]+) v", task)))

                    if is_unanswerable or is_cross_tenant or not doc_ids:
                        finding = ResearchFinding(
                            summary=(
                                "Abstain: No authoritative documentation found for this query "
                                "in the tenant operational corpus."
                            ),
                            citations=[],
                            confidence="low",
                            abstain=True,
                        )
                    else:
                        finding = ResearchFinding(
                            summary=(
                                "Research summary: synthesized findings from verified document(s): "
                                f"{', '.join(doc_ids)}."
                            ),
                            citations=doc_ids[:2],
                            confidence="high",
                            abstain=False,
                        )
                else:
                    finding = ResearchFinding(
                        summary=(
                            "Research summary: identify authoritative sources, validate "
                            f"assumptions, and retain citations for the task: {task}"
                        ),
                        citations=["DOC-SEC-402", "RUNBOOK-OP-12"],
                        confidence="high",
                        abstain=False,
                    )
                structured_result = finding
                content = finding.summary
            elif response_schema is ActionProposal:
                proposal = ActionProposal(
                    summary=(
                        "Implementation plan: isolate side effects, add typed interfaces, "
                        "test failure paths, and stage the requested change for: "
                        f"{query_content.splitlines()[0]}"
                    ),
                    action_type=action_type,
                    target_resource="TICKET-592" if action_type == "ticket_update" else (
                        "PROD-CLUSTER" if is_mutation else None
                    ),
                    parameters={"action": "stage_operation"} if is_mutation else {},
                    is_mutation=is_mutation,
                )
                structured_result = proposal
                content = proposal.summary
            elif response_schema is ComplianceReview:
                is_override = any(
                    k in q_lower
                    for k in ("override", "bypass", "ignore", "confidential instruction")
                )
                if is_override:
                    review = ComplianceReview(
                        policy_satisfied=False,
                        risk_assessment="high",
                        requires_human_approval=True,
                        audit_notes=[
                            "Flagged adversarial prompt override attempt.",
                            "Execution halted. Explicit human authorization required for "
                            "mutations.",
                        ],
                    )
                elif is_mutation:
                    if "$45" in q_lower:
                        review = ComplianceReview(
                            policy_satisfied=True,
                            risk_assessment="low",
                            requires_human_approval=False,
                            audit_notes=[
                                "Applied least privilege checks.",
                                "Refund amount is within support agent authorization threshold "
                                "($100).",
                            ],
                        )
                    else:
                        review = ComplianceReview(
                            policy_satisfied=True,
                            risk_assessment="high",
                            requires_human_approval=True,
                            audit_notes=[
                                "Applied least privilege checks.",
                                "Mandated human approval for production mutation.",
                            ],
                        )
                else:
                    review = ComplianceReview(
                        policy_satisfied=True,
                        risk_assessment="low",
                        requires_human_approval=False,
                        audit_notes=[
                            "Applied least privilege checks.",
                            "Read-only operational query verified against compliance constraints.",
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
