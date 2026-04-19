"""Unit tests for CLI registration helpers."""

from __future__ import annotations

from pathlib import Path

from apps.orchestrator.cli import (
    _build_agents_md,
    _build_claude_md,
    _create_agent_task_scaffold,
    _ensure_codegraph_ignore,
    _extract_shared_doc_block,
    _local_state_ignore,
    _replace_shared_doc_block,
    _shared_state_ignore,
    _sync_agent_docs,
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


def test_agent_docs_share_identical_marked_block() -> None:
    repo_context = {
        "language": "Python",
        "build_cmd": "pip install -e .",
        "test_cmd": "pytest tests/",
        "lint_cmd": "ruff check .",
    }

    agents_md = _build_agents_md("demo", repo_context)
    claude_md = _build_claude_md("demo", repo_context)

    assert _extract_shared_doc_block(agents_md, "BOBCODE") == _extract_shared_doc_block(
        claude_md,
        "BOBCODE",
    )


def test_agent_doc_sync_detects_and_repairs_drift(tmp_path: Path) -> None:
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    repo_context = {
        "language": "Python",
        "build_cmd": "pip install -e .",
        "test_cmd": "pytest tests/",
        "lint_cmd": "ruff check .",
    }
    agents_path = repo / "AGENTS.md"
    claude_path = repo / "CLAUDE.md"
    agents_path.write_text(_build_agents_md("demo", repo_context), encoding="utf-8")
    claude_path.write_text(_build_claude_md("demo", repo_context), encoding="utf-8")

    mutated_block = (
        _extract_shared_doc_block(agents_path.read_text(encoding="utf-8"), "BOBCODE")
        + "\nExtra shared guidance.\n"
    )
    agents_path.write_text(
        _replace_shared_doc_block(
            agents_path.read_text(encoding="utf-8"),
            "BOBCODE",
            mutated_block,
        ),
        encoding="utf-8",
    )

    check = _sync_agent_docs(repo, "BOBCODE")
    assert check["ok"] is False
    assert check["drift"]

    synced = _sync_agent_docs(repo, "BOBCODE", source_key="agents", write=True)
    assert synced["ok"] is True
    assert synced["updated"] == [{"key": "claude", "path": str(claude_path)}]
    assert _extract_shared_doc_block(
        agents_path.read_text(encoding="utf-8"),
        "BOBCODE",
    ) == _extract_shared_doc_block(claude_path.read_text(encoding="utf-8"), "BOBCODE")


def test_agent_doc_markers_must_stand_alone() -> None:
    text = """# AGENTS.md

This prose mentions <!-- BEGIN SHARED:BOBCODE --> without starting a region.

<!-- BEGIN SHARED:BOBCODE -->
shared
<!-- END SHARED:BOBCODE -->
"""

    assert _extract_shared_doc_block(text, "BOBCODE") == "shared\n"
