#!/usr/bin/env python3
"""Read pre-computed mini-optimizer analyses.

Usage:
  python show_analysis.py <id1> [id2 ...] [--step <step_number>]

If --step is not provided, defaults to the latest step found in analysis_runs/.
"""
import re
import sys
from pathlib import Path


def _find_latest_step(analysis_runs_dir: Path) -> str | None:
    """Scan analysis_runs/ directory for the highest numbered step_N."""
    if not analysis_runs_dir.exists():
        return None
    step_nums = []
    for d in analysis_runs_dir.iterdir():
        if not d.is_dir():
            continue
        m = re.match(r"step_(\d+)$", d.name)
        if m:
            step_nums.append(int(m.group(1)))
    if not step_nums:
        return None
    return str(max(step_nums))


def _print_task(task_id: str, analysis_runs_dir: Path, step_name: str | None) -> bool:
    """Print analysis.txt for a single task.
    Returns True if analysis.txt was found."""
    safe_id = task_id.replace(":", "_")
    found = False

    for step_d in sorted(analysis_runs_dir.iterdir()):
        if not step_d.is_dir():
            continue
        if step_name and step_d.name != step_name:
            continue
        task_dir = step_d / safe_id
        analysis = task_dir / "analysis.txt"
        if not analysis.exists():
            continue
        found = True
        print()
        print("=" * 70)
        print("  %s -- %s" % (task_id, step_d.name))
        print("=" * 70)
        print()
        print(analysis.read_text())
    return found


def main():
    if len(sys.argv) < 2:
        print("Usage: python show_analysis.py <id1> [id2 ...] [--step <step_number>]")
        sys.exit(1)

    task_ids = []
    step = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--step" and i + 1 < len(args):
            step = args[i + 1]
            i += 2
        else:
            task_ids.append(args[i])
            i += 1

    if not task_ids:
        print("Usage: python show_analysis.py <id1> [id2 ...] [--step <step_number>]")
        sys.exit(1)

    analysis_runs_dir = Path(__file__).parent / "analysis_runs"
    if not analysis_runs_dir.exists():
        print("No analysis_runs/ directory found.")
        sys.exit(1)

    if step is None:
        step = _find_latest_step(analysis_runs_dir)
        if step is None:
            print("No step directories found in analysis_runs/.")
            sys.exit(1)

    step_name = f"step_{step}"

    missing = []
    for task_id in task_ids:
        if not _print_task(task_id, analysis_runs_dir, step_name):
            missing.append(task_id)

    if missing:
        print("\nNo analysis found for: %s" % ", ".join(missing))
        sys.exit(1)


if __name__ == "__main__":
    main()
