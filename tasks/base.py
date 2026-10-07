"""Abstract base class for benchmark tasks optimized with SelfOp.

Each task subclass sets ``self.task_config`` in its own ``__init__``
(no magic config loading).
"""

from __future__ import annotations

from typing import Any
from pathlib import Path
from abc import ABC, abstractmethod

from selfop.config import PipelineConfig


class Task(ABC):
    """Base class for benchmark tasks.

    Subclasses must set ``self.cfg`` in __init__ and implement
    all abstract methods below.
    """

    name: str
    cfg: Any

    # --- lifecycle ---

    def setup(self) -> None:
        """Called once before training. Override to validate environment."""

    def teardown(self) -> None:
        """Called once after training (in a finally block)."""

    # --- data ---

    @abstractmethod
    def load_data_ids(self) -> dict[str, list[str]]:
        """Load data IDs from file and return dict with 'train', 'validation', 'test' keys mapping to data IDs."""

    # --- forward pass ---

    @abstractmethod
    def run_forward(
        self,
        config: PipelineConfig,
        run_output_dir: Path,
        task_ids: list[str],
    ) -> None:
        """Run the agent on task_ids with the given agent home.

        Writes per-task workspace, metadata, and trace artifacts under run_output_dir.
        """

    # --- evaluation ---

    @abstractmethod
    def run_evaluation(
        self,
        config: PipelineConfig,
        run_output_dir: Path,
        task_ids: list[str],
    ) -> None:
        """Evaluate agent outputs and write per-task score.json.

        score.json follows TASK.md format:
            {"overall": bool, "fields": { ... per-field breakdown ... }}
        """

    # --- scoring ---

    @abstractmethod
    def read_scores(self, output_dir: Path, data_ids: list[str]) -> dict[str, bool]:
        """Read overall success per task from output_dir. Returns {data_id: bool}."""

    @abstractmethod
    def print_results(self, output_dir: Path, data_ids: list[str], scores: dict[str, bool]) -> None:
        """Print a human-readable results table to stdout."""

    @abstractmethod
    def format_batch_scores(self, output_dir: Path, data_ids: list[str]) -> str:
        """Return a formatted string of batch results for the optimizer's user prompt.

        Reads all required artifacts (scores, run status, field breakdowns, etc.)
        from output_dir internally — the optimizer layer never touches raw score files.
        """

    # --- metadata ---

    @abstractmethod
    def task_description(self) -> str:
        """One-paragraph description used by the optimizer system prompt."""

    @abstractmethod
    def task_workspace_description(self) -> str:
        """Describe what the task-solving agent's workspace looks like.

        Returns a description of the files/artifacts provided to the agent
        when it starts a task instance. This helps the optimizer understand
        the context the agent was working in.
        """

    @abstractmethod
    def populate_task_meta(self, run_output_dir: Path, task_ids: list[str]) -> None:
        """Write task-specific metadata that helps the optimizer analyze runs."""
