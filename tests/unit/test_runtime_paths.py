"""Unit tests for project/runtime path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.config.runtime import (
    find_task_dir,
    get_community_dir,
    get_project_paths,
    iter_registered_projects,
)


def test_project_paths_use_registered_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness_root = tmp_path / "harness"
    config_dir = harness_root / "config" / "projects"
    config_dir.mkdir(parents=True)
    data_dir = harness_root / "data"
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()

    (harness_root / "config" / "harness.yaml").write_text(
        "harness:\n  data_dir: data\n",
        encoding="utf-8",
    )
    (config_dir / "demo.yaml").write_text(
        f"project:\n  name: demo\n  repo_path: {repo_path}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    paths = get_project_paths(project_name="demo")
    assert paths.repo_path == repo_path.resolve()
    assert paths.project_dir == data_dir / "projects" / "demo"
    assert paths.db_path == data_dir / "projects" / "demo" / "sqlite" / "harness.db"

    registered = dict(iter_registered_projects())
    assert registered["demo"] == repo_path.resolve()


def test_find_task_dir_searches_registered_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness_root = tmp_path / "harness"
    config_dir = harness_root / "config" / "projects"
    config_dir.mkdir(parents=True)
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()

    (harness_root / "config" / "harness.yaml").write_text(
        "harness:\n  data_dir: data\n",
        encoding="utf-8",
    )
    (config_dir / "demo.yaml").write_text(
        f"project:\n  name: demo\n  repo_path: {repo_path}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    task_dir = harness_root / "data" / "projects" / "demo" / "tasks" / "TASK-001"
    task_dir.mkdir(parents=True)

    found = find_task_dir("TASK-001")
    assert found is not None
    assert found[0] == "demo"
    assert found[1] == task_dir


def test_get_community_dir_uses_harness_data_dir(
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

    assert get_community_dir() == harness_root / "data" / "community"
