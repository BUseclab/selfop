from __future__ import annotations

"""SelfOp — ConvergenceOptimizer + coverage-annotated (hard/soft) gradient reports.

Extends ConvergenceOptimizer by feeding coverage classification results back into the
accumulated report before Phase 3. Each improvement theme is annotated
with a gradient type:

  Hard gradient (gap):    The skill does NOT contain specific guidance for
                          this failure pattern. The optimizer should make
                          substantial changes — new instructions, new
                          sections, new reference files.

  Soft gradient (covered): The skill ALREADY addresses this pattern with
                           specific instructions, but the agent still fails.
                           The optimizer should only refine — clarify wording,
                           add examples, strengthen emphasis, add edge cases.

Pipeline difference from ConvergenceOptimizer:
  Phase 2.5  accumulation runs but does NOT write the report yet.
  Phase 2.75 classification runs (coverage classifier required).
  Phase 2.8  re-renders the report with gradient annotations.
  Phase 3    uses a gradient-aware system prompt.

Inherits all convergence gating, expand-in-place, and SNR logic.
"""

import asyncio
from pathlib import Path

from selfop.optimizer.convergence import ConvergenceOptimizer
from selfop.policy import AGENT_HOME_DESCRIPTION
from selfop.runner.codex import CodexRunner
from selfop.optimizer.gradient import TIMEOUT_MAIN
from selfop.accumulation.accumulator import render_report


# ── Prompts ───────────────────────────────────────────────────────────

SELFOP_MAIN_SYSTEM_PROMPT = """\
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
3. **Improvements** — cross-task orchestration gaps/issues and suggested improvements ranked by prevalence \
and association with failure. Each improvement includes supporting observations from specific tasks, \
so you can trace patterns back to concrete examples.

Each improvement is also annotated with a **gradient type** that determines how you should address it:

## Gradient Types

### Hard Gradient
The agent home has a GAP: it does not contain specific guidance \
for this failure pattern. This is a genuine missing capability in the agent home. \
Addressing it MAY require substantial (structural or content) changes in the agent home, but \
within the scope defined in the policy.md file.

### Soft Gradient
The agent home already contains instructions that target this failure \
pattern, but the agent is still failing. This could mean the existing \
guidance is not effective enough, OR the agent is not reliably engaging \
with it (e.g. not loading the relevant file, skipping steps, or not \
recognizing when the guidance applies). Diagnose why the existing \
coverage isn't working and make the *targeted change* (on a smaller scale \
as compared to a hard gradient, and within the scope of policy.md) that would \
fix it — this might be rewording for clarity, adding an example, \
surfacing buried content, making load-triggers more explicit, or \
restructuring for visibility. Avoid adding duplicate content in the agent home. \
The test is: would an agent reading the updated agent home be more likely to \
notice, load, and follow the relevant guidance for this failure pattern?

**IMPORTANT:** If most improvements are soft and only a few are hard, do not \
let the volume of soft gradients shrink your ambition on the hard ones — address \
hard gradients with the full substantial changes they need, independent of how \
many soft items surround them.

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
(strengths and improvements) that you should focus on. **Pay attention to the gradient type on each \
improvement — it determines how aggressively you should address it**.
3. If you need more detail on a specific task mentioned in the report, *you can always drill down* with \
`bash show_analysis.sh <id1> [id2 ...]` to see the full per-task analysis, or \
`bash show_datapoint.sh <task_id>` for raw trace + score + meta of a specific task.
4. Based on the accumulated patterns, edit the agent's home directory such that the agent's \
orchestration is improved for the given task and follows the policies defined in `policy.md`. \
For hard gradient improvements, make the substantial (structural or content) changes they need. \
For soft gradient improvements, diagnose why existing coverage isn't landing and make targeted changes.
5. Keep in mind the past edits on previous step runs as well, and try not to overfit to a specific \
step run. Our goal is to improve the agent's orchestration for the given task in a **generalizable way**, \
so that the agent performs better in the future unseen scenarios of the given task.
6. Use `bash policy_checker.sh` to check if the edited agent's home directory follows the \
syntactical/structural guidelines defined in `policy.md`. If there are any \
issues, fix them before finalizing the edit and returning final text.
7. Briefly summarize what you changed and why in the final text.
"""


def _selfop_main_user_prompt(step_dir_name: str, step_scores: str) -> str:
    step_num = int(step_dir_name.replace("step_", ""))
    return "\n".join([
        f"New step results available at `steps/{step_dir_name}/`\n",
        step_scores + "\n",
        f"A **gradient-annotated** accumulated report has been saved to "
        f"`analysis_runs/step_{step_num}/accumulated_report.txt`.\n",
        "Each improvement in the report is marked with a gradient type "
        "(Hard or Soft). Pay close attention to these annotations:\n",
        "- **Hard Gradient** improvements are gaps — MAY need substantial (structural or content) changes.",
        "- **Soft Gradient** improvements have existing coverage that isn't landing — "
        "diagnose why and make *targeted changes* without duplicating existing content.",
        "- Do NOT let a majority of soft items shrink your ambition on the hard ones.\n",
        "If you need to look at few representative examples or need more details on a specific task, ",
        "*you can always drill down* with the following commands:\n",
        "- `bash show_analysis.sh <id1> [id2 ...]` — per-task analysis "
        "(score + trajectory + orchestration-level) for one or more tasks",
        "- `bash show_datapoint.sh <task_id>` — raw trace + score + meta of a specific task\n",
        "**Read the accumulated report, do your analysis, respect the gradient annotations, and improve the agent's orchestration.**",
    ])


# ── Optimizer ─────────────────────────────────────────────────────────

class SelfOp(ConvergenceOptimizer):
    """ConvergenceOptimizer + gradient-annotated reports and gradient-aware Phase 3.

    Phases 1 & 2 are inherited from GradientOptimizer unchanged.
    Phase 2.5 runs accumulation (deferred report writing).
    Phase 2.75 runs coverage classification.
    Phase 2.8 re-renders report with hard/soft gradient annotations.
    Phase 3 uses a gradient-aware system prompt.
    """

    name = "selfop"

    # ── Phase 2.5: accumulation (deferred report) ─────────────────────

    async def _run_accumulation(
        self,
        step_dir: Path,
        step_ids: list[str],
    ) -> dict:
        """Run accumulation but do NOT write the report yet.

        The report will be re-rendered after classification with gradient
        annotations in Phase 2.8.
        """
        result = await super()._run_accumulation(step_dir, step_ids)
        return result

    # ── Phase 2.8: annotated report ───────────────────────────────────

    def _render_annotated_report(
        self,
        accum_result: dict,
        classification: dict,
        step_dir: Path,
    ) -> str:
        """Re-render the accumulated report with gradient annotations.

        Extracts raw coverage classifications from the ClassificationResult's
        _coverage_detail field and passes them to render_report.
        """
        coverage_detail = classification.get("_coverage_detail")
        coverage_annotations = None
        if coverage_detail:
            coverage_annotations = coverage_detail.get("classifications")

        report = render_report(
            accum_result["selected_strengths"],
            accum_result["selected_improvements"],
            total_tasks=accum_result["total_tasks"],
            total_solved=accum_result["total_solved"],
            total_failed=accum_result["total_failed"],
            step=accum_result["step"],
            summarized=True,
            usage_summary=accum_result.get("usage_summary", ""),
            coverage_annotations=coverage_annotations,
        )

        step_num = int(step_dir.name.replace("step_", ""))
        report_path = (
            self.workspace_dir / "analysis_runs" / f"step_{step_num}"
            / "accumulated_report.txt"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report)

        return report

    # ── Phase 3: gradient-aware main optimizer ────────────────────────

    async def _run_main_optimizer(
        self, step_dir: Path, step_ids: list[str],
        session_id: str | None = None,
    ) -> dict:
        """Override: uses gradient-aware system and user prompts."""
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

        await asyncio.sleep(60)

        step_scores = self.task.format_batch_scores(step_dir, step_ids)
        usr_prompt = _selfop_main_user_prompt(step_dir.name, step_scores)

        print(f"\n{'─'*60}")
        print(f"[Phase 3] User prompt to main optimizer:")
        print(f"{'─'*60}")
        print(usr_prompt)
        print(f"{'─'*60}\n")

        sys_prompt = SELFOP_MAIN_SYSTEM_PROMPT.format(
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
        snr_threshold: float | None = None,
        convergence_mode: str = "novelty",
        convergence_gate: bool = False,
    ) -> dict:
        """Full pipeline with gradient-annotated reports and convergence gating.

        Same interface as ConvergenceOptimizer, but inserts Phase 2.8 (annotated report) between
        classification and the convergence gate, and uses a gradient-aware
        Phase 3 prompt.
        """
        print(f"[selfop] Phase 1: Running {len(step_ids)} trajectory analyses...")
        phase1_results = await self._run_all_phase1(step_dir, step_ids)

        print(f"[selfop] Phase 2: Running {len(step_ids)} gradient analyses...")
        phase2_results = await self._run_all_phase2(step_dir, step_ids)

        print("[selfop] Phase 2.5: Running gradient accumulation...")
        accum_result = await self._run_accumulation(step_dir, step_ids)

        selected_improvements = accum_result.get("selected_improvements", [])

        if not selected_improvements:
            if convergence_gate:
                print("[selfop] No improvement themes selected — skipping Phase 3.")
                return {
                    "optimizer": self.name,
                    "phase1_results": phase1_results,
                    "phase2_results": phase2_results,
                    "snr": None,
                    "classification": None,
                    "skipped": True,
                    "session_id": session_id,
                }
            else:
                print("[selfop] No improvement themes selected — running Phase 3 anyway (stop-only mode).")
                main_result = await self._run_main_optimizer(step_dir, step_ids, session_id)
                return {
                    "optimizer": self.name,
                    "phase1_results": phase1_results,
                    "phase2_results": phase2_results,
                    "snr": None,
                    "classification": None,
                    "skipped": False,
                    **main_result,
                }

        print(f"[selfop] Phase 2.75: Classifying {len(selected_improvements)} "
              f"selected improvement themes...")
        if self.config.classifier_type == "coverage":
            class_result = await self._run_coverage_classification(
                selected_improvements, step_dir,
            )
        else:
            class_result = await self._run_classification(selected_improvements, step_dir)
        snr = class_result["snr"]
        classification = class_result["classification"]

        # Phase 2.8: re-render report with gradient annotations
        has_coverage = classification.get("_coverage_detail") is not None
        if has_coverage:
            print("[selfop] Phase 2.8: Re-rendering report with gradient annotations...")
            self._render_annotated_report(accum_result, classification, step_dir)
        else:
            print("[selfop] Phase 2.8: Skipped (no coverage annotations — "
                  "theme-history classifier does not produce gap/covered labels).")

        # Convergence gating (identical to ConvergenceOptimizer)
        should_skip = False
        if convergence_gate:
            if convergence_mode == "novelty":
                if classification["novel_count"] > 0:
                    pass
                elif classification["common_diff_count"] > 0 and snr_threshold is not None and snr >= snr_threshold:
                    pass
                else:
                    print(f"[selfop] No significant signal (novel=0, diff_causal={classification['common_diff_count']}, "
                          f"z={snr:.2f}) — skipping Phase 3 (main optimizer).")
                    should_skip = True
            elif convergence_mode == "snr":
                if snr_threshold is not None and snr < snr_threshold:
                    print(f"[selfop] z={snr:.2f} < z_crit={snr_threshold:.2f} "
                          f"— skipping Phase 3 (main optimizer).")
                    should_skip = True

        if should_skip:
            return {
                "optimizer": self.name,
                "phase1_results": phase1_results,
                "phase2_results": phase2_results,
                "snr": snr,
                "classification": classification,
                "skipped": True,
                "session_id": session_id,
            }

        print("[selfop] Phase 3: Running main optimizer (gradient-aware report + agent_home update)...")
        main_result = await self._run_main_optimizer(step_dir, step_ids, session_id)
        print("[selfop] Done.")

        return {
            "optimizer": self.name,
            "phase1_results": phase1_results,
            "phase2_results": phase2_results,
            "snr": snr,
            "classification": classification,
            "skipped": False,
            **main_result,
        }
