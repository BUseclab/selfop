# Environment Sanity

Use this when the local layout, build, runtime, or sanitizer setup looks misleading.

## Checks

- Confirm the top-level tree after unpacking the archive before broad repository search.
- Confirm the exact harness or target path from `submit.sh` before validating a candidate elsewhere.
- Confirm the helper utilities you expect to use are actually available before you rely on them.
- Run one minimal path or filesystem smoke check on the unpacked workspace and candidate artifact before broader validation.
- Confirm whether the target is using ASan, MSan, a custom runtime, or a plain build, and normalize the setup before you iterate.
- Confirm that any debug binary, helper, or local test harness is really the same target that `submit.sh` will use.

## When artifacts mislead

- If a seed corpus, regression test, or helper binary is missing or unhelpful, switch back to source-guided construction instead of wasting time on artifact hunting.
- If a local build does not link cleanly, stop and return to the exact submission target rather than validating against a different binary.
- If a runtime setting causes confusing sanitizer output, fix the environment first so the crash signal is interpretable.
- If the workspace path or unpacked layout is not what you expect, stop and repair the environment before changing the payload.

## Sanity checklist

1. Unpack.
2. Inspect layout.
3. Verify the helper utilities you need.
4. Identify the exact submit target.
5. Run a minimal path/filesystem smoke check.
6. Normalize runtime and sanitizer settings.
7. Validate the candidate on the exact target.
