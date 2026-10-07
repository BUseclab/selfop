"""CyberGym helpers — scoring, PoC verification, result display."""

from __future__ import annotations

import json
import httpx
from pathlib import Path
from typing import Optional

from cybergym.server.pocdb import PoCRecord, Session, init_engine


def sanitize_task_id(task_id: str) -> str:
    """Replace colons with underscores for filesystem-safe directory names."""
    return task_id.replace(":", "_")


def load_result_meta(output_dir: Path, task_id: str) -> Optional[dict]:
    """Load result_meta.json for a task. Returns None if missing or corrupt."""
    path = output_dir / sanitize_task_id(task_id) / "result_meta.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def verify_agent(agent_id: str, server: str, api_key: str) -> dict:
    """POST /verify-agent-pocs to trigger server-side PoC verification."""
    with httpx.Client(base_url=server, timeout=1200) as c:
        try:
            resp = c.post(
                "/verify-agent-pocs",
                json={"agent_id": agent_id},
                headers={"X-API-Key": api_key},
            )
            return {"status": "completed", "output": resp.text}
        except httpx.ReadTimeout:
            return {"status": "timeout", "output": ""}
        except Exception as e:
            return {"status": "error", "output": str(e)}


def load_poc_results(pocdb_path: Path, agent_id: str) -> list[dict]:
    """Query the PoC SQLite DB for all submissions by agent_id."""
    try:
        engine = init_engine(pocdb_path)
        with Session(engine) as session:
            return [
                {
                    "poc_id": p.poc_id,
                    "vul_exit_code": p.vul_exit_code,
                    "fix_exit_code": p.fix_exit_code,
                    "poc_length": p.poc_length,
                }
                for p in session.query(PoCRecord)
                    .filter(PoCRecord.agent_id == agent_id)
                    .all()
            ]
    except Exception:
        return []


def redact_trace(messages: list[dict], max_chars: int = 1000) -> str:
    """Summarise a Codex NDJSON trace for optimizer context (truncated)."""
    lines: list[str] = []
    for evt in (messages or []):
        if evt.get("type") != "item.completed":
            continue
        item = evt.get("item", {})
        kind = item.get("type", "")
        if kind == "agent_message":
            lines.append(f"[agent] {item.get('text', '')[:max_chars]}")
        elif kind == "function_call":
            lines.append(f"[tool:{item.get('name', '?')}] {item.get('output', '')[:max_chars]}")
    return "\n".join(lines) or "(no trace available)"


# ── Scoring ───────────────────────────────────────────────────────────

def read_scores(output_dir: Path, task_ids: list[str]) -> dict[str, bool]:
    """Read score.json for each task. Returns {task_id: overall_bool}."""
    scores: dict[str, bool] = {}
    for tid in task_ids:
        path = output_dir / sanitize_task_id(tid) / "score.json"
        if not path.exists():
            scores[tid] = False
            continue
        try:
            scores[tid] = bool(json.loads(path.read_text()).get("success", False))
        except (OSError, json.JSONDecodeError):
            scores[tid] = False
    return scores


def read_score_fields(output_dir: Path, task_id: str) -> dict:
    """Read per-PoC fields from a single task's score.json."""
    path = output_dir / sanitize_task_id(task_id) / "score.json"
    if path.exists():
        try:
            return json.loads(path.read_text()).get("fields", {})
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def print_results(
    output_dir: Path, task_ids: list[str], scores: dict[str, bool],
) -> None:
    """Pretty-print a results table to stdout."""
    tick = lambda v: "\u2713" if v else "\u2717"  # noqa: E731
    print(f"\n{'ID':<35} {'ok':^4}  PoCs")
    print("-" * 60)
    for tid in task_ids:
        fields = read_score_fields(output_dir, tid)
        ok = scores.get(tid, False)
        n_correct = sum(1 for p in fields.values() if p.get("success"))
        print(f"{tid:<35} {tick(ok):^4}  {n_correct}/{len(fields)}")
    print("-" * 60)
    total = len(task_ids)
    correct = sum(scores.values())
    print(
        f"Accuracy: {correct}/{total}  ({correct / total:.1%})"
        if total else "Accuracy: 0/0"
    )
