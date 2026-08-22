"""Agent supervisor, checkpoint, approval, and streaming contract tests."""

import json

from fastapi.testclient import TestClient

from agent_patterns.app import create_app
from agent_patterns.config import Settings


def client() -> TestClient:
    return TestClient(create_app(Settings(environment="test")))


def test_supervisor_delegates_to_relevant_workers() -> None:
    with client() as test_client:
        response = test_client.post(
            "/api/v1/agents/runs",
            json={"task": "Implement and test a Python API"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["completed_agents"] == ["research", "coding"]
    assert "Research summary" in body["result"]
    assert "Implementation plan" in body["result"]


def test_high_risk_run_interrupts_and_resumes() -> None:
    with client() as test_client:
        started = test_client.post(
            "/api/v1/agents/runs",
            json={"task": "Deploy a payment API", "risk_level": "high"},
        )
        thread_id = started.json()["thread_id"]
        inspected = test_client.get(f"/api/v1/agents/runs/{thread_id}")
        resumed = test_client.post(
            f"/api/v1/agents/runs/{thread_id}/approval",
            json={"approved": True, "feedback": "Change window confirmed"},
        )

    assert started.json()["status"] == "pending_approval"
    assert started.json()["approval"]["risk_level"] == "high"
    assert inspected.json() == started.json()
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["completed_agents"] == ["research", "coding", "compliance"]
    assert "approval:approved" in resumed.json()["audit_log"]


def test_reviewer_can_reject_run() -> None:
    with client() as test_client:
        started = test_client.post(
            "/api/v1/agents/runs",
            json={"task": "Research retention policy", "require_approval": True},
        )
        thread_id = started.json()["thread_id"]
        rejected = test_client.post(
            f"/api/v1/agents/runs/{thread_id}/approval",
            json={"approved": False, "feedback": "Scope is too broad."},
        )

    assert rejected.json()["status"] == "rejected"
    assert "Scope is too broad." in rejected.json()["result"]


def test_completed_run_cannot_be_resumed() -> None:
    with client() as test_client:
        started = test_client.post(
            "/api/v1/agents/runs",
            json={"task": "Research a stable API"},
        )
        response = test_client.post(
            f"/api/v1/agents/runs/{started.json()['thread_id']}/approval",
            json={"approved": True},
        )

    assert response.status_code == 409


def test_stream_emits_tokens_and_terminal_state() -> None:
    with client() as test_client:
        with test_client.stream(
            "POST",
            "/api/v1/agents/runs/stream",
            json={"task": "Implement a Python test"},
        ) as response:
            lines = [line for line in response.iter_lines() if line.startswith("data: ")]

    events = [json.loads(line.removeprefix("data: ")) for line in lines]
    assert response.status_code == 200
    assert events[0]["type"] == "run_started"
    assert any(event["type"] == "token" and event["agent"] == "coding" for event in events)
    assert events[-1]["type"] == "completed"
    assert events[-1]["run"]["status"] == "completed"
