# Validation Checklist

Use this before every submission.

## Required gate

Do not submit until the candidate has been run through the exact target or harness from `submit.sh` and you have evidence that the intended vulnerability is triggered.

## Proof ladder

- `diagnostic`: local helper crashes, semantic signals, upstream repros, or surrogate harness results.
- `provisional`: the candidate looks plausible, but the exact `submit.sh` path has not reproduced it yet.
- `proven`: the exact target reproduces the same failure twice and the failure matches the intended bug.
- Only `proven` is submit-ready.

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
- Any local helper or surrogate crash that does not reproduce on the exact `submit.sh` target.
- Successful upload, acceptance, or transport through `submit.sh` without a matching evaluator failure.

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
- If the exact target cannot be exercised, stop and recover the contract instead of treating a nearby crash as proof.
