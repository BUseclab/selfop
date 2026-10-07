"""SelfOp training loop (resumable, multi-epoch).

Usage:
    selfop train --run-dir outputs/my_run
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from selfop.config import PipelineConfig
from selfop.optimizer import Optimizer, SelfOp
from selfop.policy import POLICY_CHECKER_FILE, POLICY_FILE
from selfop.task_runner import evaluate
from selfop.utils.batching import make_steps
from selfop.utils.io import (
    append_jsonl,
    initialize_agent_home,
    load_checkpoint,
    save_checkpoint,
    snapshot_agent_home,
)

from tasks import get_task
from tasks.base import Task

def _restore_agent_home_from_snapshot(config: PipelineConfig, label: str) -> None:
    """Restore snapshot entries into the live agent_home (selective merge)."""
    src = config.agent_home_snapshots_dir / label
    if not src.exists():
        raise FileNotFoundError(f"Snapshot not found: {src}")
    dst = config.agent_home_dir
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        dst_entry = dst / entry.name
        if dst_entry.exists():
            if dst_entry.is_dir():
                shutil.rmtree(dst_entry)
            else:
                dst_entry.unlink()
        if entry.is_dir():
            shutil.copytree(entry, dst_entry)
        else:
            shutil.copy2(entry, dst_entry)


def _sync_optimizer_home(optimizer: Optimizer, config: PipelineConfig) -> None:
    """Copy optimizer's edited skill (+ agents if present) back to config.agent_home_dir."""
    opt_home = optimizer.workspace_dir / "agent_home"
    if not opt_home.exists():
        return

    dst_home = config.agent_home_dir
    skill_src = opt_home / "skills" / config.skill_name
    if skill_src.exists():
        skill_dst = dst_home / "skills" / config.skill_name
        if skill_dst.exists():
            shutil.rmtree(skill_dst)
        shutil.copytree(skill_src, skill_dst)

    agents_src = opt_home / "agents"
    if agents_src.exists():
        agents_dst = dst_home / "agents"
        if agents_dst.exists():
            shutil.rmtree(agents_dst)
        shutil.copytree(agents_src, agents_dst)


def _is_converging_optimizer(optimizer: Optimizer) -> bool:
    """Check if the optimizer supports convergence detection."""
    from selfop.optimizer.convergence import ConvergenceOptimizer
    return isinstance(optimizer, ConvergenceOptimizer)


async def run_training(
    config: PipelineConfig,
    task: Task,
    optimizer: Optimizer,
    train_ids: list[str],
    val_ids: list[str],
    extra_train_ids: list[str] | None = None,
) -> None:
    """Run training across all epochs: forward + optimize + validate per step, with resume."""
    batches = make_steps(train_ids, config.batch_size, config.epochs)
    if extra_train_ids:
        extra_batches = [extra_train_ids[i:i + config.batch_size]
                         for i in range(0, len(extra_train_ids), config.batch_size)]
        batches.extend(extra_batches)
    total_batches = len(batches)

    ckpt = load_checkpoint(config)
    converging = _is_converging_optimizer(optimizer)

    # Restore state from checkpoint
    if ckpt:
        opt_step = ckpt["completed_step"] + 1
        start_batch_idx = (ckpt.get("batch_idx", ckpt["completed_step"]) + 1)
        optimizer_session_id = ckpt.get("optimizer_session_id")
        consecutive_skips = ckpt.get("consecutive_skips", 0) if converging else 0
        current_step_ids: list[str] = ckpt.get("current_step_ids", []) if converging else []
    else:
        opt_step = 0
        start_batch_idx = 0
        optimizer_session_id = None
        consecutive_skips = 0
        current_step_ids = []

    if converging:
        gate_mode = "gate+accumulate" if config.convergence_gate else "stop-only"
        print(f"[train] Convergence detection enabled: "
              f"mode={config.convergence_mode}, z_crit={config.snr_threshold}, "
              f"convergence_k={config.convergence_k}, gate={gate_mode}")
        if current_step_ids:
            print(f"[train] Resuming with {len(current_step_ids)} accumulated tasks in opt_step {opt_step}, "
                  f"{consecutive_skips} consecutive skips")

    if not ckpt:
        initialize_agent_home(config)
        snapshot_agent_home(config, "step_-1")
    else:
        restore_label = f"step_{opt_step - 1}" if opt_step > 0 else "step_-1"
        _restore_agent_home_from_snapshot(config, restore_label)
        print(f"[train] Resuming from opt_step {opt_step}, batch_idx {start_batch_idx}")

    optimizer.setup(config, task, optimizer.name)
    config.save()

    converged = False

    for batch_idx in range(start_batch_idx, total_batches):
        batch_ids = batches[batch_idx]

        if converging and config.convergence_gate:
            # Expand-in-place: accumulate task IDs into the current opt_step
            current_step_ids.extend(batch_ids)
            step_ids = current_step_ids
        else:
            step_ids = batch_ids

        step_path = config.step_dir(opt_step)
        print(f"\n{'='*60}")
        print(f"opt_step {opt_step} | batch {batch_idx}/{total_batches-1} | "
              f"tasks={len(step_ids)} (batch={len(batch_ids)})")
        print(f"{'='*60}")

        # Forward pass + eval (idempotent — skips tasks with existing outputs)
        task.run_forward(config, step_path, step_ids)
        task.run_evaluation(config, step_path, step_ids)
        if config.include_task_meta:
            task.populate_task_meta(step_path, step_ids)

        # Train score (report on latest batch for recency, full set for context)
        batch_scores = task.read_scores(step_path, batch_ids)
        batch_acc = sum(batch_scores.values()) / len(batch_scores)
        if len(step_ids) > len(batch_ids):
            all_scores = task.read_scores(step_path, step_ids)
            total_acc = sum(all_scores.values()) / len(all_scores)
            print(f"[train] batch_acc={batch_acc:.1%}  total_acc={total_acc:.1%} ({len(step_ids)} tasks)")
        else:
            total_acc = batch_acc
            print(f"[train] batch_acc={batch_acc:.1%}")

        print(task.format_batch_scores(step_path, batch_ids))

        batch_scores = task.format_batch_scores(step_path, step_ids)
        print(batch_scores)

        # Optimizer step
        if converging:
            opt_result = await optimizer.run(
                step_dir=step_path,
                step_ids=step_ids,
                session_id=optimizer_session_id,
                snr_threshold=config.snr_threshold,
                convergence_mode=config.convergence_mode,
                convergence_gate=config.convergence_gate,
            )
        else:
            opt_result = await optimizer.run(
                step_dir=step_path, step_ids=step_ids, session_id=optimizer_session_id,
            )

        snr = opt_result.get("snr")
        step_skipped = opt_result.get("skipped", False)

        if converging and step_skipped and config.convergence_gate:
            # Gate mode: Phase 3 was skipped, accumulate in-place
            consecutive_skips += 1
            if snr is None:
                reason = "no improvement themes"
            elif config.convergence_mode == "novelty":
                reason = f"no novel/diff_causal themes (z={snr:.2f})"
            else:
                reason = f"z={snr:.2f} < z_crit={config.snr_threshold}"
            print(f"[train] SKIPPED ({reason}), "
                  f"consecutive_skips={consecutive_skips}/{config.convergence_k}")

            if consecutive_skips >= config.convergence_k:
                converged = True
                conv_reason = (f"no novel themes for {config.convergence_k} consecutive batches"
                              if config.convergence_mode == "novelty"
                              else f"z < z_crit={config.snr_threshold} for {config.convergence_k} consecutive batches")
                print(f"\n[train] CONVERGED at opt_step {opt_step} ({conv_reason})")
        else:
            # Track novelty for stop-only mode (tiered signal)
            if converging and not config.convergence_gate:
                classification = opt_result.get("classification")
                has_new = True
                if classification:
                    if classification["novel_count"] > 0:
                        has_new = True
                    elif classification["common_diff_count"] > 0 and snr is not None and snr >= config.snr_threshold:
                        has_new = True
                    else:
                        has_new = False
                if has_new:
                    consecutive_skips = 0
                else:
                    consecutive_skips += 1
                    snr_str = f" (z={snr:.2f})" if snr is not None else ""
                    diff_str = f", diff_causal={classification['common_diff_count']}" if classification else ""
                    print(f"[train] No significant signal{snr_str}{diff_str}, "
                          f"consecutive_no_novel={consecutive_skips}/{config.convergence_k}")
                    if consecutive_skips >= config.convergence_k:
                        converged = True
                        print(f"\n[train] CONVERGED at opt_step {opt_step + 1} "
                              f"(no significant signal for {config.convergence_k} consecutive steps)")
            elif converging and config.convergence_gate:
                # Gate mode: applied step resets counters
                consecutive_skips = 0
                current_step_ids = []

            optimizer_session_id = opt_result.get("session_id")
            _sync_optimizer_home(optimizer, config)
            snapshot_agent_home(config, f"step_{opt_step}")
            opt_step += 1

        # Validation (on apply or convergence; gated by val_interval)
        val_acc = None
        if val_ids:
            is_last = (batch_idx == total_batches - 1) or converged
            applied = not step_skipped
            should_validate = applied and (
                opt_step % config.val_interval == 0
                or is_last
            )
            if should_validate:
                val_dir = config.val_dir(opt_step - 1)
                val_scores = evaluate(config, task, config.agent_home_dir, val_ids, val_dir)
                val_acc = sum(val_scores.values()) / len(val_scores)

        # Log
        log_entry = {
            "opt_step": opt_step - (0 if step_skipped else 1),
            "batch_idx": batch_idx,
            "train_acc": total_acc,
            "batch_acc": batch_acc,
            "train_n": len(step_ids),
            "batch_n": len(batch_ids),
        }
        if converging:
            log_entry["step_type"] = "skipped" if step_skipped else "applied"
            log_entry["convergence_gate"] = config.convergence_gate
            if snr is not None:
                log_entry["snr"] = snr
            classification = opt_result.get("classification")
            if classification:
                log_entry["novel_count"] = classification["novel_count"]
                log_entry["common_same_count"] = classification["common_same_count"]
                log_entry["common_diff_count"] = classification["common_diff_count"]
                if "_coverage_detail" in classification:
                    log_entry["gap_count"] = classification["_coverage_detail"]["gap_count"]
                    log_entry["covered_count"] = classification["_coverage_detail"]["covered_count"]
            log_entry["consecutive_no_novel"] = consecutive_skips
            if converged:
                log_entry["converged"] = True
        if val_acc is not None:
            log_entry["val_acc"] = val_acc
            log_entry["val_n"] = len(val_ids)
        append_jsonl(config.train_log, log_entry)
        save_checkpoint(
            config, completed_step=opt_step - (0 if step_skipped else 1),
            optimizer_session_id=optimizer_session_id,
            consecutive_skips=consecutive_skips if converging else None,
            batch_idx=batch_idx if converging else None,
            current_step_ids=current_step_ids if converging else None,
        )

        if val_acc is not None:
            print(f"[train] opt_step {opt_step-1} => total_acc={total_acc:.1%}  val={val_acc:.1%}")
        else:
            status = "SKIPPED" if step_skipped else "applied"
            snr_str = f"  z={snr:.2f}" if snr is not None else ""
            print(f"[train] opt_step {opt_step - (0 if step_skipped else 1)} => "
                  f"acc={total_acc:.1%}  ({status}{snr_str})")

        if converged:
            break

    if converged:
        print(f"\n[train] Training converged at opt_step {opt_step} after {batch_idx + 1} batches")
    else:
        print(f"\n[train] Training complete ({opt_step} opt_steps, "
              f"{total_batches} batches across {config.epochs} epochs)")


# ── CLI ───────────────────────────────────────────────────────────────

def main() -> None:

    p = argparse.ArgumentParser(
        description="Optimize an agent's skill with SelfOp.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--run-dir", type=Path, required=True,
                   help="Output directory for this training run.")
    p.add_argument("--task", default="cybergym",
                   help="Task name.")
    p.add_argument("--split-file", type=Path, default=None,
                   help="Path to split JSON (overrides task default).")
    p.add_argument("--initial-home", type=Path, default=None,
                   help="Path to initial agent home (overrides task default).")
    p.add_argument("--model", default="gpt-5.4-mini")
    p.add_argument("--agent", default="codex", choices=["codex"])
    p.add_argument("--reasoning", default="high")
    p.add_argument("--num-workers", type=int, default=16)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--val-interval", type=int, default=1,
                   help="Run validation every N steps (always validates on the last step).")
    p.add_argument("--optimizer-model", default="gpt-5.4-mini")
    p.add_argument("--optimizer-reasoning", default="high")
    p.add_argument("--policy-file", type=Path, default=POLICY_FILE,
                   help="Structure policy given to the optimizer.")
    p.add_argument("--policy-checker-file", type=Path, default=POLICY_CHECKER_FILE,
                   help="Structure checker the optimizer runs after its edits.")
    p.add_argument("--model-provider", default=None)
    p.add_argument("--no-meta", action="store_true",
                   help="Skip generating extra task metadata (extra_meta.json, batch_line.txt) for the optimizer.")
    p.add_argument("--no-val", action="store_true",
                   help="Skip validation entirely (no val forward passes).")
    p.add_argument("--accum-model", default="gpt-5.4-mini",
                   help="Model for accumulation pipeline.")
    p.add_argument("--accum-reasoning", default="high",
                   help="Reasoning effort for accumulation pipeline.")
    p.add_argument("--accum-chunk-size", type=int, default=16,
                   help="Chunk size for map-reduce clustering in gradient accumulation.")
    p.add_argument("--accum-min-support", type=int, default=2,
                   help="Minimum task count for a theme to be selected.")
    p.add_argument("--accum-min-ratio-strength", type=float, default=0.30,
                   help="Minimum support ratio for strength themes.")
    p.add_argument("--accum-min-ratio-improvement", type=float, default=0.20,
                   help="Minimum support ratio for improvement themes.")
    p.add_argument("--accum-min-composite-strength", type=float, default=0.00,
                   help="Minimum composite score for strength themes.")
    p.add_argument("--accum-min-composite-improvement", type=float, default=0.00,
                   help="Minimum composite score for improvement themes.")
    p.add_argument("--classifier-type", default="coverage", choices=["theme_history", "coverage"],
                   help="Which Phase 2.75 classifier to use: 'coverage' (default) uses CodexRunner to check "
                        "whether the current skill already addresses each theme; 'theme_history' compares "
                        "against persisted theme history.")
    p.add_argument("--convergence-mode", default="snr", choices=["snr", "novelty"],
                   help="Convergence gate: 'novelty' skips when no novel/diff_causal themes; "
                        "'snr' skips when z-score < threshold.")
    p.add_argument("--snr-threshold", type=float, default=1.0,
                   help="Z-score critical value (z_crit) for convergence detection (mode=snr only).")
    p.add_argument("--convergence-k", type=int, default=3,
                   help="Consecutive low-SNR steps to declare convergence.")
    p.add_argument("--convergence-gate", action="store_true",
                   help="skip Phase 3 and accumulate batches when no novelty detected. "
                        "Without this flag, Phase 3 always runs and novelty is used only for early stopping.")
    p.add_argument("--classifier-p0", type=float, default=0.073,
                   help="Baseline noise rate (p0) for the SNR one-proportion z-test.")
    args = p.parse_args()

    task_kwargs = {}
    if args.split_file:
        task_kwargs["split_file"] = args.split_file
    if args.initial_home:
        task_kwargs["initial_home"] = args.initial_home
    task = get_task(args.task, **task_kwargs)
    task.setup()

    config = PipelineConfig(
        run_dir=args.run_dir,
        model=args.model,
        agent=args.agent,
        reasoning=args.reasoning,
        num_workers=args.num_workers,
        batch_size=args.batch_size,
        epochs=args.epochs,
        val_interval=args.val_interval,
        skill_name=task.cfg.skill_name,
        initial_home=task.cfg.initial_home,
        optimizer_model=args.optimizer_model,
        optimizer_reasoning=args.optimizer_reasoning,
        policy_file=args.policy_file,
        policy_checker_file=args.policy_checker_file,
        model_provider=args.model_provider,
        include_task_meta=not args.no_meta,
        accum_model=args.accum_model,
        accum_reasoning=args.accum_reasoning,
        accum_chunk_size=args.accum_chunk_size,
        accum_min_support=args.accum_min_support,
        accum_min_support_ratio_strength=args.accum_min_ratio_strength,
        accum_min_support_ratio_improvement=args.accum_min_ratio_improvement,
        accum_min_composite_strength=args.accum_min_composite_strength,
        accum_min_composite_improvement=args.accum_min_composite_improvement,
        classifier_type=args.classifier_type,
        convergence_mode=args.convergence_mode,
        snr_threshold=args.snr_threshold,
        convergence_k=args.convergence_k,
        convergence_gate=args.convergence_gate,
        classifier_p0=args.classifier_p0,
    )

    data = task.load_data_ids()
    train_ids = data["train"]
    extra_train_ids = data.get("extra_train", [])
    val_ids = [] if args.no_val else data["validation"]

    optimizer = SelfOp()

    total_steps = len(make_steps(train_ids, args.batch_size, args.epochs))
    if extra_train_ids:
        total_steps += len([extra_train_ids[i:i + args.batch_size]
                           for i in range(0, len(extra_train_ids), args.batch_size)])
    print(f"[train] task={args.task}  model={args.model}  "
          f"batch_size={args.batch_size}")
    print(f"[train] train={len(train_ids)}  extra_train={len(extra_train_ids)}  "
          f"val={len(val_ids)}  epochs={args.epochs}  total_steps={total_steps}")

    asyncio.run(run_training(config, task, optimizer, train_ids, val_ids, extra_train_ids))


if __name__ == "__main__":
    main()
