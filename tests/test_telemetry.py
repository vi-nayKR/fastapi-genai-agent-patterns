"""Trace coverage tests for HTTP, graph workers, and cache operations."""

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from redis.asyncio import Redis

from agent_patterns.agents.runtime import AgentRuntime
from agent_patterns.app import create_app
from agent_patterns.cache.redis_cache import RedisSemanticCache
from agent_patterns.config import Settings
from agent_patterns.providers.openai_provider import OpenAIProvider
from agent_patterns.schemas import AgentRunRequest
from tests.fakes import FakeRedis
from tests.test_agents import LOG


def provider_and_exporter() -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


@pytest.mark.asyncio
async def test_agent_run_contains_specialist_child_spans() -> None:
    provider, exporter = provider_and_exporter()
    runtime = AgentRuntime(provider.get_tracer("test"))

    result = await runtime.start(AgentRunRequest(task=LOG), tenant_id="tenant-alpha")

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert result.status == "completed"
    assert "agent.run" in spans
    assert "agent.worker.root_cause" in spans
    assert "agent.worker.fix_drafter" in spans
    assert "mcp.tool.get_log_context" in spans
    assert "mcp.tool.search_incidents" in spans
    assert (
        spans["mcp.tool.search_incidents"].parent.span_id
        == spans["agent.worker.incident_retriever"].context.span_id
    )
    assert spans["agent.worker.fix_drafter"].parent is not None
    assert spans["agent.worker.fix_drafter"].parent.span_id == spans["agent.run"].context.span_id
    provider.shutdown()


@pytest.mark.asyncio
async def test_approval_and_timeout_spans_report_their_actual_state() -> None:
    tracer_provider, exporter = provider_and_exporter()
    tracer = tracer_provider.get_tracer("test")
    runtime = AgentRuntime(tracer)
    pending = await runtime.start(
        AgentRunRequest(task=LOG, risk_level="high"),
        tenant_id="tenant-alpha",
    )
    await runtime.close()

    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    openai_provider = OpenAIProvider(
        api_key="test-key",
        max_retries=0,
        tracer=tracer,
        transport=httpx.MockTransport(timeout),
    )
    failing_runtime = AgentRuntime(tracer, provider=openai_provider)
    failed = await failing_runtime.start(
        AgentRunRequest(task=LOG, risk_level="high"),
        tenant_id="tenant-alpha",
    )
    await failing_runtime.close()

    spans = exporter.get_finished_spans()
    pending_span = next(span for span in spans if span.name == "agent.run")
    error_span = next(
        span
        for span in spans
        if span.name == "provider.chat.completions" and span.status.status_code.name == "ERROR"
    )
    assert pending.status == "pending_approval"
    assert pending_span.attributes["agent.approval_required"] is True
    assert failed.status == "failed"
    assert error_span.status.status_code.name == "ERROR"
    tracer_provider.shutdown()


@pytest.mark.asyncio
async def test_cache_spans_record_hit_source_without_prompt() -> None:
    provider, exporter = provider_and_exporter()
    fake = FakeRedis()
    cache = RedisSemanticCache(cast(Redis, fake), tracer=provider.get_tracer("test"))
    await cache.put("tenant", "model", "sensitive prompt", {"answer": "safe"})

    hit = await cache.get("tenant", "model", "sensitive prompt")

    lookup = next(span for span in exporter.get_finished_spans() if span.name == "cache.lookup")
    attributes = dict(lookup.attributes or {})
    assert hit is not None
    assert attributes["cache.hit"] is True
    assert attributes["cache.source"] == "exact"
    assert "sensitive prompt" not in repr(attributes)
    provider.shutdown()


def test_fastapi_emits_server_span() -> None:
    exporter = InMemorySpanExporter()
    app = create_app(Settings(environment="test"), span_exporter=exporter)

    with TestClient(app) as test_client:
        response = test_client.get("/health")

    spans = exporter.get_finished_spans()
    assert response.status_code == 200
    assert any(span.kind.name == "SERVER" and "/health" in span.name for span in spans)
