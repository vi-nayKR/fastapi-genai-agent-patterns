"""Liveness and readiness routes."""

from fastapi import APIRouter, Request

from agent_patterns import __version__
from agent_patterns.config import Settings
from agent_patterns.schemas import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Report process liveness without calling downstream dependencies."""

    settings: Settings = request.app.state.settings
    return HealthResponse(
        service=settings.service_name,
        version=__version__,
        environment=settings.environment,
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness() -> ReadinessResponse:
    """Report whether the foundation is ready to accept traffic."""

    return ReadinessResponse(checks={"api": "up"})
