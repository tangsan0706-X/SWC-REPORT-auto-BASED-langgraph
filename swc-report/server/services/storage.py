"""SQLite 存储 — 运行历史记录。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from server.models import RunStatus, RunSummary, RunDetail

_DB_PATH: Path | None = None
_conn: sqlite3.Connection | None = None


def init_db(db_path: Path):
    """初始化数据库。"""
    global _DB_PATH, _conn
    _DB_PATH = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(db_path), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            finished_at TEXT,
            project_name TEXT DEFAULT '',
            total_score REAL DEFAULT 0,
            use_llm INTEGER DEFAULT 1,
            output_dir TEXT,
            error_message TEXT,
            steps TEXT DEFAULT '[]'
        )
    """)
    _conn.commit()


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database not initialized, call init_db() first")
    return _conn


def create_run(use_llm: bool = True) -> str:
    """创建一条运行记录，返回 run_id。"""
    conn = _get_conn()
    run_id = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO runs (id, status, created_at, use_llm) VALUES (?, ?, ?, ?)",
        (run_id, RunStatus.pending, now, int(use_llm)),
    )
    conn.commit()
    return run_id


def update_run(run_id: str, **kwargs):
    """更新运行记录字段。"""
    conn = _get_conn()
    allowed = {"status", "finished_at", "project_name", "total_score",
               "output_dir", "error_message", "steps"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    if "steps" in updates and isinstance(updates["steps"], list):
        updates["steps"] = json.dumps(updates["steps"], ensure_ascii=False)
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE runs SET {set_clause} WHERE id = ?",
                 [*updates.values(), run_id])
    conn.commit()


def get_run(run_id: str) -> RunDetail | None:
    """获取单条运行详情。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return _row_to_detail(row)


def list_runs(limit: int = 50) -> list[RunSummary]:
    """获取运行列表。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_row_to_summary(r) for r in rows]


def delete_run(run_id: str) -> bool:
    """删除运行记录。"""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    conn.commit()
    return cur.rowcount > 0


def _row_to_summary(row: sqlite3.Row) -> RunSummary:
    return RunSummary(
        id=row["id"],
        status=row["status"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
        project_name=row["project_name"] or "",
        total_score=row["total_score"] or 0,
        use_llm=bool(row["use_llm"]),
        error_message=row["error_message"],
    )


def _row_to_detail(row: sqlite3.Row) -> RunDetail:
    steps = json.loads(row["steps"]) if row["steps"] else []
    return RunDetail(
        id=row["id"],
        status=row["status"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
        project_name=row["project_name"] or "",
        total_score=row["total_score"] or 0,
        use_llm=bool(row["use_llm"]),
        error_message=row["error_message"],
        output_dir=row["output_dir"],
        steps=steps,
    )
