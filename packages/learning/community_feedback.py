"""Harness-level, share-safe feedback events for cross-project improvement."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.learning.failure_classification import classify_failure

logger = logging.getLogger(__name__)


def build_feedback_event(
    state: dict[str, Any],
    eval_results: dict[str, Any],
    final_status: str,
) -> dict[str, Any]:
    """Build a repo-agnostic feedback event safe for harness-level aggregation."""
    plan = state.get("plan") or {}
    local_issues = eval_results.get("local_issues", [])
    deterministic = eval_results.get("deterministic_verdict") or {}
    review = eval_results.get("review_verdict") or {}
    failure_class = classify_failure(state, eval_results)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_type": state.get("task_type", "unknown"),
        "final_status": final_status,
        "failure_class": None if final_status == "done" and failure_class == "unknown" else failure_class,
        "selected_skill": plan.get("selected_skill"),
        "plan_confidence": plan.get("confidence"),
        "estimated_budget_tokens": plan.get("estimated_budget_tokens"),
        "tests_passed": eval_results.get("tests_passed"),
        "deterministic_passed": deterministic.get("passed"),
        "review_verdict": review.get("verdict"),
        "review_confidence": review.get("confidence"),
        "retry_count": state.get("retries", 0),
        "max_retries": state.get("max_retries", 0),
        "local_issue_checks": sorted(
            {
                issue.get("check")
                for issue in local_issues
                if issue.get("check")
            }
        ),
        "critical_issue_count": sum(
            1 for issue in local_issues if issue.get("severity") == "critical"
        ),
    }


def append_feedback_event(event: dict[str, Any], output_dir: Path | None = None) -> Path:
    """Append a feedback event to the harness-level community log."""
    if output_dir is None:
        from packages.config import get_community_dir

        target_dir = get_community_dir()
    else:
        target_dir = output_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / "feedback_events.jsonl"
    with output_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")
    logger.debug("Appended community feedback event to %s", output_path)
    return output_path
