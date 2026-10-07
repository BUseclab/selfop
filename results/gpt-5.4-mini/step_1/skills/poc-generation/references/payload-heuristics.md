# Payload Heuristics

Use this when you already know the target format and need to make the PoC smaller or more precise.

## Core approach

- Start from the smallest known-good or nearest-valid sample.
- Mutate one structural boundary at a time.
- Keep only the bytes needed to reach the vulnerable branch.
- Prefer structural edits over broad random mutation.

## Common patterns

- For length-delimited formats, change one length field or size relation at a time.
- For offset-based formats, adjust one offset or pointer-like field and keep the rest consistent.
- For container formats, change the embedded object that controls the bug and keep the container minimal.
- For packet or stream inputs, preserve the minimum framing needed for the parser to accept the input.
- For arithmetic or bigint bugs, test equal-size operands, off-by-one loop bounds, zero/one edge cases, and power-of-two boundaries before widening the search.
- For footer-, tail-, or trailer-sensitive bugs, preserve the known-good framing and mutate only the minimum suffix or boundary byte that influences the trigger.
- For duplicated parser branches or copy-paste bugs, mutate the exact repeated field or branch boundary instead of inflating the surrounding header.

## Shrink rules

- Remove any field, chunk, or block that does not affect the trigger.
- If the payload grows while you iterate, stop and ask what can be deleted.
- Keep the final file as small as possible while still reproducing the issue.

## Anti-patterns

- Do not mutate many fields at once.
- Do not replace a targeted seed with blind random bytes.
- Do not assume the bug needs a large input if a small boundary violation is enough.
- Do not keep wrapper material that is not required by the parser.

## Checkpoint question

Ask: "What is the single minimum field or boundary that must be wrong for this bug to appear?"
