"""OpenAPI stability tests for documented operations."""

from agent_patterns.app import create_app
from agent_patterns.config import Settings


def test_openapi_contains_stable_operation_ids() -> None:
    document = create_app(Settings(environment="test")).openapi()
    operations = {
        operation["operationId"]
        for path in document["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    }

    assert operations == {
        "getHealth",
        "getReadiness",
        "startAgentRun",
        "getAgentRun",
        "resumeAgentRun",
        "streamAgentRun",
        "putCacheEntry",
        "lookupCacheEntry",
        "evictCacheEntry",
        "evictCacheNamespace",
        "getCacheStats",
    }
    assert document["info"]["license"]["identifier"] == "MIT"


def test_openapi_documents_sse_and_error_responses() -> None:
    document = create_app(Settings(environment="test")).openapi()
    stream = document["paths"]["/api/v1/agents/runs/stream"]["post"]
    approval = document["paths"]["/api/v1/agents/runs/{thread_id}/approval"]["post"]
    lookup = document["paths"]["/api/v1/cache/lookup"]["post"]

    assert "text/event-stream" in stream["responses"]["200"]["content"]
    assert "409" in approval["responses"]
    assert "404" in lookup["responses"]
