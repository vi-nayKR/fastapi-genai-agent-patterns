"""Liveness and dependency-aware readiness routes."""

import asyncio
from typing import Literal, cast

from fastapi import APIRouter, Request, Response, status
from redis.exceptions import RedisError

from agent_patterns import __version__
from agent_patterns.cache import RedisSemanticCache
from agent_patterns.config import Settings
from agent_patterns.schemas import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    operation_id="getHealth",
    summary="Check process liveness",
)
async def health(request: Request) -> HealthResponse:
    """Report process liveness without calling downstream dependencies."""

    settings: Settings = request.app.state.settings
    return HealthResponse(
        service=settings.service_name,
        version=__version__,
        environment=settings.environment,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    operation_id="getReadiness",
    summary="Check dependency readiness",
    responses={503: {"description": "A required dependency is degraded"}},
)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    """Verify Redis connectivity and native vector-set support."""

    settings: Settings = request.app.state.settings
    cache = cast(RedisSemanticCache, request.app.state.semantic_cache)
    redis_status: Literal["up", "degraded"] = "up"
    try:
        async with asyncio.timeout(settings.dependency_timeout_seconds):
            await cache.redis.ping()  # type: ignore[misc]
            await cache.ensure_index()
    except (RedisError, TimeoutError):
        redis_status = "degraded"

    ready = redis_status == "up" or not settings.cache_required
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "degraded",
        checks={"api": "up", "redis": redis_status},
    )
