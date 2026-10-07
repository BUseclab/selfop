from __future__ import annotations

"""Chain-rule gradient computation (paper §3.2) — three-level gradient composition.

Phase 1: For each task in the step, an ephemeral mini-optimizer agent
         analyzes the solver's trajectory *without access to agent_home*,
         producing a task-specific trajectory analysis (trajectory_analysis.txt).
Phase 2: For each task, a second mini-optimizer reads the Phase 1 trajectory
         analysis *with* agent_home and policy.md, and produces an
         agent_home-grounded gradient analysis (agent_analysis.txt).
         Then score_analysis + trajectory_analysis + agent_analysis are
         composed into a single analysis.txt.
Phase 3: A main optimizer reads all composed analyses, identifies
         cross-task patterns, and updates the skill files.
"""

import asyncio
import shutil
import subprocess
from pathlib import Path

from tqdm import tqdm

from selfop.config import PipelineConfig
from selfop.optimizer.base import Optimizer
from selfop.policy import AGENT_HOME_DESCRIPTION, ANALYSIS_SCOPE_HINT
from selfop.runner.codex import CodexRunner
from tasks.base import Task

TIMEOUT_MINI = 20 * 60
TIMEOUT_MAIN = 20 * 60


# ── Prompts ───────────────────────────────────────────────────────────

PHASE1_SYSTEM_PROMPT = """\
You are a task-run analyst. Your job is to analyze a single task run \
performed by a solver agent and produce a detailed, task-specific analysis \
of the agent's trajectory — what actions contributed to correctness or \
incorrectness of each scored field, and how it could be improved.

You do NOT have access to the agent's orchestration files (that it might be using to solve the task). \
Your analysis MUST focus purely on the agent's trajectory, the task, and \
the efficiency, correctness, and completeness of the solution approach itself. \
You should use the reasoning text in the agent's trace to help you understand \
the agent's approach, and its strengths and weaknesses, and how it could be improved.

# TASK DESCRIPTION

{task_description}

### TASK-SOLVING AGENT'S WORKSPACE

When the agent starts a task instance, it is given a workspace with the \
task-specific files/artifacts it needs. Understanding this workspace should help \
you reason about what the agent saw.

{task_workspace_description}

# YOUR WORKSPACE

```
<task_id>/
├── datapoint.txt           ← pre-generated detailed readable run summary: agent trace (with redacted tool calls content to fit in agent's context) + scores + metadata for the task run
├── workspace/              ← the actual workspace the solver agent ran in
├── score.json              ← per-field correctness scores
├── trace.json              ← full agent execution trace (raw)
└── meta/                   ← task metadata files
```

# YOUR WORKFLOW

1. Read `datapoint.txt` for a readable detailed summary of the solver's trace, scores, \
and metadata. If you need more details you can inspect the raw files in the task directory directly.
2. Examine the printed score from `datapoint.txt` or the `score.json` file to understand \
exactly which fields were scored correct vs incorrect and why, and how it lead to the overall \
success or failure of the task.
3. Trace back through the agent's trajectory to identify which actions/decisions contributed \
to the fields' outcomes.
4. Produce your analysis as your final response text. Structure it as follows:

## Analysis Structure

Your final response MUST contain these sections, and focus your analysis on the agent's trajectory \
for the task with metrics like agent's reasoning path, tool usage, efficiency, correctness, and \
completeness of the solution approach.


```markdown
### Result
Whether the task was solved successfully and a brief one-liner summary of the outcome.

### Score Analysis
Analyze the scored fields and how the agent's trajectory led to their outcomes. \
If there are many fields, group them by theme or category rather than listing every \
field and its analysis individually.

### Trajectory Strengths
What approaches, strategies, or actions in the agent's trajectory were \
effective? What did the agent do well?

### Trajectory Weaknesses
What approaches, strategies, or actions in the agent's trajectory were \
ineffective, incorrect, or harmful? Where did the agent go wrong?

### Improvement Suggestions
What could the agent have done differently to improve the trajectory/approach \
for the given task?
```
"""


PHASE2_SYSTEM_PROMPT = """\
You are an agent orchestration analyst. Your job is to bridge a task-specific \
trajectory analysis to the agent's orchestration files (agent_home), and \
determine how the orchestration influenced the agent's behavior — both \
positively and negatively, and how it could be improved.

You are given a pre-computed trajectory analysis (`trajectory_analysis.txt`) \
that describes what the agent did well and poorly during a single task run. \
That analysis was produced WITHOUT access to agent_home — it is purely about \
the agent's trajectory. Your job is to read that analysis, then examine \
`agent_home/` ({analysis_scope_hint}) and `policy.md`, and \
determine how the orchestration files caused or failed to prevent the \
observed behaviors, and how it could be improved for the given task.

{agent_home_description}

# EDITING POLICY

A `policy.md` file describes the structural rules and constraints for editing \
`agent_home/`. You should read it and ground your improvement suggestions in \
what the policy allows. Your suggestions must be actionable within the policy.

# TASK DESCRIPTION

{task_description}

### TASK-SOLVING AGENT'S WORKSPACE

When the agent starts a task instance, it is given a workspace with the \
task-specific files/artifacts it needs. Understanding this workspace should help \
you reason about what the agent saw and how it should approach the problem.

{task_workspace_description}

# YOUR WORKSPACE

```
<task_id>/
├── trajectory_analysis.txt ← pre-computed trajectory analysis (your primary input)
├── agent_home/             ← the agent's orchestration directory (read-only)
├── policy.md               ← editing constraints for agent_home
├── datapoint.txt           ← readable run summary (for deeper inspection if needed)
├── workspace/              ← the actual workspace the solver agent ran in
├── score.json              ← per-field correctness scores
├── trace.json              ← full agent execution trace (raw)
└── meta/                   ← task metadata files
```

# YOUR WORKFLOW

1. Read `trajectory_analysis.txt` — this is your primary input. It contains a \
detailed analysis of the agent's trajectory: what the agent did well, what it did \
poorly, per-field score attribution, and improvement suggestions.
2. Read/explore `agent_home/` to understand the current orchestration.
3. Read `policy.md` to understand what edits are allowed and how the orchestration \
space is structured.
4. Bridge the trajectory analysis to agent_home: determine which parts of the \
orchestration caused or failed to \
prevent the trajectory behaviors identified in the analysis and how it could be \
improved for the given task.
5. If you need more detail on the agent's actual actions, read `datapoint.txt` or \
inspect the raw files in the task directory.
6. Produce your analysis as your final response text. Structure it as follows:

## Analysis Structure

Your final response MUST contain these sections:

```markdown
### Result
Whether the task was solved successfully and a brief one-liner summary of the outcome.

### Agent's Usage of agent_home
Did the agent use {analysis_scope_hint} effectively? \
Did it ignore parts, misinterpret them, or follow them faithfully? \
Connect the trajectory analysis findings to specific orchestration files \
the agent did or did not use.

### Strengths
What parts of agent_home (or its structure) contributed positively \
to the outcome? Tie each strength to a concrete trajectory behavior \
from the trajectory analysis.

### Weaknesses
What parts of agent_home (or gaps in it) contributed negatively to \
the outcome? Tie each weakness to a concrete trajectory behavior \
from the trajectory analysis.

### Improvements
What specific changes to agent_home would improve the outcome? \
(Grounded in policy.md constraints and the agent's usage of agent_home.)
```
"""


MAIN_SYSTEM_PROMPT = """\
You are an agent optimizer. Your job is to improve the agent orchestration so \
that the agent performs better on a given task.

{agent_home_description}

# YOUR WORKSPACE

```
workspace/
├── agent_home/                 ← the agent's home directory, that you will be editing
├── steps/                      ← the steps directory, that contains the results of the step runs
│   └── step_N/
│       └── <task_id>/
│           ├── workspace/      ← the workspace directory of the task
│           ├── meta/           ← task metadata files
│           ├── score.json      ← per-field correctness scores
│           └── trace.json      ← full agent's execution trace
├── analysis_runs/              ← pre-computed per-task analyses
│   └── step_N/
│       └── <task_id>/
│           └── analysis.txt    ← combined analysis (score + trajectory + orchestration)
├── show_analysis.sh            ← read analyses: bash show_analysis.sh <id1> [id2 ...]
├── show_datapoint.sh           ← inspect raw data: bash show_datapoint.sh <task_id>
├── policy_checker.sh           ← check if the edited agent_home/ follows policy.md
└── policy.md                   ← agent's home directory editing guidelines
```

# IMPORTANT: PRE-COMPUTED ANALYSES

Each task in the step has been independently analyzed at three levels, combined into \
a single `analysis.txt`. Running `bash show_analysis.sh <id1> [id2 ...]` prints it for each task. \
The analysis contains three sections:

1. **Score Analysis** — per-field score decomposition showing which sub-scores passed or \
failed and how they contributed to the overall correct/incorrect outcome.
2. **Trajectory Analysis** — what the agent did well and poorly in its approach to the task, \
per-field score attribution, and improvement suggestions at the approach level. This was \
produced WITHOUT access to agent_home — it is purely about the agent's trajectory and approach.
3. **Orchestration Analysis** — how agent_home caused or failed to prevent the observed \
trajectory behaviors, and what specific agent_home changes would improve the outcome. \
This was produced WITH access to agent_home and policy.md.

Use these analyses as your PRIMARY source of insight:
- `bash show_analysis.sh <id1> [id2 ...]` — read analyses for one or more tasks

If you need deeper inspection of a specific task's raw trace, you can fall back to:
- `bash show_datapoint.sh <task_id>` — prints the trace + score + meta

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
of the step run results in the user message, and the step artifacts (including pre-computed \
analyses) will be available in the `steps/` directory.
2. Read the analyses using `bash show_analysis.sh <id1> [id2 ...]`. You can pass multiple task \
IDs at once. Each task will show three levels: score analysis (what scored correct/incorrect and why), \
trajectory analysis (approach-level strengths/weaknesses), and orchestration analysis (how agent_home \
influenced the outcome and what to change).
3. If you really need more detail on a specific task, use `bash show_datapoint.sh <task_id>` to see \
the trace + score + meta.
4. Based on the analyses, edit the agent's home directory such that the agent's orchestration is improved for the given \
task and follows the policies defined in `policy.md`.
5. Keep in mind the past edits on previous step runs as well, and try not to overfit to a specific \
step run. Our goal is to improve the agent's orchestration for the given task in a generalizable way, \
so that the agent performs better in the future unseen scenarios of the given task.
6. Use `bash policy_checker.sh` to check if the edited agent's home directory follows the \
syntactical/structural guidelines defined in `policy.md`. If there are any \
issues, fix them before finalizing the edit and returning final text.
7. Briefly summarize what you changed and why in the final text.
"""


def _main_user_prompt(step_dir_name: str, step_scores: str) -> str:
    step_num = int(step_dir_name.replace("step_", ""))
    return "\n".join([
        f"New step results available at `steps/{step_dir_name}/`\n",
        step_scores + "\n",
        "Each task has pre-computed analyses (score, trajectory, and orchestration levels). ",
        "Read these analyses with: `bash show_analysis.sh <id1> [id2 ...]` ",
        "(for deeper raw inspection: `bash show_datapoint.sh <task_id>`). ",
        f"These commands show data from the latest step (step {step_num}). ",
        "To view a task from a previous step, add `--step N`.\n",
        "Read the analyses and improve the agent's orchestration.",
    ])


# ── Helpers ───────────────────────────────────────────────────────────

def _cleanup(workspace_dir: Path) -> None:
    for name in ("AGENTS.md", "CLAUDE.md", ".agents"):
        p = workspace_dir / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file() or p.is_symlink():
            p.unlink(missing_ok=True)


def _generate_datapoint_txt(task_id: str, workspace_dir: Path) -> str:
    """Run show_datapoint.py as a subprocess and capture its output.

    show_datapoint.py resolves steps/ relative to its own __file__,
    so it must live alongside the steps symlink in workspace_dir.
    """
    script = workspace_dir / "show_datapoint.py"
    venv_python = workspace_dir / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else "python3"
    proc = subprocess.run(
        [python, str(script), task_id],
        capture_output=True, text=True,
    )
    return proc.stdout or "(show_datapoint.py produced no output)"


def _safe_symlink(target: Path, link: Path) -> None:
    """Create a symlink, removing any existing file/link/dir first."""
    if link.exists() or link.is_symlink():
        if link.is_dir() and not link.is_symlink():
            shutil.rmtree(link)
        else:
            link.unlink()
    link.symlink_to(target.resolve())


# ── Optimizer ─────────────────────────────────────────────────────────

class GradientOptimizer(Optimizer):
    """Three-phase optimizer: trajectory analysis, gradient analysis, synthesis.

    Phase 1 analyzes each task's trajectory without agent_home.
    Phase 2 bridges each trajectory analysis to agent_home.
    Phase 3 aggregates the gradient analyses and edits agent_home."""

    name = "gradient"

    def setup(self, config: PipelineConfig, task: Task, run_name: str) -> Path:
        self.config = config
        self.task = task

        self.workspace_dir = config.optimizer_workspace_dir

        # Clone agent_home
        cloned_agent_home = self.workspace_dir / "agent_home"
        if cloned_agent_home.exists():
            shutil.rmtree(cloned_agent_home)

        agent_home_src = config.agent_home_dir
        skills_src = agent_home_src / "skills" / config.skill_name
        agents_src = agent_home_src / "agents"
        config_toml_src = agent_home_src / "config.toml"

        if skills_src.exists():
            shutil.copytree(skills_src, cloned_agent_home / "skills" / config.skill_name)
        if agents_src.exists():
            shutil.copytree(agents_src, cloned_agent_home / "agents")
        if config_toml_src.exists():
            shutil.copy2(config_toml_src, cloned_agent_home / "config.toml")

        # Symlink steps
        steps_link = self.workspace_dir / "steps"
        _safe_symlink(config.steps_dir, steps_link)

        # Copy resource scripts
        resources_dir = Path(__file__).parent.parent / "resources"
        for fname in (
            "show_datapoint.py", "show_datapoint.sh",
            "show_analysis.py", "show_analysis.sh",
            "policy_checker.sh",
        ):
            src = resources_dir / fname
            if src.exists():
                shutil.copy2(src, self.workspace_dir / fname)
        shutil.copy2(config.policy_file, self.workspace_dir / "policy.md")
        shutil.copy2(config.policy_checker_file, self.workspace_dir / "policy_checker.py")

        # Symlink .venv
        venv_src = resources_dir / ".venv"
        venv_link = self.workspace_dir / ".venv"
        if venv_link.exists() or venv_link.is_symlink():
            if venv_link.is_symlink():
                venv_link.unlink()
            else:
                shutil.rmtree(venv_link)
        if venv_src.exists():
            venv_link.symlink_to(venv_src.resolve())

        return self.workspace_dir

    # ── Phase 1: trajectory analysis (agent_home-blind) ───────────────

    def _prepare_phase1_workspace(
        self, task_id: str, mini_dir: Path, step_task_dir: Path,
    ) -> None:
        """Prepare workspace for Phase 1 mini-optimizer.

        Sets up symlinks to step artifacts and generates datapoint.txt.
        Does NOT add agent_home or policy.md.
        """
        mini_dir.mkdir(parents=True, exist_ok=True)

        for name in ("workspace", "meta", "score.json", "trace.json"):
            src = step_task_dir / name
            if src.exists():
                _safe_symlink(src, mini_dir / name)

        dp_text = _generate_datapoint_txt(task_id, self.workspace_dir)
        (mini_dir / "datapoint.txt").write_text(dp_text)

    async def _run_phase1(
        self, task_id: str, mini_dir: Path, step_task_dir: Path,
    ) -> dict:
        """Run Phase 1 trajectory analysis on one task."""
        cached = mini_dir / "trajectory_analysis.txt"
        if cached.exists() and cached.stat().st_size > 0:
            return {
                "task_id": task_id,
                "phase": 1,
                "log_path": str(mini_dir / "phase1.log"),
                "analysis_len": len(cached.read_text()),
                "cached": True,
            }

        self._prepare_phase1_workspace(task_id, mini_dir, step_task_dir)

        runner = CodexRunner()
        log_path = mini_dir / "phase1.log"
        trace_path = mini_dir / "phase1_trace.json"

        sys_prompt = PHASE1_SYSTEM_PROMPT.format(
            task_description=self.task.task_description(),
            task_workspace_description=self.task.task_workspace_description(),
        )

        _cleanup(mini_dir)

        result = await runner.run(
            prompt="Analyze this task run.",
            workspace_dir=mini_dir,
            model=self.config.optimizer_model,
            reasoning=self.config.optimizer_reasoning,
            system_prompt=sys_prompt,
            sandbox="read-only",
            log_path=log_path,
            trace_path=trace_path,
            timeout=TIMEOUT_MINI,
            model_provider=self.config.model_provider,
        )

        _cleanup(mini_dir)

        analysis_text = result.final_text or "(no trajectory analysis produced)"
        (mini_dir / "trajectory_analysis.txt").write_text(analysis_text)

        return {
            "task_id": task_id,
            "phase": 1,
            "log_path": str(log_path),
            "analysis_len": len(analysis_text),
        }

    async def _run_all_phase1(
        self, step_dir: Path, step_ids: list[str],
    ) -> list[dict]:
        """Run Phase 1 trajectory analyses for all tasks in parallel."""
        sem = asyncio.Semaphore(self.config.num_workers)
        pbar = tqdm(total=len(step_ids), desc="phase-1", unit="task")

        analysis_runs_step = self.workspace_dir / "analysis_runs" / step_dir.name
        analysis_runs_step.mkdir(parents=True, exist_ok=True)

        async def _guarded(task_id: str) -> dict:
            safe_id = task_id.replace(":", "_")
            mini_dir = analysis_runs_step / safe_id
            step_task_dir = step_dir / safe_id
            async with sem:
                result = await self._run_phase1(
                    task_id, mini_dir, step_task_dir,
                )
                pbar.update(1)
                return result

        results = await asyncio.gather(
            *[_guarded(tid) for tid in step_ids],
            return_exceptions=True,
        )
        pbar.close()

        phase1_results = []
        for tid, r in zip(step_ids, results):
            if isinstance(r, Exception):
                safe_id = tid.replace(":", "_")
                mini_dir = analysis_runs_step / safe_id
                mini_dir.mkdir(parents=True, exist_ok=True)
                (mini_dir / "trajectory_analysis.txt").write_text(
                    f"(phase-1 failed: {r})"
                )
                phase1_results.append({
                    "task_id": tid, "phase": 1, "error": str(r),
                })
            else:
                phase1_results.append(r)
        return phase1_results

    # ── Phase 2: gradient analysis (agent_home-aware) ─────────────────

    def _prepare_phase2_workspace(self, mini_dir: Path) -> None:
        """Enrich an existing Phase 1 directory for Phase 2.

        Adds agent_home symlink and policy.md. All other artifacts
        (workspace, score.json, trace.json, meta, datapoint.txt,
        trajectory_analysis.txt) are already present from Phase 1.
        """
        _safe_symlink(
            self.workspace_dir / "agent_home",
            mini_dir / "agent_home",
        )

        policy_src = self.workspace_dir / "policy.md"
        policy_dst = mini_dir / "policy.md"
        if policy_src.exists():
            shutil.copy2(policy_src, policy_dst)

    async def _run_phase2(
        self, task_id: str, mini_dir: Path,
    ) -> dict:
        """Run Phase 2 gradient analysis on one task."""
        cached = mini_dir / "agent_analysis.txt"
        if cached.exists() and cached.stat().st_size > 0:
            return {
                "task_id": task_id,
                "phase": 2,
                "log_path": str(mini_dir / "phase2.log"),
                "analysis_len": len(cached.read_text()),
                "cached": True,
            }

        self._prepare_phase2_workspace(mini_dir)

        runner = CodexRunner()
        log_path = mini_dir / "phase2.log"
        trace_path = mini_dir / "phase2_trace.json"

        sys_prompt = PHASE2_SYSTEM_PROMPT.format(
            task_description=self.task.task_description(),
            task_workspace_description=self.task.task_workspace_description(),
            skill_name=self.config.skill_name,
            agent_home_description=AGENT_HOME_DESCRIPTION.format(
                skill_name=self.config.skill_name,
            ),
            analysis_scope_hint=ANALYSIS_SCOPE_HINT,
        )

        _cleanup(mini_dir)

        result = await runner.run(
            prompt="Analyze how the agent's orchestration influenced this task run.",
            workspace_dir=mini_dir,
            model=self.config.optimizer_model,
            reasoning=self.config.optimizer_reasoning,
            system_prompt=sys_prompt,
            sandbox="read-only",
            log_path=log_path,
            trace_path=trace_path,
            timeout=TIMEOUT_MINI,
            model_provider=self.config.model_provider,
        )

        _cleanup(mini_dir)

        analysis_text = result.final_text or "(no gradient analysis produced)"
        (mini_dir / "agent_analysis.txt").write_text(analysis_text)

        return {
            "task_id": task_id,
            "phase": 2,
            "log_path": str(log_path),
            "analysis_len": len(analysis_text),
        }

    async def _run_all_phase2(
        self, step_dir: Path, step_ids: list[str],
    ) -> list[dict]:
        """Run Phase 2 gradient analyses for all tasks in parallel."""
        sem = asyncio.Semaphore(self.config.num_workers)
        pbar = tqdm(total=len(step_ids), desc="phase-2", unit="task")

        analysis_runs_step = self.workspace_dir / "analysis_runs" / step_dir.name

        async def _guarded(task_id: str) -> dict:
            safe_id = task_id.replace(":", "_")
            mini_dir = analysis_runs_step / safe_id
            async with sem:
                result = await self._run_phase2(task_id, mini_dir)
                pbar.update(1)
                return result

        results = await asyncio.gather(
            *[_guarded(tid) for tid in step_ids],
            return_exceptions=True,
        )
        pbar.close()

        phase2_results = []
        for tid, r in zip(step_ids, results):
            if isinstance(r, Exception):
                safe_id = tid.replace(":", "_")
                mini_dir = analysis_runs_step / safe_id
                (mini_dir / "agent_analysis.txt").write_text(
                    f"(phase-2 failed: {r})"
                )
                phase2_results.append({
                    "task_id": tid, "phase": 2, "error": str(r),
                })
            else:
                phase2_results.append(r)

        for tid in step_ids:
            safe_id = tid.replace(":", "_")
            mini_dir = analysis_runs_step / safe_id
            self._compose_analysis(mini_dir)

        return phase2_results

    @staticmethod
    def _compose_analysis(mini_dir: Path) -> None:
        """Compose analysis.txt from score_analysis, trajectory_analysis, and agent_analysis."""
        sections: list[str] = []

        score_file = mini_dir / "meta" / "score_analysis.txt"
        if score_file.exists():
            sections.append("# SCORE ANALYSIS\n\"\"\"\n" + score_file.read_text().strip() + "\n\"\"\"")

        traj_file = mini_dir / "trajectory_analysis.txt"
        if traj_file.exists():
            sections.append("# TRAJECTORY ANALYSIS\n\"\"\"\n" + traj_file.read_text().strip() + "\n\"\"\"")

        agent_file = mini_dir / "agent_analysis.txt"
        if agent_file.exists():
            sections.append("# ORCHESTRATION ANALYSIS\n\"\"\"\n" + agent_file.read_text().strip() + "\n\"\"\"")

        (mini_dir / "analysis.txt").write_text("\n\n".join(sections) + "\n")

    # ── Phase 3: main optimizer ───────────────────────────────────────

    async def _run_main_optimizer(
        self, step_dir: Path, step_ids: list[str],
        session_id: str | None = None,
    ) -> dict:
        """Run the main optimizer that synthesizes gradient analyses
        and updates agent_home."""
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
        usr_prompt = _main_user_prompt(step_dir.name, step_scores)

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

        print("[selfop] Phase 3: Running main optimizer (synthesis + agent_home update)...")
        main_result = await self._run_main_optimizer(step_dir, step_ids, session_id)
        print("[selfop] Done.")

        return {
            "optimizer": self.name,
            "phase1_results": phase1_results,
            "phase2_results": phase2_results,
            **main_result,
        }
