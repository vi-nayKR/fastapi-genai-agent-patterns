"""Cross-day quota, cost persistence, and resumption without repeated agent calls."""

import sqlite3
from pathlib import Path

import httpx
import pytest

from agent_patterns.config import Settings
from agent_patterns.providers import quota
from agent_patterns.providers.base import EvaluationBudget, ProviderBudgetError, ProviderQuotaError
from agent_patterns.providers.openai_provider import OpenAIProvider
from evals import evaluator
from evals.progress import Progress


def test_rolling_model_quotas_survive_restart_and_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [100000.0]
    monkeypatch.setattr(quota.time, "time", lambda: now[0])
    path = str(tmp_path / "quota.sqlite3")
    q = quota.TokenQuota(path, "endpoint", "agent", 20, 50)
    first, _ = q.reserve(10)
    assert first is not None
    q.reserve(10)
    assert q.reserve(5) == (None, 60)
    q.settle(first, 2)
    assert q.reserve(5)[0] is not None
    assert quota.TokenQuota(path, "endpoint", "judge", 20, 50).reserve(20)[0] is not None
    now[0] += 61
    q = quota.TokenQuota(path, "endpoint", "agent", 20, 50)
    assert q.reserve(20)[0] is not None
    now[0] += 61
    with pytest.raises(ProviderQuotaError, match="Daily"):
        q.reserve(20)
    now[0] += 86400
    assert q.reserve(20)[0] is not None


def test_campaign_budget_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    EvaluationBudget(1, state_path=path).reserve(0.4)
    resumed = EvaluationBudget(1, state_path=path)
    assert resumed.reserved_usd == 0.4
    with pytest.raises(ProviderBudgetError):
        resumed.reserve(0.7)
    with pytest.raises(ProviderBudgetError):
        resumed.reserve(float("nan"))
    assert EvaluationBudget(1, state_path=path).reserved_usd == 0.4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model,effort", [("openai/gpt-oss-120b", "low"), ("qwen/qwen3.8-27b", "none")]
)
async def test_groq_payload_and_daily_pause(model: str, effort: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        assert payload["max_completion_tokens"] == 700
        assert payload["reasoning_effort"] == effort and "max_tokens" not in payload
        return httpx.Response(429, text="Rate limit reached on tokens per day (TPD)")

    provider = OpenAIProvider(
        base_url="https://api.groq.com/openai/v1",
        model=model,
        transport=httpx.MockTransport(handler),
        max_retries=3,
    )
    for _ in range(2):
        with pytest.raises(ProviderQuotaError):
            await provider.generate([{"role": "user", "content": "test"}], max_output_tokens=700)
    assert provider.request_metrics["http_attempts"] == 1
    await provider.close()


@pytest.mark.asyncio
async def test_unknown_generated_error_keeps_quota_reservation(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="json_validate_failed after generation")

    path = str(tmp_path / "quota.sqlite3")
    provider = OpenAIProvider(
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
        quota=quota.TokenQuota(path, "endpoint", "agent", 8000, 200000),
        transport=httpx.MockTransport(handler),
    )
    from agent_patterns.providers.base import ProviderError
    with pytest.raises(ProviderError):
        await provider.generate([{"role": "user", "content": "test"}], max_output_tokens=700)
    def reserved() -> int:
        with sqlite3.connect(path) as db:
            return db.execute("SELECT SUM(tokens) FROM reservations").fetchone()[0]
    import asyncio
    assert await asyncio.to_thread(reserved) == 832
    await provider.close()


@pytest.mark.asyncio
async def test_completed_case_checkpoint_skips_agent_calls_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "progress.json"
    report = await evaluator.run_benchmark(
        Settings(provider_mode="deterministic"), smoke=True, progress=Progress(path)
    )
    assert report["summary"]["completed_cases"] == 5

    async def unexpected_call(*args: object, **kwargs: object) -> None:
        pytest.fail("Completed cases must not call the agent on resume")

    monkeypatch.setattr(evaluator.AgentRuntime, "start", unexpected_call)
    resumed = await evaluator.run_benchmark(
        Settings(provider_mode="deterministic"), smoke=True, progress=Progress(path)
    )
    assert resumed["resumed_case_count"] == 5
    assert resumed["summary"] == report["summary"]
