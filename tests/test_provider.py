"""Unit tests for the OpenAI-compatible async provider adapter."""

import json
from typing import Any

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_patterns.providers.base import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderMalformedOutputError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from agent_patterns.providers.openai_provider import OpenAIProvider
from agent_patterns.schemas import ResearchFinding


def _chat_completion_payload(content: str, model: str = "gpt-4o-mini") -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 20,
            "total_tokens": 32,
        },
    }


@pytest.mark.asyncio
async def test_provider_generates_response_with_tokens() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = _chat_completion_payload("Verified response text")
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    provider = OpenAIProvider(
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        transport=transport,
    )

    response = await provider.generate([{"role": "user", "content": "Test prompt"}])
    assert response.content == "Verified response text"
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 20
    assert response.usage.total_tokens == 32
    assert response.model == "gpt-4o-mini"
    await provider.close()


@pytest.mark.asyncio
async def test_provider_validates_structured_schema() -> None:
    expected_data = {
        "summary": "Tenant policy verified",
        "citations": ["SEC-001"],
        "confidence": "high",
        "abstain": False,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json=_chat_completion_payload(json.dumps(expected_data)))

    provider = OpenAIProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    response = await provider.generate(
        [{"role": "user", "content": "Verify policy"}],
        response_schema=ResearchFinding,
    )
    assert isinstance(response.structured, ResearchFinding)
    assert response.structured.summary == "Tenant policy verified"
    assert response.structured.citations == ["SEC-001"]
    assert response.structured.confidence == "high"
    await provider.close()


@pytest.mark.asyncio
async def test_provider_raises_on_malformed_structured_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        # Return invalid JSON when structured output was requested
        return httpx.Response(200, json=_chat_completion_payload("Not valid JSON"))

    provider = OpenAIProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderMalformedOutputError) as exc_info:
        await provider.generate(
            [{"role": "user", "content": "Get finding"}],
            response_schema=ResearchFinding,
        )
    assert "Failed to validate output against ResearchFinding" in str(exc_info.value)
    await provider.close()


@pytest.mark.asyncio
async def test_provider_retries_transient_429_with_retry_after() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0.01"},
                text="Rate limit exceeded",
            )
        return httpx.Response(200, json=_chat_completion_payload("Recovered after retry"))

    provider = OpenAIProvider(
        api_key="test-key",
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )

    response = await provider.generate([{"role": "user", "content": "Retryable request"}])
    assert response.content == "Recovered after retry"
    assert attempts == 2
    await provider.close()


@pytest.mark.asyncio
async def test_provider_fails_when_429_retries_exhausted() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(429, text="Rate limit quota exceeded")

    provider = OpenAIProvider(
        api_key="test-key",
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderRateLimitError) as exc_info:
        await provider.generate([{"role": "user", "content": "Exhaust retries"}])
    assert exc_info.value.status_code == 429
    await provider.close()


@pytest.mark.asyncio
async def test_provider_fails_fast_on_401_without_retrying() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, text="Invalid API key")

    provider = OpenAIProvider(
        api_key="invalid-key",
        max_retries=3,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderAuthenticationError):
        await provider.generate([{"role": "user", "content": "Auth test"}])
    # Must fail immediately on attempt 1 without wastefully retrying
    assert attempts == 1
    await provider.close()


@pytest.mark.asyncio
async def test_provider_fails_fast_on_400() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, text="Bad request")

    provider = OpenAIProvider(
        api_key="key",
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderError) as exc_info:
        await provider.generate([{"role": "user", "content": "Bad request test"}])
    assert exc_info.value.status_code == 400
    assert attempts == 1
    await provider.close()


@pytest.mark.asyncio
async def test_provider_retries_500_and_succeeds() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(200, json=_chat_completion_payload("Recovered from 500"))

    provider = OpenAIProvider(
        api_key="key",
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )

    response = await provider.generate([{"role": "user", "content": "500 recovery test"}])
    assert response.content == "Recovered from 500"
    assert attempts == 2
    await provider.close()


@pytest.mark.asyncio
async def test_provider_handles_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ReadTimeout("Read timed out")

    provider = OpenAIProvider(
        api_key="key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTimeoutError):
        await provider.generate([{"role": "user", "content": "Timeout test"}])
    await provider.close()


@pytest.mark.asyncio
async def test_provider_streams_tokens() -> None:
    sse_body = (
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=sse_body.encode(),
        )

    provider = OpenAIProvider(
        api_key="key",
        transport=httpx.MockTransport(handler),
    )

    tokens: list[str] = []
    async for token in provider.stream([{"role": "user", "content": "Stream test"}]):
        tokens.append(token)

    assert tokens == ["Hello", " world"]
    await provider.close()


@pytest.mark.asyncio
async def test_provider_records_telemetry_span_and_token_attributes() -> None:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = tracer_provider.get_tracer("test")

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=_chat_completion_payload("Traced output"))

    provider = OpenAIProvider(
        api_key="key",
        tracer=tracer,
        transport=httpx.MockTransport(handler),
    )

    await provider.generate([{"role": "user", "content": "Traced prompt"}])

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert "provider.chat.completions" in spans
    span = spans["provider.chat.completions"]
    attrs = dict(span.attributes or {})
    assert attrs["provider.name"] == "openai"
    assert attrs["provider.model"] == "gpt-4o-mini"
    assert attrs["llm.usage.prompt_tokens"] == 12
    assert attrs["llm.usage.completion_tokens"] == 20
    assert attrs["llm.usage.total_tokens"] == 32
    assert attrs["provider.status"] == "success"

    await provider.close()
    tracer_provider.shutdown()
