from __future__ import annotations

import json
from pathlib import Path

OutcomeKey = str  # "correct" | "incorrect"


def batch_accuracy(scores: dict[str, bool]) -> float:
    if not scores:
        return 0.0
    return sum(scores.values()) / len(scores)


def classify_outcomes(scores: dict[str, bool]) -> dict[OutcomeKey, list[str]]:
    out: dict[OutcomeKey, list[str]] = {"correct": [], "incorrect": []}
    for data_id, ok in scores.items():
        out["correct" if ok else "incorrect"].append(data_id)
    return out


def sanitize_data_id(data_id: str) -> str:
    return data_id.replace(":", "_")


def read_scores(run_output_dir: Path, data_ids: list[str]) -> dict[str, bool]:
    """Read score.json files from a run output directory."""
    scores: dict[str, bool] = {}
    for data_id in data_ids:
        score_path = Path(run_output_dir) / sanitize_data_id(data_id) / "score.json"
        if not score_path.exists():
            scores[data_id] = False
            continue
        try:
            scores[data_id] = bool(json.loads(score_path.read_text()).get("success", False))
        except (OSError, json.JSONDecodeError):
            scores[data_id] = False
    return scores


def read_score_fields(output_dir: Path, data_id: str) -> dict[str, dict]:
    score_path = Path(output_dir) / sanitize_data_id(data_id) / "score.json"
    if not score_path.exists():
        return {}
    try:
        return json.loads(score_path.read_text()).get("fields", {})
    except (OSError, json.JSONDecodeError):
        return {}
