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
3. Stop after one or two failed direct exact-id checks. If no artifact appears quickly, return to local source derivation instead of broad remote mining.
4. If an exact raw testcase or shipped regression seed for the same harness is found, prefer replaying or minimally adapting it over manual synthesis.
5. If only a patch is found, treat it as localization help, not proof of the scored crash site. Confirm whether the issue, testcase, or logs identify a different sink or later cleanup path.

## Boundaries
- This is a benchmark-linked lookup rule, not a general invitation to browse history.
- Do not replace exact-id lookup with keyword GitHub searches, search-engine scraping, guessed attachment URLs, repo cloning, or adjacent-issue browsing.
- Prefer project-native endpoints over search engines or generic HTML pages.
- If the response is only a generic HTML shell, sign-in scaffolding, or no-download issue page, count that as a failed direct check and stop rather than scraping more pages.
- Once local source already identifies the harness and sink, avoid unrelated GitHub/GitLab archaeology unless a specific public artifact is already known to exist.
- If a close replay shows only a semantic difference and not sink-state evidence, stop remote lookup and redesign validation around the vulnerable state transition.

## Submission Rule
If the public artifact is an exact testcase for the same harness and crash family, submit it promptly unless local evidence shows it mismatches the scored sink.
