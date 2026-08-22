"""ASGI entry point used by Uvicorn."""

from agent_patterns.app import create_app

app = create_app()
