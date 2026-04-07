"""Multi-stage review pipeline: initial_review → worker_fix → final_review.

Replaces the single validate node with a three-pass pipeline:
  1. initial_review  — GPT-5.4 reviews worker output, produces actionable feedback
  2. worker_fix      — Qwen applies fixes based on review feedback (skipped if clean)
  3. final_review    — Opus 4.6 read-only final pass, prints issues, determines verdict
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from apps.orchestrator.agents.reviewer import ReviewerAgent
from apps.orchestrator.agents.worker import WorkerAgent
from apps.orchestrator.budget import budget_enforcer
from packages.config import get_project_paths
from packages.eval.deterministic import DeterministicEvaluator
from packages.learning.community_feedback import append_feedback_event, build_feedback_event
from packages.llm.router import LLMRouter
from packages.state.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage 1: Initial Review (GPT-5.4)
# ---------------------------------------------------------------------------

def initial_review_node(state: dict[str, Any]) -> dict[str, Any]:
    """GPT-5.4 first-pass review of worker output.

    Runs deterministic checks, then invokes the initial_reviewer role.
    Stores feedback in state for the worker_fix stage.
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

    # --- Invoke GPT-5.4 reviewer ---
    review_verdict: dict[str, Any] | None = None

    if budget_enforcer.check_budget(state):
        logger.info("Invoking initial reviewer (GPT-5.4) for task %s", task_id)
        review_verdict = _invoke_reviewer(
            artifacts, plan, state, role="initial_reviewer"
        )
    else:
        logger.warning("Skipping initial review for %s — budget exceeded", task_id)

    # Store results for downstream stages
    full_eval = {
        **eval_results,
        "deterministic_verdict": deterministic_verdict,
        "initial_review": review_verdict,
    }

    # Determine if fixes are needed
    needs_fix = False
    if review_verdict:
        verdict = review_verdict.get("verdict", "needs_changes")
        if verdict in ("needs_changes", "rejected"):
            needs_fix = True
            issues = review_verdict.get("issues", [])
            critical = [i for i in issues if i.get("severity") == "critical"]
            if verdict == "rejected" and len(critical) > 3:
                # Too many critical issues — skip fix, go straight to fail
                needs_fix = False

    if not deterministic_verdict.get("passed", False):
        needs_fix = True

    logger.info(
        "Initial review for %s: det_passed=%s, review=%s, needs_fix=%s",
        task_id,
        deterministic_verdict.get("passed"),
        review_verdict.get("verdict") if review_verdict else "skipped",
        needs_fix,
    )

    return {
        **state,
        "status": "fixing" if needs_fix else "final_review",
        "eval_results": full_eval,
    }


# ---------------------------------------------------------------------------
# Stage 2: Worker Fix (Qwen 3.5)
# ---------------------------------------------------------------------------

def worker_fix_node(state: dict[str, Any]) -> dict[str, Any]:
    """Qwen 3.5 applies fixes based on initial review feedback.

    Only runs if initial_review found issues. Uses the worker_fix role.
    """
    task_id = state.get("task_id", "unknown")
    status = state.get("status", "")

    # Skip if no fixes needed
    if status != "fixing":
        logger.info("Skipping worker_fix for %s — no fixes needed", task_id)
        return {**state, "status": "final_review"}

    plan = state.get("plan") or {}
    eval_results = state.get("eval_results") or {}
    initial_review = eval_results.get("initial_review") or {}
    project_paths = get_project_paths(
        project_name=state.get("project_name"),
        repo_path=state.get("repo_path"),
    )

    if not budget_enforcer.check_budget(state):
        logger.warning("Skipping worker_fix for %s — budget exceeded", task_id)
        return {**state, "status": "final_review"}

    # Build fix instructions from review feedback
    issues = initial_review.get("issues", [])
    review_summary = initial_review.get("summary", "")
    fix_instructions = _build_fix_instructions(issues, review_summary, plan)

    # Create a modified plan that includes the fix instructions
    fix_plan = {
        **plan,
        "plan_steps": [
            {
                "step_number": 1,
                "action": "Apply fixes based on review feedback",
                "target": "Files identified in review",
                "rationale": fix_instructions,
            }
        ],
        "selected_skill": plan.get("selected_skill", ""),
    }

    # Invoke worker with the worker_fix role
    worktree_path = state.get("worktree_path") or state.get("repo_path") or "."
    llm_router = LLMRouter()
    worker = WorkerAgent(
        worktree_path=worktree_path,
        project_paths=project_paths,
        llm_router=llm_router,
    )
    # Override to use worker_fix role
    worker.role = "worker_fix"

    try:
        result = _run_async(worker.execute(fix_plan, state))
    except Exception as exc:
        logger.exception("Worker fix failed for task %s", task_id)
        return {
            **state,
            "status": "final_review",
            "eval_results": {
                **eval_results,
                "worker_fix_error": str(exc),
            },
        }

    # Merge fix artifacts with original artifacts
    fix_artifacts = result.get("artifacts", [])
    original_artifacts = state.get("artifacts", [])
    merged_artifacts = original_artifacts + fix_artifacts

    logger.info(
        "Worker fix complete for %s: %d fix artifacts, tests_passed=%s",
        task_id,
        len(fix_artifacts),
        result.get("tests_passed", False),
    )

    return {
        **state,
        "status": "final_review",
        "artifacts": merged_artifacts,
        "eval_results": {
            **eval_results,
            "worker_fix_summary": result.get("summary", ""),
            "worker_fix_tests_passed": result.get("tests_passed", False),
            "tests_passed": result.get("tests_passed", eval_results.get("tests_passed", False)),
        },
    }


# ---------------------------------------------------------------------------
# Stage 3: Final Review (Opus 4.6 — READ-ONLY)
# ---------------------------------------------------------------------------

_FINAL_REVIEW_SYSTEM_PROMPT = """\
You are the Final Reviewer. You perform a read-only quality assessment of the \
completed work. You CANNOT modify files or trigger any agent actions.

## Your Role
- Provide a final quality verdict on the task output
- List any remaining issues with severity ratings
- Your output is the final word — it goes directly to the human operator

## Output Contract
Respond with a single JSON object:
{
  "verdict": "approved" | "needs_changes" | "rejected",
  "issues": [{"severity": "critical|warning|info", "description": "...", "file": "..."}],
  "confidence": 0.0-1.0,
  "summary": "...",
  "quality_score": 0-10,
  "recommendation": "Brief human-readable recommendation"
}

Be thorough but fair. Only reject if there are genuinely critical problems.
"""


def final_review_node(state: dict[str, Any]) -> dict[str, Any]:
    """Opus 4.6 final pass — read-only, no tools, just prints issues.

    This is the terminal review. Its verdict determines the task outcome.
    """
    task_id = state.get("task_id", "unknown")
    plan = state.get("plan") or {}
    artifacts = state.get("artifacts", [])
    eval_results = state.get("eval_results") or {}
    project_paths = get_project_paths(
        project_name=state.get("project_name"),
        repo_path=state.get("repo_path"),
    )

    final_verdict: dict[str, Any] | None = None

    if budget_enforcer.check_budget(state):
        logger.info("Invoking final reviewer (Opus 4.6) for task %s", task_id)
        final_verdict = _invoke_final_reviewer(artifacts, plan, eval_results, state)
    else:
        logger.warning("Skipping final review for %s — budget exceeded", task_id)

    # --- Determine final status ---
    final_status = _determine_final_status(eval_results, final_verdict)

    # --- Aggregate all eval results ---
    full_eval = {
        **eval_results,
        "final_review": final_verdict,
        "final_status": final_status,
    }

    # --- Save validation results ---
    _save_validation(task_id, full_eval, str(project_paths.tasks_dir), str(project_paths.db_path))
    _save_community_feedback(state, full_eval, final_status)

    # --- Log final review for human visibility ---
    if final_verdict:
        _log_final_review(task_id, final_verdict)

    # Handle retries
    retries = state.get("retries", 0)
    if final_status == "retry":
        retries += 1

    logger.info("Review pipeline complete for %s: final_status=%s", task_id, final_status)

    return {
        **state,
        "status": final_status,
        "eval_results": full_eval,
        "retries": retries,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_deterministic_checks(
    eval_results: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    """Run deterministic (non-LLM) validation checks."""
    evaluator = DeterministicEvaluator()
    checks: list[dict[str, Any]] = []
    passed = True

    eval_input: dict[str, Any] = {}
    if eval_results.get("tests_passed") is not None:
        eval_input["test_output"] = "passed" if eval_results["tests_passed"] else "FAILED"

    local_issues = eval_results.get("local_issues", [])
    boundary_violations = [i for i in local_issues if i.get("check") == "out_of_scope_change"]
    if boundary_violations:
        eval_input["boundary_violations"] = boundary_violations

    det_results = evaluator.run_all(eval_input)
    for er in det_results:
        checks.append({"check": er.check_name, "passed": er.passed, "detail": er.details})
        if not er.passed:
            passed = False

    tests_passed = eval_results.get("tests_passed", False)
    checks.append({"check": "tests_passed", "passed": tests_passed, "detail": "Worker-reported"})
    if not tests_passed:
        passed = False

    critical_issues = [i for i in local_issues if i.get("severity") == "critical"]
    checks.append({
        "check": "no_critical_issues",
        "passed": len(critical_issues) == 0,
        "detail": f"{len(critical_issues)} critical issues",
    })
    if critical_issues:
        passed = False

    plan_confidence = plan.get("confidence", 0)
    checks.append({
        "check": "plan_confidence",
        "passed": plan_confidence >= 0.3,
        "detail": f"Plan confidence: {plan_confidence}",
    })

    return {"passed": passed, "checks": checks, "critical_issues": critical_issues}


def _invoke_reviewer(
    artifacts: list[dict[str, Any]],
    plan: dict[str, Any],
    state: dict[str, Any],
    role: str = "initial_reviewer",
) -> dict[str, Any]:
    """Invoke a reviewer agent with the specified role."""
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
    # Override role so it routes to the correct model
    reviewer.role = role

    try:
        return _run_async(reviewer.review(artifacts, plan, state))
    except Exception as exc:
        logger.exception("Reviewer (%s) failed for task %s", role, state.get("task_id"))
        return {
            "verdict": "needs_changes",
            "issues": [{"severity": "warning", "description": f"Reviewer error: {exc}"}],
            "confidence": 0.0,
            "summary": f"Reviewer ({role}) failed with an exception.",
        }


def _invoke_final_reviewer(
    artifacts: list[dict[str, Any]],
    plan: dict[str, Any],
    eval_results: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Invoke Opus 4.6 for read-only final review — NO tools, just analysis."""
    llm_router = LLMRouter()

    # Build a comprehensive review request
    artifact_summary = _summarise_artifacts(artifacts)
    initial_review = eval_results.get("initial_review") or {}
    fix_summary = eval_results.get("worker_fix_summary", "No fixes applied")
    det_verdict = eval_results.get("deterministic_verdict") or {}

    user_message = (
        f"## Final Review — Task {state.get('task_id', '')}\n\n"
        f"### Plan\n"
        f"- In-scope: {json.dumps(plan.get('in_scope', []))}\n"
        f"- Steps: {json.dumps(plan.get('plan_steps', []), indent=2)}\n\n"
        f"### Deterministic Checks\n"
        f"- Passed: {det_verdict.get('passed', 'unknown')}\n"
        f"- Failed checks: {[c['check'] for c in det_verdict.get('checks', []) if not c.get('passed')]}\n\n"
        f"### Initial Review (GPT-5.4)\n"
        f"- Verdict: {initial_review.get('verdict', 'skipped')}\n"
        f"- Issues: {json.dumps(initial_review.get('issues', []), indent=2)}\n"
        f"- Summary: {initial_review.get('summary', 'N/A')}\n\n"
        f"### Worker Fixes Applied\n{fix_summary}\n\n"
        f"### Final Artifacts\n{artifact_summary}\n\n"
        f"Provide your final assessment. Be thorough but fair."
    )

    try:
        result = llm_router.call(
            role="final_reviewer",
            messages=[
                {"role": "system", "content": _FINAL_REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        return _parse_verdict(result.get("content", ""))
    except Exception as exc:
        logger.exception("Final reviewer failed for task %s", state.get("task_id"))
        return {
            "verdict": "needs_changes",
            "issues": [{"severity": "warning", "description": f"Final reviewer error: {exc}"}],
            "confidence": 0.0,
            "summary": "Final reviewer failed.",
            "quality_score": 0,
            "recommendation": "Manual review required.",
        }


def _determine_final_status(
    eval_results: dict[str, Any],
    final_verdict: dict[str, Any] | None,
) -> str:
    """Determine final task status from the full review pipeline."""
    det = eval_results.get("deterministic_verdict", {})

    # Hard fail: deterministic checks failed and no fixes helped
    if not det.get("passed", False):
        # Check if worker_fix improved things
        if eval_results.get("worker_fix_tests_passed"):
            return "done"
        else:
            return "retry"

    # Final reviewer verdict
    if final_verdict:
        verdict = final_verdict.get("verdict", "needs_changes")
        if verdict == "approved":
            return "done"
        if verdict == "rejected":
            return "retry"
        return "retry"

    # No final review (budget exceeded) — use deterministic + initial review
    initial = eval_results.get("initial_review")
    if initial and initial.get("verdict") == "approved":
        return "done"

    return "done" if det.get("passed", False) else "retry"


def _build_fix_instructions(
    issues: list[dict[str, Any]], review_summary: str, plan: dict[str, Any]
) -> str:
    """Build fix instructions from review feedback."""
    parts = [f"## Review Feedback\n{review_summary}\n\n## Issues to Fix"]
    for i, issue in enumerate(issues, 1):
        severity = issue.get("severity", "info")
        desc = issue.get("description", "")
        file = issue.get("file", "")
        parts.append(f"{i}. [{severity.upper()}] {desc}" + (f" (in {file})" if file else ""))
    parts.append(f"\n## Original Plan Scope\n- In-scope: {json.dumps(plan.get('in_scope', []))}")
    parts.append("Fix the issues above. Run tests after fixes. Keep changes minimal.")
    return "\n".join(parts)


def _log_final_review(task_id: str, verdict: dict[str, Any]) -> None:
    """Log the final review results prominently for human visibility."""
    quality = verdict.get("quality_score", "N/A")
    recommendation = verdict.get("recommendation", "")
    issues = verdict.get("issues", [])
    critical = [i for i in issues if i.get("severity") == "critical"]
    warnings = [i for i in issues if i.get("severity") == "warning"]

    logger.info(
        "=== FINAL REVIEW: %s === verdict=%s quality=%s/10 critical=%d warnings=%d",
        task_id, verdict.get("verdict"), quality, len(critical), len(warnings),
    )
    if recommendation:
        logger.info("  Recommendation: %s", recommendation)
    for issue in critical:
        logger.warning("  [CRITICAL] %s", issue.get("description", ""))
    for issue in warnings:
        logger.info("  [WARNING] %s", issue.get("description", ""))


def _summarise_artifacts(artifacts: list[dict[str, Any]]) -> str:
    """Build a compact artifact summary for the final reviewer."""
    if not artifacts:
        return "(no artifacts)"
    parts: list[str] = []
    for art in artifacts:
        art_type = art.get("type", "unknown")
        path = art.get("path", "")
        content = art.get("content", "")
        preview = content[:500] + "..." if len(content) > 500 else content
        parts.append(f"**{art_type}** `{path}`\n```\n{preview}\n```")
    return "\n\n".join(parts)


def _parse_verdict(content: str) -> dict[str, Any]:
    """Parse reviewer JSON output."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    try:
        verdict = json.loads(cleaned)
        verdict.setdefault("verdict", "needs_changes")
        verdict.setdefault("issues", [])
        verdict.setdefault("confidence", 0.5)
        verdict.setdefault("summary", "")
        verdict.setdefault("quality_score", 5)
        verdict.setdefault("recommendation", "")
        return verdict
    except json.JSONDecodeError:
        return {
            "verdict": "needs_changes",
            "issues": [{"severity": "warning", "description": "Final reviewer output was not valid JSON"}],
            "confidence": 0.0,
            "summary": content[:500],
            "quality_score": 0,
            "recommendation": "Manual review required — reviewer output unparseable.",
        }


def _run_async(coro: Any) -> Any:
    """Run an async coroutine, handling nested event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


def _save_validation(
    task_id: str, eval_results: dict[str, Any], tasks_dir: str, db_path: str
) -> None:
    """Persist validation results to filesystem and SQLiteStore."""
    import os

    evals_dir = os.path.join(tasks_dir, task_id, "evals")
    os.makedirs(evals_dir, exist_ok=True)

    try:
        with open(os.path.join(evals_dir, "validation.json"), "w") as f:
            json.dump(eval_results, f, indent=2, default=str)
    except OSError:
        logger.warning("Failed to save validation for %s", task_id)

    try:
        store = SQLiteStore(db_path)
        det = eval_results.get("deterministic_verdict", {})
        store.record_eval(
            task_id=task_id, eval_type="deterministic",
            passed=det.get("passed", False),
            score=1.0 if det.get("passed") else 0.0, details=det,
        )
        for review_key, eval_type in [
            ("initial_review", "initial_reviewer"),
            ("final_review", "final_reviewer"),
        ]:
            review = eval_results.get(review_key)
            if review:
                store.record_eval(
                    task_id=task_id, eval_type=eval_type,
                    passed=review.get("verdict") == "approved",
                    score=review.get("confidence", 0.0), details=review,
                )
        store.close()
    except Exception:
        logger.debug("Failed to persist eval results to SQLite for %s", task_id, exc_info=True)


def _save_community_feedback(
    state: dict[str, Any], eval_results: dict[str, Any], final_status: str
) -> None:
    """Persist repo-agnostic validation record for harness-level learning."""
    try:
        event = build_feedback_event(state, eval_results, final_status)
        append_feedback_event(event)
    except Exception:
        logger.debug("Failed to persist community feedback for %s", state.get("task_id"), exc_info=True)
