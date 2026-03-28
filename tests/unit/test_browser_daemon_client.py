"""Unit tests for browser daemon helpers."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from packages.browser_daemon.client import BrowserDaemonClient
from packages.browser_daemon.manager import BrowserDaemonManager
from packages.browser_daemon.models import BrowserDaemonSession
from packages.config.runtime import get_project_paths


def test_browser_daemon_manager_reads_state_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    (harness_root / "config").mkdir(parents=True)
    (harness_root / "config" / "harness.yaml").write_text(
        "harness:\n  data_dir: data\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    paths = get_project_paths(repo_path=str(repo_path))
    paths.ensure_dirs()
    paths.browser_state_file.write_text(
        json.dumps(
            {
                "pid": 123,
                "port": 4567,
                "token": "secret",
                "started_at": "2026-03-27T00:00:00Z",
                "last_seen_at": "2026-03-27T00:01:00Z",
                "mode": "headless",
                "version": "v1",
            }
        ),
        encoding="utf-8",
    )

    manager = BrowserDaemonManager(paths)
    session = manager.read_session()

    assert session == BrowserDaemonSession(
        pid=123,
        port=4567,
        token="secret",
        started_at="2026-03-27T00:00:00Z",
        last_seen_at="2026-03-27T00:01:00Z",
        mode="headless",
        version="v1",
    )


def test_browser_daemon_manager_health_uses_http_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    (harness_root / "config").mkdir(parents=True)
    (harness_root / "config" / "harness.yaml").write_text(
        "harness:\n  data_dir: data\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    paths = get_project_paths(repo_path=str(repo_path))
    manager = BrowserDaemonManager(paths)

    def _fake_get(url: str, timeout: float) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, json={"status": "healthy"})

    monkeypatch.setattr(httpx, "get", _fake_get)

    assert manager.is_healthy(
        BrowserDaemonSession(
            pid=1,
            port=1234,
            token="secret",
            started_at="2026-03-27T00:00:00Z",
            last_seen_at="2026-03-27T00:00:01Z",
        )
    )


def test_browser_daemon_client_returns_normalized_command_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    (harness_root / "config").mkdir(parents=True)
    (harness_root / "config" / "harness.yaml").write_text(
        "harness:\n  data_dir: data\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    paths = get_project_paths(repo_path=str(repo_path))
    client = BrowserDaemonClient(paths)

    session = BrowserDaemonSession(
        pid=1,
        port=9999,
        token="secret",
        started_at="2026-03-27T00:00:00Z",
        last_seen_at="2026-03-27T00:00:01Z",
    )
    monkeypatch.setattr(client._manager, "ensure_running", lambda: session)

    def _fake_post(
        url: str,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
    ) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "ok": True,
                "command": json["command"],
                "result": {"current_url": "http://localhost:3000/"},
            },
        )

    monkeypatch.setattr(httpx, "post", _fake_post)

    result = client.command("status")

    assert result.ok is True
    assert result.command == "status"
    assert result.result["current_url"] == "http://localhost:3000/"
