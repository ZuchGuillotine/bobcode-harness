"""Learn stage — stores eval results, classifies failures, updates tracking."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from packages.config import get_project_paths
from packages.learning.failure_classification import FAILURE_CLASSES, classify_failure
from packages.state.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


def learn_node(state: dict[str, Any]) -> dict[str, Any]:
    """Post-mortem learning: classify failures, store results, update skill tracking.

    This node runs after validation when the task is not immediately 'done'.
    """

    task_id = state.get("task_id", "unknown")
    eval_results = state.get("eval_results") or {}
    plan = state.get("plan") or {}
    status = state.get("status", "")
    project_paths = get_project_paths(
        project_name=state.get("project_name"),
        repo_path=state.get("repo_path"),
    )

    # --- Classify failure ---
    failure_class = classify_failure(state, eval_results)

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
    _save_learning_record(task_id, record, project_paths)

    # --- Update skill usage tracking ---
    _update_skill_tracking(record, project_paths)

    # --- Analyze routing patterns and suggest adjustments ---
    _analyze_routing_patterns(record, project_paths)

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


def _save_learning_record(task_id: str, record: dict[str, Any], project_paths: Any) -> None:
    """Persist the learning record to filesystem and SQLiteStore."""
    import os

    # Save to task directory
    task_dir = os.path.join(str(project_paths.tasks_dir), task_id, "evals")
    os.makedirs(task_dir, exist_ok=True)

    try:
        with open(os.path.join(task_dir, "learning.json"), "w") as f:
            json.dump(record, f, indent=2, default=str)
    except OSError:
        logger.warning("Failed to save learning record for %s", task_id)

    # Append to global learning log
    log_dir = str(project_paths.learning_dir)
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, "failures.jsonl")
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError:
        logger.warning("Failed to append to global learning log")

    # Persist failure to SQLiteStore
    try:
        store = SQLiteStore(str(project_paths.db_path))
        failure_class = record.get("failure_class", "unknown")
        if failure_class != "unknown" or record.get("final_status") not in ("done", "learned"):
            # Determine which model was responsible
            model_used = _infer_model_for_failure(failure_class, project_paths)
            store.record_failure(
                task_id=task_id,
                category=failure_class,
                description=record.get("failure_description", ""),
                skill_id=record.get("selected_skill"),
                model_used=model_used,
            )
        store.close()
    except Exception:
        logger.debug("Failed to persist failure to SQLite for %s", task_id, exc_info=True)


def _update_skill_tracking(record: dict[str, Any], project_paths: Any) -> None:
    """Update skill usage via SQLiteStore and legacy JSON file."""
    import os

    skill_id = record.get("selected_skill", "")
    if not skill_id:
        return

    task_id = record.get("task_id", "unknown")
    failure_class = record.get("failure_class", "unknown")
    is_success = record.get("final_status") in ("done", "learned") and failure_class == "unknown"

    # Persist to SQLiteStore
    try:
        store = SQLiteStore(str(project_paths.db_path))
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
    tracking_dir = str(project_paths.skills_dir)
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


# ---------------------------------------------------------------------------
# Routing pattern analysis
# ---------------------------------------------------------------------------

# Thresholds for generating routing suggestions
_MIN_SAMPLE_SIZE = 5          # Need at least N failures before suggesting
_HIGH_FAILURE_RATE = 0.40     # 40%+ failure rate triggers a suggestion
_CRITICAL_FAILURE_RATE = 0.60 # 60%+ triggers urgent suggestion

_ROLE_MODEL_MAP = {
    "execution_error": "worker",
    "test_failure": "worker",
    "review_rejected": "initial_reviewer",
    "final_review_rejected": "final_reviewer",
    "worker_fix_failed": "worker_fix",
    "plan_quality": "planner",
}


def _infer_model_for_failure(failure_class: str, project_paths: Any) -> str | None:
    """Infer which model was responsible for a given failure class."""
    role = _ROLE_MODEL_MAP.get(failure_class)
    if role:
        return _get_current_model_for_role(role, project_paths)
    return None


def _analyze_routing_patterns(record: dict[str, Any], project_paths: Any) -> None:
    """Analyze failure patterns and suggest routing adjustments.

    Checks the last N failures to detect consistent model-specific issues
    and records suggestions to the routing_suggestions table.
    """
    try:
        store = SQLiteStore(str(project_paths.db_path))
        stats = store.get_failure_stats()
        total_failures = stats.get("total", 0)

        if total_failures < _MIN_SAMPLE_SIZE:
            store.close()
            return

        by_category = stats.get("by_category", {})

        # Check each failure category for high rates
        for category, count in by_category.items():
            if count < _MIN_SAMPLE_SIZE:
                continue

            role = _ROLE_MODEL_MAP.get(category)
            if not role:
                continue

            # Calculate failure rate for this category
            # Query total tasks to get the rate
            total_tasks = store._conn.execute(
                "SELECT COUNT(*) FROM tasks"
            ).fetchone()[0] or 1

            failure_rate = count / total_tasks

            if failure_rate >= _HIGH_FAILURE_RATE:
                severity = "urgent" if failure_rate >= _CRITICAL_FAILURE_RATE else "advisory"
                current_model = _get_current_model_for_role(role, project_paths)

                suggestion_text = (
                    f"[{severity.upper()}] Role '{role}' has {failure_rate:.0%} failure rate "
                    f"({count}/{total_tasks} tasks) in category '{category}'. "
                    f"Current model: {current_model}. "
                    f"Consider switching to a more capable model or adjusting prompts."
                )

                # Check if we already have a recent suggestion for this role
                existing = store._conn.execute(
                    "SELECT id FROM routing_suggestions "
                    "WHERE role = ? AND acknowledged = 0 AND pattern = ?",
                    (role, category),
                ).fetchone()

                if not existing:
                    store.record_routing_suggestion(
                        role=role,
                        current_model=current_model,
                        suggestion=suggestion_text,
                        failure_rate=failure_rate,
                        sample_size=count,
                        pattern=category,
                        confidence=min(failure_rate * 1.5, 1.0),
                    )
                    logger.warning("ROUTING SUGGESTION: %s", suggestion_text)

        store.close()
    except Exception:
        logger.debug("Failed to analyze routing patterns", exc_info=True)


def _get_current_model_for_role(role: str, project_paths: Any) -> str:
    """Read the current model for a role from the routing config."""
    try:
        import yaml
        from pathlib import Path
        config_path = Path(project_paths.repo_path) / "config" / "model_routing.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        return config.get("routing", {}).get(role, {}).get("model", "unknown")
    except Exception:
        return "unknown"
