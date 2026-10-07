# Provenance Pivot

Use this when the vulnerable path is already localized and the search is drifting into source history or external provenance.

## Goal

Stop broad history churn once the target sink, parser branch, or bug family is known, and switch to provenance that helps you converge faster.

## What to look for

- Upstream issues or bug reports that match the localized failure mode.
- Testcase IDs, regression inputs, or corpus entries tied to the same path.
- Fix commits or patch diffs that explain the exact boundary condition.
- Historical notes that confirm the smallest trigger shape or contract detail.

## What to stop doing

- Do not keep grepping git history once the localized path is already known.
- Do not keep searching for a better explanation if the current path already matches the sink and the candidate can be validated.
- Do not use provenance as a substitute for exact-target validation.

## Workflow

1. Record the localized sink or parser branch.
2. Ask whether upstream issues, testcase IDs, or fix commits can reduce uncertainty.
3. Pull only the smallest provenance artifact that clarifies the trigger or contract.
4. Return immediately to candidate construction and exact-target validation.

## Useful question

Ask: "What provenance artifact will help me confirm the exact trigger shape fastest?"

