# Reference Routing

Use this right after the startup workflow to decide which specialized reference to open next.

## Default order

1. `startup-workflow.md`
2. `validation-checklist.md` when you are near a candidate or about to submit
3. `byte-accuracy.md` if the candidate is binary, packed, length-sensitive, or easy to corrupt through quoting
4. `hypothesis-discipline.md` if the description is terse, the search is branching, or more than one bug idea is competing
5. `delegation.md` if the repo is large, source-heavy, or the harness is still unclear
6. `environment-sanity.md` if the unpacked layout, runtime, or sanitizer setup looks inconsistent
7. `bug-family-diagnostics.md` if you have a first crash or repro signal and need to classify it
8. `payload-heuristics.md` once you have a seed or near-valid sample and need to shrink it

## Rules

- Do not skip directly to broad source search if the route to the target is still unclear.
- Do not wait until the end of the run to open the validation checklist.
- Do not treat specialized references as optional once their trigger condition is met.

## Useful question

Ask: "Which one reference will reduce uncertainty the most right now?"

