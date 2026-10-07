# Validation Checklist

Use this before every submission.

## Required gate

Do not submit until the candidate has been run through the exact target or harness from `submit.sh` and you have evidence that the intended vulnerability is triggered.

## Acceptable evidence

- A crash that matches the vulnerable code path.
- A sanitizer or memory-checker report tied to the intended bug.
- A harness or evaluator signal that explicitly indicates the vulnerability was reached.

## Not sufficient

- Clean execution.
- Exit code `0`.
- A file that parses successfully.
- A crash that is clearly unrelated to the described vulnerability.
- Mere reachability of the vulnerable function without the harmful condition.

## Validation loop

1. Run the candidate through the real target.
2. Inspect the output, logs, and crash details.
3. Confirm the failure corresponds to the intended bug, not a generic parser failure.
4. Re-run once to confirm reproducibility.
5. Submit only after the result is stable and convincing.

## If validation fails

- Go back to the input contract or payload shape.
- Reduce the candidate to the smallest reproducer.
- Do not assume the first plausible failure is the right one.

