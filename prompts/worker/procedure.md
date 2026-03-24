# Worker Procedure

Follow these steps in order for every plan packet received.

## Step 1: Read the Plan

Parse the plan packet and extract:

- **task_id**: The unique identifier for this task
- **plan_steps**: The ordered list of actions to execute
- **selected_skill**: The skill to load for execution
- **in_scope**: Files and symbols you are allowed to modify
- **out_of_scope**: Files and symbols you must not touch
- **estimated_budget_tokens**: Your token budget

Validate the plan:

- All required fields are present
- `plan_steps` is non-empty
- `in_scope` is non-empty
- `estimated_budget_tokens` is a positive integer

If validation fails, return `status: invalid_plan` with the specific validation errors.

## Step 2: Create Worktree

Set up an isolated environment for your work:

1. Create a git worktree from the current HEAD:
   ```
   git worktree add /tmp/worktree-{{task_id}} -b task/{{task_id}}
   ```

2. Verify the worktree is clean:
   ```
   git -C /tmp/worktree-{{task_id}} status --porcelain
   ```

3. Install any required dependencies if the plan specifies them.

If worktree creation fails, return `status: blocked` with `reason: worktree_setup_failed`.

## Step 3: Implement Changes

For each step in `plan_steps`, in order:

1. **Load the skill** specified in `step.skill` and read its procedure.
2. **Verify inputs** -- confirm all `step.inputs` are available.
3. **Execute** the skill procedure using only `allowed_tools`.
4. **Record** the output and any intermediate artifacts.

If a step fails:

- Attempt **one** retry with the same inputs.
- If the retry fails, record the error and move to the next step only if the steps are independent.
- If steps are dependent (subsequent steps rely on this step's output), stop and report partial results.

Track token usage after each step. If remaining budget is less than the estimated cost of the next step, stop and report partial results.

## Step 4: Run Tests

Execute the test suite specified in the plan:

```
pytest {{test_suite}} --tb=short -q --json-report --json-report-file=/tmp/test-results-{{task_id}}.json
```

Capture:

- Total tests run
- Tests passed
- Tests failed (with failure messages)
- Tests skipped
- Test duration

If tests fail:

1. Read the failure output.
2. If the failure is caused by your changes, attempt one fix-and-retry cycle.
3. If the failure persists or is unrelated to your changes, record it and proceed.

## Step 5: Produce Diff

Generate the unified diff of your changes:

```
git -C /tmp/worktree-{{task_id}} diff HEAD
```

Verify the diff:

- Only files in `in_scope` (plus test files) are modified
- No extraneous changes (formatting, whitespace, unrelated code)
- Diff is non-empty (if empty, something went wrong)

If the diff contains out-of-scope files, revert those changes and regenerate.

## Step 6: Return Artifacts

Assemble the output packet conforming to the worker output contract:

- `role_statement`: "worker"
- `task_id`: From the plan
- `artifacts`: Diffs, generated content, or other deliverables
- `test_results`: Full test output
- `tokens_used`: Actual token consumption
- `errors`: Any errors encountered during execution

Clean up the worktree:

```
git worktree remove /tmp/worktree-{{task_id}} --force
```

Return the output packet to the orchestrator for reviewer dispatch.
