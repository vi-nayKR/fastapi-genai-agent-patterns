"""Keep local credentials and service URLs out of deterministic test runs."""

import os

from agent_patterns.config import Settings, get_settings


def pytest_configure() -> None:
    Settings.model_config["env_file"] = None
    os.environ["AGENT_PATTERNS_PROVIDER_MODE"] = "deterministic"
    os.environ.pop("AGENT_PATTERNS_PROVIDER_API_KEY", None)
    get_settings.cache_clear()
