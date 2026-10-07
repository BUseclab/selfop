"""Gradient Accumulation Pipeline.

Takes a batch of per-task gradient analyses (analysis.txt), extracts
strengths and improvements separately, clusters each via Strategy E
(map-reduce, chunk_size=8), ranks/selects, resolves conflicts, optionally
summarizes per cluster, generates a compliance summary, and renders a
final report for the main optimizer.

Pipeline:
  1.    Extract    — parallel LLM, 1 per task → strengths + improvements
  2.    Cluster    — Strategy E × 2 (strengths, improvements)
  3.    Aggregate  — composite ranking (failure-weighted for improvements,
                     success-concentrated for strengths)
  3.5   Resolve    — detect strength/improvement contradictions, remove
                     losing strengths, annotate winning improvements
  4.    Summarize  — (optional) LLM, 1 per selected cluster
  4.75  Usage      — LLM compliance summary from 'Agent's Usage' sections
  5.    Report     — compact strengths, compliance context, full
                     improvement detail ranked by composite
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import BaseModel, Field


# ── Defaults ──────────────────────────────────────────────────────────
# Inline in function signatures; no module-level config dependency.

_client = AsyncOpenAI()


# ── Checkpoint helpers ────────────────────────────────────────────────

def _save_checkpoint(cache_dir: Path, name: str, data) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / name
    if name.endswith(".txt"):
        path.write_text(data)
    else:
        path.write_text(json.dumps(data, indent=2, default=str))


def _load_checkpoint(cache_dir: Path | None, name: str):
    if cache_dir is None:
        return None
    path = cache_dir / name
    if not path.exists() or path.stat().st_size == 0:
        return None
    if name.endswith(".txt"):
        return path.read_text()
    return json.loads(path.read_text())


# ── Pydantic models ──────────────────────────────────────────────────

class ExtractionResult(BaseModel):
    strengths: list[str] = Field(description="Orchestration-level strengths.")
    improvements: list[str] = Field(description="Orchestration-level improvements.")

class ThemeAssignment(BaseModel):
    theme_id: int = Field(description="Unique integer ID for this theme.")
    theme: str = Field(description="Short theme name.")
    description: str = Field(description="One or two sentence description of what this theme covers.")
    item_ids: list[str] = Field(description="List of item IDs assigned to this theme.")

class ClusteringResult(BaseModel):
    themes: list[ThemeAssignment] = Field(description="List of themes, each with its assigned item IDs. Every item must appear in exactly one theme.")

class ClusterSummary(BaseModel):
    summary: str = Field(description="Non-redundant summary paragraph of the cluster's observations, citing which tasks support each point.")

class ConflictPair(BaseModel):
    strength_theme: str = Field(description="Name of the strength theme that conflicts — the text INSIDE the S[...] brackets, without the 'S[' prefix or ']' suffix.")
    improvement_theme: str = Field(description="Name of the improvement theme that conflicts — the text INSIDE the I[...] brackets, without the 'I[' prefix or ']' suffix.")
    rationale: str = Field(description="Why these two themes contradict each other.")

class ConflictDetectionResult(BaseModel):
    conflicts: list[ConflictPair] = Field(description="Pairs of strength/improvement themes that directly contradict. Empty if no conflicts.")

class UsageSummaryResult(BaseModel):
    summary: str = Field(description="Few bullet points of pure compliance facts: what agents did with the artifacts. No causal reasoning or quality assessment.")


# ── Data loading ──────────────────────────────────────────────────────

def load_gradients(analysis_base: Path, step: int) -> list[dict]:
    step_dir = analysis_base / f"step_{step}"
    gradients = []
    for task_dir in sorted(step_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        analysis_file = task_dir / "analysis.txt"
        if not analysis_file.exists():
            continue
        text = analysis_file.read_text()
        score_file = task_dir / "score.json"
        if score_file.exists():
            solved = json.loads(score_file.read_text()).get("success", False)
        else:
            solved = False
        gradients.append(
            {"task_id": task_dir.name, "analysis_text": text, "solved": solved}
        )
    return gradients


# =====================================================================
#  Step 1: Extraction
# =====================================================================

EXTRACTION_SYSTEM = """\
You are a structured data extractor for a textual backpropagation \
pipeline. We optimize an agent's home directory by analyzing task runs. \
Each analysis decomposes the backward pass via a chain rule:

  d(Loss)/d(AgentHome) = d(Loss)/d(Score) × d(Score)/d(Trajectory) \
× d(Trajectory)/d(AgentHome)

The analysis you receive has three sections corresponding to this chain:

- SCORE ANALYSIS → d(Loss)/d(Score): binary pass/fail outcome and how \
the each scored field contributed to the outcome.

- TRAJECTORY ANALYSIS → d(Score)/d(Trajectory): what the agent \
actually did — behavioral strengths and weaknesses, and how they contributed \
to certain scored fields' outcomes, and suggestions for improvements in \
the agent behavior to improve the scored fields' outcomes.

- ORCHESTRATION ANALYSIS → d(Trajectory)/d(AgentHome): how the \
agent home artifacts caused or failed to cause the observed behaviors in the \
agent's trajectory, and suggestions for improvements in the agent home to \
improve the behavioral outcomes.

Your job: extract strengths and improvements from the ORCHESTRATION \
ANALYSIS section. That is the final gradient — what agent_home should \
preserve or change. Use the TRAJECTORY and SCORE sections to fill in \
evidence for the causal chain, to connect orchestration observation \
to the concrete agent behavior and outcome it produced.

Rules:
- Extract from ORCHESTRATION ANALYSIS. Do not extract standalone \
trajectory-level suggestions that have no orchestration root cause.
- Each item MUST be **self-contained**: the orchestration observation \
plus enough trajectory/score evidence to understand the full **causal \
chain** without reading the original analysis.
- Do NOT merge multiple distinct points into one entry.
- Do NOT invent points not present in the analysis.
- You can re-phrase the information while extracting it, but you MUST \
NOT change or omit it.
"""


async def extract_one(
    task_id: str,
    analysis_text: str,
    solved: bool,
    *,
    model: str = "gpt-5.4-mini",
    reasoning: str = "high",
) -> dict:
    prompt = (
        f"Task ID: {task_id}\nSolved: {solved}\n\n"
        f'ANALYSIS TEXT:\n"""\n{analysis_text}\n"""'
    )
    response = await _client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": EXTRACTION_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        text_format=ExtractionResult,
        reasoning={"effort": reasoning},
    )
    result = response.output_parsed
    return {
        "task_id": task_id,
        "solved": solved,
        "strengths": result.strengths,
        "improvements": result.improvements,
    }


async def run_extraction(
    gradients: list[dict],
    *,
    num_workers: int = 16,
    model: str = "gpt-5.4-mini",
    reasoning: str = "high",
) -> list[dict]:
    sem = asyncio.Semaphore(num_workers)

    async def _guarded(g: dict) -> dict:
        async with sem:
            try:
                return await extract_one(
                    g["task_id"], g["analysis_text"], g["solved"],
                    model=model, reasoning=reasoning,
                )
            except Exception as e:
                print(f"  [WARN] extraction failed for {g['task_id']}: {e}")
                return {
                    "task_id": g["task_id"],
                    "solved": g["solved"],
                    "strengths": [],
                    "improvements": [],
                }

    results = await asyncio.gather(*[_guarded(g) for g in gradients])
    total_s = sum(len(r["strengths"]) for r in results)
    total_i = sum(len(r["improvements"]) for r in results)
    print(f"Extracted {total_s} strengths + {total_i} improvements from {len(results)} gradients")
    return results


def _build_flat_strengths(extractions: list[dict]) -> list[dict]:
    flat = []
    for ext in extractions:
        for i, s in enumerate(ext["strengths"]):
            flat.append({
                "id": f"{ext['task_id']}:s{i}",
                "task_id": ext["task_id"],
                "solved": ext["solved"],
                "description": s,
            })
    return flat


def _build_flat_improvements(extractions: list[dict]) -> list[dict]:
    flat = []
    for ext in extractions:
        for i, imp in enumerate(ext["improvements"]):
            flat.append({
                "id": f"{ext['task_id']}:i{i}",
                "task_id": ext["task_id"],
                "solved": ext["solved"],
                "description": imp,
            })
    return flat


# =====================================================================
#  Step 2: Clustering (Parallel Map + Merge)
# =====================================================================

CLUSTER_MAP_SYSTEM = """\
You are a theme builder for "{item_type}" items. You receive a batch of \
pre-extracted "{item_type}" items (with task IDs and metadata).

Your job is to group the items into coherent themes based on the "{item_type}" type:
- Keep **granularity consistent**: not so broad that unrelated ideas merge, \
not so narrow that restatements of the same idea stay separate.
- Each theme should capture a single distinct pattern or concept.
- Write a **short description** (one or two sentences) for each theme that precisely \
characterizes what the theme covers.
"""

CLUSTER_MERGE_SYSTEM = """\
You are a theme deduplicator. You receive candidate themes from independent \
clustering runs over different subsets of the same data.

Some themes from different chunks may describe the same underlying pattern. \
Your job: identify which themes should be merged because they are redundant.

ONLY output groups of **2 or more themes** that should be merged. Do NOT output \
themes that should remain as-is — those are handled automatically. Our end goal \
is to have a small number of themes that are not redundant.

Rules:
- *Two or more themes* should merge ONLY if they describe the same core idea such that \
keeping both would be redundant.
- Do NOT collapse unrelated or very weakly related themes.
- For each merge group, provide a unified theme name and description derived \
ONLY from the input descriptions. Do NOT add new information, interpretation, \
or recommendations beyond what the original descriptions state.
- If NO themes need merging, output an empty list.
"""


class MergeGroup(BaseModel):
    unified_theme: str = Field(description="The unified theme name for this merged group.")
    unified_description: str = Field(description="Unified description derived only from the merged themes' descriptions. Must not add information beyond what the original descriptions contain.")
    source_theme_ids: list[str] = Field(description="List of source theme IDs (chunk_index:theme_id format) to merge. Must contain 2 or more IDs.")


class MergeResult(BaseModel):
    groups: list[MergeGroup] = Field(description="List of merge groups. Each group contains 2+ themes that should be merged. Empty list if no merges needed.")


async def cluster_map_reduce(
    flat_items: list[dict],
    item_type: str,
    *,
    chunk_size: int = 8,
    model: str = "gpt-5.4-mini",
    reasoning: str = "high",
    num_workers: int = 16,
    cache_dir: Path | None = None,
) -> list[dict]:
    """Parallel map + merge: each chunk clusters independently, then a
    merge step deduplicates themes across chunks.

    Phase A (map) results are cached per-chunk keyed by sorted task_ids.
    Phase B (merge) always re-runs since chunk compositions may change.
    """

    task_order: list[str] = []
    by_task: dict[str, list[dict]] = {}
    for s in flat_items:
        tid = s["task_id"]
        if tid not in by_task:
            task_order.append(tid)
            by_task[tid] = []
        by_task[tid].append(s)

    flat_by_id = {s["id"]: s for s in flat_items}
    system_prompt = CLUSTER_MAP_SYSTEM.format(item_type=item_type)

    # ── Phase A: Independent map (parallel, with per-chunk caching) ────

    MAX_RETRIES = 2
    sem = asyncio.Semaphore(num_workers)

    # Load cached map results (keyed by chunk's sorted task_ids)
    map_cache_name = f"chunk_maps_{item_type}.json"
    cached_maps: dict = {}
    if cache_dir:
        raw = _load_checkpoint(cache_dir, map_cache_name)
        if raw and isinstance(raw, dict):
            cached_maps = raw

    # Stable chunking: reuse existing chunk compositions from the cache
    # so that adding new tasks doesn't reshuffle all chunk boundaries.
    all_task_set = set(task_order)
    previously_chunked: set[str] = set()
    chunk_task_lists: list[list[str]] = []

    for key in cached_maps:
        chunk_tids = key.split("|")
        if all(tid in all_task_set for tid in chunk_tids):
            chunk_task_lists.append(chunk_tids)
            previously_chunked.update(chunk_tids)

    new_task_ids = [tid for tid in task_order if tid not in previously_chunked]
    n_stable = len(chunk_task_lists)
    for i in range(0, len(new_task_ids), chunk_size):
        chunk_task_lists.append(new_task_ids[i : i + chunk_size])
    n_new = len(chunk_task_lists) - n_stable

    if n_stable:
        print(f"  Stable chunking: {len(previously_chunked)} tasks in "
              f"{n_stable} cached chunks, {len(new_task_ids)} new tasks → "
              f"{n_new} new chunks")

    chunks: list[list[dict]] = []
    for chunk_tids in chunk_task_lists:
        chunk_items = []
        for tid in chunk_tids:
            chunk_items.extend(by_task[tid])
        chunks.append(chunk_items)

    print(f"  {len(flat_items)} {item_type} across {len(task_order)} tasks → {len(chunks)} chunks")

    def _chunk_key(chunk: list[dict]) -> str:
        return "|".join(sorted(set(s["task_id"] for s in chunk)))

    async def _cluster_chunk(ci: int, chunk: list[dict]) -> ClusteringResult:
        item_lines = "\n\n---\n\n".join(
            f"ID: {s['id']}\nDescription: {s['description']}"
            for s in chunk
        )
        prompt = (
            f"Group these {len(chunk)} {item_type} into themes:\n\n{item_lines}"
        )
        async with sem:
            response = await _client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                text_format=ClusteringResult,
                reasoning={"effort": reasoning},
            )
        return response.output_parsed

    def _count_assigned(result: ClusteringResult) -> int:
        return sum(
            1 for t in result.themes for sid in t.item_ids if sid in flat_by_id
        )

    def _result_to_dict(result: ClusteringResult) -> list[dict]:
        return [{"theme_id": t.theme_id, "theme": t.theme,
                 "description": t.description, "item_ids": t.item_ids}
                for t in result.themes]

    def _dict_to_result(data: list[dict]) -> ClusteringResult:
        return ClusteringResult(themes=[
            ThemeAssignment(**t) for t in data
        ])

    # Determine which chunks need LLM calls
    chunks_to_run: list[tuple[int, list[dict]]] = []
    chunk_results: dict[int, ClusteringResult] = {}

    for ci, chunk in enumerate(chunks):
        key = _chunk_key(chunk)
        if key in cached_maps:
            chunk_results[ci] = _dict_to_result(cached_maps[key])
        else:
            chunks_to_run.append((ci, chunk))

    n_cached = len(chunks) - len(chunks_to_run)
    if chunks_to_run:
        if n_cached > 0:
            print(f"  Map: {n_cached} chunks cached, running {len(chunks_to_run)} new...")
        new_results = list(await asyncio.gather(
            *[_cluster_chunk(ci, chunk) for ci, chunk in chunks_to_run]
        ))
        for (ci, chunk), result in zip(chunks_to_run, new_results):
            chunk_results[ci] = result
    else:
        print(f"  Map: all {len(chunks)} chunks cached")

    # Retry chunks that got 0 assignments (LLM returned bad item IDs)
    for ci in range(len(chunks)):
        result = chunk_results[ci]
        assigned = _count_assigned(result)
        if assigned == 0 and len(chunks[ci]) > 0:
            for attempt in range(1, MAX_RETRIES + 1):
                print(f"  [RETRY] Chunk {ci + 1}/{len(chunks)}: "
                      f"0/{len(chunks[ci])} assigned, retrying ({attempt}/{MAX_RETRIES})...")
                result = await _cluster_chunk(ci, chunks[ci])
                assigned = _count_assigned(result)
                if assigned > 0:
                    chunk_results[ci] = result
                    break
            else:
                print(f"  [WARN] Chunk {ci + 1}/{len(chunks)}: "
                      f"still 0 assigned after {MAX_RETRIES} retries")

    # Save all chunk map results to cache
    if cache_dir:
        for ci, chunk in enumerate(chunks):
            key = _chunk_key(chunk)
            cached_maps[key] = _result_to_dict(chunk_results[ci])
        _save_checkpoint(cache_dir, map_cache_name, cached_maps)

    # Collect per-chunk themes with globally-unique IDs
    chunk_themes: list[list[dict]] = []
    for ci in range(len(chunks)):
        result = chunk_results[ci]
        themes_in_chunk = []
        assigned = 0
        for t in result.themes:
            member_ids = [sid for sid in t.item_ids if sid in flat_by_id]
            assigned += len(member_ids)
            themes_in_chunk.append({
                "global_id": f"{ci}:{t.theme_id}",
                "theme": t.theme,
                "description": t.description,
                "member_ids": member_ids,
            })
        chunk_themes.append(themes_in_chunk)
        print(
            f"  Chunk {ci + 1}/{len(chunks)}: "
            f"{len(chunks[ci])} items → {assigned} assigned, "
            f"{len(themes_in_chunk)} themes"
        )

    all_candidate_themes = [t for ct in chunk_themes for t in ct]

    # ── Short-circuit: single chunk → no merge needed ─────────────────

    if len(chunks) == 1:
        themes = []
        for t in all_candidate_themes:
            members = [flat_by_id[sid] for sid in t["member_ids"]]
            if members:
                themes.append({
                    "theme": t["theme"],
                    "description": t["description"],
                    "members": members,
                })
        total_assigned = sum(len(t["members"]) for t in themes)
        print(f"  → {len(themes)} themes from {total_assigned} {item_type}")
        return themes

    # ── Phase B: Merge (single LLM call) ──────────────────────────────

    theme_lines = "\n\n".join(
        f"ID: {t['global_id']}\n"
        f"Theme: {t['theme']}\n"
        f"Description: {t['description']}"
        for t in all_candidate_themes
    )

    merge_prompt = (
        f"These {len(all_candidate_themes)} candidate themes were discovered "
        f"independently from {len(chunks)} chunks of {item_type}.\n"
        f"Identify any that are redundant and should be merged.\n\n{theme_lines}"
    )

    merge_response = await _client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": CLUSTER_MERGE_SYSTEM},
            {"role": "user", "content": merge_prompt},
        ],
        text_format=MergeResult,
        reasoning={"effort": reasoning},
    )
    merge_result = merge_response.output_parsed

    # Collect IDs that were consumed by a merge group
    merged_ids: set[str] = set()
    themes = []

    for group in merge_result.groups:
        if len(group.source_theme_ids) < 2:
            continue
        members = []
        for source_id in group.source_theme_ids:
            merged_ids.add(source_id)
            for t in all_candidate_themes:
                if t["global_id"] == source_id:
                    members.extend(flat_by_id[sid] for sid in t["member_ids"])
                    break
        if members:
            themes.append({
                "theme": group.unified_theme,
                "description": group.unified_description,
                "members": members,
            })

    # Keep unmerged themes as-is
    for t in all_candidate_themes:
        if t["global_id"] not in merged_ids:
            members = [flat_by_id[sid] for sid in t["member_ids"]]
            if members:
                themes.append({
                    "theme": t["theme"],
                    "description": t["description"],
                    "members": members,
                })

    total_assigned = sum(len(t["members"]) for t in themes)
    merged_count = len(merge_result.groups)
    print(
        f"  Merge: {len(all_candidate_themes)} candidate themes → "
        f"{len(themes)} final ({merged_count} merges)"
    )
    print(f"  → {len(themes)} themes from {total_assigned} {item_type}")
    return themes


# =====================================================================
#  Step 3: Aggregate, Rank, Select
# =====================================================================

def aggregate_strengths(
    themes: list[dict],
    total_tasks: int,
    total_solved: int,
    total_failed: int,
) -> list[dict]:
    ranked = []
    for theme in themes:
        members = theme["members"]
        unique_tasks = set(m["task_id"] for m in members)
        solved_tasks = set(m["task_id"] for m in members if m.get("solved"))
        failed_tasks = set(m["task_id"] for m in members if not m.get("solved"))

        support_count = len(unique_tasks)
        support_ratio = support_count / total_tasks if total_tasks else 0
        success_ratio = len(solved_tasks) / total_solved if total_solved else 0
        failure_ratio = len(failed_tasks) / total_failed if total_failed else 0
        success_weight = success_ratio - failure_ratio
        composite = 0.4 * support_ratio + 0.6 * success_weight

        ranked.append({
            **theme,
            "support_count": support_count,
            "support_ratio": support_ratio,
            "solved_count": len(solved_tasks),
            "failed_count": len(failed_tasks),
            "success_weight": success_weight,
            "composite": composite,
        })

    ranked.sort(key=lambda x: x["composite"], reverse=True)
    return ranked


def aggregate_improvements(
    themes: list[dict],
    total_tasks: int,
    total_solved: int,
    total_failed: int,
) -> list[dict]:
    ranked = []
    for theme in themes:
        members = theme["members"]
        unique_tasks = set(m["task_id"] for m in members)
        failed_tasks = set(m["task_id"] for m in members if not m.get("solved"))
        solved_tasks = set(m["task_id"] for m in members if m.get("solved"))

        support = len(unique_tasks)
        support_ratio = support / total_tasks if total_tasks else 0
        failure_ratio = len(failed_tasks) / total_failed if total_failed else 0
        success_ratio = len(solved_tasks) / total_solved if total_solved else 0
        failure_weight = failure_ratio - success_ratio
        composite = 0.4 * support_ratio + 0.6 * failure_weight

        ranked.append({
            **theme,
            "support_count": support,
            "support_ratio": support_ratio,
            "failed_task_count": len(failed_tasks),
            "solved_task_count": len(solved_tasks),
            "failure_weight": failure_weight,
            "composite": composite,
        })

    ranked.sort(key=lambda x: x["composite"], reverse=True)
    return ranked


def select_strength_themes(
    ranked_themes: list[dict],
    *,
    min_support: int = 2,
    min_ratio: float = 0.30,
    min_composite: float = 0.00,
    base_batch_size: int | None = None,
    total_tasks: int | None = None,
) -> list[dict]:
    effective_ratio = min_ratio
    if base_batch_size is not None and total_tasks is not None and total_tasks > base_batch_size:
        effective_ratio = min_ratio * (base_batch_size / total_tasks) ** 0.5

    selected = [
        t for t in ranked_themes
        if t["support_count"] >= min_support
        and t["support_ratio"] >= effective_ratio
        and t["composite"] >= min_composite
    ]
    ratio_note = f"effective_ratio={effective_ratio:.3f}" if effective_ratio != min_ratio else f"min_ratio={min_ratio}"
    print(f"  Selected {len(selected)}/{len(ranked_themes)} strength themes "
          f"(min_support={min_support}, {ratio_note}, "
          f"min_composite={min_composite})")
    return selected


def select_improvement_themes(
    ranked_themes: list[dict],
    *,
    min_support: int = 2,
    min_ratio: float = 0.20,
    min_composite: float = 0.00,
    base_batch_size: int | None = None,
    total_tasks: int | None = None,
) -> list[dict]:
    effective_ratio = min_ratio
    if base_batch_size is not None and total_tasks is not None and total_tasks > base_batch_size:
        effective_ratio = min_ratio * (base_batch_size / total_tasks) ** 0.5

    selected = [
        t for t in ranked_themes
        if t["support_count"] >= min_support
        and t["support_ratio"] >= effective_ratio
        and t["composite"] >= min_composite
    ]
    ratio_note = f"effective_ratio={effective_ratio:.3f}" if effective_ratio != min_ratio else f"min_ratio={min_ratio}"
    print(f"  Selected {len(selected)}/{len(ranked_themes)} improvement themes "
          f"(min_support={min_support}, {ratio_note}, "
          f"min_composite={min_composite})")
    return selected


# =====================================================================
#  Step 4: Summarize per Cluster
# =====================================================================

SUMMARIZE_SYSTEM = """\
You are a concise summarizer. Below are N observations from M tasks, \
all grouped under a single theme. Many observations repeat similar \
points across tasks. Condense them into a single non-redundant summary \
paragraph. For each distinct point, note which tasks support it (e.g. \
'seen in <task_id_1>, <task_id_2>, ...'). Do NOT add any information, \
interpretation, or recommendations not explicitly present in the \
observations.
"""


async def summarize_cluster(
    theme: dict,
    *,
    model: str = "gpt-5.4-mini",
    reasoning: str = "high",
) -> dict:
    unique_tasks = set(m["task_id"] for m in theme["members"])
    member_lines = "\n".join(
        f"- {m['task_id']} ({'solved' if m['solved'] else 'FAILED'}): {m['description']}"
        for m in theme["members"]
    )
    prompt = (
        f'Theme: "{theme["theme"]}"\n'
        f'Description: {theme["description"]}\n\n'
        f"Observations ({len(theme['members'])} items from "
        f"{len(unique_tasks)} tasks):\n\n{member_lines}"
    )
    response = await _client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": SUMMARIZE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        text_format=ClusterSummary,
        reasoning={"effort": reasoning},
    )
    return response.output_parsed.model_dump()


async def run_summarization(
    selected_strengths: list[dict],
    selected_improvements: list[dict],
    *,
    num_workers: int = 16,
    model: str = "gpt-5.4-mini",
    reasoning: str = "high",
) -> tuple[list[dict], list[dict]]:
    """Summarize all selected clusters."""

    sem = asyncio.Semaphore(num_workers)

    async def _summarize(theme: dict) -> dict:
        async with sem:
            try:
                summary = await summarize_cluster(
                    theme, model=model, reasoning=reasoning,
                )
            except Exception as e:
                print(f"  [WARN] summary failed for {theme['theme']}: {e}")
                summary = {"summary": "(summarization failed)"}
            return {**theme, "summary": summary}

    strength_results = await asyncio.gather(
        *[_summarize(t) for t in selected_strengths]
    )
    print(f"  Summarized {len(strength_results)} strength themes")

    improvement_results = await asyncio.gather(
        *[_summarize(t) for t in selected_improvements]
    )
    print(f"  Summarized {len(improvement_results)} improvement themes")

    return strength_results, improvement_results


# =====================================================================
#  Step 4.5: Conflict Resolution
# =====================================================================

CONFLICT_SYSTEM = """\
You are a conflict detector for agent orchestration feedback. You \
receive two lists: strength themes (things the orchestration does well) \
and improvement themes (things the orchestration should change).

DECISION CRITERION:

A conflict exists ONLY when the strength and improvement make \
incompatible claims about the same concrete behavior — accepting both \
would be logically incoherent. Ask: "Can this strength be true AT THE \
SAME TIME as this improvement?" If yes, they are not in conflict.

EXAMPLES:

1. If one talks about 'validation' as a strength, and the other talks about \
'improving validation': 
- it *is a conflict* if the improvement is in terms of the *same causal chain*, \
addressed by the strength.
- it is *not a conflict*, if the improvement is in terms of a *different causal chain*, \
not addressed by the strength.

2. If one talks about 'validation' as a strength, and the other talks about \
'removing validation' as an improvement, they are in conflict. (Same category, \
opposite action.)

3. If one talks about 'validation' as a strength, and the other talks about \
'designing workflow' as an improvement, they are not in conflict. (Different categories.)

RULES:
- Only flag pairs where accepting both would be incoherent.
- Keep in mind the causal chains that are provided in the descriptions.
- Return an empty list if no genuine conflicts exist.
"""


async def resolve_conflicts(
    selected_strengths: list[dict],
    selected_improvements: list[dict],
    *,
    model: str = "gpt-5.4-mini",
    reasoning: str = "high",
) -> tuple[list[dict], list[dict]]:
    """Detect and resolve contradictions between strength and improvement themes."""

    if not selected_strengths or not selected_improvements:
        print("  No conflicts to resolve (one list empty)")
        return selected_strengths, selected_improvements

    strength_lines = "\n".join(
        f"- S[{t['theme']}]: {t['description']}"
        for t in selected_strengths
    )
    improvement_lines = "\n".join(
        f"- I[{t['theme']}]: {t['description']}"
        for t in selected_improvements
    )

    prompt = (
        f"STRENGTH THEMES:\n\n{strength_lines}\n\n"
        f"IMPROVEMENT THEMES:\n\n{improvement_lines}"
    )

    try:
        response = await _client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": CONFLICT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            text_format=ConflictDetectionResult,
            reasoning={"effort": reasoning},
        )
        conflicts = response.output_parsed.conflicts
    except Exception as e:
        print(f"  [WARN] conflict detection failed: {e}")
        return selected_strengths, selected_improvements

    if not conflicts:
        print("  No conflicts detected")
        return selected_strengths, selected_improvements

    print(conflicts)

    strength_by_name = {t["theme"]: t for t in selected_strengths}
    improvement_by_name = {t["theme"]: t for t in selected_improvements}

    strengths_to_remove: set[str] = set()
    improvements_to_remove: set[str] = set()

    for conflict in conflicts:
        s_name = re.sub(r'^S\[(.+)\]$', r'\1', conflict.strength_theme)
        i_name = re.sub(r'^I\[(.+)\]$', r'\1', conflict.improvement_theme)

        s = strength_by_name.get(s_name)
        imp = improvement_by_name.get(i_name)
        if s is None or imp is None:
            continue

        if imp["composite"] > s["composite"]:
            strengths_to_remove.add(s_name)
            imp["resolution_note"] = (
                f"Conflicts with strength '{s_name}': {conflict.rationale}. "
                f"Improvement wins (composite {imp['composite']:.2f} > "
                f"{s['composite']:.2f}). "
                f"Preserve the positive pattern where possible."
            )
            print(f"  Resolved: I[{i_name}] wins over S[{s_name}] "
                  f"(composite {imp['composite']:.2f} > {s['composite']:.2f})")
        else:
            improvements_to_remove.add(i_name)
            s["resolution_note"] = (
                f"Conflicts with improvement '{i_name}': {conflict.rationale}. "
                f"Strength wins (composite {s['composite']:.2f} > "
                f"{imp['composite']:.2f}). "
                f"Note: some tasks still struggle with this pattern."
            )
            print(f"  Resolved: S[{s_name}] wins over I[{i_name}] "
                  f"(composite {s['composite']:.2f} > {imp['composite']:.2f})")

    filtered_strengths = [
        t for t in selected_strengths if t["theme"] not in strengths_to_remove
    ]
    filtered_improvements = [
        t for t in selected_improvements if t["theme"] not in improvements_to_remove
    ]

    s_removed = len(selected_strengths) - len(filtered_strengths)
    i_removed = len(selected_improvements) - len(filtered_improvements)
    print(f"  → {len(conflicts)} conflicts found, "
          f"{s_removed} strengths removed, {i_removed} improvements removed")

    return filtered_strengths, filtered_improvements


# =====================================================================
#  Step 4.75: Usage Summary
# =====================================================================

_USAGE_SECTION_RE = re.compile(
    r"### Agent's Usage of agent_home\n(.*?)(?=\n###|\Z)",
    re.DOTALL,
)

USAGE_SUMMARY_SYSTEM = """\
You are a compliance summarizer. You receive per-task observations \
about how an agent used its orchestration artifacts. Your job is to \
summarize ONLY what agents did with the artifacts — pure compliance facts.

Produce a few bullet points covering:
- Which artifacts were loaded and how consistently
- Which instructions were followed and how consistently
- Which instructions were ignored or misinterpreted
- Which artifacts were unavailable or empty or not loaded

STRICT RULES:
- Report ONLY what is explicitly stated in the observations.
- Do NOT assess the quality or sufficiency of the artifacts.
- Do NOT infer, assume, or add anything beyond what the \
observations say.
"""


def _extract_usage_sections(gradients: list[dict]) -> list[dict]:
    """Pull the 'Agent's Usage of agent_home' section from each analysis."""
    sections = []
    for g in gradients:
        m = _USAGE_SECTION_RE.search(g["analysis_text"])
        if m:
            sections.append({
                "task_id": g["task_id"],
                "solved": g["solved"],
                "usage_text": m.group(1).strip(),
            })
    return sections


async def generate_usage_summary(
    gradients: list[dict],
    total_tasks: int,
    total_solved: int,
    total_failed: int,
    *,
    model: str = "gpt-5.4-mini",
    reasoning: str = "high",
) -> str:
    """Summarize agent_home compliance across the batch."""

    sections = _extract_usage_sections(gradients)
    if not sections:
        return "(No agent usage sections found in analyses.)"

    section_lines = "\n\n---\n\n".join(
        f"Task: {s['task_id']} ({'solved' if s['solved'] else 'FAILED'})\n"
        f"{s['usage_text']}"
        for s in sections
    )

    prompt = (
        f"BATCH: {total_tasks} tasks ({total_solved} solved, "
        f"{total_failed} failed)\n\n"
        f"PER-TASK COMPLIANCE OBSERVATIONS:\n\n{section_lines}"
    )

    try:
        response = await _client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": USAGE_SUMMARY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            text_format=UsageSummaryResult,
            reasoning={"effort": reasoning},
        )
        return response.output_parsed.summary
    except Exception as e:
        print(f"  [WARN] usage summary failed: {e}")
        return "(Usage summary generation failed.)"


# =====================================================================
#  Step 5: Report Rendering
# =====================================================================

def _render_member_bullets(members: list[dict]) -> list[str]:
    lines = []
    for m in members:
        status = "succeeded" if m.get("solved") else "failed"
        lines.append(f"- {m['task_id']} ({status}): {m['description']}")
    return lines


def render_report(
    strength_themes: list[dict],
    improvement_themes: list[dict],
    total_tasks: int,
    total_solved: int,
    total_failed: int,
    step: int,
    *,
    summarized: bool = False,
    usage_summary: str = "",
    coverage_annotations: list[dict] | None = None,
) -> str:
    lines: list[str] = []

    lines.append(f"# Accumulated Gradient Report")
    lines.append(f"## Step {step} | {total_tasks} tasks ({total_solved} succeeded, {total_failed} failed)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Agent home compliance
    if usage_summary:
        lines.append("## Agent Home Compliance")
        lines.append("")
        lines.append(usage_summary)
        lines.append("")
        lines.append("---")
        lines.append("")

    # Strengths — bullet list with description, ranked by success_weight
    lines.append(f"## Strengths (ranked by prevalence and association with success)")
    lines.append("")
    for t in strength_themes:
        lines.append(
            f"- **{t['theme']}** "
            f"(supported by {t['support_count']}/{total_tasks} tasks, "
            f"{t['solved_count']} succeeded, {t['failed_count']} failed) — "
            f"{t['description']}"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Improvements — full detail, ranked by failure_weight
    lines.append(f"## Improvements (ranked by prevalence and association with failure)")
    lines.append("")
    for i, t in enumerate(improvement_themes, 1):
        tasks = sorted(set(m["task_id"] for m in t["members"]))

        lines.append(f"### I{i}. {t['theme']}")
        lines.append(
            f"**Supported by:** {t['support_count']}/{total_tasks} tasks | "
            f"Failed: {t['failed_task_count']} | "
            f"Succeeded: {t['solved_task_count']}"
        )

        if t.get("resolution_note"):
            lines.append(f"**Resolution:** {t['resolution_note']}")

        if coverage_annotations and (i - 1) < len(coverage_annotations):
            ann = coverage_annotations[i - 1]
            category = ann.get("category", "gap")
            rationale = ann.get("rationale", "")
            cited = ann.get("cited_instruction")
            if category == "gap":
                lines.append(f"**Gradient:** HARD — {rationale}")
            else:
                label = f"**Gradient:** SOFT — {rationale}"
                if cited:
                    label += f" (cited: {cited})"
                lines.append(label)

        if summarized and "summary" in t:
            lines.append(f"**Summary:** {t['summary']['summary']}")
        else:
            lines.append(f"**Pattern:** {t['description']}")
            lines.append("**Observations:**")
            lines.extend(_render_member_bullets(t["members"]))

        lines.append(f"**Observed in:** {', '.join(tasks)}")
        lines.append("")

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


# =====================================================================
#  Full Pipeline
# =====================================================================

async def accumulate(
    gradients: list[dict],
    step: int,
    *,
    model: str = "gpt-5.4-mini",
    reasoning: str = "high",
    num_workers: int = 16,
    chunk_size: int = 8,
    min_support: int = 2,
    min_support_ratio_strength: float = 0.30,
    min_support_ratio_improvement: float = 0.20,
    min_composite_strength: float = 0.00,
    min_composite_improvement: float = 0.00,
    summarize_clusters: bool = False,
    cache_dir: Path | None = None,
    base_batch_size: int | None = None,
) -> dict:
    """Run the full gradient accumulation pipeline.

    Args:
        summarize_clusters: If True, run an LLM summarization step per
            selected cluster (Option B). If False, skip summarization and
            include raw member descriptions in the report (Option A).
        cache_dir: If provided, intermediate results are checkpointed to
            this directory so that a crashed run can resume from the last
            completed step instead of re-running all LLM calls.

    Returns dict with all intermediate outputs and the final report string.
    """
    total_tasks = len(gradients)
    total_solved = sum(1 for g in gradients if g["solved"])
    total_failed = total_tasks - total_solved

    print(f"{'=' * 70}")
    print(f"  Gradient Accumulation | Step {step} | "
          f"{total_tasks} tasks ({total_solved} solved, {total_failed} failed)")
    print(f"  Mode: {'summarized' if summarize_clusters else 'raw'}"
          f"{'  |  cache: ' + str(cache_dir) if cache_dir else ''}")
    print(f"{'=' * 70}\n")

    # Step 1: Extract (incremental — keyed by task_id)
    cached_extractions_dict: dict | None = _load_checkpoint(cache_dir, "extractions.json")
    if cached_extractions_dict is None:
        cached_extractions_dict = {}

    # Detect new gradients not yet extracted
    new_gradients = [g for g in gradients if g["task_id"] not in cached_extractions_dict]

    if new_gradients:
        print(f"Step 1: Extracting {len(new_gradients)} new tasks "
              f"({len(cached_extractions_dict)} cached)...")
        new_results = await run_extraction(
            new_gradients, num_workers=num_workers,
            model=model, reasoning=reasoning,
        )
        for r in new_results:
            cached_extractions_dict[r["task_id"]] = r
        if cache_dir:
            _save_checkpoint(cache_dir, "extractions.json", cached_extractions_dict)
            # Invalidate downstream caches since input changed
            for stale in ("clusters.json", "selected.json", "summarized.json", "usage_summary.txt"):
                stale_path = cache_dir / stale
                if stale_path.exists():
                    stale_path.unlink()
    else:
        total_s = sum(len(r["strengths"]) for r in cached_extractions_dict.values())
        total_i = sum(len(r["improvements"]) for r in cached_extractions_dict.values())
        print(f"Step 1: All {len(cached_extractions_dict)} extractions cached "
              f"({total_s} strengths + {total_i} improvements)")

    # Rebuild positional list aligned with input gradients
    extractions = [cached_extractions_dict[g["task_id"]] for g in gradients]

    flat_strengths = _build_flat_strengths(extractions)
    flat_improvements = _build_flat_improvements(extractions)
    print(f"  → {len(flat_strengths)} flat strengths, {len(flat_improvements)} flat improvements\n")

    # Step 2: Cluster
    clusters = _load_checkpoint(cache_dir, "clusters.json")
    if clusters is None:
        print("Step 2a: Clustering strengths...")
        strength_themes = await cluster_map_reduce(
            flat_strengths, "strengths",
            chunk_size=chunk_size, model=model, reasoning=reasoning,
            cache_dir=cache_dir,
        )
        print()

        print("Step 2b: Clustering improvements...")
        improvement_themes = await cluster_map_reduce(
            flat_improvements, "improvements",
            chunk_size=chunk_size, model=model, reasoning=reasoning,
            cache_dir=cache_dir,
        )
        print()

        if cache_dir:
            _save_checkpoint(cache_dir, "clusters.json", {
                "strength_themes": strength_themes,
                "improvement_themes": improvement_themes,
            })
    else:
        strength_themes = clusters["strength_themes"]
        improvement_themes = clusters["improvement_themes"]
        print(f"Step 2: Loaded cached clusters "
              f"({len(strength_themes)} strength themes, "
              f"{len(improvement_themes)} improvement themes)\n")

    # Step 3 + 3.5: Aggregate, Rank, Select, Resolve conflicts
    selected = _load_checkpoint(cache_dir, "selected.json")
    if selected is None:
        print("Step 3: Aggregating and selecting...")
        ranked_strengths = aggregate_strengths(
            strength_themes, total_tasks, total_solved, total_failed,
        )
        ranked_improvements = aggregate_improvements(
            improvement_themes, total_tasks, total_solved, total_failed,
        )

        selected_strengths = select_strength_themes(
            ranked_strengths, min_support=min_support, min_ratio=min_support_ratio_strength,
            min_composite=min_composite_strength,
            base_batch_size=base_batch_size, total_tasks=total_tasks,
        )
        selected_improvements = select_improvement_themes(
            ranked_improvements, min_support=min_support, min_ratio=min_support_ratio_improvement,
            min_composite=min_composite_improvement,
            base_batch_size=base_batch_size, total_tasks=total_tasks,
        )
        print()

        print("Step 3.5: Resolving conflicts...")
        selected_strengths, selected_improvements = await resolve_conflicts(
            selected_strengths, selected_improvements,
            model=model, reasoning=reasoning,
        )
        print()

        if cache_dir:
            _save_checkpoint(cache_dir, "selected.json", {
                "selected_strengths": selected_strengths,
                "selected_improvements": selected_improvements,
            })
    else:
        selected_strengths = selected["selected_strengths"]
        selected_improvements = selected["selected_improvements"]
        print(f"Step 3+3.5: Loaded cached selection "
              f"({len(selected_strengths)} strengths, "
              f"{len(selected_improvements)} improvements)\n")

    # Step 4: Summarize (optional)
    if summarize_clusters:
        summarized_data = _load_checkpoint(cache_dir, "summarized.json")
        if summarized_data is None:
            print("Step 4: Summarizing clusters...")
            final_strengths, final_improvements = await run_summarization(
                selected_strengths, selected_improvements,
                num_workers=num_workers, model=model, reasoning=reasoning,
            )
            print()
            if cache_dir:
                _save_checkpoint(cache_dir, "summarized.json", {
                    "final_strengths": final_strengths,
                    "final_improvements": final_improvements,
                })
        else:
            final_strengths = summarized_data["final_strengths"]
            final_improvements = summarized_data["final_improvements"]
            print(f"Step 4: Loaded cached summaries "
                  f"({len(final_strengths)} strengths, "
                  f"{len(final_improvements)} improvements)\n")
    else:
        print("Step 4: Skipped (raw mode)\n")
        final_strengths = selected_strengths
        final_improvements = selected_improvements

    # Step 4.75: Usage summary
    usage_summary = _load_checkpoint(cache_dir, "usage_summary.txt")
    if usage_summary is None:
        print("Step 4.75: Generating usage summary...")
        usage_summary = await generate_usage_summary(
            gradients, total_tasks, total_solved, total_failed,
            model=model, reasoning=reasoning,
        )
        print(f"  → {len(usage_summary)} chars\n")
        if cache_dir:
            _save_checkpoint(cache_dir, "usage_summary.txt", usage_summary)
    else:
        print(f"Step 4.75: Loaded cached usage summary ({len(usage_summary)} chars)\n")

    # Step 5: Render report (pure string, always re-runs)
    print("Step 5: Rendering report...")
    report = render_report(
        final_strengths,
        final_improvements,
        total_tasks=total_tasks,
        total_solved=total_solved,
        total_failed=total_failed,
        step=step,
        summarized=summarize_clusters,
        usage_summary=usage_summary,
    )
    print(f"  → Report: {len(report)} chars, "
          f"{len(final_strengths)} strength themes, "
          f"{len(final_improvements)} improvement themes\n")

    return {
        "step": step,
        "total_tasks": total_tasks,
        "total_solved": total_solved,
        "total_failed": total_failed,
        "extractions": extractions,
        "flat_strengths": flat_strengths,
        "flat_improvements": flat_improvements,
        "all_strength_themes": strength_themes,
        "all_improvement_themes": improvement_themes,
        "selected_strengths": final_strengths,
        "selected_improvements": final_improvements,
        "usage_summary": usage_summary,
        "report": report,
    }
