"""Unit tests for Telegram bot runtime path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.notifications.telegram_bot import (
    _resolve_legacy_sqlite_path,
    _resolve_telegram_project,
)


def test_resolve_telegram_project_prefers_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    project = _resolve_telegram_project(
        {"notifications": {"telegram": {"project": "demo"}}},
        env={"TELEGRAM_PROJECT": "override"},
    )

    assert project == "override"


def test_resolve_telegram_project_auto_selects_single_registered_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    project = _resolve_telegram_project({}, env={})

    assert project == "demo"


def test_resolve_legacy_sqlite_path_uses_harness_root_relative_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    db_path = _resolve_legacy_sqlite_path(
        {"database": {"sqlite_path": "data/sqlite/custom.db"}},
        env={},
    )

    assert db_path == harness_root / "data" / "sqlite" / "custom.db"
