"""Unit tests for CLI registration helpers."""

from __future__ import annotations

from pathlib import Path

from apps.orchestrator.cli import _ensure_codegraph_ignore


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
