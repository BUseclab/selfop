from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from selfop.policy import POLICY_CHECKER_FILE, POLICY_FILE


@dataclass
class PipelineConfig:
    # --- paths ---
    run_dir: Path
    data_dir: Path = Path("tasks/cybergym/data/cybergym_data/data")
    split_file: Path = Path("")  # overridden by task config

    # --- task ---
    task: str = "cybergym"

    # --- model ---
    model: str = "gpt-5.4-mini"
    agent: str = "codex"
    reasoning: str = "high"
    model_provider: str | None = None
    num_workers: int = 16

    # --- training ---
    epochs: int = 1
    batch_size: int = 16
    val_interval: int = 2

    # --- agent home / skill ---
    skill_name: str = "poc-generation"
    initial_home: Path = Path("tasks/cybergym/initial_home/")

    # --- optimizer agent ---
    optimizer_model: str = "gpt-5.4-mini"
    optimizer_reasoning: str = "high"

    # --- policy ---
    policy_file: Path = POLICY_FILE
    policy_checker_file: Path = POLICY_CHECKER_FILE

    # --- gradient accumulation ---
    accum_model: str = "gpt-5.4-mini"
    accum_reasoning: str = "high"
    accum_chunk_size: int = 8
    accum_min_support: int = 2
    accum_min_support_ratio_strength: float = 0.30
    accum_min_support_ratio_improvement: float = 0.20
    accum_min_composite_strength: float = 0.00
    accum_min_composite_improvement: float = 0.00

    # --- convergence detection ---
    classifier_type: str = "coverage"  # "theme_history" | "coverage" (skill-gap classifier via CodexRunner)
    convergence_mode: str = "snr"  # "snr" (z-score) or "novelty" (any novel/diff_causal)
    snr_threshold: float = 1.0  # z_crit for the one-proportion z-test (used when mode="snr")
    convergence_k: int = 3
    convergence_gate: bool = False  # True = skip+accumulate on no novelty; False = always apply, stop-only
    classifier_p0: float = 0.073  # baseline noise rate for SNR z-test

    # --- meta ---
    include_task_meta: bool = True

    # --- derived (populated in __post_init__) ---
    workspace_dir: Path = field(init=False)
    agent_home_dir: Path = field(init=False)
    steps_dir: Path = field(init=False)
    agent_home_snapshots_dir: Path = field(init=False)
    optimizer_workspace_dir: Path = field(init=False)
    train_log: Path = field(init=False)
    val_log: Path = field(init=False)
    config_file: Path = field(init=False)
    checkpoint_file: Path = field(init=False)

    def __post_init__(self):
        self.run_dir = Path(self.run_dir)
        self.data_dir = Path(self.data_dir)
        self.split_file = Path(self.split_file)
        self.initial_home = Path(self.initial_home)
        self.policy_file = Path(self.policy_file)
        self.policy_checker_file = Path(self.policy_checker_file)
        self.workspace_dir = self.run_dir / "workspace"
        self.agent_home_dir = self.workspace_dir / "agent_home"
        self.steps_dir = self.workspace_dir / "steps"
        self.agent_home_snapshots_dir = self.run_dir / "agent_home_snapshots"
        self.optimizer_workspace_dir = self.run_dir / "optimizer" / "workspace"
        self.train_log = self.run_dir / "train.jsonl"
        self.val_log = self.run_dir / "val.jsonl"
        self.config_file = self.run_dir / "config.json"
        self.checkpoint_file = self.run_dir / "checkpoint.json"

    # --- path helpers ---

    def step_dir(self, step: int) -> Path:
        return self.steps_dir / f"step_{step}"

    def val_dir(self, step: int) -> Path:
        return self.run_dir / "val" / f"step_{step}"

    def skill_dir(self) -> Path:
        return self.agent_home_dir / "skills" / self.skill_name

    # --- serialisation ---

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Path):
                d[k] = str(v)
        return d

    def save(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(self.to_dict(), indent=4))

    @classmethod
    def from_dict(cls, d: dict) -> PipelineConfig:
        path_fields = {"run_dir", "data_dir", "split_file", "initial_home", "policy_file", "policy_checker_file"}
        for k in path_fields:
            if k in d and d[k] is not None:
                d[k] = Path(d[k])
        derived = {
            "workspace_dir", "agent_home_dir", "steps_dir",
            "agent_home_snapshots_dir", "optimizer_workspace_dir",
            "train_log", "val_log",
            "config_file", "checkpoint_file",
        }
        for k in derived:
            d.pop(k, None)
        return cls(**d)

    @classmethod
    def load(cls, run_dir: Path) -> PipelineConfig:
        cfg_file = Path(run_dir) / "config.json"
        return cls.from_dict(json.loads(cfg_file.read_text()))

