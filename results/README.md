# Results

These are the `poc-generation` skill snapshots from the SelfOp runs in the paper, one for every optimization step.

```
results/
├── gpt-5.4-mini/step_-1 … step_13    GPT-5.4-mini (agent + optimizer), 14 steps
└── gpt-5.4/step_-1 … step_11         GPT-5.4 (agent + optimizer), 12 steps
```

- `step_-1` is the initial skill (CyberGym's base prompt, `tasks/cybergym/initial_home`).
- `step_N` is the skill after optimizer step N. Step numbers match the paper's figures.

Each snapshot is a complete `agent_home`, so it can be evaluated directly:

```bash
selfop eval --task cybergym --split test \
    --agent-home results/gpt-5.4-mini/step_8 \
    --eval-dir   outputs/eval_gpt-5.4-mini_step_8
```

| Run | Baseline (test) | SelfOp (test) |
|---|---|---|
| GPT-5.4-mini | 38% | 55% |
| GPT-5.4 | 49% | 67.5% |

For GPT-5.4-mini, the convergence detector selects `step_8`, which reaches 55% on test. The best test result, 56.2%, is at `step_12`.
