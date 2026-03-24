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


def _progress_bar(pct: float, width: int = 10) -> str:
    """Render a text-based progress bar."""
    filled = int(pct / 100 * width)
    filled = min(filled, width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return escape_markdown(f"[{bar}]")
