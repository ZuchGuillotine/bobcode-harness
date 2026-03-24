"""Git worktree manager for task isolation."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WORKTREE_BASE = ".harness/worktrees"


class WorktreeManager:
    """Create and manage git worktrees for parallel task execution."""

    def __init__(self, repo_path: str = ".") -> None:
        self._repo = Path(repo_path).resolve()
        self._base = self._repo / _WORKTREE_BASE
        self._base.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, repo_path: str, task_id: str, branch: str) -> Path:
        """Create a worktree for *task_id* on *branch*.

        Returns the Path to the new worktree directory.
        """
        repo = Path(repo_path).resolve()
        wt_path = self._base / task_id

        if wt_path.exists():
            logger.info("Worktree already exists for %s at %s", task_id, wt_path)
            return wt_path

        # Ensure the branch exists (create if needed)
        self._ensure_branch(repo, branch)

        cmd = [
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            str(wt_path),
            branch,
        ]
        logger.info("Creating worktree: %s", " ".join(cmd))
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed (rc={result.returncode}): {result.stderr.strip()}"
            )
        return wt_path

    def cleanup(self, task_id: str) -> None:
        """Remove the worktree for *task_id*."""
        wt_path = self._base / task_id

        # git worktree remove
        cmd = [
            "git",
            "worktree",
            "remove",
            str(wt_path),
            "--force",
        ]
        logger.info("Removing worktree: %s", " ".join(cmd))
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            logger.warning(
                "git worktree remove failed: %s", result.stderr.strip()
            )
            # Try manual cleanup as fallback
            import shutil

            if wt_path.exists():
                shutil.rmtree(wt_path, ignore_errors=True)
                logger.info("Manually removed worktree dir %s", wt_path)

    def get_worktree_path(self, task_id: str) -> Path:
        """Return the expected worktree path for *task_id*."""
        return self._base / task_id

    def list_active(self) -> list[dict[str, Any]]:
        """List all active git worktrees as dicts.

        Each dict has keys: ``path``, ``branch``, ``head``.
        """
        cmd = ["git", "-C", str(self._repo), "worktree", "list", "--porcelain"]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            logger.warning("git worktree list failed: %s", result.stderr.strip())
            return []

        worktrees: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in result.stdout.splitlines():
            if not line.strip():
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line.split(" ", 1)[1]
            elif line.startswith("HEAD "):
                current["head"] = line.split(" ", 1)[1]
            elif line.startswith("branch "):
                current["branch"] = line.split(" ", 1)[1]

        if current:
            worktrees.append(current)

        return worktrees

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_branch(repo: Path, branch: str) -> None:
        """Create *branch* if it doesn't already exist."""
        check = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", branch],
            capture_output=True,
            text=True,
            check=False,
        )
        if check.returncode != 0:
            subprocess.run(
                ["git", "-C", str(repo), "branch", branch],
                capture_output=True,
                text=True,
                check=False,
            )
