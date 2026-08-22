"""Trace coverage tests for HTTP, graph workers, and cache operations."""

from typing import cast

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
from agent_patterns.schemas import AgentRunRequest
from tests.fakes import FakeRedis


def provider_and_exporter() -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


@pytest.mark.asyncio
async def test_agent_run_contains_specialist_child_spans() -> None:
    provider, exporter = provider_and_exporter()
    runtime = AgentRuntime(provider.get_tracer("test"))

    result = await runtime.start(AgentRunRequest(task="Implement a Python API test"))

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert result.status == "completed"
    assert "agent.run" in spans
    assert "agent.worker.research" in spans
    assert "agent.worker.coding" in spans
    assert spans["agent.worker.coding"].parent is not None
    assert spans["agent.worker.coding"].parent.span_id == spans["agent.run"].context.span_id
    provider.shutdown()


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
