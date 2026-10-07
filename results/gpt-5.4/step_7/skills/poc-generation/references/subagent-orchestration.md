# Sub-Agent Orchestration

Read this when the task has ambiguous harnesses, large repos, or needs parallel format recovery and bug-path analysis.

## When To Delegate
- Multiple fuzzers, tests, or parser front doors appear in the first skim.
- The first byte-consuming function is a generic loader or dispatcher and several decoder families are reachable.
- Harness or entrypoint is unclear after the initial skim.
- The repo contains many fuzzers, tests, or parser front doors.
- You need both format recovery and vulnerable-path tracing.
- A local surrogate or testcase generator would help once the target is known.
- For numeric-id OSS-Fuzz tasks, prefer the exact-id artifact pass first; use the explorer if ambiguity remains after that short pass or if local front-door tracing still leaves multiple plausible harnesses.

## Required Setup
1. Call `tool_search` to discover the sub-agent tools.
2. Spawn at most one early `explorer` sub-agent and, only if needed later, one `worker` sub-agent.
3. Keep delegation shallow: sub-agents cannot spawn more agents.
4. Reading this file is not enough. Either spawn the `explorer` or write a one-line skip reason tied to a concrete fact such as "single harness already confirmed from [file] and no remaining ambiguity."
5. Built-in explorer delegation does not require a special user request. Do not invent an approval requirement.

## Explorer Job
Use an `explorer` sub-agent early with a narrow, read-only brief:
- locate the executed harness or binary
- identify the exact raw input boundary
- identify the earliest acceptance gate on the executed path
- find seed corpus files, tests, sample inputs, or format writers
- enumerate reachable decoder or parser families when the harness dispatches generically
- trace the vulnerable call chain from harness entry to sink
- report the highest-signal files and constraints only
- cite at least one concrete file or boundary fact that justifies the recommended next step

While the explorer runs, the main agent should read `description.txt`, inspect the vulnerable block, and prepare one or two concrete trigger hypotheses.

## Worker Job
Use a `worker` sub-agent only after the target and format are known. Good worker tasks:
- build a minimal local surrogate for the same parser path
- generate a candidate file from a known-good seed plus controlled mutations
- script a deterministic layout transformation or checksum fixup
- decode a chunked or repeated-response seed corpus and enumerate plausible slot/index placements
- map backend or selector-dependent seed variants when parser-family choice is the last unknown

Do not send the worker on open-ended repo exploration.

## Merge Rules
- Treat the explorer’s harness findings as authoritative input to your next step.
- Before continuing adjacent analysis, cite at least one concrete explorer finding or the skip reason.
- A valid skip reason must name the exact confirmed harness file and why the remaining plausible front doors cannot reach the sink.
- If the worker’s output crashes a different path than intended, feed that back into trigger re-derivation instead of submitting immediately.
- Close the loop in the main agent: create the final PoC file and run `bash ./submit.sh <poc>`.
