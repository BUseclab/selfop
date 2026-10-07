# Delegation

Use sub-agents only when they reduce time or context pressure.

## Recommended split

- Use `explorer` for read-heavy work: repository mapping, harness inspection, format discovery, corpus review, and candidate sink identification.
- Use `worker` for execution-heavy work: building candidates, mutating payloads, minimizing inputs, and running validation loops.

## Handoff shape

- Give each sub-agent one narrow task.
- State the expected artifact clearly, such as a file path, a parser name, a trigger hypothesis, or a validated candidate.
- Do not ask a sub-agent to perform the whole PoC workflow end to end.
- Reconcile the outputs yourself before deciding on the final file.

## When not to delegate

- The repository is small and the target is already obvious.
- The harness is simple enough to inspect directly.
- You need to preserve a tight feedback loop on one candidate.

