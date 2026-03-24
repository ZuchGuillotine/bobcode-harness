"""SQLite-backed persistence for tasks, evals, failures, and metrics."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteStore:
    """Thin CRUD wrapper around an SQLite database for the agent harness."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id       TEXT PRIMARY KEY,
                title         TEXT,
                description   TEXT,
                status        TEXT NOT NULL DEFAULT 'pending',
                priority      INTEGER DEFAULT 0,
                assignee      TEXT,
                branch        TEXT,
                worktree_path TEXT,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                completed_at  TEXT,
                metadata      TEXT  -- JSON blob
            );

            CREATE TABLE IF NOT EXISTS eval_results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     TEXT NOT NULL REFERENCES tasks(task_id),
                eval_type   TEXT NOT NULL,
                passed      INTEGER NOT NULL DEFAULT 0,
                score       REAL,
                details     TEXT,  -- JSON blob
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS failures (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     TEXT NOT NULL REFERENCES tasks(task_id),
                category    TEXT NOT NULL,
                description TEXT,
                skill_id    TEXT,
                model_used  TEXT,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS campaign_metrics (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id     TEXT NOT NULL,
                metric_name     TEXT NOT NULL,
                metric_value    REAL,
                recorded_at     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS skill_usage (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id         TEXT NOT NULL REFERENCES tasks(task_id),
                skill_id        TEXT NOT NULL,
                invocation_count INTEGER DEFAULT 1,
                total_tokens    INTEGER DEFAULT 0,
                total_cost      REAL DEFAULT 0.0,
                duration_secs   REAL DEFAULT 0.0,
                success         INTEGER DEFAULT 1,
                created_at      TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Tasks CRUD
    # ------------------------------------------------------------------

    def create_task(self, task: dict[str, Any]) -> str:
        """Insert a new task row.  *task* must contain at least ``task_id``."""
        task_id = task["task_id"]
        now = _now_iso()
        self._conn.execute(
            """
            INSERT INTO tasks
                (task_id, title, description, status, priority, assignee,
                 branch, worktree_path, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                task.get("title", ""),
                task.get("description", ""),
                task.get("status", "pending"),
                task.get("priority", 0),
                task.get("assignee"),
                task.get("branch"),
                task.get("worktree_path"),
                now,
                now,
                json.dumps(task.get("metadata", {})),
            ),
        )
        self._conn.commit()
        return task_id

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_task_status(self, task_id: str, status: str) -> None:
        now = _now_iso()
        completed = now if status in ("completed", "failed", "rejected") else None
        self._conn.execute(
            """
            UPDATE tasks
               SET status = ?, updated_at = ?, completed_at = COALESCE(?, completed_at)
             WHERE task_id = ?
            """,
            (status, now, completed, task_id),
        )
        self._conn.commit()

    def update_task(self, task_id: str, fields: dict[str, Any]) -> None:
        """Update arbitrary columns on a task row."""
        allowed = {
            "title", "description", "status", "priority", "assignee",
            "branch", "worktree_path", "metadata",
        }
        cols = {k: v for k, v in fields.items() if k in allowed}
        if not cols:
            return
        if "metadata" in cols and not isinstance(cols["metadata"], str):
            cols["metadata"] = json.dumps(cols["metadata"])
        cols["updated_at"] = _now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in cols)
        vals = list(cols.values()) + [task_id]
        self._conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE task_id = ?", vals
        )
        self._conn.commit()

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Eval results
    # ------------------------------------------------------------------

    def record_eval(
        self,
        task_id: str,
        eval_type: str,
        passed: bool,
        score: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO eval_results (task_id, eval_type, passed, score, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                eval_type,
                int(passed),
                score,
                json.dumps(details) if details else None,
                _now_iso(),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_evals(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM eval_results WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Failures
    # ------------------------------------------------------------------

    def record_failure(
        self,
        task_id: str,
        category: str,
        description: str,
        skill_id: str | None = None,
        model_used: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO failures (task_id, category, description, skill_id, model_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (task_id, category, description, skill_id, model_used, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_failure_stats(self, since: datetime | None = None) -> dict[str, Any]:
        """Aggregate failure counts by category since *since*."""
        if since:
            rows = self._conn.execute(
                """
                SELECT category, COUNT(*) as count
                  FROM failures
                 WHERE created_at >= ?
                 GROUP BY category
                """,
                (since.isoformat(),),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT category, COUNT(*) as count FROM failures GROUP BY category"
            ).fetchall()

        by_category = {r["category"]: r["count"] for r in rows}
        total = sum(by_category.values())
        return {"total": total, "by_category": by_category}

    # ------------------------------------------------------------------
    # Campaign metrics
    # ------------------------------------------------------------------

    def record_campaign_metric(
        self, campaign_id: str, metric_name: str, metric_value: float
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO campaign_metrics (campaign_id, metric_name, metric_value, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            (campaign_id, metric_name, metric_value, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Skill usage
    # ------------------------------------------------------------------

    def record_skill_usage(
        self,
        task_id: str,
        skill_id: str,
        invocation_count: int = 1,
        total_tokens: int = 0,
        total_cost: float = 0.0,
        duration_secs: float = 0.0,
        success: bool = True,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO skill_usage
                (task_id, skill_id, invocation_count, total_tokens,
                 total_cost, duration_secs, success, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                skill_id,
                invocation_count,
                total_tokens,
                total_cost,
                duration_secs,
                int(success),
                _now_iso(),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_skill_usage(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM skill_usage WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]
