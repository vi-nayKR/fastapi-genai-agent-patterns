"""Recompute judge agreement from the existing live report after blind human labelling."""

import json

from evals.evaluator import ROOT, render_report, validate_judge


def main() -> None:
    path = ROOT / "results/triage_live.json"
    if not path.exists():
        raise SystemExit("Live judge pending: run make eval-live when model service is available.")
    report = json.loads(path.read_text(encoding="utf-8"))
    report["judge"] = validate_judge(report["judge"])
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    path.with_suffix(".md").write_text(render_report(report), encoding="utf-8")
    print(
        json.dumps(
            {
                key: report["judge"][key]
                for key in (
                    "validation_status",
                    "human_labelled_cases",
                    "agreement",
                    "disagreements",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
