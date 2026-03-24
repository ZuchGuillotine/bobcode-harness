"""Shared failure taxonomy helpers for project and community learning."""

from __future__ import annotations

from typing import Any

FAILURE_CLASSES = {
    "plan_quality": "Planner produced a low-confidence or invalid plan",
    "execution_error": "Worker encountered an error during execution",
    "test_failure": "Tests did not pass after execution",
    "boundary_violation": "Changes touched out-of-scope files",
    "review_rejected": "Reviewer rejected the changes",
    "budget_exceeded": "Task exceeded its budget ceiling",
    "unknown": "Failure cause could not be determined",
}


def classify_failure(state: dict[str, Any], eval_results: dict[str, Any]) -> str:
    """Determine the root-cause category for a task outcome."""
    error = state.get("error", "")

    if error and "budget" in error.lower():
        return "budget_exceeded"

    local_issues = eval_results.get("local_issues", [])
    if any(issue.get("check") == "out_of_scope_change" for issue in local_issues):
        return "boundary_violation"

    review = eval_results.get("review_verdict")
    if review and review.get("verdict") == "rejected":
        return "review_rejected"

    if not eval_results.get("tests_passed", True):
        return "test_failure"

    if error and "worker" in error.lower():
        return "execution_error"

    plan = state.get("plan") or {}
    if plan.get("confidence", 1.0) < 0.3:
        return "plan_quality"
    if error and "plan" in error.lower():
        return "plan_quality"

    return "unknown"
