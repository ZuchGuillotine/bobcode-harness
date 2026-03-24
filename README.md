# Agent Harness

A self-improving agent harness for software development and marketing automation. The harness wraps LLM-powered agents with structured orchestration, repo intelligence, deterministic evaluation, and human-in-the-loop gating.

## What It Does

- **Plans** code changes and marketing campaigns using frontier models (Opus 4.6)
- **Executes** plans in isolated git worktrees with sandboxed file/shell access (Sonnet 4.6)
- **Reviews** output for correctness, boundary violations, and blast radius
- **Learns** from failures to improve skills and prompts over time
- **Traces** every action for observability (Phoenix + OpenTelemetry)
- **Gates** all production actions behind human approval (Telegram bot)

## Architecture

```
┌──────────────────────────────────────────────┐
│           ORCHESTRATOR (LangGraph)            │
│  Planner ←→ Worker ←→ Reviewer               │
│  Budget Enforcer ←→ Task Router               │
└──────┬──────────────────┬────────────────────┘
       │                  │
  ┌────▼─────┐    ┌──────▼──────┐
  │ codegraph │    │  Marketing   │
  │ per-repo  │    │  Adapter     │
  └────┬─────┘    └──────┬──────┘
       │                  │
  ┌────▼──────────────────▼────────────────────┐
  │           SHARED STATE LAYER                │
  │  SQLite · Phoenix · Git · Telegram          │
  └────────────────────────────────────────────┘
```

### Model Routing

| Role | Model | Route | Cost |
|------|-------|-------|------|
| Planner | Opus 4.6 | Claude Code CLI | Max subscription |
| Worker | Sonnet 4.6 | Anthropic API | API credits |
| Reviewer | Sonnet 4.6 | Anthropic API | API credits |
| Lightweight | GPT-5.4-mini | OpenAI API | Cheapest |

The planner routes through Claude Code CLI to use your Max subscription for expensive Opus calls. All other roles use the API with automatic fallback.

## Quick Start

### 1. Install the Harness

```bash
git clone https://github.com/ZuchGuillotine/bobcode-harness.git
cd agent-harness
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install -g @optave/codegraph
```

### 2. Configure

```bash
cp config/harness.yaml.example config/harness.yaml
# Edit with your settings

# Set API keys
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...

# Authenticate Claude Code (for Max plan routing)
claude auth login
```

### 3. Register a Project

```bash
harness-ctl register /path/to/your/project
```

This creates:
- `AGENTS.md` in the project root (project metadata for agents)
- `.harness/` directory for project-specific state (add to `.gitignore`)
- Codegraph dependency graph (`.codegraph/graph.db`)

### 4. Submit a Task

```bash
harness-ctl submit "refactor the auth module to use JWT tokens" --project my-project
```

Or via Telegram:
```
/task "refactor the auth module to use JWT tokens"
```

### 5. Monitor

- **Phoenix UI**: `http://your-server/phoenix/` — traces, latency, cost
- **Telegram**: `/status`, `/budget` — task status and spend
- **CLI**: `harness-ctl status`, `harness-ctl list`

## Using the Harness with Your Projects

The harness is a **tool that manages projects**, not a framework you embed. Your project repos stay clean — the harness operates on them from the outside.

### How It Works

```
agent-harness/                    ← Installed once on your VPS
├── apps/orchestrator/            ← Core orchestration logic
├── packages/                     ← Shared packages (LLM, state, eval)
├── skills/                       ← Base skill library
├── prompts/                      ← Agent personas
├── config/
│   ├── harness.yaml              ← Global config
│   ├── model_routing.yaml        ← LLM routing
│   └── projects/                 ← Per-project config overrides
│       ├── my-app.yaml
│       └── marketing-site.yaml
└── data/
    └── projects/                 ← Per-project state (isolated)
        ├── my-app/
        │   ├── tasks/            ← Task history
        │   ├── sqlite/           ← Eval results, failures
        │   └── learning/         ← Skill improvement data
        └── marketing-site/
            ├── tasks/
            ├── sqlite/
            └── learning/

~/projects/my-app/                ← Your project (untouched)
├── AGENTS.md                     ← Project metadata for agents
├── .codegraph/graph.db           ← Dependency graph (gitignored)
├── .gitignore                    ← Includes .codegraph/, .harness/
└── src/                          ← Your code
```

### Key Principles

1. **Your project repo stays clean.** The harness writes only `AGENTS.md` (committed) and `.codegraph/` (gitignored) to your project. All task state, learning data, and eval results live in the harness's `data/projects/` directory.

2. **Per-project isolation.** Each project gets its own SQLite database, task history, learning data, and codegraph. Improvements learned from project A don't leak into project B unless you explicitly share skills.

3. **Per-project config.** Override model routing, budget limits, skills, and prompts per project. A high-stakes production repo might use Opus for all roles; a side project might use only GPT-5.4-mini.

4. **Base skills + project skills.** The harness ships with base skills (safe_refactor, bug_trace, review_diff). Projects can define additional skills in `AGENTS.md` or in a `skills/` directory within the project repo.

5. **Worktrees for safety.** The harness never modifies your main branch directly. All changes happen in isolated git worktrees. You review and merge.

### AGENTS.md

Every managed project has an `AGENTS.md` at its root. This is the contract between your project and the harness:

```markdown
# AGENTS.md

## Project: my-app
## Language: Python
## Build: pip install -e .
## Test: pytest tests/
## Lint: ruff check .

## Architecture
FastAPI backend with SQLAlchemy ORM. React frontend in /web.

## Boundaries
- models/ must not import from api/
- External API calls only in services/
- No direct SQL queries outside models/

## Conventions
- snake_case for functions, PascalCase for classes
- All API endpoints require auth middleware
- Every new endpoint needs a test

## Known Issues
- Auth token refresh is flaky under load (#142)
- Migration 034 needs manual review before deploy
```

### Project Config Override

```yaml
# config/projects/my-app.yaml
project:
  name: my-app
  repo_path: /home/harness/repos/my-app

routing:
  # Override: use Opus for all roles on this critical project
  worker:
    model: anthropic/claude-opus-4-6

budget:
  max_cost_usd: 10.00  # Higher budget for complex tasks

skills:
  # Additional project-specific skills
  extra_dirs:
    - /home/harness/repos/my-app/skills/
```

## Deployment

### VPS (Recommended)

The harness runs as a set of systemd services on a VPS:

```bash
# On your VPS (Ubuntu 24.04)
sudo bash scripts/setup.sh

# Configure secrets
nano /opt/agent-harness/secrets/.env

# Start services
systemctl enable --now harness-orchestrator
systemctl enable --now harness-phoenix
systemctl enable --now harness-telegram
```

See `scripts/setup.sh` for full setup details including nginx, firewall, and security hardening.

### Minimum Requirements

- 4 cores, 16 GB RAM, 100 GB SSD
- Ubuntu 24.04 LTS
- Node.js 20+ (for codegraph and promptfoo)
- Python 3.11+

## Task Lifecycle

```
INTAKE → PLAN → EXECUTE → VALIDATE → DONE
                                    → RETRY (up to 3x)
                                    → LEARN (failure recorded)
```

1. **Intake**: Validates task, assigns ID, classifies type, creates task directory
2. **Plan** (Opus): Decomposes task, gathers repo context via codegraph, produces bounded plan
3. **Execute** (Sonnet): Creates worktree, implements plan, runs tests, produces diff
4. **Validate**: Deterministic checks (tests, boundaries, blast radius) + optional Reviewer agent
5. **Learn**: Records outcome, classifies failures, updates skill usage stats

## Telegram Bot

The Telegram bot provides human-in-the-loop control:

| Command | Description |
|---------|-------------|
| `/task "description"` | Submit a new task |
| `/status [TASK-ID]` | Check task or system status |
| `/approve TASK-ID` | Approve a pending task |
| `/reject TASK-ID "reason"` | Reject with feedback |
| `/hold TASK-ID` | Pause a task |
| `/budget` | Show cost usage |

Campaign previews and approval requests are sent with inline buttons.

## Repo Intelligence (codegraph)

The harness uses [optave/codegraph](https://github.com/optave/codegraph) for local, zero-cost code understanding:

- **Symbol lookup**: Find where functions/classes are defined and used
- **Call graph**: Who calls what, full dependency chains
- **Impact analysis**: What breaks if you change a function
- **Semantic search**: Find code by natural language ("auth token validation")
- **Complexity metrics**: Cognitive complexity, cyclomatic complexity, maintainability index
- **Diff impact**: Understand blast radius before committing

All queries are local SQLite lookups. Zero API calls, zero tokens.

## Eval & Quality

### Deterministic Checks (every task)
- Output schema validation
- Test pass/fail verification
- Boundary violation detection
- Blast radius threshold
- Budget compliance

### Promptfoo Suites
- Regression tests per skill (`evals/regressions/`)
- Red-team adversarial tests (`evals/adversarial/`)

### Self-Improvement Loop

The harness learns from every task it runs. The improvement cycle works across three levels:

**Level 1 — Per-Project Learning (automatic)**

Every task outcome is classified into one of four failure buckets:
- `routing_failure` — wrong skill or agent selected
- `retrieval_failure` — missing context, stale codegraph
- `execution_failure` — code doesn't compile, tests fail
- `evaluation_mismatch` — output looks correct but eval flags it

This data accumulates in each project's SQLite database. The harness uses it to adjust confidence thresholds and skill selection for that project.

**Level 2 — Cross-Project Pattern Detection (semi-automatic)**

When the same failure pattern appears across multiple projects, it's likely a systemic skill or prompt issue — not a project-specific problem.

```bash
# Analyze failure patterns across all registered projects
harness-ctl analyze-failures --cross-project --since 30d
```

Example output:
```
Pattern: safe_refactor.v1 — 38% failure rate on cross-module renames
  project-alpha: 12/30 tasks failed (retrieval_failure)
  project-beta:   8/22 tasks failed (retrieval_failure)
  project-gamma:  0/15 tasks failed (single-module only)

Root cause: Skill procedure step 2 ("query codegraph for callers")
  does not traverse cross-module boundaries when modules are in
  separate directories with independent __init__.py files.

Proposed fix: Add boundary-aware caller resolution step before rename.
Confidence: 0.82 (based on 42 failure examples)
```

**Level 3 — Harness Improvement PR (human-gated)**

When a pattern is detected and a fix is proposed, the harness can generate a PR against itself:

```bash
# Generate a skill improvement proposal
harness-ctl propose-improvement --pattern "safe_refactor_cross_module"
```

This creates:
1. A new skill version (`safe_refactor.v2.md`) with the proposed fix
2. Offline eval results comparing v1 vs v2 on historical failures
3. A PR to the harness repo with anonymized failure data, the skill diff, and eval results

The PR includes:
```markdown
## Skill Improvement: safe_refactor.v1 → v2

### Evidence
- 42 failures across 3 projects (38% failure rate on cross-module renames)
- Root cause: missing boundary-aware caller resolution
- Pattern confidence: 0.82

### Changes
- Added step 2b: "Resolve callers across module boundaries using
  codegraph `--cross-module` flag"
- Added failure mode: `cross_module_caller_missed`

### Eval Results
| Metric | v1 | v2 | Delta |
|--------|----|----|-------|
| Cross-module rename success | 62% | 91% | +29% |
| Single-module rename success | 98% | 98% | 0% |
| Avg tokens per task | 45K | 52K | +7K |

### Holdout
Tested against 10 held-out examples not used in training the fix.
Holdout pass rate: 9/10 (90%)
```

**No improvement ships without human approval.** The harness never self-merges.

## Cost Management

- **Budget ceiling per task**: Default $5.00 / 500K tokens / 30 min
- **Daily kill switch**: $100/day hard limit
- **Planner via Max plan**: Opus calls use Claude Code CLI (subscription, not API credits)
- **Rate limit backoff**: Exponential retry (2s → 32s) on 429 errors
- **Automatic fallback**: OpenAI GPT-5.4-mini when primary providers fail
- **Per-task tracking**: Every LLM call logged with model, tokens, cost

## Project Structure

```
agent-harness/
├── apps/orchestrator/       # LangGraph orchestrator, agents, stages, CLI
├── packages/
│   ├── llm/                 # LiteLLM router, prompt loader
│   ├── state/               # SQLite store, task state manager
│   ├── repo_intel/          # Codegraph adapter, AGENTS.md parser
│   ├── stage_manager/       # Git worktree, tmux session management
│   ├── eval/                # Deterministic checks, promptfoo runner
│   └── notifications/       # Telegram bot, message formatters
├── skills/code/             # Base code skills (refactor, bug trace, review)
├── prompts/                 # Agent personas (planner, worker, reviewer)
├── evals/                   # Promptfoo regression + red-team configs
├── config/                  # Model routing, harness config, eval config
├── scripts/                 # VPS setup, deploy, backup
├── tests/                   # 60 tests (unit + integration)
└── docs/                    # Status tracking, architecture docs
```

## Contributing

There are three ways to contribute to the harness:

### 1. Run It and Share Learnings

The most valuable contributions come from real usage. When you run the harness on your projects, it generates failure data that can improve the base skills for everyone.

```bash
# After running the harness on your projects for a while:
harness-ctl analyze-failures --cross-project --since 30d

# If a pattern is detected, propose an improvement:
harness-ctl propose-improvement --pattern "pattern_name"

# This generates a PR-ready branch with:
# - New skill version with the fix
# - Anonymized failure evidence
# - Before/after eval results
# - Holdout test results
```

Submit the generated PR. Your failure data is anonymized — no project names, file paths, or code content are included. Only the failure pattern, category, and skill metadata.

### 2. Add Skills

Skills are markdown files with YAML frontmatter. To add a new skill:

1. Create `skills/code/your_skill.v1.md` (or `skills/marketing/`)
2. Define triggers, tools, procedure, and validation checklist
3. Add a Promptfoo regression suite in `evals/regressions/`
4. Submit a PR

See `skills/code/safe_refactor.v1.md` for the template.

### 3. Improve the Core

For changes to the orchestrator, agents, or infrastructure:

1. Fork the repo
2. Create a feature branch
3. Run tests: `pytest tests/`
4. Submit a PR

All skills and prompts are versioned in git. Changes follow the proposal lifecycle:

```
PR → offline eval → human approve → canary (10%) → promote (100%)
```

### Contribution Data Flow

```
Your projects          Other contributors' projects
     │                          │
     ▼                          ▼
  Failure data              Failure data
  (per-project)             (per-project)
     │                          │
     └──────────┬───────────────┘
                │
     Cross-project pattern detection
                │
         ┌──────▼──────┐
         │  Is this a   │
         │  harness bug  │──── No ──→ Project-specific fix
         │  or a skill   │           (stays local)
         │  limitation?  │
         └──────┬──────┘
                │ Yes
                ▼
     Generate skill patch + eval
                │
                ▼
     Open PR to agent-harness repo
     (anonymized evidence + eval results)
                │
                ▼
     Community review + merge
                │
                ▼
     Everyone's harness gets better
```

### What Makes a Good Contribution

| Type | Example | Impact |
|------|---------|--------|
| **Skill fix** | safe_refactor fails on async code → add async-aware step | High — fixes a failure mode for all users |
| **New skill** | `dependency_update.v1` — safely update package versions | High — adds a new capability |
| **Prompt improvement** | Worker policy change that reduces out-of-scope edits | Medium — improves all projects |
| **Eval case** | New red-team test for a prompt injection pattern | Medium — hardens security |
| **Bug fix** | Rate limiter doesn't respect Retry-After header | Direct — fixes broken behavior |
| **Documentation** | Runbook for debugging retrieval failures | Indirect — helps others self-serve |

## License

Apache 2.0
