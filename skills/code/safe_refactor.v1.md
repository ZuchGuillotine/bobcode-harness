---
id: safe_refactor_v1
name: Safe Refactor
version: "1.0"
domain: code
scope: single_module
triggers:
  - rename
  - extract
  - move
  - refactor
  - restructure
agent_role: worker
allowed_tools:
  - codegraph_query
  - file_read
  - file_write
  - git_diff
  - test_runner
  - ast_grep
inputs:
  - task_packet: "Bounded plan from planner including target symbol, operation type, and destination"
  - codegraph_snapshot: "Current codegraph index for the affected module"
  - test_suite: "Paths to relevant test files"
outputs:
  - diff: "Unified diff of all changes"
  - test_results: "Full test output (pass/fail/skip counts and logs)"
  - impact_report: "List of files and symbols affected by the refactor"
definition_of_done:
  - All references to the target symbol are updated
  - No new lint errors or type errors introduced
  - All pre-existing tests pass
  - No out-of-scope files modified
  - Diff is reviewable (no extraneous changes)
failure_modes:
  - missed_reference: "A caller or import was not updated, causing a NameError or ImportError"
  - scope_violation: "Files outside the declared scope were modified"
  - test_regression: "One or more previously-passing tests now fail"
  - circular_dependency: "The move introduced a circular import"
validators:
  - type: test_pass
    command: "pytest {{test_suite}} --tb=short"
  - type: lint_clean
    command: "ruff check {{changed_files}}"
  - type: type_check
    command: "pyright {{changed_files}}"
  - type: scope_check
    description: "Verify diff only touches files listed in plan.in_scope"
estimated_tokens: 12000
---

# Safe Refactor

## When to Use

Use this skill when the task requires **renaming**, **extracting**, or **moving** a symbol (function, class, method, constant, module) within a codebase. This includes:

- Renaming a function, class, variable, or file
- Extracting a block of code into a new function or class
- Moving a symbol from one module to another
- Splitting a large module into smaller ones

Do **not** use this skill for:

- Behavioral changes (use a feature or bugfix skill instead)
- Deleting dead code (use a cleanup skill)
- Changes that span more than one logical module without planner decomposition

## Procedure

### 1. Query the Codegraph

Resolve the target symbol in the codegraph to obtain its fully qualified name, file location, and line range.

```
codegraph_query --symbol "{{target_symbol}}" --fields fqn,file,line_range,kind
```

If the symbol cannot be resolved, **stop immediately** and return `status: failed` with `reason: symbol_not_found`.

### 2. Identify All Callers and References

Query the codegraph for every file that references the target symbol. This includes:

- Direct imports
- Call sites
- Type annotations
- Re-exports
- Test fixtures and assertions

```
codegraph_query --references "{{target_fqn}}" --fields file,line,context
```

Record the full list as `affected_files`.

### 3. Check Scope Boundaries

Compare `affected_files` against `plan.in_scope`. If any affected file falls outside scope:

- If the out-of-scope reference is a **test file**, include it (tests are always in scope for refactors).
- Otherwise, **stop and escalate** to the planner with the list of out-of-scope files that need updating.

### 4. Apply the Refactor Patch

Depending on the operation type:

- **Rename**: Update the symbol definition and all references in `affected_files`.
- **Extract**: Cut the target code block, create a new function/class, insert a call at the original location, and update any local references.
- **Move**: Remove the symbol from the source module, add it to the destination module, update all imports in `affected_files`, and add a re-export at the source if the plan requires backward compatibility.

Write changes using `file_write`. Produce a unified diff after all writes.

### 5. Run Tests

Execute the test suite specified in the task packet:

```
pytest {{test_suite}} --tb=short -q
```

- If all tests pass, proceed to verification.
- If any test fails, attempt **one** automatic fix cycle: read the failure, trace it to a missed reference, fix it, and re-run. If the second run still fails, **stop and report failure**.

### 6. Verify

Run the full validator suite:

1. **test_pass** -- all tests green
2. **lint_clean** -- no new lint violations
3. **type_check** -- no new type errors
4. **scope_check** -- diff only touches in-scope files (plus tests)

Collect all validator results into the output packet.

## Validation Checklist

Before returning the output packet, confirm each item:

- [ ] Target symbol resolved via codegraph (not guessed)
- [ ] All callers and references identified and updated
- [ ] No files outside `plan.in_scope` modified (except tests)
- [ ] Diff contains only refactor-related changes (no formatting, no unrelated fixes)
- [ ] All pre-existing tests pass
- [ ] No new lint errors
- [ ] No new type errors
- [ ] No circular dependencies introduced
- [ ] Impact report lists every changed file and symbol
- [ ] Token usage is within `estimated_budget_tokens`
