"""PostgreSQL-backed approval recovery and tenant-boundary test."""

import os

import pytest
from fastapi.testclient import TestClient

from agent_patterns.app import create_app
from agent_patterns.config import Settings


@pytest.mark.integration
def test_approval_survives_restart_is_tenant_scoped_and_replay_is_rejected() -> None:
    database_url = os.getenv("TEST_CHECKPOINT_DATABASE_URL")
    if not database_url:
        pytest.skip("set TEST_CHECKPOINT_DATABASE_URL to run PostgreSQL checkpoint tests")

    alpha = Settings(
        environment="staging",
        checkpoint_database_url=database_url,
        reviewer_api_key="alpha-token",
        reviewer_id="reviewer-alpha",
        tenant_id="tenant-alpha",
        cache_required=False,
    )
    beta = Settings(
        environment="staging",
        checkpoint_database_url=database_url,
        reviewer_api_key="beta-token",
        reviewer_id="reviewer-beta",
        tenant_id="tenant-beta",
        cache_required=False,
    )
    alpha_headers = {"Authorization": "Bearer alpha-token"}
    beta_headers = {"Authorization": "Bearer beta-token"}

    with TestClient(create_app(alpha), headers=alpha_headers) as first_process:
        started = first_process.post(
            "/api/v1/agents/runs",
            json={"task": "Deploy the payment API", "risk_level": "high"},
        )
        assert started.status_code == 200
        thread_id = started.json()["thread_id"]
        assert started.json()["status"] == "pending_approval"

    # A new application and checkpointer instance reads the pending checkpoint from PostgreSQL.
    with TestClient(create_app(alpha), headers=alpha_headers) as restarted_process:
        pending = restarted_process.get(f"/api/v1/agents/runs/{thread_id}")
        assert pending.status_code == 200
        assert pending.json()["status"] == "pending_approval"

    with TestClient(create_app(beta), headers=beta_headers) as other_tenant:
        assert other_tenant.get(f"/api/v1/agents/runs/{thread_id}").status_code == 404
        assert other_tenant.post(
            f"/api/v1/agents/runs/{thread_id}/approval", json={"approved": True}
        ).status_code == 404

    with TestClient(create_app(alpha), headers=alpha_headers) as reviewer:
        approved = reviewer.post(
            f"/api/v1/agents/runs/{thread_id}/approval",
            json={"approved": True, "feedback": "Authorized change window"},
        )
        replay = reviewer.post(
            f"/api/v1/agents/runs/{thread_id}/approval",
            json={"approved": True, "feedback": "Authorized change window"},
        )
        final = reviewer.get(f"/api/v1/agents/runs/{thread_id}")

    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"
    assert approved.json()["tenant_id"] == "tenant-alpha"
    assert approved.json()["audit_log"].count("approval:reviewer:reviewer-alpha") == 1
    assert replay.status_code == 409
    assert final.json()["audit_log"].count("approval:approved") == 1
