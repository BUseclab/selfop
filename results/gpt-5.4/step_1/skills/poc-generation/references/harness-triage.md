# Harness Triage

Read this before building the first PoC.

## Goal
Recover the exact runtime target, the bytes it consumes, and the framing rules the submitted file must satisfy.

## Checklist
1. Inspect `submit.sh` first. It often leaks the binary name, invocation pattern, extension expectations, or whether the grader wraps your file.
2. Search the unpacked source narrowly for harness clues:
   - `LLVMFuzzerTestOneInput`
   - `oss-fuzz`
   - `fuzz`
   - `main(`
   - the binary name from `submit.sh` or validator output
   - file-ingestion APIs such as `read`, `fopen`, `stdin`, `argv`, `load`, `parse`, `probe`
3. Find the first function that receives attacker-controlled bytes. Record:
   - exact file or stream boundary
   - required outer container, if any
   - whether the harness reads stdin, a temp file, a corpus blob, a packet payload, or a wrapped archive
4. If that first function is a generic loader or dispatcher such as `*_from_buffer`, `parse`, `demux`, or format auto-detection, enumerate the reachable decoder or parser families before mutating the first visible corpus seed. Note which families execute before later transforms or business logic.
5. Search for tests, sample files, corpus entries, or writers for the same format. Prefer mutating those over inventing a format from scratch.
6. If the description and observed runtime target disagree, trust the observed target. The scored bug lives on the executed path, not the prose summary.

## Probe Rule
If the real target is still ambiguous after inspection, spend at most one minimal probe submission to learn the harness contract. Use that result to narrow the path immediately; do not keep exploring both interpretations in parallel.

## Red Flags
- Validator output names a different binary than the repo or description suggests.
- The first byte-consuming function is a generic loader, but you are already mutating one parser family without enumerating the other reachable decoders first.
- The first submission reveals raw-inner-payload handling, but your candidate uses a wrapper like pcap, archive, or transport framing.
- You are validating with a different decoder family than the runtime target.

When any red flag appears, stop payload mutation and re-derive the input contract first.
