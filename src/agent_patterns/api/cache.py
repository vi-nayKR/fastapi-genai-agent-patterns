"""Operational API for the Redis semantic cache."""

from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response, status
from redis.exceptions import RedisError

from agent_patterns.cache import RedisSemanticCache
from agent_patterns.schemas import (
    CacheEvictionResponse,
    CacheLookupRequest,
    CacheLookupResponse,
    CachePutRequest,
    CacheStatsResponse,
)

router = APIRouter(prefix="/cache", tags=["cache"])


def _cache(request: Request) -> RedisSemanticCache:
    return cast(RedisSemanticCache, request.app.state.semantic_cache)


def _unavailable(exc: RedisError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Redis cache is unavailable",
    )


@router.post("/entries", status_code=status.HTTP_201_CREATED)
async def put_entry(body: CachePutRequest, request: Request) -> dict[str, str]:
    try:
        key = await _cache(request).put(body.namespace, body.model, body.prompt, body.response)
    except RedisError as exc:
        raise _unavailable(exc) from exc
    return {"key": key}


@router.post("/lookup", response_model=CacheLookupResponse)
async def lookup(
    body: CacheLookupRequest,
    request: Request,
    response: Response,
) -> CacheLookupResponse:
    try:
        hit = await _cache(request).get(body.namespace, body.model, body.prompt)
    except RedisError as exc:
        raise _unavailable(exc) from exc
    if hit is None:
        response.status_code = status.HTTP_404_NOT_FOUND
        return CacheLookupResponse(hit=False)
    return CacheLookupResponse(
        hit=True,
        source=hit.source,
        distance=hit.distance,
        matched_prompt=hit.matched_prompt,
        response=hit.response,
    )


@router.delete("/entries", response_model=CacheEvictionResponse)
async def evict_entry(body: CacheLookupRequest, request: Request) -> CacheEvictionResponse:
    try:
        deleted = await _cache(request).evict_exact(body.namespace, body.model, body.prompt)
    except RedisError as exc:
        raise _unavailable(exc) from exc
    return CacheEvictionResponse(deleted=int(deleted))


@router.delete("/namespaces/{namespace}", response_model=CacheEvictionResponse)
async def evict_namespace(
    namespace: str,
    request: Request,
    model: str | None = None,
) -> CacheEvictionResponse:
    try:
        deleted = await _cache(request).evict_namespace(namespace, model)
    except RedisError as exc:
        raise _unavailable(exc) from exc
    return CacheEvictionResponse(deleted=deleted)


@router.get("/stats", response_model=CacheStatsResponse)
async def cache_stats(request: Request) -> CacheStatsResponse:
    try:
        counters = await _cache(request).stats()
    except RedisError as exc:
        raise _unavailable(exc) from exc
    return CacheStatsResponse(**counters)
