"""Configuration contract tests."""

import pytest
from pydantic import ValidationError

from agent_patterns.config import Settings


def test_settings_are_immutable() -> None:
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.environment = "production"  # type: ignore[misc]


def test_settings_validate_cache_threshold() -> None:
    with pytest.raises(ValidationError):
        Settings(cache_semantic_distance_threshold=3.0)
