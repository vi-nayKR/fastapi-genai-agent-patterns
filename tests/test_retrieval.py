"""Unit tests for the retrieval engine: BM25, dense similarity, RRF, and tenant isolation."""

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_patterns.retrieval.bm25 import BM25Index, tokenize
from agent_patterns.retrieval.corpus import OPERATIONAL_CORPUS
from agent_patterns.retrieval.hybrid import HybridRetriever
from agent_patterns.retrieval.models import Document


def test_tokenize_filters_stopwords_and_symbols() -> None:
    tokens = tokenize("What is the 90-day API key rotation policy?")
    assert "is" not in tokens
    assert "the" not in tokens
    assert "90" in tokens
    assert "day" in tokens
    assert "api" in tokens
    assert "key" in tokens
    assert "rotation" in tokens


def test_bm25_scores_relevant_passages_higher() -> None:
    corpus = [
        "API keys must be rotated every 90 days with MFA.",
        "Database backups are taken daily and stored for 30 days.",
        "Refunds are approved within 30 days of purchase.",
    ]
    index = BM25Index(corpus)
    scores = index.score_all("API key rotation")
    assert scores[0][0] == 0
    assert scores[0][1] > scores[1][1]


def test_retriever_enforces_tenant_isolation() -> None:
    retriever = HybridRetriever(OPERATIONAL_CORPUS)
    # Search for secret KMS key as tenant-alpha
    alpha_results = retriever.search("KMS alias dedicated secret", tenant_id="tenant-alpha")
    for res in alpha_results:
        assert res.chunk.tenant_id == "tenant-alpha"
        assert "tenant-beta" not in res.chunk.text

    # Search for same query as tenant-beta
    beta_results = retriever.search("KMS alias dedicated secret", tenant_id="tenant-beta")
    assert len(beta_results) > 0
    assert beta_results[0].chunk.doc_id == "DOC-BETA-SEC-001"
    assert beta_results[0].chunk.tenant_id == "tenant-beta"


def test_retriever_excludes_deprecated_stale_documents() -> None:
    retriever = HybridRetriever(OPERATIONAL_CORPUS)
    results = retriever.search("API authentication tokens", tenant_id="tenant-alpha")
    doc_ids = [r.chunk.doc_id for r in results]
    # Must retrieve active DOC-SEC-001 and exclude deprecated DOC-SEC-001-v1
    assert "DOC-SEC-001" in doc_ids
    assert "DOC-SEC-001-v1" not in doc_ids


def test_retriever_can_include_deprecated_when_explicitly_requested() -> None:
    retriever = HybridRetriever(OPERATIONAL_CORPUS)
    results = retriever.search(
        "Legacy API authentication HMAC-SHA1",
        tenant_id="tenant-alpha",
        include_deprecated=True,
    )
    doc_ids = [r.chunk.doc_id for r in results]
    assert "DOC-SEC-001-v1" in doc_ids


def test_hybrid_rrf_combines_ranks() -> None:
    docs = [
        Document(
            doc_id="DOC-1",
            title="Database",
            tenant_id="t1",
            version=1,
            status="active",
            content="Postgres database failover and read replica configuration.",
            tags=[],
            updated_at="2026-01-01",
        ),
        Document(
            doc_id="DOC-2",
            title="Redis",
            tenant_id="t1",
            version=1,
            status="active",
            content="Redis semantic cache eviction and TTL management.",
            tags=[],
            updated_at="2026-01-01",
        ),
    ]
    retriever = HybridRetriever(docs, rrf_constant=60)
    hybrid_res = retriever.search("Postgres replica", tenant_id="t1", mode="hybrid")
    dense_res = retriever.search("Postgres replica", tenant_id="t1", mode="dense")
    lex_res = retriever.search("Postgres replica", tenant_id="t1", mode="lexical")

    assert len(hybrid_res) > 0
    assert hybrid_res[0].chunk.doc_id == "DOC-1"
    assert dense_res[0].chunk.doc_id == "DOC-1"
    assert lex_res[0].chunk.doc_id == "DOC-1"


def test_retriever_records_telemetry_span() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")

    retriever = HybridRetriever(OPERATIONAL_CORPUS, tracer=tracer)
    retriever.search("incident escalation P1", tenant_id="tenant-alpha")

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert "retrieval.search" in spans
    span = spans["retrieval.search"]
    attrs = dict(span.attributes or {})
    assert attrs["retrieval.tenant_id"] == "tenant-alpha"
    assert attrs["retrieval.mode"] == "hybrid"
    assert attrs["retrieval.top_k"] == 5
    returned_count = attrs.get("retrieval.returned_count")
    assert isinstance(returned_count, int)
    assert returned_count > 0
    provider.shutdown()
