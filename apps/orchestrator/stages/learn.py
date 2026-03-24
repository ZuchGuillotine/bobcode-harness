"""Learn stage — stores eval results, classifies failures, updates tracking."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from packages.state.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

_DB_PATH = os.environ.get("HARNESS_DB_PATH", os.path.join(".harness", "harness.db"))

# Failure classification taxonomy
FAILURE_CLASSES = {
    "plan_quality": "Planner produced a low-confidence or invalid plan",
    "execution_error": "Worker encountered an error during execution",
    "test_failure": "Tests did not pass after execution",
    "boundary_violation": "Changes touched out-of-scope files",
    "review_rejected": "Reviewer rejected the changes",
    "budget_exceeded": "Task exceeded its budget ceiling",
    "unknown": "Failure cause could not be determined",
}


def learn_node(state: dict[str, Any]) -> dict[str, Any]:
    """Post-mortem learning: classify failures, store results, update skill tracking.

    This node runs after validation when the task is not immediately 'done'.
    """

    task_id = state.get("task_id", "unknown")
    eval_results = state.get("eval_results") or {}
    plan = state.get("plan") or {}
    status = state.get("status", "")

    # --- Classify failure ---
    failure_class = _classify_failure(state, eval_results)

    # --- Build learning record ---
    record = {
        "task_id": task_id,
        "task_type": state.get("task_type", "unknown"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "final_status": status,
        "failure_class": failure_class,
        "failure_description": FAILURE_CLASSES.get(failure_class, ""),
        "retries": state.get("retries", 0),
        "plan_confidence": plan.get("confidence", 0),
        "selected_skill": plan.get("selected_skill", ""),
        "estimated_tokens": plan.get("estimated_budget_tokens", 0),
        "eval_summary": _summarise_evals(eval_results),
        "error": state.get("error"),
    }

    # --- Store learning record ---
    _save_learning_record(task_id, record)

    # --- Update skill usage tracking ---
    _update_skill_tracking(record)

    logger.info(
        "Learn complete for %s: class=%s, skill=%s",
        task_id,
        failure_class,
        record["selected_skill"],
    )

    return {
        **state,
        "status": "learned",
    }


def _classify_failure(state: dict[str, Any], eval_results: dict[str, Any]) -> str:
    """Determine the root cause category for a non-successful task."""

    error = state.get("error", "")

    # Budget exceeded
    if error and "budget" in error.lower():
        return "budget_exceeded"

    # Check for boundary violations
    local_issues = eval_results.get("local_issues", [])
    if any(i.get("check") == "out_of_scope_change" for i in local_issues):
        return "boundary_violation"

    # Reviewer rejection
    review = eval_results.get("review_verdict")
    if review and review.get("verdict") == "rejected":
        return "review_rejected"

    # Test failures
    if not eval_results.get("tests_passed", True):
        return "test_failure"

    # Execution errors
    if error and "worker" in error.lower():
        return "execution_error"

    # Plan quality issues
    plan = state.get("plan") or {}
    if plan.get("confidence", 1.0) < 0.3:
        return "plan_quality"
    if error and "plan" in error.lower():
        return "plan_quality"

    return "unknown"


def _summarise_evals(eval_results: dict[str, Any]) -> dict[str, Any]:
    """Create a compact summary of eval results for the learning record."""

    summary: dict[str, Any] = {}

    # Deterministic checks
    det = eval_results.get("deterministic_verdict", {})
    if det:
        summary["deterministic_passed"] = det.get("passed", False)
        summary["checks_failed"] = [
            c["check"] for c in det.get("checks", []) if not c.get("passed", True)
        ]

    # Review
    review = eval_results.get("review_verdict")
    if review:
        summary["review_verdict"] = review.get("verdict", "unknown")
        summary["review_confidence"] = review.get("confidence", 0)
        summary["review_issue_count"] = len(review.get("issues", []))

    # Tests
    summary["tests_passed"] = eval_results.get("tests_passed", False)

    return summary


def _save_learning_record(task_id: str, record: dict[str, Any]) -> None:
    """Persist the learning record to filesystem and SQLiteStore."""

    # Save to task directory
    task_dir = os.path.join(".harness", "tasks", task_id, "evals")
    os.makedirs(task_dir, exist_ok=True)

    try:
        with open(os.path.join(task_dir, "learning.json"), "w") as f:
            json.dump(record, f, indent=2, default=str)
    except OSError:
        logger.warning("Failed to save learning record for %s", task_id)

    # Append to global learning log
    log_dir = os.path.join(".harness", "learning")
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, "failures.jsonl")
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError:
        logger.warning("Failed to append to global learning log")

    # Persist failure to SQLiteStore
    try:
        store = SQLiteStore(_DB_PATH)
        failure_class = record.get("failure_class", "unknown")
        if failure_class != "unknown" or record.get("final_status") not in ("done", "learned"):
            store.record_failure(
                task_id=task_id,
                category=failure_class,
                description=record.get("failure_description", ""),
                skill_id=record.get("selected_skill"),
                model_used=None,
            )
        store.close()
    except Exception:
        logger.debug("Failed to persist failure to SQLite for %s", task_id, exc_info=True)


def _update_skill_tracking(record: dict[str, Any]) -> None:
    """Update skill usage via SQLiteStore and legacy JSON file."""

    skill_id = record.get("selected_skill", "")
    if not skill_id:
        return

    task_id = record.get("task_id", "unknown")
    failure_class = record.get("failure_class", "unknown")
    is_success = record.get("final_status") in ("done", "learned") and failure_class == "unknown"

    # Persist to SQLiteStore
    try:
        store = SQLiteStore(_DB_PATH)
        store.record_skill_usage(
            task_id=task_id,
            skill_id=skill_id,
            invocation_count=1,
            total_tokens=record.get("estimated_tokens", 0),
            total_cost=0.0,
            duration_secs=0.0,
            success=is_success,
        )
        store.close()
    except Exception:
        logger.debug("Failed to persist skill usage to SQLite for %s", task_id, exc_info=True)

    # Legacy JSON-based tracking
    tracking_dir = os.path.join(".harness", "skills")
    os.makedirs(tracking_dir, exist_ok=True)
    tracking_path = os.path.join(tracking_dir, "usage.json")

    tracking: dict[str, Any] = {}
    if os.path.exists(tracking_path):
        try:
            with open(tracking_path) as f:
                tracking = json.load(f)
        except (json.JSONDecodeError, OSError):
            tracking = {}

    if skill_id not in tracking:
        tracking[skill_id] = {
            "total_uses": 0,
            "successes": 0,
            "failures": 0,
            "failure_classes": {},
            "last_used": None,
        }

    entry = tracking[skill_id]
    entry["total_uses"] += 1
    entry["last_used"] = record.get("timestamp")

    if is_success:
        entry["successes"] += 1
    else:
        entry["failures"] += 1
        fc_counts = entry.get("failure_classes", {})
        fc_counts[failure_class] = fc_counts.get(failure_class, 0) + 1
        entry["failure_classes"] = fc_counts

    try:
        with open(tracking_path, "w") as f:
            json.dump(tracking, f, indent=2)
    except OSError:
        logger.warning("Failed to update skill tracking for %s", skill_id)
