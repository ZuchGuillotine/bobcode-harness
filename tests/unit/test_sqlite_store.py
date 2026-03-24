"""Unit tests for packages.state.sqlite_store.SQLiteStore."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from packages.state.sqlite_store import SQLiteStore


class TestCreateAndGetTask:
    """Tests for task creation and retrieval."""

    def test_create_and_get_task(self, sqlite_store: SQLiteStore) -> None:
        """A created task can be retrieved by its task_id."""
        task: dict[str, Any] = {
            "task_id": "TASK-001",
            "title": "Fix auth bug",
            "description": "The login endpoint returns 500 for valid credentials",
            "status": "pending",
            "priority": 2,
        }

        returned_id = sqlite_store.create_task(task)
        assert returned_id == "TASK-001"

        fetched = sqlite_store.get_task("TASK-001")
        assert fetched is not None
        assert fetched["task_id"] == "TASK-001"
        assert fetched["title"] == "Fix auth bug"
        assert fetched["description"] == "The login endpoint returns 500 for valid credentials"
        assert fetched["status"] == "pending"
        assert fetched["priority"] == 2
        assert fetched["created_at"] is not None
        assert fetched["updated_at"] is not None

    def test_get_nonexistent_task_returns_none(self, sqlite_store: SQLiteStore) -> None:
        """Requesting a non-existent task_id returns None."""
        assert sqlite_store.get_task("TASK-NOPE") is None


class TestUpdateTaskStatus:
    """Tests for status transitions."""

    def test_update_task_status(self, sqlite_store: SQLiteStore) -> None:
        """Updating status persists the change and sets updated_at."""
        sqlite_store.create_task({"task_id": "TASK-002", "title": "Status test"})

        sqlite_store.update_task_status("TASK-002", "executing")
        task = sqlite_store.get_task("TASK-002")
        assert task is not None
        assert task["status"] == "executing"
        assert task["completed_at"] is None  # not a terminal status

    def test_update_task_status_completed_sets_completed_at(
        self, sqlite_store: SQLiteStore
    ) -> None:
        """Terminal statuses (completed, failed, rejected) set completed_at."""
        sqlite_store.create_task({"task_id": "TASK-003", "title": "Complete test"})

        sqlite_store.update_task_status("TASK-003", "completed")
        task = sqlite_store.get_task("TASK-003")
        assert task is not None
        assert task["status"] == "completed"
        assert task["completed_at"] is not None


class TestListTasksByStatus:
    """Tests for listing tasks filtered by status."""

    def test_list_tasks_by_status(self, sqlite_store: SQLiteStore) -> None:
        """Tasks can be filtered by status."""
        sqlite_store.create_task({"task_id": "T-1", "status": "pending"})
        sqlite_store.create_task({"task_id": "T-2", "status": "pending"})
        sqlite_store.create_task({"task_id": "T-3", "status": "executing"})

        pending = sqlite_store.list_tasks(status="pending")
        assert len(pending) == 2
        assert all(t["status"] == "pending" for t in pending)

        executing = sqlite_store.list_tasks(status="executing")
        assert len(executing) == 1
        assert executing[0]["task_id"] == "T-3"

    def test_list_tasks_no_filter(self, sqlite_store: SQLiteStore) -> None:
        """Listing without a status filter returns all tasks."""
        sqlite_store.create_task({"task_id": "T-A", "status": "pending"})
        sqlite_store.create_task({"task_id": "T-B", "status": "completed"})

        all_tasks = sqlite_store.list_tasks()
        assert len(all_tasks) == 2


class TestRecordEval:
    """Tests for eval result recording."""

    def test_record_eval(self, sqlite_store: SQLiteStore) -> None:
        """An eval result is persisted and retrievable."""
        sqlite_store.create_task({"task_id": "TASK-010"})

        eval_id = sqlite_store.record_eval(
            task_id="TASK-010",
            eval_type="deterministic",
            passed=True,
            score=0.95,
            details={"checks": ["schema", "tests", "blast_radius"]},
        )
        assert isinstance(eval_id, int)
        assert eval_id > 0

        evals = sqlite_store.get_evals("TASK-010")
        assert len(evals) == 1
        assert evals[0]["eval_type"] == "deterministic"
        assert evals[0]["passed"] == 1  # SQLite stores as int
        assert evals[0]["score"] == 0.95


class TestRecordFailure:
    """Tests for failure recording and stats."""

    def test_record_failure(self, sqlite_store: SQLiteStore) -> None:
        """A failure is persisted with its metadata."""
        sqlite_store.create_task({"task_id": "TASK-020"})

        failure_id = sqlite_store.record_failure(
            task_id="TASK-020",
            category="budget_exceeded",
            description="Task exceeded token budget of 500000",
            skill_id="skill-code-change-v1",
            model_used="anthropic/claude-sonnet-4-6",
        )
        assert isinstance(failure_id, int)
        assert failure_id > 0

    def test_get_failure_stats(self, sqlite_store: SQLiteStore) -> None:
        """Failure stats aggregate correctly by category."""
        sqlite_store.create_task({"task_id": "TASK-021"})

        sqlite_store.record_failure("TASK-021", "budget_exceeded", "Over budget")
        sqlite_store.record_failure("TASK-021", "budget_exceeded", "Over budget again")
        sqlite_store.record_failure("TASK-021", "validation_error", "Schema invalid")

        stats = sqlite_store.get_failure_stats()
        assert stats["total"] == 3
        assert stats["by_category"]["budget_exceeded"] == 2
        assert stats["by_category"]["validation_error"] == 1

    def test_get_failure_stats_with_since(self, sqlite_store: SQLiteStore) -> None:
        """Failure stats can be filtered by a since timestamp."""
        sqlite_store.create_task({"task_id": "TASK-022"})
        sqlite_store.record_failure("TASK-022", "test_failure", "Tests failed")

        # Query with a far-future 'since' should return nothing
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        stats = sqlite_store.get_failure_stats(since=future)
        assert stats["total"] == 0


class TestRecordSkillUsage:
    """Tests for skill usage tracking."""

    def test_record_skill_usage(self, sqlite_store: SQLiteStore) -> None:
        """Skill usage is persisted and retrievable."""
        sqlite_store.create_task({"task_id": "TASK-030"})

        usage_id = sqlite_store.record_skill_usage(
            task_id="TASK-030",
            skill_id="skill-code-change-v1",
            invocation_count=3,
            total_tokens=45000,
            total_cost=0.135,
            duration_secs=12.5,
            success=True,
        )
        assert isinstance(usage_id, int)

        usages = sqlite_store.get_skill_usage("TASK-030")
        assert len(usages) == 1
        assert usages[0]["skill_id"] == "skill-code-change-v1"
        assert usages[0]["total_tokens"] == 45000
        assert usages[0]["total_cost"] == 0.135
        assert usages[0]["success"] == 1
