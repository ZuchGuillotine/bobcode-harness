---
id: review_diff_v1
name: Review Diff
version: "1.0"
domain: code
scope: read_only
triggers:
  - review
  - check
  - verify
  - audit
  - inspect
agent_role: reviewer
allowed_tools:
  - codegraph_query
  - file_read
  - git_diff
  - test_runner
inputs:
  - diff: "Unified diff to review"
  - plan: "Original plan packet from the planner (includes in_scope, out_of_scope, definition_of_done)"
  - test_results: "Test output from the worker"
outputs:
  - verdict: "approved | rejected | needs_changes"
  - issues: "List of issues found, each with severity, file, line, and description"
  - boundary_violations: "List of out-of-scope changes detected"
  - missing_tests: "List of changed code paths that lack test coverage"
  - confidence: "Float 0.0-1.0 indicating reviewer confidence in the verdict"
  - summary: "Human-readable summary of the review"
definition_of_done:
  - Every changed file in the diff has been read and analyzed
  - All boundary violations are flagged
  - All missing test coverage is flagged
  - Blast radius has been assessed
  - Verdict is supported by specific evidence
failure_modes:
  - incomplete_review: "Not all changed files were inspected"
  - false_positive: "An issue was flagged that is not actually a problem"
  - missed_issue: "A real problem in the diff was not detected"
  - scope_confusion: "Reviewer misidentified in-scope vs out-of-scope files"
validators:
  - type: coverage_check
    description: "Every file in the diff was read and analyzed"
  - type: dod_check
    description: "Each item in definition_of_done was explicitly verified"
estimated_tokens: 8000
---

# Review Diff

## When to Use

Use this skill as a **pre-completion review** before any worker output is accepted. This is the final quality gate. Use it when:

- A worker has produced a diff that needs verification
- A plan has been executed and the output needs sign-off
- A human requests a review of pending changes
- Automated checks pass but human-level reasoning is needed

This skill operates in **read-only mode**. The reviewer never modifies code.

## Procedure

### 1. Read the Diff

Parse the unified diff and build a structured list of changes:

- For each file in the diff, record:
  - File path
  - Lines added / removed / modified
  - Symbols affected (functions, classes, variables)
  - Whether the file is in `plan.in_scope`

If the diff is empty or malformed, return `verdict: rejected` with `reason: invalid_diff`.

### 2. Check Scope Boundaries

Compare every changed file against `plan.in_scope` and `plan.out_of_scope`:

- **In-scope files modified**: Expected. Proceed with content review.
- **Out-of-scope files modified**: Flag as a `boundary_violation` with severity `high`.
- **In-scope files NOT modified**: Check if the plan expected changes to these files. If so, flag as `missing_change` with severity `medium`.

Record all boundary violations in the output.

### 3. Analyze Change Quality

For each changed file, verify:

#### Correctness
- Do the changes match the intent described in the plan?
- Are new code paths logically correct?
- Are edge cases handled (null checks, empty collections, boundary values)?
- Are error conditions handled appropriately?

#### Consistency
- Do the changes follow existing code conventions in the file?
- Are naming conventions consistent with the codebase?
- Are imports organized according to project standards?

#### Safety
- Are there any new security concerns (hardcoded secrets, SQL injection, path traversal)?
- Are there any new performance concerns (N+1 queries, unbounded loops, large allocations)?
- Are there any concurrency concerns (race conditions, deadlocks)?

Flag each issue with:
- `severity`: critical | high | medium | low | info
- `file`: affected file path
- `line`: line number in the diff
- `description`: clear explanation of the problem
- `suggestion`: recommended fix (if applicable)

### 4. Check Blast Radius

Assess the broader impact of the changes:

1. **Query downstream dependents** -- for each modified symbol, find its callers:
   ```
   codegraph_query --callers "{{modified_symbol}}" --fields fqn,file,line
   ```

2. **Identify untested impact** -- cross-reference callers against the test results. Flag any caller that is not exercised by the test suite.

3. **Rate blast radius**:
   - `contained`: Changes affect only the target module and its direct tests
   - `moderate`: Changes affect 2-5 downstream modules
   - `wide`: Changes affect 6+ downstream modules or public API surfaces

### 5. Check Test Coverage

For each changed code path:

1. Verify that a test exists which exercises the new or modified logic.
2. Check that the test is meaningful (not a trivial assertion or a duplicate).
3. For bug fixes, verify that a regression test exists.

Record any changed code paths without test coverage in `missing_tests`.

### 6. Verify Definition of Done

Walk through each item in `plan.definition_of_done` and explicitly verify:

- Mark each item as `met`, `not_met`, or `cannot_verify`.
- For `not_met` items, provide specific evidence.
- For `cannot_verify` items, explain what is missing.

### 7. Produce Verdict

Based on the analysis:

- **approved**: No critical or high issues. All definition_of_done items met. Blast radius is contained or moderate with adequate test coverage.
- **needs_changes**: Medium issues exist, or some definition_of_done items are not met, but the overall approach is sound.
- **rejected**: Critical issues exist, boundary violations found, blast radius is wide without adequate tests, or the changes do not match the plan intent.

Set `confidence` based on how thoroughly the review could be conducted:
- `>= 0.9`: Full codegraph access, all files read, all tests verified
- `0.7 - 0.9`: Most files read, some codegraph queries succeeded
- `< 0.7`: Incomplete review -- escalate to human

## Validation Checklist

Before returning the output packet, confirm each item:

- [ ] Every file in the diff was read and analyzed
- [ ] All boundary violations are documented
- [ ] Change quality assessed for correctness, consistency, and safety
- [ ] Blast radius rated and downstream impact assessed
- [ ] Missing test coverage identified for all changed code paths
- [ ] Every definition_of_done item explicitly verified
- [ ] Verdict is supported by specific evidence (not intuition)
- [ ] Confidence score reflects the thoroughness of the review
- [ ] Summary is clear and actionable for the worker or human
- [ ] No code was modified (read-only operation)
