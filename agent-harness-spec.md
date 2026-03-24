# Agent Harness — Technical Implementation Spec

**Version:** 1.0  
**Date:** March 22, 2026  
**Status:** Ready for implementation  
**Scope:** Software development + marketing automation harness  

---

## 1. Executive Summary

This spec defines a **self-improving agent harness** for managing software projects and their associated marketing efforts. The harness follows a **thin-agent / thick-infrastructure** architecture: agents are narrow executors with strict role boundaries, while graphs, evaluators, and deterministic stage management control flow and quality.

### Core Principles

1. **Harness > Model.** The durable assets are the skills, evals, traces, and graphs — not any specific LLM.
2. **Iterate fast, elaborate later.** Start with the minimum viable loop and add complexity only when traces reveal where it's needed.
3. **Rippable by design.** Every "smart" layer must be removable when models improve enough to not need it.
4. **Quantify everything.** Code tasks produce test results; marketing tasks produce campaign metrics. Both feed the self-improvement loop.
5. **Human-in-the-loop by default.** No autonomous merges or campaign launches in MVP. Gate all production actions.

### What This Harness Does

- Accepts tasks (code changes, marketing campaigns, content creation)
- Plans and executes via specialized agents with curated tool access
- Validates output through deterministic checks and eval suites
- Traces every action for observability and failure analysis
- Proposes improvements to its own skills and processes via gated self-improvement
- Connects to code repos (via structural graph intelligence) and marketing platforms (via MCP servers)

---

## 2. Tool Stack

### Core Stack (Phase 1)

| Component | Tool | License | Why |
|-----------|------|---------|-----|
| **Orchestration** | LangGraph | MIT | Stateful graphs, durable execution, human-in-the-loop, checkpointing. Verbose but production-proven. |
| **Repo Intelligence** | codegraph (optave) | Apache 2.0 | Fully local, zero API keys, function-level dependency graph, 33-tool MCP server, incremental rebuilds, diff-impact analysis. |
| **Repo Intelligence (backup)** | CodeGraphContext | MIT | 14 languages, multiple DB backends (KùzuDB zero-config, Neo4j, FalkorDB), MCP server + CLI. Fallback if codegraph gaps appear. |
| **Tracing / Observability** | Phoenix + OpenTelemetry | Apache 2.0 | Self-hosted, OTel-based, no feature gates, no outbound telemetry. |
| **Evals (Phase 1)** | Promptfoo | MIT | CI-friendly matrix testing, red-teaming, simple YAML config. |
| **Evals (Phase 2)** | DeepEval | Apache 2.0 | Behavioral checks, regression suites, RAG/agent evals. Add when failure data warrants it. |
| **LLM Routing** | LiteLLM | MIT | Single interface to 100+ LLM providers. Model-agnostic by design. Route by agent role and task complexity. |
| **Data Store** | SQLite + KùzuDB | Public Domain / MIT | SQLite for structured state (tasks, evals, configs). KùzuDB for graph queries (skills, relationships). No JVM, no Docker dependency. |
| **Version Control** | Git (worktrees + branches) | — | Skills, prompts, configs all versioned in git. Worktrees for parallel task execution. |
| **Process Management** | systemd + tmux | — | systemd for service lifecycle on VPS. tmux for task-scoped terminal sessions. |
| **Notifications** | Telegram Bot API | — | Human-in-the-loop approvals, status updates, task submission, budget alerts. |
| **VPS Provider** | Hetzner Cloud | — | Cost-effective, EU/US regions, `hcloud` CLI for provisioning. |
| **Marketing MCP Servers** | Platform-specific (see §8) | Varies | Google Ads, GA4, GSC, X/Twitter, LinkedIn MCP servers. |

### Intentionally Excluded

| Tool | Reason |
|------|--------|
| **n2-QLN** | 2 GitHub stars, 17 commits, zero community. The concept (tool routing) is valid but the project is too immature. Implement simple tool curation per agent role instead. |
| **Neo4j** | Overkill for Phase 1. Adds JVM, Docker, Cypher learning curve. KùzuDB gives you graph queries as an embedded library. Revisit in Phase 3 if cross-entity traversals become a bottleneck. |
| **GitNexus** | PolyForm Noncommercial license. Useful as a reference and exploration tool only. |
| **Docker (Phase 1)** | Adds build time, networking complexity, and debugging overhead. Run everything as native processes on VPS. Add containerization in Phase 3 for isolation. |
| **CrewAI** | Simpler but less control. LangGraph's explicit state management is worth the verbosity for a self-improving system. |

---

## 3. Architecture

### High-Level View

```
┌─────────────────────────────────────────────────────────┐
│                   ORCHESTRATOR (LangGraph)               │
│  Planner Agent  ←→  Worker Agent  ←→  Reviewer Agent    │
│  Stage Manager  ←→  Budget Enforcer  ←→  Task Router    │
└──────────────┬──────────────────────┬───────────────────┘
               │                      │
     ┌─────────▼──────────┐  ┌───────▼────────────────────┐
     │  REPO INTELLIGENCE  │  │  MARKETING ADAPTER         │
     │  codegraph per repo │  │  MCP server registry       │
     │  - symbols/calls    │  │  - Google Ads/GA4/GSC      │
     │  - impact analysis  │  │  - X / LinkedIn            │
     │  - co-change        │  │  - Analytics ingestion     │
     │  - boundary checks  │  │  - Campaign skill executor │
     └─────────┬──────────┘  └───────┬────────────────────┘
               │                      │
     ┌─────────▼──────────────────────▼───────────────────┐
     │           SHARED STATE LAYER                        │
     │  SQLite: tasks, evals, configs, budgets, metrics    │
     │  KùzuDB: skill graph, decision graph, lineage       │
     │  Git: skills, prompts, personas (versioned)          │
     └──────────────────────┬─────────────────────────────┘
                            │
     ┌──────────────────────▼─────────────────────────────┐
     │           OBSERVABILITY & EVAL                      │
     │  Phoenix + OTel: traces, spans, cost, latency       │
     │  Promptfoo: regression tests, red-teaming            │
     │  Deterministic checks: tests pass, schema valid,     │
     │    blast radius under threshold, budget under ceiling │
     └────────────────────────────────────────────────────┘
```

### Why This Split

**codegraph** is the authoritative local structural graph — fast, incremental, directly queryable. The shared state layer holds cross-task/cross-skill/cross-repo semantic data that survives sessions. This gives you cheap precise repo navigation plus a shared memory system, with a clean boundary between "facts about code structure" and "facts about how we work."

The **marketing adapter** is a parallel intelligence layer that connects to external platforms via MCP servers. It uses the same skill/eval/trace infrastructure as the code side, but with campaign-specific skills and metrics-based validators.

---

## 4. Agent Roster (MVP)

Start with **three agents**. Add more only when traces reveal where these three fail.

### Planner

Combines the original plan's Manager + Navigator roles.

**Owns:** Task intake, decomposition, budget allocation, code subgraph selection, skill selection, stop/go decisions, escalation.

**Sees:**
- Task registry
- Skill registry (read-only)
- codegraph queries (locate_symbol, get_context, get_impact, get_cochange)
- Git diff metadata
- Trace summaries
- Marketing platform analytics (for marketing tasks)

**Does NOT:** Edit code. Edit files. Make direct API calls to marketing platforms.

**Tools (curated, explicit — no routing layer):**
- `repo_intel.locate_symbol`
- `repo_intel.get_context`
- `repo_intel.get_impact`
- `repo_intel.get_cochange`
- `repo_intel.get_boundary_violations`
- `skill_registry.find_best_skill`
- `task_state.read`
- `task_state.write_plan`
- `marketing.get_campaign_metrics` (for marketing tasks)
- `marketing.get_analytics_summary` (for marketing tasks)

**Model tier:** Frontier (Claude Opus / GPT-5 class). Planning requires strong reasoning.

### Worker

Combines Implementer + basic self-validation.

**Owns:** Executing the plan in a worktree (code) or via MCP servers (marketing). Running local validation. Returning bounded output (diff, campaign config, content draft).

**Sees:**
- Plan packet from Planner
- File tools (read, write, patch)
- Shell (run tests, linters)
- Targeted repo-intel queries
- Marketing MCP tools (for marketing tasks)
- No graph-store writes

**Tools (curated):**
- `file.read`, `file.write`, `file.patch`
- `shell.run` (sandboxed)
- `repo_intel.get_context` (targeted, not exploratory)
- `repo_intel.get_candidate_tests`
- `git.apply_patch`, `git.diff`
- `marketing.create_draft_campaign` (marketing tasks)
- `marketing.create_content_draft` (marketing tasks)
- `marketing.schedule_post` (marketing tasks, requires approval gate)

**Model tier:** Mid-tier (Claude Sonnet / GPT-4o class). Implementation is less reasoning-heavy than planning.

### Reviewer

Independent verification agent. Added in Phase 1 but can be skipped for trivial tasks.

**Owns:** Verifying output quality, architectural fit, boundary violations, suspicious omissions, campaign compliance.

**Sees:**
- Read-only diff or campaign output
- Repo-intel (read-only)
- Test results
- Campaign metrics (for marketing)
- Prompt/persona version metadata

**Tools (curated, read-only):**
- `repo_intel.get_boundary_violations`
- `repo_intel.get_impact` (verification)
- `diff.read`
- `test_results.read`
- `marketing.get_campaign_metrics` (marketing tasks)
- `marketing.check_brand_compliance` (marketing tasks)

**Model tier:** Frontier. Review requires strong judgment.

### Agents Added Later

| Agent | Phase | Trigger |
|-------|-------|---------|
| **Eval Judge** | Phase 2 | When failure classification needs to be automated |
| **Skill Maintainer** | Phase 3 | When enough failure data exists to propose skill updates |
| **Marketing Analyst** | Phase 3 | When campaign iteration requires dedicated analytical reasoning |

---

## 5. Prompt / Persona System

Treat "persona" as a strict operating profile, not brand voice.

### File Structure

```
prompts/
  planner/
    identity.md
    policy.md
    procedure.md
    output_contract.json
  worker/
    identity.md
    policy.md
    procedure.md
    output_contract.json
  reviewer/
    identity.md
    policy.md
    procedure.md
    output_contract.json
```

### Required Prompt Sections

Each agent prompt is composed from 4 files, rehydrated fresh every run.

**1. Identity** — Who you are and what you do. One paragraph.

```
You are the Planner. Your job is to decompose tasks into bounded, 
executable plans and select the smallest high-confidence code subgraph 
(or marketing context) needed to act safely.
```

**2. Non-negotiable policy** — Hard constraints.

```
- Do not edit files directly
- Do not speculate about symbols you did not resolve
- If confidence < 0.7, escalate to human
- Never exceed the task budget
- For marketing tasks: never launch campaigns without human approval
```

**3. Procedure** — Step-by-step playbook.

```
1. Read the task packet
2. Classify: code_change | marketing_campaign | content_creation | mixed
3. For code: locate target → retrieve context → retrieve impact → select tests
4. For marketing: retrieve current metrics → identify target audience → select skill
5. Propose plan with estimated budget
6. Return bounded plan packet
```

**4. Output contract** — JSON schema. Enforced by deterministic validation.

```json
{
  "role_statement": "planner",
  "task_id": "string",
  "task_type": "code_change | marketing_campaign | content_creation",
  "plan_steps": ["array of step objects"],
  "selected_skill": "string",
  "estimated_budget_tokens": "integer",
  "confidence": "float 0-1",
  "missing_evidence": ["array of strings"],
  "in_scope": ["array of strings"],
  "out_of_scope": ["array of strings"]
}
```

### Anti-Drift Rules

- Every run rehydrates from versioned prompt files (no reliance on conversational memory)
- Each output includes: role_statement, in_scope, out_of_scope, confidence, missing_evidence
- Prompts are versioned in git alongside skills
- Prompt changes follow the same gated proposal lifecycle as skill changes

### AGENTS.md Convention

Every repo managed by the harness MUST contain an `AGENTS.md` file at root. This is auto-injected into agent context at task start.

```markdown
# AGENTS.md

## Project: [name]
## Language: [primary language]
## Build: [build command]
## Test: [test command]
## Lint: [lint command]

## Architecture
[Brief description of project structure]

## Boundaries
- [module A] must not import from [module B]
- [external API calls] only in [services/ directory]

## Conventions
- [naming conventions]
- [error handling patterns]
- [testing requirements]

## Known Issues
- [active bugs or tech debt]

## codegraph
Graph at `.codegraph/graph.db`. Run `codegraph build` after structural changes.
Before modifying code:
1. `codegraph where <symbol>` — find where it lives
2. `codegraph callers <symbol>` — check who calls it
3. `codegraph impact` — check blast radius after changes
```

---

## 6. Skill System

### Skill Definition Format

Skills are **markdown + YAML frontmatter in git**. This is the source of truth. Graph projections are derived.

```yaml
---
id: skill.safe_refactor.v1
name: Safe Refactor
version: 1
domain: code  # code | marketing | content
scope: code-modification
triggers:
  - "refactor"
  - "rename"
  - "extract"
agent_role: worker
allowed_tools:
  - repo_intel.get_context
  - repo_intel.get_impact
  - repo_intel.get_candidate_tests
  - git.apply_patch
  - shell.run_tests
inputs:
  - task_packet
  - repo_context
outputs:
  schema: refactor_result_v1
definition_of_done:
  - "all impacted callers reviewed"
  - "tests selected and run"
  - "diff-impact checked post-edit"
failure_modes:
  - missing_callers
  - stale_context
  - over_broad_edit
validators:
  - eval.refactor_correctness.v1
supersedes: null
estimated_tokens: 15000
---

# Safe Refactor

## When to Use
Use for rename, extract, or move operations on existing code.

## Procedure
1. Receive plan packet with target symbol and desired change
2. Query codegraph for full caller/import/test graph of target
3. ...

## Validation Checklist
- [ ] All callers updated
- [ ] Tests pass
- [ ] No boundary violations introduced
- [ ] Diff-impact confirms no unexpected changes
```

### First 5 Skills to Implement

#### Code Domain

**1. `safe_refactor.v1`** — Rename/extract/move. Requires context, impact, candidate tests, post-edit diff-impact.

**2. `bug_trace.v1`** — Regression/runtime bugs. Requires call path, co-change history, failing test or reproduction.

**3. `review_diff.v1`** — Pre-completion review. Requires diff summary, boundary check, blast radius, missing test check.

#### Marketing Domain

**4. `seo_content.v1`** — Create/optimize content for search. Requires GSC keyword data, competitor analysis, brand voice constraints, target metrics.

**5. `social_campaign.v1`** — Plan and draft social media campaign. Requires platform analytics, audience data, content calendar, A/B test framework.

### Skill Graph Schema (KùzuDB)

Node types: `Skill`, `Evaluator`, `ArtifactSchema`, `RecoveryPattern`, `PromptVersion`, `TaskType`

Edges: `REQUIRES`, `VALIDATED_BY`, `PRODUCES`, `SAFE_FALLBACK_TO`, `SUPERSEDES`, `BEST_FOR`, `CONFLICTS_WITH`

---

## 7. Stage Management

### Simplified Stage Machine (MVP)

```
INTAKE
  → PLAN          (Planner produces bounded plan)
  → EXECUTE        (Worker implements in worktree/sandbox)
  → VALIDATE       (Deterministic checks + optional Reviewer)
  → DONE | RETRY   (Human approves or requests rework)
  → LEARN          (Trace + eval data stored for improvement loop)
```

Elaborate to the full 10-state machine (from original plan) only when traces show where the simple version fails.

### Runtime Primitives

- **Git worktree per task branch** (code tasks)
- **tmux session per task** (process isolation)
- **One state directory per task**
- **One trace root per task**

```
.harness/tasks/TASK-123/
  task.json          # task definition, metadata
  state.json         # current stage, timestamps
  budget.json        # token/cost ceiling and usage
  plan.json          # planner output
  artifacts/         # diffs, content drafts, campaign configs
  eval/              # eval results
  traces/            # OTel trace files
  patches/           # proposed changes
```

### Stage Gate Rules

- No code edit before plan packet exists
- No review before local validation exists  
- No learning update before eval classification exists
- No autonomous merge in MVP (human approves all production changes)
- No campaign launch without human approval
- Task killed if budget ceiling exceeded

### Cost Ceiling Enforcement

Every task has a hard budget:

```json
{
  "task_id": "TASK-123",
  "budget": {
    "max_tokens": 500000,
    "max_cost_usd": 5.00,
    "max_duration_minutes": 30,
    "max_retries": 3
  },
  "usage": {
    "tokens_used": 0,
    "cost_usd": 0.00,
    "duration_minutes": 0,
    "retries": 0
  }
}
```

The orchestrator checks budget after every LLM call. Exceeding any ceiling triggers immediate escalation to human, not retry.

---

## 8. Marketing Adapter Layer

This is the component missing from the original plan. It connects the harness to marketing platforms using the same skill/eval/trace infrastructure as the code side.

### MCP Server Registry

The harness maintains a registry of authenticated MCP server connections:

```yaml
# config/marketing_servers.yaml
servers:
  google_ads:
    type: mcp
    url: "mcp://google-ads-server"
    auth: oauth2
    credentials_ref: secrets/google_ads.json
    capabilities: [read_campaigns, read_metrics, create_draft]
    enabled: true

  ga4:
    type: mcp
    url: "mcp://ga4-server"
    auth: oauth2
    credentials_ref: secrets/ga4.json
    capabilities: [read_analytics, read_events]
    enabled: true

  gsc:
    type: mcp
    url: "mcp://gsc-server"  
    auth: oauth2
    credentials_ref: secrets/gsc.json
    capabilities: [read_search_data, read_sitemaps]
    enabled: true

  twitter_x:
    type: mcp
    url: "mcp://x-server"
    auth: oauth2
    credentials_ref: secrets/x.json
    capabilities: [read_analytics, create_draft_post, schedule_post]
    enabled: true

  linkedin:
    type: mcp
    url: "mcp://linkedin-server"
    auth: oauth2
    credentials_ref: secrets/linkedin.json
    capabilities: [read_analytics, create_draft_post, schedule_post]
    enabled: true
```

### Marketing Tools Exposed to Agents

These wrap MCP server calls with harness-level controls:

```python
# Core marketing tools
marketing.get_campaign_metrics(platform, campaign_id, date_range)
marketing.get_analytics_summary(platform, property_id, date_range, dimensions)
marketing.get_search_keywords(property_id, date_range, filters)
marketing.get_social_analytics(platform, account_id, date_range)

# Draft creation (requires human approval to publish)
marketing.create_content_draft(content_type, target_platform, brief)
marketing.create_draft_campaign(platform, campaign_config)
marketing.schedule_post(platform, content, schedule_time)  # GATED

# Analysis
marketing.compare_campaigns(campaign_ids, metrics, date_range)
marketing.get_audience_insights(platform, segment)
marketing.get_competitor_content(domain, content_type)  # via web search
```

### Campaign as Task

A marketing campaign follows the same task lifecycle as a code change:

```json
{
  "task_id": "MKT-045",
  "task_type": "marketing_campaign",
  "domain": "social",
  "objective": "Increase populationmars.com newsletter signups by 20%",
  "platforms": ["twitter_x", "linkedin"],
  "skill": "social_campaign.v1",
  "metrics": {
    "primary": "newsletter_signups",
    "secondary": ["impressions", "engagement_rate", "click_through_rate"],
    "baseline": {"newsletter_signups_weekly": 50},
    "target": {"newsletter_signups_weekly": 60}
  },
  "constraints": {
    "budget_usd": 0,
    "brand_voice": "prompts/brand/populationmars_voice.md",
    "content_guidelines": "prompts/brand/populationmars_guidelines.md"
  }
}
```

### Marketing Eval Signals

Marketing tasks produce quantifiable outcomes — this is where the self-improvement loop is most powerful:

| Signal | Source | Latency |
|--------|--------|---------|
| Content quality score | LLM-as-judge eval | Immediate |
| Brand voice compliance | Deterministic + LLM check | Immediate |
| Engagement rate | Platform analytics via MCP | 24-72 hours |
| Click-through rate | GA4 / platform analytics | 24-72 hours |
| Conversion rate | GA4 goals / CRM | 1-7 days |
| SEO ranking change | GSC | 1-4 weeks |

The harness stores these as time-series data in SQLite and feeds them back into the skill improvement loop.

---

## 9. Self-Improvement Loop

This section is largely preserved from the original plan — it's well-designed.

### Allowed Mutation Targets

The Skill Maintainer (Phase 3) may propose changes to:
- Skill trigger text
- Procedure steps
- Prompt wording
- Tool exposure sets
- Stage thresholds

It may **NOT**:
- Change hidden eval sets
- Modify pass/fail thresholds without human review
- Merge directly
- Update production prompt aliases automatically

### Proposal Lifecycle

```
1. Collect traces + failures (automatic, continuous)
2. Cluster failures into taxonomy buckets (automatic)
3. Generate patch proposal (Skill Maintainer agent)
4. Run offline eval suite (automatic)
5. Compare against holdout + regression + cost budget (automatic)
6. Open PR with rationale + results (automatic)
7. Human approves rollout (manual gate)
8. Canary to 10% of tasks (automatic with monitoring)
9. Promote or rollback based on metrics (human-approved)
```

### Failure Taxonomy

Exactly four primary buckets:

- **`routing_failure`** — Wrong skill selected, wrong agent invoked, wrong tool used
- **`retrieval_failure`** — Missing context, stale data, incomplete subgraph
- **`execution_failure`** — Code doesn't compile, tests fail, API error, malformed output
- **`evaluation_mismatch`** — Output looks correct but eval flags it (or vice versa)

### Eval Stack

**Phase 1: Promptfoo + deterministic checks**
- Promptfoo for CI-friendly matrix testing and red-teaming
- Deterministic checks: tests passed, no boundary violations, blast radius under threshold, output schema valid, budget under ceiling

**Phase 2: Add DeepEval**
- Behavioral regression tests
- Task-specific correctness checks
- RAG/retrieval quality evals

**Phase 3: Marketing-specific evals**
- Campaign performance vs. baseline
- Content quality scores over time
- A/B test significance checks
- Brand voice drift detection

**Always: Human review for**
- Changes to agent policies
- Changes to routing thresholds
- Changes with mixed eval signals
- Any production campaign launch

---

## 10. Model Routing

### LiteLLM Configuration

Use LiteLLM as the unified interface. All LLM calls go through it.

```yaml
# config/model_routing.yaml
default_provider: anthropic

routing:
  planner:
    model: anthropic/claude-opus-4-6
    fallback: openai/gpt-5.4-mini
    max_tokens: 8000
    temperature: 0.3
    note: "Planning requires strongest reasoning. Opus 4.6 is the frontier choice."

  worker:
    model: anthropic/claude-sonnet-4-6
    fallback: openai/gpt-5.4-mini
    max_tokens: 16000
    temperature: 0.2
    note: "Implementation is execution-heavy, not reasoning-heavy. Sonnet 4.6 is the sweet spot."

  reviewer:
    model: anthropic/claude-sonnet-4-6
    fallback: openai/gpt-5.4-mini
    max_tokens: 4000
    temperature: 0.1
    note: "Review needs solid judgment but not frontier reasoning. Sonnet 4.6 with low temp."

  content_generation:
    model: anthropic/claude-sonnet-4-6
    fallback: openai/gpt-5.4-mini
    max_tokens: 8000
    temperature: 0.7
    note: "Marketing content benefits from more creativity. Higher temp on Sonnet."

  eval_judge:
    model: anthropic/claude-sonnet-4-6
    max_tokens: 2000
    temperature: 0.0
    note: "Evals need determinism. Zero temp, no creativity."

  lightweight:
    model: openai/gpt-5.4-mini
    max_tokens: 4000
    temperature: 0.1
    note: "For simple classification, formatting, parsing. Cheapest option."

# Cost tracking
cost_tracking:
  enabled: true
  alert_threshold_daily_usd: 50.00
  kill_threshold_daily_usd: 100.00
```

### Why LiteLLM

- Single API for Anthropic, OpenAI, Google, open-source models
- Built-in cost tracking per request
- Automatic fallback on provider errors
- No vendor lock-in — swap models by changing config
- Proxy mode available for self-hosted deployment

---

## 11. Persistent State Management

### State Tiers

| Tier | Store | What | Durability |
|------|-------|------|------------|
| **Hot** | In-memory (LangGraph state) | Current task execution context | Per-task |
| **Warm** | SQLite | Task records, eval results, metrics, budgets, configs | Permanent |
| **Structured** | KùzuDB (embedded graph) | Skill relationships, decision lineage, task→skill→eval connections | Permanent |
| **Versioned** | Git | Skills, prompts, personas, AGENTS.md, configs | Permanent + history |
| **Traces** | Phoenix (backed by SQLite) | OTel spans, latency, token usage, cost | Permanent |
| **Marketing metrics** | SQLite (time-series tables) | Campaign performance data pulled from platforms | Permanent |

### SQLite Schema (Core Tables)

```sql
-- Tasks
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,  -- code_change, marketing_campaign, content_creation
    domain TEXT NOT NULL,  -- code, marketing, content
    status TEXT NOT NULL,  -- planned, executing, validating, done, failed, retry
    skill_id TEXT,
    plan JSON,
    budget JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Eval results
CREATE TABLE eval_results (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id),
    eval_type TEXT NOT NULL,  -- deterministic, promptfoo, deepeval, human
    passed BOOLEAN,
    score REAL,
    details JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Failure classifications
CREATE TABLE failures (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id),
    category TEXT NOT NULL,  -- routing, retrieval, execution, evaluation_mismatch
    description TEXT,
    skill_id TEXT,
    prompt_version TEXT,
    model_used TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Marketing metrics (time-series)
CREATE TABLE campaign_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT REFERENCES tasks(id),
    platform TEXT NOT NULL,
    campaign_id TEXT,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    measured_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Skill usage tracking
CREATE TABLE skill_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT REFERENCES tasks(id),
    skill_id TEXT NOT NULL,
    skill_version INTEGER,
    prompt_version TEXT,
    model_used TEXT,
    tokens_used INTEGER,
    cost_usd REAL,
    outcome TEXT,  -- success, failure, partial
    failure_category TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Version Management

All mutable configuration lives in git:

```
harness-config/           # Separate repo, or monorepo subdirectory
  skills/
    code/
      safe_refactor.v1.md
      safe_refactor.v2.md  # New version after improvement
      bug_trace.v1.md
      review_diff.v1.md
    marketing/
      seo_content.v1.md
      social_campaign.v1.md
  prompts/
    planner/
      identity.md
      policy.md
      procedure.md
      output_contract.json
    worker/...
    reviewer/...
    brand/
      populationmars_voice.md
      populationmars_guidelines.md
      micros_voice.md
  config/
    model_routing.yaml
    marketing_servers.yaml
    eval_config.yaml
```

Skill/prompt changes follow the proposal lifecycle: PR → offline eval → human approve → canary → promote.

---

## 12. Deployment (Self-Hosted VPS)

### Minimum VPS Requirements

- **CPU:** 4 cores
- **RAM:** 16 GB (8 GB minimum, 16 GB recommended for Phoenix + KùzuDB)
- **Storage:** 100 GB SSD
- **OS:** Ubuntu 24.04 LTS
- **Network:** Open ports for Phoenix UI (6006), harness API (8080)

### Service Layout

```
/opt/agent-harness/
  bin/
    harness-ctl           # CLI for task management
  apps/
    orchestrator/         # LangGraph-based, Python
    phoenix/              # Self-hosted Phoenix instance
  config/                 # Symlink to git-managed config
  data/
    sqlite/
      harness.db          # Core state
      kuzu/               # KùzuDB graph data
    traces/               # OTel export directory
    worktrees/            # Git worktrees for active tasks
  logs/
  tmp/
```

### systemd Services

```ini
# /etc/systemd/system/harness-orchestrator.service
[Unit]
Description=Agent Harness Orchestrator
After=network.target

[Service]
Type=simple
User=harness
WorkingDirectory=/opt/agent-harness
ExecStart=/opt/agent-harness/.venv/bin/python -m apps.orchestrator.main
Restart=on-failure
RestartSec=5
Environment=HARNESS_CONFIG=/opt/agent-harness/config
Environment=HARNESS_DATA=/opt/agent-harness/data
Environment=LITELLM_LOG_LEVEL=WARNING

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/harness-phoenix.service
[Unit]
Description=Phoenix Observability
After=network.target

[Service]
Type=simple
User=harness
ExecStart=/opt/agent-harness/.venv/bin/python -m phoenix.server.main serve
Restart=on-failure
Environment=PHOENIX_PORT=6006
Environment=PHOENIX_WORKING_DIR=/opt/agent-harness/data/traces

[Install]
WantedBy=multi-user.target
```

### Telegram Notification Service

The harness includes a Telegram bot for human-in-the-loop interaction.

**Capabilities:**

| Feature | Command / Trigger | Description |
|---------|------------------|-------------|
| Notifications | Automatic | Task completed, task failed, approval needed, budget alert, campaign metrics update |
| Approvals | `/approve TASK-123` | Approve a pending task |
| Rejections | `/reject TASK-123 "reason"` | Reject with reason |
| Hold | `/hold TASK-123` | Put task on hold |
| Status | `/status`, `/status TASK-123` | System or task status |
| Budget | `/budget` | Current budget usage |
| Task submission | `/task "description"` | Submit new task via Telegram |
| Campaign previews | Inline buttons | Bot sends draft with approve/reject buttons |

**Architecture:**

```
packages/notifications/
  __init__.py
  telegram_bot.py          # TelegramNotifier service
  formatters.py            # Message formatting (Markdown)
```

**systemd service:**

```ini
# /etc/systemd/system/harness-telegram.service
[Unit]
Description=Agent Harness Telegram Bot
After=network.target harness-orchestrator.service

[Service]
Type=simple
User=harness
WorkingDirectory=/opt/agent-harness
ExecStart=/opt/agent-harness/.venv/bin/python -m packages.notifications.telegram_bot
Restart=on-failure
RestartSec=5
Environment=HARNESS_CONFIG=/opt/agent-harness/config
Environment=TELEGRAM_BOT_TOKEN=file:/opt/agent-harness/secrets/telegram_token

[Install]
WantedBy=multi-user.target
```

### Security

- All secrets in `/opt/agent-harness/secrets/` (mode 0600, owned by harness user)
- Marketing MCP OAuth tokens encrypted at rest
- Phoenix UI behind nginx reverse proxy with basic auth or Tailscale
- No public exposure of orchestrator API without auth
- Git SSH key for config repo access

---

## 13. Repository Structure

```
agent-harness/
  apps/
    orchestrator/
      main.py                    # LangGraph entrypoint
      agents/
        planner.py
        worker.py
        reviewer.py
      stages/
        intake.py
        plan.py
        execute.py
        validate.py
        learn.py
      budget.py                  # Cost ceiling enforcement
      task_router.py             # Task type classification
    marketing_adapter/
      registry.py                # MCP server registry
      tools.py                   # Marketing tool wrappers
      metrics_collector.py       # Periodic metrics ingestion
  packages/
    repo_intel/
      codegraph_adapter.py       # Wrapper around codegraph CLI/MCP
      agents_md.py               # AGENTS.md parser and injector
    state/
      sqlite_store.py            # SQLite operations
      kuzu_store.py              # KùzuDB graph operations
      task_state.py              # Task lifecycle management
    llm/
      router.py                  # LiteLLM wrapper with cost tracking
      prompt_loader.py           # Loads versioned prompts from git
    stage_manager/
      worktree.py                # Git worktree operations
      tmux.py                    # tmux session management
    eval/
      deterministic.py           # Schema validation, test checks
      promptfoo_runner.py        # Promptfoo integration
      marketing_eval.py          # Campaign performance evaluation
    notifications/
      telegram_bot.py            # TelegramNotifier service
      formatters.py              # Message formatting helpers
  skills/
    code/
      safe_refactor.v1.md
      bug_trace.v1.md
      review_diff.v1.md
    marketing/
      seo_content.v1.md
      social_campaign.v1.md
  prompts/
    planner/...
    worker/...
    reviewer/...
    brand/...
  evals/
    regressions/
      test_safe_refactor.yaml    # Promptfoo test file
      test_review_diff.yaml
    adversarial/
      red_team.yaml              # Promptfoo red-team config
    marketing/
      test_seo_content.yaml
      test_social_campaign.yaml
    goldens/                     # Ground truth examples
  config/
    model_routing.yaml
    marketing_servers.yaml
    eval_config.yaml
    harness.yaml                 # Global harness configuration
  scripts/
    setup.sh                     # VPS setup script
    deploy.sh                    # Deployment script
    backup.sh                    # Data backup
  docs/
    architecture.md
    runbooks/
      adding_a_skill.md
      adding_a_marketing_platform.md
      debugging_failures.md
    ADRs/
      001_litellm_over_direct_apis.md
      002_sqlite_over_neo4j.md
      003_codegraph_as_primary_repo_intel.md
  tests/
    unit/
    integration/
  requirements.txt
  pyproject.toml
  README.md
```

---

## 14. Implementation Phases

### Phase 1 — Core Loop (Weeks 1-3)

**Goal:** A task can flow from intake to validated output with full tracing.

**Deliverables:**
- LangGraph orchestrator with Planner + Worker + Reviewer
- codegraph wrapper (repo-intel adapter)
- LiteLLM router with cost tracking
- SQLite state store
- Phoenix tracing
- Worktree + tmux stage manager
- 3 code skills: safe_refactor, bug_trace, review_diff
- AGENTS.md convention and injector
- Budget ceiling enforcement
- Promptfoo regression suite for code skills
- `harness-ctl` CLI for task submission and monitoring

**Acceptance criteria:**
- Task opens a worktree
- Planner returns bounded plan with confidence score
- Worker patches code and runs tests
- Reviewer verifies diff
- Full trace visible in Phoenix
- Budget enforcement kills runaway tasks
- Promptfoo regressions pass

### Phase 2 — Marketing + Eval (Weeks 4-6)

**Goal:** Marketing tasks flow through the same harness with platform-specific skills and metrics.

**Deliverables:**
- Marketing adapter with MCP server registry
- Google Ads + GA4 + GSC MCP connections
- X/Twitter + LinkedIn MCP connections
- 2 marketing skills: seo_content, social_campaign
- Marketing eval suite (content quality, brand compliance)
- Metrics collector (periodic pull from platforms)
- Campaign-as-task lifecycle
- DeepEval integration for behavioral checks
- Failure classification automation
- Cost/latency dashboards in Phoenix

**Acceptance criteria:**
- Marketing task produces content draft with brand compliance check
- Campaign metrics are ingested and stored
- Failed tasks are auto-classified into taxonomy
- Marketing evals run alongside code evals

### Phase 3 — Skill Graph + Self-Improvement (Weeks 7-10)

**Goal:** The system can propose improvements to its own skills and processes.

**Deliverables:**
- KùzuDB skill graph with projections from git-backed skills
- Skill Maintainer agent
- Patch proposal format and offline eval harness
- Canary rollout flow (10% → 50% → 100%)
- Skill versioning and supersession
- Prompt version registry
- A/B testing framework for marketing skills
- Historical eval trend dashboards

**Acceptance criteria:**
- System proposes skill/prompt updates based on failure clusters
- No direct self-merge (human approval required)
- Holdout evals gate promotion
- Superseded skills stop routing by default
- Marketing skills improve measurably based on campaign metrics

### Phase 4 — Scale + Advanced (Weeks 11+)

Choose based on what traces reveal:

- **Eval Judge agent** — Automated failure classification and quality scoring
- **Multi-repo support** — Cross-repo skill sharing and context
- **Async GitHub issue resolver** — Open SWE-style issue-to-PR automation
- **Nightly maintenance jobs** — Automated code health checks, content calendar execution
- **Container isolation** — Docker/Podman for task sandboxing
- **Neo4j migration** — If graph traversal queries become a bottleneck in KùzuDB

---

## 15. Files to Create First

In priority order for Phase 1:

```
agent-harness/
  pyproject.toml
  requirements.txt
  config/harness.yaml
  config/model_routing.yaml
  apps/orchestrator/main.py
  apps/orchestrator/agents/planner.py
  apps/orchestrator/agents/worker.py
  apps/orchestrator/agents/reviewer.py
  apps/orchestrator/stages/intake.py
  apps/orchestrator/stages/plan.py
  apps/orchestrator/stages/execute.py
  apps/orchestrator/stages/validate.py
  apps/orchestrator/budget.py
  packages/repo_intel/codegraph_adapter.py
  packages/repo_intel/agents_md.py
  packages/state/sqlite_store.py
  packages/state/task_state.py
  packages/llm/router.py
  packages/llm/prompt_loader.py
  packages/stage_manager/worktree.py
  packages/stage_manager/tmux.py
  packages/eval/deterministic.py
  skills/code/safe_refactor.v1.md
  skills/code/bug_trace.v1.md
  skills/code/review_diff.v1.md
  prompts/planner/identity.md
  prompts/planner/policy.md
  prompts/planner/procedure.md
  prompts/planner/output_contract.json
  prompts/worker/identity.md
  prompts/worker/policy.md
  prompts/worker/procedure.md
  prompts/worker/output_contract.json
  prompts/reviewer/identity.md
  prompts/reviewer/policy.md
  prompts/reviewer/procedure.md
  prompts/reviewer/output_contract.json
  evals/regressions/test_safe_refactor.yaml
  scripts/setup.sh
```

---

## 16. Key Decisions Log

| Decision | Chosen | Rejected | Rationale |
|----------|--------|----------|-----------|
| Orchestration | LangGraph | CrewAI, custom | Production-proven stateful graphs, durable execution, checkpointing |
| Repo intelligence | codegraph (optave) | CodeGraphContext, custom | Apache 2.0, local, incremental, 33-tool MCP, strongest feature set |
| LLM interface | LiteLLM | Direct provider SDKs | Provider-agnostic, cost tracking, automatic fallback |
| Data store (Phase 1) | SQLite + KùzuDB | Neo4j, Postgres | Zero infrastructure overhead, embedded, fast iteration |
| Data store (Phase 3+) | Neo4j (optional) | — | Only if graph traversals outgrow KùzuDB |
| Tracing | Phoenix + OTel | Langfuse, custom | No outbound telemetry, self-hosted, no feature gates |
| Evals (Phase 1) | Promptfoo | DeepEval | Simpler CI integration, YAML-based, sufficient for MVP |
| Tool routing | Manual curation per agent | n2-QLN | n2-QLN too immature (2 stars). Manual curation is explicit and debuggable. |
| Deployment | systemd on VPS | Docker, K8s | Minimum overhead, fastest iteration, add containers in Phase 4 |
| Marketing integration | MCP servers | REST API wrappers | MCP is the converging standard. Google, Meta, HubSpot all support it. |

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **Harness** | The complete system wrapping the LLM: orchestration, tools, context, persistence, verification, constraints |
| **Skill** | A versioned, git-backed procedure with defined inputs, outputs, tools, validators, and failure modes |
| **Stage** | A discrete phase in the task lifecycle (plan, execute, validate, learn) |
| **Task** | A unit of work flowing through the harness (code change, campaign, content) |
| **Trace** | An OTel-compatible record of every action taken during a task |
| **Gate** | A checkpoint that must pass before proceeding to the next stage |
| **Canary** | A partial rollout of a skill/prompt change (10% → 50% → 100%) |
| **Holdout eval** | An eval set hidden from the Skill Maintainer to prevent overfitting |

---

## Appendix B: Migration Path from Original Plan

| Original Plan Element | This Spec | Status |
|----------------------|-----------|--------|
| 6 services | 3 services (Phase 1) | Simplified |
| 6 agents | 3 agents (Phase 1) | Simplified |
| 10-state stage machine | 5-state stage machine | Simplified |
| Neo4j graph store | SQLite + KùzuDB | Replaced (Phase 1) |
| n2-QLN router | Manual tool curation | Replaced |
| Docker Compose | systemd on VPS | Replaced (Phase 1) |
| codegraph | codegraph (unchanged) | Kept |
| LangGraph | LangGraph (unchanged) | Kept |
| Phoenix + OTel | Phoenix + OTel (unchanged) | Kept |
| DeepEval + Promptfoo | Promptfoo only (Phase 1) | Deferred |
| Skill system | Skill system (enhanced with marketing) | Enhanced |
| Self-improvement loop | Self-improvement loop (unchanged) | Kept |
| Prompt/persona system | Prompt/persona system (unchanged) | Kept |
| Failure taxonomy | Failure taxonomy (unchanged) | Kept |
| Marketing adapter | NEW | Added |
| LiteLLM routing | NEW | Added |
| AGENTS.md convention | NEW | Added |
| Cost ceiling enforcement | NEW | Added |
| Model routing config | NEW | Added |
