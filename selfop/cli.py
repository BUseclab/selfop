"""`selfop` command line: `selfop train ...` or `selfop eval ...`."""
from __future__ import annotations

import sys

from selfop import task_runner, train

COMMANDS = {
    "train": train.main,      # optimize a skill with SelfOp
    "eval": task_runner.main,  # evaluate a skill (agent_home) on a data split
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("usage: selfop {train,eval} [options]   (selfop <command> -h for options)")
        sys.exit(2)
    command = sys.argv.pop(1)
    sys.argv[0] = f"selfop {command}"
    COMMANDS[command]()
