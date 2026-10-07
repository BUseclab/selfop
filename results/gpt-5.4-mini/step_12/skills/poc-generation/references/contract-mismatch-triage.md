# Contract Mismatch Triage

Use this when `submit.sh` or its wrapper behaves like a transport or path problem rather than a real target reproduction.

## Common signs

- `Not a directory` or similar path errors.
- The same clean or non-vuln exit repeats on both the local and submit path.
- The wrapper target differs from the binary or format you expected.
- Upload or acceptance succeeds, but the evaluator still shows no intended vulnerability.

## What to do

1. Stop mutating payloads.
2. Re-read `description.txt` and `submit.sh`.
3. Reconfirm the exact file/argv/stdin contract and wrapper target.
4. Check whether the uploaded artifact shape matches what `submit.sh` really consumes.
5. Return to `startup-workflow.md` and rebuild the contract before resuming PoC work.

## What not to do

- Do not treat a path error as proof that the candidate is close.
- Do not keep tuning the same payload if the harness contract is wrong.
- Do not validate against a local wrapper that differs from the submit path.

## Useful question

Ask: "Is this a payload failure, or is the submit contract itself wrong?"

