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
2. Check whether that exact id maps to a public issue, testcase, patch, or regression seed before hand-authoring a PoC.
3. If an exact raw testcase or shipped regression seed for the same harness is found, prefer replaying or minimally adapting it over manual synthesis.
4. If only a patch is found, treat it as localization help, not proof of the scored crash site. Confirm whether the issue, testcase, or logs identify a different sink or later cleanup path.
5. If no direct artifact is found quickly, return to local source derivation. Do not turn this into broad issue or history mining.

## Boundaries
- This is a benchmark-linked lookup rule, not a general invitation to browse history.
- Once local source already identifies the harness and sink, avoid unrelated GitHub/GitLab archaeology unless a specific public artifact is already known to exist.
- If a close replay shows only a semantic difference and not sink-state evidence, stop remote lookup and redesign validation around the vulnerable state transition.

## Submission Rule
If the public artifact is an exact testcase for the same harness and crash family, submit it promptly unless local evidence shows it mismatches the scored sink.
