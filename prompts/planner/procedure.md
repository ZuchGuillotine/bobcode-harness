# Planner Procedure

Follow these steps in order for every incoming task.

## Step 1: Read the Task Packet

Parse the incoming task and extract:

- **objective**: What needs to be accomplished
- **context**: Any provided background, error messages, or references
- **constraints**: Budget limits, deadlines, scope restrictions
- **requestor**: Who submitted the task (human or upstream agent)

If the task packet is incomplete or ambiguous, return immediately with `status: needs_clarification` and a list of specific questions.

## Step 2: Classify the Task

Determine the task type:

| Type | Indicators |
|------|-----------|
| `code_change` | Mentions files, functions, bugs, features, refactoring, tests |
| `marketing_campaign` | Mentions campaigns, audiences, channels, metrics, conversions |
| `content_creation` | Mentions blog posts, documentation, copy, assets |
| `mixed` | Contains elements of multiple types |

For `mixed` tasks, decompose into sub-tasks, each with a single type. Process each sub-task independently.

## Step 3: Gather Context

### For Code Tasks

1. **Locate the target** -- query the codegraph for the primary symbol, file, or module:
   ```
   codegraph_query --symbol "{{target}}" --fields fqn,file,line_range,kind,module
   ```

2. **Retrieve context** -- get the surrounding code and dependencies:
   ```
   codegraph_query --dependencies "{{target_fqn}}" --fields fqn,file,kind
   codegraph_query --callers "{{target_fqn}}" --fields fqn,file,line
   ```

3. **Retrieve impact** -- determine the blast radius:
   ```
   codegraph_query --dependents "{{target_fqn}}" --depth 2 --fields fqn,file,module
   ```

4. **Select tests** -- find the test files that cover the target:
   ```
   codegraph_query --tests-for "{{target_fqn}}" --fields file,test_name
   ```

### For Marketing Tasks

1. **Retrieve current metrics** -- query the analytics index for baseline data:
   ```
   metrics_query --source "{{channel}}" --period "last_30d" --fields impressions,clicks,conversions,spend
   ```

2. **Identify target audience** -- retrieve audience segments and their performance:
   ```
   audience_query --segment "{{target_segment}}" --fields size,engagement_rate,ltv
   ```

3. **Select skill** -- match the task to the appropriate marketing skill (campaign_launch, content_brief, audience_analysis).

## Step 4: Define Scope

Explicitly declare:

- **in_scope**: List of files, modules, symbols, or assets that may be modified
- **out_of_scope**: List of files, modules, symbols, or assets that must NOT be modified
- **dependencies**: External systems or services that the plan interacts with (read-only)

The scope must be as narrow as possible. When in doubt, exclude rather than include.

## Step 5: Propose Plan

Build the plan packet:

1. **Plan steps**: Ordered list of actions, each with:
   - `step_id`: Sequential identifier
   - `action`: What to do (e.g., "rename function X to Y in file Z")
   - `skill`: Which skill to invoke (e.g., `safe_refactor_v1`)
   - `inputs`: What the worker needs
   - `expected_output`: What success looks like
   - `evidence`: Codegraph query results or metric sources that justify this step

2. **Estimated budget**: Total token estimate across all steps (sum of skill `estimated_tokens` values plus overhead).

3. **Confidence**: Float 0.0-1.0 based on:
   - Symbol resolution success rate
   - Completeness of codegraph data
   - Clarity of task description
   - Complexity of the change

If confidence < 0.7, do NOT proceed. Return the partial plan with `status: needs_human_review`.

## Step 6: Return Bounded Plan Packet

Assemble the final output conforming to the output contract schema. Verify:

- All required fields are present
- All symbols are codegraph-verified
- `in_scope` and `out_of_scope` are populated
- `estimated_budget_tokens` does not exceed the task budget
- `confidence` is >= 0.7

Return the plan packet to the orchestrator for dispatch to a worker.
