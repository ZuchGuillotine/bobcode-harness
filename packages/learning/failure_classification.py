"""Shared failure taxonomy helpers for project and community learning."""

from __future__ import annotations

from typing import Any

FAILURE_CLASSES = {
    "plan_quality": "Planner produced a low-confidence or invalid plan",
    "execution_error": "Worker encountered an error during execution",
    "test_failure": "Tests did not pass after execution",
    "boundary_violation": "Changes touched out-of-scope files",
    "review_rejected": "Initial reviewer (GPT-5.4) rejected the changes",
    "final_review_rejected": "Final reviewer (Opus) rejected after fix cycle",
    "worker_fix_failed": "Worker fix pass failed to resolve review issues",
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

    # Check final review first (most downstream)
    final_review = eval_results.get("final_review")
    if final_review and final_review.get("verdict") == "rejected":
        return "final_review_rejected"

    # Check if worker fix was attempted but failed
    if eval_results.get("worker_fix_error"):
        return "worker_fix_failed"

    # Check initial review rejection
    initial_review = eval_results.get("initial_review")
    if initial_review and initial_review.get("verdict") == "rejected":
        return "review_rejected"

    # Legacy: check review_verdict for backward compat
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
