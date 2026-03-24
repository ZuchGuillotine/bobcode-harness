"""Integration tests for the full orchestrator pipeline.

These tests mock LLM calls but exercise real graph wiring, node execution,
and state transitions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

class TestBuildGraph:
    """Verify the LangGraph StateGraph compiles correctly."""

    def test_build_graph(self) -> None:
        """build_graph() produces a compilable StateGraph with all expected nodes."""
        from apps.orchestrator.main import build_graph

        graph = build_graph()
        compiled = graph.compile()

        # The compiled graph should be invocable (i.e. it compiled without errors)
        assert compiled is not None

        # Verify key nodes are present in the graph
        node_names = set(graph.nodes.keys())
        assert "intake" in node_names
        assert "plan" in node_names
        assert "execute" in node_names
        assert "validate" in node_names
        assert "learn" in node_names
        assert "route_result" in node_names


# ---------------------------------------------------------------------------
# Intake node
# ---------------------------------------------------------------------------

class TestIntakeNode:
    """Test the intake stage in isolation."""

    @patch("apps.orchestrator.stages.intake.TaskRouter")
    @patch("apps.orchestrator.stages.intake.SQLiteStore")
    def test_intake_node(self, MockStore: MagicMock, MockRouter: MagicMock, tmp_path: Path) -> None:
        """Intake assigns a task ID, creates a directory, and transitions to 'planning'."""
        from apps.orchestrator.stages.intake import intake_node

        MockRouter.return_value.classify_task.return_value = "code_change"
        mock_store_instance = MagicMock()
        MockStore.return_value = mock_store_instance
        repo_path = tmp_path / "demo-repo"
        repo_path.mkdir()

        with patch.dict(os.environ, {"HARNESS_DATA": str(tmp_path / "data")}, clear=False):
            state: dict[str, Any] = {
                "task_id": "",
                "task_type": "code_change",
                "domain": "",
                "repo_path": str(repo_path),
                "description": "Fix the login endpoint returning 500",
                "status": "intake",
                "plan": None,
                "artifacts": [],
                "eval_results": None,
                "budget": {
                    "max_tokens": 500_000,
                    "max_cost_usd": 5.00,
                },
                "trace_id": "",
                "retries": 0,
                "max_retries": 3,
                "error": None,
            }

            result = intake_node(state)

        # Task ID should be assigned
        assert result["task_id"] != ""
        assert result["task_id"].startswith("TASK-")

        # Status should transition to planning
        assert result["status"] == "planning"

        # Description should be preserved
        assert result["description"] == "Fix the login endpoint returning 500"

        # Domain should be inferred
        assert result["domain"] == "engineering"

        # Trace ID should be assigned
        assert result["trace_id"] != ""

        # Budget defaults should be populated
        assert result["budget"]["max_tokens"] == 500_000

        # Task directory should live under the external project data dir
        task_dir = tmp_path / "data" / "projects" / repo_path.name / "tasks" / result["task_id"]
        assert task_dir.is_dir()
        assert (task_dir / "manifest.json").is_file()

    def test_intake_node_empty_description(self) -> None:
        """Intake with empty description returns failed status."""
        from apps.orchestrator.stages.intake import intake_node

        state: dict[str, Any] = {
            "description": "",
            "status": "intake",
        }

        result = intake_node(state)
        assert result["status"] == "failed"
        assert "required" in result["error"].lower()


# ---------------------------------------------------------------------------
# Plan node — low confidence escalation
# ---------------------------------------------------------------------------

class TestPlanNodeLowConfidence:
    """Test that the plan node handles low-confidence plans correctly."""

    @patch("apps.orchestrator.stages.plan.PlannerAgent")
    @patch("apps.orchestrator.stages.plan.budget_enforcer")
    def test_plan_node_low_confidence(
        self, mock_budget: MagicMock, MockPlannerAgent: MagicMock
    ) -> None:
        """A plan with confidence < 0.7 still proceeds but includes a warning.

        When confidence is 0 and there are validation errors, the plan fails.
        """
        from apps.orchestrator.stages.plan import plan_node

        # Budget check passes
        mock_budget.check_budget.return_value = True
        mock_budget.get_remaining.return_value = {
            "tokens_remaining": 500_000,
            "cost_remaining_usd": 5.00,
        }

        # Planner returns a zero-confidence plan with no steps (triggers failure)
        mock_planner_instance = MagicMock()
        mock_planner_instance.plan = AsyncMock(return_value={
            "task_id": "TASK-LOW",
            "task_type": "code_change",
            "plan_steps": [],
            "selected_skill": "skill-code-change-v1",
            "estimated_budget_tokens": 10000,
            "confidence": 0.0,
        })
        MockPlannerAgent.return_value = mock_planner_instance

        state: dict[str, Any] = {
            "task_id": "TASK-LOW",
            "task_type": "code_change",
            "description": "Do something uncertain",
            "status": "planning",
            "budget": {"max_tokens": 500_000, "max_cost_usd": 5.00},
            "retries": 0,
            "max_retries": 3,
        }

        result = plan_node(state)

        # Zero confidence + empty plan_steps => should fail
        assert result["status"] == "failed"
        assert result["error"] is not None
        assert "validation failed" in result["error"].lower() or "Plan" in result["error"]

    @patch("apps.orchestrator.stages.plan.PlannerAgent")
    @patch("apps.orchestrator.stages.plan.budget_enforcer")
    def test_plan_node_moderate_confidence_continues(
        self, mock_budget: MagicMock, MockPlannerAgent: MagicMock
    ) -> None:
        """A plan with moderate confidence (e.g. 0.5) proceeds to execution."""
        from apps.orchestrator.stages.plan import plan_node

        mock_budget.check_budget.return_value = True
        mock_budget.get_remaining.return_value = {
            "tokens_remaining": 500_000,
            "cost_remaining_usd": 5.00,
        }

        mock_planner_instance = MagicMock()
        mock_planner_instance.plan = AsyncMock(return_value={
            "task_id": "TASK-MED",
            "task_type": "code_change",
            "plan_steps": [
                {"step": 1, "action": "Analyze", "target": "src/main.py", "rationale": "Understand"},
            ],
            "selected_skill": "skill-code-change-v1",
            "estimated_budget_tokens": 30000,
            "confidence": 0.5,
        })
        MockPlannerAgent.return_value = mock_planner_instance

        state: dict[str, Any] = {
            "task_id": "TASK-MED",
            "task_type": "code_change",
            "description": "Moderate confidence task",
            "status": "planning",
            "budget": {"max_tokens": 500_000, "max_cost_usd": 5.00},
            "retries": 0,
            "max_retries": 3,
        }

        result = plan_node(state)

        # Should proceed to executing (confidence > 0, has steps)
        assert result["status"] == "executing"
        assert result["plan"] is not None
        assert result["plan"]["confidence"] == 0.5

    @patch("apps.orchestrator.stages.plan.PlannerAgent")
    @patch("apps.orchestrator.stages.plan.budget_enforcer")
    def test_plan_node_budget_exceeded(
        self, mock_budget: MagicMock, MockPlannerAgent: MagicMock
    ) -> None:
        """Plan node returns failed when budget is already exceeded."""
        from apps.orchestrator.stages.plan import plan_node

        mock_budget.check_budget.return_value = False

        state: dict[str, Any] = {
            "task_id": "TASK-BROKE",
            "task_type": "code_change",
            "description": "Over budget task",
            "status": "planning",
            "budget": {"max_tokens": 100, "max_cost_usd": 0.001},
        }

        result = plan_node(state)
        assert result["status"] == "failed"
        assert "budget" in result["error"].lower()

    @patch("apps.orchestrator.stages.plan.PlannerAgent")
    @patch("apps.orchestrator.stages.plan.budget_enforcer")
    def test_plan_node_passes_repo_path_to_planner(
        self, mock_budget: MagicMock, MockPlannerAgent: MagicMock, tmp_path: Path
    ) -> None:
        """Plan node should construct the planner with the task's repo path."""
        from apps.orchestrator.stages.plan import plan_node

        repo_path = tmp_path / "demo-repo"
        repo_path.mkdir()
        mock_budget.check_budget.return_value = True
        mock_budget.get_remaining.return_value = {
            "tokens_remaining": 500_000,
            "cost_remaining_usd": 5.00,
        }

        mock_planner_instance = MagicMock()
        mock_planner_instance.plan = AsyncMock(return_value={
            "task_id": "TASK-REPO",
            "task_type": "code_change",
            "plan_steps": [{"step": 1, "action": "Inspect", "target": "foo.py", "rationale": "Understand"}],
            "selected_skill": "skill-code-change-v1",
            "estimated_budget_tokens": 1000,
            "confidence": 0.9,
        })
        MockPlannerAgent.return_value = mock_planner_instance

        with patch.dict(os.environ, {"HARNESS_DATA": str(tmp_path / "data")}, clear=False):
            state: dict[str, Any] = {
                "task_id": "TASK-REPO",
                "task_type": "code_change",
                "repo_path": str(repo_path),
                "description": "Inspect the repo",
                "status": "planning",
                "budget": {"max_tokens": 500_000, "max_cost_usd": 5.00},
                "retries": 0,
                "max_retries": 3,
            }
            result = plan_node(state)

        assert result["status"] == "executing"
        MockPlannerAgent.assert_called_once()
        assert MockPlannerAgent.call_args.kwargs["repo_path"] == str(repo_path)
