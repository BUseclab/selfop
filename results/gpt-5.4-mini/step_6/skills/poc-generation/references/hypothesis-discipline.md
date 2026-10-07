# Hypothesis Discipline

Use this when the description is ambiguous, the source search branches, or you are tempted to chase more than one bug idea.

## Rule

Keep one concrete hypothesis active at a time.

## What to record

- The exact condition that must become true for the bug to trigger.
- The exact field, offset, frame, or state variable that controls that condition.
- The exact parser branch, sink, or call path you are targeting.
- The smallest input change that would falsify the hypothesis.

## How to search

- Start from the description and source, then expand only to neighboring concepts if the literal clue is missing.
- If a variable name is absent, look for adjacent length, offset, metadata, or copy-path logic that could encode the same condition.
- If a branch does not match the hypothesis, stop carrying it forward instead of blending it with the next idea.

## Anti-patterns

- Do not keep two unrelated payload ideas alive in parallel unless the source proves they are the same bug.
- Do not switch from one parser family to another without an explicit source link.
- Do not let a speculative hypothesis survive after the harness or source contradicts it.

