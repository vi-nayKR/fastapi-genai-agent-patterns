"""Redis 8 exact and vector semantic cache implementation."""

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from agent_patterns.cache.embedding import HashingEmbedder, canonical_prompt

CacheSource = Literal["exact", "semantic"]


@dataclass(frozen=True, slots=True)
class CacheHit:
    """A decoded cache value and the lookup path that returned it."""

    response: Any
    source: CacheSource
    distance: float
    matched_prompt: str


class RedisSemanticCache:
    """Two-stage Redis cache with exact lookup before vector similarity search."""

    def __init__(
        self,
        redis: Redis,
        *,
        dimensions: int = 128,
        ttl_seconds: int = 3600,
        distance_threshold: float = 0.12,
        prefix: str = "agent-cache",
    ) -> None:
        self.redis = redis
        self.embedder = HashingEmbedder(dimensions)
        self.ttl_seconds = ttl_seconds
        self.distance_threshold = distance_threshold
        self.prefix = prefix

    @staticmethod
    def _digest(value: str, length: int = 32) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:length]

    def _entry_key(self, namespace: str, model: str, prompt: str) -> str:
        return ":".join(
            (
                self.prefix,
                "entry",
                self._digest(namespace, 16),
                self._digest(model, 16),
                self._digest(canonical_prompt(prompt)),
            )
        )

    def _lock_key(self, namespace: str, model: str, prompt: str) -> str:
        return f"{self.prefix}:lock:{self._entry_key(namespace, model, prompt)}"

    def _vector_key(self, namespace: str, model: str) -> str:
        return f"{self.prefix}:vectors:{self._digest(namespace, 16)}:{self._digest(model, 16)}"

    async def ensure_index(self) -> None:
        """Verify that the connected server provides Redis 8 vector sets."""

        command_info = await self.redis.execute_command(  # type: ignore[no-untyped-call]
            "COMMAND", "INFO", "VADD"
        )
        available = (
            any(str(name).casefold() == "vadd" for name in command_info)
            if isinstance(command_info, dict)
            else bool(command_info and command_info[0] is not None)
        )
        if not available:
            raise ResponseError("Redis 8 vector-set command VADD is unavailable")

    async def get(self, namespace: str, model: str, prompt: str) -> CacheHit | None:
        """Return an exact hit first, then try the vector index."""

        exact = await self.redis.hgetall(  # type: ignore[misc]
            self._entry_key(namespace, model, prompt)
        )
        if exact:
            await self._increment("exact_hits")
            return self._decode_hash(exact, "exact", 0.0)

        semantic = await self._semantic_get(namespace, model, prompt)
        if semantic is not None:
            await self._increment("semantic_hits")
            return semantic

        await self._increment("misses")
        return None

    async def put(self, namespace: str, model: str, prompt: str, response: Any) -> str:
        """Store one response as both an exact key and a vector-search document."""

        key = self._entry_key(namespace, model, prompt)
        mapping: dict[str, str | bytes] = {
            "namespace_id": self._digest(namespace, 16),
            "model_id": self._digest(model, 16),
            "prompt": prompt,
            "canonical_prompt": canonical_prompt(prompt),
            "response": json.dumps(response, separators=(",", ":"), ensure_ascii=True),
            "embedding": self.embedder.pack(prompt),
            "created_at": datetime.now(UTC).isoformat(),
        }
        await self.redis.hset(key, mapping=mapping)  # type: ignore[misc]
        await self.redis.expire(key, self.ttl_seconds)
        await self.redis.execute_command(  # type: ignore[no-untyped-call]
            "VADD",
            self._vector_key(namespace, model),
            "FP32",
            self.embedder.pack(prompt),
            self._digest(canonical_prompt(prompt)),
            "NOQUANT",
        )
        await self._increment("writes")
        return key

    async def get_or_compute(
        self,
        namespace: str,
        model: str,
        prompt: str,
        producer: Callable[[], Awaitable[Any]],
    ) -> CacheHit:
        """Prevent duplicate model work with a distributed per-prompt lock."""

        cached = await self.get(namespace, model, prompt)
        if cached is not None:
            return cached

        lock = self.redis.lock(
            self._lock_key(namespace, model, prompt),
            timeout=30,
            blocking_timeout=10,
        )
        async with lock:
            cached = await self.get(namespace, model, prompt)
            if cached is not None:
                return cached
            response = await producer()
            await self.put(namespace, model, prompt, response)
            return CacheHit(response=response, source="exact", distance=0.0, matched_prompt=prompt)

    async def evict_exact(self, namespace: str, model: str, prompt: str) -> bool:
        """Delete one canonical prompt entry in constant Redis key time."""

        deleted = await self.redis.delete(self._entry_key(namespace, model, prompt))
        await self.redis.execute_command(  # type: ignore[no-untyped-call]
            "VREM",
            self._vector_key(namespace, model),
            self._digest(canonical_prompt(prompt)),
        )
        if deleted:
            await self._increment("exact_evictions")
        return bool(deleted)

    async def evict_namespace(self, namespace: str, model: str | None = None) -> int:
        """Scan and delete entries in one namespace without blocking Redis."""

        namespace_id = self._digest(namespace, 16)
        model_pattern = self._digest(model, 16) if model is not None else "*"
        pattern = f"{self.prefix}:entry:{namespace_id}:{model_pattern}:*"
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await self.redis.scan(cursor=cursor, match=pattern, count=250)
            if keys:
                deleted += int(await self.redis.delete(*keys))
            if cursor == 0:
                break
        if deleted:
            await self._increment("namespace_evictions", deleted)
        if model is not None:
            await self.redis.delete(self._vector_key(namespace, model))
        else:
            vector_pattern = f"{self.prefix}:vectors:{namespace_id}:*"
            vector_cursor = 0
            while True:
                vector_cursor, vector_keys = await self.redis.scan(
                    cursor=vector_cursor, match=vector_pattern, count=250
                )
                if vector_keys:
                    await self.redis.delete(*vector_keys)
                if vector_cursor == 0:
                    break
        return deleted

    async def stats(self) -> dict[str, int]:
        """Read low-cardinality counters used by dashboards and tests."""

        names = (
            "exact_hits",
            "semantic_hits",
            "misses",
            "writes",
            "exact_evictions",
            "namespace_evictions",
        )
        values = await self.redis.mget([f"{self.prefix}:stats:{name}" for name in names])
        return {
            name: int(value) if value is not None else 0
            for name, value in zip(names, values, strict=True)
        }

    async def _semantic_get(
        self,
        namespace: str,
        model: str,
        prompt: str,
    ) -> CacheHit | None:
        raw = await self.redis.execute_command(  # type: ignore[no-untyped-call]
            "VSIM",
            self._vector_key(namespace, model),
            "FP32",
            self.embedder.pack(prompt),
            "WITHSCORES",
            "COUNT",
            1,
        )
        if not isinstance(raw, list) or len(raw) < 2:
            return None
        member = self._text(raw[0])
        distance = 1.0 - float(self._text(raw[1]))
        if distance > self.distance_threshold:
            return None
        key = ":".join(
            (
                self.prefix,
                "entry",
                self._digest(namespace, 16),
                self._digest(model, 16),
                member,
            )
        )
        entry = await self.redis.hgetall(key)  # type: ignore[misc]
        if not entry:
            await self.redis.execute_command(  # type: ignore[no-untyped-call]
                "VREM", self._vector_key(namespace, model), member
            )
            return None
        return self._decode_hash(entry, "semantic", distance)

    def _decode_hash(
        self,
        raw: dict[Any, Any],
        source: CacheSource,
        distance: float,
    ) -> CacheHit:
        decoded = {self._text(key): value for key, value in raw.items()}
        return CacheHit(
            response=json.loads(self._text(decoded["response"])),
            source=source,
            distance=distance,
            matched_prompt=self._text(decoded["prompt"]),
        )

    async def _increment(self, name: str, amount: int = 1) -> None:
        await self.redis.incrby(f"{self.prefix}:stats:{name}", amount)

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode()
        return str(value)
