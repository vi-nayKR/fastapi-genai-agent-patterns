"""Mock HTTP and orchestration checks; these are not live Gemini quality results."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from agent_patterns.config import Settings
from agent_patterns.providers.base import EvaluationBudget, ProviderBudgetError
from agent_patterns.providers.openai_provider import OpenAIProvider
from scripts import run_evaluation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model,effort", [("gemini-3.8-flash", "low"), ("gemini-2.5-flash", "none")]
)
async def test_gemini_pacing_backoff_cache_and_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model: str, effort: str
) -> None:
    calls = []
    sleeps = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        assert request.url.path == "/v1beta/openai/chat/completions"
        assert payload["temperature"] == 0.1 and payload["reasoning_effort"] == effort
        assert "seed" not in payload and payload["max_tokens"] == 700
        if len(calls) <= 2:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    monkeypatch.setattr(asyncio, "sleep", sleep)
    budget = EvaluationBudget(2.9)
    provider = OpenAIProvider(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key="secret-test-key",
        model=model,
        min_interval_seconds=12,
        retry_backoff_seconds=2,
        cache_dir=str(tmp_path),
        budget=budget,
        transport=httpx.MockTransport(handler),
    )
    prompt = [{"role": "user", "content": "log"}]
    first = await provider.generate(prompt, max_output_tokens=700)
    reserved = budget.reserved_usd
    second = await provider.generate(prompt, max_output_tokens=700)
    assert len(calls) == 3 and 2 in sleeps and 4 in sleeps
    assert provider.request_metrics["rate_limit_responses"] == 2
    assert provider.request_metrics["retries"] == 2
    assert provider.request_metrics["backoff_seconds"] == 6
    assert provider.request_metrics["cache_hits"] == 1
    assert any(delay > 11 for delay in sleeps)  # Retry attempts are paced too.
    assert not first.cached and second.cached and second.billed_cost_usd == 0
    assert budget.reserved_usd == reserved and reserved > 0
    cached = await asyncio.to_thread(lambda: next(tmp_path.glob("*.json")).read_text())
    assert "secret-test-key" not in cached and "run_date_utc" in cached
    budget.max_cost_usd = reserved
    with pytest.raises(ProviderBudgetError):
        await provider.generate([{"role": "user", "content": "different"}], max_output_tokens=700)
    assert len(calls) == 3 and not await asyncio.to_thread(lambda: list(tmp_path.glob("*.tmp")))
    await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "complete,projection,full", [(False, 0.1, False), (True, 4, False), (True, 0.1, True)]
)
async def test_live_runs_smoke_before_full_with_shared_budget(
    monkeypatch: pytest.MonkeyPatch, complete: bool, projection: float, full: bool
) -> None:
    invocations = []

    async def benchmark(settings: Settings, **kwargs: object) -> dict:
        invocations.append(kwargs)
        return {
            "projection_complete": complete,
            "projected_full_eval_cost_usd": projection,
            "summary": {
                "injection_pass_rate": 1,
                "unauthorized_persisted_tickets": 0,
                "approved_ticket_positive_control": True,
                "approval_replay_rejected": True,
            },
        }

    monkeypatch.setattr(run_evaluation, "run_benchmark", benchmark)
    monkeypatch.setattr(run_evaluation, "save_report", lambda *args: None)
    settings = Settings(provider_api_key="test", provider_judge_model="gemini-3.1-pro-preview")
    if full:
        await run_evaluation.evaluate(settings, True)
        assert invocations[0]["budget"] is invocations[1]["budget"]
    else:
        with pytest.raises(SystemExit):
            await run_evaluation.evaluate(settings, True)
    assert invocations[0]["smoke"] is True and len(invocations) == (2 if full else 1)


@pytest.mark.asyncio
async def test_live_preflight_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_call(*args: object, **kwargs: object) -> None:
        pytest.fail("No credentials must make no API calls")

    monkeypatch.setattr(run_evaluation, "run_benchmark", unexpected_call)
    with pytest.raises(SystemExit, match="No API calls made"):
        await run_evaluation.evaluate(Settings(provider_api_key=None), True)
