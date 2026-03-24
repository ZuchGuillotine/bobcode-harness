"""BudgetEnforcer — tracks and enforces per-task token/cost ceilings."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    """Accumulated usage for a single task."""

    tokens_used: int = 0
    cost_used: float = 0.0


class BudgetEnforcer:
    """Per-task budget tracking.

    Budget limits are carried inside the task state dict under the ``budget``
    key. This class provides helpers to check, record, and query usage.
    """

    def __init__(self) -> None:
        self._usage: dict[str, UsageRecord] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_budget(self, task_state: dict[str, Any]) -> bool:
        """Return True if the task is still within budget, False otherwise."""

        budget = task_state.get("budget", {})
        task_id = task_state.get("task_id", "unknown")
        usage = self._usage.get(task_id, UsageRecord())

        max_tokens = budget.get("max_tokens", 500_000)
        max_cost = budget.get("max_cost_usd", 5.00)

        if usage.tokens_used >= max_tokens:
            logger.warning(
                "Task %s exceeded token budget: %d / %d",
                task_id,
                usage.tokens_used,
                max_tokens,
            )
            return False

        if usage.cost_used >= max_cost:
            logger.warning(
                "Task %s exceeded cost budget: $%.4f / $%.2f",
                task_id,
                usage.cost_used,
                max_cost,
            )
            return False

        return True

    def record_usage(self, task_id: str, tokens: int, cost: float) -> None:
        """Accumulate token/cost usage for a task."""

        if task_id not in self._usage:
            self._usage[task_id] = UsageRecord()

        record = self._usage[task_id]
        record.tokens_used += tokens
        record.cost_used += cost

        logger.debug(
            "Task %s usage: +%d tokens ($%.4f) → total %d tokens ($%.4f)",
            task_id,
            tokens,
            cost,
            record.tokens_used,
            record.cost_used,
        )

    def get_remaining(self, task_id: str, budget: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return remaining budget for a task."""

        usage = self._usage.get(task_id, UsageRecord())
        max_tokens = (budget or {}).get("max_tokens", 500_000)
        max_cost = (budget or {}).get("max_cost_usd", 5.00)

        return {
            "tokens_remaining": max(0, max_tokens - usage.tokens_used),
            "cost_remaining_usd": max(0.0, max_cost - usage.cost_used),
            "tokens_used": usage.tokens_used,
            "cost_used_usd": usage.cost_used,
            "tokens_pct": round(usage.tokens_used / max_tokens * 100, 1) if max_tokens else 0,
            "cost_pct": round(usage.cost_used / max_cost * 100, 1) if max_cost else 0,
        }

    def kill_if_exceeded(self, task_state: dict[str, Any]) -> dict[str, Any]:
        """Check budget and mutate task_state to 'failed' if exceeded.

        Returns the (possibly mutated) task_state.
        """

        if not self.check_budget(task_state):
            task_state["status"] = "failed"
            task_state["error"] = "Budget ceiling exceeded"
            logger.error("Killed task %s — budget exceeded", task_state.get("task_id"))

        return task_state


# Module-level singleton so all stages share one enforcer instance.
budget_enforcer = BudgetEnforcer()
