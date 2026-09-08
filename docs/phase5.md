# Phase 5: Real Provider Mode, Structured Outputs, and Failure Boundaries

## Goal

Phase 5 transitions the LangGraph supervisor from canned mock demonstrations into a
production-grade, model-backed service. It introduces an asynchronous, OpenAI-compatible
provider adapter with request deadlines and bounded retries; enforces schema-valid
structured outputs across specialists; ensures explicit error propagation without silent
mock fallback; and preserves deterministic execution for rapid, zero-network tests.

## Work completed

### Async provider adapter

A typed `LLMProvider` protocol defines generation and token-streaming boundaries in
`src/agent_patterns/providers/base.py`. `OpenAIProvider` implements this protocol
using `httpx.AsyncClient`, supporting OpenAI, Ollama, vLLM, OpenRouter, and Groq endpoints.

The provider incorporates production resilience patterns:

- **Request deadlines:** Enforces configurable HTTP timeouts (`AGENT_PATTERNS_PROVIDER_TIMEOUT_SECONDS`).
- **Bounded retries:** Automatically retries transient network interruptions and HTTP 5xx responses with exponential backoff and jitter.
- **Rate-limit backoff:** Parses upstream `Retry-After` headers on HTTP 429 status codes before sleeping and retrying.
- **Fail-fast authentication:** Immediately fails on HTTP 401 and 403 responses without wasteful retries.
- **Cancellation safety:** Cleans up active requests without leaking tasks or connections upon caller cancellation.

### Schema-enforced structured outputs

Specialist nodes now produce typed Pydantic models conforming to strict domain schemas:

- `ResearchFinding`: Synthesizes retrieved evidence, authoritative citations, confidence levels, and explicit abstention.
- `ActionProposal`: Categorizes proposed actions (`read_only`, `ticket_update`, `system_change`, `escalate`), resource targets, and mutation flags.
- `ComplianceReview`: Assesses policy satisfaction, risk level, and whether human authorization is mandated.
- `StructuredAgentResult`: Consolidates specialist findings into a unified, machine-readable payload with recorded token consumption.

Provider calls pass strict JSON schemas to the model. If a provider returns unparseable or
non-conforming output, `ProviderMalformedOutputError` is raised and recorded.

### Explicit failure handling (No silent fallback)

A critical architectural guarantee is that **real provider mode never silently falls back
to mock data**. When an upstream model provider fails (e.g. rate-limit exhaustion, network
disconnect, invalid credentials, or malformed JSON):

1. The worker records the typed exception (`ProviderRateLimitError`, `ProviderAuthenticationError`, etc.) on the OpenTelemetry span.
2. The supervisor halts iteration and routes immediately to `finalize`.
3. The run status transitions to `failed` with descriptive `error_details`.
4. The audit log explicitly records the failure reason (e.g., `research:failed:ProviderRateLimitError`, `run:failed`).

### Preserved deterministic mode

Offline development and CI pipelines require fast, deterministic execution without
requiring external API keys or incurring costs. The default `DeterministicProvider`
generates schema-valid instances matching expected test fixtures while maintaining
identical telemetry and token accounting spans.

## Files introduced and modified

- `src/agent_patterns/providers/base.py`: Protocol, typed exceptions, and response models.
- `src/agent_patterns/providers/openai_provider.py`: Async client with retries, streaming, and schema validation.
- `src/agent_patterns/providers/deterministic_provider.py`: Deterministic test double and offline fixture.
- `src/agent_patterns/providers/factory.py`: Provider instantiation from runtime settings.
- `src/agent_patterns/providers/__init__.py`: Exported provider interface.
- `src/agent_patterns/schemas.py`: Structured output models (`ResearchFinding`, `ActionProposal`, `ComplianceReview`, `StructuredAgentResult`).
- `src/agent_patterns/config.py`: Provider configuration settings.
- `src/agent_patterns/agents/state.py`: Structured partial outputs and error tracking in graph state.
- `src/agent_patterns/agents/workers.py`: Provider-backed specialist execution with failure handling.
- `src/agent_patterns/agents/graph.py`: Failure routing and structured finalization.
- `src/agent_patterns/agents/runtime.py`: Provider lifecycle and structured response mapping.
- `src/agent_patterns/app.py`: Dependency injection and graceful shutdown for provider resources.
- `tests/test_provider.py`: Comprehensive adapter unit tests (retries, deadlines, 429 backoff, 401 fail-fast, streaming).
- `tests/test_real_provider_mode.py`: End-to-end API integration tests verifying structured outputs and explicit failure behavior.
- `tests/test_agents.py`: Verified structured output assertions in deterministic mode.

## Verification

Run the full quality gate:

```bash
ruff check .
mypy src
pytest
```

Run provider and real mode tests:

```bash
pytest tests/test_provider.py tests/test_real_provider_mode.py
```
