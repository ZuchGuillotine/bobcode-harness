# Browser Daemon V1 Spec

## Purpose

Add a limited browser subsystem to the harness so planner, worker, and reviewer flows can verify live localhost output quickly without cold-starting a browser on every action.

V1 is intentionally narrow:
- persistent Playwright session per project
- localhost-only daemon with bearer-token auth
- headless by default
- fast command API for navigation, snapshot, screenshot, and simple interaction
- evidence capture for validation

V1 does not include:
- gstack telemetry or contributor flows
- slash-command UX
- Chrome side panel extension
- cookie import from real browsers
- child browser agents
- production-site automation as a default path

## Why This Fits This Repo

The harness already has:
- per-project runtime storage in `data/projects/<project>/...`
- stage boundaries at intake, plan, execute, validate, learn
- worker and reviewer tool loops

Relevant local integration points:
- `packages/config/runtime.py`
- `apps/orchestrator/stages/execute.py`
- `apps/orchestrator/stages/validate.py`
- `apps/orchestrator/agents/worker.py`
- `apps/orchestrator/agents/reviewer.py`
- `apps/orchestrator/task_router.py`

The current repo does not have:
- browser lifecycle management
- browser evidence artifacts
- browser-aware skill routing

## Architecture

V1 uses a Python-controlled Node sidecar.

Rationale:
- the harness is already Python-first
- Playwright support in Node is mature and simpler than adding Bun as a second runtime standard
- a sidecar keeps browser process crashes isolated from orchestrator state
- we can preserve the same daemon model gstack uses without importing its full toolchain

High-level flow:

1. Harness resolves `ProjectPaths`.
2. A Python `BrowserDaemonClient` checks the project browser state file.
3. If missing or unhealthy, Python spawns the Node daemon.
4. The daemon launches a persistent Playwright Chromium context.
5. Worker and reviewer tools issue HTTP requests to the daemon.
6. The daemon returns plain JSON plus artifact paths for screenshots and logs.

## File Layout

Add the following files:

```text
packages/browser_daemon/
  __init__.py
  client.py
  models.py
  manager.py

tools/browser-daemon/
  package.json
  src/server.ts
  src/session.ts
  src/refs.ts
  src/commands.ts
  src/state.ts
  src/logs.ts

tests/unit/
  test_browser_daemon_client.py
  test_browser_runtime_paths.py

tests/integration/
  test_browser_daemon_lifecycle.py
  test_browser_validate_flow.py
```

Per-project runtime files:

```text
data/projects/<project>/browser/
  daemon.json
  console.log
  network.log
  session/
  artifacts/
```

## Runtime Paths

Extend `ProjectPaths` with:
- `browser_dir`
- `browser_state_file`
- `browser_artifacts_dir`
- `browser_console_log`
- `browser_network_log`

`ensure_dirs()` should create these directories.

Do not store browser runtime state in the repo worktree. Keep it under the existing project data directory.

## Daemon Process Model

The daemon is a single-process HTTP server bound to `127.0.0.1` only.

Startup behavior:
- choose a random port in a safe high range
- generate a random bearer token
- write `daemon.json` atomically with mode `0600`
- launch Chromium and one browser context
- create an initial blank page

Shutdown behavior:
- stop after 30 minutes idle
- close context and browser cleanly
- remove `daemon.json`

Crash behavior:
- if Chromium disconnects, the daemon exits
- the Python client treats this as unhealthy and starts a fresh daemon on the next request
- do not attempt in-process self-healing in V1

## State File Contract

`daemon.json` schema:

```json
{
  "pid": 12345,
  "port": 34123,
  "token": "uuid-or-random-hex",
  "started_at": "2026-03-27T12:34:56Z",
  "last_seen_at": "2026-03-27T12:35:10Z",
  "mode": "headless",
  "version": "v1"
}
```

The Python client must trust health checks over PID checks.

## HTTP API

### `GET /health`

No auth required.

Response:

```json
{
  "status": "healthy",
  "mode": "headless",
  "current_url": "http://localhost:3000/",
  "tabs": 1,
  "version": "v1"
}
```

### `POST /command`

Auth required: `Authorization: Bearer <token>`

Request:

```json
{
  "command": "snapshot",
  "args": ["-i"]
}
```

Response:

```json
{
  "ok": true,
  "command": "snapshot",
  "result": {
    "text": "...",
    "current_url": "http://localhost:3000/",
    "artifacts": []
  }
}
```

### `GET /logs/console`

Auth required.

Returns the last N console events.

### `GET /logs/network`

Auth required.

Returns the last N network events.

## Supported V1 Commands

Required:
- `status`
- `goto <url>`
- `snapshot`
- `screenshot [name]`
- `click <ref>`
- `type <ref> <text>`
- `press <key>`
- `wait-for <selector-or-ms>`
- `eval <js>`
- `console`
- `network`
- `new-tab [url]`
- `close-tab [id]`

Optional if implementation is still clean:
- `resize <preset>`
- `reload`

Deferred to V2:
- `connect`
- `disconnect`
- `cookie-import-browser`
- `handoff`
- `watch`
- `perf`

## Ref System

V1 should include lightweight ref-based interaction.

Behavior:
- `snapshot` builds a text snapshot of the current page
- interactive elements get stable refs like `@e1`, `@e2`
- refs are stored in daemon memory only
- refs are cleared on navigation
- command handlers resolve refs to Playwright locators

Implementation guidance:
- prefer accessibility-role based locators
- if a ref becomes stale, return a fast explicit error telling the agent to run `snapshot` again
- do not mutate the DOM to inject identifiers

## Logging and Evidence

The daemon should collect:
- browser console events
- network failures and non-2xx/3xx responses
- screenshots saved into `browser/artifacts/`

Worker/reviewer artifact payload shape:

```json
{
  "type": "browser_evidence",
  "path": "data/projects/<project>/browser/artifacts/homepage.png",
  "metadata": {
    "url": "http://localhost:3000/",
    "command": "screenshot",
    "timestamp": "2026-03-27T12:40:00Z"
  }
}
```

## Python Control Layer

Add `packages/browser_daemon/client.py` with:
- `ensure_running(project_paths) -> BrowserSessionInfo`
- `health(project_paths) -> dict`
- `command(project_paths, command, args) -> dict`
- `stop(project_paths) -> None`

Add `packages/browser_daemon/manager.py` with:
- spawn logic
- state-file reads
- health-check retries
- daemon version checks

The Python layer is the only code the orchestrator should call directly.

## Worker Integration

Extend worker tool definitions with:
- `browser_status`
- `browser_goto`
- `browser_snapshot`
- `browser_screenshot`
- `browser_click`
- `browser_type`
- `browser_console`
- `browser_network`

Execution rules:
- worker may use browser tools only when the selected skill or plan requires browser verification
- browser actions should be limited to localhost or explicit project URLs in V1
- worker must attach screenshot or snapshot artifacts when it claims UI verification

## Reviewer Integration

Extend reviewer tools with:
- `browser_artifact_read`
- `browser_console_read`
- `browser_network_read`

Reviewer use cases:
- confirm the page loaded
- check console cleanliness
- verify expected visual or DOM state from artifacts
- reject completion when browser verification was required but missing

## Planner Integration

Planner does not need direct browser control in V1.

It does need two new planning fields:
- `requires_browser_verification: bool`
- `verification_targets: list[str]`

Routing heuristics:
- tasks mentioning UI, page, screen, localhost, browser, screenshot, layout, form, interaction, or visual behavior should set browser verification
- imported `browse`, `qa-only`, and `benchmark` skills should bias plans toward browser evidence

## Validation Changes

Add deterministic checks in `validate.py`:
- if `requires_browser_verification` is true, fail validation when no `browser_evidence` artifact exists
- fail validation when browser console logs include uncaught runtime errors unless explicitly waived in the plan
- record browser verification summary in `eval_results`

## Security Rules

Required:
- bind only to `127.0.0.1`
- require bearer token on all command and log routes
- write state file with owner-only permissions
- reject non-http(s) URLs except `about:blank`
- allow `localhost`, `127.0.0.1`, and explicit project URLs
- cap `eval` execution time

Out of scope for V1:
- importing real browser cookies
- decrypting browser profiles
- extension-based chat

## Dependencies

Node sidecar:
- `playwright`
- one lightweight HTTP server library only if native Node HTTP becomes noisy

Python harness:
- no new heavyweight dependency required

## Testing

Unit tests:
- state-file parsing
- health fallback when PID is stale
- auth header enforcement
- runtime path creation

Integration tests:
- daemon boot on first command
- daemon reuse on second command
- idle shutdown behavior
- worker browser artifact creation
- validation failure when browser evidence is required but missing

Fixture app coverage:
- plain HTML page
- simple SPA route
- form interaction
- console-error page

## Delivery Plan

### Milestone 1
- runtime path extension
- Python client and manager
- Node daemon with `health`, `status`, `goto`, `snapshot`, `screenshot`

### Milestone 2
- ref system
- `click`, `type`, `press`, `new-tab`, `close-tab`
- console and network log capture

### Milestone 3
- worker tool integration
- reviewer artifact integration
- validation gates

### Milestone 4
- benchmark-specific support
- optional headed mode design for V2

## Acceptance Criteria

V1 is complete when:
- the harness can boot a browser daemon on demand for a project
- the daemon persists across multiple commands
- worker can verify a localhost page and attach screenshot evidence
- reviewer can inspect that evidence
- validation can deterministically fail missing browser verification
- the entire flow works without any gstack-specific global install or CLI wrapper
