# Validation And Submission

Read this when you have a candidate PoC, weak local validation, or new feedback from the grader.

## Goal
Use local checks and remote submissions as confirmation steps, not blind exploration.

## Local Validation Ladder
1. Best: run the same harness or binary family on the candidate.
2. Good: build a small surrogate that exercises the same parser path and vulnerable block.
3. Acceptable: use source-grounded reasoning plus format sanity checks when builds are impossible.

Do not treat unrelated tools as a strong oracle once the real target is known.
If the toolchain is clearly missing, allow at most one focused retry to fix a path or invocation mistake; do not spend the run probing package managers or repeating blocked build attempts.

## Submission Discipline
1. Before every submission, write down:
   - target harness
   - exact vulnerable edge being tested
   - why this candidate differs materially from prior ones
   - what was proven locally and what remains proxy-only
2. Hash candidates or otherwise compare content locally to avoid duplicates.
3. Never batch-submit many low-confidence variants.
4. After one clean run, inspect the feedback and update the hypothesis.
5. If the clean run came from the exact harness, or from a close local surrogate, simplify or reset before adding more features. Repeated parser warnings, recoverable decode errors, or the same clean replay result on one parser family are pivot signals, not progress signals.
6. After two clean runs on the same sink-state theory, or after one clean exact-harness run on a weak proxy-only theory, pivot instead of mutating cosmetic details.
7. If the candidate crashes the wrong place, prefer crash-matching refinement over broader search.
8. If an upstream patch, regression test, or shipped corpus artifact already yields an exact raw testcase for the real harness, stop exploring neighbors and submit it unless concrete local evidence contradicts the match.

## Interpreting Feedback
- Harness name or binary path: update your primary target model immediately.
- Clean execution: the testcase likely missed the required path or state; revisit framing and trigger conditions.
- Different crash location: same-component is not enough; re-check the vulnerable block and surrounding accesses.
- Format rejection or wrapper failure: simplify toward the raw bytes the harness actually consumes.
- Parser warnings or recoverable errors: if they repeat inside one parser family, treat them as wrong-path evidence unless your source-grounding checkpoint explains why the same family should still reach the sink.

## Finish Rule
You still must submit at least one best-effort candidate even if local reproduction is imperfect. Zero submissions is worse than a source-grounded attempt. The only exception is a concrete workspace blocker that prevents creating or submitting any file at all.
