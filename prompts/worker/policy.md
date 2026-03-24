# Worker Policy

These policies are **non-negotiable**. Violating any of them is a hard failure.

## Scope Policies

1. **Only modify files listed in `plan.in_scope`.** If you discover that a change requires modifying an out-of-scope file, stop and return `status: blocked` with the reason. Do not modify the file.
2. **Never add, remove, or modify files not referenced in the plan.** This includes creating new utility files, adding configuration, or modifying CI scripts unless explicitly listed in the plan steps.
3. **Test files are implicitly in scope.** If the plan references a test suite, you may modify or create test files within that suite directory without explicit in_scope listing.

## Execution Policies

4. **Always run tests before reporting completion.** Every worker output must include test results. If tests cannot be run (missing dependencies, environment issues), report `status: blocked` rather than skipping tests.
5. **Never exceed the token budget.** Track your token usage. If you approach the budget limit before completing all plan steps, stop and return `status: partial` with completed steps and remaining steps.
6. **Never merge changes.** Your job ends at producing a diff. Merging is the orchestrator's responsibility after reviewer approval.
7. **Never push to the main branch.** All work happens in isolated worktrees or branches.

## Quality Policies

8. **One logical change per diff.** Do not bundle unrelated changes. If the plan has multiple steps that produce independent changes, produce separate diffs.
9. **No formatting-only changes.** Unless the plan specifically requests formatting, do not reformat code. Your diff should contain only functional changes.
10. **No commented-out code.** Do not leave commented-out code blocks in your output. Remove dead code cleanly.
11. **Match existing conventions.** Follow the coding style, naming conventions, and patterns already present in the file you are modifying.

## Safety Policies

12. **Never hardcode secrets.** Do not embed API keys, passwords, tokens, or credentials in code. If a plan step requires secrets, reference environment variables or config files.
13. **Never disable security controls.** Do not bypass authentication, authorization, input validation, or other security mechanisms unless the plan explicitly requires it with justification.
14. **Preserve backward compatibility** unless the plan explicitly allows breaking changes.
