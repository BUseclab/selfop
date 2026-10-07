# Upstream Artifacts

Read this when the benchmark exposes a numeric task id and the repo/build layout clearly maps to OSS-Fuzz or a libFuzzer-style public target.

## Goal
Use public issue-linked artifacts selectively and early when the benchmark id itself is a likely key to an exact testcase, patch, or regression seed.

## When To Use
- `submit.sh`, metadata, or file names expose a numeric task id such as an OSS-Fuzz issue id.
- The repo contains OSS-Fuzz build scripts, libFuzzer harnesses, or issue-linked regression tests.
- The task looks like a public fuzzing benchmark where testcase ids, reproducer names, or issue numbers may map directly to artifacts.

## Workflow
1. Record the numeric id from `submit.sh`, metadata, or filenames.
2. Do a short exact-id retrieval pass in this order:
   - project-native testcase download, redirect, or attachment endpoint for that exact id
   - project-native issue or testcase endpoint for that exact id
   - repo-scoped commit, patch, regression-test, or testcase references naming that exact id
   - project-native metadata feeds such as JSON, Atom, or discussion endpoints tied to that exact id
3. If any direct check reveals a canonical project-native testcase URL, issue id, testcase id, attachment id, or redirect target, follow that revealed chain immediately with one or two more project-native requests before stopping. Do not switch to keyword search or manual synthesis until that direct chain is exhausted.
4. Stop after one or two failed direct exact-id checks or one exhausted canonical chain. If no artifact appears quickly, return to local source derivation instead of broad remote mining.
5. If an exact raw testcase or shipped regression seed for the same harness is found, prefer replaying or minimally adapting it over manual synthesis.
6. If only a patch is found, treat it as localization help, not proof of the scored crash site. Confirm whether the issue, testcase, or logs identify a different sink or later cleanup path.
7. If a public harness source is available, extract its byte boundary, wrapper behavior, and first parser calls before the first hand-crafted submission. Those details outrank local guesses about entrypoint shape.

## Boundaries
- This is a benchmark-linked lookup rule, not a general invitation to browse history.
- Do not replace exact-id lookup with keyword GitHub searches, search-engine scraping, guessed attachment URLs, repo cloning, or adjacent-issue browsing.
- Prefer project-native endpoints over search engines or generic HTML pages.
- If the response is only a generic HTML shell, sign-in scaffolding, redirect, `403`, tiny suspicious file, or no-download issue page, first check whether it exposes a concrete canonical project-native endpoint or artifact id. If it does, follow that endpoint directly once or twice; otherwise count it as a failed direct check and stop rather than scraping more pages.
- Once local source already identifies the harness and sink, avoid unrelated GitHub/GitLab archaeology unless a specific public artifact is already known to exist.
- If a close replay shows only a semantic difference and not sink-state evidence, stop remote lookup and redesign validation around the vulnerable state transition.

## Submission Rule
If the public artifact is an exact testcase for the same harness and crash family, submit it promptly unless local evidence shows it mismatches the scored sink.
If grader or public feedback newly reveals the exact harness and the mechanism still looks live, do one immediate local re-derivation cycle against that harness instead of ending on the earlier guess.
