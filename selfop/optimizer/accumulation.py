from __future__ import annotations

"""Gradient accumulation (paper §3.3) — GradientOptimizer + gradient accumulation.

Phases 1 and 2 are identical to GradientOptimizer: per-task trajectory analysis
(agent_home-blind) followed by per-task orchestration analysis
(agent_home-aware), composed into analysis.txt.

Phase 2.5: runs the gradient accumulation pipeline from
selfop/accumulation/accumulator.py on the composed analyses, producing a
ranked/filtered report of cross-task strengths and improvements.

Phase 3: a modified main optimizer that reads the accumulated report
as its primary input, with per-task drill-down tools still available.
"""

from pathlib import Path

from selfop.optimizer.gradient import GradientOptimizer, TIMEOUT_MAIN
from selfop.policy import AGENT_HOME_DESCRIPTION
from selfop.runner.codex import CodexRunner
from selfop.accumulation.accumulator import load_gradients, accumulate


# ── Prompts ───────────────────────────────────────────────────────────

MAIN_SYSTEM_PROMPT = """\
You are an agent optimizer. Your job is to improve the agent orchestration so \
that the agent performs better on a given task.

{agent_home_description}

# YOUR WORKSPACE

```
workspace/
├── agent_home/                           ← the agent's home directory, that you will be editing
├── steps/                                ← the steps directory, that contains the results of the step runs
│   └── step_N/
│       └── <task_id>/
│           ├── workspace/                ← the workspace directory of the task
│           ├── meta/                     ← task metadata files
│           ├── score.json                ← per-field correctness scores
│           └── trace.json                ← full agent's execution trace
├── analysis_runs/                        ← pre-computed per-task analyses + accumulated report
│   └── step_N/
│       ├── accumulated_report.txt        ← accumulated gradient report (READ THIS FIRST)
│       └── <task_id>/
│           └── analysis.txt              ← individual task analysis (score + trajectory + orchestration)
├── show_analysis.sh                      ← drill-down: bash show_analysis.sh <id1> [id2 ...]
├── show_datapoint.sh                     ← drill-down: bash show_datapoint.sh <task_id>
├── policy_checker.sh                     ← check if the edited agent_home/ follows policy.md
└── policy.md                             ← agent's home directory editing guidelines
```

# IMPORTANT: ACCUMULATED GRADIENT REPORT

An **accumulated gradient report** has been pre-computed from all independent per-task analyses in \
the given step (step_N) and saved to `analysis_runs/step_N/accumulated_report.txt`. This is your \
PRIMARY input and it contains the following information:

1. **Agent Home Compliance** — a summary of how consistently the agent used/followed \
the orchestration artifacts across all tasks in the given step.
2. **Strengths** — cross-task orchestration patterns that contributed to success, ranked by \
prevalence and association with successful outcomes.
3. **Improvements** — cross-task orchestration gaps/issues and suggested improvements ranked by prevalence 
and association with failure. Each improvement includes supporting observations from specific tasks, \
so you can trace patterns back to concrete examples.

# TASK TO OPTIMIZE THE AGENT FOR

{task_description}

### TASK-SOLVING AGENT'S WORKSPACE

When the agent starts a task instance, it is given a workspace with the task-specific \
files/artifacts it needs. Understanding this workspace should help you reason about what the \
agent saw and how it should approach the problem.

{task_workspace_description}

# YOUR WORKFLOW

**Pre-requisites** (for the first step run):
1. Read the `policy.md` file to understand the policies to edit the agent's home directory.
2. Read/explore the current `agent_home/` directory to understand the current state of the \
agent's orchestration.

**Workflow** (for each step run):
1. When a new step runs with the `agent_home/` orchestration, you will be provided a summary \
of the step run results in the user message, and the step artifacts will be available in the \
`steps/` directory. However, the pre-computed accumulated gradient report, and per-task analyses \
will be available in the `analysis_runs/` directory.
2. Start by reading the accumulated gradient report: `analysis_runs/step_N/accumulated_report.txt` (the \
path with the correct step number of the latest step run will be provided in the user message). \
This gives you an accumulated analysis view of the step run results, and their cross-task patterns \
(strengths and improvements) that you should focus on.
3. If you need more detail on a specific task mentioned in the report, you can always drill down with \
`bash show_analysis.sh <id1> [id2 ...]` to see the full per-task analysis, or \
`bash show_datapoint.sh <task_id>` for raw trace + score + meta of a specific task.
4. Based on the accumulated patterns, edit the agent's home directory such that the agent's \
orchestration is improved for the given task and follows the policies defined in `policy.md`.
5. Keep in mind the past edits on previous step runs as well, and try not to overfit to a specific \
step run. Our goal is to improve the agent's orchestration for the given task in a generalizable way, \
so that the agent performs better in the future unseen scenarios of the given task.
6. Use `bash policy_checker.sh` to check if the edited agent's home directory follows the \
syntactical/structural guidelines defined in `policy.md`. If there are any \
issues, fix them before finalizing the edit and returning final text.
7. Briefly summarize what you changed and why in the final text.
"""


def _accum_main_user_prompt(step_dir_name: str, step_scores: str) -> str:
    step_num = int(step_dir_name.replace("step_", ""))
    return "\n".join([
        f"New step results available at `steps/{step_dir_name}/`\n",
        step_scores + "\n",
        f"An accumulated gradient report has been saved to "
        f"`analysis_runs/step_{step_num}/accumulated_report.txt`.\n",
        "Read it first — it contains ranked cross-task patterns (strengths and improvements). "
        "If needed, you can drill down into individual tasks with the following commands:\n",
        "- `bash show_analysis.sh <id1> [id2 ...]` — per-task analysis "
        "(score + trajectory + orchestration-level) for one or more tasks",
        "- `bash show_datapoint.sh <task_id>` — raw trace + score + meta of a specific task\n",
        "Read the accumulated report, do your analysis, and improve the agent's orchestration.",
    ])


# ── Optimizer ─────────────────────────────────────────────────────────

class AccumulationOptimizer(GradientOptimizer):
    """GradientOptimizer + gradient accumulation between per-task analysis and main optimizer.

    Phases 1 & 2 are inherited from GradientOptimizer unchanged.
    Phase 2.5 runs the gradient accumulation pipeline.
    Phase 3 uses the accumulated report as primary input."""

    name = "accumulation"

    # ── Phase 2.5: gradient accumulation ──────────────────────────────

    async def _run_accumulation(
        self, step_dir: Path, step_ids: list[str],
    ) -> str:
        step_num = int(step_dir.name.replace("step_", ""))
        analysis_step_dir = self.workspace_dir / "analysis_runs" / f"step_{step_num}"
        report_path = analysis_step_dir / "accumulated_report.txt"

        if report_path.exists() and report_path.stat().st_size > 0:
            print(f"[selfop] Phase 2.5: Cached accumulated report found, skipping.")
            return report_path.read_text()

        cache_dir = self.workspace_dir / "accumulation_cache" / f"step_{step_num}"

        gradients = load_gradients(self.workspace_dir / "analysis_runs", step_num)
        result = await accumulate(
            gradients, step_num,
            model=self.config.accum_model,
            reasoning=self.config.accum_reasoning,
            num_workers=self.config.num_workers,
            chunk_size=self.config.accum_chunk_size,
            min_support=self.config.accum_min_support,
            min_support_ratio_strength=self.config.accum_min_support_ratio_strength,
            min_support_ratio_improvement=self.config.accum_min_support_ratio_improvement,
            min_composite_strength=self.config.accum_min_composite_strength,
            min_composite_improvement=self.config.accum_min_composite_improvement,
            cache_dir=cache_dir,
            summarize_clusters=True,
        )

        report = result["report"]
        report_path.write_text(report)
        return report

    # ── Phase 3: main optimizer (accumulated) ─────────────────────────

    async def _run_main_optimizer(
        self, step_dir: Path, step_ids: list[str],
        session_id: str | None = None,
    ) -> dict:
        runner = CodexRunner()

        log_path = self.workspace_dir.parent / f"optimizer_{step_dir.name}.log"
        trace_path = self.workspace_dir.parent / f"optimizer_trace_{step_dir.name}.json"

        if trace_path.exists():
            return {
                "log_path": str(log_path),
                "trace_path": str(trace_path),
                "final_text": "(main optimizer run already completed)",
                "session_id": session_id,
            }

        step_scores = self.task.format_batch_scores(step_dir, step_ids)
        usr_prompt = _accum_main_user_prompt(step_dir.name, step_scores)

        print(f"\n{'─'*60}")
        print(f"[Phase 3] User prompt to main optimizer:")
        print(f"{'─'*60}")
        print(usr_prompt)
        print(f"{'─'*60}\n")

        sys_prompt = MAIN_SYSTEM_PROMPT.format(
            task_description=self.task.task_description(),
            task_workspace_description=self.task.task_workspace_description(),
            skill_name=self.config.skill_name,
            agent_home_description=AGENT_HOME_DESCRIPTION.format(
                skill_name=self.config.skill_name,
            ),
        ) if session_id is None else None

        result, thread_id = await runner.run_persistent(
            prompt=usr_prompt,
            session_id=session_id,
            workspace_dir=self.workspace_dir,
            model=self.config.optimizer_model,
            reasoning=self.config.optimizer_reasoning,
            system_prompt=sys_prompt,
            sandbox="workspace-write",
            log_path=log_path,
            messages_path=trace_path,
            timeout=TIMEOUT_MAIN,
            model_provider=self.config.model_provider,
        )

        return {
            "log_path": str(log_path),
            "trace_path": str(trace_path),
            "final_text": result.final_text,
            "session_id": thread_id,
        }

    # ── Public interface ──────────────────────────────────────────────

    async def run(
        self,
        *,
        step_dir: Path,
        step_ids: list[str],
        session_id: str | None = None,
    ) -> dict:
        print(f"[selfop] Phase 1: Running {len(step_ids)} trajectory analyses...")
        phase1_results = await self._run_all_phase1(step_dir, step_ids)

        print(f"[selfop] Phase 2: Running {len(step_ids)} gradient analyses...")
        phase2_results = await self._run_all_phase2(step_dir, step_ids)

        print("[selfop] Phase 2.5: Running gradient accumulation...")
        await self._run_accumulation(step_dir, step_ids)

        print("[selfop] Phase 3: Running main optimizer (accumulated report + agent_home update)...")
        main_result = await self._run_main_optimizer(step_dir, step_ids, session_id)
        print("[selfop] Done.")

        return {
            "optimizer": self.name,
            "phase1_results": phase1_results,
            "phase2_results": phase2_results,
            **main_result,
        }
