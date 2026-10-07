"""Structure policy: what the optimizer may edit, and the checker that enforces it."""
from __future__ import annotations

from pathlib import Path

from selfop.policy.prompts import AGENT_HOME_DESCRIPTION, ANALYSIS_SCOPE_HINT

_DIR = Path(__file__).parent

POLICY_FILE = _DIR / "policy.md"
POLICY_CHECKER_FILE = _DIR / "checker.py"

__all__ = ["AGENT_HOME_DESCRIPTION", "ANALYSIS_SCOPE_HINT", "POLICY_FILE", "POLICY_CHECKER_FILE"]
