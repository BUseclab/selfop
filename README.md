# SelfOp

Code and results for **SelfOp: An Optimization Algorithm for Self-Improving Security Agents**.

SelfOp improves a frozen agent's context using textual gradients. It works in three stages: it computes per-task gradients, accumulates them across tasks, and stops when the gradient signal reaches the noise floor. The paper evaluates it on [CyberGym](https://github.com/sunblaze-ucb/cybergym) PoC generation, using Codex as both the agent and the optimizer.

## Repository layout

```
selfop/              the optimizer (installed as the `selfop` command)
  optimizer/         gradient.py (§3.2) → accumulation.py (§3.3) → convergence.py (§3.4) → selfop.py
  accumulation/      gradient clustering/ranking and hard/soft coverage classifier
  policy/            structure policy + checker given to the optimizer
  runner/            Codex and Docker runners
  tools/             helper scripts the optimizer uses to inspect trajectories
tasks/cybergym/      CyberGym task: data split, Docker image, initial skill
results/             skill snapshots from every optimization step in the paper
```

## Setup

Requirements: [uv](https://docs.astral.sh/uv/), Docker, and the [Codex CLI](https://github.com/openai/codex).

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .

uv venv --python 3.12 --clear selfop/tools/.venv   # interpreter for the optimizer's helper tools
codex login                                # agent + optimizer auth (~/.codex/auth.json)
```

All commands below assume the environment is active (`source .venv/bin/activate`) and are run from the repository root.

**CyberGym.** Clone and install CyberGym, download its data, and build the agent image:

```bash
git clone https://github.com/sunblaze-ucb/cybergym.git tasks/cybergym/repo/cybergym
uv pip install -e 'tasks/cybergym/repo/cybergym[dev,server]'

# agent-facing data -> tasks/cybergym/data/cybergym_data
git lfs install
git clone https://huggingface.co/datasets/sunblaze-ucb/cybergym tasks/cybergym/data/cybergym_data

# processed task metadata (patch diffs, bug-report metadata) used for gradient computation
#   -> tasks/cybergym/data/cybergym_data/processed_data
git clone https://github.com/saadullah01/processed_data.git tasks/cybergym/data/cybergym_data/processed_data

# server data (binary-only mode, ~130GB) -> tasks/cybergym/data/cybergym-server-data
python tasks/cybergym/repo/cybergym/scripts/server_data/download_binary_only_runners.py   # pulls runner Docker images
wget -P tasks/cybergym/data https://huggingface.co/datasets/sunblaze-ucb/cybergym-server-binary/resolve/main/cybergym-server-data.7z
7z x tasks/cybergym/data/cybergym-server-data.7z -otasks/cybergym/data
rm tasks/cybergym/data/cybergym-server-data.7z

bash tasks/cybergym/docker/build.sh
```

The resulting layout, which `tasks/cybergym/task.py` expects:

```
tasks/cybergym/data/
├── split.json
├── cybergym_data/
│   ├── data/{arvo,oss-fuzz}/...
│   └── processed_data/{arvo,oss-fuzz}/...
└── cybergym-server-data/
```

Start the PoC verification server in a separate terminal, with the same environment active (use absolute paths):

```bash
python -m cybergym.server --host 0.0.0.0 --port 8666 \
    --log_dir     "$(pwd)/tasks/cybergym/server_poc" \
    --db_path     "$(pwd)/tasks/cybergym/server_poc/poc.db" \
    --binary_dir  "$(pwd)/tasks/cybergym/data/cybergym-server-data"
```

Create a `.env` file in the repository root:

```bash
CYBERGYM_SERVER=http://localhost:8666
OPENAI_API_KEY=...                         # used by gradient accumulation
```

## Run SelfOp

The defaults reproduce the paper's configuration:

| Setting | Value |
|---|---|
| Model (agent and optimizer) | GPT-5.4-mini |
| Training tasks | 224 |
| Batch size | 16 |
| Accumulation | loose, ρ_imp = 0.20, ρ_str = 0.30 |
| Gradient annotation | hard/soft coverage |
| Convergence | stop when z < 1.0 for 3 steps, with p₀ = 0.073 |

```bash
selfop train --run-dir outputs/selfop_gpt-5.4-mini
```

To run with GPT-5.4, add `--model gpt-5.4 --optimizer-model gpt-5.4 --accum-model gpt-5.4`. A run picks up where it left off if you re-run the same command. Use `selfop train -h` to see every option.

Evaluate any skill (an `agent_home` directory) on the test split:

```bash
selfop eval --task cybergym --split test \
    --agent-home results/gpt-5.4-mini/step_8 \
    --eval-dir   outputs/eval_gpt-5.4-mini_step_8
```

## Outputs

```
outputs/<run>/
├── agent_home_snapshots/step_N/   skill after optimizer step N (step_-1 = initial skill)
├── train.jsonl, val.jsonl         per-step accuracy, novelty / z-score
├── workspace/steps/step_N/        per-task trajectories, scores, gradients, accumulated report
└── optimizer/                     optimizer workspace, prompts and traces
```

## Results

`results/` contains the skill snapshot from every optimization step of the paper's GPT-5.4-mini and GPT-5.4 runs. See [`results/README.md`](results/README.md).
