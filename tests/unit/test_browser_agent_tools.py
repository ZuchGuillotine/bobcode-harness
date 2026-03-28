"""Unit tests for worker/reviewer browser tool integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.orchestrator.agents.reviewer import ReviewerAgent
from apps.orchestrator.agents.worker import WorkerAgent
from packages.browser_daemon.models import BrowserDaemonCommandResult
from packages.config.runtime import get_project_paths


def test_worker_browser_screenshot_records_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    (harness_root / "config").mkdir(parents=True)
    (harness_root / "config" / "harness.yaml").write_text(
        "harness:\n  data_dir: data\n",
        encoding="utf-8",
    )
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    paths = get_project_paths(repo_path=str(repo_path))
    worker = WorkerAgent(worktree_path=str(repo_path), project_paths=paths)

    monkeypatch.setattr(
        worker._browser,
        "command",
        lambda command, args=None: BrowserDaemonCommandResult(
            ok=True,
            command=command,
            result={
                "current_url": "http://localhost:3000/",
                "artifact_path": "/tmp/smoke.png",
            },
        ),
    )

    result = worker._tool_browser_screenshot("smoke")

    assert result["artifact_path"] == "/tmp/smoke.png"
    assert worker._pending_browser_artifacts[0]["type"] == "browser_evidence"
    assert worker._pending_browser_artifacts[0]["path"] == "/tmp/smoke.png"


def test_reviewer_browser_artifact_read_stays_within_runtime_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    (harness_root / "config").mkdir(parents=True)
    (harness_root / "config" / "harness.yaml").write_text(
        "harness:\n  data_dir: data\n",
        encoding="utf-8",
    )
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    paths = get_project_paths(repo_path=str(repo_path))
    paths.ensure_dirs()
    artifact = paths.browser_artifacts_dir / "shot.txt"
    artifact.write_text("hello", encoding="utf-8")

    reviewer = ReviewerAgent(worktree_path=str(repo_path), project_paths=paths)

    allowed = reviewer._tool_browser_artifact_read(str(artifact))
    denied = reviewer._tool_browser_artifact_read("/tmp/outside.txt")

    assert allowed["size_bytes"] == 5
    assert "hello" in allowed["preview_text"]
    assert "outside browser runtime" in denied["error"]
