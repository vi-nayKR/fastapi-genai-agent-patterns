# Phase 4: Observability and Deployment Hardening

## Goal

Phase 4 connects the runtime pieces into an operable service. It adds trace
context across HTTP, graph, worker, and cache boundaries; makes readiness depend
on Redis 8 capabilities; supplies non-root containers and a local trace backend;
and turns lint, type, test, integration, and performance checks into CI gates.

## End-to-end tracing

The application creates one OpenTelemetry `TracerProvider` with resource
attributes for service name, version, and deployment environment. When
`AGENT_PATTERNS_OTLP_ENDPOINT` is set, completed spans are batched and sent with
OTLP over HTTP. Tests inject an in-memory exporter through the application
factory, so trace behavior is asserted without a collector.

FastAPI instrumentation creates server spans and extracts standard W3C trace
context. The active context flows into `agent.run` or `agent.run.stream`, then
into each `agent.worker.NAME` span. Approval resumes create a separate
`agent.approval.resume` span tied to the checkpoint thread by an attribute.

Cache lookup, write, and exact eviction create spans with cache source, hit,
distance, and deletion outcome. Prompts, responses, raw namespaces, and model
names are intentionally excluded. Namespace and model attributes are truncated
SHA-256 digests, allowing correlation without placing user content in telemetry.

## Dependency-aware readiness

`/health` remains a side-effect-free liveness endpoint. `/ready` now pings Redis
within a bounded timeout and verifies that `VADD` is present. If Redis is marked
required, either failure returns HTTP 503 and a degraded body. Local or partial
deployments may set `AGENT_PATTERNS_CACHE_REQUIRED=false`; readiness then remains
ready while explicitly reporting Redis as degraded.

This distinction prevents an orchestrator from restarting a live process for a
downstream outage while still keeping an unready instance out of load-balancer
rotation when caching is a required service capability.

## Container and local observability stack

The Docker image installs only runtime dependencies, runs as UID and GID 10001,
writes no bytecode, and includes a liveness health check. It does not contain the
test suite, local environment files, Git history, or tool caches.

Docker Compose starts four services:

- The FastAPI service on port 8002.
- Redis 8 with append-only persistence and a health check.
- OpenTelemetry Collector Contrib with OTLP HTTP and gRPC receivers.
- Jaeger 2 with its query UI on port 16686.

The collector batches traces, exports them to Jaeger, and logs a basic debug
summary. The application waits for healthy Redis before starting.

Start the complete stack with:

```bash
docker compose up --build
```

Open the API at `http://localhost:8002/docs` and Jaeger at
`http://localhost:16686`.

## Continuous integration

The GitHub Actions workflow grants read-only repository permissions and starts a
Redis 8 service container. Every push and pull request must pass:

1. Ruff lint checks.
2. Strict Mypy checking.
3. Unit and real Redis integration tests.
4. A 500-iteration exact lookup and eviction benchmark with a 5 ms p95 gate.

The performance gate runs Redis on the same CI host and therefore measures the
wrapper plus local Redis round trips. Deployment environments should repeat the
1,000-iteration benchmark described in Phase 3.

## OpenAPI documentation

Every route has a stable operation ID, summary, typed schema, and explicit
operational error responses. FastAPI serves Swagger UI, ReDoc, and OpenAPI 3.1
JSON from the runtime contract. `docs/openapi.md` adds request and response
examples, SSE framing, status semantics, headers, validation behavior, and a
compatibility policy. `python -m scripts.export_openapi` prints the generated
machine-readable contract for SDK generation or review.

Tests lock the operation-ID set and verify that SSE content and important 404 and
409 responses remain present in the generated schema.

## Trace verification

Tests assert that coding and research worker spans are children of the agent-run
span, that cache spans record hit source without prompt content, and that FastAPI
emits a server span. To inspect a real trace:

```bash
curl -X POST http://localhost:8002/api/v1/agents/runs \
  -H 'content-type: application/json' \
  -H 'traceparent: 00-0123456789abcdef0123456789abcdef-0123456789abcdef-01' \
  -d '{"task":"Implement and test a Python API"}'
```

Select `fastapi-genai-agent-patterns` in Jaeger. The trace should show the HTTP
server span, agent run, and the research and coding worker spans.

## Verification

Run the complete local quality gate:

```bash
ruff check .
mypy
pytest
```

With Redis running, include the external contract and performance gates:

```bash
TEST_REDIS_URL=redis://localhost:6379/0 pytest tests/integration/test_redis_cache.py
python -m scripts.benchmark_cache --iterations 1000 --target-ms 5
```
