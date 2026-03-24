"""Execute stage — invokes the Worker agent in a worktree and captures artifacts."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from apps.orchestrator.agents.worker import WorkerAgent
from apps.orchestrator.budget import budget_enforcer
from packages.llm.router import LLMRouter
from packages.stage_manager.worktree import WorktreeManager

logger = logging.getLogger(__name__)


def execute_node(state: dict[str, Any]) -> dict[str, Any]:
    """Run the Worker agent against the plan and capture artifacts.

    This node:
    1. Checks budget
    2. Resolves the worktree path
    3. Invokes the Worker agent
    4. Captures artifacts and runs local validation
    5. Updates state
    """

    task_id = state.get("task_id", "unknown")
    plan = state.get("plan")

    if not plan:
        logger.error("Execute called with no plan for task %s", task_id)
        return {
            **state,
            "status": "failed",
            "error": "No plan available for execution",
        }

    # --- Budget gate ---
    if not budget_enforcer.check_budget(state):
        return {
            **state,
            "status": "failed",
            "error": "Budget exceeded before execution",
        }

    # --- Resolve worktree via WorktreeManager ---
    repo_path = state.get("repo_path", os.environ.get("HARNESS_REPO_PATH", "."))
    branch = state.get("branch", f"harness/{task_id}")
    wt_manager = WorktreeManager(repo_path=repo_path)

    try:
        worktree_path = str(wt_manager.create(repo_path, task_id, branch))
    except Exception as exc:
        logger.warning("WorktreeManager.create failed, falling back to directory: %s", exc)
        worktree_path = _resolve_worktree(task_id)

    # --- Invoke Worker ---
    llm_router = LLMRouter()
    worker = WorkerAgent(worktree_path=worktree_path, llm_router=llm_router)

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(asyncio.run, worker.execute(plan, state)).result()
        else:
            result = asyncio.run(worker.execute(plan, state))
    except Exception as exc:
        logger.exception("Worker failed for task %s — cleaning up worktree", task_id)
        try:
            wt_manager.cleanup(task_id)
        except Exception:
            logger.debug("Worktree cleanup also failed for %s", task_id, exc_info=True)
        return {
            **state,
            "status": "failed",
            "error": f"Worker exception: {exc}",
        }

    # --- Extract artifacts ---
    artifacts = result.get("artifacts", [])
    tests_passed = result.get("tests_passed", False)
    summary = result.get("summary", "")

    # --- Save artifacts ---
    _save_artifacts(task_id, artifacts)

    # --- Local validation (lightweight) ---
    local_issues = _run_local_validation(artifacts, plan)

    logger.info(
        "Execution complete for %s: %d artifacts, tests_passed=%s, local_issues=%d",
        task_id,
        len(artifacts),
        tests_passed,
        len(local_issues),
    )

    return {
        **state,
        "status": "validating",
        "artifacts": artifacts,
        "eval_results": {
            "worker_summary": summary,
            "tests_passed": tests_passed,
            "local_issues": local_issues,
        },
        "error": None,
    }


def _resolve_worktree(task_id: str) -> str:
    """Resolve the worktree path for a task.

    In MVP, use the task directory. In production, this would create a
    proper git worktree via the stage_manager.
    """

    # Try to use configured worktree base
    worktree_base = os.environ.get(
        "HARNESS_WORKTREE_BASE",
        os.path.join(".harness", "worktrees"),
    )
    worktree_path = os.path.join(worktree_base, task_id)
    os.makedirs(worktree_path, exist_ok=True)

    return worktree_path


def _save_artifacts(task_id: str, artifacts: list[dict[str, Any]]) -> None:
    """Persist artifacts to the task directory."""

    artifact_dir = os.path.join(".harness", "tasks", task_id, "artifacts")
    os.makedirs(artifact_dir, exist_ok=True)

    for i, artifact in enumerate(artifacts):
        filename = f"artifact_{i:03d}.json"
        try:
            with open(os.path.join(artifact_dir, filename), "w") as f:
                json.dump(artifact, f, indent=2)
        except OSError:
            logger.warning("Failed to save artifact %d for %s", i, task_id)

    # Also save a summary manifest
    manifest = {
        "task_id": task_id,
        "artifact_count": len(artifacts),
        "types": [a.get("type", "unknown") for a in artifacts],
    }
    try:
        with open(os.path.join(artifact_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)
    except OSError:
        pass


def _run_local_validation(
    artifacts: list[dict[str, Any]], plan: dict[str, Any]
) -> list[dict[str, Any]]:
    """Run lightweight deterministic checks on the artifacts.

    Returns a list of issues found.
    """

    issues: list[dict[str, Any]] = []

    if not artifacts:
        issues.append({
            "severity": "warning",
            "check": "no_artifacts",
            "message": "Worker produced no artifacts",
        })
        return issues

    # Check: diff artifacts should not touch out-of-scope files
    out_of_scope = set(plan.get("out_of_scope", []))
    for art in artifacts:
        if art.get("type") == "diff":
            art_path = art.get("path", "")
            if art_path in out_of_scope:
                issues.append({
                    "severity": "critical",
                    "check": "out_of_scope_change",
                    "message": f"Diff touches out-of-scope file: {art_path}",
                })

    # Check: at least one test_result artifact if plan expects tests
    has_tests = any(a.get("type") == "test_result" for a in artifacts)
    plan_mentions_tests = any(
        "test" in step.get("action", "").lower()
        for step in plan.get("plan_steps", [])
    )
    if plan_mentions_tests and not has_tests:
        issues.append({
            "severity": "warning",
            "check": "missing_tests",
            "message": "Plan mentions tests but no test_result artifacts found",
        })

    return issues
