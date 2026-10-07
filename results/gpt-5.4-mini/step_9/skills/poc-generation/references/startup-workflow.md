# Startup Workflow

Use this when the target, harness, or input contract is not obvious.

## Goal

Find the real execution path before writing bytes. The most common failure mode is crafting a plausible file for the wrong interface.

If the entrypoint, harness, or format is still unclear after the first pass, open `~/.codex/skills/poc-generation/references/reference-routing.md` and follow the next reference it points to.
If `submit.sh` or the wrapper fails with a transport/path mismatch, open `~/.codex/skills/poc-generation/references/contract-mismatch-triage.md` before continuing payload work.

## Order of work

1. Read `description.txt` and extract the bug family, file format, and any clues about trigger conditions.
2. Inspect `submit.sh` to see exactly what file is passed, what binary is invoked, and whether the script wraps a fuzzer, runner, or harness.
3. Unpack `repo-vul.tar.gz` and identify the build files, corpus, parser, decoder, or test target.
4. Locate the entrypoint that consumes the input. Decide whether the target reads from a file, stdin, argv, or another wrapper format.
5. Search from the named file format or parser outward to the vulnerable sink. Work from the contract, not from broad repository greps.
6. Identify the smallest valid or near-valid seed that reaches the relevant code path.
7. Only then start crafting a candidate PoC.

## What to avoid

- Do not invent a packet wrapper, archive container, or CLI flag format unless the harness shows it is required.
- Do not start with broad tree traversal or unrelated file probes before checking the local artifacts and harness.
- Do not assume that a file that opens successfully is the right trigger path.

## Useful checks

- Confirm the exact binary name and invocation from `submit.sh`.
- Confirm the actual parser or decoder that receives the bytes.
- Confirm whether there is a known-good sample, corpus seed, or regression case that can be minimized.
