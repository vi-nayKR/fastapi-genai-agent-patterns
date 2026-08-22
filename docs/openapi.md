# OpenAPI and HTTP API Reference

## Interactive and machine-readable documents

FastAPI generates the OpenAPI 3.1 contract directly from the route and Pydantic
models used at runtime. With the service running, the following documents are
available:

- Swagger UI: `GET /docs`
- ReDoc: `GET /redoc`
- OpenAPI JSON: `GET /openapi.json`

Export the same document without starting a server:

```bash
python -m scripts.export_openapi > openapi.json
```

Every operation has an explicit, stable `operationId` so generated client method
names do not change when Python handler names are refactored.

## Conventions

The application prefix is `/api/v1`. Health endpoints remain unversioned because
they are deployment probes rather than business resources.

Requests and normal responses use `application/json`. Unknown request fields are
rejected. Invalid types, missing required fields, and configured length or range
violations return FastAPI's standard HTTP 422 validation response.

Every HTTP response includes `x-request-id`. A caller may supply that header and
the service preserves it; otherwise the service returns a generated UUID. The
same request participates in W3C trace propagation through `traceparent`.

The reference application does not implement authentication. A production
deployment must enforce authentication and tenant authorization before exposing
agent or cache routes.

## Health operations

### `GET /health`

Operation ID: `getHealth`

Checks process liveness without calling Redis or another downstream service.

```json
{
  "status": "healthy",
  "service": "fastapi-genai-agent-patterns",
  "version": "0.1.0",
  "environment": "production",
  "timestamp": "2026-08-22T05:30:00Z"
}
```

### `GET /ready`

Operation ID: `getReadiness`

Pings Redis and verifies the Redis 8 `VADD` capability inside the configured
dependency timeout. When the cache is required, a degraded dependency returns
HTTP 503. When the cache is optional it returns HTTP 200 but keeps the degraded
check visible.

```json
{
  "status": "ready",
  "checks": {
    "api": "up",
    "redis": "up"
  }
}
```

## Agent operations

### `POST /api/v1/agents/runs`

Operation ID: `startAgentRun`

Starts a checkpointed graph and executes until it reaches a terminal state or a
human approval interrupt.

| Field | Type | Required | Constraints and behavior |
| --- | --- | --- | --- |
| `task` | string | yes | 3 to 10,000 characters |
| `thread_id` | string or null | no | Caller ID or generated UUID; maximum 128 characters |
| `risk_level` | enum | no | `low`, `medium`, or `high`; default `low` |
| `require_approval` | boolean | no | Forces approval for any risk; default `false` |
| `max_iterations` | integer | no | 2 through 32; default 8 |

Example request:

```json
{
  "task": "Deploy a payment API",
  "risk_level": "high",
  "require_approval": false,
  "max_iterations": 8
}
```

A high-risk run returns a checkpoint rather than a fabricated result:

```json
{
  "thread_id": "4974451f-1874-47d5-98cb-7c4be34f617e",
  "status": "pending_approval",
  "task": "Deploy a payment API",
  "result": null,
  "completed_agents": ["research", "coding", "compliance"],
  "audit_log": [
    "supervisor:planned:research,coding,compliance",
    "supervisor:routed:research",
    "research:completed",
    "supervisor:routed:coding",
    "coding:completed",
    "supervisor:routed:compliance",
    "compliance:completed",
    "supervisor:routed:approval"
  ],
  "approval": {
    "type": "approval_required",
    "thread_id": "4974451f-1874-47d5-98cb-7c4be34f617e",
    "task": "Deploy a payment API",
    "completed_agents": ["research", "coding", "compliance"],
    "risk_level": "high"
  }
}
```

`status` is one of `running`, `pending_approval`, `completed`, `rejected`, or
`failed`.

### `GET /api/v1/agents/runs/{thread_id}`

Operation ID: `getAgentRun`

Returns the latest checkpoint using the `AgentRunResponse` contract. An unknown
thread ID returns HTTP 404.

### `POST /api/v1/agents/runs/{thread_id}/approval`

Operation ID: `resumeAgentRun`

Consumes one explicit reviewer decision and resumes the suspended graph.

```json
{
  "approved": true,
  "feedback": "Change window confirmed"
}
```

`feedback` is optional and limited to 2,000 characters. Approval continues to a
`completed` response. Rejection returns a `rejected` response containing the
feedback. An unknown thread returns HTTP 404; a completed, rejected, failed, or
otherwise non-suspended thread returns HTTP 409.

### `POST /api/v1/agents/runs/stream`

Operation ID: `streamAgentRun`

Accepts `AgentRunRequest` and returns `text/event-stream`. Frames use standard
SSE syntax:

```text
event: token
data: {"type":"token","thread_id":"...","agent":"coding","token":"Implementation ","run":null}

```

Event order is:

1. One `run_started` event containing the assigned thread ID.
2. Zero or more `token` events containing `agent` and `token`.
3. One terminal `completed`, `pending_approval`, `rejected`, or `failed` event
   containing the full `run` object.

Clients should parse frames incrementally, preserve the returned thread ID, and
use the approval endpoint when the final stream event is `pending_approval`.

## Cache operations

Cache identity consists of `namespace`, `model`, and canonicalized `prompt`.
Namespace and model values are limited to 128 characters; prompts are limited to
20,000 characters.

### `POST /api/v1/cache/entries`

Operation ID: `putCacheEntry`

Writes an exact Redis hash and a native Redis 8 vector member. `response` may be
any JSON value.

```json
{
  "namespace": "support",
  "model": "model-a",
  "prompt": "How do I reset my password?",
  "response": {"answer": "Open settings."}
}
```

Returns HTTP 201 with the internal Redis entry key. Redis failures return 503.

### `POST /api/v1/cache/lookup`

Operation ID: `lookupCacheEntry`

```json
{
  "namespace": "support",
  "model": "model-a",
  "prompt": "How can I reset my password?"
}
```

An exact or semantic hit returns HTTP 200:

```json
{
  "hit": true,
  "source": "semantic",
  "distance": 0.07996,
  "matched_prompt": "How do I reset my password?",
  "response": {"answer": "Open settings."}
}
```

A miss returns HTTP 404 with `{"hit":false}` plus nullable response fields.
Redis failures return 503.

### `DELETE /api/v1/cache/entries`

Operation ID: `evictCacheEntry`

Accepts the same JSON body as a lookup and removes both the canonical hash and
its vector member. Returns `{"deleted":1}` when present or `{"deleted":0}` when
absent.

### `DELETE /api/v1/cache/namespaces/{namespace}`

Operation ID: `evictCacheNamespace`

Deletes all hashes and vector sets in a namespace using incremental scans. The
optional `model` query parameter restricts invalidation to one model.

```text
DELETE /api/v1/cache/namespaces/support?model=model-a
```

The response contains the number of entry hashes deleted.

### `GET /api/v1/cache/stats`

Operation ID: `getCacheStats`

Returns process-independent Redis counters:

```json
{
  "exact_hits": 14,
  "semantic_hits": 3,
  "misses": 2,
  "writes": 5,
  "exact_evictions": 1,
  "namespace_evictions": 4
}
```

## Error contract

Explicit operational errors use FastAPI's standard detail object:

```json
{
  "detail": "Run is not waiting for approval"
}
```

| Status | Meaning |
| --- | --- |
| 200 | Read, lookup hit, completed action, or optional-cache readiness |
| 201 | Cache entry created |
| 404 | Agent thread not found or cache miss |
| 409 | Approval submitted to a run that is not suspended |
| 422 | Request schema validation failed |
| 503 | Required Redis readiness failed or cache operation could not reach Redis |

## Compatibility policy

Additive response fields and new endpoints may be introduced within `/api/v1`.
Removing or renaming fields, changing types, or changing operation semantics
requires a new API prefix. Stable operation IDs are covered by tests so generated
SDKs retain their method names.
