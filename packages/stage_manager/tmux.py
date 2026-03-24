"""Tmux session manager for running tasks in isolated terminals."""

from __future__ import annotations

import logging
import subprocess
import time

logger = logging.getLogger(__name__)

_SESSION_PREFIX = "harness-"


class TmuxManager:
    """Create and manage tmux sessions for task execution."""

    @staticmethod
    def _session_name(task_id: str) -> str:
        """Normalise *task_id* into a tmux-safe session name."""
        return f"{_SESSION_PREFIX}{task_id}"

    @staticmethod
    def _run(
        *args: str, check: bool = False, timeout: int = 30
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["tmux", *args]
        logger.debug("Running: %s", " ".join(cmd))
        return subprocess.run(
            cmd, capture_output=True, text=True, check=check, timeout=timeout
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_session(self, task_id: str) -> str:
        """Create a new detached tmux session for *task_id*.

        Returns the session name.
        """
        name = self._session_name(task_id)

        # Check if session already exists
        result = self._run("has-session", "-t", name)
        if result.returncode == 0:
            logger.info("Tmux session '%s' already exists", name)
            return name

        result = self._run("new-session", "-d", "-s", name)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create tmux session '{name}': {result.stderr.strip()}"
            )

        logger.info("Created tmux session: %s", name)
        return name

    def run_command(self, task_id: str, command: str, wait_secs: float = 2.0) -> str:
        """Send *command* to the task's tmux session and capture output.

        Waits *wait_secs* then reads back the pane content.
        """
        name = self._session_name(task_id)

        # Send the command
        self._run("send-keys", "-t", name, command, "Enter")

        # Give the command time to produce output
        time.sleep(wait_secs)

        # Capture the pane content
        result = self._run("capture-pane", "-t", name, "-p")
        if result.returncode != 0:
            logger.warning(
                "Failed to capture pane for '%s': %s", name, result.stderr.strip()
            )
            return ""

        return result.stdout

    def kill_session(self, task_id: str) -> None:
        """Kill the tmux session for *task_id*."""
        name = self._session_name(task_id)
        result = self._run("kill-session", "-t", name)
        if result.returncode != 0:
            logger.warning(
                "Failed to kill tmux session '%s': %s", name, result.stderr.strip()
            )
        else:
            logger.info("Killed tmux session: %s", name)

    def list_sessions(self) -> list[str]:
        """Return names of all harness-managed tmux sessions."""
        result = self._run("list-sessions", "-F", "#{session_name}")
        if result.returncode != 0:
            # tmux returns non-zero when no server is running
            return []

        sessions: list[str] = []
        for line in result.stdout.strip().splitlines():
            name = line.strip()
            if name.startswith(_SESSION_PREFIX):
                sessions.append(name)
        return sessions
