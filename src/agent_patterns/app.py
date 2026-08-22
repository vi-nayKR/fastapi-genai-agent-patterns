"""FastAPI application factory."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import Response

from agent_patterns import __version__
from agent_patterns.api.health import router as health_router
from agent_patterns.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an isolated application instance for production or tests."""

    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = resolved_settings
        yield

    app = FastAPI(
        title="FastAPI and LangGraph Production Agent Patterns",
        version=__version__,
        description="Reference implementation for stateful and observable agent services.",
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
    return app
