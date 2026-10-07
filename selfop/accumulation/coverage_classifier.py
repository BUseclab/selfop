"""Skill Coverage Classifier for convergence detection.

Alternative to the theme-history classifier (theme_classifier.py).
Instead of comparing improvement themes against a persisted theme history,
this classifier uses a CodexRunner agent to read the current agent_home
snapshot and determine whether each improvement theme is already addressed
by the skill's existing instructions.

Two-category classification:
  - gap:     the skill does NOT contain specific guidance for this failure pattern
  - covered: the skill contains actionable instructions that address this failure

The output is mapped to the standard ClassificationResult shape so that all
existing convergence_mode (novelty/snr), convergence_gate, and logging logic
works unchanged.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from selfop.accumulation.theme_classifier import ClassificationResult, ThemeClassification


# ── System prompt ─────────────────────────────────────────────────────

COVERAGE_SYSTEM_PROMPT = """\
You are a skill coverage analyst. You will be given a set of improvement \
themes extracted from a batch of task runs. Each theme describes a failure \
pattern observed across multiple tasks, along with a summary of the specific \
mechanisms involved.

Your job is to read the agent's current orchestration files in `agent_home/` \
and determine whether each improvement theme is already **specifically \
addressed** by the existing skill instructions.

# YOUR WORKSPACE

```
agent_home/
└── skills/
    └── {skill_name}/
        ├── SKILL.md            ← main skill file
        └── references/         ← on-demand reference docs
```

Read ALL files under `agent_home/skills/{skill_name}/` before classifying.

# CLASSIFICATION CATEGORIES

For each improvement theme, classify it as one of:

- **gap**: The skill does NOT contain specific guidance that would prevent \
this failure pattern. The theme describes a problem the skill hasn't \
addressed, or addresses only at a vague/generic level that clearly isn't \
working (the same failure keeps recurring despite the general language).

- **covered**: The skill already contains **specific, actionable \
instructions** that directly target this failure pattern. You MUST cite \
the exact file (starting from the agent_home directory, NOT the absolute path) and \
the relevant instruction text in the respective field of your response, but \
also mention it briefly in the rationale.

# DECISION CRITERION

The question is NOT "does the skill mention this topic?" — it is "does \
the skill contain an instruction specific enough that an agent following \
it faithfully would avoid the failure described in the theme's summary?"

If the theme describes a failure that keeps happening despite existing \
skill language, that language is not specific enough — classify as **gap**.

# OUTPUT FORMAT

After reading the skill files, do your analysis and output a single JSON block:

```json
{{
  "classifications": [
    {{
      "index": 0,
      "category": "gap",
      "rationale": "The skill says to validate but does not specify...",
      "cited_instruction": null
    }},
    {{
      "index": 1,
      "category": "covered",
      "rationale": "The skill explicitly requires...",
      "cited_instruction": "harness-proof.md: 'Run the exact scorer binary...'"
    }}
  ]
}}
```

RULES:
- Read ALL files in `agent_home/skills/{skill_name}/` before classifying.
- Every improvement theme must appear exactly once in your output.
- For "covered", you MUST cite the specific instruction from a specific file.
- For "gap", explain what is missing or why existing language is insufficient.
- Be strict: vague coverage is a gap. Only mark "covered" when the \
instruction is specific enough to prevent the exact failure mechanism.\
"""


# ── User prompt builder ───────────────────────────────────────────────

def build_coverage_prompt(
    selected_improvements: list[dict],
    skill_name: str,
) -> str:
    """Build the user prompt listing improvement themes for the classifier."""
    parts = [f"# IMPROVEMENT THEMES ({len(selected_improvements)} total)\n"]
    for i, imp in enumerate(selected_improvements):
        summary = imp.get("summary", "")
        if isinstance(summary, dict):
            summary = summary.get("summary", "")
        parts.append(f"## I[{i}] {imp['theme']}")
        parts.append(f"**Description:** {imp['description']}")
        parts.append(f"**Summary:** {summary}")
        parts.append("")
    parts.append(
        f"Read all files under `agent_home/skills/{skill_name}/` "
        f"(SKILL.md + any references), then classify each theme above."
    )
    return "\n".join(parts)


# ── Output parser ─────────────────────────────────────────────────────

def parse_coverage_result(final_text: str, total: int) -> dict:
    """Extract coverage classifications from the agent's free-text response.

    Returns a dict with keys: classifications, gap_count, covered_count, total.
    """
    classifications: list[dict] = []

    # Try ```json ... ``` fenced block first
    json_match = re.search(
        r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", final_text,
    )
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            classifications = data.get("classifications", [])
        except json.JSONDecodeError:
            pass

    # Fallback: bare JSON object with "classifications" key
    if not classifications:
        json_match = re.search(
            r'\{\s*"classifications"\s*:\s*\[[\s\S]*?\]\s*\}', final_text,
        )
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                classifications = data.get("classifications", [])
            except json.JSONDecodeError:
                pass

    # Fill missing indices as gap (conservative)
    seen = {c.get("index") for c in classifications}
    for i in range(total):
        if i not in seen:
            classifications.append({
                "index": i,
                "category": "gap",
                "rationale": "Missing from classifier output",
                "cited_instruction": None,
            })

    classifications.sort(key=lambda c: c.get("index", 0))

    gap_count = sum(1 for c in classifications if c.get("category") == "gap")
    covered_count = total - gap_count

    return {
        "classifications": classifications,
        "gap_count": gap_count,
        "covered_count": covered_count,
        "total": total,
    }


# ── Mapper to ClassificationResult ───────────────────────────────────

def to_classification_result(coverage_result: dict) -> ClassificationResult:
    """Map coverage classifier output to the standard ClassificationResult.

    Mapping:
      gap     -> novel             (unaddressed = signal)
      covered -> common_same_causal (already handled = no signal)
      (no diff_causal concept)

    Attaches raw coverage detail under '_coverage_detail' for logging.
    """
    mapped_classifications: list[ThemeClassification] = []
    for c in coverage_result["classifications"]:
        category = c.get("category", "gap")
        if category == "gap":
            mapped_cat = "novel"
        else:
            mapped_cat = "common_same_causal"

        mapped_classifications.append(ThemeClassification(
            index=c.get("index", 0),
            category=mapped_cat,
            matched_known_index=None,
            rationale=c.get("rationale", ""),
        ))

    result: ClassificationResult = {
        "classifications": mapped_classifications,
        "novel_count": coverage_result["gap_count"],
        "common_same_count": coverage_result["covered_count"],
        "common_diff_count": 0,
        "total": coverage_result["total"],
    }

    # Attach raw coverage detail for logging/debugging
    result["_coverage_detail"] = {  # type: ignore[typeddict-unknown-key]
        "gap_count": coverage_result["gap_count"],
        "covered_count": coverage_result["covered_count"],
        "classifications": coverage_result["classifications"],
    }

    return result
