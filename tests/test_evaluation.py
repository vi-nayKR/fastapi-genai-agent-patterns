"""Small runnable checks for corpus reproducibility and agreement math."""

import json
from pathlib import Path

import pytest

from evals import evaluator
from evals.evaluator import agreement
from scripts.generate_incidents import generate


def test_generated_corpus_matches_commit_and_split() -> None:
    rows = json.loads(Path("evals/data/incidents.json").read_text())
    assert generate() == rows
    assert sum(r["split"] == "history" for r in rows) == 200
    assert sum(r["split"] == "test" for r in rows) == 50
    assert len({r["log"] for r in rows}) == len(rows)


def test_agreement_math() -> None:
    assert agreement([1, 3, 5], [1, 3, 5]) == {"exact_match": 1, "within_one": 1, "cohens_kappa": 1}
    result = agreement([1, 1, 5, 5], [1, 5, 1, 5])
    assert result == {"exact_match": 0.5, "within_one": 0.5, "cohens_kappa": 0}
    assert agreement([3], [4])["within_one"] == 1
    assert agreement([5], [5])["cohens_kappa"] is None  # Constant marginals make kappa undefined.
    with pytest.raises(ValueError):
        agreement([1], [1, 2])


def test_frozen_judge_validation_preserves_scores_and_reports_disagreements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scores = [
        {"id": f"REVIEW-{i:03d}", "score": i % 5 + 1, "rationale": "judge fixture"}
        for i in range(15)
    ]
    labels = {
        r["id"]: {"score": r["score"], "would_apply": "yes", "rationale": "human fixture"}
        for r in scores
    }
    labels["REVIEW-000"]["score"] = 2
    labels["REVIEW-001"]["score"] = 5
    monkeypatch.setattr(evaluator, "read_human_labels", lambda: labels)
    result = evaluator.validate_judge({"validation_scores": scores})
    assert result["validation_status"] == "complete"
    assert result["agreement"]["exact_match"] == pytest.approx(13 / 15)
    assert result["agreement"]["within_one"] == pytest.approx(14 / 15)
    assert [r["id"] for r in result["disagreements"]] == ["REVIEW-000", "REVIEW-001"]
    assert result["disagreements"][0]["human"]["rationale"] == "human fixture"
    assert scores[0]["score"] == 1 and scores[1]["score"] == 2
