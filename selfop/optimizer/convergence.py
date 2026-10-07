from __future__ import annotations

"""Convergence detection (paper §3.4) — AccumulationOptimizer + SNR-based convergence detection.

Extends AccumulationOptimizer with:
  Phase 2.75: Three-way theme classification of selected improvements
                    against a persisted theme history, computing a textual SNR.

  SNR gating: When SNR >= z_crit, proceeds to Phase 3 (main optimizer) normally.
              When SNR < z_crit, skips Phase 3 — the training loop will expand the
              step in-place with the next batch (expand-in-place accumulation).

  Expand-in-place: The training loop keeps the same step_dir open and adds more
                   tasks on each skip. Phase 1/2 are idempotent (cached per task),
                   and the accumulation extraction cache is incremental (keyed by
                   task_id). Only clustering/ranking/selection re-run on each call.

  Coverage classifier (classifier_type="coverage"): Alternative to the theme-history
      classifier. Uses CodexRunner to read the latest agent_home snapshot and
      classify each improvement theme as gap/covered. Outputs the same
      ClassificationResult shape so all convergence_mode/convergence_gate logic
      works unchanged.
"""

import shutil
from pathlib import Path

from selfop.optimizer.accumulation import AccumulationOptimizer
from selfop.runner.codex import CodexRunner
from selfop.accumulation.accumulator import load_gradients, accumulate
from selfop.accumulation.theme_classifier import (
    classify_and_update,
    compute_snr,
    load_theme_history,
    save_theme_history,
)
from selfop.accumulation.coverage_classifier import (
    COVERAGE_SYSTEM_PROMPT,
    build_coverage_prompt,
    parse_coverage_result,
    to_classification_result,
)


def _safe_symlink(target: Path, link: Path) -> None:
    """Create a symlink, removing any existing file/link/dir first."""
    if link.exists() or link.is_symlink():
        if link.is_dir() and not link.is_symlink():
            shutil.rmtree(link)
        else:
            link.unlink()
    link.symlink_to(target.resolve())


class ConvergenceOptimizer(AccumulationOptimizer):
    """AccumulationOptimizer + SNR-based convergence detection.

    Phases 1 & 2 are inherited from GradientOptimizer unchanged (idempotent per task).
    Phase 2.5 uses the accumulator with incremental extraction cache.
    Phase 2.75 classifies selected improvements for novelty.
    Phase 3 is gated by SNR — skipped when signal is below threshold.
    """

    name = "convergence"

    # ── Phase 2.5: gradient accumulation ──────────────────────────────

    async def _run_accumulation(
        self,
        step_dir: Path,
        step_ids: list[str],
    ) -> dict:
        """Override: returns full accumulation result dict (not just report text).

        Loads all gradients from analysis_runs/step_N/ (which grows in-place
        as the training loop expands the step with additional batches).
        The extraction cache is incremental — only new tasks get extracted.
        """
        step_num = int(step_dir.name.replace("step_", ""))
        analysis_step_dir = self.workspace_dir / "analysis_runs" / f"step_{step_num}"
        report_path = analysis_step_dir / "accumulated_report.txt"
        cache_dir = self.workspace_dir / "accumulation_cache" / f"step_{step_num}"

        gradients = load_gradients(self.workspace_dir / "analysis_runs", step_num)

        result = await accumulate(
            gradients, step_num,
            base_batch_size=self.config.batch_size,
            model=self.config.accum_model,
            reasoning=self.config.accum_reasoning,
            num_workers=self.config.num_workers,
            chunk_size=self.config.accum_chunk_size,
            min_support=self.config.accum_min_support,
            min_support_ratio_strength=self.config.accum_min_support_ratio_strength,
            min_support_ratio_improvement=self.config.accum_min_support_ratio_improvement,
            min_composite_strength=self.config.accum_min_composite_strength,
            min_composite_improvement=self.config.accum_min_composite_improvement,
            cache_dir=cache_dir,
            summarize_clusters=True,
        )

        report = result["report"]
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report)

        return result

    # ── Phase 2.75: theme classification ──────────────────────────────

    async def _run_classification(
        self,
        selected_improvements: list[dict],
        step_dir: Path,
    ) -> dict:
        """Classify selected improvement themes against theme history.

        Returns dict with 'snr', 'classification', and updated history path.
        """
        step_num = int(step_dir.name.replace("step_", ""))
        history_path = self.workspace_dir / "theme_history.json"
        history = load_theme_history(history_path)

        classification, updated_history = await classify_and_update(
            selected_improvements,
            history,
            step_num,
            model=self.config.optimizer_model,
            reasoning=self.config.optimizer_reasoning,
        )

        snr = compute_snr(classification, p0=self.config.classifier_p0)
        save_theme_history(history_path, updated_history)

        print(f"  [selfop] Classification: novel={classification['novel_count']}, "
              f"common_same={classification['common_same_count']}, "
              f"common_diff={classification['common_diff_count']} "
              f"(K={classification['total']}) → z={snr:.2f}")

        return {
            "snr": snr,
            "classification": classification,
        }

    # ── Phase 2.75 (alt): skill coverage classification ─────────────

    async def _run_coverage_classification(
        self,
        selected_improvements: list[dict],
        step_dir: Path,
    ) -> dict:
        """Classify improvement themes against the current skill snapshot.

        Uses CodexRunner in read-only mode to read the latest agent_home
        snapshot and determine which themes are already addressed (covered)
        vs. which are gaps. Returns the same shape as _run_classification
        so all downstream gating logic works unchanged.
        """
        step_num = int(step_dir.name.replace("step_", ""))
        prev_label = f"step_{step_num - 1}"
        latest_snapshot = self.config.agent_home_snapshots_dir / prev_label

        if not latest_snapshot.exists():
            print(f"  [selfop] Coverage: snapshot {prev_label} not found, "
                  f"treating all themes as gaps")
            gap_result = {
                "classifications": [
                    {"index": i, "category": "gap",
                     "rationale": "No snapshot available", "cited_instruction": None}
                    for i in range(len(selected_improvements))
                ],
                "gap_count": len(selected_improvements),
                "covered_count": 0,
                "total": len(selected_improvements),
            }
            classification = to_classification_result(gap_result)
            snr = compute_snr(classification, p0=self.config.classifier_p0)
            return {"snr": snr, "classification": classification}

        classifier_dir = self.workspace_dir / "classifier_workspace"
        classifier_dir.mkdir(parents=True, exist_ok=True)
        _safe_symlink(latest_snapshot, classifier_dir / "agent_home")

        runner = CodexRunner()
        log_path = self.workspace_dir.parent / f"classifier_step_{step_num}.log"

        sys_prompt = COVERAGE_SYSTEM_PROMPT.format(
            skill_name=self.config.skill_name,
        )
        usr_prompt = build_coverage_prompt(
            selected_improvements, self.config.skill_name,
        )

        result = await runner.run(
            prompt=usr_prompt,
            workspace_dir=classifier_dir,
            model=self.config.optimizer_model,
            reasoning=self.config.optimizer_reasoning,
            system_prompt=sys_prompt,
            sandbox="read-only",
            log_path=log_path,
            timeout=10 * 60,
            model_provider=self.config.model_provider,
        )

        coverage_result = parse_coverage_result(
            result.final_text, len(selected_improvements),
        )
        classification = to_classification_result(coverage_result)
        snr = compute_snr(classification, p0=self.config.classifier_p0)

        gap = coverage_result["gap_count"]
        covered = coverage_result["covered_count"]
        total = coverage_result["total"]
        print(f"  [selfop] Coverage: {gap} gaps, {covered} covered "
              f"(K={total}) → z={snr:.2f}")

        return {
            "snr": snr,
            "classification": classification,
        }

    # ── Phase 3: main optimizer (inherited, unchanged) ────────────────
    # _run_main_optimizer is inherited from AccumulationOptimizer unchanged.

    # ── Public interface ──────────────────────────────────────────────

    async def run(
        self,
        *,
        step_dir: Path,
        step_ids: list[str],
        session_id: str | None = None,
        snr_threshold: float | None = None,
        convergence_mode: str = "novelty",
        convergence_gate: bool = False,
    ) -> dict:
        """Full pipeline with convergence gating.

        Args:
            step_dir: Path to the current step's data (grows in-place on skip).
            step_ids: All task IDs accumulated into this step so far.
            session_id: Persistent optimizer session ID.
            snr_threshold: Gates Phase 3 on z >= z_crit (mode="snr" only).
            convergence_mode: "snr" uses z-score threshold; "novelty" skips
                only when zero novel/diff_causal themes are found.
            convergence_gate: If True, skip Phase 3 when no novelty (original
                behavior). If False, always run Phase 3 (stop-only mode).

        Returns:
            Dict with optimizer results. Includes:
            - 'snr': float (z-score from one-proportion test)
            - 'classification': ClassificationResult dict
            - 'skipped': bool (True if Phase 3 was skipped)
            - Standard optimizer fields when not skipped.
        """
        print(f"[selfop] Phase 1: Running {len(step_ids)} trajectory analyses...")
        phase1_results = await self._run_all_phase1(step_dir, step_ids)

        print(f"[selfop] Phase 2: Running {len(step_ids)} gradient analyses...")
        phase2_results = await self._run_all_phase2(step_dir, step_ids)

        print("[selfop] Phase 2.5: Running gradient accumulation...")
        accum_result = await self._run_accumulation(step_dir, step_ids)

        selected_improvements = accum_result.get("selected_improvements", [])

        # No improvement themes survived filtering
        if not selected_improvements:
            if convergence_gate:
                print("[selfop] No improvement themes selected — skipping Phase 3.")
                return {
                    "optimizer": self.name,
                    "phase1_results": phase1_results,
                    "phase2_results": phase2_results,
                    "snr": None,
                    "classification": None,
                    "skipped": True,
                    "session_id": session_id,
                }
            else:
                print("[selfop] No improvement themes selected — running Phase 3 anyway (stop-only mode).")
                main_result = await self._run_main_optimizer(step_dir, step_ids, session_id)
                return {
                    "optimizer": self.name,
                    "phase1_results": phase1_results,
                    "phase2_results": phase2_results,
                    "snr": None,
                    "classification": None,
                    "skipped": False,
                    **main_result,
                }

        print(f"[selfop] Phase 2.75: Classifying {len(selected_improvements)} "
              f"selected improvement themes...")
        if self.config.classifier_type == "coverage":
            class_result = await self._run_coverage_classification(
                selected_improvements, step_dir,
            )
        else:
            class_result = await self._run_classification(selected_improvements, step_dir)
        snr = class_result["snr"]
        classification = class_result["classification"]

        # Convergence gating (only skip Phase 3 when convergence_gate is enabled)
        # Tiered signal: novel themes always count; diff_causal only counts
        # if z-score is above threshold (statistically significant).
        should_skip = False
        if convergence_gate:
            if convergence_mode == "novelty":
                if classification["novel_count"] > 0:
                    pass  # novel = strong signal, don't skip
                elif classification["common_diff_count"] > 0 and snr_threshold is not None and snr >= snr_threshold:
                    pass  # significant diff_causal = apply
                else:
                    print(f"[selfop] No significant signal (novel=0, diff_causal={classification['common_diff_count']}, "
                          f"z={snr:.2f}) — skipping Phase 3 (main optimizer).")
                    should_skip = True
            elif convergence_mode == "snr":
                if snr_threshold is not None and snr < snr_threshold:
                    print(f"[selfop] z={snr:.2f} < z_crit={snr_threshold:.2f} "
                          f"— skipping Phase 3 (main optimizer).")
                    should_skip = True

        if should_skip:
            return {
                "optimizer": self.name,
                "phase1_results": phase1_results,
                "phase2_results": phase2_results,
                "snr": snr,
                "classification": classification,
                "skipped": True,
                "session_id": session_id,
            }

        print("[selfop] Phase 3: Running main optimizer (accumulated report + agent_home update)...")
        main_result = await self._run_main_optimizer(step_dir, step_ids, session_id)
        print("[selfop] Done.")

        return {
            "optimizer": self.name,
            "phase1_results": phase1_results,
            "phase2_results": phase2_results,
            "snr": snr,
            "classification": classification,
            "skipped": False,
            **main_result,
        }
