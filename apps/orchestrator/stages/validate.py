"""Validate stage — deterministic checks + optional Reviewer agent."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from apps.orchestrator.agents.reviewer import ReviewerAgent
from apps.orchestrator.budget import budget_enforcer
from packages.config import get_project_paths
from packages.eval.deterministic import DeterministicEvaluator
from packages.learning.community_feedback import append_feedback_event, build_feedback_event
from packages.llm.router import LLMRouter
from packages.state.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# Confidence threshold below which we invoke the Reviewer
_REVIEW_THRESHOLD = 0.85


def validate_node(state: dict[str, Any]) -> dict[str, Any]:
    """Run validation checks and optionally invoke the Reviewer agent.

    Steps:
    1. Run deterministic checks (tests passed, no critical local issues)
    2. If confidence is low or issues exist, invoke the Reviewer
    3. Aggregate results and determine final status
    """

    task_id = state.get("task_id", "unknown")
    plan = state.get("plan") or {}
    artifacts = state.get("artifacts", [])
    eval_results = state.get("eval_results") or {}
    project_paths = get_project_paths(
        project_name=state.get("project_name"),
        repo_path=state.get("repo_path"),
    )

    # --- Deterministic checks ---
    deterministic_verdict = _run_deterministic_checks(eval_results, plan)

    # --- Decide whether to invoke Reviewer ---
    plan_confidence = plan.get("confidence", 0)
    has_critical_issues = any(
        i.get("severity") == "critical"
        for i in eval_results.get("local_issues", [])
    )
    needs_review = (
        plan_confidence < _REVIEW_THRESHOLD
        or has_critical_issues
        or not eval_results.get("tests_passed", False)
    )

    review_verdict: dict[str, Any] | None = None

    if needs_review and budget_enforcer.check_budget(state):
        logger.info("Invoking Reviewer for task %s", task_id)
        review_verdict = _invoke_reviewer(artifacts, plan, state)
    elif needs_review:
        logger.warning("Skipping review for %s — budget exceeded", task_id)

    # --- Aggregate results ---
    final_status = _determine_status(deterministic_verdict, review_verdict)

    # --- Build eval results ---
    full_eval = {
        **eval_results,
        "deterministic_verdict": deterministic_verdict,
        "review_verdict": review_verdict,
        "final_status": final_status,
    }

    # --- Save validation results ---
    _save_validation(task_id, full_eval, str(project_paths.tasks_dir), str(project_paths.db_path))
    _save_community_feedback(state, full_eval, final_status)

    # Handle retries
    retries = state.get("retries", 0)
    if final_status == "retry":
        retries += 1

    logger.info("Validation complete for %s: status=%s", task_id, final_status)

    return {
        **state,
        "status": final_status,
        "eval_results": full_eval,
        "retries": retries,
    }


def _run_deterministic_checks(
    eval_results: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    """Run deterministic (non-LLM) validation checks using DeterministicEvaluator."""

    evaluator = DeterministicEvaluator()
    checks: list[dict[str, Any]] = []
    passed = True

    # Build a task_state-like dict for the evaluator
    eval_input: dict[str, Any] = {}

    # Feed test output if available
    test_output = eval_results.get("worker_summary", "")
    if eval_results.get("tests_passed") is not None:
        eval_input["test_output"] = "passed" if eval_results["tests_passed"] else "FAILED"

    # Feed boundary violations from local issues
    local_issues = eval_results.get("local_issues", [])
    boundary_violations = [i for i in local_issues if i.get("check") == "out_of_scope_change"]
    if boundary_violations:
        eval_input["boundary_violations"] = boundary_violations

    # Run DeterministicEvaluator checks
    det_results = evaluator.run_all(eval_input)
    for er in det_results:
        checks.append({
            "check": er.check_name,
            "passed": er.passed,
            "detail": er.details,
        })
        if not er.passed:
            passed = False

    # Additional: check tests_passed from worker report
    tests_passed = eval_results.get("tests_passed", False)
    checks.append({
        "check": "tests_passed",
        "passed": tests_passed,
        "detail": "Worker-reported test results",
    })
    if not tests_passed:
        passed = False

    # Additional: no critical local issues
    critical_issues = [i for i in local_issues if i.get("severity") == "critical"]
    checks.append({
        "check": "no_critical_issues",
        "passed": len(critical_issues) == 0,
        "detail": f"{len(critical_issues)} critical issues found",
    })
    if critical_issues:
        passed = False

    # Plan confidence
    plan_confidence = plan.get("confidence", 0)
    checks.append({
        "check": "plan_confidence",
        "passed": plan_confidence >= 0.3,
        "detail": f"Plan confidence: {plan_confidence}",
    })

    return {
        "passed": passed,
        "checks": checks,
        "critical_issues": critical_issues,
    }


def _invoke_reviewer(
    artifacts: list[dict[str, Any]],
    plan: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Invoke the Reviewer agent backed by real dependencies."""

    worktree_path = state.get("worktree_path") or state.get("repo_path") or "."
    llm_router = LLMRouter()
    reviewer = ReviewerAgent(
        worktree_path=worktree_path,
        project_paths=get_project_paths(
            project_name=state.get("project_name"),
            repo_path=state.get("repo_path"),
        ),
        llm_router=llm_router,
    )

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, reviewer.review(artifacts, plan, state)
                ).result()
        else:
            return asyncio.run(reviewer.review(artifacts, plan, state))
    except Exception as exc:
        logger.exception("Reviewer failed for task %s", state.get("task_id"))
        return {
            "verdict": "needs_changes",
            "issues": [{"severity": "warning", "description": f"Reviewer error: {exc}"}],
            "confidence": 0.0,
            "summary": "Reviewer failed with an exception.",
        }


def _determine_status(
    deterministic: dict[str, Any],
    review: dict[str, Any] | None,
) -> str:
    """Determine the final task status from validation results.

    Returns: done, retry, or failed.
    """

    # If deterministic checks failed hard, retry
    if not deterministic.get("passed", False):
        return "retry"

    # If reviewer ran and rejected, retry
    if review:
        verdict = review.get("verdict", "needs_changes")
        if verdict == "approved":
            return "done"
        if verdict == "rejected":
            return "retry"
        # needs_changes → retry
        return "retry"

    # No review needed and deterministic passed → done
    return "done"


def _save_validation(
    task_id: str,
    eval_results: dict[str, Any],
    tasks_dir: str,
    db_path: str,
) -> None:
    """Persist validation results to the task directory and SQLiteStore."""
    import os

    # File-based persistence
    evals_dir = os.path.join(tasks_dir, task_id, "evals")
    os.makedirs(evals_dir, exist_ok=True)

    try:
        with open(os.path.join(evals_dir, "validation.json"), "w") as f:
            json.dump(eval_results, f, indent=2, default=str)
    except OSError:
        logger.warning("Failed to save validation for %s", task_id)

    # SQLiteStore persistence
    try:
        store = SQLiteStore(db_path)
        det = eval_results.get("deterministic_verdict", {})
        store.record_eval(
            task_id=task_id,
            eval_type="deterministic",
            passed=det.get("passed", False),
            score=1.0 if det.get("passed") else 0.0,
            details=det,
        )
        review = eval_results.get("review_verdict")
        if review:
            store.record_eval(
                task_id=task_id,
                eval_type="reviewer",
                passed=review.get("verdict") == "approved",
                score=review.get("confidence", 0.0),
                details=review,
            )
        store.close()
    except Exception:
        logger.debug("Failed to persist eval results to SQLite for %s", task_id, exc_info=True)


def _save_community_feedback(
    state: dict[str, Any],
    eval_results: dict[str, Any],
    final_status: str,
) -> None:
    """Persist a repo-agnostic validation record for harness-level learning."""
    try:
        event = build_feedback_event(state, eval_results, final_status)
        append_feedback_event(event)
    except Exception:
        logger.debug(
            "Failed to persist community feedback for %s",
            state.get("task_id"),
            exc_info=True,
        )
