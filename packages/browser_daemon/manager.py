"""Lifecycle management for the local browser daemon sidecar."""

from __future__ import annotations

import json
import logging
import os
import secrets
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from packages.config import ProjectPaths, get_harness_root

from .models import BrowserDaemonSession

logger = logging.getLogger(__name__)

_START_TIMEOUT_SECONDS = 10.0
_HEALTH_TIMEOUT_SECONDS = 2.0


class BrowserDaemonManager:
    """Start, stop, and inspect the project-scoped browser daemon."""

    def __init__(
        self,
        project_paths: ProjectPaths,
        node_bin: str | None = None,
        daemon_script: Path | None = None,
    ) -> None:
        self._paths = project_paths
        self._node_bin = node_bin or os.environ.get("HARNESS_NODE_BIN", "node")
        self._daemon_script = daemon_script or (
            get_harness_root() / "tools" / "browser-daemon" / "src" / "server.js"
        )

    def read_session(self) -> BrowserDaemonSession | None:
        """Read the current daemon state file if present and valid."""
        path = self._paths.browser_state_file
        if not path.is_file():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return BrowserDaemonSession.from_dict(payload)
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("Failed to parse browser state file: %s", path, exc_info=True)
            return None

    def is_healthy(self, session: BrowserDaemonSession | None = None) -> bool:
        """Return True when the daemon responds healthy for the given session."""
        active = session or self.read_session()
        if active is None:
            return False

        try:
            response = httpx.get(
                f"http://127.0.0.1:{active.port}/health",
                timeout=_HEALTH_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError:
            return False

        if response.status_code != 200:
            return False

        try:
            payload = response.json()
        except ValueError:
            return False

        return payload.get("status") == "healthy"

    def ensure_running(self) -> BrowserDaemonSession:
        """Return a healthy session, starting the daemon if needed."""
        self._paths.ensure_dirs()

        current = self.read_session()
        if current is not None and self.is_healthy(current):
            return current

        self.start()
        deadline = time.monotonic() + _START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            current = self.read_session()
            if current is not None and self.is_healthy(current):
                return current
            time.sleep(0.1)

        raise RuntimeError("Browser daemon failed to become healthy before timeout")

    def start(self) -> subprocess.Popen[str]:
        """Spawn the daemon process in the background."""
        self._paths.ensure_dirs()
        token = secrets.token_hex(24)

        env = os.environ.copy()
        env["HARNESS_BROWSER_STATE_FILE"] = str(self._paths.browser_state_file)
        env["HARNESS_BROWSER_ARTIFACTS_DIR"] = str(self._paths.browser_artifacts_dir)
        env["HARNESS_BROWSER_CONSOLE_LOG"] = str(self._paths.browser_console_log)
        env["HARNESS_BROWSER_NETWORK_LOG"] = str(self._paths.browser_network_log)
        env["HARNESS_BROWSER_TOKEN"] = token
        env["HARNESS_BROWSER_MODE"] = "headless"
        env["HARNESS_BROWSER_VERSION"] = "v1"

        logger.info("Starting browser daemon using %s", self._daemon_script)
        return subprocess.Popen(
            [self._node_bin, str(self._daemon_script)],
            cwd=str(get_harness_root()),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def stop(self) -> None:
        """Request daemon shutdown if the session is available."""
        session = self.read_session()
        if session is None:
            return

        try:
            httpx.post(
                f"http://127.0.0.1:{session.port}/shutdown",
                headers={"Authorization": f"Bearer {session.token}"},
                timeout=_HEALTH_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError:
            logger.debug("Browser daemon shutdown request failed", exc_info=True)

    def write_state_file(self, payload: dict[str, Any]) -> None:
        """Atomically write a daemon state payload with restrictive permissions."""
        self._paths.browser_dir.mkdir(parents=True, exist_ok=True)
        target = self._paths.browser_state_file
        tmp_path = target.with_suffix(".tmp")

        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_path, target)
