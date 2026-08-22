"""HTTP routes for starting, streaming, inspecting, and resuming agent runs."""

from collections.abc import AsyncIterator
from typing import cast

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from agent_patterns.agents.runtime import (
    AgentRuntime,
    RunNotFoundError,
    RunNotPendingApprovalError,
)
from agent_patterns.schemas import AgentRunRequest, AgentRunResponse, ApprovalRequest

router = APIRouter(prefix="/agents", tags=["agents"])


def _runtime(request: Request) -> AgentRuntime:
    return cast(AgentRuntime, request.app.state.agent_runtime)


@router.post(
    "/runs",
    response_model=AgentRunResponse,
    operation_id="startAgentRun",
    summary="Start a checkpointed agent run",
)
async def start_run(body: AgentRunRequest, request: Request) -> AgentRunResponse:
    """Execute until completion or a durable human approval interrupt."""

    return await _runtime(request).start(body)


@router.get(
    "/runs/{thread_id}",
    response_model=AgentRunResponse,
    operation_id="getAgentRun",
    summary="Inspect a checkpointed agent run",
    responses={404: {"description": "Thread ID was not found"}},
)
async def get_run(thread_id: str, request: Request) -> AgentRunResponse:
    """Read the latest checkpointed run state."""

    try:
        return await _runtime(request).get(thread_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/runs/{thread_id}/approval",
    response_model=AgentRunResponse,
    operation_id="resumeAgentRun",
    summary="Resume a run with a human decision",
    responses={
        404: {"description": "Thread ID was not found"},
        409: {"description": "Run is not waiting for approval"},
    },
)
async def approve_run(
    thread_id: str,
    body: ApprovalRequest,
    request: Request,
) -> AgentRunResponse:
    """Resume a suspended graph with an explicit reviewer decision."""

    try:
        return await _runtime(request).resume(thread_id, body)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RunNotPendingApprovalError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/runs/stream",
    operation_id="streamAgentRun",
    summary="Stream an agent run as Server-Sent Events",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "SSE stream containing run_started, token, and terminal events",
            "content": {"text/event-stream": {}},
        }
    },
)
async def stream_run(body: AgentRunRequest, request: Request) -> StreamingResponse:
    """Stream worker tokens and the terminal checkpoint as SSE events."""

    async def event_source() -> AsyncIterator[str]:
        async for event in _runtime(request).stream(body):
            yield f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
