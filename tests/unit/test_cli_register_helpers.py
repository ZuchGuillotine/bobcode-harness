"""Unit tests for CLI registration helpers."""

from __future__ import annotations

from pathlib import Path

from apps.orchestrator.cli import (
    _create_agent_task_scaffold,
    _ensure_codegraph_ignore,
    _local_state_ignore,
    _shared_state_ignore,
)


def test_external_mode_uses_git_info_exclude(tmp_path: Path) -> None:
    repo = tmp_path / "demo-repo"
    (repo / ".git" / "info").mkdir(parents=True)

    ignore_path, added = _ensure_codegraph_ignore(repo, "external")

    assert ignore_path == repo / ".git" / "info" / "exclude"
    assert added == [".codegraph/"]
    assert ".codegraph/" in ignore_path.read_text(encoding="utf-8")


def test_assisted_mode_uses_gitignore(tmp_path: Path) -> None:
    repo = tmp_path / "demo-repo"
    repo.mkdir()

    ignore_path, added = _ensure_codegraph_ignore(repo, "assisted")

    assert ignore_path == repo / ".gitignore"
    assert added == [".codegraph/"]
    assert ".codegraph/" in ignore_path.read_text(encoding="utf-8")


def test_local_state_ignore_uses_git_info_exclude(tmp_path: Path) -> None:
    repo = tmp_path / "demo-repo"
    (repo / ".git" / "info").mkdir(parents=True)

    ignore_path, added = _local_state_ignore(repo)

    assert ignore_path == repo / ".git" / "info" / "exclude"
    assert added == [".bobcode/", ".codegraph/"]
    content = ignore_path.read_text(encoding="utf-8")
    assert ".bobcode/" in content
    assert ".codegraph/" in content


def test_shared_state_ignore_uses_gitignore(tmp_path: Path) -> None:
    repo = tmp_path / "demo-repo"
    repo.mkdir()

    ignore_path, added = _shared_state_ignore(repo)

    assert ignore_path == repo / ".gitignore"
    assert added == [".bobcode/", ".codegraph/"]
    content = ignore_path.read_text(encoding="utf-8")
    assert ".bobcode/" in content
    assert ".codegraph/" in content


def test_create_agent_task_scaffold_without_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "demo-repo"
    (repo / ".git" / "info").mkdir(parents=True)

    payload = _create_agent_task_scaffold(
        repo_root=repo,
        slug="Fix login flow",
        description="Fix the login flow",
        owner_agent="claude",
        create_worktree=False,
    )

    task_dir = Path(payload["task_dir"])
    assert payload["task_id"] == "TASK-001"
    assert payload["slug"] == "fix-login-flow"
    assert payload["worktree_path"] is None
    assert (task_dir / "manifest.json").is_file()
    assert (task_dir / "state.json").is_file()
    assert (task_dir / "plan.json").is_file()
    assert (task_dir / "progress.jsonl").is_file()
    assert (repo / ".bobcode" / "progress.jsonl").is_file()
    assert ".bobcode/" in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
