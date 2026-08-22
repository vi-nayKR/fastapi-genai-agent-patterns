"""Exact, semantic, invalidation, and stampede cache tests."""

from typing import Any, cast

import pytest
from redis.asyncio import Redis

from agent_patterns.cache.embedding import HashingEmbedder, canonical_prompt
from agent_patterns.cache.redis_cache import RedisSemanticCache
from tests.fakes import FakeRedis


def cache_with_fake() -> tuple[RedisSemanticCache, FakeRedis]:
    fake = FakeRedis()
    return RedisSemanticCache(cast(Redis, fake), distance_threshold=0.3), fake


def test_prompt_canonicalization_and_embedding_are_deterministic() -> None:
    assert canonical_prompt("  RESET   My Password  ") == "reset my password"
    embedder = HashingEmbedder(64)
    first = embedder.embed("How do I reset my password?")
    second = embedder.embed("How do I reset my password?")
    assert first == second
    assert sum(value * value for value in first) == pytest.approx(1.0)
    assert len(embedder.pack("hello")) == 64 * 4


@pytest.mark.asyncio
async def test_exact_round_trip_and_eviction() -> None:
    cache, _ = cache_with_fake()
    await cache.put("support", "model-a", "Reset my password", {"answer": "Use settings"})

    hit = await cache.get("support", "model-a", "  reset MY   password ")
    deleted = await cache.evict_exact("support", "model-a", "reset my password")
    missing = await cache.get("support", "model-a", "reset my password")

    assert hit is not None
    assert hit.source == "exact"
    assert hit.response == {"answer": "Use settings"}
    assert deleted is True
    assert missing is None


@pytest.mark.asyncio
async def test_semantic_result_respects_distance_threshold() -> None:
    cache, fake = cache_with_fake()
    reference_prompt = "How do I reset my password?"
    await cache.put("support", "model-a", reference_prompt, {"answer": "Use settings"})
    member = cache._digest(canonical_prompt(reference_prompt))
    fake.search_response = [member.encode(), b"0.86"]

    hit = await cache.get("support", "model-a", "Can I reset the password?")

    assert hit is not None
    assert hit.source == "semantic"
    assert hit.distance == pytest.approx(0.14)


@pytest.mark.asyncio
async def test_namespace_eviction_is_scoped() -> None:
    cache, fake = cache_with_fake()
    await cache.put("tenant-a", "model-a", "first", 1)
    await cache.put("tenant-a", "model-a", "second", 2)
    await cache.put("tenant-b", "model-a", "third", 3)

    deleted = await cache.evict_namespace("tenant-a")

    assert deleted == 2
    assert len(fake.hashes) == 1


@pytest.mark.asyncio
async def test_get_or_compute_stores_producer_result() -> None:
    cache, _ = cache_with_fake()
    calls = 0

    async def producer() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"generated": True}

    first = await cache.get_or_compute("tenant", "model", "prompt", producer)
    second = await cache.get_or_compute("tenant", "model", "prompt", producer)

    assert first.response == {"generated": True}
    assert second.source == "exact"
    assert calls == 1
