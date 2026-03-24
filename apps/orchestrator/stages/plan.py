"""Plan stage — invokes the Planner agent and validates output."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from apps.orchestrator.agents.planner import PlannerAgent
from apps.orchestrator.budget import budget_enforcer
from packages.llm.router import LLMRouter
from packages.state.task_state import TaskStateManager

logger = logging.getLogger(__name__)

# Required keys in a valid plan packet
_REQUIRED_PLAN_KEYS = {
    "task_id",
    "task_type",
    "plan_steps",
    "selected_skill",
    "estimated_budget_tokens",
    "confidence",
}


def _validate_plan(plan: dict[str, Any]) -> list[str]:
    """Validate the plan packet against the output contract.

    Returns a list of validation errors (empty = valid).
    """

    errors: list[str] = []

    missing = _REQUIRED_PLAN_KEYS - set(plan.keys())
    if missing:
        errors.append(f"Missing required keys: {missing}")

    steps = plan.get("plan_steps", [])
    if not isinstance(steps, list):
        errors.append("plan_steps must be a list")
    elif len(steps) == 0:
        errors.append("plan_steps is empty — Planner produced no actionable steps")

    confidence = plan.get("confidence", 0)
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        errors.append(f"confidence must be a float 0-1, got {confidence}")

    budget_est = plan.get("estimated_budget_tokens", 0)
    if not isinstance(budget_est, (int, float)) or budget_est < 0:
        errors.append(f"estimated_budget_tokens must be non-negative, got {budget_est}")

    return errors


def plan_node(state: dict[str, Any]) -> dict[str, Any]:
    """Invoke the Planner agent and validate its output.

    Runs the async planner in the current event loop or creates one.
    """

    task_id = state.get("task_id", "unknown")

    # --- Budget check before planning ---
    if not budget_enforcer.check_budget(state):
        logger.error("Task %s failed budget check before planning", task_id)
        return {
            **state,
            "status": "failed",
            "error": "Budget exceeded before planning",
        }

    # --- Invoke Planner ---
    repo_path = state.get("repo_path", os.environ.get("HARNESS_REPO_PATH", "."))
    llm_router = LLMRouter()
    planner = PlannerAgent(repo_path=repo_path, llm_router=llm_router)

    try:
        # LangGraph nodes are synchronous; bridge to async
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside an async context — use nest_asyncio or thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                plan = pool.submit(asyncio.run, planner.plan(state)).result()
        else:
            plan = asyncio.run(planner.plan(state))
    except Exception as exc:
        logger.exception("Planner failed for task %s", task_id)
        return {
            **state,
            "status": "failed",
            "error": f"Planner exception: {exc}",
        }

    # --- Validate plan ---
    errors = _validate_plan(plan)
    if errors:
        logger.warning("Plan validation failed for %s: %s", task_id, errors)

        # If confidence is zero and there are critical errors, fail
        if plan.get("confidence", 0) == 0:
            return {
                **state,
                "status": "failed",
                "plan": plan,
                "error": f"Plan validation failed: {'; '.join(errors)}",
            }

        # Otherwise warn but continue (the plan may still be usable)
        logger.warning("Continuing with imperfect plan for %s", task_id)

    # --- Check estimated budget against remaining ---
    remaining = budget_enforcer.get_remaining(task_id, state.get("budget"))
    estimated = plan.get("estimated_budget_tokens", 0)

    if estimated > remaining["tokens_remaining"]:
        logger.warning(
            "Plan for %s estimates %d tokens but only %d remain",
            task_id,
            estimated,
            remaining["tokens_remaining"],
        )
        # Don't fail — let budget_enforcer kill it during execution if needed

    # --- Persist plan to task directory ---
    _save_plan(task_id, plan)

    logger.info(
        "Plan complete for %s: %d steps, confidence=%.2f, est_tokens=%d",
        task_id,
        len(plan.get("plan_steps", [])),
        plan.get("confidence", 0),
        plan.get("estimated_budget_tokens", 0),
    )

    return {
        **state,
        "status": "executing",
        "plan": plan,
        "error": None,
    }


def _save_plan(task_id: str, plan: dict[str, Any]) -> None:
    """Write the plan to the task directory for traceability via TaskStateManager."""
    try:
        tsm = TaskStateManager()
        tsm.write_plan(task_id, plan)
    except Exception:
        # Fallback to direct file write
        task_dir = os.path.join(".harness", "tasks", task_id)
        if os.path.isdir(task_dir):
            plan_path = os.path.join(task_dir, "plan.json")
            try:
                with open(plan_path, "w") as f:
                    json.dump(plan, f, indent=2)
            except OSError:
                logger.warning("Failed to save plan for %s", task_id)
