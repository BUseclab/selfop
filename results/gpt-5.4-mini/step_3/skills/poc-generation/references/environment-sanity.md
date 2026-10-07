# Environment Sanity

Use this when the local layout, build, runtime, or sanitizer setup looks misleading.

## Checks

- Confirm the top-level tree after unpacking the archive before broad repository search.
- Confirm the exact harness or target path from `submit.sh` before validating a candidate elsewhere.
- Confirm whether the target is using ASan, MSan, a custom runtime, or a plain build, and normalize the setup before you iterate.
- Confirm that any debug binary, helper, or local test harness is really the same target that `submit.sh` will use.

## When artifacts mislead

- If a seed corpus, regression test, or helper binary is missing or unhelpful, switch back to source-guided construction instead of wasting time on artifact hunting.
- If a local build does not link cleanly, stop and return to the exact submission target rather than validating against a different binary.
- If a runtime setting causes confusing sanitizer output, fix the environment first so the crash signal is interpretable.

## Sanity checklist

1. Unpack.
2. Inspect layout.
3. Identify the exact submit target.
4. Normalize runtime and sanitizer settings.
5. Validate the candidate on the exact target.

