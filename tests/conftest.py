"""Shared pytest fixtures for the agent harness test suite."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# SQLite fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path: Path) -> str:
    """Return a path to a temporary SQLite database file."""
    return str(tmp_path / "test_harness.db")


@pytest.fixture()
def sqlite_store(tmp_db: str):
    """Return a SQLiteStore instance backed by a temporary database."""
    from packages.state.sqlite_store import SQLiteStore

    store = SQLiteStore(tmp_db)
    yield store
    store.close()


# ---------------------------------------------------------------------------
# TaskStateManager fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def task_state_manager(tmp_path: Path):
    """Return a TaskStateManager rooted in a temporary directory."""
    from packages.state.task_state import TaskStateManager

    return TaskStateManager(root=str(tmp_path))


# ---------------------------------------------------------------------------
# Sample task state
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_task_state() -> dict[str, Any]:
    """Return a complete TaskState dict suitable for testing."""
    return {
        "task_id": "TASK-042",
        "task_type": "code_change",
        "domain": "engineering",
        "description": "Refactor the auth module to use JWT tokens",
        "status": "planning",
        "plan": {
            "task_id": "TASK-042",
            "task_type": "code_change",
            "plan_steps": [
                {"step": 1, "action": "Read current auth module", "tool": "read_file"},
                {"step": 2, "action": "Implement JWT token generation", "tool": "write_file"},
                {"step": 3, "action": "Update tests", "tool": "write_file"},
            ],
            "selected_skill": "skill-code-change-v1",
            "estimated_budget_tokens": 50000,
            "confidence": 0.85,
        },
        "artifacts": [],
        "eval_results": None,
        "budget": {
            "max_tokens": 500_000,
            "max_cost_usd": 5.00,
            "tokens_used": 0,
            "cost_used": 0.0,
        },
        "trace_id": "abc123-def456-ghi789",
        "retries": 0,
        "max_retries": 3,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Mock LLM Router
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_llm_router():
    """Return a mocked LLMRouter that returns canned responses.

    The mock's ``call`` method returns a realistic response dict without
    making any real API calls.
    """
    from packages.llm.providers.base import LLMResponse

    mock_provider = MagicMock()
    mock_provider.complete.return_value = LLMResponse(
        content='{"result": "mocked LLM response"}',
        model="mock/model",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        cost=0.003,
    )

    with patch("packages.llm.router.get_provider", return_value=mock_provider):
        from packages.llm.router import LLMRouter

        config_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "model_routing.yaml"
        )
        router = LLMRouter(config_path=config_path)

        yield router
