"""Theme Novelty Classifier for convergence detection.

Classifies selected improvement themes from the current optimization step
against a persisted theme history using LLM-based semantic matching.

Three-way classification:
  - Novel: no semantically equivalent theme in any prior step
  - Common (same causal): equivalent theme seen before with same failure mechanism
  - Common (diff causal): equivalent theme seen before but driven by different failures

The classifier uses full cluster summaries (not just theme name + description)
to provide the LLM with enough causal context for reliable classification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypedDict

from openai import AsyncOpenAI
from pydantic import BaseModel, Field


_client = AsyncOpenAI()


# ── Data structures ───────────────────────────────────────────────────

class ThemeHistoryEntry(TypedDict):
    theme: str
    description: str
    summary: str
    first_seen_step: int
    seen_at_steps: list[int]


ThemeHistory = list[ThemeHistoryEntry]


class ThemeClassification(TypedDict):
    index: int
    category: str  # "novel" | "common_same_causal" | "common_diff_causal"
    matched_known_index: int | None
    rationale: str


class ClassificationResult(TypedDict):
    classifications: list[ThemeClassification]
    novel_count: int
    common_same_count: int
    common_diff_count: int
    total: int


# ── Pydantic models for LLM structured output ────────────────────────

# Pass 1: theme matching (name + description only)

class Pass1Entry(BaseModel):
    current_index: int = Field(
        description="0-based index into the CURRENT THEMES list."
    )
    matched_known_indices: list[int] = Field(
        description=(
            "Indices into the KNOWN THEMES list that address the same actionable "
            "improvement as this current theme. A current theme may match multiple "
            "known entries when variants of the same improvement exist in history. "
            "Empty list if the current theme is novel (no known theme covers it)."
        )
    )
    rationale: str = Field(
        description=(
            "Why this theme is novel (which known themes were considered and why "
            "none require the same skill edit), or which known themes match and "
            "why they call for the same actionable improvement."
        )
    )


class Pass1Result(BaseModel):
    entries: list[Pass1Entry] = Field(
        description=(
            "One entry per CURRENT theme, in index order. Every current theme "
            "must appear exactly once."
        )
    )


# Pass 2: causal chain novelty (one call per matched theme)

class Pass2Result(BaseModel):
    new_mechanism: bool = Field(
        description=(
            "True if the failure mechanism described in the current theme's "
            "summary is NOT already covered by any of the known family "
            "entries' summaries — a different or extended skill instruction "
            "would be needed. False if an existing known entry's summary "
            "describes the same mechanism — the same instruction would work."
        )
    )
    best_match_known_index: int = Field(
        description=(
            "If new_mechanism is false: the K[idx] index of the known entry "
            "whose failure mechanism best matches the current theme's. "
            "If new_mechanism is true: set to -1."
        )
    )
    rationale: str = Field(
        description=(
            "Which known entry's summary was compared, what failure mechanism "
            "the current summary describes, and why it is or is not already "
            "covered by an existing known summary."
        )
    )


# ── Pass 1: Theme Matching ────────────────────────────────────────────

PASS1_SYSTEM = """\
You are a theme-matching assistant. You receive two lists:
- CURRENT THEMES: selected improvement themes from the current step
- KNOWN THEMES: improvement themes from prior steps, each preserved as originally observed

Each theme has a name and a brief description. Your task: for EACH current theme, \
identify which known themes (if any) address the same actionable improvement.

MATCHING CRITERION:

Two themes match when they call for the SAME improvement — when writing a \
contextual instruction to address one would also address the other. Do NOT match on abstract \
category or topic similarity.

For example: "validate before submission" and "validate against the real scorer binary, \
not a local build" both involve validation, but they call for different skill edits. \
The first needs "always validate before submitting." The second needs "validate against \
the exact scorer binary." These should NOT match.

Conversely: "delegate broad search to explorer agent" and "delegate ambiguous mapping to \
sub-agents" use different words but both call for the same improvement: "when the search \
space is large, delegate to a sub-agent instead of doing it yourself." These SHOULD match.

MULTIPLE MATCHES:

A current theme may match multiple known entries. This happens when the same improvement \
area has accumulated variants over time (e.g., K[0] "delegation" from step 0 and K[5] \
"delegation scoping" from step 3 are both about delegation). Include ALL matching known \
indices in matched_known_indices.

EXAMPLES (assume known themes K[0]..K[5] exist):

Novel: C[0] "workspace and repo root verification" — no known theme covers environment \
setup or directory verification. → matched_known_indices=[].

Single match: C[1] "delegate broad search to explorer agent" — matches K[1] "delegate \
ambiguous mapping to sub-agents" (same improvement: delegate when search space is large). \
No other known themes cover delegation. → matched_known_indices=[1].

Multi-match: C[2] "harness validation and scorer parity" — matches K[0] "validate \
before submission" and K[4] "exact scorer binary validation." Both K[0] and K[4] are \
about validation and the improvement for C[2] overlaps with both. \
→ matched_known_indices=[0, 4].

RULES:

- Return one entry per current theme. Every current theme must appear exactly once.
- Only match if you are confident that the two themes belong to the same improvement family, \
otherwise leave matched_known_indices empty.
- Only match on the name and description provided. Do not infer causal detail."""


def _build_pass1_prompt(
    current_themes: list[dict],
    known_themes: list[ThemeHistoryEntry],
) -> str:
    parts = []

    parts.append(f"# CURRENT THEMES ({len(current_themes)})")
    for i, t in enumerate(current_themes):
        parts.append(f"  C[{i}] {t['theme']}: {t['description']}")
    parts.append("")

    parts.append(f"# KNOWN THEMES ({len(known_themes)})")
    for i, t in enumerate(known_themes):
        parts.append(f"  K[{i}] {t['theme']}: {t['description']}")
    return "\n".join(parts)


# ── Pass 2: Causal Chain Novelty ─────────────────────────────────────

PASS2_SYSTEM = """\
You are a causal-chain analyst. You receive one improvement theme from the current \
optimization step and one or more KNOWN FAMILY entries from prior steps that address \
the same improvement area.

You see:
- CURRENT: the theme's detailed summary describing specific failure mechanisms, \
root causes, and evidence from tasks at this step
- KNOWN FAMILY: summaries of prior observations of the same improvement area

Your task: determine whether the failure mechanism in the current summary is ALREADY \
COVERED by any known family summary, or whether it represents a NEW mechanism.

DECISION CRITERION:

Ask: would the exact same contextual instruction that addresses a known family entry \
also fix the current failure? Read the summaries carefully — they contain specific \
causal detail (which tasks failed, why, what the agent did wrong).

- COVERED (new_mechanism=false): the current summary describes the same class of \
agent mistake, the same root cause, or the same gap as an existing known entry. The \
same instruction would work. Set best_match_known_index to the K[idx] of the known \
entry whose mechanism is the closest match.

- NEW MECHANISM (new_mechanism=true): the current summary describes a different \
failure pattern, a different root cause, or a different gap — even though the \
high-level improvement area is the same. A different or extended instruction would \
be needed. Set best_match_known_index to -1.

EXAMPLES:

Covered: Current summary says "agent attempted exhaustive file search itself instead \
of delegating, wasting 80% of time budget." Known K[2] says "agent did not delegate \
broad search to sub-agents, spending most of its time reading files." Same mistake \
(not delegating), same fix ("delegate broad search"). → new_mechanism=false, \
best_match_known_index=2.

New mechanism: Current summary says "agent delegated search to explorer sub-agent but \
gave it no scope constraints, so the explorer read hundreds of irrelevant files and \
timed out." Known K[2] says "agent did not delegate at all." Opposite problems: one \
never delegated, the other delegated without bounds. Different instructions needed. \
→ new_mechanism=true, best_match_known_index=-1.

RULES:

- Only say it is new if you are confident that the causal mechanism is different from \
the known family entries, otherwise say it is covered.
- Base your judgment SOLELY on the summary content. Ignore theme names — the matching \
decision was already made."""


def _build_pass2_prompt(
    current_theme: dict,
    theme_history: ThemeHistory,
    known_indices: list[int],
) -> str:
    """Build Pass 2 prompt for a single matched theme vs its known family."""
    summary = _extract_summary(current_theme)

    parts = []
    parts.append(f"# CURRENT THEME")
    parts.append(f"  \"{current_theme['theme']}\": {current_theme.get('description', '')}")
    parts.append(f"  Summary: {summary}")
    parts.append("")
    parts.append(f"# KNOWN FAMILY ({len(known_indices)} entries)")
    for ki in known_indices:
        entry = theme_history[ki]
        steps_str = ", ".join(str(s) for s in entry["seen_at_steps"])
        parts.append(f"  K[{ki}] \"{entry['theme']}\" (steps {steps_str}):")
        parts.append(f"    Summary: {entry.get('summary', '(no summary)')}")
    parts.append("")
    return "\n".join(parts)


def _extract_summary(theme: dict) -> str:
    """Extract the summary string from a theme dict (handles nested dict or str)."""
    summary = theme.get("summary")
    if summary is None:
        return ""
    if isinstance(summary, dict):
        return summary.get("summary", "")
    return str(summary)


# ── Result helpers ────────────────────────────────────────────────────

def _build_result(classifications: list[ThemeClassification]) -> ClassificationResult:
    novel = sum(1 for c in classifications if c["category"] == "novel")
    same = sum(1 for c in classifications if c["category"] == "common_same_causal")
    diff = sum(1 for c in classifications if c["category"] == "common_diff_causal")
    return ClassificationResult(
        classifications=classifications,
        novel_count=novel,
        common_same_count=same,
        common_diff_count=diff,
        total=len(classifications),
    )


def _all_novel(total: int, rationale: str = "") -> ClassificationResult:
    classifications = [
        ThemeClassification(
            index=i,
            category="novel",
            matched_known_index=None,
            rationale=rationale or "First step — no prior themes to compare against.",
        )
        for i in range(total)
    ]
    return _build_result(classifications)


# ── Pass 1 execution ─────────────────────────────────────────────────

async def _run_pass1(
    selected_improvements: list[dict],
    theme_history: ThemeHistory,
    *,
    model: str,
    reasoning: str,
) -> Pass1Result | None:
    """Run Pass 1: match current themes against known themes by name+description."""
    prompt = _build_pass1_prompt(selected_improvements, theme_history)
    try:
        response = await _client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": PASS1_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            text_format=Pass1Result,
            reasoning={"effort": reasoning},
        )
        return response.output_parsed
    except Exception as e:
        print(f"  [WARN] Pass 1 (matching) failed: {e}")
        return None


def _process_pass1(
    result: Pass1Result | None,
    total: int,
    n_known: int,
) -> tuple[set[int], dict[int, list[int]]]:
    """Extract novel indices and matched {current_idx: [known_idx, ...]} from Pass 1.

    Validates indices and treats missing/invalid entries as novel.
    """
    matched: dict[int, list[int]] = {}
    seen: set[int] = set()

    if result is not None:
        for entry in result.entries:
            idx = entry.current_index
            if not (0 <= idx < total) or idx in seen:
                continue
            seen.add(idx)
            valid_known = [
                ki for ki in entry.matched_known_indices
                if 0 <= ki < n_known
            ]
            if valid_known:
                matched[idx] = valid_known

    novel_indices = set(range(total)) - set(matched.keys())
    return novel_indices, matched


# ── Pass 2 execution ─────────────────────────────────────────────────

async def _run_pass2_single(
    current_theme: dict,
    theme_history: ThemeHistory,
    known_indices: list[int],
    *,
    model: str,
    reasoning: str,
) -> Pass2Result | None:
    """Run Pass 2 for a single matched theme vs its known family."""
    prompt = _build_pass2_prompt(current_theme, theme_history, known_indices)
    try:
        response = await _client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": PASS2_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            text_format=Pass2Result,
            reasoning={"effort": reasoning},
        )
        return response.output_parsed
    except Exception as e:
        print(f"  [WARN] Pass 2 failed for \"{current_theme.get('theme', '?')}\": {e}")
        return None


async def _run_pass2(
    selected_improvements: list[dict],
    theme_history: ThemeHistory,
    matched: dict[int, list[int]],
    *,
    model: str,
    reasoning: str,
) -> dict[int, tuple[bool, int]]:
    """Run Pass 2 for all matched themes (one LLM call each, concurrent).

    Returns {current_idx: (new_mechanism, best_known_idx)}.
    On failure, defaults to new_mechanism=True (diff_causal).
    """
    import asyncio

    async def _handle(cidx: int, kindices: list[int]) -> tuple[int, tuple[bool, int]]:
        result = await _run_pass2_single(
            selected_improvements[cidx], theme_history, kindices,
            model=model, reasoning=reasoning,
        )
        if result is None:
            return cidx, (True, -1)
        if result.new_mechanism:
            return cidx, (True, -1)
        best = result.best_match_known_index
        if 0 <= best < len(theme_history) and best in kindices:
            return cidx, (False, best)
        return cidx, (False, kindices[0])

    tasks = [_handle(cidx, kindices) for cidx, kindices in matched.items()]
    results = await asyncio.gather(*tasks)
    return dict(results)


# ── Two-pass orchestration ───────────────────────────────────────────

def _combine_results(
    total: int,
    novel_indices: set[int],
    matched: dict[int, list[int]],
    causal: dict[int, tuple[bool, int]],
    pass1_result: Pass1Result | None,
) -> ClassificationResult:
    """Combine Pass 1 + Pass 2 results into a unified ClassificationResult."""
    # Build rationale lookup from Pass 1
    p1_rationales: dict[int, str] = {}
    if pass1_result is not None:
        for entry in pass1_result.entries:
            if 0 <= entry.current_index < total:
                p1_rationales[entry.current_index] = entry.rationale

    classifications: list[ThemeClassification] = []
    for i in range(total):
        if i in novel_indices:
            classifications.append(ThemeClassification(
                index=i,
                category="novel",
                matched_known_index=None,
                rationale=p1_rationales.get(i, "No matching known theme."),
            ))
        else:
            new_mechanism, best_known = causal[i]
            if new_mechanism:
                family = matched[i]
                classifications.append(ThemeClassification(
                    index=i,
                    category="common_diff_causal",
                    matched_known_index=family[0],
                    rationale=p1_rationales.get(i, "Matched but new causal mechanism."),
                ))
            else:
                classifications.append(ThemeClassification(
                    index=i,
                    category="common_same_causal",
                    matched_known_index=best_known,
                    rationale=p1_rationales.get(i, "Matched with same causal mechanism."),
                ))

    return _build_result(classifications)


async def classify_themes(
    selected_improvements: list[dict],
    theme_history: ThemeHistory,
    *,
    model: str = "gpt-5.4-mini",
    reasoning: str = "high",
) -> ClassificationResult:
    """Classify selected improvement themes against the theme history.

    Two-pass architecture:
      Pass 1: match themes by name + description (no summaries)
      Pass 2: check causal novelty for matched themes (summaries only)

    For step 0 (empty history), all themes are novel by definition.
    """
    total = len(selected_improvements)

    if total == 0:
        return _all_novel(0)

    if not theme_history:
        return _all_novel(total)

    # Pass 1: matching
    print(f"    Pass 1: matching {total} current themes against "
          f"{len(theme_history)} known themes...")
    pass1 = await _run_pass1(
        selected_improvements, theme_history,
        model=model, reasoning=reasoning,
    )
    novel_indices, matched = _process_pass1(pass1, total, len(theme_history))
    print(f"    Pass 1 result: {len(novel_indices)} novel, {len(matched)} matched")

    # Pass 2: causal chain (only if there are matches, one call per theme)
    causal: dict[int, tuple[bool, int]] = {}
    if matched:
        print(f"    Pass 2: checking causal novelty for {len(matched)} "
              f"matched themes ({len(matched)} LLM calls)...")
        causal = await _run_pass2(
            selected_improvements, theme_history, matched,
            model=model, reasoning=reasoning,
        )
        n_new = sum(1 for v in causal.values() if v[0])
        n_same = len(causal) - n_new
        print(f"    Pass 2 result: {n_same} same_causal, {n_new} diff_causal")

    return _combine_results(total, novel_indices, matched, causal, pass1)


# ── SNR computation ───────────────────────────────────────────────────

def compute_snr(result: ClassificationResult, p0: float = 0.1) -> float:
    """Compute z-score measuring signal above baseline noise.

    Uses a one-proportion z-test against p0 (the empirically calibrated
    baseline rate at which themes appear novel even when the skill has
    converged). This normalizes for sample size K — small K requires a
    higher observed proportion to produce a significant z-score.

    z = (p_hat - p0) / sqrt(p0 * (1 - p0) / K)

    Returns the z-score (higher = more signal). Compared against z_crit
    (default 1.0) in the convergence detector.
    """
    k = result["total"]
    if k == 0:
        return float("inf")  # no themes = no noise = proceed
    signal = result["novel_count"] + result["common_diff_count"]
    p_hat = signal / k
    denominator = (p0 * (1 - p0) / k) ** 0.5
    return (p_hat - p0) / denominator


# ── Theme history management ──────────────────────────────────────────

def _update_history_immutable(
    theme_history: ThemeHistory,
    selected_improvements: list[dict],
    classification: ClassificationResult,
    step: int,
) -> ThemeHistory:
    """Update theme history with immutable entries.

    - novel: append new entry with original theme data
    - common_same_causal: only append step to matched entry's seen_at_steps
      (do NOT overwrite name/description/summary — preserve narrow reference)
    - common_diff_causal: append step to matched entry's seen_at_steps AND
      add a new entry with the current theme's original data (represents a
      new causal variant that deserves its own reference point)
    """
    for cls in classification["classifications"]:
        idx = cls["index"]
        theme = selected_improvements[idx]
        cat = cls["category"]
        known_idx = cls["matched_known_index"]

        if cat == "novel":
            theme_history.append(ThemeHistoryEntry(
                theme=theme["theme"],
                description=theme["description"],
                summary=_extract_summary(theme),
                first_seen_step=step,
                seen_at_steps=[step],
            ))
        elif cat == "common_same_causal":
            if known_idx is not None and known_idx < len(theme_history):
                theme_history[known_idx]["seen_at_steps"].append(step)
        elif cat == "common_diff_causal":
            if known_idx is not None and known_idx < len(theme_history):
                theme_history[known_idx]["seen_at_steps"].append(step)
            theme_history.append(ThemeHistoryEntry(
                theme=theme["theme"],
                description=theme["description"],
                summary=_extract_summary(theme),
                first_seen_step=step,
                seen_at_steps=[step],
            ))

    return theme_history


async def classify_and_update(
    selected_improvements: list[dict],
    theme_history: ThemeHistory,
    step: int,
    *,
    model: str = "gpt-5.4-mini",
    reasoning: str = "high",
) -> tuple[ClassificationResult, ThemeHistory]:
    """Classify themes and update history in one call.

    Primary entry point. Uses two-pass classification (Pass 1: matching,
    Pass 2: causal chain), then updates theme history with immutable entries.
    """
    total = len(selected_improvements)

    if total == 0:
        return _all_novel(0), theme_history

    if not theme_history:
        result = _all_novel(total)
        for theme in selected_improvements:
            theme_history.append(ThemeHistoryEntry(
                theme=theme["theme"],
                description=theme["description"],
                summary=_extract_summary(theme),
                first_seen_step=step,
                seen_at_steps=[step],
            ))
        return result, theme_history

    result = await classify_themes(
        selected_improvements, theme_history,
        model=model, reasoning=reasoning,
    )
    theme_history = _update_history_immutable(
        theme_history, selected_improvements, result, step,
    )
    return result, theme_history


# ── Persistence ───────────────────────────────────────────────────────

def load_theme_history(path: Path) -> ThemeHistory:
    """Load theme history from a JSON file. Returns empty list if not found."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    return json.loads(path.read_text())


def save_theme_history(path: Path, history: ThemeHistory) -> None:
    """Persist theme history to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2))
