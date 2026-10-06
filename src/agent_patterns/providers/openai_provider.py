"""OpenAI-compatible async model provider with deadlines, retries, and structured outputs."""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, Tracer
from pydantic import BaseModel, ValidationError

from agent_patterns.providers.base import (
    EvaluationBudget,
    LLMProvider,
    ProviderAuthenticationError,
    ProviderError,
    ProviderMalformedOutputError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ProviderUsage,
)


class OpenAIProvider(LLMProvider):
    """Async provider adapter for OpenAI and compatible APIs (Ollama, vLLM, Groq)."""

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        tracer: Tracer | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        temperature: float = 0.1,
        seed: int | None = None,
        cache_dir: str | None = None,
        budget: EvaluationBudget | None = None,
        input_usd_per_million: float = 10,
        output_usd_per_million: float = 10,
        min_interval_seconds: float = 0,
        retry_backoff_seconds: float = 1,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._tracer = tracer or trace.get_tracer(__name__)
        self._temperature = temperature
        self._seed = seed
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._budget = budget
        self._input_rate = input_usd_per_million / 1_000_000
        self._output_rate = output_usd_per_million / 1_000_000
        self._min_interval = min_interval_seconds
        self._retry_backoff = retry_backoff_seconds
        self._throttle_lock = asyncio.Lock()
        self._next_request = 0.0
        self.request_metrics: dict[str, float] = {
            "http_attempts": 0,
            "rate_limit_responses": 0,
            "retries": 0,
            "backoff_seconds": 0,
            "throttle_wait_seconds": 0,
            "cache_hits": 0,
        }

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(self._timeout_seconds),
            transport=transport,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    def _parse_retry_after(self, response: httpx.Response) -> float | None:
        header = response.headers.get("Retry-After")
        if not header:
            return None
        try:
            return float(header)
        except (ValueError, TypeError):
            return None

    async def _post_with_retry(
        self,
        endpoint: str,
        payload: dict[str, Any],
        request_timeout: float | None = None,
    ) -> httpx.Response:
        """Execute a POST request with bounded retries and exponential backoff."""
        url = f"{self._base_url}{endpoint}"
        req_timeout = httpx.Timeout(request_timeout or self._timeout_seconds)
        attempts = 1 + max(0, self._max_retries)

        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                # ponytail: per-process pacing; use a shared limiter for multiple replicas.
                async with self._throttle_lock:
                    loop = asyncio.get_running_loop()
                    wait = max(0, self._next_request - loop.time())
                    self.request_metrics["throttle_wait_seconds"] += wait
                    await asyncio.sleep(wait)
                    self._next_request = loop.time() + self._min_interval
                self.request_metrics["http_attempts"] += 1
                response = await self._client.post(url, json=payload, timeout=req_timeout)
                if response.status_code == 200:
                    return response

                # Non-retryable status codes fail fast immediately
                if response.status_code in (401, 403):
                    raise ProviderAuthenticationError(
                        f"Authentication failed: {response.text}",
                        status_code=response.status_code,
                    )
                if response.status_code == 400:
                    raise ProviderError(
                        f"Bad request to provider: {response.text}",
                        status_code=400,
                    )

                # Retryable status codes
                if response.status_code == 429:
                    self.request_metrics["rate_limit_responses"] += 1
                    retry_after = self._parse_retry_after(response)
                    last_error = ProviderRateLimitError(
                        f"Rate limit exceeded (429): {response.text}",
                        retry_after=retry_after,
                    )
                    delay = max(retry_after or 0, self._retry_backoff * (2**attempt))
                elif response.status_code >= 500:
                    last_error = ProviderUnavailableError(
                        f"Provider server error ({response.status_code}): {response.text}",
                        status_code=response.status_code,
                    )
                    delay = 0.25 * (2**attempt)
                else:
                    raise ProviderError(
                        f"Unexpected provider status ({response.status_code}): {response.text}",
                        status_code=response.status_code,
                    )

            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_error = ProviderUnavailableError(f"Connection to provider failed: {exc}")
                delay = 0.25 * (2**attempt)
            except httpx.ReadTimeout as exc:
                last_error = ProviderTimeoutError(f"Provider request timed out: {exc}")
                delay = 0.25 * (2**attempt)
            except (ProviderAuthenticationError, ProviderError):
                raise

            # If this was not the last attempt, back off before retrying
            if "max_tokens" in payload and not isinstance(last_error, ProviderRateLimitError):
                break  # A timeout/5xx could already be billed; retry only rejected 429s.
            if attempt < attempts - 1:
                wait = min(max(delay, 0), 60.0)
                self.request_metrics["retries"] += 1
                self.request_metrics["backoff_seconds"] += wait
                await asyncio.sleep(wait)

        if last_error:
            raise last_error
        raise ProviderUnavailableError("Provider request failed after retries")

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: type[BaseModel] | None = None,
        request_timeout: float | None = None,
        max_output_tokens: int | None = None,
    ) -> ProviderResponse:
        """Call the completions endpoint, validating structured output when requested."""
        with self._tracer.start_as_current_span("provider.chat.completions") as span:
            span.set_attribute("provider.name", "openai")
            span.set_attribute("provider.model", self._model)
            span.set_attribute("provider.streaming", False)

            formatted_messages = list(messages)
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": formatted_messages,
                "stream": False,
                "temperature": self._temperature,
            }
            if max_output_tokens is not None:
                payload["max_tokens"] = max_output_tokens
            if self._seed is not None:
                payload["seed"] = self._seed
            if "generativelanguage.googleapis.com" in self._base_url:
                # 2.5 Flash's low effort allocates 1024 thinking tokens, exceeding
                # our small completion cap; none is supported by that model.
                payload["reasoning_effort"] = (
                    "none" if self._model.startswith("gemini-2.5-flash") else "low"
                )

            if response_schema is not None:
                payload["response_format"] = {"type": "json_object"}
                schema_json = json.dumps(response_schema.model_json_schema())
                formatted_messages.append(
                    {
                        "role": "system",
                        "content": (
                            "You must format your response as valid JSON adhering to "
                            f"this schema: {schema_json}"
                        ),
                    }
                )

            try:
                key = hashlib.sha256(
                    json.dumps([self._base_url, payload], sort_keys=True).encode()
                ).hexdigest()
                cache = self._cache_dir / f"{key}.json" if self._cache_dir else None
                # ponytail: simultaneous first misses may duplicate calls; add per-key locks
                # if identical concurrent traffic matters. Completed reruns use disk cache.
                cached = cache is not None and await asyncio.to_thread(cache.exists)
                if cached and cache is not None:
                    self.request_metrics["cache_hits"] += 1
                    envelope = json.loads(
                        await asyncio.to_thread(cache.read_text, encoding="utf-8")
                    )
                    data = envelope["response"]
                else:
                    if self._budget is not None:
                        prompt_bound = (
                            sum(len(m["content"].encode()) for m in formatted_messages) + 128
                        )
                        self._budget.reserve(
                            prompt_bound * self._input_rate
                            + (max_output_tokens or 700) * self._output_rate
                        )
                    response = await self._post_with_retry(
                        "/chat/completions",
                        payload,
                        request_timeout=request_timeout,
                    )
                    data = response.json()
                    if cache is not None:
                        await asyncio.to_thread(cache.parent.mkdir, parents=True, exist_ok=True)
                        envelope = {
                            "requested_model": self._model,
                            "temperature": self._temperature,
                            "seed": self._seed,
                            "run_date_utc": datetime.now(UTC).isoformat(),
                            "request": payload,
                            "response": data,
                        }
                        # Atomic replacement prevents partial cache files on interruption.
                        temporary = cache.with_suffix(f".{uuid4().hex}.tmp")
                        try:
                            await asyncio.to_thread(
                                temporary.write_text,
                                json.dumps(envelope, indent=2),
                                encoding="utf-8",
                            )
                            await asyncio.to_thread(temporary.replace, cache)
                        finally:
                            await asyncio.to_thread(temporary.unlink, missing_ok=True)
            except Exception as exc:
                span.record_exception(exc)
                span.set_attribute("provider.status", "error")
                span.set_status(Status(StatusCode.ERROR, exc.__class__.__name__))
                raise

            choice = data["choices"][0]["message"]["content"]
            usage_data = data.get("usage", {})
            prompt = usage_data.get("prompt_tokens", 0)
            completion = usage_data.get("completion_tokens", 0)
            total = usage_data.get("total_tokens", 0)
            reasoning = 0
            if (
                "generativelanguage.googleapis.com" in self._base_url
                and all(type(value) is int and value >= 0 for value in (prompt, completion, total))
                and total >= prompt + completion
            ):
                # Gemini compatibility can omit thinking from completion_tokens while
                # including it in total_tokens. Charge and cap all generated tokens.
                reasoning = total - prompt - completion
                completion += reasoning
            usage = ProviderUsage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                reasoning_tokens=reasoning,
            )

            span.set_attribute("llm.usage.prompt_tokens", usage.prompt_tokens)
            span.set_attribute("llm.usage.completion_tokens", usage.completion_tokens)
            span.set_attribute("llm.usage.total_tokens", usage.total_tokens)
            span.set_attribute("provider.status", "success")

            structured_instance: Any = None
            if response_schema is not None:
                try:
                    structured_instance = response_schema.model_validate_json(choice)
                except (ValidationError, ValueError) as exc:
                    span.record_exception(exc)
                    span.set_attribute("provider.status", "malformed_output")
                    raise ProviderMalformedOutputError(
                        f"Failed to validate output against {response_schema.__name__}: {exc}"
                    ) from exc

            if max_output_tokens is not None and (
                not all(
                    type(value) is int and value >= 0
                    for value in (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)
                )
                or usage.total_tokens == 0
                or usage.total_tokens != usage.prompt_tokens + usage.completion_tokens
                or usage.completion_tokens > max_output_tokens
            ):
                raise ProviderMalformedOutputError(
                    "Budgeted provider response has missing or invalid token usage"
                )
            return ProviderResponse(
                content=choice,
                usage=usage,
                model=data.get("model", self._model),
                structured=structured_instance,
                cached=cached,
                response_cost_usd=usage.prompt_tokens * self._input_rate
                + usage.completion_tokens * self._output_rate,
                billed_cost_usd=0
                if cached
                else usage.prompt_tokens * self._input_rate
                + usage.completion_tokens * self._output_rate,
                raw_response_key=key if cache is not None else None,
            )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        request_timeout: float | None = None,
    ) -> AsyncIterator[str]:
        """Stream output tokens asynchronously via Server-Sent Events."""
        with self._tracer.start_as_current_span("provider.chat.completions.stream") as span:
            span.set_attribute("provider.name", "openai")
            span.set_attribute("provider.model", self._model)
            span.set_attribute("provider.streaming", True)

            url = f"{self._base_url}/chat/completions"
            payload = {
                "model": self._model,
                "messages": messages,
                "stream": True,
            }
            req_timeout = httpx.Timeout(request_timeout or self._timeout_seconds)

            try:
                async with self._client.stream(
                    "POST", url, json=payload, timeout=req_timeout
                ) as response:
                    if response.status_code in (401, 403):
                        body = await response.aread()
                        raise ProviderAuthenticationError(
                            f"Authentication failed ({response.status_code}): {body.decode()}",
                            status_code=response.status_code,
                        )
                    if response.status_code == 429:
                        body = await response.aread()
                        retry_after = self._parse_retry_after(response)
                        raise ProviderRateLimitError(
                            f"Rate limit exceeded (429): {body.decode()}",
                            retry_after=retry_after,
                        )
                    if response.status_code >= 400:
                        body = await response.aread()
                        raise ProviderError(
                            f"Provider error ({response.status_code}): {body.decode()}",
                            status_code=response.status_code,
                        )

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line.removeprefix("data: ").strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                token = delta.get("content")
                                if token:
                                    yield token
                        except json.JSONDecodeError:
                            continue
            except httpx.ReadTimeout as exc:
                span.record_exception(exc)
                raise ProviderTimeoutError(f"Streaming request timed out: {exc}") from exc
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                span.record_exception(exc)
                raise ProviderUnavailableError(f"Streaming connection failed: {exc}") from exc
