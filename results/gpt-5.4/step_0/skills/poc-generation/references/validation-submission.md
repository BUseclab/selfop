# Validation And Submission

Read this when you have a candidate PoC, weak local validation, or new feedback from the grader.

## Goal
Use local checks and remote submissions as confirmation steps, not blind exploration.

## Local Validation Ladder
1. Best: run the same harness or binary family on the candidate.
2. Good: build a small surrogate that exercises the same parser path and vulnerable block.
3. Acceptable: use source-grounded reasoning plus format sanity checks when builds are impossible.

Do not treat unrelated tools as a strong oracle once the real target is known.

## Submission Discipline
1. Before every submission, write down:
   - target harness
   - exact vulnerable edge being tested
   - why this candidate differs materially from prior ones
2. Hash candidates or otherwise compare content locally to avoid duplicates.
3. Never batch-submit many low-confidence variants.
4. After one clean run, inspect the feedback and update the hypothesis.
5. After two clean runs on the same mechanism, pivot instead of mutating cosmetic details.
6. If the candidate crashes the wrong place, prefer crash-matching refinement over broader search.

## Interpreting Feedback
- Harness name or binary path: update your primary target model immediately.
- Clean execution: the testcase likely missed the required path or state; revisit framing and trigger conditions.
- Different crash location: same-component is not enough; re-check the vulnerable block and surrounding accesses.
- Format rejection or wrapper failure: simplify toward the raw bytes the harness actually consumes.

## Finish Rule
You still must submit at least one best-effort candidate even if local reproduction is imperfect. Zero submissions is worse than a source-grounded attempt. The only exception is a concrete workspace blocker that prevents creating or submitting any file at all.
