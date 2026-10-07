"""Generic Docker runner for coding agents (Codex, Claude Code, etc.).

Each agent type is registered in AGENTS with its image, auth dir, and
container home path. The runner handles image selection, auth mounting,
skill injection, workspace binding, container lifecycle, log streaming,
and NDJSON event parsing.

To add a new agent: add an AgentConfig entry to AGENTS and create a
matching docker/<agent>/Dockerfile + run.sh.
"""

from __future__ import annotations

import os
import json
import shutil
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import uuid4

import docker
from docker.errors import NotFound

logger = logging.getLogger(__name__)


# ── Agent type configuration ─────────────────────────────────────────

@dataclass
class AgentConfig:
    image: str       # Docker image name
    auth_dir: str    # Host auth dir name under ~/ (e.g. ".codex")
    home_path: str   # Container path where auth + skills are expected
    skill_symbol: str # Symbol to use for skill injection


AGENTS: dict[str, AgentConfig] = {
    "codex": AgentConfig(
        image="cybergym/codex:latest",
        auth_dir=".codex",
        home_path="/home/agent/.codex",
        skill_symbol="$"
    ),
    "claude": AgentConfig(
        image="cybergym/claude:latest",
        auth_dir=".claude",
        home_path="/home/agent/.claude",
        skill_symbol="/"
    ),
}


# ── Result ────────────────────────────────────────────────────────────

@dataclass
class RunResult:
    final_text: str
    events: list[dict]
    usage: Optional[dict]


# ── Runner ────────────────────────────────────────────────────────────

class AgentDockerRunner:
    """Run any supported agent CLI inside a Docker container.

    Usage:
        runner = AgentDockerRunner("codex")
        runner.prepare_workspace(ws_dir, skill_path=..., skill_name=...)
        result = await runner.run(prompt, workspace_dir=ws_dir, model=..., ...)
    """

    def __init__(self, agent: str = "codex"):
        if agent not in AGENTS:
            raise ValueError(f"Unknown agent {agent!r}; available: {sorted(AGENTS)}")
        self.agent = agent
        self._cfg = AGENTS[agent]
        self.image = self._cfg.image
        self._client = docker.from_env()

    # ── Run ───────────────────────────────────────────────────────

    async def run(
        self,
        prompt: str,
        *,
        agent_home: Path,
        run_output_dir: Path,
        model: str,
        reasoning: Optional[str] = None,
        log_path: Path,
        trace_path: Path,
        timeout: float = 30 * 60,
        model_provider: Optional[str] = None,
        skill_name: Optional[str] = None,
    ) -> RunResult:
        """Start container, stream logs, parse events, cleanup."""

        agent_home = Path(agent_home).resolve()
        run_output_dir = Path(run_output_dir).resolve()
        log_path = Path(log_path).resolve()
        trace_path = Path(trace_path).resolve()

        # Environment variables passed to the container's run.sh
        if skill_name:
            prompt = f"{self._cfg.skill_symbol}{skill_name} {prompt}"
        env: dict[str, str] = {
            "PROMPT": prompt,
            "MODEL": model,
            "HOME": "/home/agent",
        }
        if reasoning:
            env["REASONING"] = reasoning
        if model_provider:
            env["MODEL_PROVIDER"] = model_provider

        volumes = self._build_volumes(agent_home, run_output_dir)
        name = f"agent-{self.agent}-{uuid4().hex[:12]}"

        # Fix permissions of the run output directory
        run_output_dir.chmod(0o777)
        for path in run_output_dir.rglob("*"):
            try:
                path.chmod(0o777)
            except Exception:
                pass

        # Fix permissions of the agent home
        agent_home.chmod(0o777)
        for path in agent_home.rglob("*"):
            try:
                path.chmod(0o777)
            except Exception:
                pass

        container = None
        try:
            container = self._client.containers.create(
                image=self.image,
                name=name,
                environment=env,
                working_dir="/task-run/workspace",
                volumes=volumes,
                user=f"{os.getuid()}:{os.getgid()}",
                network_mode="host",
                detach=True,
            )
            container.start()

            lines = await self._stream_logs(container, log_path, timeout)
            events = self._parse_events(lines)

            if trace_path:
                Path(trace_path).parent.mkdir(parents=True, exist_ok=True)
                Path(trace_path).write_text(json.dumps(events, indent=2))

            return RunResult(
                final_text=self._extract_final_text(events),
                events=events,
                usage=None,
            )
        except asyncio.TimeoutError:
            if container:
                container.kill()
            raise
        finally:
            if container:
                try:
                    container.remove(force=True)
                except NotFound:
                    pass

    # ── Private helpers ───────────────────────────────────────────

    def _build_volumes(self, agent_home: Path, run_output_dir: Path) -> dict:
        vols: dict[str, dict] = {
            str(run_output_dir): {"bind": "/task-run", "mode": "rw"},
        }

        meta_dir = run_output_dir / "meta"
        if meta_dir.is_dir():
            vols[str(meta_dir)] = {"bind": "/task-run/meta", "mode": "ro"}

        vols[str(agent_home)] = {
            "bind": self._cfg.home_path, "mode": "rw",
        }

        config_toml = agent_home / "config.toml"
        if config_toml.is_file():
            vols[str(config_toml)] = {"bind": f"{self._cfg.home_path}/config.toml", "mode": "ro"}

        skills_dir = agent_home / "skills"
        if skills_dir.is_dir():
            vols[str(skills_dir)] = {"bind": f"{self._cfg.home_path}/skills", "mode": "ro"}

        return vols

    async def _stream_logs(
        self, container, log_path: Path, timeout: float,
    ) -> list[str]:
        """Stream container stdout to disk + memory, respecting timeout."""
        loop = asyncio.get_event_loop()

        def _blocking() -> list[str]:
            chunks: list[str] = []
            with open(log_path, "w") as fh:
                for chunk in container.logs(stream=True, follow=True):
                    text = chunk.decode(errors="replace")
                    fh.write(text)
                    fh.flush()
                    chunks.append(text)
            container.wait()
            return chunks

        return await asyncio.wait_for(
            loop.run_in_executor(None, _blocking), timeout=timeout,
        )

    def _parse_events(self, raw: list[str]) -> list[dict]:
        """Parse NDJSON log output into a list of event dicts."""
        events: list[dict] = []
        for line in "".join(raw).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"raw": line})
        return events

    def _extract_final_text(self, events: list[dict]) -> str:
        """Extract the last agent message from parsed events."""
        if self.agent == "codex":
            for e in reversed(events):
                item = e.get("item", {})
                if (e.get("type") == "item.completed"
                        and item.get("type") == "agent_message"):
                    return item.get("text", "")

        elif self.agent == "claude":
            for e in reversed(events):
                if e.get("type") == "assistant" and "content" in e:
                    content = e["content"]
                    if isinstance(content, list):
                        return "\n".join(
                            b.get("text", "")
                            for b in content if b.get("type") == "text"
                        )
                    if isinstance(content, str):
                        return content

        # Fallback: last raw line
        for e in reversed(events):
            if "raw" in e:
                return e["raw"]
        return ""
