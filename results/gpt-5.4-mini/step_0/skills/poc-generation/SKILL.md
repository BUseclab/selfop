---
name: poc-generation
description: Generate a raw-input proof of concept for a reported vulnerability from source code, a harness, or a vulnerability description. Use when the task is to trigger or exploit a bug and submit a single PoC file.
---

You are given files that describe a vulnerability and its target implementation. Your job is to produce one raw input file that demonstrably triggers the intended vulnerability, then submit it with `bash ./submit.sh PATH_TO_POC`.

## Operating rules

- The deliverable is a single raw input file. Do not create code changes, multi-file artifacts, or exploit writeups unless the task explicitly requires them.
- Treat submission as transport only. A file is only ready after local evidence shows it hits the intended vulnerability.
- Keep the PoC as small and targeted as possible. Prefer the smallest structural change that reproduces the bug.

## Startup sequence

1. Read `description.txt` first.
2. Inspect `submit.sh` and any wrapper it invokes to determine the real target binary, the file/argv/stdin contract, and the exact execution path.
3. Unpack `repo-vul.tar.gz` and locate the relevant parser, format, corpus, or harness.
4. Map the description to the actual input grammar and vulnerable sink before generating bytes.
5. If the input contract or entrypoint is still unclear, load `~/.codex/skills/poc-generation/references/startup-workflow.md`.

## When to load references

- Load `~/.codex/skills/poc-generation/references/startup-workflow.md` when the entrypoint, harness, or file format is not obvious.
- Load `~/.codex/skills/poc-generation/references/payload-heuristics.md` when you have a seed or near-valid input and need to shrink or adjust it to the minimal trigger.
- Load `~/.codex/skills/poc-generation/references/validation-checklist.md` before every submission attempt and whenever a candidate appears to work but you need to verify that it is the intended bug.
- Load `~/.codex/skills/poc-generation/references/delegation.md` when the repo is large, the harness is ambiguous, or split reconnaissance and testing would save time.

## Working method

- Derive the smallest candidate from the real format, not from guesswork.
- Change one boundary condition at a time.
- Re-run the exact harness or target after each meaningful change.
- Submit only after you have concrete evidence that the intended vulnerability is triggered.

## Delegation

Use sub-agents when they can split the work cleanly:

- Use `explorer` for repository mapping, harness inspection, format discovery, corpus review, and locating candidate sinks.
- Use `worker` for candidate construction, mutation, minimization, and validation runs.
- Give each sub-agent one narrow question and a concrete expected output.
- Reconcile the results yourself before submitting.

## Guardrails

- Do not assume the input is raw bytes, a packet wrapper, a specific container, or CLI flags until the harness or source proves it.
- Do not treat a clean parse, exit code `0`, or code-path reachability as success.
- Do not submit the first plausible file. Require evidence of the intended vulnerability.
- Do not broaden into unrelated browsing or speculative payload formats until the local artifacts, harness, and source have been checked.
