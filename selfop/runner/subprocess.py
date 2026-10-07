from __future__ import annotations

import asyncio
import json
from pathlib import Path


async def run_subprocess(
    cmd: list[str],
    log_path: Path,
    timeout_seconds: float,
    cwd: str | None = None,
) -> list[str]:
    """Run a CLI command async, stream output to log_path, return stdout lines."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        limit=2**24,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    async def _stream(
        stream: asyncio.StreamReader, log_fh, accumulate: bool,
    ) -> list[str]:
        lines: list[str] = []
        async for raw_line in stream:
            text = raw_line.decode(errors="replace")
            log_fh.write(text)
            log_fh.flush()
            if accumulate:
                lines.append(text)
        return lines

    async def _run_and_wait() -> list[str]:
        with open(log_path, "w") as log_fh:
            stdout_lines, _ = await asyncio.gather(
                _stream(proc.stdout, log_fh, accumulate=True),
                _stream(proc.stderr, log_fh, accumulate=False),
            )
        await proc.wait()
        return stdout_lines

    try:
        stdout_lines = await asyncio.wait_for(
            _run_and_wait(), timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError(f"subprocess timed out after {timeout_seconds}s")
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        raise

    if proc.returncode != 0:
        raise RuntimeError(
            f"subprocess exited with code {proc.returncode} (see {log_path})"
        )

    return stdout_lines


def parse_jsonl_events(lines: list[str]) -> list[dict]:
    """Parse text lines into a JSON event list. Non-JSON lines become {"raw": line}."""
    events: list[dict] = []
    for line in lines:
        line = line.rstrip("\n").strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"raw": line})
    return events
