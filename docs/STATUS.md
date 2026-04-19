# BOBCODE Status

**Last Updated:** 2026-04-19
**Branch Focus:** Local-first repo harness

## Current Direction

BOBCODE is being simplified from a VPS/Telegram-managed harness into a local-first CLI harness that can be initialized inside any git repository.

The core retained pieces are:

- LangGraph task pipeline
- Planner / Worker / Reviewer roles
- codegraph-backed repository intelligence
- git worktree isolation
- deterministic validation
- browser evidence for UI tasks
- SQLite and JSONL task state
- project-scoped learning and feedback export

The removed/default-off pieces are:

- Telegram bot control plane
- VPS deployment scripts
- systemd/nginx setup path
- Telegram dependency

## Implemented On This Branch

- [x] `harness-ctl init [path]`
  - creates repo-local `.bobcode/`
  - creates `bobcode.json`
  - creates `feature_list.json`
  - creates `progress.jsonl`
  - adds `.bobcode/` and `.codegraph/` to `.git/info/exclude`
  - builds codegraph unless `--skip-codegraph` is passed

- [x] `harness-ctl doctor [path]`
  - verifies git repo
  - verifies `.bobcode/` and `bobcode.json`
  - checks codegraph binary/artifact
  - checks provider API key presence
  - checks browser daemon package
  - reports build/test/lint command detection

- [x] `harness-ctl inbox`
  - shows tasks that are not terminal
  - includes current repo-local tasks by default

- [x] Direct repo task submission
  - `harness-ctl submit "task"` now defaults to the current git repo
  - task state resolves under `<repo>/.bobcode/`

- [x] Telegram removal
  - removed `python-telegram-bot` from dependencies
  - removed Telegram bot and MarkdownV2 formatter modules
  - removed Telegram runtime tests
  - removed Telegram config from default config files

- [x] Docs updated for local-first usage
  - `README.md`
  - `agent-harness-spec.md`

## Still To Do

- [ ] Add bounded `file_view` with line numbers.
- [ ] Add line-bounded edit tool with immediate lint/syntax feedback.
- [ ] Add capped repo search tool with narrowing guidance.
- [ ] Normalize agent tool responses to `status`, `summary`, `artifacts`, and `next_actions`.
- [ ] Append progress events to `.bobcode/progress.jsonl` at task boundaries.
- [ ] Update `feature_list.json` from verified task completions.
- [ ] Hide ephemeral task branches behind a single integration branch.
- [ ] Auto-rebuild codegraph after structural edits or retrieval failure clusters.
- [ ] Add `harness-ctl learn report`.
- [ ] Add focused tests for `init`, `doctor`, and `inbox`.

## Known Issues

- Plan step key alignment remains imperfect: planner output can include richer `plan_steps` objects than downstream validators expect.
- `CodegraphAdapter` still needs a deeper compatibility pass against the currently installed optave codegraph CLI.
- Worker tools still expose broad `file_write` and `shell_run`; these are next in line for harness-quality improvements.
- UI completion still relies on prompt discipline to use browser evidence; deterministic enforcement is not complete yet.

## Validation Targets

Minimum local flow:

```bash
harness-ctl init .
harness-ctl doctor
harness-ctl submit "small local task"
harness-ctl inbox
harness-ctl status TASK-001
```

Focused tests:

```bash
pytest tests/unit/test_runtime_paths.py tests/unit/test_cli_register_helpers.py tests/integration/test_pipeline.py
```
