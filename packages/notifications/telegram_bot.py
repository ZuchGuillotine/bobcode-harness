"""Telegram bot for task notifications and human-in-the-loop control."""

from __future__ import annotations

import logging
import re
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from packages.notifications.formatters import (
    escape_markdown,
    format_approval_request,
    format_budget_summary,
    format_campaign_preview,
    format_task_status,
)

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram bot for agent-harness notifications and commands."""

    def __init__(
        self,
        token: str,
        allowed_chat_ids: list[int],
        task_state_manager: Any,
        sqlite_store: Any,
    ) -> None:
        self._token = token
        self._allowed_chat_ids = set(allowed_chat_ids)
        self._tsm = task_state_manager
        self._store = sqlite_store
        self._app: Application | None = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def _is_authorized(self, chat_id: int) -> bool:
        return chat_id in self._allowed_chat_ids

    async def _check_auth(self, update: Update) -> bool:
        """Return True if the sender is authorized, else reply and return False."""
        chat_id = update.effective_chat.id  # type: ignore[union-attr]
        if self._is_authorized(chat_id):
            return True
        await update.message.reply_text("Unauthorized.")  # type: ignore[union-attr]
        return False

    # ------------------------------------------------------------------
    # Bot lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Build the Application and start polling (blocking)."""
        self._app = (
            Application.builder()
            .token(self._token)
            .build()
        )

        # Register command handlers
        self._app.add_handler(CommandHandler("approve", self._cmd_approve))
        self._app.add_handler(CommandHandler("reject", self._cmd_reject))
        self._app.add_handler(CommandHandler("hold", self._cmd_hold))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("budget", self._cmd_budget))
        self._app.add_handler(CommandHandler("task", self._cmd_task))

        # Inline callback handler (approve/reject buttons)
        self._app.add_handler(CallbackQueryHandler(self._callback_handler))

        logger.info("Starting Telegram bot polling...")
        self._app.run_polling()

    # ------------------------------------------------------------------
    # Outbound notifications
    # ------------------------------------------------------------------

    async def notify(
        self,
        chat_id: int,
        message: str,
        reply_markup: Any | None = None,
    ) -> None:
        """Send a MarkdownV2 message to *chat_id*."""
        if self._app is None:
            logger.warning("Bot not started; cannot send notification.")
            return
        await self._app.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2",
            reply_markup=reply_markup,
        )

    async def notify_task_complete(self, task_id: str) -> None:
        task = self._store.get_task(task_id)
        if task is None:
            return
        msg = f"✅ *Task {escape_markdown(task_id)} completed\\!*\n\n"
        msg += format_task_status(task)
        for chat_id in self._allowed_chat_ids:
            await self.notify(chat_id, msg)

    async def notify_task_failed(self, task_id: str, error: str) -> None:
        msg = (
            f"❌ *Task {escape_markdown(task_id)} failed*\n\n"
            f"*Error:* {escape_markdown(error)}"
        )
        for chat_id in self._allowed_chat_ids:
            await self.notify(chat_id, msg)

    async def notify_approval_needed(self, task_id: str, summary: str) -> None:
        """Send an approval request with inline approve/reject buttons."""
        msg = format_approval_request(task_id, summary)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Approve",
                        callback_data=f"approve:{task_id}",
                    ),
                    InlineKeyboardButton(
                        "❌ Reject",
                        callback_data=f"reject:{task_id}",
                    ),
                ]
            ]
        )
        for chat_id in self._allowed_chat_ids:
            await self.notify(chat_id, msg, reply_markup=keyboard)

    async def notify_budget_alert(self, task_id: str, usage: dict[str, Any]) -> None:
        msg = (
            f"⚠️ *Budget Alert for {escape_markdown(task_id)}*\n\n"
            + format_budget_summary(usage)
        )
        for chat_id in self._allowed_chat_ids:
            await self.notify(chat_id, msg)

    async def notify_campaign_preview(self, task_id: str, content: str) -> None:
        """Send a campaign draft with inline approve/reject buttons."""
        msg = format_campaign_preview(task_id, content)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Approve",
                        callback_data=f"campaign_approve:{task_id}",
                    ),
                    InlineKeyboardButton(
                        "❌ Reject",
                        callback_data=f"campaign_reject:{task_id}",
                    ),
                ]
            ]
        )
        for chat_id in self._allowed_chat_ids:
            await self.notify(chat_id, msg, reply_markup=keyboard)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _cmd_approve(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle ``/approve TASK-123``."""
        if not await self._check_auth(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: /approve TASK-123")  # type: ignore[union-attr]
            return
        task_id = args[0]
        self._store.update_task_status(task_id, "in_progress")
        state = self._tsm.read_state(task_id)
        state["approved"] = True
        self._tsm.write_state(task_id, state)
        await update.message.reply_text(f"Task {task_id} approved.")  # type: ignore[union-attr]

    async def _cmd_reject(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle ``/reject TASK-123 "reason"``."""
        if not await self._check_auth(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text('Usage: /reject TASK-123 "reason"')  # type: ignore[union-attr]
            return
        task_id = args[0]
        reason = " ".join(args[1:]).strip('"') if len(args) > 1 else "No reason given"
        self._store.update_task_status(task_id, "rejected")
        state = self._tsm.read_state(task_id)
        state["rejected"] = True
        state["rejection_reason"] = reason
        self._tsm.write_state(task_id, state)
        await update.message.reply_text(f"Task {task_id} rejected: {reason}")  # type: ignore[union-attr]

    async def _cmd_hold(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle ``/hold TASK-123``."""
        if not await self._check_auth(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: /hold TASK-123")  # type: ignore[union-attr]
            return
        task_id = args[0]
        self._store.update_task_status(task_id, "held")
        await update.message.reply_text(f"Task {task_id} put on hold.")  # type: ignore[union-attr]

    async def _cmd_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle ``/status [TASK-123]``."""
        if not await self._check_auth(update):
            return
        args = context.args or []
        if args:
            task_id = args[0]
            task = self._store.get_task(task_id)
            if task is None:
                await update.message.reply_text(f"Task {task_id} not found.")  # type: ignore[union-attr]
                return
            msg = format_task_status(task)
            await update.message.reply_text(msg, parse_mode="MarkdownV2")  # type: ignore[union-attr]
        else:
            tasks = self._store.list_tasks()
            if not tasks:
                await update.message.reply_text("No tasks found.")  # type: ignore[union-attr]
                return
            lines = []
            for t in tasks[:10]:
                tid = escape_markdown(t["task_id"])
                st = escape_markdown(t["status"])
                title = escape_markdown(t.get("title", "")[:40])
                lines.append(f"• *{tid}* \\[{st}\\] {title}")
            msg = "*Recent Tasks:*\n" + "\n".join(lines)
            await update.message.reply_text(msg, parse_mode="MarkdownV2")  # type: ignore[union-attr]

    async def _cmd_budget(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle ``/budget``."""
        if not await self._check_auth(update):
            return
        # Aggregate across recent tasks
        tasks = self._store.list_tasks()
        total_cost = 0.0
        total_tokens = 0
        for t in tasks:
            budget = self._tsm.read_budget(t["task_id"])
            total_cost += budget.get("actual_cost", 0.0)
            total_tokens += budget.get("actual_tokens", 0)

        summary = {
            "max_cost": 100.0,  # default cap
            "actual_cost": total_cost,
            "max_tokens": 10_000_000,
            "actual_tokens": total_tokens,
        }
        msg = format_budget_summary(summary)
        await update.message.reply_text(msg, parse_mode="MarkdownV2")  # type: ignore[union-attr]

    async def _cmd_task(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle ``/task "description"``."""
        if not await self._check_auth(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text('Usage: /task "description"')  # type: ignore[union-attr]
            return

        description = " ".join(args).strip('"')
        # Generate a simple task id
        import uuid

        task_id = f"TASK-{uuid.uuid4().hex[:6].upper()}"

        self._tsm.create_task_dir(task_id)
        self._store.create_task(
            {
                "task_id": task_id,
                "title": description[:80],
                "description": description,
                "status": "pending",
            }
        )
        self._tsm.write_state(task_id, {"status": "pending", "description": description})

        await update.message.reply_text(  # type: ignore[union-attr]
            f"Created task {task_id}: {description}"
        )

    # ------------------------------------------------------------------
    # Inline callback handler
    # ------------------------------------------------------------------

    async def _callback_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle inline keyboard button presses."""
        query = update.callback_query
        if query is None:
            return

        chat_id = query.message.chat_id  # type: ignore[union-attr]
        if not self._is_authorized(chat_id):
            await query.answer("Unauthorized.")
            return

        await query.answer()

        data = query.data or ""
        if ":" not in data:
            return

        action, task_id = data.split(":", 1)

        if action == "approve":
            self._store.update_task_status(task_id, "in_progress")
            state = self._tsm.read_state(task_id)
            state["approved"] = True
            self._tsm.write_state(task_id, state)
            await query.edit_message_text(f"Task {task_id} approved.")

        elif action == "reject":
            self._store.update_task_status(task_id, "rejected")
            state = self._tsm.read_state(task_id)
            state["rejected"] = True
            self._tsm.write_state(task_id, state)
            await query.edit_message_text(f"Task {task_id} rejected.")

        elif action == "campaign_approve":
            state = self._tsm.read_state(task_id)
            state["campaign_approved"] = True
            self._tsm.write_state(task_id, state)
            self._store.update_task_status(task_id, "in_progress")
            await query.edit_message_text(f"Campaign for {task_id} approved.")

        elif action == "campaign_reject":
            state = self._tsm.read_state(task_id)
            state["campaign_approved"] = False
            self._tsm.write_state(task_id, state)
            self._store.update_task_status(task_id, "rejected")
            await query.edit_message_text(f"Campaign for {task_id} rejected.")


# ---------------------------------------------------------------------------
# Entrypoint (for running as systemd service)
# ---------------------------------------------------------------------------

def main() -> None:
    """Boot the Telegram bot from environment config."""
    import os
    import yaml

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        raise SystemExit(1)

    # Load allowed chat IDs from config
    config_dir = os.environ.get("HARNESS_CONFIG", "config")
    harness_cfg_path = os.path.join(config_dir, "harness.yaml")
    allowed_ids: list[int] = []
    try:
        with open(harness_cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
        allowed_ids = cfg.get("notifications", {}).get("telegram", {}).get("allowed_chat_ids", [])
    except FileNotFoundError:
        logger.warning("harness.yaml not found; no chat ID restrictions")

    from packages.state.sqlite_store import SQLiteStore
    from packages.state.task_state import TaskStateManager

    db_path = os.environ.get("HARNESS_DB", "data/sqlite/harness.db")
    store = SQLiteStore(db_path)
    tsm = TaskStateManager()

    bot = TelegramNotifier(
        token=token,
        allowed_chat_ids=allowed_ids,
        task_state_manager=tsm,
        sqlite_store=store,
    )

    logger.info("Starting Telegram bot...")
    bot.start()


if __name__ == "__main__":
    main()
