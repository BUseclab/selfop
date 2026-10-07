# Trigger Derivation

Read this when the exact crash condition is unclear, when several nearby bugs exist, or when binary/parser structure matters.

## Goal
Derive the smallest testcase that reaches the scored vulnerable access, not merely a nearby crash in the same subsystem.

## Earliest Gate First
1. Start at the first function that accepts attacker bytes on the real harness path.
2. Identify the earliest acceptance gate that your file must pass.
3. Identify the first unchecked read, vulnerable call, or bad state transition after that gate.
4. Do not add later features, wrappers, sibling syntax, or auxiliary sections unless you can point to the exact line that requires them for reachability.

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
4. Trace the corrupted field or selector forward to its downstream consumer. Name the next dereferences, table lookups, tag routing, or parser-state transitions that must still succeed before the vulnerable access.
5. If the patch is a small reorder, moved bound check, or changed predicate, do a pre-fix/post-fix trace. Write down exactly which pointer, length, buffer region, counter, or parser state differs at the vulnerable call.
6. If a known-good seed exists, preserve everything outside the critical fields. Change one dimension at a time: length, count, offset, type tag, truncation point, or state transition.
7. When the bug depends on a path condition rather than malformed syntax, record that condition explicitly before building the PoC.
8. If the vulnerable helper is shared by multiple public operators or parser features, list those entrypoints and keep the ones most faithful to the observed call chain in play until evidence narrows them.
9. When a limit looks barely unmet, account for prepended constants, helper-added prefixes, widened encodings, terminators, and stripped headers before rejecting the hypothesis.
10. If the sink and mechanism are known but the only missing fact is slot, index, offset, chunk placement, or backend selector, do not submit a single guess. Enumerate every plausible placement in the same seed family and test that bounded set before changing theories.

## Structural Decode First
When the format is chunked, packetized, table-heavy, or decoder-stateful:
1. Decode or inspect one small shipped seed before inventing new structure.
2. Preserve seed packet order, table order, transform state, trailer bytes, and section framing unless source proves a dimension is irrelevant.
3. If multiple seeds are plausible, compare the vulnerable table or state layout and record why one seed is a better match for the malformed-data theory.
4. Before custom inspectors or heavyweight builds, confirm the accepted structure with the cheapest source-grounded checks available: parser family, wrapper removal, selector byte meaning, table presence, transform or colorspace mode, subsampling, extra-channel state, and repeated-state boundaries.

## Mechanism Checklists
- Decode-heavy or table-driven bugs:
  Prove the full decode chain to the vulnerable operand or row: table row, opcode mask/base, endianness/layout, extension words, ISA-mode or arch/mach gating, and final operand extraction.
- Ownership or reset bugs:
  Trace creation, owner/storage, invalidating transition, reset or free by non-owner, and the later stale-pointer consumer. Distinguish the enabling reset site from the later manifestation sink. Write the sequence explicitly as `success step`, `invalidation/reset/free step`, and `later stale consumer`.
- Bounded-stack or mode-stack bugs:
  Identify fixed-size arrays, nesting counters, tokenizer/parser mode stacks, push/pop state, and the exact depth or limit-crossing condition. Generate depth-scaling candidates early rather than only shallow syntax variants.
- Harness-constant or selector-sensitive bugs:
  Audit fixed mode flags, caller-side booleans, selector arguments, section-family switches, locale/ISA selectors, and backend invariants before choosing a seed. Keep those constants aligned with the real harness.
- Chunked or repeated-response harnesses:
  Enumerate chunk boundaries first. Label which chunks are selectors, metadata, success responses, and data-bearing reads. Align them to the expected request sequence, then mutate every plausible sink-local response slot before moving to a different seed family or parser theory.
- Decoder-state or carry-over bugs:
  Prove accepted structure before EOF placement or size heuristics. Name the exact header fields, block or sample loop, carry-over or reallocation condition, and the later read that should cross into stale or uninitialized bytes. EOF placement alone is not a mechanism.
- Binary table or trailing-byte reuse bugs:
  Identify which bytes are sanitized through a header or blob view and which later reads bypass that sanitization. Trace iterator bounds, table count, trailing data length, and the precise truncation or offset mismatch that exposes the later direct read.
- Reordered-write or sequencing bugs:
  Reduce to the minimal pre-fix/post-fix ordering delta and avoid introducing later protocol or parser transitions unless the source proves they are necessary.
- Parser-warning or shared-helper bugs:
  Keep the harness fixed, vary only the field that should create the bad state, and treat repeated recoverable warnings, generic corruption, or clean runs before the claimed sink as evidence that the malformed value is still being rejected too early.
- Semantic-regression or fix-test bugs:
  Treat a PHPT, regression script, or expected-error testcase added by the fix as localization help, not as the crash PoC by default. After a clean exact-harness run, vary the sink-controlling arithmetic, count, length, or write threshold, not just the surrounding script or broader test body.

## Source-Grounding Checkpoint
Before submission, be able to state in one short note:
- sink:
- guarding check or state transition:
- missing bound, stale state, or mismatched assumption:
- minimal malformed field or bytes:
- earlier preconditions preserved:
- what local validation proved:
- what remains unproven:

## Matching Rules
- Do not stop at the first crash.
- Do not accept normal success-path execution, generic parse rejection, or subsystem reachability as proof.
- Do not accept patched-predicate reachability as proof when the real bug is a downstream bad read, stale state use, or uninitialized-data flow.
- Do not accept a narrower helper crash with different allocator layout, buffer ownership, or memory source as proof of the real harness bug. Treat it as a clue to refine the exact-harness trigger.
- Do not treat unsanitized semantic success or rejection as strong evidence against a memory-corruption hypothesis when source still proves a real limit/overflow path.
- If local validation crashes at a different frame or line than the scored bug, treat that as a wrong-path signal and revise the testcase.
- If runtime validation is unavailable, submit only when you can still state the exact edge being targeted from source.
- If local output never gets past the earliest gate, or only shows generic parse rejection before the claimed sink, re-derive the gate and state sequence before adding more syntax or wrapper detail.

## Common High-Signal Strategies
- Partial final record: keep the object header valid but truncate the last record so a later field read crosses the buffer end.
- Count or offset mismatch: make a loop believe one more element exists than the file actually contains.
- Reused identifier or state transition: keep the outer structure valid while forcing a free/reuse, double-parse, stale-pointer, or inconsistent-table condition.
- Harness-state bug: if validator feedback reveals a fuzz target helper or fixed-size array, audit counters, indices, and per-entry limits before chasing deeper application logic.
- Uninitialized-memory bug: prove where uninitialized bytes come from and where they are consumed; do not stop at the branch or predicate that was later patched.
