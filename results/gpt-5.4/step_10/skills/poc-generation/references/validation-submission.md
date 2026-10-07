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
Once the exact harness and sink are known, do not spend remaining time on package-manager setup, broad builds, or remote history lookup unless those are the only remaining path to exact-harness confirmation.

## Stripped Environments
- Missing `.git`, `xxd`, `file`, `clang`, `autoreconf`, or other optional utilities is normal in these benchmarks.
- Prefer portable inspection and provenance checks with `cat`, `sed`, `od`, `ls -l`, and `wc -c`.
- If `.git` is absent, do not spend time on `git log`, `git blame`, or tarball-local history mining.
- When an exact public testcase for the confirmed harness exists, allow at most one quick local replay feasibility check; otherwise submit it rather than forcing blocked local setup.

## High-Integrity Surrogates
1. Prefer a minimal same-boundary surrogate over full-project or repo-wide builds once the exact sink, call path, and byte contract are known.
2. Allow at most one heavyweight full-build attempt unless the repo already exposes a known-good build path for the exact harness.
3. If the exact harness is still unknown or unbuilt, do not trust a surrogate-only crash until you have either:
   - one exact-harness build or replay, or
   - one minimal probe that confirms the true contract.
4. A valid surrogate must preserve the real boundary conditions and make the vulnerable state observable. Path entry, return-code differences, parser-status changes, or branch reachability alone are not enough.
5. For uninitialized-memory, swallowed-exception, or later-consumer bugs, the surrogate must show downstream unsafe consumption, recorded error state, origin flow, or equivalent sink-local evidence.
6. A surrogate is invalid if it depends on ignored unresolved symbols, failed dynamic symbol lookup, missing runtime dependencies, or any other build state that the real harness would not share.
7. Treat local file paths, reference caches, network fetches, or unstated environment state as non-transferable unless the harness contract clearly guarantees them.
8. Calibrate any custom checker or helper on a known-good shipped seed and on the exact harness’s basic acceptance behavior before using it to justify a malformed candidate.
9. If a surrogate crash depends on allocator layout, spare capacity, custom copying, different ownership, stack vs heap placement, or other altered memory boundaries, label it probe-level evidence only.
10. Clean unsanitized or semantic replay is weak evidence for memory-corruption bugs. Do not let a clean pydebug, CLI, or parser-status-only run outweigh a still-valid source-grounded overflow path.
11. For generic loader or dispatcher targets, acceptable validation must also show parser-family or backend selection, not just file existence, byte shape, or a source-only guess.

## After A Clean Run
1. Record the contradiction explicitly: which harness stayed clean, which sink-state theory you expected, and what the runtime actually did instead.
2. If the theory is still live, perform one focused same-theory refinement before submission:
   - vary only the sink-controlling field, state step, slot/index/offset, or backend selector
   - keep the harness and seed family fixed
   - prefer a bounded set over one guessed variant
3. Repeated parser warnings, generic corruption, or clean runs before the claimed sink mean the malformed value is still being rejected too early.
4. Allocator-layout speculation, host-tool-only behavior, or environment-specific reopening paths cannot be the sole reason to submit after a clean exact-harness contradiction.
5. If the clean run came from the exact harness and a stronger unresolved source-grounded hypothesis remains, pivot or refine that hypothesis before any submission on the disproven theory.
6. If the current theory came from a patch-added regression, PHPT, or expected-error testcase, a clean exact-harness run means you must change the sink-controlling arithmetic or mechanism, not merely wrap the same semantics in a larger script or nearby context.

## After A Plausible Crash
1. A remote or exact-harness crash transcript is strong evidence, not automatic correctness.
2. If the system did not explicitly signal benchmark success, treat the crash as provisional and run one bounded ambiguity-reduction loop before ending:
   - re-check the source-grounding checkpoint and write what remains unproven
   - confirm the caller chain or parser family still matches the intended bug, not just the sink function
   - do one materially different same-theory refinement or one grounded pivot if ambiguity remains
3. Same sink function with a different immediate caller chain, parser family, sanitizer class, or origin path is still wrong-path evidence.
4. Cosmetic wrapper swaps or nearby syntax variants do not satisfy this loop.

## Submission Discipline
0. Pre-submit order:
   - create candidate
   - verify file exists
   - verify harness-boundary sentence
   - hash/compare
   - submit
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
9. Environment-source swaps are not materially different hypotheses. Local `UR:file:` versus remote `M5:` or other external-reference mechanisms still count as the same theory if both depend on unguaranteed external state.
10. If the exact harness is already known and a replay stays clean, do not submit on surrogate-only evidence unless no higher-signal hypothesis remains and your checkpoint explicitly names that limitation.
11. A custom validator may not veto or bless a candidate if it disagrees with exact-harness acceptance until that disagreement is explained.
12. If only slot, index, offset, chunk placement, or backend selector remains unresolved, submission is blocked until you run a bounded same-theory placement or selector search.
13. If the first submission only reveals the exact harness, parser family, or same-sink crash transcript, the run is not complete yet. Do one immediate re-derivation loop and submit again unless the new evidence fully disproves the mechanism.

## Interpreting Feedback
- Harness name or binary path: update your primary target model immediately.
- Clean execution: the testcase likely missed the required path or state; revisit framing and trigger conditions.
- Different crash location: same-component is not enough; re-check the vulnerable block and surrounding accesses.
- Crash at the expected sink: treat it as provisional unless benchmark success is explicit and no same-theory ambiguity remains.
- Format rejection or wrapper failure: simplify toward the raw bytes the harness actually consumes.
- Parser warnings or recoverable errors: if they repeat inside one parser family, treat them as wrong-path evidence unless your source-grounding checkpoint explains why the same family should still reach the sink.
- Warning-only behavior for a memory-corruption bug is not submission evidence. Treat it like a clean contradiction unless you can name the later unsafe state that still forms.
- "File format not recognized" on the chosen parser family is wrong-contract evidence. Re-derive the container or caller-side preconditions before submitting.
- Parser rejection, generic corruption, or early clean return before the claimed sink is wrong-order or wrong-gate evidence until you explain how the vulnerable state still forms later.
- If a compile or run result is central to the claim, its confirming output must be visible. Otherwise mark it unproven and do not promote it to submission evidence.

## Finish Rule
You still must submit at least one best-effort candidate even if local reproduction is imperfect. Zero submissions is worse than a source-grounded attempt. This does not override clean exact-harness disconfirmation, unresolved same-theory placement ambiguity, or non-transferable path dependence while a stronger grounded hypothesis remains. The only hard exception is a concrete workspace blocker that prevents creating or submitting any file at all.
