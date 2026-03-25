"""Telegram MarkdownV2 message formatters."""

from __future__ import annotations

import re
from typing import Any


# Characters that must be escaped in Telegram MarkdownV2
_MD2_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 format."""
    return re.sub(r"([" + re.escape(_MD2_SPECIAL) + r"])", r"\\\1", str(text))


def format_task_status(task: dict[str, Any]) -> str:
    """Format a task dict as a MarkdownV2 status message."""
    task_id = escape_markdown(task.get("task_id", "unknown"))
    title = escape_markdown(task.get("title", "Untitled"))
    status = task.get("status", "unknown")
    priority = task.get("priority", 0)
    assignee = escape_markdown(task.get("assignee") or "unassigned")
    created = escape_markdown(task.get("created_at", ""))

    status_emoji = {
        "pending": "🕐",
        "planning": "📋",
        "in_progress": "🔄",
        "review": "👀",
        "completed": "✅",
        "failed": "❌",
        "rejected": "🚫",
        "held": "⏸",
        "awaiting_approval": "⏳",
    }.get(status, "❓")

    return (
        f"*Task {task_id}*\n"
        f"{status_emoji} *Status:* {escape_markdown(status)}\n"
        f"📌 *Title:* {title}\n"
        f"🎯 *Priority:* {escape_markdown(str(priority))}\n"
        f"👤 *Assignee:* {assignee}\n"
        f"📅 *Created:* {created}"
    )


def format_budget_summary(budget: dict[str, Any]) -> str:
    """Format budget usage as a MarkdownV2 message."""
    max_cost = budget.get("max_cost", 0)
    actual_cost = budget.get("actual_cost", 0)
    max_tokens = budget.get("max_tokens", 0)
    actual_tokens = budget.get("actual_tokens", 0)

    cost_pct = (actual_cost / max_cost * 100) if max_cost else 0
    token_pct = (actual_tokens / max_tokens * 100) if max_tokens else 0

    cost_bar = _progress_bar(cost_pct)
    token_bar = _progress_bar(token_pct)

    return (
        f"*💰 Budget Summary*\n\n"
        f"*Cost:* {escape_markdown(f'${actual_cost:.4f}')} / "
        f"{escape_markdown(f'${max_cost:.4f}')}\n"
        f"{cost_bar} {escape_markdown(f'{cost_pct:.1f}%')}\n\n"
        f"*Tokens:* {escape_markdown(str(actual_tokens))} / "
        f"{escape_markdown(str(max_tokens))}\n"
        f"{token_bar} {escape_markdown(f'{token_pct:.1f}%')}"
    )


def format_approval_request(task_id: str, summary: str) -> str:
    """Format an approval request message."""
    return (
        f"*🔔 Approval Required*\n\n"
        f"*Task:* {escape_markdown(task_id)}\n\n"
        f"{escape_markdown(summary)}\n\n"
        f"_Use the buttons below or reply with_\n"
        f"`/approve {escape_markdown(task_id)}` _or_ "
        f"`/reject {escape_markdown(task_id)}`"
    )


def format_campaign_preview(task_id: str, content: str) -> str:
    """Format a campaign content preview for approval."""
    # Truncate long content
    preview = content[:2000] + "..." if len(content) > 2000 else content

    return (
        f"*📝 Campaign Preview*\n\n"
        f"*Task:* {escape_markdown(task_id)}\n\n"
        f"```\n{escape_markdown(preview)}\n```\n\n"
        f"_Approve or reject this content\\._"
    )


def format_task_lifecycle_complete(task_id: str, summary: dict[str, Any]) -> str:
    """Compact completion message: summary-first, no code dumps."""
    parts = [f"✅ *{escape_markdown(task_id)} completed*"]

    worker_summary = summary.get("summary", "")
    if worker_summary:
        parts.append(escape_markdown(str(worker_summary)[:200]))

    changed = summary.get("changed_files")
    if changed:
        parts.append(f"📁 *Changed files:* {escape_markdown(str(changed))}")

    tests = summary.get("tests")
    if tests is not None:
        icon = "✅" if tests else "❌"
        label = "passed" if tests else "failed"
        parts.append(f"{icon} *Tests:* {escape_markdown(label)}")

    branch = summary.get("branch")
    if branch:
        parts.append(f"🌿 *Branch:* {escape_markdown(str(branch))}")

    return "\n".join(parts)


def format_task_lifecycle_failed(task_id: str, error: str) -> str:
    """Compact failure message with inspect hint."""
    tid = escape_markdown(task_id)
    return (
        f"❌ *{tid} failed*\n\n"
        f"*Reason:* {escape_markdown(str(error)[:300])}\n\n"
        f"_Use /details {tid} to inspect\\._"
    )


def format_task_details(
    task_id: str,
    manifest: dict[str, Any],
    evals: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> str:
    """Detailed task view for /details command (pull-based verbosity)."""
    parts = [f"*📋 Task {escape_markdown(task_id)}*\n"]

    if manifest:
        parts.append(f"*Type:* {escape_markdown(manifest.get('task_type', '?'))}")
        parts.append(f"*Created:* {escape_markdown(manifest.get('created_at', '?'))}")
        desc = manifest.get("description", "")
        if desc:
            parts.append(f"*Description:* {escape_markdown(desc[:200])}")
        project = manifest.get("project_name")
        if project:
            parts.append(f"*Project:* {escape_markdown(project)}")

    if plan:
        steps = plan.get("plan_steps", [])
        confidence = plan.get("confidence", 0)
        skill = plan.get("selected_skill", "")
        parts.append(
            f"\n*Plan* \\(confidence: {escape_markdown(f'{confidence:.0%}')}\\)"
        )
        if skill:
            parts.append(f"*Skill:* {escape_markdown(skill)}")
        for i, step in enumerate(steps[:5], 1):
            action = escape_markdown(str(step.get("action", "?"))[:80])
            parts.append(f"  {i}\\. {action}")
        if len(steps) > 5:
            remaining = escape_markdown(str(len(steps) - 5))
            parts.append(f"  _\\.\\.\\.and {remaining} more_")

    if evals:
        det = evals.get("deterministic_verdict", {})
        if det:
            passed = det.get("passed", False)
            icon = "✅" if passed else "❌"
            parts.append(f"\n*Validation:* {icon}")
            for check in det.get("checks", []):
                c_icon = "✅" if check.get("passed") else "❌"
                parts.append(
                    f"  {c_icon} {escape_markdown(check.get('check', '?'))}"
                )

        review = evals.get("review_verdict")
        if review:
            verdict = review.get("verdict", "?")
            conf = review.get("confidence", 0)
            parts.append(
                f"\n*Review:* {escape_markdown(verdict)} "
                f"\\(confidence: {escape_markdown(f'{conf:.0%}')}\\)"
            )

    msg = "\n".join(parts)
    if len(msg) > 4000:
        msg = msg[:3950] + "\n\n_\\(truncated\\)_"
    return msg


def _progress_bar(pct: float, width: int = 10) -> str:
    """Render a text-based progress bar."""
    filled = int(pct / 100 * width)
    filled = min(filled, width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return escape_markdown(f"[{bar}]")
