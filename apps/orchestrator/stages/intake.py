"""Intake stage — validates task input, assigns ID, initialises budget."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from apps.orchestrator.task_router import TaskRouter
from packages.config import get_project_paths
from packages.state.sqlite_store import SQLiteStore
from packages.state.task_state import TaskStateManager

logger = logging.getLogger(__name__)

def _next_task_id(counter_file: str) -> str:
    """Generate the next sequential task ID (TASK-001, TASK-002, ...)."""
    from pathlib import Path

    counter_path = Path(counter_file)
    counter_path.parent.mkdir(parents=True, exist_ok=True)

    counter = 1
    if counter_path.exists():
        try:
            with counter_path.open() as f:
                counter = int(f.read().strip()) + 1
        except (ValueError, OSError):
            counter = 1

    with counter_path.open("w") as f:
        f.write(str(counter))

    return f"TASK-{counter:03d}"


def _create_task_directory(task_id: str, tasks_dir: str) -> str:
    """Create the working directory for a task via TaskStateManager."""
    try:
        tsm = TaskStateManager(tasks_dir=tasks_dir)
        task_path = tsm.create_task_dir(task_id)
        return str(task_path)
    except Exception:
        import os

        # Fallback to manual directory creation
        task_dir = os.path.join(tasks_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        for subdir in ("artifacts", "traces", "evals"):
            os.makedirs(os.path.join(task_dir, subdir), exist_ok=True)
        return task_dir


def intake_node(state: dict[str, Any]) -> dict[str, Any]:
    """Validate task input, assign a task ID, and initialise state.

    This is the first node in the orchestrator graph.
    """

    description = state.get("description", "").strip()

    # --- Validation ---
    if not description:
        logger.error("Task submitted with empty description")
        return {
            **state,
            "status": "failed",
            "error": "Task description is required",
        }

    # --- Task classification via TaskRouter (backed by LLMRouter) ---
    task_type = state.get("task_type", "")
    if not task_type:
        router = TaskRouter()
        task_type = router.classify_task(description)

    project_paths = get_project_paths(
        project_name=state.get("project_name"),
        repo_path=state.get("repo_path"),
    )
    project_paths.ensure_dirs()

    # --- Assign ID ---
    task_id = _next_task_id(str(project_paths.counter_file))
    trace_id = str(uuid.uuid4())

    # --- Create task directory ---
    task_dir = _create_task_directory(task_id, str(project_paths.tasks_dir))

    # --- Write task manifest ---
    import json

    manifest = {
        "task_id": task_id,
        "task_type": task_type,
        "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "project_name": project_paths.project_name,
        "repo_path": str(project_paths.repo_path) if project_paths.repo_path else None,
    }

    import os

    manifest_path = os.path.join(task_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # --- Persist task to SQLiteStore ---
    try:
        store = SQLiteStore(str(project_paths.db_path))
        store.create_task({
            "task_id": task_id,
            "title": description[:120],
            "description": description,
            "status": "pending",
            "branch": state.get("branch"),
            "metadata": manifest,
            "worktree_path": state.get("worktree_path"),
        })
        store.close()
    except Exception:
        logger.debug("Failed to persist task to SQLite", exc_info=True)

    # --- Initialise budget with defaults if not provided ---
    budget = state.get("budget", {})
    budget.setdefault("max_tokens", 500_000)
    budget.setdefault("max_cost_usd", 5.00)
    budget.setdefault("tokens_used", 0)
    budget.setdefault("cost_used", 0.0)

    # --- Determine domain ---
    domain = state.get("domain", "")
    if not domain:
        domain = _infer_domain(task_type)

    logger.info(
        "Intake complete: %s project=%s type=%s domain=%s trace=%s",
        task_id,
        project_paths.project_name or "legacy",
        task_type,
        domain,
        trace_id,
    )

    return {
        **state,
        "task_id": task_id,
        "task_type": task_type,
        "project_name": project_paths.project_name,
        "repo_path": str(project_paths.repo_path) if project_paths.repo_path else state.get("repo_path"),
        "domain": domain,
        "description": description,
        "status": "planning",
        "trace_id": trace_id,
        "budget": budget,
        "retries": 0,
        "max_retries": state.get("max_retries", 3),
        "error": None,
    }


def _infer_domain(task_type: str) -> str:
    """Infer a default domain from the task type."""
    domain_map = {
        "code_change": "engineering",
        "marketing_campaign": "marketing",
        "content_creation": "content",
    }
    return domain_map.get(task_type, "general")
