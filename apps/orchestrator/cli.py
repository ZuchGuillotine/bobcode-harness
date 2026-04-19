"""harness-ctl — CLI for the agent harness orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from packages.config import (
    find_task_dir,
    get_config_dir,
    get_data_dir,
    get_project_paths,
    iter_registered_projects,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_task_roots(project_name: str | None = None) -> list[tuple[str | None, Path]]:
    """Return the task roots to search for task state."""
    if project_name:
        paths = get_project_paths(project_name=project_name)
        return [(project_name, paths.tasks_dir)]

    roots: list[tuple[str | None, Path]] = []
    seen: set[Path] = set()

    current_repo = _current_git_repo()
    if current_repo is not None:
        paths = get_project_paths(repo_path=str(current_repo))
        roots.append((paths.project_name, paths.tasks_dir))
        seen.add(paths.tasks_dir)

    for name, _ in iter_registered_projects():
        tasks_dir = get_project_paths(project_name=name).tasks_dir
        if tasks_dir in seen:
            continue
        roots.append((name, tasks_dir))
        seen.add(tasks_dir)

    legacy = get_project_paths()
    if current_repo is None and legacy.tasks_dir.is_dir() and legacy.tasks_dir not in seen:
        roots.append((None, legacy.tasks_dir))
    return roots


def _load_task(
    task_id: str,
    project_name: str | None = None,
) -> tuple[str | None, Path, dict[str, Any]] | None:
    """Load a task manifest and return ``(project_name, task_dir, manifest)``."""
    if project_name:
        located = find_task_dir(task_id, project_name=project_name)
        if not located:
            return None
        located_project, task_dir = located
    else:
        located_project = None
        task_dir: Path | None = None
        for candidate_project, tasks_dir in _iter_task_roots():
            candidate = tasks_dir / task_id
            if candidate.is_dir():
                located_project = candidate_project
                task_dir = candidate
                break
        if task_dir is None:
            return None

    manifest_path = task_dir / "manifest.json"
    if not manifest_path.is_file():
        return None

    with manifest_path.open() as f:
        manifest = json.load(f)

    if located_project and not manifest.get("project_name"):
        manifest["project_name"] = located_project

    return located_project, task_dir, manifest


def _list_tasks(
    project_name: str | None = None,
) -> list[tuple[str | None, str, Path, dict[str, Any]]]:
    """List all tasks across registered projects or a single project."""
    tasks: list[tuple[str | None, str, Path, dict[str, Any]]] = []
    for name, tasks_dir in _iter_task_roots(project_name):
        if not tasks_dir.is_dir():
            continue
        task_dirs = (
            p for p in tasks_dir.iterdir()
            if p.is_dir() and p.name.startswith("TASK-")
        )
        for task_dir in sorted(task_dirs):
            manifest_path = task_dir / "manifest.json"
            manifest: dict[str, Any] = {}
            if manifest_path.is_file():
                with manifest_path.open() as f:
                    manifest = json.load(f)
            tasks.append((name, task_dir.name, task_dir, manifest))
    return tasks


def _detect_repo_context(repo_path: str) -> dict[str, str]:
    """Infer basic language/build/test/lint commands from the repo shape."""
    language = "Unknown"
    build_cmd = "# TODO"
    test_cmd = "# TODO"
    lint_cmd = "# TODO"

    if os.path.exists(os.path.join(repo_path, "pyproject.toml")):
        language = "Python"
        build_cmd = "pip install -e ."
        test_cmd = "pytest tests/"
        lint_cmd = "ruff check ."
    elif os.path.exists(os.path.join(repo_path, "package.json")):
        language = "JavaScript/TypeScript"
        build_cmd = "npm install"
        test_cmd = "npm test"
        lint_cmd = "npm run lint"
    elif os.path.exists(os.path.join(repo_path, "go.mod")):
        language = "Go"
        build_cmd = "go build ./..."
        test_cmd = "go test ./..."
        lint_cmd = "golangci-lint run"
    elif os.path.exists(os.path.join(repo_path, "Cargo.toml")):
        language = "Rust"
        build_cmd = "cargo build"
        test_cmd = "cargo test"
        lint_cmd = "cargo clippy"

    return {
        "language": language,
        "build_cmd": build_cmd,
        "test_cmd": test_cmd,
        "lint_cmd": lint_cmd,
    }


def _print_json(data: Any) -> None:
    """Pretty-print a JSON-serialisable object."""
    print(json.dumps(data, indent=2, default=str))


def _read_json_file(path: Path) -> dict[str, Any] | list[Any] | None:
    """Read a JSON file, returning None when it is missing or invalid."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _append_jsonl(path: Path, event: dict[str, Any]) -> None:
    """Append one JSON event to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")


def _slugify(value: str) -> str:
    """Return a branch-safe slug."""
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-._")
    return slug or "agent-task"


def _task_status_payload(
    project_name: str | None,
    task_dir: Path,
    manifest: dict[str, Any],
    shallow: bool = False,
) -> dict[str, Any]:
    """Build a stable machine-readable task status payload."""
    eval_data = _read_json_file(task_dir / "evals" / "validation.json")
    payload: dict[str, Any] = {
        **manifest,
        "project_name": manifest.get("project_name") or project_name,
        "task_dir": str(task_dir),
        "state_path": str(task_dir / "state.json"),
        "plan_path": str(task_dir / "plan.json"),
        "progress_path": str(task_dir / "progress.jsonl"),
        "eval_results": eval_data,
    }
    if not shallow:
        state_data = _read_json_file(task_dir / "state.json")
        plan_data = _read_json_file(task_dir / "plan.json")
        if state_data is not None:
            payload["state"] = state_data
        if plan_data is not None:
            payload["plan"] = plan_data
    return payload


def _load_harness_yaml() -> tuple[Path, dict[str, Any]]:
    """Load ``config/harness.yaml`` if present."""
    import yaml

    path = get_config_dir() / "harness.yaml"
    if not path.is_file():
        return path, {}
    with path.open() as fh:
        return path, yaml.safe_load(fh) or {}


def _save_harness_yaml(path: Path, data: dict[str, Any]) -> None:
    """Persist ``config/harness.yaml``."""
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False)


def _upsert_lines(path: Path, entries: list[str]) -> list[str]:
    """Append ignore entries if missing and return newly-added lines."""
    existing_lines: list[str] = []
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    added: list[str] = []
    for entry in entries:
        if entry not in existing_lines:
            existing_lines.append(entry)
            added.append(entry)

    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")

    return added


def _ensure_codegraph_ignore(repo_path: Path, mode: str) -> tuple[Path, list[str]]:
    """Keep repo-local codegraph artifacts out of version control."""
    ignore_path = (
        repo_path / ".gitignore" if mode == "assisted"
        else repo_path / ".git" / "info" / "exclude"
    )
    added = _upsert_lines(ignore_path, [".codegraph/"])
    return ignore_path, added


def _build_agents_md(project_name: str, repo_context: dict[str, str]) -> str:
    """Return the default AGENTS.md template for assisted mode."""
    return f"""# AGENTS.md

## Project: {project_name}
## Language: {repo_context["language"]}
## Build: {repo_context["build_cmd"]}
## Test: {repo_context["test_cmd"]}
## Lint: {repo_context["lint_cmd"]}

## Architecture
<!-- Describe your project structure here -->

## Boundaries
<!-- Define module boundaries, e.g.: -->
<!-- - models/ must not import from api/ -->
<!-- - External API calls only in services/ -->

## Conventions
<!-- Naming conventions, error handling patterns, testing requirements -->

## Known Issues
<!-- Active bugs or tech debt -->

## BOBCODE Agent Harness
Use BOBCODE when the operator asks you to work through the harness or when a task
needs durable state across agent sessions.

Startup sequence:
1. `harness-ctl doctor --json` — verify local readiness.
2. `harness-ctl cg status --json` — inspect codegraph and embedding state.
3. `harness-ctl task new --agent-driven <slug> "<task description>" --json` —
   create a task scaffold and isolated worktree without invoking another LLM.
4. Read the returned `state_path`, `plan_path`, and `worktree_path`.
5. Keep `.bobcode/tasks/<TASK-ID>/progress.jsonl` current with short JSONL progress events.
6. Before finishing, run the repo test/lint commands and update `state.json`
   with status, summary, and verification.

Prefer the generic `--agent-driven` flag. `--claude-driven` is accepted as a compatibility alias.

## codegraph
Graph at `.codegraph/graph.db`. Rebuild it after structural changes.
Before modifying code, use harness-wrapped codegraph commands so output is stable:
1. `harness-ctl cg where <symbol> --json` — find where it lives
2. `harness-ctl cg context <symbol> --json` — check who calls it
3. `harness-ctl cg impact <symbol-or-file> --json` — check blast radius
4. `harness-ctl cg search "<natural language query>" --json` — semantic
   search; if embeddings are missing, run `harness-ctl cg embed`
"""


def _is_git_repo(path: Path) -> bool:
    """Return True when *path* is a git working tree."""
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _current_git_repo(path: str | Path = ".") -> Path | None:
    """Return the git top-level path for *path*, or None outside a worktree."""
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).expanduser().resolve()


def _local_state_ignore(repo_path: Path) -> tuple[Path, list[str]]:
    """Keep repo-local harness runtime artifacts out of tracked files."""
    ignore_path = repo_path / ".git" / "info" / "exclude"
    added = _upsert_lines(ignore_path, [".bobcode/", ".codegraph/"])
    return ignore_path, added


def _shared_state_ignore(repo_path: Path) -> tuple[Path, list[str]]:
    """Add BOBCODE runtime artifacts to tracked repo ignores."""
    ignore_path = repo_path / ".gitignore"
    added = _upsert_lines(ignore_path, [".bobcode/", ".codegraph/"])
    return ignore_path, added


def _ensure_local_runtime_metadata(
    repo_root: Path,
    project_name: str,
    codegraph_status: str = "unknown",
    codegraph_message: str = "Codegraph has not been checked. Run `harness-ctl cg build`.",
    codegraph_path: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Create minimal repo-local runtime metadata and return useful paths."""
    repo_context = _detect_repo_context(str(repo_root))
    project_paths = get_project_paths(repo_path=str(repo_root))
    project_paths.ensure_dirs()

    now = datetime.now(UTC).isoformat()
    config_path = project_paths.project_dir / "bobcode.json"
    existing = _read_json_file(config_path)
    existing_config = existing if isinstance(existing, dict) else {}
    if codegraph_path is None:
        codegraph_path = repo_root / ".codegraph" / "graph.db"

    if force or not config_path.is_file():
        payload = {
            "version": 1,
            "project": {
                "name": project_name,
                "repo_path": str(repo_root),
                "created_at": existing_config.get("project", {}).get("created_at", now),
                "updated_at": now,
            },
            "repo_context": repo_context,
            "runtime": {
                "state_dir": str(project_paths.project_dir),
                "tasks_dir": str(project_paths.tasks_dir),
                "worktree_base": str(project_paths.worktree_base),
            },
            "codegraph": {
                "status": codegraph_status,
                "artifact_path": str(codegraph_path),
                "last_checked_at": now,
                "last_message": codegraph_message,
            },
        }
        if codegraph_status == "ready":
            payload["codegraph"]["last_built_at"] = now
        config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    feature_list_path = project_paths.project_dir / "feature_list.json"
    if force or not feature_list_path.exists():
        feature_list_path.write_text(
            json.dumps({"version": 1, "features": []}, indent=2) + "\n",
            encoding="utf-8",
        )

    progress_path = project_paths.project_dir / "progress.jsonl"
    progress_path.touch(exist_ok=True)

    return {
        "project_paths": project_paths,
        "repo_context": repo_context,
        "config_path": config_path,
        "feature_list_path": feature_list_path,
        "progress_path": progress_path,
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_submit(args: argparse.Namespace) -> None:
    """Submit a new task to the orchestrator."""
    from apps.orchestrator.main import run_task

    description = args.description
    task_type = args.type
    project_name = args.project or None
    repo_path: str | None = None
    if project_name is None:
        current_repo = _current_git_repo()
        if current_repo is None:
            print(
                "No registered project specified and current directory is not a git repo. "
                "Run from a repo or pass --project.",
                file=sys.stderr,
            )
            sys.exit(1)
        repo_path = str(current_repo)

    print(f"Submitting task: {description}")
    print(f"Type: {task_type}")
    if project_name:
        print(f"Project: {project_name}")
    elif repo_path:
        print(f"Repo: {repo_path}")
    print()

    try:
        result = asyncio.run(
            run_task(
                description,
                task_type,
                project_name=project_name,
                repo_path=repo_path,
            )
        )
        print("Task completed.")
        _print_json({
            "task_id": result.get("task_id"),
            "project_name": result.get("project_name"),
            "status": result.get("status"),
            "error": result.get("error"),
        })
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    """Show the status of a task or all tasks."""
    if args.task_id:
        task = _load_task(args.task_id, args.project)
        if task is None:
            print(f"Task {args.task_id} not found.", file=sys.stderr)
            sys.exit(1)
        project_name, task_dir, manifest = task

        status_info = _task_status_payload(project_name, task_dir, manifest)
        _print_json(status_info)
    else:
        # Show all tasks
        tasks = _list_tasks(args.project)
        if not tasks:
            if args.json:
                _print_json({"tasks": []})
                return
            print("No tasks found.")
            return

        if args.json:
            _print_json({
                "tasks": [
                    _task_status_payload(project_name, task_dir, manifest, shallow=True)
                    for project_name, _task_id, task_dir, manifest in tasks
                ],
            })
            return

        for project_name, task_id, _task_dir, manifest in tasks:
            if manifest:
                display_project = manifest.get("project_name") or project_name or "legacy"
                print(
                    f"  {task_id}  project={display_project:15s}  "
                    f"type={manifest.get('task_type', '?'):20s}  "
                    f"created={manifest.get('created_at', '?')}"
                )
            else:
                print(f"  {task_id}  (no manifest)")


def cmd_budget(args: argparse.Namespace) -> None:
    """Show budget usage for a task."""
    from apps.orchestrator.budget import budget_enforcer

    if args.task_id:
        remaining = budget_enforcer.get_remaining(args.task_id)
        _print_json({"task_id": args.task_id, **remaining})
    else:
        # Show default budget from config
        print("Default budget per task:")
        _print_json({
            "max_tokens": 500_000,
            "max_cost_usd": 5.00,
        })


def cmd_list(args: argparse.Namespace) -> None:
    """List all tasks."""
    tasks = _list_tasks(args.project)
    if not tasks:
        if args.json:
            _print_json({"tasks": []})
            return
        print("No tasks found.")
        return

    if args.json:
        _print_json({
            "tasks": [
                _task_status_payload(project_name, task_dir, manifest, shallow=True)
                for project_name, _task_id, task_dir, manifest in tasks
            ],
        })
        return

    print(f"{'Task ID':<12} {'Project':<18} {'Type':<22} {'Created'}")
    print("-" * 90)
    for project_name, task_id, _task_dir, manifest in tasks:
        if manifest:
            print(
                f"{task_id:<12} {(manifest.get('project_name') or project_name or 'legacy'):<18} "
                f"{manifest.get('task_type', '?'):<22} "
                f"{manifest.get('created_at', '?')}"
            )
        else:
            print(f"{task_id:<12} {(project_name or 'legacy'):<18} {'?':<22} ?")


def cmd_approve(args: argparse.Namespace) -> None:
    """Approve a task (human-in-the-loop gate)."""
    task_id = args.task_id
    task = _load_task(task_id, args.project)
    if task is None:
        print(f"Task {task_id} not found.", file=sys.stderr)
        sys.exit(1)
    _project_name, task_dir, _manifest = task

    # Write approval marker
    approval_path = task_dir / "approved.json"
    approval = {
        "task_id": task_id,
        "approved": True,
        "approved_by": "cli",
    }
    with approval_path.open("w") as f:
        json.dump(approval, f, indent=2)

    print(f"Task {task_id} approved.")


def cmd_reject(args: argparse.Namespace) -> None:
    """Reject a task with a reason."""
    task_id = args.task_id
    task = _load_task(task_id, args.project)
    if task is None:
        print(f"Task {task_id} not found.", file=sys.stderr)
        sys.exit(1)
    _project_name, task_dir, _manifest = task

    reason = args.reason or "No reason provided"

    rejection_path = task_dir / "rejected.json"
    rejection = {
        "task_id": task_id,
        "approved": False,
        "rejected_by": "cli",
        "reason": reason,
    }
    with rejection_path.open("w") as f:
        json.dump(rejection, f, indent=2)

    print(f"Task {task_id} rejected: {reason}")


def cmd_init(args: argparse.Namespace) -> None:
    """Initialise repo-local BOBCODE state for the current repository."""
    from datetime import datetime

    from packages.repo_intel.codegraph_manager import build_codegraph

    repo_root = _current_git_repo(args.path)
    if repo_root is None:
        print(f"Not a git repository: {args.path}", file=sys.stderr)
        sys.exit(1)

    project_name = args.name or repo_root.name
    repo_context = _detect_repo_context(str(repo_root))
    project_paths = get_project_paths(repo_path=str(repo_root))
    project_paths.ensure_dirs()

    ignore_path, added_entries = _local_state_ignore(repo_root)
    shared_ignore_path: Path | None = None
    shared_added_entries: list[str] = []
    if args.gitignore:
        shared_ignore_path, shared_added_entries = _shared_state_ignore(repo_root)

    now = datetime.now(UTC).isoformat()
    config_path = project_paths.project_dir / "bobcode.json"
    existing: dict[str, Any] = {}
    if config_path.is_file() and not args.force:
        with config_path.open(encoding="utf-8") as fh:
            existing = json.load(fh)

    codegraph_status = "skipped"
    codegraph_message = "Codegraph build skipped by operator request"
    codegraph_path = repo_root / ".codegraph" / "graph.db"
    if not args.skip_codegraph:
        build_result = build_codegraph(repo_root, timeout_seconds=args.codegraph_timeout)
        codegraph_path = build_result.artifact_path
        codegraph_status = "ready" if build_result.success else "unavailable"
        codegraph_message = build_result.message

    payload = {
        "version": 1,
        "project": {
            "name": project_name,
            "repo_path": str(repo_root),
            "created_at": existing.get("project", {}).get("created_at", now),
            "updated_at": now,
        },
        "repo_context": repo_context,
        "runtime": {
            "state_dir": str(project_paths.project_dir),
            "tasks_dir": str(project_paths.tasks_dir),
            "worktree_base": str(project_paths.worktree_base),
        },
        "codegraph": {
            "status": codegraph_status,
            "artifact_path": str(codegraph_path),
            "last_checked_at": now,
            "last_message": codegraph_message,
        },
    }
    if codegraph_status == "ready":
        payload["codegraph"]["last_built_at"] = now

    config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    feature_list_path = project_paths.project_dir / "feature_list.json"
    if args.force or not feature_list_path.exists():
        feature_list_path.write_text(
            json.dumps({"version": 1, "features": []}, indent=2) + "\n",
            encoding="utf-8",
        )

    progress_path = project_paths.project_dir / "progress.jsonl"
    progress_path.touch(exist_ok=True)

    if args.assisted:
        agents_md_path = repo_root / "AGENTS.md"
        if args.force or not agents_md_path.exists():
            agents_md_path.write_text(
                _build_agents_md(project_name, repo_context),
                encoding="utf-8",
            )

    print(f"Initialised BOBCODE for: {project_name}")
    print(f"  Repo: {repo_root}")
    print(f"  State: {project_paths.project_dir}")
    print(f"  Config: {config_path}")
    if added_entries:
        print(f"  Updated {ignore_path}: added {', '.join(added_entries)}")
    if shared_ignore_path and shared_added_entries:
        print(f"  Updated {shared_ignore_path}: added {', '.join(shared_added_entries)}")
    print(f"  Codegraph: {codegraph_status} — {codegraph_message}")
    if codegraph_status == "ready":
        print(
            "  Semantic search: run `harness-ctl cg embed` "
            "when natural-language search is needed"
        )
    print("  Submit tasks with: harness-ctl submit 'description'")


def cmd_doctor(args: argparse.Namespace) -> None:
    """Run local preflight checks for a repo-local BOBCODE install."""
    import shutil

    repo_root = _current_git_repo(args.path)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, required: bool = False) -> None:
        checks.append({
            "name": name,
            "ok": ok,
            "required": required,
            "detail": detail,
        })

    add(
        "git_repo",
        repo_root is not None,
        str(repo_root) if repo_root else "not in a git repo",
        True,
    )

    project_paths = None
    config_data: dict[str, Any] = {}
    if repo_root is not None:
        project_paths = get_project_paths(repo_path=str(repo_root))
        config_path = project_paths.project_dir / "bobcode.json"
        add("local_state", project_paths.project_dir.is_dir(), str(project_paths.project_dir), True)
        add("local_config", config_path.is_file(), str(config_path), True)
        if config_path.is_file():
            try:
                config_data = json.loads(config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                add("local_config_parse", False, f"invalid JSON: {exc}", True)
            else:
                add("local_config_parse", True, "bobcode.json is valid JSON")

        graph_path = repo_root / ".codegraph" / "graph.db"
        codegraph_bin = shutil.which("codegraph")
        add("codegraph_binary", codegraph_bin is not None, codegraph_bin or "missing")
        add("codegraph_artifact", graph_path.is_file(), str(graph_path))

        repo_context = config_data.get("repo_context", {})
        for key in ("build_cmd", "test_cmd", "lint_cmd"):
            value = repo_context.get(key, "# TODO")
            add(key, bool(value and value != "# TODO"), value)

    has_model_key = any(
        os.environ.get(name)
        for name in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "GOOGLE_API_KEY",
        )
    )
    model_key_detail = (
        "at least one provider key is set"
        if has_model_key
        else "no provider key found"
    )
    add("model_api_key", has_model_key, model_key_detail)

    browser_pkg = Path(__file__).resolve().parents[2] / "tools" / "browser-daemon" / "package.json"
    add("browser_daemon", browser_pkg.is_file(), str(browser_pkg))

    if args.json:
        _print_json({"checks": checks, "ok": all(c["ok"] for c in checks if c["required"])})
    else:
        for check in checks:
            if check["ok"]:
                marker = "OK"
            elif check["required"]:
                marker = "FAIL"
            else:
                marker = "WARN"
            print(f"{marker:4s} {check['name']:<22} {check['detail']}")

    if any((not c["ok"]) and c["required"] for c in checks):
        sys.exit(1)


def cmd_inbox(args: argparse.Namespace) -> None:
    """Show tasks that need operator attention."""
    rows: list[dict[str, Any]] = []
    terminal_statuses = {"done", "completed"}

    for project_name, tasks_dir in _iter_task_roots(args.project or None):
        if not tasks_dir.is_dir():
            continue
        task_dirs = (
            p for p in tasks_dir.iterdir()
            if p.is_dir() and p.name.startswith("TASK-")
        )
        for task_dir in sorted(task_dirs):
            manifest_path = task_dir / "manifest.json"
            if not manifest_path.is_file():
                continue
            with manifest_path.open(encoding="utf-8") as fh:
                manifest = json.load(fh)

            eval_path = task_dir / "evals" / "validation.json"
            validation: dict[str, Any] = {}
            if eval_path.is_file():
                with eval_path.open(encoding="utf-8") as fh:
                    validation = json.load(fh)

            status = validation.get("final_status") or manifest.get("status", "pending")
            if not args.all and status in terminal_statuses:
                continue

            rows.append({
                "task_id": task_dir.name,
                "project": manifest.get("project_name") or project_name or "local",
                "status": status,
                "type": manifest.get("task_type", "?"),
                "description": manifest.get("description", "")[:80],
                "task_dir": str(task_dir),
                "state_path": str(task_dir / "state.json"),
                "plan_path": str(task_dir / "plan.json"),
                "progress_path": str(task_dir / "progress.jsonl"),
            })

    if not rows:
        if args.json:
            _print_json({"items": []})
            return
        print("Inbox is empty.")
        return

    if args.json:
        _print_json({"items": rows})
        return

    print(f"{'Task ID':<12} {'Project':<18} {'Status':<14} {'Type':<18} Description")
    print("-" * 100)
    for row in rows:
        print(
            f"{row['task_id']:<12} {row['project']:<18} {row['status']:<14} "
            f"{row['type']:<18} {row['description']}"
        )


def _update_local_codegraph_metadata(
    repo_root: Path,
    status: str,
    message: str,
    graph_path: Path | None = None,
) -> None:
    """Best-effort update of `.bobcode/bobcode.json` codegraph metadata."""
    project_paths = get_project_paths(repo_path=str(repo_root))
    config_path = project_paths.project_dir / "bobcode.json"
    data = _read_json_file(config_path)
    if not isinstance(data, dict):
        return
    now = datetime.now(UTC).isoformat()
    data["codegraph"] = {
        **data.get("codegraph", {}),
        "status": status,
        "artifact_path": str(graph_path or repo_root / ".codegraph" / "graph.db"),
        "last_checked_at": now,
        "last_message": message,
    }
    if status == "ready":
        data["codegraph"]["last_built_at"] = now
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _codegraph_status_payload(repo_root: Path) -> dict[str, Any]:
    """Return codegraph health in a stable JSON shape."""
    graph_path = repo_root / ".codegraph" / "graph.db"
    codegraph_bin = shutil.which("codegraph")
    payload: dict[str, Any] = {
        "repo_path": str(repo_root),
        "binary": codegraph_bin,
        "graph_path": str(graph_path),
        "graph_exists": graph_path.is_file(),
        "embeddings_ready": False,
        "stats": None,
        "remediation": [],
    }
    if codegraph_bin is None:
        payload["remediation"].append("Install codegraph: npm install -g @optave/codegraph")
        return payload
    if not graph_path.is_file():
        payload["remediation"].append("Run: harness-ctl cg build")
        return payload

    result = subprocess.run(
        ["codegraph", "stats", "--json"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )
    if result.returncode != 0:
        payload["remediation"].append(result.stderr.strip() or "Run: harness-ctl cg build")
        return payload
    try:
        stats = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload["remediation"].append("Run: harness-ctl cg build")
        payload["raw"] = result.stdout.strip()[:2000]
        return payload

    payload["stats"] = stats
    payload["embeddings_ready"] = bool(stats.get("embeddings"))
    if not payload["embeddings_ready"]:
        payload["remediation"].append(
            "Semantic search requires embeddings. Run: harness-ctl cg embed"
        )
    return payload


def _run_codegraph_json(
    repo_root: Path,
    command_args: list[str],
    timeout: int = 30,
) -> dict[str, Any]:
    """Run a codegraph command with JSON output and wrap failures for agents."""
    if shutil.which("codegraph") is None:
        return {
            "ok": False,
            "command": ["codegraph", *command_args, "--json"],
            "error": "codegraph CLI not found",
            "remediation": ["Install codegraph: npm install -g @optave/codegraph"],
        }

    cmd = ["codegraph", *command_args, "--json"]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=repo_root,
        check=False,
    )
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    remediation: list[str] = []
    combined = f"{stdout}\n{stderr}".lower()
    if "no embeddings" in combined or "fts5 index not found" in combined:
        remediation.append("Run: harness-ctl cg embed")
    if "graph.db" in combined and "not found" in combined:
        remediation.append("Run: harness-ctl cg build")

    parsed: Any = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = None

    return {
        "ok": result.returncode == 0 and parsed is not None,
        "returncode": result.returncode,
        "command": cmd,
        "repo_path": str(repo_root),
        "data": parsed,
        "stdout": None if parsed is not None else stdout[:4000],
        "stderr": stderr[:4000],
        "remediation": remediation,
    }


def cmd_cg(args: argparse.Namespace) -> None:
    """Harness-wrapped codegraph commands for agents."""
    from packages.repo_intel.codegraph_manager import build_codegraph

    repo_root = _current_git_repo(args.path)
    if repo_root is None:
        _print_json({
            "ok": False,
            "error": f"Not a git repository: {args.path}",
            "remediation": ["Run from a git repo or pass --path"],
        })
        sys.exit(1)

    if args.cg_command == "status":
        payload = _codegraph_status_payload(repo_root)
        payload["ok"] = payload["binary"] is not None and payload["graph_exists"]
        _print_json(payload)
        if not payload["ok"]:
            sys.exit(1)
        return

    if args.cg_command == "build":
        result = build_codegraph(repo_root, timeout_seconds=args.timeout)
        _update_local_codegraph_metadata(
            repo_root,
            "ready" if result.success else "unavailable",
            result.message,
            result.artifact_path,
        )
        _print_json({
            "ok": result.success,
            "repo_path": str(repo_root),
            "artifact_path": str(result.artifact_path),
            "message": result.message,
            "remediation": [] if result.success else [
                "Install/configure codegraph, then rerun: harness-ctl cg build",
            ],
        })
        if not result.success:
            sys.exit(1)
        return

    if args.cg_command == "embed":
        graph_path = repo_root / ".codegraph" / "graph.db"
        if not graph_path.is_file():
            _print_json({
                "ok": False,
                "error": f"Missing graph: {graph_path}",
                "remediation": ["Run: harness-ctl cg build"],
            })
            sys.exit(1)
        cmd = ["codegraph", "embed", str(repo_root)]
        if args.model:
            cmd.extend(["--model", args.model])
        if args.strategy:
            cmd.extend(["--strategy", args.strategy])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=args.timeout,
            check=False,
        )
        payload = {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "command": cmd,
            "repo_path": str(repo_root),
            "stdout": result.stdout.strip()[:4000],
            "stderr": result.stderr.strip()[:4000],
        }
        _print_json(payload)
        if result.returncode != 0:
            sys.exit(1)
        return

    query_args: list[str]
    if args.cg_command == "where":
        query_args = ["where", args.symbol]
    elif args.cg_command == "context":
        query_args = ["context", args.symbol]
    elif args.cg_command == "impact":
        if "/" in args.target or "." in args.target:
            query_args = ["impact", args.target]
        else:
            query_args = ["fn-impact", args.target]
    elif args.cg_command == "search":
        query_args = ["search", " ".join(args.query), "--limit", str(args.limit)]
    elif args.cg_command == "stats":
        query_args = ["stats"]
    elif args.cg_command == "deps":
        query_args = ["deps", args.file]
    elif args.cg_command == "dataflow":
        query_args = ["dataflow", args.symbol]
    elif args.cg_command == "complexity":
        query_args = ["complexity"]
        if args.target:
            query_args.append(args.target)
    else:
        _print_json({"ok": False, "error": "Unknown cg command"})
        sys.exit(1)

    payload = _run_codegraph_json(repo_root, query_args, timeout=args.timeout)
    _print_json(payload)
    if not payload["ok"]:
        sys.exit(1)


def _git_has_head(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _create_agent_task_scaffold(
    repo_root: Path,
    slug: str,
    description: str,
    task_type: str = "code_change",
    owner_agent: str = "external-agent",
    branch: str = "",
    create_worktree: bool = True,
) -> dict[str, Any]:
    """Create a task scaffold for an external orchestrator agent."""
    from apps.orchestrator.stages.intake import _next_task_id
    from packages.stage_manager.worktree import WorktreeManager
    from packages.state.sqlite_store import SQLiteStore
    from packages.state.task_state import TaskStateManager

    project_name = repo_root.name
    metadata = _ensure_local_runtime_metadata(repo_root, project_name)
    project_paths = metadata["project_paths"]
    _local_state_ignore(repo_root)

    task_id = _next_task_id(str(project_paths.counter_file))
    safe_slug = _slugify(slug)
    trace_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    description = description.strip() or safe_slug.replace("-", " ")
    branch = branch or f"bobcode/{task_id.lower()}-{safe_slug}"

    worktree_path: Path | None = None
    if create_worktree:
        if not _git_has_head(repo_root):
            raise RuntimeError(
                "Cannot create a worktree before the repository has an initial commit. "
                "Rerun with --no-worktree or create the first commit."
            )
        wt_manager = WorktreeManager(
            repo_path=str(repo_root),
            worktree_base=str(project_paths.worktree_base),
        )
        worktree_path = wt_manager.create(str(repo_root), task_id, branch)

    tsm = TaskStateManager(tasks_dir=str(project_paths.tasks_dir))
    task_dir = tsm.create_task_dir(task_id)

    budget = {
        "max_tokens": 500_000,
        "max_cost_usd": 5.00,
        "tokens_used": 0,
        "cost_used": 0.0,
    }
    manifest = {
        "task_id": task_id,
        "slug": safe_slug,
        "task_type": task_type,
        "description": description,
        "status": "agent_ready",
        "mode": "agent_direct",
        "owner_agent": owner_agent,
        "created_at": now,
        "trace_id": trace_id,
        "project_name": project_paths.project_name,
        "repo_path": str(repo_root),
        "branch": branch,
        "worktree_path": str(worktree_path) if worktree_path else None,
    }
    state = {
        **manifest,
        "domain": "engineering" if task_type == "code_change" else "general",
        "plan": None,
        "artifacts": [],
        "eval_results": None,
        "budget": budget,
        "retries": 0,
        "max_retries": 0,
        "error": None,
        "orchestrator": {
            "mode": "agent_direct",
            "owner_agent": owner_agent,
            "instructions": [
                "Fill plan.json before broad edits.",
                "Keep progress.jsonl current with concise JSONL events.",
                "Update state.json before handoff with status, summary, and verification.",
            ],
        },
    }
    plan = {
        "task_id": task_id,
        "mode": "agent_direct",
        "created_by": owner_agent,
        "created_at": now,
        "status": "draft",
        "objective": description,
        "plan_steps": [],
        "verification": [],
        "notes": "External agent should replace this draft before implementation.",
    }

    (task_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    tsm.write_state(task_id, state)
    tsm.write_plan(task_id, plan)
    tsm.write_budget(task_id, budget)

    event = {
        "ts": now,
        "event": "task_created",
        "task_id": task_id,
        "slug": safe_slug,
        "owner_agent": owner_agent,
        "status": "agent_ready",
        "branch": branch,
        "worktree_path": str(worktree_path) if worktree_path else None,
    }
    _append_jsonl(project_paths.project_dir / "progress.jsonl", event)
    _append_jsonl(task_dir / "progress.jsonl", event)

    try:
        store = SQLiteStore(str(project_paths.db_path))
        store.create_task({
            "task_id": task_id,
            "title": description[:120],
            "description": description,
            "status": "agent_ready",
            "branch": branch,
            "metadata": manifest,
            "worktree_path": str(worktree_path) if worktree_path else None,
        })
        store.close()
    except Exception:
        pass

    return {
        "ok": True,
        "task_id": task_id,
        "slug": safe_slug,
        "project_name": project_paths.project_name,
        "repo_path": str(repo_root),
        "task_dir": str(task_dir),
        "state_path": str(task_dir / "state.json"),
        "plan_path": str(task_dir / "plan.json"),
        "progress_path": str(task_dir / "progress.jsonl"),
        "global_progress_path": str(project_paths.project_dir / "progress.jsonl"),
        "branch": branch,
        "worktree_path": str(worktree_path) if worktree_path else None,
        "next_steps": [
            f"cd {worktree_path or repo_root}",
            f"edit {task_dir / 'plan.json'}",
            "use harness-ctl cg where/context/impact/search for repo intelligence",
            f"update {task_dir / 'state.json'} before handoff",
        ],
    }


def cmd_task(args: argparse.Namespace) -> None:
    """Task scaffolding commands for external orchestrator agents."""
    if args.task_command != "new":
        _print_json({"ok": False, "error": "Unknown task command"})
        sys.exit(1)

    repo_root = _current_git_repo(args.path)
    if repo_root is None:
        _print_json({
            "ok": False,
            "error": f"Not a git repository: {args.path}",
            "remediation": ["Run from a git repo or pass --path"],
        })
        sys.exit(1)

    owner_agent = args.owner_agent or "external-agent"
    if args.claude_driven:
        owner_agent = "claude"
    elif args.agent_driven and owner_agent == "external-agent":
        owner_agent = os.environ.get("BOBCODE_AGENT_NAME", "external-agent")

    description = args.description_flag or " ".join(args.description)
    try:
        payload = _create_agent_task_scaffold(
            repo_root=repo_root,
            slug=args.slug,
            description=description,
            task_type=args.type,
            owner_agent=owner_agent,
            branch=args.branch,
            create_worktree=not args.no_worktree,
        )
    except Exception as exc:
        _print_json({
            "ok": False,
            "error": str(exc),
            "remediation": [
                "Rerun with --no-worktree if the active agent will work in the current checkout.",
                "Run harness-ctl doctor --json to inspect local setup.",
            ],
        })
        sys.exit(1)

    if args.json:
        _print_json(payload)
        return

    print(f"Created task scaffold: {payload['task_id']}")
    print(f"  Task dir: {payload['task_dir']}")
    print(f"  Plan: {payload['plan_path']}")
    print(f"  State: {payload['state_path']}")
    print(f"  Worktree: {payload['worktree_path'] or 'not created'}")
    print(f"  Branch: {payload['branch']}")


def cmd_register(args: argparse.Namespace) -> None:
    """Register a project for harness management."""
    from datetime import datetime

    import yaml

    from packages.repo_intel.codegraph_manager import build_codegraph

    repo_path = os.path.abspath(args.path)
    project_name = args.name or os.path.basename(repo_path)
    mode = args.mode
    skip_codegraph = args.skip_codegraph

    if not os.path.isdir(repo_path):
        print(f"Directory not found: {repo_path}", file=sys.stderr)
        sys.exit(1)

    repo_path_obj = Path(repo_path)
    if not _is_git_repo(repo_path_obj):
        print(f"Not a git repository: {repo_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Registering project: {project_name}")
    print(f"  Path: {repo_path}")
    print(f"  Mode: {mode}")
    print(f"  Codegraph: {'skip (degraded)' if skip_codegraph else 'required'}")
    print()

    repo_context = _detect_repo_context(repo_path)

    # 1. Create per-project data directory
    project_data = get_data_dir() / "projects" / project_name
    for subdir in ["tasks", "sqlite", "learning", "skills", "worktrees", "eval_outputs"]:
        os.makedirs(project_data / subdir, exist_ok=True)
    print(f"  Project data: {project_data}")

    # 2. Build codegraph by default unless explicitly skipped
    codegraph_status = "skipped"
    codegraph_message = "Codegraph build skipped by operator request"
    codegraph_path = repo_path_obj / ".codegraph" / "graph.db"
    if skip_codegraph:
        print("  Skipping codegraph build (--skip-codegraph)")
    else:
        print("  Building codegraph...")
        build_result = build_codegraph(repo_path_obj, timeout_seconds=args.codegraph_timeout)
        codegraph_path = build_result.artifact_path
        codegraph_message = build_result.message
        if build_result.success:
            codegraph_status = "ready"
            print(f"  {build_result.message}")
        else:
            print(f"  {build_result.message}", file=sys.stderr)
            print(
                "  Registration aborted. Install/configure codegraph or rerun with "
                "--skip-codegraph for degraded mode.",
                file=sys.stderr,
            )
            sys.exit(1)

    # 3. Keep repo-local codegraph artifacts untracked
    ignore_path, added_entries = _ensure_codegraph_ignore(repo_path_obj, mode)
    if added_entries:
        target_name = ".gitignore" if mode == "assisted" else ".git/info/exclude"
        print(f"  Updated {target_name}: added {', '.join(added_entries)}")
    else:
        target_name = ".gitignore" if mode == "assisted" else ".git/info/exclude"
        print(f"  Found existing ignore entry in {target_name}")

    # 4. Create AGENTS.md if it doesn't exist
    agents_md_path = os.path.join(repo_path, "AGENTS.md")
    if mode == "assisted" and not os.path.exists(agents_md_path):
        with open(agents_md_path, "w") as f:
            f.write(_build_agents_md(project_name, repo_context))
        print(f"  Created: {agents_md_path}")
    elif mode == "assisted":
        print(f"  Found existing: {agents_md_path}")
    else:
        print("  External mode: leaving AGENTS.md untouched")

    # 5. Create per-project config
    config_dir = get_config_dir()
    projects_config_dir = config_dir / "projects"
    os.makedirs(projects_config_dir, exist_ok=True)

    project_config_path = projects_config_dir / f"{project_name}.yaml"
    existing_registered_at: str | None = None
    project_config: dict[str, Any] = {}
    if project_config_path.exists():
        with project_config_path.open() as f:
            project_config = yaml.safe_load(f) or {}
        existing_registered_at = (
            project_config.get("project", {}).get("registered_at")
        )

    now = datetime.now(UTC).isoformat()
    project_config["project"] = {
        "name": project_name,
        "repo_path": repo_path,
        "registered_at": existing_registered_at or now,
        "updated_at": now,
    }
    project_config["registration"] = {
        "mode": mode,
        "codegraph_required": not skip_codegraph,
        "codegraph_ignore_path": str(ignore_path),
    }
    project_config["repo_context"] = repo_context
    project_config["codegraph"] = {
        "status": codegraph_status,
        "artifact_path": str(codegraph_path),
        "last_checked_at": now,
        "last_message": codegraph_message,
        "build_mode": "automatic" if not skip_codegraph else "skipped",
    }
    if codegraph_status == "ready":
        project_config["codegraph"]["last_built_at"] = now

    with project_config_path.open("w") as f:
        yaml.safe_dump(project_config, f, default_flow_style=False, sort_keys=False)
    print(f"  Config: {project_config_path}")

    # 6. Register in harness.yaml
    harness_config_path, cfg = _load_harness_yaml()
    projects = cfg.setdefault("projects", {})
    projects[project_name] = repo_path
    _save_harness_yaml(harness_config_path, cfg)

    print()
    print(f"Project '{project_name}' registered.")
    print(f"  Submit tasks with: harness-ctl submit 'description' --project {project_name}")


def cmd_projects(args: argparse.Namespace) -> None:
    """List registered projects."""
    projects = list(iter_registered_projects())
    if not projects:
        print("No projects registered. Use: harness-ctl register /path/to/project")
        return

    print(f"{'Project':<20} {'Path'}")
    print("-" * 60)
    for name, path in projects:
        exists = "OK" if path.is_dir() else "MISSING"
        print(f"{name:<20} {path}  [{exists}]")


def cmd_feedback_status(args: argparse.Namespace) -> None:
    """Show community feedback consent and export status."""
    from packages.learning.community_exchange import summarize_feedback_status

    _print_json(summarize_feedback_status())


def cmd_feedback_consent(args: argparse.Namespace) -> None:
    """Set community feedback sharing consent."""
    from datetime import datetime

    from packages.learning.community_exchange import validate_consent_level

    consent = validate_consent_level(args.level)
    actor = args.actor or os.environ.get("USER") or "unknown"

    harness_config_path, cfg = _load_harness_yaml()
    feedback_cfg = cfg.setdefault("community_feedback", {})
    feedback_cfg["consent"] = consent
    feedback_cfg["updated_at"] = datetime.now(UTC).isoformat()
    feedback_cfg["updated_by"] = actor
    _save_harness_yaml(harness_config_path, cfg)

    print(f"Community feedback consent set to: {consent}")
    print(f"  Updated by: {actor}")


def cmd_feedback_export(args: argparse.Namespace) -> None:
    """Export anonymized community feedback for upstream sharing."""
    from packages.learning.community_exchange import (
        build_feedback_export,
        get_feedback_settings,
        write_feedback_export,
    )

    settings = get_feedback_settings()
    if not settings.export_enabled:
        print(
            "Community feedback consent is local_only. "
            "Run `harness-ctl feedback consent anonymized_export` to enable export.",
            file=sys.stderr,
        )
        sys.exit(1)

    bundle = build_feedback_export(include_all=args.all, limit=args.limit)
    if bundle["event_count"] == 0:
        print("No feedback events available for export.")
        return

    output_path = write_feedback_export(
        bundle,
        output_path=args.output,
        advance_state=not args.no_mark_exported,
    )

    print(f"Exported {bundle['event_count']} feedback events to: {output_path}")
    _print_json({
        "consent": bundle["consent"],
        "event_count": bundle["event_count"],
        "line_range": bundle["line_range"],
        "output_path": str(output_path),
        "marked_exported": not args.no_mark_exported,
    })


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the harness-ctl argument parser."""

    parser = argparse.ArgumentParser(
        prog="harness-ctl",
        description="Agent Harness Orchestrator CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # submit
    p_submit = subparsers.add_parser("submit", help="Submit a new task")
    p_submit.add_argument("description", help="Task description")
    p_submit.add_argument(
        "--type",
        default="code_change",
        choices=["code_change", "marketing_campaign", "content_creation"],
        help="Task type (default: code_change)",
    )
    p_submit.add_argument("--project", default="", help="Registered project name")

    # status
    p_status = subparsers.add_parser("status", help="Show task status")
    p_status.add_argument("task_id", nargs="?", help="Task ID (omit to show all)")
    p_status.add_argument("--project", default="", help="Registered project name")
    p_status.add_argument("--json", action="store_true", help="Emit JSON instead of text")

    # budget
    p_budget = subparsers.add_parser("budget", help="Show budget usage")
    p_budget.add_argument("task_id", nargs="?", help="Task ID")
    p_budget.add_argument("--project", default="", help="Registered project name")

    # list
    p_list = subparsers.add_parser("list", help="List all tasks")
    p_list.add_argument("--project", default="", help="Registered project name")
    p_list.add_argument("--json", action="store_true", help="Emit JSON instead of text")

    # init
    p_init = subparsers.add_parser("init", help="Initialise BOBCODE in the current repo")
    p_init.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Repository path (default: current directory)",
    )
    p_init.add_argument("--name", default="", help="Project name (default: repo directory name)")
    p_init.add_argument(
        "--assisted",
        action="store_true",
        help="Also create/update AGENTS.md with detected build/test/lint commands",
    )
    p_init.add_argument(
        "--agent-instructions",
        action="store_true",
        dest="assisted",
        help="Alias for --assisted; create/update AGENTS.md for direct agent use",
    )
    p_init.add_argument(
        "--gitignore",
        action="store_true",
        help="Also add .bobcode/ and .codegraph/ to tracked .gitignore",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing repo-local BOBCODE metadata files",
    )
    p_init.add_argument(
        "--skip-codegraph",
        action="store_true",
        help="Skip codegraph build during init",
    )
    p_init.add_argument(
        "--codegraph-timeout",
        type=int,
        default=120,
        help="Timeout in seconds for codegraph build (default: 120)",
    )

    # doctor
    p_doctor = subparsers.add_parser("doctor", help="Check local BOBCODE readiness")
    p_doctor.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Repository path (default: current directory)",
    )
    p_doctor.add_argument("--json", action="store_true", help="Emit JSON instead of text")

    # inbox
    p_inbox = subparsers.add_parser("inbox", help="Show tasks needing operator attention")
    p_inbox.add_argument("--project", default="", help="Registered project name")
    p_inbox.add_argument("--all", action="store_true", help="Include terminal tasks")
    p_inbox.add_argument("--json", action="store_true", help="Emit JSON instead of text")

    # cg
    p_cg = subparsers.add_parser("cg", help="Harness-wrapped codegraph commands")
    p_cg.add_argument(
        "--path",
        default=".",
        help="Repository path (default: current directory)",
    )
    cg_subparsers = p_cg.add_subparsers(dest="cg_command", help="Codegraph commands")

    p_cg_status = cg_subparsers.add_parser("status", help="Show codegraph health")
    p_cg_status.add_argument("--json", action="store_true", help="Accepted for agent symmetry")

    p_cg_build = cg_subparsers.add_parser("build", help="Build .codegraph/graph.db")
    p_cg_build.add_argument("--json", action="store_true", help="Accepted for agent symmetry")
    p_cg_build.add_argument("--timeout", type=int, default=120, help="Timeout in seconds")

    p_cg_embed = cg_subparsers.add_parser("embed", help="Build semantic embeddings")
    p_cg_embed.add_argument("--json", action="store_true", help="Accepted for agent symmetry")
    p_cg_embed.add_argument("--timeout", type=int, default=300, help="Timeout in seconds")
    p_cg_embed.add_argument("--model", default="", help="Embedding model override")
    p_cg_embed.add_argument("--strategy", default="", help="Embedding strategy")

    p_cg_where = cg_subparsers.add_parser("where", help="Find symbol definitions/usages")
    p_cg_where.add_argument("symbol")
    p_cg_where.add_argument("--json", action="store_true", help="Accepted for agent symmetry")
    p_cg_where.add_argument("--timeout", type=int, default=30, help="Timeout in seconds")

    p_cg_context = cg_subparsers.add_parser("context", help="Show symbol context")
    p_cg_context.add_argument("symbol")
    p_cg_context.add_argument("--json", action="store_true", help="Accepted for agent symmetry")
    p_cg_context.add_argument("--timeout", type=int, default=30, help="Timeout in seconds")

    p_cg_impact = cg_subparsers.add_parser("impact", help="Show symbol or file impact")
    p_cg_impact.add_argument("target")
    p_cg_impact.add_argument("--json", action="store_true", help="Accepted for agent symmetry")
    p_cg_impact.add_argument("--timeout", type=int, default=30, help="Timeout in seconds")

    p_cg_search = cg_subparsers.add_parser("search", help="Semantic search")
    p_cg_search.add_argument("query", nargs="+")
    p_cg_search.add_argument("--limit", type=int, default=10, help="Maximum results")
    p_cg_search.add_argument("--json", action="store_true", help="Accepted for agent symmetry")
    p_cg_search.add_argument("--timeout", type=int, default=30, help="Timeout in seconds")

    p_cg_stats = cg_subparsers.add_parser("stats", help="Show graph stats")
    p_cg_stats.add_argument("--json", action="store_true", help="Accepted for agent symmetry")
    p_cg_stats.add_argument("--timeout", type=int, default=30, help="Timeout in seconds")

    p_cg_deps = cg_subparsers.add_parser("deps", help="Show file imports/importers")
    p_cg_deps.add_argument("file")
    p_cg_deps.add_argument("--json", action="store_true", help="Accepted for agent symmetry")
    p_cg_deps.add_argument("--timeout", type=int, default=30, help="Timeout in seconds")

    p_cg_dataflow = cg_subparsers.add_parser("dataflow", help="Show symbol data flow")
    p_cg_dataflow.add_argument("symbol")
    p_cg_dataflow.add_argument("--json", action="store_true", help="Accepted for agent symmetry")
    p_cg_dataflow.add_argument("--timeout", type=int, default=30, help="Timeout in seconds")

    p_cg_complexity = cg_subparsers.add_parser("complexity", help="Show complexity metrics")
    p_cg_complexity.add_argument("target", nargs="?")
    p_cg_complexity.add_argument("--json", action="store_true", help="Accepted for agent symmetry")
    p_cg_complexity.add_argument("--timeout", type=int, default=30, help="Timeout in seconds")

    # task
    p_task = subparsers.add_parser("task", help="Task scaffolding for external agents")
    task_subparsers = p_task.add_subparsers(dest="task_command", help="Task commands")

    p_task_new = task_subparsers.add_parser(
        "new",
        help="Create a task scaffold without invoking the LLM orchestrator",
    )
    p_task_new.add_argument("slug", help="Short task slug")
    p_task_new.add_argument("description", nargs="*", help="Task description")
    p_task_new.add_argument(
        "--description",
        dest="description_flag",
        default="",
        help="Task description, useful when the positional form is awkward",
    )
    p_task_new.add_argument("--path", default=".", help="Repository path")
    p_task_new.add_argument(
        "--type",
        default="code_change",
        choices=["code_change", "marketing_campaign", "content_creation"],
        help="Task type (default: code_change)",
    )
    p_task_new.add_argument("--branch", default="", help="Branch name override")
    p_task_new.add_argument(
        "--agent-driven",
        action="store_true",
        help="Mark the task as orchestrated by the active external agent",
    )
    p_task_new.add_argument(
        "--claude-driven",
        action="store_true",
        help="Compatibility alias for Claude sessions; sets owner_agent=claude",
    )
    p_task_new.add_argument("--owner-agent", default="", help="Agent name for metadata")
    p_task_new.add_argument(
        "--no-worktree",
        action="store_true",
        help="Create task files without creating an isolated git worktree",
    )
    p_task_new.add_argument("--json", action="store_true", help="Emit JSON instead of text")

    # approve
    p_approve = subparsers.add_parser("approve", help="Approve a task")
    p_approve.add_argument("task_id", help="Task ID to approve")
    p_approve.add_argument("--project", default="", help="Registered project name")

    # reject
    p_reject = subparsers.add_parser("reject", help="Reject a task")
    p_reject.add_argument("task_id", help="Task ID to reject")
    p_reject.add_argument("--reason", default="", help="Rejection reason")
    p_reject.add_argument("--project", default="", help="Registered project name")

    # register
    p_register = subparsers.add_parser("register", help="Register a project")
    p_register.add_argument("path", help="Path to the project repository")
    p_register.add_argument("--name", default="", help="Project name (default: directory name)")
    p_register.add_argument(
        "--mode",
        default="external",
        choices=["external", "assisted"],
        help="Registration mode (default: external)",
    )
    p_register.add_argument(
        "--skip-codegraph",
        action="store_true",
        help="Skip codegraph build during registration (degraded repo-intel mode)",
    )
    p_register.add_argument(
        "--codegraph-timeout",
        type=int,
        default=120,
        help="Timeout in seconds for codegraph build (default: 120)",
    )

    # projects
    subparsers.add_parser("projects", help="List registered projects")

    # feedback
    p_feedback = subparsers.add_parser(
        "feedback",
        help="Inspect and export anonymized community feedback",
    )
    feedback_subparsers = p_feedback.add_subparsers(
        dest="feedback_command",
        help="Feedback commands",
    )

    feedback_subparsers.add_parser("status", help="Show feedback consent and export status")

    p_feedback_consent = feedback_subparsers.add_parser(
        "consent",
        help="Set feedback sharing consent",
    )
    p_feedback_consent.add_argument(
        "level",
        choices=["local_only", "anonymized_export"],
        help="Consent level for community feedback sharing",
    )
    p_feedback_consent.add_argument(
        "--actor",
        default="",
        help="Operator name recorded with the consent change",
    )

    p_feedback_export = feedback_subparsers.add_parser(
        "export",
        help="Export feedback bundle for upstream sharing",
    )
    p_feedback_export.add_argument(
        "--all",
        action="store_true",
        help="Export all recorded feedback events instead of only pending events",
    )
    p_feedback_export.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of events to export (default: all pending)",
    )
    p_feedback_export.add_argument(
        "--output",
        default="",
        help="Write the export bundle to this path instead of the default exports directory",
    )
    p_feedback_export.add_argument(
        "--no-mark-exported",
        action="store_true",
        help="Do not advance the export state after writing the bundle",
    )

    return parser


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point for harness-ctl."""

    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "submit": cmd_submit,
        "status": cmd_status,
        "budget": cmd_budget,
        "list": cmd_list,
        "init": cmd_init,
        "doctor": cmd_doctor,
        "inbox": cmd_inbox,
        "cg": cmd_cg,
        "task": cmd_task,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "register": cmd_register,
        "projects": cmd_projects,
    }

    if args.command == "feedback":
        feedback_dispatch = {
            "status": cmd_feedback_status,
            "consent": cmd_feedback_consent,
            "export": cmd_feedback_export,
        }
        handler = feedback_dispatch.get(getattr(args, "feedback_command", ""))
    else:
        handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "feedback" and getattr(args, "feedback_command", None) == "export":
        if args.limit <= 0:
            args.limit = None
        if not args.output:
            args.output = None

    handler(args)


if __name__ == "__main__":
    main()
