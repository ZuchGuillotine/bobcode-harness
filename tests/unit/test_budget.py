"""Unit tests for apps.orchestrator.budget.BudgetEnforcer."""

from __future__ import annotations

from typing import Any

import pytest

from apps.orchestrator.budget import BudgetEnforcer


@pytest.fixture()
def enforcer() -> BudgetEnforcer:
    """Return a fresh BudgetEnforcer for each test."""
    return BudgetEnforcer()


def _make_task_state(
    task_id: str = "TASK-100",
    max_tokens: int = 500_000,
    max_cost_usd: float = 5.00,
) -> dict[str, Any]:
    """Build a minimal task_state dict with budget info."""
    return {
        "task_id": task_id,
        "budget": {
            "max_tokens": max_tokens,
            "max_cost_usd": max_cost_usd,
        },
    }


class TestCheckBudget:
    """Tests for BudgetEnforcer.check_budget."""

    def test_check_budget_within_limits(self, enforcer: BudgetEnforcer) -> None:
        """Returns True when no usage has been recorded (within limits)."""
        state = _make_task_state()
        assert enforcer.check_budget(state) is True

    def test_check_budget_within_limits_after_partial_usage(
        self, enforcer: BudgetEnforcer
    ) -> None:
        """Returns True when usage is below the ceiling."""
        state = _make_task_state(max_tokens=100_000, max_cost_usd=1.00)
        enforcer.record_usage("TASK-100", tokens=50_000, cost=0.50)
        assert enforcer.check_budget(state) is True

    def test_check_budget_exceeds_tokens(self, enforcer: BudgetEnforcer) -> None:
        """Returns False when token usage meets or exceeds the ceiling."""
        state = _make_task_state(max_tokens=100_000)
        enforcer.record_usage("TASK-100", tokens=100_000, cost=0.0)
        assert enforcer.check_budget(state) is False

    def test_check_budget_exceeds_cost(self, enforcer: BudgetEnforcer) -> None:
        """Returns False when cost usage meets or exceeds the ceiling."""
        state = _make_task_state(max_cost_usd=2.00)
        enforcer.record_usage("TASK-100", tokens=0, cost=2.00)
        assert enforcer.check_budget(state) is False


class TestRecordUsage:
    """Tests for BudgetEnforcer.record_usage."""

    def test_record_usage(self, enforcer: BudgetEnforcer) -> None:
        """Usage accumulates across multiple record_usage calls."""
        enforcer.record_usage("TASK-200", tokens=10_000, cost=0.05)
        enforcer.record_usage("TASK-200", tokens=20_000, cost=0.10)

        remaining = enforcer.get_remaining("TASK-200")
        assert remaining["tokens_used"] == 30_000
        assert remaining["cost_used_usd"] == pytest.approx(0.15)

    def test_record_usage_separate_tasks(self, enforcer: BudgetEnforcer) -> None:
        """Usage is tracked independently per task_id."""
        enforcer.record_usage("TASK-A", tokens=10_000, cost=0.05)
        enforcer.record_usage("TASK-B", tokens=50_000, cost=0.25)

        remaining_a = enforcer.get_remaining("TASK-A")
        remaining_b = enforcer.get_remaining("TASK-B")
        assert remaining_a["tokens_used"] == 10_000
        assert remaining_b["tokens_used"] == 50_000


class TestGetRemaining:
    """Tests for BudgetEnforcer.get_remaining."""

    def test_get_remaining(self, enforcer: BudgetEnforcer) -> None:
        """Remaining budget is correctly computed."""
        budget = {"max_tokens": 100_000, "max_cost_usd": 2.00}
        enforcer.record_usage("TASK-300", tokens=30_000, cost=0.60)

        remaining = enforcer.get_remaining("TASK-300", budget=budget)
        assert remaining["tokens_remaining"] == 70_000
        assert remaining["cost_remaining_usd"] == pytest.approx(1.40)
        assert remaining["tokens_used"] == 30_000
        assert remaining["cost_used_usd"] == pytest.approx(0.60)
        assert remaining["tokens_pct"] == pytest.approx(30.0)
        assert remaining["cost_pct"] == pytest.approx(30.0)

    def test_get_remaining_no_usage(self, enforcer: BudgetEnforcer) -> None:
        """Remaining equals the full budget when nothing has been used."""
        budget = {"max_tokens": 500_000, "max_cost_usd": 5.00}

        remaining = enforcer.get_remaining("TASK-UNUSED", budget=budget)
        assert remaining["tokens_remaining"] == 500_000
        assert remaining["cost_remaining_usd"] == pytest.approx(5.00)
        assert remaining["tokens_used"] == 0
        assert remaining["cost_used_usd"] == 0.0

    def test_get_remaining_defaults_when_no_budget_provided(
        self, enforcer: BudgetEnforcer
    ) -> None:
        """When no budget dict is passed, defaults are used (500k tokens, $5)."""
        remaining = enforcer.get_remaining("TASK-NOBUDGET")
        assert remaining["tokens_remaining"] == 500_000
        assert remaining["cost_remaining_usd"] == pytest.approx(5.00)

    def test_get_remaining_clamps_to_zero(self, enforcer: BudgetEnforcer) -> None:
        """Remaining never goes negative even if usage exceeds the limit."""
        budget = {"max_tokens": 10_000, "max_cost_usd": 0.50}
        enforcer.record_usage("TASK-OVER", tokens=20_000, cost=1.00)

        remaining = enforcer.get_remaining("TASK-OVER", budget=budget)
        assert remaining["tokens_remaining"] == 0
        assert remaining["cost_remaining_usd"] == 0.0
