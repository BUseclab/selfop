from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional


Sandbox = Literal["read-only", "workspace-write"]


_BACKEND_ARTEFACTS: dict[str, tuple[str, ...]] = {
    "codex": ("AGENTS.md", ".agents"),
    "claude": ("CLAUDE.md", ".agents"),
}


@dataclass
class RunResult:
    final_text: str
    events: Optional[list[dict]] = None
    usage: Optional[dict] = None


class BackendRunner(ABC):
    name: str
    _workspace_prepared: bool = False

    def prepare_workspace(
        self,
        workspace_dir: Path,
        *,
        system_prompt: Optional[str] = None,
        skill: Optional[str] = None,
        skill_dir: Optional[Path] = None,
    ) -> Path:
        self._workspace_prepared = True
        return workspace_dir

    @abstractmethod
    async def run(
        self,
        prompt: str,
        *,
        workspace_dir: Path,
        model: str,
        reasoning: Optional[str] = None,
        system_prompt: Optional[str] = None,
        skill: Optional[str] = None,
        skill_dir: Optional[Path] = None,
        sandbox: Sandbox = "read-only",
        log_path: Optional[Path] = None,
        messages_path: Optional[Path] = None,
        timeout: float = 15 * 60,
        model_provider: Optional[str] = None,
        network_access: bool = False,
    ) -> RunResult:
        raise NotImplementedError


def wipe_cross_backend_artefacts(workspace_dir: Path, *, keep: str) -> None:
    workspace_dir = Path(workspace_dir)
    if not workspace_dir.exists():
        return
    keep_set = set(_BACKEND_ARTEFACTS.get(keep, ()))
    stale: Iterable[str] = (
        name
        for backend, names in _BACKEND_ARTEFACTS.items()
        if backend != keep
        for name in names
        if name not in keep_set
    )
    for name in stale:
        path = workspace_dir / name
        if path.is_symlink() or path.is_file():
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def resolve_skill(
    *,
    skill: Optional[str],
    skill_dir: Optional[Path],
    global_skills_dir: Path,
    workspace_skills_dir: Path,
) -> Optional[str]:
    workspace_skills_dir = Path(workspace_skills_dir)
    if skill is None:
        if workspace_skills_dir.exists():
            shutil.rmtree(workspace_skills_dir, ignore_errors=True)
        return None
    if (Path(global_skills_dir) / skill).is_dir():
        if workspace_skills_dir.exists():
            shutil.rmtree(workspace_skills_dir, ignore_errors=True)
        return skill
    if skill_dir is None or not Path(skill_dir).exists():
        raise ValueError(
            f"skill {skill!r} not found in {global_skills_dir} and no usable "
            f"skill_dir was provided (got: {skill_dir!r})."
        )
    dest = workspace_skills_dir / skill
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_dir, dest, dirs_exist_ok=True)
    return skill
