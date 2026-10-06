"""Base exceptions, protocols, and data models for model providers."""

import json
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class ProviderError(Exception):
    """Base exception for all model provider failures."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderAuthenticationError(ProviderError):
    """Raised on HTTP 401/403 or invalid provider credentials."""


class ProviderRateLimitError(ProviderError):
    """Raised on HTTP 429 when quota or rate limits are exceeded."""

    def __init__(
        self,
        message: str,
        retry_after: float | None = None,
        status_code: int = 429,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request exceeds its allotted deadline."""


class ProviderMalformedOutputError(ProviderError):
    """Raised when provider output cannot be parsed or validated against the schema."""


class ProviderUnavailableError(ProviderError):
    """Raised on network connection errors or 5xx responses from the upstream provider."""


class ProviderBudgetError(ProviderError):
    """Raised before a paid call would exceed the evaluation-wide budget."""


class ProviderQuotaError(ProviderError):
    """A daily quota stops this invocation; successful work remains resumable."""


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@dataclass
class EvaluationBudget:
    max_cost_usd: float
    reserved_usd: float = 0
    state_path: Path | None = None

    def __post_init__(self) -> None:
        if self.state_path and self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.reserved_usd = float(state["reserved_usd"])
            if (
                not math.isfinite(self.reserved_usd)
                or not 0 <= self.reserved_usd <= self.max_cost_usd
            ):
                raise ValueError("Invalid persisted evaluation budget")

    def reserve(self, amount: float) -> None:
        if (
            not math.isfinite(amount)
            or amount < 0
            or self.reserved_usd + amount > self.max_cost_usd
        ):
            raise ProviderBudgetError("Evaluation cost cap reached before API call")
        # No awaits: reservation is atomic within the evaluation's single asyncio loop.
        if self.state_path:
            # ponytail: one eval process per campaign; use SQLite for concurrent campaigns.
            write_json_atomic(self.state_path, {"reserved_usd": self.reserved_usd + amount})
        self.reserved_usd += amount


@dataclass(frozen=True)
class ProviderUsage:
    """Token consumption details returned by a provider invocation."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(frozen=True)
class ProviderResponse:
    """Unified response payload across model providers."""

    content: str
    usage: ProviderUsage
    model: str
    structured: Any | None = None
    cached: bool = False
    response_cost_usd: float = 0
    billed_cost_usd: float = 0
    raw_response_key: str | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Asynchronous model provider protocol supporting generation, streaming, and schemas."""

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: type[BaseModel] | None = None,
        request_timeout: float | None = None,
        max_output_tokens: int | None = None,
    ) -> ProviderResponse:
        """Execute a completion request, optionally validating structured output."""
        ...

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        request_timeout: float | None = None,
    ) -> AsyncIterator[str]:
        """Stream output tokens asynchronously as they arrive."""
        ...

    async def close(self) -> None:
        """Release underlying HTTP and network resources."""
        ...
