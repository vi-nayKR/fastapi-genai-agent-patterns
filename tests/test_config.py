"""Configuration contract tests."""

import pytest
from pydantic import ValidationError

from agent_patterns.config import Settings


def test_settings_are_immutable() -> None:
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.environment = "production"



def test_settings_validate_cache_threshold() -> None:
    with pytest.raises(ValidationError):
        Settings(cache_semantic_distance_threshold=3.0)
    with pytest.raises(ValidationError, match="cover both agent token rates"):
        Settings(token_price_usd_per_million=1, provider_output_usd_per_million=2)


def test_deployment_settings_require_persistent_checkpoints_and_nonempty_reviewer_key() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")
    with pytest.raises(ValidationError):
        Settings(
            environment="staging",
            checkpoint_database_url="postgresql://localhost/agents",
            reviewer_api_key="",
        )
    settings = Settings(
        environment="staging",
        checkpoint_database_url="postgresql://localhost/agents",
        reviewer_api_key="test-token",
    )
    assert settings.reviewer_api_key is not None
