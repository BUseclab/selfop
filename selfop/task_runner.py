"""
Run a task's forward pass + evaluation on a data split.

Creates an isolated workspace with a clean copy of agent_home,
runs inference + evaluation, and saves scores.

Usage:
    selfop eval \
        --task cybergym \
        --agent-home results/gpt-5.4-mini/step_8 \
        --eval-dir   outputs/eval_gpt-5.4-mini_step_8 \
        --split test

Output layout:
    <eval-dir>/
    ├── agent_home/         # clean copy (skills/, agents/, config.toml, auth)
    ├── runs/               # per-task forward-pass + evaluation artifacts
    └── eval_scores.json    # {task_id: bool}
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from dotenv import load_dotenv

from selfop.config import PipelineConfig
from tasks.base import Task


# ── Internals ─────────────────────────────────────────────────────────

def _clone_agent_home(
    src: Path, dst: Path, *, skill_name: str, agent: str,
) -> Path:
    """Copy only clean agent_home files (skills/, agents/, config.toml) + auth."""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    skills_src = src / "skills" / skill_name
    agents_src = src / "agents"
    config_toml = src / "config.toml"

    if skills_src.exists():
        shutil.copytree(skills_src, dst / "skills" / skill_name)
    if agents_src.exists():
        shutil.copytree(agents_src, dst / "agents")
    if config_toml.exists():
        shutil.copy2(config_toml, dst / "config.toml")

    auth_in_src = src / "auth.json"
    if auth_in_src.exists():
        shutil.copy2(auth_in_src, dst / "auth.json")
    elif agent == "codex":
        auth_sys = Path.home() / ".codex" / "auth.json"
        if not auth_sys.exists():
            raise FileNotFoundError(f"No auth.json in source or at {auth_sys}")
        shutil.copy2(auth_sys, dst / "auth.json")

    return dst


# ── Public API ────────────────────────────────────────────────────────

def evaluate(
    config: PipelineConfig,
    task: Task,
    agent_home_src: Path,
    eval_ids: list[str],
    eval_dir: Path,
    *,
    populate_meta: bool = False,
) -> dict[str, bool]:
    """Run forward + evaluation with clean isolation.

    Copies agent_home into eval_dir/agent_home/, runs tasks into
    eval_dir/runs/, writes eval_dir/eval_scores.json.

    If populate_meta=True, also writes task metadata used by the optimizer.

    Returns {task_id: bool} scores.
    """
    eval_dir = Path(eval_dir)
    eval_dir.mkdir(parents=True, exist_ok=True)

    cloned_home = _clone_agent_home(
        agent_home_src,
        eval_dir / "agent_home",
        skill_name=config.skill_name,
        agent=config.agent,
    )
    print(f"[eval] Cloned agent_home -> {cloned_home}")

    eval_config = PipelineConfig(
        run_dir=eval_dir,
        model=config.model,
        agent=config.agent,
        reasoning=config.reasoning,
        num_workers=config.num_workers,
        skill_name=config.skill_name,
        model_provider=config.model_provider,
    )
    eval_config.agent_home_dir = cloned_home

    runs_dir = eval_dir / "runs"
    runs_dir.mkdir(exist_ok=True)

    print(f"[eval] Running {len(eval_ids)} tasks ...")

    task.run_forward(eval_config, runs_dir, eval_ids)
    task.run_evaluation(eval_config, runs_dir, eval_ids)
    if populate_meta:
        task.populate_task_meta(runs_dir, eval_ids)

    scores = task.read_scores(runs_dir, eval_ids)
    scores_file = eval_dir / "eval_scores.json"
    scores_file.write_text(json.dumps(scores, indent=2))
    print(f"[eval] Scores saved to {scores_file}")

    batch_scores = task.format_batch_scores(runs_dir, eval_ids)
    print(batch_scores)

    return scores


# ── CLI ───────────────────────────────────────────────────────────────

def main() -> None:
    """selfop eval [options]"""
    load_dotenv()

    p = argparse.ArgumentParser(
        description="Run a task's forward pass + evaluation on a data split.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--task", required=True,
                    help="Task name (e.g. 'cybergym').")
    p.add_argument("--agent-home", type=Path, required=True,
                    help="Source agent_home (treated as read-only).")
    p.add_argument("--eval-dir", type=Path, required=True,
                    help="Output directory for this eval run.")
    p.add_argument("--split", default="test",
                    choices=["train", "validation", "test"])
    p.add_argument("--model", default="gpt-5.4-mini")
    p.add_argument("--agent", default="codex", choices=["codex"])
    p.add_argument("--reasoning", default="high")
    p.add_argument("--num-workers", type=int, default=8)
    p.add_argument("--model-provider", default=None,
                    help="Model provider name from config.toml (e.g. 'myollama').")
    args = p.parse_args()

    agent_home_src = args.agent_home.resolve()
    if not agent_home_src.exists():
        raise FileNotFoundError(f"agent_home not found: {agent_home_src}")

    from tasks import get_task
    task = get_task(args.task)
    task.setup()

    cfg = task.cfg

    config = PipelineConfig(
        run_dir=args.eval_dir,
        model=args.model,
        agent=args.agent,
        reasoning=args.reasoning,
        num_workers=args.num_workers,
        skill_name=cfg.skill_name,
        initial_home=cfg.initial_home,
        model_provider=args.model_provider,
    )

    data = task.load_data_ids()
    eval_ids = data[args.split]
    print(f"[eval] Task={args.task}  skill={cfg.skill_name}  split={args.split}  n={len(eval_ids)}")

    scores = evaluate(config, task, agent_home_src, eval_ids, args.eval_dir)

    total = len(scores)
    correct = sum(scores.values())
    print(f"\n[eval] Final: {correct}/{total} ({correct / total:.1%})")


if __name__ == "__main__":
    main()
