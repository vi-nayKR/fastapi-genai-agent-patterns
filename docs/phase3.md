# Phase 3: Redis 8 Exact and Semantic Cache

## Goal

Phase 3 implements the cache behind the resume performance claim. It prioritizes
constant-time exact reuse for recurring prompts, falls back to native Redis 8
vector-set similarity, controls cache stampedes, supports scoped invalidation, and
ships a benchmark that fails when the configured latency target is missed.

## Lookup design

Each lookup follows two stages:

1. Canonical exact lookup with a directly addressable Redis hash key.
2. Filtered K-nearest-neighbor search against an HNSW vector index.

Prompt canonicalization applies Unicode NFKC normalization, case folding,
leading and trailing trimming, and whitespace collapsing. SHA-256 digests of the
namespace, model, and canonical prompt form a bounded, injection-safe Redis key.
This makes an exact lookup one `HGETALL` and exact eviction one `DEL`; neither
operation scans the keyspace.

Semantic lookup uses the `VADD`, `VSIM`, and `VREM` vector-set commands introduced
in Redis 8. Each namespace and model pair owns a separate HNSW vector set, which
enforces tenant and model isolation before similarity is calculated. Vectors use
unquantized FLOAT32 storage and cosine similarity. A result is returned only when
its cosine distance is at or below the configured threshold. Exact and semantic
hits are explicitly identified in the response.

## Embedding boundary

`HashingEmbedder` provides deterministic, normalized embeddings from word and
character-trigram features. It requires no model download, network call, GPU, or
credential, which keeps the reference implementation reproducible. It is not
presented as a replacement for a production embedding model; its small `embed`
and `pack` boundary is where a hosted or local model adapter belongs.

Vectors are serialized as little-endian FLOAT32 values, matching the index
schema. Dimension validation is shared with application settings.

## Writes, expiry, and invalidation

Entries are Redis hashes containing the original prompt, canonical prompt,
JSON-encoded response, vector, namespace and model tags, and creation time. Every
entry receives a configurable TTL immediately after writing. Vector members use
the canonical prompt digest as their identity; a stale member discovered after a
hash TTL expires is removed during lookup.

Exact invalidation derives the same canonical key and issues `DEL` plus `VREM`. Namespace
invalidation uses incremental `SCAN` batches, never `KEYS`, and may optionally be
limited to one model. The scan key includes hashed namespace and model segments,
so one tenant cannot evict another tenant's entries.

## Stampede control and counters

`get_or_compute` checks the cache, obtains a distributed Redis lock scoped to the
prompt, checks again after acquiring the lock, and only then invokes the producer.
This double-check prevents many concurrent misses from triggering duplicate LLM
requests. Lock and wait timeouts keep a failed producer from blocking indefinitely.

Redis counters expose exact hits, semantic hits, misses, writes, exact evictions,
and namespace evictions. These deliberately low-cardinality values can feed an
operations dashboard without including prompts or tenant identifiers.

## Cache API

- `POST /api/v1/cache/entries` writes an entry.
- `POST /api/v1/cache/lookup` performs exact then semantic lookup.
- `DELETE /api/v1/cache/entries` evicts one exact entry.
- `DELETE /api/v1/cache/namespaces/{namespace}` evicts a scoped group.
- `GET /api/v1/cache/stats` returns operational counters.

Redis connection errors return 503 without leaking connection details.

## Reproducible benchmark

Start Redis 8 and run the benchmark from the project environment:

```bash
docker compose up -d redis
python -m scripts.benchmark_cache --iterations 1000 --target-ms 5
```

The script warms the exact key, measures each operation with a monotonic
nanosecond clock, and reports p50 and p95 latency for exact lookup and exact
eviction. It exits nonzero when either p95 is at or above 5 ms. Run the benchmark
on the same host as Redis; a wide-area network measures network latency rather
than wrapper performance.

No latency result is hard-coded into application behavior. The resume claim
should be retained only when benchmark output from the target environment proves it.

### Recorded local validation

The implementation was validated on 2026-08-22 against Redis Open Source 8.10.1
on an Apple Silicon development host. A 1,000-iteration run produced:

```text
exact_lookup_p50_ms=0.141
exact_lookup_p95_ms=0.245
exact_eviction_p50_ms=0.163
exact_eviction_p95_ms=0.180
target_ms=5.000
```

The real vector-set contract test also matched "How can I reset my password?"
to the stored prompt "How do I reset my password?" at cosine distance 0.07996.
These numbers describe this local test environment and should be rerun after
deployment, Redis configuration changes, or network-topology changes.

## Verification

Unit tests cover canonicalization, deterministic normalized embeddings, exact
round trips, semantic response parsing and thresholds, tenant-scoped invalidation,
and producer deduplication. Run:

```bash
ruff check .
mypy
pytest
```

Run the opt-in Redis 8 contract test with:

```bash
TEST_REDIS_URL=redis://localhost:6379/0 pytest tests/integration/test_redis_cache.py
```

The Docker benchmark is the separate integration and performance gate.

## Next phase

Phase 4 will connect readiness to Redis, verify vector-set support at startup,
add OpenTelemetry spans and metrics around graph and cache operations, package
the service, and finish the operating runbook.
