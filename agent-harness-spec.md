# BOBCODE Local Harness Spec

## Purpose

BOBCODE is a local-first software development harness for agent work. It should be easy to drop into any git repo, initialize local state, and run bounded tasks through a tight feedback loop.

The harness exists to reduce agent drift:

- compact repo orientation
- semantic graph retrieval
- explicit task and feature state
- isolated worktrees
- immediate validation
- durable handoffs between sessions
- project-scoped learning

## Non-Goals

- No default VPS deployment.
- No Telegram or chat-bot control plane.
- No autonomous merges.
- No massive platform layer before local task reliability is strong.

## Default Runtime

```text
target-repo/
  .bobcode/
    bobcode.json
    feature_list.json
    progress.jsonl
    tasks/
    sqlite/harness.db
    learning/
    worktrees/
    eval_outputs/
    browser/
  .codegraph/graph.db
```

`.bobcode/` and `.codegraph/` are ignored through `.git/info/exclude` by default.
`harness-ctl init --gitignore` also adds them to tracked `.gitignore` when a team
wants shared hygiene. `--agent-instructions` may create tracked `AGENTS.md` when
the operator wants repo-visible instructions for Claude, Codex, Gemini, or any
other active coding agent.

## CLI

| Command | Purpose |
| --- | --- |
| `harness-ctl init [path]` | Create local runtime files and build codegraph |
| `harness-ctl doctor [path]` | Verify repo readiness |
| `harness-ctl submit "task"` | Run a task in the current repo |
| `harness-ctl task new --agent-driven <slug> "task"` | Scaffold a task for the active external agent without invoking the LLM pipeline |
| `harness-ctl inbox [--json]` | Show tasks needing operator attention |
| `harness-ctl status [TASK-ID] [--json]` | Inspect one task or all tasks |
| `harness-ctl cg ...` | Stable codegraph wrapper with JSON and remediation hints |
| `harness-ctl approve/reject` | Record a human decision |

## Direct Agent Mode

BOBCODE should support two task paths:

1. **Harness-orchestrated:** `harness-ctl submit "task"` runs intake, planning,
   execution, review, and learning through BOBCODE.
2. **External-agent orchestrated:** `harness-ctl task new --agent-driven ...`
   creates the durable task state, plan skeleton, progress log, branch, and
   worktree that the currently active agent can use directly.

The external-agent path is intentionally generic. Claude-specific ergonomics are
allowed as aliases (`--claude-driven`), but the stable contract should not bind
BOBCODE to any one agent runtime.

All agent-facing commands should offer machine-readable output. Current required
JSON surfaces:

- `harness-ctl doctor --json`
- `harness-ctl status --json`
- `harness-ctl inbox --json`
- `harness-ctl task new --agent-driven ... --json`
- `harness-ctl cg <subcommand> --json`

## Agent Loop

```text
intake
  -> plan
  -> execute
  -> initial_review
  -> worker_fix
  -> final_review
  -> route_result
  -> done | retry | learn
```

The loop should preserve these contracts:

- Planner selects the smallest useful code subgraph.
- Worker changes files only inside the task worktree.
- Reviewer is read-only.
- Validation records machine-readable results.
- Learning classifies failures by cause.

## Agent-Computer Interface Improvements

Priority improvements:

1. Add `file_view(path, start, limit=100)` with line numbers.
2. Replace broad `file_write` use with line-bounded edit operations where possible.
3. Add capped search results with explicit narrowing instructions.
4. Normalize tool responses:
   - `status`
   - `summary`
   - `artifacts`
   - `next_actions`
5. Run lint/syntax checks immediately after edits.

## Repo Intelligence

Codegraph is the default retrieval layer. It should provide:

- symbol location
- local context
- impact analysis
- candidate tests
- dependency and boundary checks
- graph freshness status

When retrieval failures cluster, BOBCODE should rebuild codegraph automatically and record the failure pattern.

## Feature and Progress State

`feature_list.json` stores explicit verifiable work items:

```json
{
  "version": 1,
  "features": [
    {
      "id": "auth-refresh-flow",
      "description": "A user can refresh an expired token and continue the session",
      "steps": ["Start app", "Expire token", "Refresh", "Verify session continues"],
      "passes": false
    }
  ]
}
```

`progress.jsonl` stores session handoffs. Each entry should be small and factual:

```json
{"task_id":"TASK-001","status":"done","summary":"Updated CLI init flow","tests":["pytest tests/unit/test_cli_register_helpers.py"]}
```

## Browser Verification

The browser daemon is localhost-only by default and exists for user-visible feedback:

- snapshots
- screenshots
- click/type flows
- console errors
- network failures

UI tasks should not be marked complete without browser or equivalent end-to-end evidence when a local app can be run.

## Learning

Learning remains project-scoped first. BOBCODE records:

- skill selected
- model role
- validation result
- failure class
- retries
- test status
- review verdict

Cross-project export stays explicit and anonymized.
