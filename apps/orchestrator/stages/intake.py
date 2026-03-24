"""Intake stage — validates task input, assigns ID, initialises budget."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from apps.orchestrator.task_router import TaskRouter
from packages.llm.router import LLMRouter
from packages.state.sqlite_store import SQLiteStore
from packages.state.task_state import TaskStateManager

logger = logging.getLogger(__name__)

# Base directory for task working data
HARNESS_DIR = ".harness"
TASKS_DIR = os.path.join(HARNESS_DIR, "tasks")

# Counter file for sequential task IDs
_COUNTER_FILE = os.path.join(HARNESS_DIR, ".task_counter")

_DB_PATH = os.environ.get("HARNESS_DB_PATH", os.path.join(HARNESS_DIR, "harness.db"))


def _next_task_id() -> str:
    """Generate the next sequential task ID (TASK-001, TASK-002, ...)."""

    os.makedirs(HARNESS_DIR, exist_ok=True)

    counter = 1
    if os.path.exists(_COUNTER_FILE):
        try:
            with open(_COUNTER_FILE) as f:
                counter = int(f.read().strip()) + 1
        except (ValueError, OSError):
            counter = 1

    with open(_COUNTER_FILE, "w") as f:
        f.write(str(counter))

    return f"TASK-{counter:03d}"


def _create_task_directory(task_id: str) -> str:
    """Create the working directory for a task via TaskStateManager."""
    try:
        tsm = TaskStateManager()
        task_path = tsm.create_task_dir(task_id)
        return str(task_path)
    except Exception:
        # Fallback to manual directory creation
        task_dir = os.path.join(TASKS_DIR, task_id)
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

    # --- Assign ID ---
    task_id = _next_task_id()
    trace_id = str(uuid.uuid4())

    # --- Create task directory ---
    task_dir = _create_task_directory(task_id)

    # --- Write task manifest ---
    import json

    manifest = {
        "task_id": task_id,
        "task_type": task_type,
        "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
    }

    manifest_path = os.path.join(task_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # --- Persist task to SQLiteStore ---
    try:
        store = SQLiteStore(_DB_PATH)
        store.create_task({
            "task_id": task_id,
            "title": description[:120],
            "description": description,
            "status": "pending",
            "metadata": manifest,
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
        "Intake complete: %s type=%s domain=%s trace=%s",
        task_id,
        task_type,
        domain,
        trace_id,
    )

    return {
        **state,
        "task_id": task_id,
        "task_type": task_type,
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
