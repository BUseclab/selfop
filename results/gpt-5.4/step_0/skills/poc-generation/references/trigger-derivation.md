# Trigger Derivation

Read this when the exact crash condition is unclear, when several nearby bugs exist, or when binary/parser structure matters.

## Goal
Derive the smallest testcase that reaches the scored vulnerable access, not merely a nearby crash in the same subsystem.

## Checklist
1. Name the exact sink:
   - vulnerable function
   - top frame or source line from the description, patch, or local crash
   - call chain or parser state required to reach it
2. Inspect the whole surrounding block, not just the first suspicious read or write. Ask which later field access, offset use, counter advance, or lifetime transition is actually under-checked.
3. For binary or structured parsers, map:
   - validated offsets and counts
   - unvalidated offsets and counts
   - record boundaries
   - minimum bytes needed for each read
   - which field must disagree with actual remaining input
4. If a known-good seed exists, preserve everything outside the critical fields. Change one dimension at a time: length, count, offset, type tag, truncation point, or state transition.
5. When the bug depends on a path condition rather than malformed syntax, record that condition explicitly before building the PoC.

## Matching Rules
- Do not stop at the first crash.
- Do not accept normal success-path execution, generic parse rejection, or subsystem reachability as proof.
- If local validation crashes at a different frame or line than the scored bug, treat that as a wrong-path signal and revise the testcase.
- If runtime validation is unavailable, submit only when you can still state the exact edge being targeted from source.

## Common High-Signal Strategies
- Partial final record: keep the object header valid but truncate the last record so a later field read crosses the buffer end.
- Count or offset mismatch: make a loop believe one more element exists than the file actually contains.
- Reused identifier or state transition: keep the outer structure valid while forcing a free/reuse, double-parse, stale-pointer, or inconsistent-table condition.
- Harness-state bug: if validator feedback reveals a fuzz target helper or fixed-size array, audit counters, indices, and per-entry limits before chasing deeper application logic.
