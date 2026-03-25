"""Telegram bot for task notifications and human-in-the-loop control."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
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
    format_task_details,
    format_task_lifecycle_complete,
    format_task_lifecycle_failed,
    format_task_status,
)
from packages.config import (
    find_task_dir,
    get_harness_root,
    get_project_paths,
    iter_registered_projects,
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
        project_name: str | None = None,
    ) -> None:
        self._token = token
        self._allowed_chat_ids = set(allowed_chat_ids)
        self._tsm = task_state_manager
        self._store = sqlite_store
        self._project_name = project_name
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
        self._app.add_handler(CommandHandler("details", self._cmd_details))
        self._app.add_handler(CommandHandler("diff", self._cmd_diff))

        # Inline callback handler (approve/reject/details buttons)
        self._app.add_handler(CallbackQueryHandler(self._callback_handler))

        logger.info("Starting Telegram bot polling...")
        self._app.run_polling()

    # ------------------------------------------------------------------
    # Outbound notifications (compact lifecycle format)
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
        """Send a compact completion notification to all allowed chats."""
        task = self._store.get_task(task_id)
        if task is None:
            return
        summary = {
            "status": task.get("status", "done"),
            "summary": task.get("description", "Task completed."),
            "branch": task.get("branch"),
        }
        msg = format_task_lifecycle_complete(task_id, summary)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📋 Details", callback_data=f"details:{task_id}")]]
        )
        for chat_id in self._allowed_chat_ids:
            await self.notify(chat_id, msg, reply_markup=keyboard)

    async def notify_task_failed(self, task_id: str, error: str) -> None:
        """Send a compact failure notification to all allowed chats."""
        msg = format_task_lifecycle_failed(task_id, error)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📋 Details", callback_data=f"details:{task_id}")]]
        )
        for chat_id in self._allowed_chat_ids:
            await self.notify(chat_id, msg, reply_markup=keyboard)

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
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("📋 Details", callback_data=f"details:{task_id}")]]
            )
            await update.message.reply_text(msg, parse_mode="MarkdownV2", reply_markup=keyboard)  # type: ignore[union-attr]
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
        """Handle ``/task "description"`` — submit to the real orchestrator."""
        if not await self._check_auth(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text('Usage: /task "description"')  # type: ignore[union-attr]
            return

        description = " ".join(args).strip('"')

        if not self._project_name:
            await update.message.reply_text(  # type: ignore[union-attr]
                "No project bound. Set TELEGRAM_PROJECT or register a project."
            )
            return

        # Acknowledge immediately — orchestrator runs in background
        await update.message.reply_text(  # type: ignore[union-attr]
            f"Submitting task to project {self._project_name}..."
        )

        chat_id = update.effective_chat.id  # type: ignore[union-attr]
        asyncio.create_task(self._execute_and_notify(chat_id, description))

    async def _execute_and_notify(self, chat_id: int, description: str) -> None:
        """Run the full orchestrator pipeline and send a compact result."""
        from apps.orchestrator.main import run_task

        try:
            result = await run_task(
                description=description,
                project_name=self._project_name,
            )
            task_id = result.get("task_id", "unknown")
            status = result.get("status", "unknown")

            if status == "done":
                summary = self._build_summary(result)
                msg = format_task_lifecycle_complete(task_id, summary)
            elif status in ("failed", "learned"):
                error = result.get("error") or f"Ended with status: {status}"
                msg = format_task_lifecycle_failed(task_id, error)
            else:
                msg = (
                    f"*{escape_markdown(task_id)}* finished\n"
                    f"*Status:* {escape_markdown(status)}"
                )

            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("📋 Details", callback_data=f"details:{task_id}")]]
            )
            await self.notify(chat_id, msg, reply_markup=keyboard)
        except Exception as exc:
            logger.exception("Orchestrator submission failed")
            try:
                error_msg = (
                    f"❌ *Task submission failed*\n\n"
                    f"{escape_markdown(str(exc)[:300])}"
                )
                await self.notify(chat_id, error_msg)
            except Exception:
                logger.exception("Failed to send error notification")

    @staticmethod
    def _build_summary(result: dict[str, Any]) -> dict[str, Any]:
        """Extract a compact summary dict from the orchestrator result."""
        eval_results = result.get("eval_results") or {}
        artifacts = result.get("artifacts", [])
        changed_files = sum(1 for a in artifacts if a.get("type") == "diff")
        return {
            "status": result.get("status", "done"),
            "summary": eval_results.get("worker_summary", "Task completed."),
            "changed_files": changed_files or None,
            "tests": eval_results.get("tests_passed"),
            "branch": result.get("branch"),
        }

    async def _cmd_details(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle ``/details TASK-ID`` — pull-based verbose task view."""
        if not await self._check_auth(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: /details TASK-ID")  # type: ignore[union-attr]
            return

        task_id = args[0]
        msg = self._load_and_format_details(task_id)
        if msg is None:
            await update.message.reply_text(f"Task {task_id} not found.")  # type: ignore[union-attr]
            return
        await update.message.reply_text(msg, parse_mode="MarkdownV2")  # type: ignore[union-attr]

    async def _cmd_diff(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle ``/diff TASK-ID`` — show diff artifacts on demand."""
        if not await self._check_auth(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: /diff TASK-ID")  # type: ignore[union-attr]
            return

        task_id = args[0]
        located = find_task_dir(task_id, project_name=self._project_name)
        if not located:
            await update.message.reply_text(f"Task {task_id} not found.")  # type: ignore[union-attr]
            return

        _proj, task_dir = located
        artifacts_dir = task_dir / "artifacts"
        if not artifacts_dir.is_dir():
            await update.message.reply_text(f"No artifacts for {task_id}.")  # type: ignore[union-attr]
            return

        diffs: list[dict[str, Any]] = []
        for p in sorted(artifacts_dir.glob("artifact_*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("type") == "diff":
                    diffs.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        if not diffs:
            await update.message.reply_text(f"No diff artifacts for {task_id}.")  # type: ignore[union-attr]
            return

        # Plain text to avoid MarkdownV2 escaping issues with diff content
        lines = [f"Diffs for {task_id}:\n"]
        for d in diffs[:10]:
            file_path = d.get("path", "?")
            lines.append(f"--- {file_path}")
            content = d.get("content", "")
            if content:
                preview_lines = content.splitlines()[:15]
                lines.extend(preview_lines)
                if len(content.splitlines()) > 15:
                    lines.append("... (truncated)")
            lines.append("")

        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:3950] + "\n\n(truncated)"

        await update.message.reply_text(msg)  # type: ignore[union-attr]

    def _load_and_format_details(self, task_id: str) -> str | None:
        """Load task data from filesystem and format as a details message."""
        located = find_task_dir(task_id, project_name=self._project_name)
        if not located:
            return None

        _proj, task_dir = located

        manifest: dict[str, Any] = {}
        plan: dict[str, Any] = {}
        evals: dict[str, Any] = {}

        manifest_path = task_dir / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        plan_path = task_dir / "plan.json"
        if plan_path.is_file():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        eval_path = task_dir / "evals" / "validation.json"
        if eval_path.is_file():
            try:
                evals = json.loads(eval_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        return format_task_details(task_id, manifest, evals, plan)

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

        elif action == "details":
            msg = self._load_and_format_details(task_id)
            if msg:
                await query.edit_message_text(msg, parse_mode="MarkdownV2")
            else:
                await query.edit_message_text(f"Task {task_id} not found.")


def _resolve_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def _resolve_telegram_project(
    config: dict[str, Any],
    env: dict[str, str] | None = None,
) -> str | None:
    """Resolve which registered project the Telegram bot should manage."""
    env = env or os.environ
    telegram_cfg = config.get("notifications", {}).get("telegram", {})

    explicit = (
        env.get("TELEGRAM_PROJECT")
        or env.get("HARNESS_PROJECT")
        or telegram_cfg.get("project")
        or telegram_cfg.get("default_project")
    )
    if explicit:
        return str(explicit)

    registered = [name for name, _path in iter_registered_projects()]
    if len(registered) == 1:
        return registered[0]

    return None


def _resolve_legacy_sqlite_path(
    config: dict[str, Any],
    env: dict[str, str] | None = None,
) -> Path:
    """Resolve the legacy/global SQLite path for Telegram fallback mode."""
    env = env or os.environ
    configured = env.get("HARNESS_DB") or config.get("database", {}).get("sqlite_path") or "data/sqlite/harness.db"
    return _resolve_path(str(configured), get_harness_root())


# ---------------------------------------------------------------------------
# Entrypoint (for running as systemd service)
# ---------------------------------------------------------------------------

def main() -> None:
    """Boot the Telegram bot from environment config."""
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
    cfg: dict[str, Any] = {}
    try:
        with open(harness_cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
        allowed_ids = cfg.get("notifications", {}).get("telegram", {}).get("allowed_chat_ids", [])
    except FileNotFoundError:
        logger.warning("harness.yaml not found; no chat ID restrictions")

    from packages.state.sqlite_store import SQLiteStore
    from packages.state.task_state import TaskStateManager

    project_name = _resolve_telegram_project(cfg)
    if project_name:
        project_paths = get_project_paths(project_name=project_name)
        store = SQLiteStore(str(project_paths.db_path))
        tsm = TaskStateManager(tasks_dir=str(project_paths.tasks_dir))
        logger.info(
            "Telegram bot bound to project=%s db=%s tasks_dir=%s",
            project_name,
            project_paths.db_path,
            project_paths.tasks_dir,
        )
    else:
        db_path = _resolve_legacy_sqlite_path(cfg)
        store = SQLiteStore(str(db_path))
        tsm = TaskStateManager()
        logger.warning(
            "Telegram bot running in legacy/global mode. "
            "Set TELEGRAM_PROJECT or notifications.telegram.project to bind a registered project."
        )

    bot = TelegramNotifier(
        token=token,
        allowed_chat_ids=allowed_ids,
        task_state_manager=tsm,
        sqlite_store=store,
        project_name=project_name,
    )

    logger.info("Starting Telegram bot...")
    bot.start()


if __name__ == "__main__":
    main()
