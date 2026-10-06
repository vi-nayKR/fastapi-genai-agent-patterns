"""Mock transport tests validate the live adapter contract, never model quality."""

import json
from pathlib import Path

import httpx
import pytest

from agent_patterns.agents.runtime import AgentRuntime
from agent_patterns.config import Settings
from agent_patterns.providers.openai_provider import OpenAIProvider
from agent_patterns.schemas import AgentRunRequest
from tests.test_agents import LOG


@pytest.mark.asyncio
async def test_bounded_live_provider_calls_and_usage(tmp_path: Path) -> None:
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["max_tokens"] == 700
        context = json.loads(payload["messages"][1]["content"])
        hit = context["similar_incidents"][0]
        value = (
            {
                "hypotheses": [
                    {
                        "label": hit["root_cause_label"],
                        "explanation": hit["root_cause"],
                        "incident_ids": [hit["id"]],
                    }
                ],
                "abstain": False,
            }
            if len(calls) == 1
            else {
                "summary": hit["resolution"],
                "verification": "Load-test RSS",
                "risks": "Review required",
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(value)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            },
        )

    provider = OpenAIProvider(api_key="test", transport=httpx.MockTransport(handler))
    runtime = AgentRuntime(
        settings=Settings(
            provider_mode="openai",
            provider_api_key="test",
            ticket_database_path=str(tmp_path / "tickets.db"),
        ),
        provider=provider,
    )
    run = await runtime.start(AgentRunRequest(task=LOG), tenant_id="tenant-alpha")
    await runtime.close()
    assert run.status == "completed" and len(calls) == 2
    assert run.tokens_used == 300
    assert run.estimated_cost_usd == pytest.approx(0.003)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,content,error",
    [
        (429, "quota", "ProviderRateLimitError"),
        (401, "auth", "ProviderAuthenticationError"),
        (200, "invalid JSON", "ProviderMalformedOutputError"),
    ],
)
async def test_provider_failure_never_falls_back(status: int, content: str, error: str) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})

    provider = OpenAIProvider(api_key="test", max_retries=2, transport=httpx.MockTransport(handler))
    runtime = AgentRuntime(provider=provider)
    run = await runtime.start(AgentRunRequest(task=LOG), tenant_id="tenant-alpha")
    await runtime.close()
    assert run.status == "failed"
    assert run.steps == 3  # Failed provider execution still counts as a task step.
    assert error in (run.error_details or "")
    assert calls == (3 if status == 429 else 1)
    assert run.completed_agents == ["log_parser", "incident_retriever"]
