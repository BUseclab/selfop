from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Optional

from selfop.config import PipelineConfig


def write_data_ids_file(path: Path, data_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(data_ids) + "\n")


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def initialize_agent_home(config: "PipelineConfig") -> Path:
    """Seed the shared agent home that forward runs mount into Docker."""
    agent_home = config.agent_home_dir
    agent_home.mkdir(parents=True, exist_ok=True)
    shutil.copytree(config.initial_home, agent_home, dirs_exist_ok=True)

    if config.agent == "codex":
        auth_src = Path.home() / ".codex" / "auth.json"
        auth_dst = agent_home / "auth.json"
        if not auth_src.exists():
            raise FileNotFoundError(f"Codex auth not found: {auth_src}")
        shutil.copy2(auth_src, auth_dst)
    else:
        auth_src = Path.home() / f".{config.agent}"
        if auth_src.exists():
            shutil.copytree(auth_src, agent_home, dirs_exist_ok=True)
        else:
            raise FileNotFoundError(f"Agent auth directory not found: {auth_src}")

    return agent_home


def snapshot_agent_home(config: "PipelineConfig", label: str) -> Path:
    """Copy only the artifact directories/files from agent_home that were in initial_home."""
    src = config.agent_home_dir
    if not src.exists():
        raise FileNotFoundError(f"agent_home not found: {src}")
    dst = config.agent_home_snapshots_dir / label
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    initial = Path(config.initial_home)
    for entry in initial.iterdir():
        src_entry = src / entry.name
        if not src_entry.exists():
            continue
        if src_entry.is_dir():
            shutil.copytree(src_entry, dst / entry.name)
        else:
            shutil.copy2(src_entry, dst / entry.name)
    return dst


# ------------------------------------------------------------------
# Checkpoint persistence
# ------------------------------------------------------------------

def save_checkpoint(
    config: "PipelineConfig",
    completed_step: int,
    *,
    optimizer_session_id: str | None = None,
    consecutive_skips: int | None = None,
    batch_idx: int | None = None,
    current_step_ids: list[str] | None = None,
) -> None:
    record = {
        "completed_step": completed_step,
        "optimizer_session_id": optimizer_session_id,
        "timestamp": time.time(),
    }
    if consecutive_skips is not None:
        record["consecutive_skips"] = consecutive_skips
    if batch_idx is not None:
        record["batch_idx"] = batch_idx
    if current_step_ids is not None:
        record["current_step_ids"] = current_step_ids
    config.checkpoint_file.write_text(json.dumps(record, indent=4))


def load_checkpoint(config: "PipelineConfig") -> Optional[dict]:
    if not config.checkpoint_file.exists():
        return None
    try:
        return json.loads(config.checkpoint_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None
