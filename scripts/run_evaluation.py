"""CLI runner to execute enterprise evaluation benchmark and generate reports.

Outputs versioned reports to:
  - evals/reports/benchmark_v1_report.json
  - evals/reports/benchmark_v1_report.md
"""

import argparse
import asyncio
import sys
from pathlib import Path

from evals.evaluator import BenchmarkEvaluator


def main() -> int:
    parser = argparse.ArgumentParser(description="Run agent evaluation benchmark suite")
    parser.add_argument(
        "--data",
        type=str,
        default=None,
        help="Path to evaluation benchmark JSON dataset",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="evals/reports",
        help="Directory to save generated evaluation reports",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("================================================================================")
    print("🚀 Running Enterprise GenAI Agent Evaluation Benchmark")
    print("================================================================================")

    evaluator = BenchmarkEvaluator(benchmark_path=args.data)
    print(f"Loaded benchmark dataset: {evaluator.benchmark_path.name}")
    print(f"Total evaluation cases: {len(evaluator.cases)}")

    print("\n[1/2] Computing Retrieval Engine Ablations (Dense vs Lexical vs Hybrid)...")
    ablations = evaluator.evaluate_retrieval_ablations()
    d_m = ablations["dense"]
    l_m = ablations["lexical"]
    h_m = ablations["hybrid"]
    print(f"  - Dense Semantic Recall@3: {d_m.recall_at_3 * 100:.1f}%, MRR: {d_m.mrr:.4f}")
    print(f"  - Lexical BM25 Recall@3:   {l_m.recall_at_3 * 100:.1f}%, MRR: {l_m.mrr:.4f}")
    print(f"  - Hybrid RRF Recall@3:     {h_m.recall_at_3 * 100:.1f}%, MRR: {h_m.mrr:.4f}")

    print("\n[2/2] Executing Multi-Specialist Agent Runs across 30 benchmark cases...")
    report = asyncio.run(evaluator.run_benchmark())

    # Write output reports
    json_path = output_dir / "benchmark_v1_report.json"
    md_path = output_dir / "benchmark_v1_report.md"

    with open(json_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    markdown_content = evaluator.render_markdown_report(report)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    print("\n================================================================================")
    print("📊 Benchmark Evaluation Summary")
    print("================================================================================")
    s = report.summary
    print(f"Benchmark:                     {s.benchmark_name} (v{s.version})")
    print(
        f"Overall Task Success Rate:     {s.overall_task_success_rate * 100:.1f}% "
        f"({s.passed_cases}/{s.total_cases})"
    )
    print(f"Abstention Accuracy:           {s.abstention_accuracy * 100:.1f}%")
    print(
        f"Citation Precision / Recall:   {s.citation_precision * 100:.1f}% / "
        f"{s.citation_recall * 100:.1f}%"
    )
    print(
        f"Action / Mutation Accuracy:    {s.action_classification_accuracy * 100:.1f}% / "
        f"{s.mutation_classification_accuracy * 100:.1f}%"
    )
    auth_status = "PASS (0)" if s.unauthorized_actions == 0 else f"FAIL ({s.unauthorized_actions})"
    print(f"Zero Unauthorized Actions:     {auth_status}")
    print(
        f"Latency (Avg / p95):           {s.avg_latency_seconds * 1000:.1f}ms / "
        f"{s.p95_latency_seconds * 1000:.1f}ms"
    )
    print(f"Tokens Consumed (Total / Avg): {s.total_tokens:,} / {s.avg_tokens_per_case:.1f}")
    print(f"Estimated Cost (Total):        ${s.total_estimated_cost_usd:.4f}")

    print("\nCategory Breakdown:")
    for cat, m in s.category_breakdown.items():
        print(
            f"  - {cat:<24} {m.passed_cases}/{m.total_cases} passed "
            f"({m.success_rate * 100:.0f}%) | Latency: {m.avg_latency_seconds * 1000:.1f}ms"
        )

    print("\nGenerated Reports:")
    print(f"  - JSON: {json_path}")
    print(f"  - Markdown: {md_path}")
    print("================================================================================")

    if s.unauthorized_actions > 0 or s.overall_task_success_rate < 0.90:
        print("❌ Benchmark execution failed quality gates.", file=sys.stderr)
        return 1

    print("✅ Benchmark execution passed all verification criteria.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
