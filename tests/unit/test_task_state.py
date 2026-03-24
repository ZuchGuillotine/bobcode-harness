"""Unit tests for packages.state.task_state.TaskStateManager."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from packages.state.task_state import TaskStateManager


class TestCreateTaskDir:
    """Tests for TaskStateManager.create_task_dir."""

    def test_create_task_dir(self, task_state_manager: TaskStateManager) -> None:
        """Creating a task directory produces the expected subdirectory tree."""
        task_dir = task_state_manager.create_task_dir("TASK-001")

        assert task_dir.is_dir()
        assert (task_dir / "artifacts").is_dir()
        assert (task_dir / "logs").is_dir()
        assert (task_dir / "patches").is_dir()
        assert (task_dir / "evals").is_dir()

    def test_create_task_dir_idempotent(self, task_state_manager: TaskStateManager) -> None:
        """Creating the same task directory twice does not raise an error."""
        dir1 = task_state_manager.create_task_dir("TASK-002")
        dir2 = task_state_manager.create_task_dir("TASK-002")
        assert dir1 == dir2
        assert dir1.is_dir()

    def test_default_root_uses_harness_runtime_tasks_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Default construction should not write a repo-local .harness directory."""
        harness_root = tmp_path / "harness"
        (harness_root / "config").mkdir(parents=True)
        (harness_root / "config" / "harness.yaml").write_text(
            "harness:\n  data_dir: data\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("HARNESS_HOME", str(harness_root))

        manager = TaskStateManager()

        assert manager._base == harness_root / ".harness" / "tasks"


class TestWriteAndReadState:
    """Tests for state.json persistence."""

    def test_write_and_read_state(self, task_state_manager: TaskStateManager) -> None:
        """State written to state.json can be read back."""
        task_state_manager.create_task_dir("TASK-010")

        state: dict[str, Any] = {
            "task_id": "TASK-010",
            "status": "executing",
            "plan": {"steps": ["step1", "step2"]},
        }

        task_state_manager.write_state("TASK-010", state)
        loaded = task_state_manager.read_state("TASK-010")

        assert loaded["task_id"] == "TASK-010"
        assert loaded["status"] == "executing"
        assert loaded["plan"]["steps"] == ["step1", "step2"]

    def test_read_state_missing_returns_empty(
        self, task_state_manager: TaskStateManager
    ) -> None:
        """Reading state for a task with no state.json returns {}."""
        task_state_manager.create_task_dir("TASK-011")
        assert task_state_manager.read_state("TASK-011") == {}


class TestWriteAndReadPlan:
    """Tests for plan.json persistence."""

    def test_write_and_read_plan(self, task_state_manager: TaskStateManager) -> None:
        """Plan written to plan.json can be read back."""
        task_state_manager.create_task_dir("TASK-020")

        plan: dict[str, Any] = {
            "task_id": "TASK-020",
            "plan_steps": [
                {"step": 1, "action": "Analyze code"},
                {"step": 2, "action": "Implement fix"},
            ],
            "confidence": 0.9,
            "estimated_budget_tokens": 30000,
        }

        task_state_manager.write_plan("TASK-020", plan)
        loaded = task_state_manager.read_plan("TASK-020")

        assert loaded["task_id"] == "TASK-020"
        assert len(loaded["plan_steps"]) == 2
        assert loaded["confidence"] == 0.9

    def test_read_plan_missing_returns_empty(
        self, task_state_manager: TaskStateManager
    ) -> None:
        """Reading plan for a task with no plan.json returns {}."""
        task_state_manager.create_task_dir("TASK-021")
        assert task_state_manager.read_plan("TASK-021") == {}


class TestWriteAndReadBudget:
    """Tests for budget.json persistence."""

    def test_write_and_read_budget(self, task_state_manager: TaskStateManager) -> None:
        """Budget written to budget.json can be read back."""
        task_state_manager.create_task_dir("TASK-030")

        budget: dict[str, Any] = {
            "max_tokens": 500_000,
            "max_cost_usd": 5.00,
            "tokens_used": 12345,
            "cost_used": 0.37,
        }

        task_state_manager.write_budget("TASK-030", budget)
        loaded = task_state_manager.read_budget("TASK-030")

        assert loaded["max_tokens"] == 500_000
        assert loaded["max_cost_usd"] == 5.00
        assert loaded["tokens_used"] == 12345
        assert loaded["cost_used"] == 0.37

    def test_read_budget_missing_returns_empty(
        self, task_state_manager: TaskStateManager
    ) -> None:
        """Reading budget for a task with no budget.json returns {}."""
        task_state_manager.create_task_dir("TASK-031")
        assert task_state_manager.read_budget("TASK-031") == {}


class TestAddAndListArtifacts:
    """Tests for artifact storage and listing."""

    def test_add_and_list_artifacts(self, task_state_manager: TaskStateManager) -> None:
        """Artifacts added to a task can be listed."""
        task_state_manager.create_task_dir("TASK-040")

        task_state_manager.add_artifact("TASK-040", "patch.diff", b"--- a/file\n+++ b/file\n")
        task_state_manager.add_artifact("TASK-040", "report.json", b'{"status": "ok"}')

        artifacts = task_state_manager.list_artifacts("TASK-040")
        assert len(artifacts) == 2
        assert "patch.diff" in artifacts
        assert "report.json" in artifacts

    def test_add_artifact_content_persists(
        self, task_state_manager: TaskStateManager
    ) -> None:
        """The binary content of an artifact is stored correctly."""
        task_state_manager.create_task_dir("TASK-041")

        content = b"Hello, world! \x00\xff"
        path = task_state_manager.add_artifact("TASK-041", "binary.bin", content)

        assert path.read_bytes() == content

    def test_list_artifacts_empty(self, task_state_manager: TaskStateManager) -> None:
        """Listing artifacts for a task with none returns an empty list."""
        task_state_manager.create_task_dir("TASK-042")
        assert task_state_manager.list_artifacts("TASK-042") == []

    def test_list_artifacts_no_dir(self, task_state_manager: TaskStateManager) -> None:
        """Listing artifacts for a non-existent task returns an empty list."""
        assert task_state_manager.list_artifacts("TASK-NOPE") == []
