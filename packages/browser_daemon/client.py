"""HTTP client for the local browser daemon."""

from __future__ import annotations

from typing import Any

import httpx

from packages.config import ProjectPaths

from .manager import BrowserDaemonManager
from .models import BrowserDaemonCommandResult, BrowserDaemonSession


class BrowserDaemonClient:
    """Small sync client used by orchestrator components."""

    def __init__(self, project_paths: ProjectPaths) -> None:
        self._manager = BrowserDaemonManager(project_paths)

    def ensure_running(self) -> BrowserDaemonSession:
        """Ensure the daemon is healthy and return session metadata."""
        return self._manager.ensure_running()

    def health(self) -> dict[str, Any]:
        """Read health details from the daemon."""
        session = self.ensure_running()
        response = httpx.get(f"http://127.0.0.1:{session.port}/health", timeout=2.0)
        response.raise_for_status()
        return dict(response.json())

    def command(self, command: str, args: list[str] | None = None) -> BrowserDaemonCommandResult:
        """Invoke a daemon command and return a normalized response."""
        session = self.ensure_running()
        response = httpx.post(
            f"http://127.0.0.1:{session.port}/command",
            headers={"Authorization": f"Bearer {session.token}"},
            json={"command": command, "args": args or []},
            timeout=30.0,
        )
        response.raise_for_status()
        payload = dict(response.json())
        return BrowserDaemonCommandResult(
            ok=bool(payload.get("ok")),
            command=str(payload.get("command", command)),
            result=dict(payload.get("result", {})),
            error=payload.get("error"),
        )

    def stop(self) -> None:
        """Shut down the daemon if it is currently running."""
        self._manager.stop()
