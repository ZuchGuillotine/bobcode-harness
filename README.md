# BOBCODE

BOBCODE is a local-first agent harness for moving fast on software tasks without letting agent work drift. It gives coding agents a structured environment: repo intelligence, bounded planning, isolated worktrees, deterministic validation, browser evidence when needed, and a project-scoped learning loop.

The default operating model is simple: install BOBCODE, run `harness-ctl init` in a git repo, and submit tasks from that repo. No VPS, Telegram bot, or long-running remote service is required.

## What It Does

- Plans code changes with repo context from codegraph
- Executes changes in isolated git worktrees
- Reviews output through deterministic checks and reviewer passes
- Captures task state, progress, validation, and learning data under `.bobcode/`
- Uses a localhost-only browser daemon for UI verification when needed
- Keeps human approval and review in the CLI

## Architecture

```text
┌──────────────────────────────────────────────┐
│              ORCHESTRATOR                    │
│  intake → plan → execute → review → learn    │
└──────┬──────────────────┬────────────────────┘
       │                  │
  ┌────▼─────┐    ┌──────▼──────┐
  │ codegraph │    │  Browser    │
  │ repo map  │    │  evidence   │
  └────┬─────┘    └──────┬──────┘
       │                  │
  ┌────▼──────────────────▼────────────────────┐
  │          REPO-LOCAL STATE                   │
  │  .bobcode/tasks · sqlite · learning         │
  │  worktrees · progress.jsonl · feature list  │
  └────────────────────────────────────────────┘
```

## Quick Start

```bash
git clone https://github.com/ZuchGuillotine/bobcode-harness.git
cd bobcode-harness
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
npm install -g @optave/codegraph
```

Set at least one model provider key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

Initialize BOBCODE inside any git repo:

```bash
cd /path/to/your/repo
harness-ctl init .
harness-ctl doctor
```

Submit a task:

```bash
harness-ctl submit "refactor the auth module to use JWT tokens"
harness-ctl inbox
harness-ctl status TASK-001
```

## Repo-Local State

`harness-ctl init` creates `.bobcode/` in the target repo and adds it to `.git/info/exclude` so tracked files stay clean by default.

```text
your-repo/
├── .bobcode/
│   ├── bobcode.json          # local harness metadata
│   ├── feature_list.json     # explicit verifiable work items
│   ├── progress.jsonl        # append-only handoff log
│   ├── tasks/                # task manifests, plans, artifacts, evals
│   ├── sqlite/harness.db     # task/eval/failure state
│   ├── learning/             # project-scoped failure signals
│   ├── worktrees/            # isolated task worktrees
│   └── browser/              # browser daemon state and evidence
├── .codegraph/graph.db       # local code graph, ignored by default
└── AGENTS.md                 # optional, only with --assisted
```

## Core Commands

| Command | Purpose |
| --- | --- |
| `harness-ctl init [path]` | Initialize repo-local BOBCODE state |
| `harness-ctl doctor [path]` | Check git, `.bobcode`, codegraph, provider keys, and browser daemon files |
| `harness-ctl submit "task"` | Run the task through the local orchestrator |
| `harness-ctl inbox` | Show tasks that need operator attention |
| `harness-ctl status [TASK-ID]` | Inspect task state and validation results |
| `harness-ctl approve TASK-ID` | Record local approval |
| `harness-ctl reject TASK-ID --reason "..."` | Record local rejection |
| `harness-ctl register /repo` | Optional global multi-project registration |

## Task Lifecycle

```text
INTAKE
  → PLAN
  → EXECUTE
  → INITIAL REVIEW
  → WORKER FIX
  → FINAL REVIEW
  → DONE | RETRY | LEARN
```

Every task gets a manifest, plan, artifacts, validation output, and learning record. Failed or retried work is classified so future tasks can improve skill routing, retrieval, and validation.

## Repo Intelligence

BOBCODE uses local codegraph queries as the main low-token retrieval primitive:

- symbol lookup
- callers/callees
- impact analysis
- candidate tests
- semantic search
- complexity and dependency checks

Codegraph is part of the normal path. `--skip-codegraph` exists only for degraded local setup.

## Browser Feedback

For UI tasks, BOBCODE can use a localhost-only browser daemon:

- navigate local dev servers
- capture page snapshots with stable refs
- click/type through flows
- collect console and network failures
- attach screenshots as validation evidence

Browser runtime state stays under `.bobcode/browser/`.

## Learning Loop

BOBCODE records project-scoped learning signals after validation:

- `plan_quality`
- `execution_error`
- `test_failure`
- `boundary_violation`
- `review_rejected`
- `final_review_rejected`
- `worker_fix_failed`
- `budget_exceeded`

The first goal is local usefulness: make this repo and each target repo faster and more reliable over time. Cross-project sharing remains explicit through `harness-ctl feedback`.

## Design Principles

1. **Harness over prompt cleverness.** Improve tools, feedback loops, and state handoffs before adding prompt bulk.
2. **Progressive disclosure.** Give agents compact maps and specific retrieval tools, not giant context dumps.
3. **Repo as system of record.** Tasks, progress, validation, and learning live where agents can read them.
4. **Mechanical feedback.** Tests, lint, codegraph, browser evidence, and review passes catch problems early.
5. **Local by default.** Work in any repo without a remote service.

## Project Structure

```text
apps/orchestrator/       # LangGraph orchestrator, agents, stages, CLI
packages/
  config/                # runtime path resolution
  repo_intel/            # codegraph adapter and AGENTS.md parsing
  stage_manager/         # git worktree lifecycle
  browser_daemon/        # local browser feedback sidecar
  eval/                  # deterministic checks and promptfoo runner
  learning/              # failure classification and feedback export
  llm/                   # provider routing
skills/                  # versioned skills
prompts/                 # role prompts and output contracts
evals/                   # regression and adversarial evals
tests/                   # unit and integration tests
```

## Development

```bash
pytest tests/
ruff check .
```

BOBCODE intentionally keeps production actions human-gated. It can prepare, test, and review work, but it does not self-merge.
