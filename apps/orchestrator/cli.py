"""harness-ctl — CLI for the agent harness orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TASKS_DIR = os.path.join(".harness", "tasks")


def _load_manifest(task_id: str) -> dict[str, Any] | None:
    """Load the manifest for a task, or None if not found."""
    path = os.path.join(TASKS_DIR, task_id, "manifest.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _list_tasks() -> list[str]:
    """List all task IDs in the harness directory."""
    if not os.path.isdir(TASKS_DIR):
        return []
    return sorted(
        d for d in os.listdir(TASKS_DIR)
        if os.path.isdir(os.path.join(TASKS_DIR, d)) and d.startswith("TASK-")
    )


def _print_json(data: Any) -> None:
    """Pretty-print a JSON-serialisable object."""
    print(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_submit(args: argparse.Namespace) -> None:
    """Submit a new task to the orchestrator."""
    from apps.orchestrator.main import run_task

    description = args.description
    task_type = args.type

    print(f"Submitting task: {description}")
    print(f"Type: {task_type}")
    print()

    try:
        result = asyncio.run(run_task(description, task_type))
        print("Task completed.")
        _print_json({
            "task_id": result.get("task_id"),
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
        manifest = _load_manifest(args.task_id)
        if manifest is None:
            print(f"Task {args.task_id} not found.", file=sys.stderr)
            sys.exit(1)

        # Also try to load validation results
        eval_path = os.path.join(TASKS_DIR, args.task_id, "evals", "validation.json")
        eval_data = None
        if os.path.exists(eval_path):
            with open(eval_path) as f:
                eval_data = json.load(f)

        status_info = {
            **manifest,
            "eval_results": eval_data,
        }
        _print_json(status_info)
    else:
        # Show all tasks
        tasks = _list_tasks()
        if not tasks:
            print("No tasks found.")
            return

        for tid in tasks:
            manifest = _load_manifest(tid)
            if manifest:
                print(
                    f"  {tid}  type={manifest.get('task_type', '?'):20s}  "
                    f"created={manifest.get('created_at', '?')}"
                )
            else:
                print(f"  {tid}  (no manifest)")


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
    tasks = _list_tasks()
    if not tasks:
        print("No tasks found.")
        return

    print(f"{'Task ID':<12} {'Type':<22} {'Created'}")
    print("-" * 60)
    for tid in tasks:
        manifest = _load_manifest(tid)
        if manifest:
            print(
                f"{tid:<12} {manifest.get('task_type', '?'):<22} "
                f"{manifest.get('created_at', '?')}"
            )
        else:
            print(f"{tid:<12} {'?':<22} ?")


def cmd_approve(args: argparse.Namespace) -> None:
    """Approve a task (human-in-the-loop gate)."""
    task_id = args.task_id
    manifest = _load_manifest(task_id)
    if manifest is None:
        print(f"Task {task_id} not found.", file=sys.stderr)
        sys.exit(1)

    # Write approval marker
    approval_path = os.path.join(TASKS_DIR, task_id, "approved.json")
    approval = {
        "task_id": task_id,
        "approved": True,
        "approved_by": "cli",
    }
    with open(approval_path, "w") as f:
        json.dump(approval, f, indent=2)

    print(f"Task {task_id} approved.")


def cmd_reject(args: argparse.Namespace) -> None:
    """Reject a task with a reason."""
    task_id = args.task_id
    manifest = _load_manifest(task_id)
    if manifest is None:
        print(f"Task {task_id} not found.", file=sys.stderr)
        sys.exit(1)

    reason = args.reason or "No reason provided"

    rejection_path = os.path.join(TASKS_DIR, task_id, "rejected.json")
    rejection = {
        "task_id": task_id,
        "approved": False,
        "rejected_by": "cli",
        "reason": reason,
    }
    with open(rejection_path, "w") as f:
        json.dump(rejection, f, indent=2)

    print(f"Task {task_id} rejected: {reason}")


def cmd_register(args: argparse.Namespace) -> None:
    """Register a project for harness management."""
    import subprocess

    import yaml

    repo_path = os.path.abspath(args.path)
    project_name = args.name or os.path.basename(repo_path)

    if not os.path.isdir(repo_path):
        print(f"Directory not found: {repo_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Registering project: {project_name}")
    print(f"  Path: {repo_path}")
    print()

    # 1. Create AGENTS.md if it doesn't exist
    agents_md_path = os.path.join(repo_path, "AGENTS.md")
    if not os.path.exists(agents_md_path):
        # Detect language and build/test commands
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

        agents_md = f"""# AGENTS.md

## Project: {project_name}
## Language: {language}
## Build: {build_cmd}
## Test: {test_cmd}
## Lint: {lint_cmd}

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

## codegraph
Graph at `.codegraph/graph.db`. Run `codegraph build` after structural changes.
Before modifying code:
1. `codegraph where <symbol>` — find where it lives
2. `codegraph context <symbol>` — check who calls it
3. `codegraph fn-impact <symbol>` — check blast radius after changes
"""
        with open(agents_md_path, "w") as f:
            f.write(agents_md)
        print(f"  Created: {agents_md_path}")
    else:
        print(f"  Found existing: {agents_md_path}")

    # 2. Add .codegraph/ and .harness/ to project .gitignore
    gitignore_path = os.path.join(repo_path, ".gitignore")
    entries_to_add = [".codegraph/", ".harness/"]
    existing_lines: list[str] = []
    if os.path.exists(gitignore_path):
        with open(gitignore_path) as f:
            existing_lines = f.read().splitlines()

    added = []
    for entry in entries_to_add:
        if entry not in existing_lines:
            existing_lines.append(entry)
            added.append(entry)

    if added:
        with open(gitignore_path, "w") as f:
            f.write("\n".join(existing_lines) + "\n")
        print(f"  Updated .gitignore: added {', '.join(added)}")

    # 3. Build codegraph
    print("  Building codegraph...")
    try:
        result = subprocess.run(
            ["codegraph", "build"],
            cwd=repo_path,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            # Extract summary from output
            for line in result.stderr.splitlines() + result.stdout.splitlines():
                if "Graph built" in line or "nodes" in line:
                    print(f"  {line.strip()}")
                    break
            else:
                print("  Codegraph built successfully")
        else:
            print(f"  Codegraph build warning: {result.stderr[:200]}")
    except FileNotFoundError:
        print("  Codegraph not found — install with: npm install -g @optave/codegraph")
    except subprocess.TimeoutExpired:
        print("  Codegraph build timed out (large repo?) — run manually: cd {repo_path} && codegraph build")

    # 4. Create per-project data directory
    harness_data = os.environ.get("HARNESS_DATA", "data")
    project_data = os.path.join(harness_data, "projects", project_name)
    for subdir in ["tasks", "sqlite", "learning"]:
        os.makedirs(os.path.join(project_data, subdir), exist_ok=True)
    print(f"  Project data: {project_data}")

    # 5. Create per-project config
    config_dir = os.environ.get("HARNESS_CONFIG", "config")
    projects_config_dir = os.path.join(config_dir, "projects")
    os.makedirs(projects_config_dir, exist_ok=True)

    project_config_path = os.path.join(projects_config_dir, f"{project_name}.yaml")
    if not os.path.exists(project_config_path):
        project_config = {
            "project": {
                "name": project_name,
                "repo_path": repo_path,
                "registered_at": __import__("datetime").datetime.now().isoformat(),
            },
        }
        with open(project_config_path, "w") as f:
            yaml.dump(project_config, f, default_flow_style=False)
        print(f"  Config: {project_config_path}")

    # 6. Register in harness.yaml
    harness_config_path = os.path.join(config_dir, "harness.yaml")
    if os.path.exists(harness_config_path):
        with open(harness_config_path) as f:
            cfg = yaml.safe_load(f) or {}
        projects = cfg.setdefault("projects", {})
        projects[project_name] = repo_path
        with open(harness_config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)

    print()
    print(f"Project '{project_name}' registered.")
    print(f"  Submit tasks with: harness-ctl submit 'description' --project {project_name}")


def cmd_projects(args: argparse.Namespace) -> None:
    """List registered projects."""
    import yaml

    config_dir = os.environ.get("HARNESS_CONFIG", "config")
    harness_config_path = os.path.join(config_dir, "harness.yaml")

    if not os.path.exists(harness_config_path):
        print("No harness config found.")
        return

    with open(harness_config_path) as f:
        cfg = yaml.safe_load(f) or {}

    projects = cfg.get("projects", {})
    if not projects:
        print("No projects registered. Use: harness-ctl register /path/to/project")
        return

    print(f"{'Project':<20} {'Path'}")
    print("-" * 60)
    for name, path in projects.items():
        exists = "OK" if os.path.isdir(path) else "MISSING"
        print(f"{name:<20} {path}  [{exists}]")


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

    # status
    p_status = subparsers.add_parser("status", help="Show task status")
    p_status.add_argument("task_id", nargs="?", help="Task ID (omit to show all)")

    # budget
    p_budget = subparsers.add_parser("budget", help="Show budget usage")
    p_budget.add_argument("task_id", nargs="?", help="Task ID")

    # list
    subparsers.add_parser("list", help="List all tasks")

    # approve
    p_approve = subparsers.add_parser("approve", help="Approve a task")
    p_approve.add_argument("task_id", help="Task ID to approve")

    # reject
    p_reject = subparsers.add_parser("reject", help="Reject a task")
    p_reject.add_argument("task_id", help="Task ID to reject")
    p_reject.add_argument("--reason", default="", help="Rejection reason")

    # register
    p_register = subparsers.add_parser("register", help="Register a project")
    p_register.add_argument("path", help="Path to the project repository")
    p_register.add_argument("--name", default="", help="Project name (default: directory name)")

    # projects
    subparsers.add_parser("projects", help="List registered projects")

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
        "approve": cmd_approve,
        "reject": cmd_reject,
        "register": cmd_register,
        "projects": cmd_projects,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
