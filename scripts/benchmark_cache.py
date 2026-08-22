"""Measure Redis exact lookup and eviction latency against a running Redis 8."""

import argparse
import asyncio
import statistics
import time
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

from agent_patterns.cache.redis_cache import RedisSemanticCache


def percentile(samples: list[float], percentage: float) -> float:
    ordered = sorted(samples)
    index = min(round((len(ordered) - 1) * percentage), len(ordered) - 1)
    return ordered[index]


async def timed(operation: Callable[[], Awaitable[object]]) -> float:
    started = time.perf_counter_ns()
    await operation()
    return (time.perf_counter_ns() - started) / 1_000_000


async def benchmark(redis_url: str, iterations: int, target_ms: float) -> int:
    redis = Redis.from_url(redis_url, decode_responses=False)
    cache = RedisSemanticCache(redis, prefix="agent-cache-benchmark")
    try:
        await redis.ping()
        await cache.ensure_index()
        prompt = "What is the approved deployment procedure?"
        response = {"answer": "Use the change-management runbook."}
        await cache.put("benchmark", "deterministic", prompt, response)

        lookup_samples = [
            await timed(lambda: cache.get("benchmark", "deterministic", prompt))
            for _ in range(iterations)
        ]
        eviction_samples: list[float] = []
        for _ in range(iterations):
            await cache.put("benchmark", "deterministic", prompt, response)
            eviction_samples.append(
                await timed(lambda: cache.evict_exact("benchmark", "deterministic", prompt))
            )

        lookup_p95 = percentile(lookup_samples, 0.95)
        eviction_p95 = percentile(eviction_samples, 0.95)
        print(f"iterations={iterations}")
        print(f"exact_lookup_p50_ms={statistics.median(lookup_samples):.3f}")
        print(f"exact_lookup_p95_ms={lookup_p95:.3f}")
        print(f"exact_eviction_p50_ms={statistics.median(eviction_samples):.3f}")
        print(f"exact_eviction_p95_ms={eviction_p95:.3f}")
        print(f"target_ms={target_ms:.3f}")
        return int(lookup_p95 >= target_ms or eviction_p95 >= target_ms)
    finally:
        await redis.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--target-ms", type=float, default=5.0)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(benchmark(args.redis_url, args.iterations, args.target_ms)))


if __name__ == "__main__":
    main()
