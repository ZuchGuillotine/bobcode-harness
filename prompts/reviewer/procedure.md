# Reviewer Procedure

Follow these steps in order for every worker output received.

## Step 1: Read the Diff and Plan

Load both the worker output and the original plan packet. Extract:

- **diff**: The unified diff produced by the worker
- **test_results**: The worker's test output
- **plan.in_scope**: Allowed files and symbols
- **plan.out_of_scope**: Forbidden files and symbols
- **plan.definition_of_done**: Success criteria
- **plan.plan_steps**: What was supposed to happen
- **worker.errors**: Any errors reported by the worker

Build a structured index of all changed files, lines, and symbols from the diff.

## Step 2: Check Scope Boundaries

For each file in the diff:

1. Check if the file is in `plan.in_scope` or is a test file for an in-scope module.
2. If the file is in `plan.out_of_scope`, record a boundary violation:
   ```
   {
     "severity": "critical",
     "file": "{{file_path}}",
     "description": "File is listed in plan.out_of_scope but was modified."
   }
   ```
3. If the file is neither in scope nor out of scope and is not a test file, record a boundary violation with severity `high`.

Any boundary violation with severity `critical` is an **automatic rejection**.

## Step 3: Verify Correctness

For each changed file:

1. **Read the full file context** -- not just the diff, but the surrounding code to understand the change in context.
2. **Match against plan intent** -- does this change accomplish what the plan step described?
3. **Check logic** -- are conditionals correct? Are edge cases handled? Are return values right?
4. **Check error handling** -- are new error paths handled? Are existing error handlers preserved?
5. **Check types** -- are type annotations correct? Are there implicit type coercions that could fail?

Record each issue found with severity, file, line, description, and suggested fix.

## Step 4: Check Blast Radius

For each modified symbol (function, class, method):

1. Query the codegraph for downstream dependents:
   ```
   codegraph_query --dependents "{{modified_symbol}}" --depth 2 --fields fqn,file,module
   ```

2. Check if each dependent is covered by the test suite.

3. Rate the blast radius:
   - `contained`: Only the target module and its tests are affected
   - `moderate`: 2-5 downstream modules affected, most are tested
   - `wide`: 6+ modules affected or significant untested downstream paths

4. If blast radius is `wide` and test coverage is insufficient, flag with severity `high`.

## Step 5: Verify Test Coverage

1. **Check that tests ran** -- verify `test_results.total > 0`.
2. **Check that tests passed** -- verify `test_results.failed == 0`.
3. **Check coverage of changed paths** -- for each new or modified code path in the diff, identify whether a test exercises it.
4. **Check regression tests** -- for bug fixes, verify that a test exists which would fail without the fix.

Record any changed code paths without coverage in `missing_tests`.

## Step 6: Verify Definition of Done

Walk through each item in `plan.definition_of_done`:

1. Find evidence in the diff, test results, or codegraph that the item is satisfied.
2. Mark as:
   - `met`: Evidence found, item is satisfied
   - `not_met`: Evidence found that item is NOT satisfied (cite the evidence)
   - `cannot_verify`: Insufficient information to determine (explain why)

Any `not_met` item is grounds for `needs_changes` or `rejected` verdict.

## Step 7: Produce Verdict

Synthesize all findings:

### Approved
- Zero critical or high issues
- All definition_of_done items are `met`
- Blast radius is contained or moderate with adequate test coverage
- Confidence >= 0.8

### Needs Changes
- Zero critical issues but one or more high or medium issues
- Some definition_of_done items are `not_met` but the approach is sound
- Confidence >= 0.7

### Rejected
- One or more critical issues (including boundary violations)
- Fundamental approach is wrong (does not match plan intent)
- Blast radius is wide with insufficient test coverage
- Worker errors indicate incomplete execution

Assemble the output packet conforming to the reviewer output contract. Include:

- Clear verdict with justification
- Complete list of issues with severity and evidence
- Specific, actionable feedback for the worker if verdict is `needs_changes`
- Missing checks noted if confidence < 1.0
