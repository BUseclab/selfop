# Bug-Family Diagnostics

Use this when a candidate crashes or fails, but you need to decide whether it matches the intended bug family.

## General rule

Do not accept the first nearby failure. Classify the failure against the expected bug family before you submit or minimize it further.

## MSAN / uninitialized data

- Start from the origin stack, not the final symptom.
- Identify the first downstream consumer of the uninitialized value.
- Minimize to the smallest input that still exercises that exact origin-to-consumer chain.
- Do not confuse a generic sanitizer warning with the intended uninitialized-read path.

## ASan / memory corruption

- Match the crash stack to the described bug path.
- Reject unrelated heap/stack/global crashes even if they are reproducible.
- If multiple sanitizer crashes appear, keep only the one that follows the target sink and input condition.

## Decode / parser-family failures

- Require the exact decode signature or corruption condition described by the task.
- Treat a generic parse error or a regression fixture that merely reaches the decoder as insufficient.
- If the input reaches a parser function but does not trigger the harmful state, keep searching for the missing field or boundary.

## OOM / allocation-failure bugs

- Sweep allocation-failure counters systematically.
- Binary-search the smallest allocation index or size that reproduces the failure.
- Confirm that parser success alone is not being mistaken for proof.

## Final check

Ask: "Does this failure match the intended family and sink, or is it just the nearest reproducible crash?"

