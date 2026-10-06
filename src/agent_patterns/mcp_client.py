"""Official MCP client over stdio; one isolated server session per run/resume."""

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from opentelemetry import trace
from opentelemetry.trace import Tracer

from agent_patterns.config import Settings


class IncidentToolClient:
    def __init__(self, settings: Settings, secret: str, tracer: Tracer | None = None) -> None:
        self.settings = settings
        self.secret = secret
        self.tracer = tracer or trace.get_tracer(__name__)
        self.session: ContextVar[ClientSession] = ContextVar("incident_mcp_session")

    @asynccontextmanager
    async def connect(self, tenant: str) -> AsyncIterator[None]:
        # Do not pass provider keys or reviewer credentials into the tool subprocess.
        env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "SYSTEMROOT", "WINDIR", "PYTHONPATH"}
        }
        env.update(
            TRACEWARD_DATA=self.settings.incident_data_path,
            TRACEWARD_TICKETS=self.settings.ticket_database_path,
            TRACEWARD_TENANT=tenant,
            TRACEWARD_APPROVAL_SECRET=self.secret,
        )
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "agent_patterns.incident_tools"], env=env
        )
        failure: Exception | None = None
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                token = self.session.set(session)
                try:
                    yield
                except Exception as exc:
                    # Let SDK task groups close normally so domain errors keep their type.
                    failure = exc
                finally:
                    self.session.reset(token)
        if failure is not None:
            raise failure

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self.tracer.start_as_current_span(f"mcp.tool.{name}"):
            result = await self.session.get().call_tool(name, arguments)
            if result.isError:
                raise RuntimeError("MCP tool rejected request: " + str(result.content))
            if result.structuredContent is not None:
                return result.structuredContent
            for block in result.content:
                if block.type == "text":
                    return dict(json.loads(block.text))
            raise RuntimeError("MCP tool returned no structured result")
