"""Opt-in contract test against an actual Redis 8 server."""

import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from agent_patterns.cache.redis_cache import RedisSemanticCache

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_redis_8_exact_semantic_and_eviction_contract() -> None:
    redis_url = os.getenv("TEST_REDIS_URL")
    if redis_url is None:
        pytest.skip("Set TEST_REDIS_URL to run the Redis 8 integration test")

    redis = Redis.from_url(redis_url, decode_responses=False)
    prefix = f"agent-cache-test-{uuid4().hex}"
    cache = RedisSemanticCache(redis, prefix=prefix)
    try:
        await cache.ensure_index()
        await cache.put(
            "support",
            "hashing",
            "How do I reset my password?",
            {"answer": "Open settings."},
        )

        exact = await cache.get("support", "hashing", "  HOW do I reset my password? ")
        semantic = await cache.get("support", "hashing", "How can I reset my password?")

        assert exact is not None
        assert exact.source == "exact"
        assert semantic is not None
        assert semantic.source == "semantic"
        assert semantic.distance <= cache.distance_threshold
        assert await cache.evict_exact(
            "support", "hashing", "How do I reset my password?"
        )
    finally:
        await cache.evict_namespace("support")
        await redis.aclose()
