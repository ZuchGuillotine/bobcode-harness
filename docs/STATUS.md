# bobcode-harness — Project Status

**Last Updated:** 2026-03-24
**Phase:** 1 (Core Loop) — Near Complete
**Repo:** https://github.com/ZuchGuillotine/bobcode-harness

---

## Tracking Policy

- `docs/STATUS.md` is the public, tracked status document. Keep it limited to shipped behavior, repo-wide plans, and public-facing gaps.
- `.local/STATUS.md` is the local-only operator log for private pilot history, exact test runs, repo-specific notes, and non-public validation detail.
- When behavior changes locally but is not yet well-verified, record the experiment in `.local/STATUS.md` first, then promote the validated result into this document.

---

## What's Done

### Core Orchestrator (`apps/orchestrator/`)
- [x] `main.py` — LangGraph StateGraph (intake → plan → execute → validate → route → learn)
- [x] `agents/planner.py` — Opus 4.6 via Claude Code CLI (Max plan), auto-fallback to LiteLLM API
- [x] `agents/worker.py` — Sonnet 4.6 via LiteLLM, file/shell/git tools with worktree sandboxing
- [x] `agents/reviewer.py` — Sonnet 4.6 via LiteLLM, read-only verification
- [x] `stages/intake.py` — Task validation, ID assignment, SQLite persistence, directory creation
- [x] `stages/plan.py` — Planner invocation, output contract validation
- [x] `stages/execute.py` — Worktree execution, artifact capture, cleanup on failure
- [x] `stages/validate.py` — Deterministic checks + Reviewer, results persisted to SQLite
- [x] `stages/learn.py` — Failure classification, skill usage tracking, SQLite persistence
- [x] `budget.py` — Cost ceiling enforcement
- [x] `task_router.py` — Task classification and skill routing
- [x] `cli.py` — `harness-ctl` (submit, status, budget, list, approve, reject, register, projects, feedback)

### Packages
- [x] `packages/llm/router.py` — Model routing with fallback, rate limit retry (exponential backoff), cost tracking
- [x] `packages/llm/providers/` — Pluggable provider system (replaced litellm after supply chain compromise)
- [x] `packages/llm/prompt_loader.py` — Versioned prompt loading from `prompts/{role}/`
- [x] `packages/state/sqlite_store.py` — Full CRUD (tasks, evals, failures, metrics, skill usage)
- [x] `packages/state/task_state.py` — File-based task directory management
- [x] `packages/repo_intel/codegraph_adapter.py` — codegraph CLI wrapper (connected to agents, backed by optave v3.3.1)
- [x] `packages/repo_intel/codegraph_manager.py` — registration-time codegraph build/provisioning helpers
- [x] `packages/repo_intel/agents_md.py` — AGENTS.md parser/injector
- [x] `packages/stage_manager/worktree.py` — Git worktree lifecycle
- [x] `packages/stage_manager/tmux.py` — tmux session management
- [x] `packages/eval/deterministic.py` — Schema, tests, boundaries, blast radius, budget checks
- [x] `packages/eval/promptfoo_runner.py` — Promptfoo CLI wrapper with project-aware external eval output paths
- [x] `packages/learning/community_feedback.py` — Harness-level, repo-agnostic feedback event log for cross-project improvement analysis
- [x] `packages/learning/community_exchange.py` — Consent/status/export helpers for upstream community feedback sharing
- [x] `packages/notifications/telegram_bot.py` — Full bot with commands + inline buttons
- [x] `packages/notifications/formatters.py` — MarkdownV2 message formatting

### Config
- [x] `config/model_routing.yaml` — Opus 4.6 / Sonnet 4.6 / GPT-5.4-mini routing
- [x] `config/harness.yaml` — Global harness configuration
- [x] `config/harness.yaml.example` — Template for new installations
- [x] `config/marketing_servers.yaml` — MCP server registry (Google Ads, GA4, GSC, X, LinkedIn)
- [x] `config/eval_config.yaml` — Eval configuration (promptfoo + deterministic)

### Skills & Prompts
- [x] 3 code skills (safe_refactor, bug_trace, review_diff)
- [x] All 12 prompt files (identity/policy/procedure/output_contract × 3 agents)

### Evals
- [x] `evals/regressions/test_safe_refactor.yaml` — 7 test cases
- [x] `evals/regressions/test_review_diff.yaml` — 7 test cases
- [x] `evals/adversarial/red_team.yaml` — 16 adversarial test cases

### Scripts
- [x] `scripts/setup.sh` — VPS setup (Python, Node, nginx, systemd, security hardening)
- [x] `scripts/deploy.sh` — rsync deploy to VPS with service restart
- [x] `scripts/backup.sh` — SQLite/KùzuDB/traces backup with optional GPG encryption

### Multi-Project Architecture
- [x] `README.md` — Full documentation with architecture, quick start, multi-project usage, self-improvement loop, contribution guide
- [x] `LICENSE` — Apache 2.0
- [x] `harness-ctl register` — Auto-creates AGENTS.md, builds codegraph, creates per-project data dirs
- [x] `harness-ctl projects` — List registered projects
- [x] `harness-ctl feedback` — Consent, status, and export flow for anonymized community feedback bundles
- [x] Per-project isolation (separate SQLite, learning data, eval outputs, worktrees, config overrides; codegraph builds by default and is kept untracked via `.gitignore` or `.git/info/exclude`)

### Tests (60 passing)
- [x] `tests/unit/test_sqlite_store.py` — 10 tests
- [x] `tests/unit/test_budget.py` — 10 tests
- [x] `tests/unit/test_deterministic_eval.py` — 10 tests
- [x] `tests/unit/test_llm_router.py` — 8 tests (model resolution, usage tracking)
- [x] `tests/unit/test_task_state.py` — 10 tests
- [x] `tests/integration/test_pipeline.py` — 6 tests (graph build, intake, plan)
- [x] `tests/conftest.py` — Shared fixtures

### End-to-End Pipeline (verified)
- [x] Full pipeline run: intake → plan → execute → validate → route → learn
- [x] Planner produces plans via Claude Code CLI (Opus 4.6, 0.92 confidence)
- [x] Worker executes via Anthropic API (Sonnet 4.6)
- [x] Reviewer invoked when validation warrants it
- [x] Retry loop works (3 retries, then moves to learn)
- [x] Learn stage classifies failures and records to SQLite
- [x] OpenAI fallback works when Anthropic rate limited

---

## What's Remaining

### Phase 1 — Hardening

#### Bugs / Fixes
- [x] **LLM Router rate limit retry/backoff** — 5 retries with exponential backoff (2s → 32s) on 429 errors
- [ ] **Plan step key alignment** — Opus returns `plan_steps` with rich objects but validator expects specific structure; parser needs to be more flexible
- [ ] **Worker/Reviewer Claude Code CLI routing** — Same Max plan benefit as planner; reduces API spend
- [ ] **CodegraphAdapter CLI interface alignment** — Adapter needs update for optave v3.3.1 commands (`where`, `context`, `fn-impact`, `search`)

#### Integration Testing
- [ ] Live budget enforcement test (kill over-budget task)
- [ ] Telegram bot command verification
- [ ] Run Promptfoo regression suite
- [ ] Run red-team adversarial suite

#### Remaining
- [ ] `config/projects/` — per-project config override examples

### Phase 2 — Marketing + Eval (Weeks 4-6)

#### Marketing Adapter
- [ ] `apps/marketing_adapter/registry.py` — MCP server registry
- [ ] `apps/marketing_adapter/tools.py` — Marketing tool wrappers
- [ ] `apps/marketing_adapter/metrics_collector.py` — Periodic metrics ingestion
- [ ] Google Ads, GA4, GSC, X/Twitter, LinkedIn MCP connections + OAuth

#### Marketing Skills & Evals
- [ ] `skills/marketing/seo_content.v1.md` — SEO content skill
- [ ] `skills/marketing/social_campaign.v1.md` — Social campaign skill
- [ ] `evals/marketing/test_seo_content.yaml`
- [ ] `evals/marketing/test_social_campaign.yaml`
- [ ] `packages/eval/marketing_eval.py` — Campaign performance evaluation

#### DeepEval Integration
- [ ] Behavioral regression test suite
- [ ] Task-specific correctness checks

#### Failure Classification
- [ ] Automated failure clustering into taxonomy buckets
- [ ] Failure trend dashboard in Phoenix

### Phase 3 — Self-Improvement Loop (Weeks 7-10)

The self-improvement loop is how the harness gets better over time. It operates at three levels: per-project learning, cross-project pattern detection, and harness-level improvement PRs.

#### Level 1: Per-Project Learning (automatic)

Each project accumulates failure data that adjusts skill confidence and selection locally.

- [x] `stages/learn.py` — Failure classification into 4 buckets (routing, retrieval, execution, eval_mismatch) — **delivered**
- [x] `sqlite_store.py` — `record_failure()`, `record_skill_usage()`, `get_failure_stats()` — **delivered**
- [ ] `packages/learning/project_learner.py` — Per-project confidence adjustment based on accumulated failure rates per skill
- [ ] `packages/learning/failure_taxonomy.py` — Enriched taxonomy with sub-categories (e.g., `execution_failure.cross_module_rename`, `retrieval_failure.stale_codegraph`)
- [ ] Skill selection weighting — adjust `skill_registry.find_best_skill()` confidence based on historical success rate
- [ ] Automatic codegraph rebuild trigger when `retrieval_failure` rate exceeds threshold

#### Level 2: Cross-Project Pattern Detection (semi-automatic)

Detects failure patterns that appear across multiple projects — systemic harness issues vs project-specific issues.

- [ ] `packages/learning/cross_project_analyzer.py` — Queries all project SQLite databases, clusters failures by (skill_id, failure_category, sub_category)
- [ ] `packages/learning/pattern_detector.py` — Statistical significance test: is this failure rate higher than baseline? Does it appear in 2+ projects?
- [ ] `harness-ctl analyze-failures` — CLI command: `--cross-project`, `--since <duration>`, `--skill <skill_id>`, `--min-projects <n>`
- [ ] Pattern report format — JSON output with: pattern_id, affected_skill, failure_category, affected_projects (anonymized), failure_rate, sample_count, root_cause_hypothesis, confidence
- [ ] Anonymization layer — strip project names, file paths, code content; retain only skill_id, failure_category, model_used, token_count

#### Level 3: Harness Improvement PRs (human-gated)

When a cross-project pattern is detected, the harness proposes a fix and generates a PR.

- [ ] `packages/learning/improvement_proposer.py` — Generates skill patch (new version) and eval test cases targeting the failure mode
- [ ] `packages/learning/offline_eval.py` — Runs patched skill against historical failures + holdout set, compares pass rates
- [ ] `harness-ctl propose-improvement` — CLI command that generates a git branch with:
  - New skill version file (e.g., `safe_refactor.v2.md`)
  - Updated eval suite with regression cases
  - `improvement_report.md` with anonymized evidence, eval deltas, holdout results
- [ ] `harness-ctl apply-improvement` — Applies a proposed improvement locally (canary mode)
- [ ] Canary rollout logic — route 10% of matching tasks to new skill version, compare outcomes, promote or rollback
- [ ] PR template generation — formats improvement as a GitHub PR body with evidence table and metrics

**No improvement ships without human approval. The harness never self-merges.**

#### Skill Graph (KùzuDB)

- [ ] `packages/state/kuzu_store.py` — Graph operations (create/query skill relationships)
- [ ] KùzuDB schema: nodes (Skill, Evaluator, ArtifactSchema, RecoveryPattern, PromptVersion, TaskType), edges (REQUIRES, VALIDATED_BY, PRODUCES, SUPERSEDES, BEST_FOR, CONFLICTS_WITH)
- [ ] Skill graph projection — auto-populate from git-backed skill markdown files
- [ ] Skill versioning and supersession — `safe_refactor.v2` supersedes `v1`, routing stops sending to v1
- [ ] Prompt version registry — track which prompt version was used per task, correlate with outcomes

#### Skill Maintainer Agent

- [ ] `apps/orchestrator/agents/skill_maintainer.py` — Agent that reads failure clusters, proposes skill patches, runs offline evals
- [ ] Skill Maintainer prompt/persona (`prompts/skill_maintainer/`)
- [ ] Activates only when sufficient failure data exists (minimum 20 failures per pattern)
- [ ] Human approval gate for all skill changes

### Phase 4 — Scale + Advanced (Weeks 11+)

- [ ] Eval Judge agent — automated failure classification and quality scoring
- [ ] Multi-repo support — cross-repo skill sharing and context
- [ ] Async GitHub issue resolver — SWE-style issue-to-PR automation
- [ ] Nightly maintenance jobs — automated code health checks, content calendar execution
- [ ] Container isolation (Docker/Podman) — task sandboxing
- [ ] Neo4j migration — if KùzuDB graph traversals become a bottleneck
- [ ] A/B testing framework for marketing skills
- [ ] Historical eval trend dashboards

### Documentation

- [ ] `docs/architecture.md`
- [ ] `docs/runbooks/adding_a_skill.md`
- [ ] `docs/runbooks/adding_a_marketing_platform.md`
- [ ] `docs/runbooks/debugging_failures.md`
- [ ] `docs/ADRs/001_litellm_over_direct_apis.md`
- [ ] `docs/ADRs/002_sqlite_over_neo4j.md`
- [ ] `docs/ADRs/003_codegraph_as_primary_repo_intel.md`

---

## Architecture

### Model Routing

| Role | Model | Route | Billing |
|------|-------|-------|---------|
| **Planner** | Opus 4.6 | Claude Code CLI (`claude --print`) | Max subscription |
| **Worker** | Sonnet 4.6 | Direct Anthropic SDK | API credits |
| **Reviewer** | Sonnet 4.6 | Direct Anthropic SDK | API credits |
| **Content** | Sonnet 4.6 | Direct Anthropic SDK | API credits |
| **Eval Judge** | Sonnet 4.6 | Direct Anthropic SDK | API credits |
| **Lightweight** | GPT-5.4-mini | Direct OpenAI SDK | OpenAI credits |

All roles fall back to OpenAI/gpt-5.4-mini if primary provider fails.

### Provider Architecture (post-litellm removal)

litellm was removed on 2026-03-24 after versions 1.82.7+ were found to contain supply chain malware (credential theft, Kubernetes lateral movement). Replaced with a thin adapter pattern:

```
packages/llm/providers/
  base.py              # LLMProvider interface + LLMResponse (~30 lines)
  anthropic_provider.py # Anthropic Messages API (~40 lines)
  openai_provider.py    # OpenAI Chat Completions (~40 lines)
  google_provider.py    # Gemini (optional, auto-registers if google-genai installed)
  __init__.py           # Provider registry with auto-discovery
```

Adding a new provider (Grok, Ollama, Mistral, etc.) = one file implementing `complete()` and `acomplete()`. No monolithic routing library needed.

### Repo Intelligence (codegraph)

| Capability | Command | Latency | Token Cost |
|-----------|---------|---------|------------|
| Symbol lookup | `codegraph where <name>` | <50ms | 0 |
| Full context (source, deps, callers) | `codegraph context <name>` | <100ms | 0 |
| Function-level impact | `codegraph fn-impact <name>` | <100ms | 0 |
| Data flow tracing | `codegraph dataflow <name>` | <100ms | 0 |
| Diff impact analysis | `codegraph diff-impact` | <100ms | 0 |
| Co-change analysis | `codegraph co-change <file>` | <100ms | 0 |
| Complexity metrics | `codegraph complexity` | <50ms | 0 |
| Role classification | `codegraph roles` | <50ms | 0 |
| Semantic search | `codegraph search "query"` | ~500ms | 0 |
| Execution flow tracing | `codegraph flow <entry>` | <100ms | 0 |

All queries are local (SQLite + embeddings). Zero API calls, zero tokens consumed.

---

## File Inventory

**~83 files delivered** across all phases.

```
apps/orchestrator/          14 files  (complete for Phase 1)
packages/                   23 files  (complete for Phase 1; includes provider adapters; +5 for Phase 3 learning)
config/                      5 files  (complete; +per-project overrides as projects are added)
skills/code/                 3 files  (complete; +marketing skills in Phase 2)
prompts/                    12 files  (complete; +skill_maintainer persona in Phase 3)
evals/                       3 files  (complete for Phase 1; +marketing evals in Phase 2)
scripts/                     3 files  (complete)
docs/                        1 file   (this file; +architecture, runbooks, ADRs pending)
tests/                       9 files  (60 tests passing)
root                         6 files  (pyproject.toml, requirements.txt, .gitignore, spec, README, LICENSE)
```

### Files Still Needed (by phase)

**Phase 2 — Marketing:**
```
apps/marketing_adapter/registry.py
apps/marketing_adapter/tools.py
apps/marketing_adapter/metrics_collector.py
packages/eval/marketing_eval.py
skills/marketing/seo_content.v1.md
skills/marketing/social_campaign.v1.md
evals/marketing/test_seo_content.yaml
evals/marketing/test_social_campaign.yaml
```

**Phase 3 — Self-Improvement:**
```
packages/learning/__init__.py
packages/learning/project_learner.py         # Per-project confidence adjustment
packages/learning/failure_taxonomy.py        # Enriched failure sub-categories
packages/learning/cross_project_analyzer.py  # Multi-project failure clustering
packages/learning/pattern_detector.py        # Statistical significance testing
packages/learning/improvement_proposer.py    # Skill patch generation
packages/learning/offline_eval.py            # Before/after eval comparison
packages/state/kuzu_store.py                 # KùzuDB graph operations
apps/orchestrator/agents/skill_maintainer.py # Skill Maintainer agent
prompts/skill_maintainer/identity.md
prompts/skill_maintainer/policy.md
prompts/skill_maintainer/procedure.md
prompts/skill_maintainer/output_contract.json
```

**Documentation:**
```
docs/architecture.md
docs/runbooks/adding_a_skill.md
docs/runbooks/adding_a_marketing_platform.md
docs/runbooks/debugging_failures.md
docs/ADRs/001_litellm_over_direct_apis.md
docs/ADRs/002_sqlite_over_neo4j.md
docs/ADRs/003_codegraph_as_primary_repo_intel.md
```

---

## Delivery Summary

### What's Shipped (Phase 1)

| Component | Status | Files | Tests |
|-----------|--------|-------|-------|
| LangGraph orchestrator | Complete | 14 | 6 integration |
| 3 agents (Planner/Worker/Reviewer) | Wired to real implementations | 3 | mocked in integration |
| LLM Router + Provider SDKs | Complete, direct SDKs (litellm removed) | 6 | 8 unit |
| SQLite state store | Complete | 1 | 10 unit |
| Task state manager | Complete | 1 | 10 unit |
| Budget enforcer | Complete | 1 | 10 unit |
| Deterministic evaluator | Complete | 1 | 10 unit |
| Codegraph adapter | Complete, needs CLI alignment | 1 | — |
| AGENTS.md parser | Complete | 1 | — |
| Worktree manager | Complete | 1 | — |
| tmux manager | Complete | 1 | — |
| Promptfoo runner | Complete | 1 | — |
| Telegram bot | Complete | 2 | — |
| Prompt loader | Complete | 1 | — |
| CLI (harness-ctl) | 8 commands | 1 | — |
| Project registry | Complete (register, projects) | 1 | — |
| Skills | 3 code skills | 3 | 14 promptfoo cases |
| Prompts | 12 files (3 agents × 4 files) | 12 | 16 red-team cases |
| Config | 5 files | 5 | — |
| Scripts | setup, deploy, backup | 3 | — |
| Tests | 60 passing | 9 | — |
| README + LICENSE | Complete | 2 | — |
| **Total** | | **~83** | **60** |

### What's Not Shipped Yet

| Component | Phase | Blocker | Files Needed |
|-----------|-------|---------|-------------|
| Per-project learning (confidence adjustment) | 3 | Needs failure data accumulation | 2 |
| Cross-project pattern detection | 3 | Needs 2+ projects with failure data | 3 |
| Improvement proposal + PR generation | 3 | Needs pattern detection | 3 |
| Skill graph (KùzuDB) | 3 | Needs kuzu_store.py | 1 |
| Skill Maintainer agent | 3 | Needs improvement proposer | 5 |
| Canary rollout | 3 | Needs skill versioning | 1 |
| Marketing adapter (MCP) | 2 | Needs platform OAuth setup | 3 |
| Marketing skills | 2 | Needs marketing adapter | 2 |
| Marketing evals | 2 | Needs marketing skills | 3 |
| DeepEval integration | 2 | Needs failure data | 2 |
| Documentation (runbooks, ADRs) | Ongoing | — | 7 |

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM interface | Direct provider SDKs (anthropic, openai, google-genai) | litellm removed after supply chain attack (v1.82.7+, 2026-03-24). Thin adapter pattern — one ~40-line file per provider, zero monolithic dependencies. |
| Orchestration | LangGraph | Production-proven stateful graphs, durable execution, checkpointing |
| Planner routing | Claude Code CLI | Uses Max subscription for expensive Opus calls |
| Worker/Reviewer routing | Anthropic API via LiteLLM | Cheaper Sonnet calls with automatic fallback |
| Repo intelligence | Optave codegraph v3.3.1 | Local, zero API cost, 40+ commands, semantic search |
| Data store | SQLite + KùzuDB (Phase 3) | Zero infrastructure overhead, embedded |
| Tracing | Phoenix + OpenTelemetry | Self-hosted, no outbound telemetry |
| Evals | Promptfoo (Phase 1), DeepEval (Phase 2) | CI-friendly, YAML-based |
| Notifications | Telegram bot | HITL approvals, task submission, status monitoring |
| Deployment | systemd on VPS | Minimum overhead, fastest iteration |
| License | Apache 2.0 | Permissive, standard for dev tools |
