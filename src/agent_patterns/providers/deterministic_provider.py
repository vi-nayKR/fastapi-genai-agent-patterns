"""Offline retrieval-copy baseline, never presented as measured LLM performance."""

import json
from collections.abc import AsyncIterator
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Tracer
from pydantic import BaseModel

from agent_patterns.providers.base import ProviderResponse, ProviderUsage
from agent_patterns.schemas import FixDraft, RootCauseReport


class DeterministicProvider:
    def __init__(self, tracer: Tracer | None = None) -> None:
        self._tracer = tracer or trace.get_tracer(__name__)

    async def close(self) -> None:
        pass

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: type[BaseModel] | None = None,
        request_timeout: float | None = None,
        max_output_tokens: int | None = None,
    ) -> ProviderResponse:
        del request_timeout, max_output_tokens
        with self._tracer.start_as_current_span("provider.chat.completions") as span:
            span.set_attribute("provider.name", "deterministic")
            data = json.loads(messages[-1]["content"])
            incidents = data.get("similar_incidents", [])
            if not data.get("parsed_log", {}).get("exceptions"):
                incidents = []
            value: dict[str, Any]
            if response_schema is RootCauseReport:
                seen: set[str] = set()
                hypotheses = []
                for row in incidents:
                    if row["root_cause_label"] not in seen:
                        seen.add(row["root_cause_label"])
                        hypotheses.append(
                            {
                                "label": row["root_cause_label"],
                                "explanation": row["root_cause"],
                                "incident_ids": [row["id"]],
                            }
                        )
                value = {"hypotheses": hypotheses[:3], "abstain": not hypotheses}
            elif response_schema is FixDraft:
                value = {
                    "summary": incidents[0]["resolution"]
                    if incidents
                    else "Escalate: insufficient evidence.",
                    "verification": (
                        "Reproduce the crash, test the proposed fix in staging, then monitor "
                        "recurrence."
                    ),
                    "risks": (
                        "Historical similarity does not establish causality; human review required."
                    ),
                }
            else:
                raise ValueError(
                    "Offline baseline supports triage schemas only; no fake judge scores"
                )
            structured = response_schema.model_validate(value)
            content = structured.model_dump_json()
            # Offline counters are bytes, not provider token usage.
            prompt = sum(len(m["content"].encode()) for m in messages)
            usage = ProviderUsage(prompt, len(content.encode()), prompt + len(content.encode()))
            span.set_attribute("llm.usage.total_tokens", usage.total_tokens)
            return ProviderResponse(content, usage, "retrieval-copy-baseline", structured)

    async def stream(
        self, messages: list[dict[str, str]], *, request_timeout: float | None = None
    ) -> AsyncIterator[str]:
        del messages, request_timeout
        yield "Offline baseline uses structured worker streaming."
