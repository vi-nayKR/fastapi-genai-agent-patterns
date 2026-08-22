"""FastAPI application factory."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import Response
from opentelemetry.sdk.trace.export import SpanExporter
from redis.asyncio import Redis

from agent_patterns import __version__
from agent_patterns.agents import AgentRuntime
from agent_patterns.api.agents import router as agents_router
from agent_patterns.api.cache import router as cache_router
from agent_patterns.api.health import router as health_router
from agent_patterns.cache import RedisSemanticCache
from agent_patterns.config import Settings, get_settings
from agent_patterns.telemetry import create_tracer_provider, instrument_fastapi


def create_app(
    settings: Settings | None = None,
    span_exporter: SpanExporter | None = None,
) -> FastAPI:
    """Build an isolated application instance for production or tests."""

    resolved_settings = settings or get_settings()
    tracer_provider = create_tracer_provider(resolved_settings, span_exporter)
    tracer = tracer_provider.get_tracer("agent_patterns")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = resolved_settings
        app.state.agent_runtime = AgentRuntime(tracer)
        redis = Redis.from_url(
            resolved_settings.redis_url,
            decode_responses=False,
            socket_connect_timeout=resolved_settings.dependency_timeout_seconds,
            socket_timeout=resolved_settings.dependency_timeout_seconds,
        )
        app.state.redis = redis
        app.state.semantic_cache = RedisSemanticCache(
            redis,
            dimensions=resolved_settings.cache_vector_dimensions,
            ttl_seconds=resolved_settings.cache_ttl_seconds,
            distance_threshold=resolved_settings.cache_semantic_distance_threshold,
            tracer=tracer,
        )
        try:
            yield
        finally:
            await redis.aclose()
            tracer_provider.shutdown()

    app = FastAPI(
        title="FastAPI and LangGraph Production Agent Patterns",
        version=__version__,
        description="Reference implementation for stateful and observable agent services.",
        contact={
            "name": "Vinay K R",
            "url": "https://portfolio.vinaykr.workers.dev/",
        },
        license_info={"name": "MIT", "identifier": "MIT"},
        openapi_tags=[
            {"name": "health", "description": "Process and dependency health probes."},
            {
                "name": "agents",
                "description": "Stateful execution, streaming, inspection, and approval resume.",
            },
            {
                "name": "cache",
                "description": "Redis 8 exact and semantic cache operations.",
            },
        ],
        servers=[{"url": "/", "description": "Current deployment"}],
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    app.include_router(health_router)
    app.include_router(agents_router, prefix=resolved_settings.api_prefix)
    app.include_router(cache_router, prefix=resolved_settings.api_prefix)
    instrument_fastapi(app, tracer_provider)
    return app
