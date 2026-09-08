"""End-to-end tests for real provider mode, structured outputs, and explicit failure handling."""

import json
from typing import Any

import httpx
from fastapi.testclient import TestClient

from agent_patterns.app import create_app
from agent_patterns.config import Settings
from agent_patterns.providers.openai_provider import OpenAIProvider


def _mock_chat_response(content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 25,
            "total_tokens": 40,
        },
    }


def test_real_provider_produces_structured_outputs() -> None:
    """Verify that in real provider mode, specialists emit schema-valid structured outputs."""
    research_json = json.dumps(
        {
            "summary": "Retrieved RFC-8792 and customer SLA policy.",
            "citations": ["RFC-8792", "SLA-POLICY-1.0"],
            "confidence": "high",
            "abstain": False,
        }
    )
    coding_json = json.dumps(
        {
            "summary": "Generated typed API endpoint with bounded retries.",
            "action_type": "ticket_update",
            "target_resource": "SERVICE-CORE",
            "parameters": {"endpoint": "/v1/tickets"},
            "is_mutation": True,
        }
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        messages_text = str(body["messages"])
        if "research specialist" in messages_text:
            return httpx.Response(200, json=_mock_chat_response(research_json))
        return httpx.Response(200, json=_mock_chat_response(coding_json))

    custom_provider = OpenAIProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    settings = Settings(
        environment="test",
        provider_mode="openai",
        provider_api_key="test-key",
    )
    app = create_app(settings, provider=custom_provider)

    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/agents/runs",
            json={"task": "Implement and test an authenticated API"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["completed_agents"] == ["research", "coding"]
    assert "RFC-8792" in data["result"]
    assert "SERVICE-CORE" in data["result"]

    # Verify structured outputs are properly validated and populated
    structured = data["structured_result"]
    assert structured is not None
    assert structured["research"]["citations"] == ["RFC-8792", "SLA-POLICY-1.0"]
    assert structured["research"]["confidence"] == "high"
    assert structured["action"]["action_type"] == "ticket_update"
    assert structured["action"]["is_mutation"] is True
    assert structured["tokens_used"] > 0


def test_real_provider_failure_does_not_silently_fallback() -> None:
    """Verify that when a real provider returns an error (e.g. 429), the service

    fails explicitly and does NOT silently return canned mock outputs.
    """
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(429, text="Rate limit quota exceeded")

    failing_provider = OpenAIProvider(
        api_key="test-key",
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    settings = Settings(
        environment="test",
        provider_mode="openai",
        provider_api_key="test-key",
    )
    app = create_app(settings, provider=failing_provider)

    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/agents/runs",
            json={"task": "Implement a critical database change"},
        )

    assert response.status_code == 200
    data = response.json()
    # The run must be marked failed
    assert data["status"] == "failed"
    assert "Provider failure (ProviderRateLimitError) in research worker" in data["result"]
    assert "ProviderRateLimitError" in data["error_details"]
    assert any("failed:ProviderRateLimitError" in log for log in data["audit_log"])
    assert "run:failed" in data["audit_log"]

    # Crucial assertion: it did NOT silently fall back to canned mock text!
    assert "Research summary: identify authoritative sources" not in (data["result"] or "")


def test_real_provider_auth_failure_fails_fast() -> None:
    """Verify that a 401 Authentication failure stops execution immediately with explicit error."""
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(401, text="Incorrect API key provided")

    auth_failing_provider = OpenAIProvider(
        api_key="bad-key",
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )

    settings = Settings(
        environment="test",
        provider_mode="openai",
        provider_api_key="bad-key",
    )
    app = create_app(settings, provider=auth_failing_provider)

    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/agents/runs",
            json={"task": "Implement an authorized function"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert "ProviderAuthenticationError" in data["error_details"]
    assert any("failed:ProviderAuthenticationError" in log for log in data["audit_log"])


def test_real_provider_malformed_json_fails_explicitly() -> None:
    """Verify that unparseable model output triggers ProviderMalformedOutputError and fails run."""
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        # Return plain text instead of JSON schema
        return httpx.Response(200, json=_mock_chat_response("I am a helpful assistant."))

    malformed_provider = OpenAIProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    settings = Settings(
        environment="test",
        provider_mode="openai",
        provider_api_key="test-key",
    )
    app = create_app(settings, provider=malformed_provider)

    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/agents/runs",
            json={"task": "Research compliance policy"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert "ProviderMalformedOutputError" in data["error_details"]
    assert any("failed:ProviderMalformedOutputError" in log for log in data["audit_log"])


def test_real_provider_streaming_emits_tokens_and_structured_terminal() -> None:
    """Verify that streaming in real provider mode emits worker tokens and terminal event."""
    research_json = json.dumps(
        {
            "summary": "Documented authoritative security requirements.",
            "citations": ["NIST-800-53"],
            "confidence": "high",
            "abstain": False,
        }
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=_mock_chat_response(research_json))

    custom_provider = OpenAIProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    settings = Settings(
        environment="test",
        provider_mode="openai",
        provider_api_key="test-key",
    )
    app = create_app(settings, provider=custom_provider)

    with TestClient(app) as test_client:
        with test_client.stream(
            "POST",
            "/api/v1/agents/runs/stream",
            json={"task": "Research retention security rules"},
        ) as response:
            lines = [line for line in response.iter_lines() if line.startswith("data: ")]

    events = [json.loads(line.removeprefix("data: ")) for line in lines]
    assert response.status_code == 200
    assert events[0]["type"] == "run_started"
    assert any(event["type"] == "token" and event["agent"] == "research" for event in events)
    assert events[-1]["type"] == "completed"
    terminal_run = events[-1]["run"]
    assert terminal_run["status"] == "completed"
    assert terminal_run["structured_result"]["research"]["citations"] == ["NIST-800-53"]
