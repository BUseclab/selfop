from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from selfop.runner.base import (
    BackendRunner,
    RunResult,
    Sandbox,
    resolve_skill,
    wipe_cross_backend_artefacts,
)
from selfop.runner.subprocess import parse_jsonl_events, run_subprocess


CODEX_BIN = "codex"
GLOBAL_CODEX_SKILLS = Path("~/.codex/skills/.curated").expanduser()


def extract_final_text(events: list[dict]) -> str:
    """Return the last completed agent_message text from a codex event stream."""
    for event in reversed(events):
        if (
            event.get("type") == "item.completed"
            and event.get("item", {}).get("type") == "agent_message"
        ):
            return event["item"].get("text", "")
    return ""


def extract_thread_id(events: list[dict]) -> Optional[str]:
    for event in events:
        if event.get("type") == "thread.started":
            return event.get("thread_id")
    return None


def _build_cmd(
    *,
    model: str,
    reasoning: Optional[str],
    workspace_dir: Path,
    sandbox: Sandbox,
    model_provider: Optional[str],
    network_access: bool = False,
) -> list[str]:
    cmd: list[str] = [
        CODEX_BIN, "exec",
        "--sandbox", sandbox,
        "-C", str(workspace_dir),
        "--skip-git-repo-check",
        "--ephemeral",
        "--json",
        "-m", model,
        "-c", 'web_search="disabled"',
    ]
    if sandbox == "workspace-write":
        net = "true" if network_access else "false"
        cmd += [
            "-c", f"sandbox_workspace_write.network_access={net}",
            "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
            "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
        ]
    if model_provider:
        cmd += ["-c", f'model_provider="{model_provider}"']
    if reasoning and reasoning != "none":
        cmd += ["-c", f"model_reasoning_effort={reasoning}"]
    return cmd


def _build_persistent_cmd(
    *,
    model: str,
    reasoning: Optional[str],
    workspace_dir: Path,
    sandbox: Sandbox,
    model_provider: Optional[str],
    network_access: bool = False,
) -> list[str]:
    """Like _build_cmd but without --ephemeral (session is persisted)."""
    cmd: list[str] = [
        CODEX_BIN, "exec",
        "--sandbox", sandbox,
        "-C", str(workspace_dir),
        "--skip-git-repo-check",
        "--json",
        "-m", model,
        "-c", 'web_search="disabled"',
    ]
    if sandbox == "workspace-write":
        net = "true" if network_access else "false"
        cmd += [
            "-c", f"sandbox_workspace_write.network_access={net}",
            "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
            "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
        ]
    if model_provider:
        cmd += ["-c", f'model_provider="{model_provider}"']
    if reasoning and reasoning != "none":
        cmd += ["-c", f"model_reasoning_effort={reasoning}"]
    return cmd


def _build_resume_cmd(
    session_id: str,
    *,
    model: Optional[str] = None,
    model_provider: Optional[str] = None,
) -> list[str]:
    cmd: list[str] = [
        CODEX_BIN, "exec", "resume", session_id,
        "--skip-git-repo-check",
        "--json",
    ]
    if model:
        cmd += ["-m", model]
    cmd += ["-c", 'web_search="disabled"']
    if model_provider:
        cmd += ["-c", f'model_provider="{model_provider}"']
    return cmd


class CodexRunner(BackendRunner):
    name = "codex"

    def prepare_workspace(
        self,
        workspace_dir: Path,
        *,
        system_prompt: Optional[str] = None,
        skill: Optional[str] = None,
        skill_dir: Optional[Path] = None,
    ) -> Path:
        workspace_dir = Path(workspace_dir)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        wipe_cross_backend_artefacts(workspace_dir, keep="none")

        agents_md = workspace_dir / "AGENTS.md"
        if system_prompt is not None:
            if agents_md.exists():
                agents_md.unlink()
            agents_md.write_text(system_prompt)

        resolve_skill(
            skill=skill,
            skill_dir=skill_dir,
            global_skills_dir=GLOBAL_CODEX_SKILLS,
            workspace_skills_dir=workspace_dir / ".agents" / "skills",
        )
        if skill is not None and agents_md.exists() and system_prompt is None:
            agents_md.unlink()

        self._workspace_prepared = True
        return workspace_dir

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
        trace_path: Optional[Path] = None,
        timeout: float = 15 * 60,
        model_provider: Optional[str] = None,
        network_access: bool = False,
    ) -> RunResult:
        workspace_dir = Path(workspace_dir)

        if not self._workspace_prepared:
            self.prepare_workspace(
                workspace_dir,
                system_prompt=system_prompt,
                skill=skill,
                skill_dir=skill_dir,
            )
        self._workspace_prepared = False

        cmd = _build_cmd(
            model=model,
            reasoning=reasoning,
            workspace_dir=workspace_dir,
            sandbox=sandbox,
            model_provider=model_provider,
            network_access=network_access,
        )
        cmd.append(prompt)

        if log_path is None:
            raise ValueError("CodexRunner.run requires log_path")
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        stdout_lines = await run_subprocess(cmd, log_path, timeout)
        events = parse_jsonl_events(stdout_lines)

        if trace_path is not None:
            trace_path = Path(trace_path)
            trace_path.write_text(json.dumps(events, indent=4))

        return RunResult(
            final_text=extract_final_text(events), events=events, usage=None,
        )

    async def run_persistent(
        self,
        prompt: str,
        *,
        session_id: Optional[str] = None,
        workspace_dir: Path,
        model: str,
        reasoning: Optional[str] = None,
        system_prompt: Optional[str] = None,
        sandbox: Sandbox = "workspace-write",
        log_path: Optional[Path] = None,
        messages_path: Optional[Path] = None,
        timeout: float = 20 * 60,
        model_provider: Optional[str] = None,
    ) -> tuple[RunResult, str]:
        """Run with persistent session. Returns (RunResult, thread_id)."""
        workspace_dir = Path(workspace_dir).resolve()

        if session_id is None:
            if system_prompt is not None:
                workspace_dir.mkdir(parents=True, exist_ok=True)
                agents_md = workspace_dir / "AGENTS.md"
                if agents_md.exists():
                    agents_md.unlink()
                agents_md.write_text(system_prompt)

            cmd = _build_persistent_cmd(
                model=model,
                reasoning=reasoning,
                workspace_dir=workspace_dir,
                sandbox=sandbox,
                model_provider=model_provider,
            )
            cmd.append(prompt)
        else:
            cmd = _build_resume_cmd(
                session_id, model=model, model_provider=model_provider,
            )
            cmd.append(prompt)

        if log_path is None:
            raise ValueError("run_persistent requires log_path")
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        stdout_lines = await run_subprocess(cmd, log_path, timeout, cwd=str(workspace_dir))
        events = parse_jsonl_events(stdout_lines)

        if messages_path is not None:
            messages_path = Path(messages_path)
            messages_path.parent.mkdir(parents=True, exist_ok=True)
            messages_path.write_text(json.dumps(events, indent=4))

        thread_id = extract_thread_id(events) or session_id
        if thread_id is None:
            raise RuntimeError(
                "Could not extract thread_id from codex events — "
                "session persistence will not work"
            )

        result = RunResult(
            final_text=extract_final_text(events), events=events, usage=None,
        )
        return result, thread_id
