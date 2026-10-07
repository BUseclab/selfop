#!/usr/bin/env python3
"""Inspect a CyberGym data point across steps.

Usage: python show_datapoint.py <data_id> [--step <step_number>]

If --step is not provided, defaults to the latest step found in steps/.
"""
import json
import re
import sys
from pathlib import Path


TICK, CROSS = "\u2713", "\u2717"


def _trunc(output, max_chars):
    if max_chars and len(output) > max_chars:
        mid = max_chars // 2
        return output[:mid] + f"\n ... [truncated {len(output) - max_chars} chars] ...\n" + output[-mid:]
    return output


def _redact_codex(messages, max_output):
    ordered_ids, seen, completed = [], set(), {}
    for msg in messages:
        evt = msg.get("type", "")
        if evt not in ("item.started", "item.completed"):
            continue
        item = msg.get("item", {})
        iid = item.get("id", "")
        if iid and iid not in seen:
            ordered_ids.append(iid)
            seen.add(iid)
        if evt == "item.completed" and iid:
            completed[iid] = item

    lines, n = [], 0
    for iid in ordered_ids:
        item = completed.get(iid)
        if not item:
            continue
        if item.get("type") == "agent_message":
            t = item.get("text", "")
            if t:
                lines.append("[TEXT]  " + t)
        elif item.get("type") == "command_execution":
            n += 1
            cmd = item.get("command", "")
            lines.append('[CALL %d]  bash(cmd="%s")' % (n, cmd))
            lines.append("[RESULT] " + _trunc(item.get("aggregated_output", ""), max_output))
        lines.append("")
    return "\n".join(lines)


def _redact_trace(messages, max_output=500):
    if not isinstance(messages, list) or not messages:
        return "(empty trace)"
    first = messages[0]
    for c in messages:
        if isinstance(c, dict) and set(c.keys()) != {"raw"}:
            first = c
            break
    if isinstance(first, dict) and first.get("type") in (
        "thread.started", "turn.started", "item.started",
        "item.completed", "turn.completed",
    ):
        return _redact_codex(messages, max_output)
    return "%d messages -- format not recognised" % len(messages)


# ── Section printers ──────────────────────────────────────────────────

def _print_batch_line(meta_dir):
    """Section 1: step-score table row for this task."""
    path = meta_dir / "batch_line.txt"
    if not path.exists():
        return
    print()
    print("# Run Summary")
    print("\"\"\"\n")
    print(path.read_text())
    print("\"\"\"")


def _print_score(dp_dir):
    """Section 2: hierarchical tick/cross rendering of score.json."""
    path = dp_dir / "score.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return

    sym = lambda v: TICK if v else CROSS

    print()
    print("# Per-Field Score (based on which the final correctness was derived)")
    print("\"\"\"\n")
    print(f"success: {sym(data.get('success'))}")

    fields = data.get("fields", {})
    if fields:
        print("fields:")
        for fname, fval in fields.items():
            print(f"  {fname}: {sym(fval.get('success'))}")
            for sub_key, sub_val in fval.items():
                if sub_key == "success":
                    continue
                print(f"    {sub_key}: {sym(sub_val)}")
    print("\"\"\"")


def _print_extra_meta(meta_dir):
    """Section 3: extra_meta.json rendered as titled sections."""
    path = meta_dir / "extra_meta.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return
    if not data:
        return

    print()
    print("# Extra Metadata (Only visible to you, and not the agent while solving the task)")
    for entry in data:
        print()
        print("## %s" % entry.get("name"))
        print(f"\"\"\"\n{entry.get('content')}\n\"\"\"")


def _print_trace(dp_dir):
    """Section 4: redacted agent trace."""
    path = dp_dir / "trace.json"
    if not path.exists():
        return
    print()
    print("# Agent's Trace")
    raw = json.loads(path.read_text())
    print(f"\"\"\"\n{_redact_trace(raw)}\n\"\"\"")


def _find_latest_step(steps_dir: Path) -> str | None:
    """Scan steps/ directory for the highest numbered step_N."""
    if not steps_dir.exists():
        return None
    step_nums = []
    for d in steps_dir.iterdir():
        if not d.is_dir():
            continue
        m = re.match(r"step_(\d+)$", d.name)
        if m:
            step_nums.append(int(m.group(1)))
    if not step_nums:
        return None
    return str(max(step_nums))


# ── Main ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python show_datapoint.py <data_id> [--step <step_number>]")
        sys.exit(1)

    data_id = None
    step = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--step" and i + 1 < len(args):
            step = args[i + 1]
            i += 2
        else:
            if data_id is None:
                data_id = args[i]
            i += 1

    if data_id is None:
        print("Usage: python show_datapoint.py <data_id> [--step <step_number>]")
        sys.exit(1)

    safe_id = data_id.replace(":", "_")
    steps_dir = Path(__file__).parent / "steps"

    if not steps_dir.exists():
        print("No steps/ directory found.")
        sys.exit(1)

    if step is None:
        step = _find_latest_step(steps_dir)
        if step is None:
            print("No step directories found in steps/.")
            sys.exit(1)

    step_prefix = f"step_{step}"

    found = False
    for step_d in sorted(steps_dir.iterdir()):
        if not step_d.is_dir():
            continue
        if step_d.name != step_prefix:
            continue
        dp_dir = step_d / safe_id
        if not dp_dir.is_dir():
            continue

        found = True
        meta_dir = dp_dir / "meta"

        print()
        print("=" * 70)
        print("  %s  --  %s" % (data_id, step_d.name))
        print("=" * 70)

        _print_trace(dp_dir)
        _print_batch_line(meta_dir)
        _print_score(dp_dir)
        _print_extra_meta(meta_dir)

    if not found:
        print("Data point '%s' not found in step_%s." % (data_id, step))
        sys.exit(1)


if __name__ == "__main__":
    main()
