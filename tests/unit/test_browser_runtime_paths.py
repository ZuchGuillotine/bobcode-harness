"""Unit tests for browser runtime path creation."""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.config.runtime import get_project_paths


def test_project_paths_include_browser_runtime_dirs(
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

    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()

    paths = get_project_paths(repo_path=str(repo_path))
    paths.ensure_dirs()

    assert paths.browser_dir == harness_root / "data" / "projects" / "demo-repo" / "browser"
    assert paths.browser_state_file == paths.browser_dir / "daemon.json"
    assert paths.browser_artifacts_dir == paths.browser_dir / "artifacts"
    assert paths.browser_console_log == paths.browser_dir / "console.log"
    assert paths.browser_network_log == paths.browser_dir / "network.log"
    assert paths.browser_dir.is_dir()
    assert paths.browser_artifacts_dir.is_dir()
