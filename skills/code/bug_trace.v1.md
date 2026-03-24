---
id: bug_trace_v1
name: Bug Trace
version: "1.0"
domain: code
scope: cross_module
triggers:
  - bug
  - regression
  - error
  - fix
  - crash
  - traceback
  - exception
agent_role: worker
allowed_tools:
  - codegraph_query
  - file_read
  - file_write
  - git_diff
  - git_log
  - test_runner
  - ast_grep
  - debugger
inputs:
  - task_packet: "Bounded plan from planner including bug description, reproduction steps, and suspected area"
  - error_output: "Stack trace, error message, or failing test output"
  - codegraph_snapshot: "Current codegraph index for the affected area"
outputs:
  - root_cause: "Explanation of the root cause with file, line, and symbol references"
  - diff: "Unified diff of the fix"
  - test_results: "Full test output confirming the fix and no regressions"
  - regression_test: "New or updated test that covers the bug scenario"
definition_of_done:
  - Bug is reproducible before the fix
  - Root cause is identified with codegraph-verified symbol references
  - Fix addresses the root cause (not a symptom)
  - A regression test exists that fails without the fix and passes with it
  - All pre-existing tests pass
  - No out-of-scope files modified
failure_modes:
  - cannot_reproduce: "The bug cannot be reproduced in the current environment"
  - wrong_root_cause: "The fix addresses a symptom rather than the actual cause"
  - incomplete_fix: "The fix resolves the reported case but misses related edge cases"
  - test_regression: "The fix breaks previously-passing tests"
  - scope_violation: "Files outside the declared scope were modified"
validators:
  - type: reproduction
    description: "Confirm the bug reproduces before the fix is applied"
  - type: test_pass
    command: "pytest {{test_suite}} --tb=short"
  - type: regression_test
    description: "New test fails on the pre-fix code and passes on the post-fix code"
  - type: lint_clean
    command: "ruff check {{changed_files}}"
  - type: scope_check
    description: "Verify diff only touches files listed in plan.in_scope"
estimated_tokens: 18000
---

# Bug Trace

## When to Use

Use this skill when the task involves **diagnosing and fixing** a bug, including:

- Runtime errors (exceptions, crashes, unexpected behavior)
- Test regressions (a previously-passing test now fails)
- Logic errors reported by users or QA
- Performance regressions with a clear behavioral symptom

Do **not** use this skill for:

- Feature requests or enhancements (use a feature skill)
- Refactoring without a bug (use safe_refactor)
- Flaky tests without a clear error (use a test_stabilize skill)

## Procedure

### 1. Reproduce the Bug

Before any investigation, confirm the bug is reproducible:

- If a failing test is provided, run it and capture the output:
  ```
  pytest {{failing_test}} --tb=long -v
  ```
- If reproduction steps are provided, execute them in the sandbox environment.
- If the bug cannot be reproduced, **stop and report** `status: blocked` with `reason: cannot_reproduce`. Include the exact steps attempted and environment details.

Record the reproduction output as `pre_fix_evidence`.

### 2. Trace the Call Path

Starting from the error location (stack trace top or failing assertion):

1. **Identify the failing symbol** -- resolve it in the codegraph:
   ```
   codegraph_query --symbol "{{failing_symbol}}" --fields fqn,file,line_range,kind
   ```

2. **Walk the call chain** -- for each frame in the stack trace (or each step in the logic flow), resolve the caller:
   ```
   codegraph_query --callers "{{current_symbol}}" --fields fqn,file,line,context
   ```

3. **Inspect data flow** -- at each step, read the relevant code to understand what values are being passed and where they diverge from expectations.

4. **Check recent changes** -- query git history for the affected files:
   ```
   git log --oneline -20 -- {{affected_files}}
   ```
   Look for recent commits that could have introduced the regression.

Build a `call_path_trace` documenting each step from symptom to root cause.

### 3. Identify the Root Cause

The root cause must be:

- A specific code location (file, line, symbol)
- Verified via codegraph (not guessed from file names or comments)
- Explained in terms of **why** the code is wrong, not just **what** is wrong

Common root cause categories:

- **Missing null/boundary check**: A value can be None/empty but is not guarded
- **Incorrect logic**: A conditional, comparison, or arithmetic expression is wrong
- **Stale reference**: A symbol was renamed/moved but a reference was not updated
- **Type mismatch**: A function receives or returns an unexpected type
- **Concurrency issue**: A race condition or missing synchronization
- **Configuration error**: An environment variable, config key, or default is wrong

Document the root cause in the output packet with codegraph references.

### 4. Apply the Fix

Write the minimal fix that addresses the root cause:

- Change only the code necessary to fix the bug.
- Do not refactor surrounding code (request a separate refactor task if needed).
- Do not change formatting or style in unrelated lines.

If the fix requires changes in multiple files, verify each file is within `plan.in_scope`. If any file is out of scope, **escalate to the planner**.

### 5. Write a Regression Test

Create or update a test that:

- **Fails** when run against the pre-fix code (demonstrates the bug exists)
- **Passes** when run against the post-fix code (demonstrates the fix works)
- Covers the specific scenario described in the bug report
- Is placed in the appropriate test file for the affected module

### 6. Verify

Run the full validator suite:

1. **reproduction** -- confirm the bug reproduces before the fix
2. **test_pass** -- all tests pass after the fix (including the new regression test)
3. **regression_test** -- the new test fails without the fix, passes with it
4. **lint_clean** -- no new lint violations
5. **scope_check** -- diff only touches in-scope files

Collect all results into the output packet.

## Validation Checklist

Before returning the output packet, confirm each item:

- [ ] Bug was reproduced and `pre_fix_evidence` is recorded
- [ ] Call path traced through codegraph-resolved symbols
- [ ] Root cause identified with specific file, line, and symbol references
- [ ] Root cause explains **why** the code is wrong (not just what)
- [ ] Fix is minimal and addresses the root cause (not a symptom)
- [ ] No files outside `plan.in_scope` modified
- [ ] Regression test exists and validates the fix
- [ ] All pre-existing tests pass
- [ ] No new lint errors
- [ ] Git diff is clean and reviewable
- [ ] Token usage is within `estimated_budget_tokens`
