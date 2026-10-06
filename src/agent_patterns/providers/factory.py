"""Provider factory constructing adapters from runtime settings."""

import httpx
from opentelemetry.trace import Tracer

from agent_patterns.config import Settings
from agent_patterns.providers.base import EvaluationBudget, LLMProvider
from agent_patterns.providers.deterministic_provider import DeterministicProvider
from agent_patterns.providers.openai_provider import OpenAIProvider
from agent_patterns.providers.quota import TokenQuota


def create_provider(
    settings: Settings,
    tracer: Tracer | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    budget: EvaluationBudget | None = None,
) -> LLMProvider:
    """Instantiate the configured model provider adapter."""
    if settings.provider_mode == "openai":
        if not settings.provider_api_key and "api.openai.com" in settings.provider_base_url:
            raise ValueError(
                "AGENT_PATTERNS_PROVIDER_API_KEY must be set when "
                "AGENT_PATTERNS_PROVIDER_MODE='openai' with api.openai.com"
            )
        return OpenAIProvider(
            base_url=settings.provider_base_url,
            api_key=settings.provider_api_key,
            model=settings.provider_model,
            timeout_seconds=settings.provider_timeout_seconds,
            max_retries=settings.provider_max_retries,
            tracer=tracer,
            transport=transport,
            temperature=settings.provider_temperature,
            seed=settings.provider_seed if settings.provider_seed_supported else None,
            cache_dir=settings.provider_cache_dir,
            budget=budget,
            input_usd_per_million=settings.provider_input_usd_per_million,
            output_usd_per_million=settings.provider_output_usd_per_million,
            min_interval_seconds=settings.provider_min_interval_seconds,
            retry_backoff_seconds=settings.provider_retry_backoff_seconds,
            quota=TokenQuota(
                settings.provider_quota_database,
                settings.provider_base_url.rstrip("/"),
                settings.provider_model,
                settings.provider_tokens_per_minute,
                settings.provider_tokens_per_day,
            )
            if "api.groq.com" in settings.provider_base_url
            else None,
        )

    return DeterministicProvider(tracer=tracer)
