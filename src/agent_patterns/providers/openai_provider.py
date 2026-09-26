"""OpenAI-compatible async model provider with deadlines, retries, and structured outputs."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, Tracer
from pydantic import BaseModel, ValidationError

from agent_patterns.providers.base import (
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
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._tracer = tracer or trace.get_tracer(__name__)

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
                    retry_after = self._parse_retry_after(response)
                    last_error = ProviderRateLimitError(
                        f"Rate limit exceeded (429): {response.text}",
                        retry_after=retry_after,
                    )
                    delay = retry_after if retry_after is not None else 0.25 * (2**attempt)
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
            if attempt < attempts - 1:
                await asyncio.sleep(min(delay, 10.0))

        if last_error:
            raise last_error
        raise ProviderUnavailableError("Provider request failed after retries")

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: type[BaseModel] | None = None,
        request_timeout: float | None = None,
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
            }

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
                response = await self._post_with_retry(
                    "/chat/completions",
                    payload,
                    request_timeout=request_timeout,
                )
                data = response.json()
            except Exception as exc:
                span.record_exception(exc)
                span.set_attribute("provider.status", "error")
                span.set_status(Status(StatusCode.ERROR, exc.__class__.__name__))
                raise

            choice = data["choices"][0]["message"]["content"]
            usage_data = data.get("usage", {})
            usage = ProviderUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
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

            return ProviderResponse(
                content=choice,
                usage=usage,
                model=data.get("model", self._model),
                structured=structured_instance,
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
