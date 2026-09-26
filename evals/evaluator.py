"""Calibrated evaluation suite and metrics calculator for versioned retrieval and agent runs.

No synthetic score floors or fabricated metrics: every score is mathematically derived
from ground truth expectations, document citations, specialist outputs, and runtime telemetry.
"""

import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict

from agent_patterns.agents.runtime import AgentRuntime
from agent_patterns.retrieval.corpus import OPERATIONAL_CORPUS
from agent_patterns.retrieval.hybrid import HybridRetriever
from agent_patterns.schemas import AgentRunRequest


class BenchmarkCase(BaseModel):
    """Schema for an individual evaluation benchmark case."""

    model_config = ConfigDict(extra="ignore")

    case_id: str
    category: str
    tenant_id: str
    query: str
    expected_citations: list[str]
    expected_abstain: bool
    expected_action_type: Literal["read_only", "ticket_update", "system_change", "escalate"]
    expected_mutation: bool
    requires_approval: bool
    adversarial: bool
    ground_truth_answer: str


class RetrievalAblationMetrics(BaseModel):
    """Calibrated Information Retrieval metrics across ablation modes."""

    mode: Literal["dense", "lexical", "hybrid"]
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    precision_at_1: float
    precision_at_3: float
    precision_at_5: float
    mrr: float
    evaluated_cases: int


class CaseEvaluationResult(BaseModel):
    """Detailed results and verified assertions for a single benchmark test case."""

    case_id: str
    category: str
    tenant_id: str
    query: str
    status: str
    passed: bool
    retrieved_citations: list[str]
    expected_citations: list[str]
    citation_precision: float
    citation_recall: float
    abstain_correct: bool
    action_type_correct: bool
    mutation_correct: bool
    approval_correct: bool
    unauthorized_action: bool
    latency_seconds: float
    tokens_used: int
    estimated_cost_usd: float
    notes: str


class CategoryMetrics(BaseModel):
    """Aggregated performance metrics for a specific evaluation category."""

    category: str
    total_cases: int
    passed_cases: int
    success_rate: float
    avg_latency_seconds: float
    citation_precision: float
    citation_recall: float
    abstention_accuracy: float


class BenchmarkSummary(BaseModel):
    """High-level summary of benchmark execution, retrieval ablations, and cost."""

    benchmark_name: str
    version: str
    timestamp: str
    total_cases: int
    passed_cases: int
    overall_task_success_rate: float
    abstention_accuracy: float
    citation_precision: float
    citation_recall: float
    action_classification_accuracy: float
    mutation_classification_accuracy: float
    approval_gate_accuracy: float
    unauthorized_actions: int
    avg_latency_seconds: float
    p95_latency_seconds: float
    total_tokens: int
    avg_tokens_per_case: float
    total_estimated_cost_usd: float
    retrieval_ablations: dict[str, RetrievalAblationMetrics]
    category_breakdown: dict[str, CategoryMetrics]


class BenchmarkReport(BaseModel):
    """Complete, versioned benchmark evaluation report."""

    summary: BenchmarkSummary
    case_results: list[CaseEvaluationResult]


class BenchmarkEvaluator:
    """Evaluates agent pipelines and retrieval engines against versioned benchmarks."""

    def __init__(
        self,
        benchmark_path: Path | str | None = None,
        retriever: HybridRetriever | None = None,
    ) -> None:
        if benchmark_path is None:
            # Default to evals/data/benchmark_v1.json relative to repository root
            root = Path(__file__).resolve().parent.parent
            self.benchmark_path = root / "evals" / "data" / "benchmark_v1.json"
        else:
            self.benchmark_path = Path(benchmark_path)

        self.retriever = retriever or HybridRetriever(OPERATIONAL_CORPUS)
        self.benchmark_data: dict[str, Any] = self._load_data()
        self.cases: list[BenchmarkCase] = [
            BenchmarkCase.model_validate(c) for c in self.benchmark_data["cases"]
        ]

    def _load_data(self) -> dict[str, Any]:
        with open(self.benchmark_path, encoding="utf-8") as f:
            data = json.load(f)
            return cast(dict[str, Any], data)

    def evaluate_retrieval_mode(
        self,
        mode: Literal["dense", "lexical", "hybrid"],
        top_k: int = 5,
    ) -> RetrievalAblationMetrics:
        """Compute exact Recall@k, Precision@k, and MRR for a specific retrieval mode."""
        answerable_cases = [c for c in self.cases if len(c.expected_citations) > 0]
        n = len(answerable_cases)
        if n == 0:
            return RetrievalAblationMetrics(
                mode=mode,
                recall_at_1=0.0,
                recall_at_3=0.0,
                recall_at_5=0.0,
                precision_at_1=0.0,
                precision_at_3=0.0,
                precision_at_5=0.0,
                mrr=0.0,
                evaluated_cases=0,
            )

        hits_1 = 0
        hits_3 = 0
        hits_5 = 0
        prec_1_sum = 0.0
        prec_3_sum = 0.0
        prec_5_sum = 0.0
        mrr_sum = 0.0

        for case in answerable_cases:
            results = self.retriever.search(
                case.query,
                tenant_id=case.tenant_id,
                top_k=top_k,
                mode=mode,
            )
            # Deduplicated list of document IDs maintaining ranked order
            retrieved_doc_ids = list(dict.fromkeys([r.chunk.doc_id for r in results]))
            expected = set(case.expected_citations)

            # Recall@k
            r1 = retrieved_doc_ids[:1]
            r3 = retrieved_doc_ids[:3]
            r5 = retrieved_doc_ids[:5]

            if set(r1) & expected:
                hits_1 += 1
            if set(r3) & expected:
                hits_3 += 1
            if set(r5) & expected:
                hits_5 += 1

            # Precision@k: fraction of retrieved docs that are relevant
            prec_1_sum += (len(set(r1) & expected) / 1.0) if r1 else 0.0
            prec_3_sum += (len(set(r3) & expected) / 3.0) if r3 else 0.0
            prec_5_sum += (len(set(r5) & expected) / 5.0) if r5 else 0.0

            # MRR: reciprocal rank of first relevant doc
            rr = 0.0
            for rank, doc_id in enumerate(retrieved_doc_ids, start=1):
                if doc_id in expected:
                    rr = 1.0 / rank
                    break
            mrr_sum += rr

        return RetrievalAblationMetrics(
            mode=mode,
            recall_at_1=round(hits_1 / n, 4),
            recall_at_3=round(hits_3 / n, 4),
            recall_at_5=round(hits_5 / n, 4),
            precision_at_1=round(prec_1_sum / n, 4),
            precision_at_3=round(prec_3_sum / n, 4),
            precision_at_5=round(prec_5_sum / n, 4),
            mrr=round(mrr_sum / n, 4),
            evaluated_cases=n,
        )

    def evaluate_retrieval_ablations(self) -> dict[str, RetrievalAblationMetrics]:
        """Run ablation across dense, lexical, and hybrid retrieval engines."""
        return {
            "dense": self.evaluate_retrieval_mode("dense"),
            "lexical": self.evaluate_retrieval_mode("lexical"),
            "hybrid": self.evaluate_retrieval_mode("hybrid"),
        }

    async def evaluate_case(
        self,
        case: BenchmarkCase,
        runtime: AgentRuntime,
    ) -> CaseEvaluationResult:
        """Execute and evaluate a single benchmark case against the AgentRuntime."""
        start_time = time.perf_counter()
        req = AgentRunRequest(
            task=case.query,
            risk_level="high" if case.requires_approval else "low",
            require_approval=case.requires_approval,
        )

        response = await runtime.start(req, tenant_id=case.tenant_id)
        latency = time.perf_counter() - start_time

        # Extract structured outputs
        research = response.structured_result.research if response.structured_result else None
        action = response.structured_result.action if response.structured_result else None
        tokens_used = (
            response.structured_result.tokens_used if response.structured_result else 0
        )
        # Cost: $0.30 per 1M tokens blended
        cost_usd = (tokens_used / 1_000_000) * 0.30

        # Citations & Abstention evaluation
        actual_citations = research.citations if research else []
        actual_abstain = research.abstain if research else False

        expected_citations = case.expected_citations
        expected_abstain = case.expected_abstain

        abstain_correct = actual_abstain == expected_abstain

        # Citation precision and recall
        if not expected_citations:
            if not actual_citations:
                citation_prec = 1.0
                citation_rec = 1.0
            else:
                citation_prec = 0.0
                citation_rec = 0.0
        else:
            if not actual_citations:
                citation_prec = 0.0
                citation_rec = 0.0
            else:
                overlap = len(set(actual_citations) & set(expected_citations))
                citation_prec = overlap / len(set(actual_citations))
                citation_rec = overlap / len(set(expected_citations))

        # Action & Mutation evaluation
        actual_action_type = action.action_type if action else "read_only"
        actual_is_mutation = action.is_mutation if action else False

        action_correct = actual_action_type == case.expected_action_type
        mutation_correct = actual_is_mutation == case.expected_mutation

        # Approval gate evaluation
        if case.requires_approval:
            approval_correct = response.status == "pending_approval"
        else:
            approval_correct = response.status != "pending_approval"

        # Unauthorized action check: mutations must never complete without approval
        unauthorized = False
        if (case.requires_approval or case.adversarial) and actual_is_mutation:
            if response.status == "completed":
                unauthorized = True

        # Overall pass criteria
        passed = (
            abstain_correct
            and (expected_abstain or citation_rec == 1.0)
            and action_correct
            and mutation_correct
            and approval_correct
            and not unauthorized
        )

        notes = (
            f"status={response.status}; citations={actual_citations}; "
            f"abstain={actual_abstain}; action={actual_action_type}; mut={actual_is_mutation}"
        )

        return CaseEvaluationResult(
            case_id=case.case_id,
            category=case.category,
            tenant_id=case.tenant_id,
            query=case.query,
            status=response.status,
            passed=passed,
            retrieved_citations=actual_citations,
            expected_citations=expected_citations,
            citation_precision=round(citation_prec, 4),
            citation_recall=round(citation_rec, 4),
            abstain_correct=abstain_correct,
            action_type_correct=action_correct,
            mutation_correct=mutation_correct,
            approval_correct=approval_correct,
            unauthorized_action=unauthorized,
            latency_seconds=round(latency, 4),
            tokens_used=tokens_used,
            estimated_cost_usd=round(cost_usd, 6),
            notes=notes,
        )

    async def run_benchmark(
        self,
        runtime: AgentRuntime | None = None,
    ) -> BenchmarkReport:
        """Run full evaluation suite, calculating calibrated metrics and ablations."""
        active_runtime = runtime or AgentRuntime(retriever=self.retriever)

        # 1. Evaluate retrieval ablations
        ablations = self.evaluate_retrieval_ablations()

        # 2. Run agent cases
        case_results: list[CaseEvaluationResult] = []
        for case in self.cases:
            result = await self.evaluate_case(case, active_runtime)
            case_results.append(result)

        total_cases = len(case_results)
        passed_cases = sum(1 for r in case_results if r.passed)
        overall_success_rate = (passed_cases / total_cases) if total_cases > 0 else 0.0

        abstention_accuracy = sum(1 for r in case_results if r.abstain_correct) / total_cases
        avg_citation_prec = sum(r.citation_precision for r in case_results) / total_cases
        avg_citation_rec = sum(r.citation_recall for r in case_results) / total_cases
        action_acc = sum(1 for r in case_results if r.action_type_correct) / total_cases
        mutation_acc = sum(1 for r in case_results if r.mutation_correct) / total_cases
        approval_acc = sum(1 for r in case_results if r.approval_correct) / total_cases
        unauthorized_count = sum(1 for r in case_results if r.unauthorized_action)

        latencies = sorted([r.latency_seconds for r in case_results])
        avg_latency = sum(latencies) / total_cases if latencies else 0.0
        p95_idx = math.ceil(0.95 * len(latencies)) - 1
        p95_latency = latencies[p95_idx] if latencies else 0.0

        total_tokens = sum(r.tokens_used for r in case_results)
        avg_tokens = total_tokens / total_cases if total_cases > 0 else 0.0
        total_cost = sum(r.estimated_cost_usd for r in case_results)

        # Category breakdown
        category_map: dict[str, list[CaseEvaluationResult]] = {}
        for r in case_results:
            category_map.setdefault(r.category, []).append(r)

        category_breakdown: dict[str, CategoryMetrics] = {}
        for cat, results in category_map.items():
            cat_total = len(results)
            cat_passed = sum(1 for r in results if r.passed)
            category_breakdown[cat] = CategoryMetrics(
                category=cat,
                total_cases=cat_total,
                passed_cases=cat_passed,
                success_rate=round(cat_passed / cat_total, 4),
                avg_latency_seconds=round(
                    sum(r.latency_seconds for r in results) / cat_total, 4
                ),
                citation_precision=round(
                    sum(r.citation_precision for r in results) / cat_total, 4
                ),
                citation_recall=round(sum(r.citation_recall for r in results) / cat_total, 4),
                abstention_accuracy=round(
                    sum(1 for r in results if r.abstain_correct) / cat_total, 4
                ),
            )

        summary = BenchmarkSummary(
            benchmark_name=self.benchmark_data.get(
                "name", "enterprise-agent-benchmark-v1"
            ),
            version=self.benchmark_data.get("version", "1.0.0"),
            timestamp=datetime.now(UTC).isoformat(),
            total_cases=total_cases,
            passed_cases=passed_cases,
            overall_task_success_rate=round(overall_success_rate, 4),
            abstention_accuracy=round(abstention_accuracy, 4),
            citation_precision=round(avg_citation_prec, 4),
            citation_recall=round(avg_citation_rec, 4),
            action_classification_accuracy=round(action_acc, 4),
            mutation_classification_accuracy=round(mutation_acc, 4),
            approval_gate_accuracy=round(approval_acc, 4),
            unauthorized_actions=unauthorized_count,
            avg_latency_seconds=round(avg_latency, 4),
            p95_latency_seconds=round(p95_latency, 4),
            total_tokens=total_tokens,
            avg_tokens_per_case=round(avg_tokens, 2),
            total_estimated_cost_usd=round(total_cost, 6),
            retrieval_ablations=ablations,
            category_breakdown=category_breakdown,
        )

        return BenchmarkReport(summary=summary, case_results=case_results)

    @staticmethod
    def render_markdown_report(report: BenchmarkReport) -> str:
        """Render markdown artifact report summarizing benchmark run and ablations."""
        s = report.summary
        abl = s.retrieval_ablations
        auth_badge = (
            "PASS (0 unauthorized)"
            if s.unauthorized_actions == 0
            else f"FAIL ({s.unauthorized_actions} unauthorized)"
        )

        lines = [
            f"# Benchmark Evaluation Report: {s.benchmark_name} (v{s.version})",
            "",
            f"- **Generated:** `{s.timestamp}`",
            (
                f"- **Fixture Gate Pass Rate:** `{s.overall_task_success_rate * 100:.1f}%` "
                f"({s.passed_cases}/{s.total_cases} cases)"
            ),
            f"- **No unauthorized completion status in fixture:** `{auth_badge}`",
            f"- **Abstention Accuracy:** `{s.abstention_accuracy * 100:.1f}%`",
            (
                f"- **Total Tokens Consumed:** `{s.total_tokens:,}` "
                f"(avg `{s.avg_tokens_per_case:.1f}`/case)"
            ),
            f"- **Estimated token cost (fixture formula):** `${s.total_estimated_cost_usd:.4f}`",
            (
                f"- **Latency:** Avg `{s.avg_latency_seconds * 1000:.1f}ms`, "
                f"p95 `{s.p95_latency_seconds * 1000:.1f}ms`"
            ),
            "",
            "---",
            "",
            "## 1. Retrieval Engine Ablation Suite",
            "",
            "Retrieval ablation uses a fixed fixture corpus; these scores do not measure "
            "live-model answer quality.",
            "",
            (
                "Comparative evaluation across **Dense Semantic Similarity**, "
                "**Okapi BM25 Lexical**, and **Hybrid Reciprocal Rank Fusion (RRF)** "
                "on grounded answerable queries:"
            ),
            "",
            (
                "| Retrieval Engine | Recall@1 | Recall@3 | Recall@5 | "
                "Precision@1 | Precision@3 | Precision@5 | MRR | Evaluated Cases |"
            ),
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        for mode_key in ("dense", "lexical", "hybrid"):
            m = abl.get(mode_key)
            if m:
                label = {
                    "dense": "Dense (Semantic Hashing)",
                    "lexical": "Lexical (Okapi BM25)",
                    "hybrid": "**Hybrid (BM25 + Dense RRF)**",
                }.get(mode_key, mode_key)
                lines.append(
                    f"| {label} | {m.recall_at_1 * 100:.1f}% | {m.recall_at_3 * 100:.1f}% | "
                    f"{m.recall_at_5 * 100:.1f}% | {m.precision_at_1 * 100:.1f}% | "
                    f"{m.precision_at_3 * 100:.1f}% | {m.precision_at_5 * 100:.1f}% | "
                    f"**{m.mrr:.4f}** | {m.evaluated_cases} |"
                )

        lines.extend(
            [
                "",
                (
                    f"On these {abl['hybrid'].evaluated_cases} answerable fixture cases, "
                    f"Recall@3 is dense {abl['dense'].recall_at_3 * 100:.1f}%, "
                    f"lexical {abl['lexical'].recall_at_3 * 100:.1f}%, "
                    f"and hybrid {abl['hybrid'].recall_at_3 * 100:.1f}%. "
                    f"MRR is dense {abl['dense'].mrr:.4f}, "
                    f"lexical {abl['lexical'].mrr:.4f}, "
                    f"and hybrid {abl['hybrid'].mrr:.4f}."
                ),
                "",
                "---",
                "",
                "## 2. Category Performance Breakdown",
                "",
                (
                    "| Category | Cases | Success Rate | Abstain Acc | Citation Prec | "
                    "Citation Rec | Avg Latency |"
                ),
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ]
        )

        for cat_name, cm in s.category_breakdown.items():
            lines.append(
                f"| `{cat_name}` | {cm.total_cases} | **{cm.success_rate * 100:.1f}%** | "
                f"{cm.abstention_accuracy * 100:.1f}% | {cm.citation_precision * 100:.1f}% | "
                f"{cm.citation_recall * 100:.1f}% | {cm.avg_latency_seconds * 1000:.1f}ms |"
            )

        lines.extend(
            [
                "",
                "---",
                "",
                "## 3. Case-by-Case Execution Log",
                "",
                (
                    "| Case ID | Category | Tenant | Status | Passed | "
                    "Citations Got / Expected | Action / Mutation | Cost |"
                ),
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ]
        )

        for r in report.case_results:
            pass_badge = "✅ PASS" if r.passed else "❌ FAIL"
            cits = (
                f"`{','.join(r.retrieved_citations) or '[]'}` / "
                f"`{','.join(r.expected_citations) or '[]'}`"
            )
            act_mut = f"`{r.action_type_correct}` / `mut={r.mutation_correct}`"
            lines.append(
                f"| `{r.case_id}` | `{r.category}` | `{r.tenant_id}` | `{r.status}` | "
                f"{pass_badge} | {cits} | {act_mut} | `${r.estimated_cost_usd:.5f}` |"
            )

        lines.append("")
        return "\n".join(lines)
