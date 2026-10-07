from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from selfop.config import PipelineConfig
from tasks.base import Task


class Optimizer(ABC):
    """Base class for optimizer designs.

    Each subclass is a single self-contained file with its own
    setup, prompts, and optimization logic.
    """

    name: str
    workspace_dir: Path

    @abstractmethod
    def setup(self, config: PipelineConfig, task: Task, run_name: str) -> Path:
        """Prepare the optimizer workspace for a run.

        Stores config and task on the instance. Returns the workspace directory.
        """

    @abstractmethod
    async def run(
        self,
        *,
        step_dir: Path,
        step_ids: list[str],
        session_id: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Run optimization for a given step.

        Returns metadata dict which must include "session_id" key
        (str or None) for persistent session tracking.

        Subclasses may accept additional keyword arguments (e.g.
        convergence_mode, snr_threshold, convergence_gate for convergence detection).
        """
