"""Filesystem-backed task state management for task directories."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HARNESS_DIR = ".harness"
_TASKS_DIR = "tasks"

# Standard subdirectories created inside each task directory
_SUBDIRS = ("artifacts", "logs", "patches", "evals")


class TaskStateManager:
    """Manages per-task directories and JSON state files."""

    def __init__(self, root: str = ".", tasks_dir: str | None = None) -> None:
        self._root = Path(root).resolve()
        if tasks_dir is None:
            if root == ".":
                from packages.config import get_project_paths

                self._base = get_project_paths().tasks_dir
            else:
                self._base = self._root / _HARNESS_DIR / _TASKS_DIR
        else:
            self._base = Path(tasks_dir).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Directory management
    # ------------------------------------------------------------------

    def _task_dir(self, task_id: str) -> Path:
        return self._base / task_id

    def create_task_dir(self, task_id: str) -> Path:
        """Create the directory tree for a task and return its Path."""
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        for sub in _SUBDIRS:
            (task_dir / sub).mkdir(exist_ok=True)
        logger.info("Created task directory: %s", task_dir)
        return task_dir

    # ------------------------------------------------------------------
    # State (state.json)
    # ------------------------------------------------------------------

    def write_state(self, task_id: str, state: dict[str, Any]) -> None:
        """Persist *state* as ``state.json`` inside the task directory."""
        path = self._task_dir(task_id) / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    def read_state(self, task_id: str) -> dict[str, Any]:
        """Load and return ``state.json``.  Returns ``{}`` if missing."""
        path = self._task_dir(task_id) / "state.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Plan (plan.json)
    # ------------------------------------------------------------------

    def write_plan(self, task_id: str, plan: dict[str, Any]) -> None:
        path = self._task_dir(task_id) / "plan.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")

    def read_plan(self, task_id: str) -> dict[str, Any]:
        path = self._task_dir(task_id) / "plan.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Budget (budget.json)
    # ------------------------------------------------------------------

    def write_budget(self, task_id: str, budget: dict[str, Any]) -> None:
        path = self._task_dir(task_id) / "budget.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(budget, indent=2, default=str), encoding="utf-8")

    def read_budget(self, task_id: str) -> dict[str, Any]:
        path = self._task_dir(task_id) / "budget.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------

    def add_artifact(self, task_id: str, name: str, content: bytes) -> Path:
        """Write binary *content* to the artifacts subdirectory."""
        artifacts_dir = self._task_dir(task_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = artifacts_dir / name
        path.write_bytes(content)
        logger.debug("Stored artifact %s for %s", name, task_id)
        return path

    def list_artifacts(self, task_id: str) -> list[str]:
        """Return names of all stored artifacts for *task_id*."""
        artifacts_dir = self._task_dir(task_id) / "artifacts"
        if not artifacts_dir.is_dir():
            return []
        return sorted(p.name for p in artifacts_dir.iterdir() if p.is_file())
