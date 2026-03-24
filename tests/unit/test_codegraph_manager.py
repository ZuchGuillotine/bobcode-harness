"""Unit tests for codegraph provisioning helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from packages.repo_intel.codegraph_manager import build_codegraph, codegraph_artifact_path


def test_codegraph_artifact_path_is_repo_local(tmp_path: Path) -> None:
    repo = tmp_path / "demo-repo"
    repo.mkdir()

    assert codegraph_artifact_path(repo) == repo / ".codegraph" / "graph.db"


@patch("packages.repo_intel.codegraph_manager.shutil.which", return_value=None)
def test_build_codegraph_reports_missing_binary(_mock_which: MagicMock, tmp_path: Path) -> None:
    repo = tmp_path / "demo-repo"
    repo.mkdir()

    result = build_codegraph(repo)

    assert result.available is False
    assert result.success is False
    assert "install" in result.message.lower()


@patch("packages.repo_intel.codegraph_manager.shutil.which", return_value="/usr/bin/codegraph")
@patch("packages.repo_intel.codegraph_manager.subprocess.run")
def test_build_codegraph_success_uses_summary_line(
    mock_run: MagicMock,
    _mock_which: MagicMock,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "demo-repo"
    repo.mkdir()

    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="",
        stderr="Graph built successfully with 123 nodes",
    )

    result = build_codegraph(repo)

    assert result.available is True
    assert result.success is True
    assert "123 nodes" in result.message

