"""Types for browser daemon state and responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BrowserDaemonSession:
    """Runtime metadata for a project-scoped browser daemon."""

    pid: int
    port: int
    token: str
    started_at: str
    last_seen_at: str
    mode: str = "headless"
    version: str = "v1"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BrowserDaemonSession":
        """Build a session from a state-file payload."""
        return cls(
            pid=int(data["pid"]),
            port=int(data["port"]),
            token=str(data["token"]),
            started_at=str(data["started_at"]),
            last_seen_at=str(data["last_seen_at"]),
            mode=str(data.get("mode", "headless")),
            version=str(data.get("version", "v1")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the session to a JSON-serializable dict."""
        return {
            "pid": self.pid,
            "port": self.port,
            "token": self.token,
            "started_at": self.started_at,
            "last_seen_at": self.last_seen_at,
            "mode": self.mode,
            "version": self.version,
        }


@dataclass(frozen=True)
class BrowserDaemonCommandResult:
    """Structured result from a daemon command request."""

    ok: bool
    command: str
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
