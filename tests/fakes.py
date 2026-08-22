"""Small asynchronous Redis test double for cache unit tests."""

from collections.abc import Iterable
from fnmatch import fnmatch
from types import TracebackType
from typing import Any, Self


class FakeLock:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str | bytes, str | bytes]] = {}
        self.counters: dict[str, int] = {}
        self.search_response: list[Any] = [0]

    async def hgetall(self, key: str) -> dict[str | bytes, str | bytes]:
        return self.hashes.get(key, {})

    async def hset(self, key: str, mapping: dict[str, str | bytes]) -> int:
        self.hashes[key] = mapping
        return len(mapping)

    async def expire(self, key: str, ttl: int) -> bool:
        return key in self.hashes and ttl > 0

    async def delete(self, *keys: str | bytes) -> int:
        deleted = 0
        for raw_key in keys:
            key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            deleted += int(self.hashes.pop(key, None) is not None)
        return deleted

    async def scan(
        self,
        cursor: int = 0,
        match: str | None = None,
        count: int | None = None,
    ) -> tuple[int, list[str]]:
        del cursor, count
        return 0, [key for key in self.hashes if match is None or fnmatch(key, match)]

    async def incrby(self, key: str, amount: int = 1) -> int:
        self.counters[key] = self.counters.get(key, 0) + amount
        return self.counters[key]

    async def mget(self, keys: Iterable[str]) -> list[int | None]:
        return [self.counters.get(key) for key in keys]

    async def execute_command(self, *_args: Any) -> list[Any]:
        return self.search_response

    def lock(self, *_args: Any, **_kwargs: Any) -> FakeLock:
        return FakeLock()
