"""Pipeline 运行器 — 后台线程执行 + 进度事件推送。"""

from __future__ import annotations

import json
import threading
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from server.services import storage
from server.models import RunStatus

logger = logging.getLogger(__name__)

# 进度事件存储: {run_id: [event_dict, ...]}
_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
# 运行状态锁
_lock = threading.Lock()


def start_run(run_id: str, facts_path: Path, measures_path: Path,
              output_dir: Path, use_llm: bool = True):
    """在后台线程启动 Pipeline 运行。"""
    t = threading.Thread(
        target=_run_pipeline,
        args=(run_id, facts_path, measures_path, output_dir, use_llm),
        daemon=True,
    )
    t.start()


def get_events(run_id: str, after: int = 0) -> list[dict[str, Any]]:
    """获取指定 run_id 的进度事件 (从 after 索引开始)。"""
    with _lock:
        events = _events.get(run_id, [])
        return events[after:]


def is_finished(run_id: str) -> bool:
    """检查 run 是否已结束。完成后标记延迟清理以防止内存泄漏。"""
    run = storage.get_run(run_id)
    if run is None:
        return True
    finished = run.status in (RunStatus.done, RunStatus.error)
    if finished:
        _finished_runs.add(run_id)
    return finished


def _push_event(run_id: str, event: dict[str, Any]):
    """推送一个进度事件。"""
    event["timestamp"] = datetime.now().isoformat()
    with _lock:
        _events[run_id].append(event)
    # 同步更新 DB 中的 steps
    storage.update_run(run_id, steps=_events[run_id])


def _run_pipeline(run_id: str, facts_path: Path, measures_path: Path,
                  output_dir: Path, use_llm: bool):
    """在后台线程中执行 Pipeline。"""
    import sys
    import os

    # 确保项目根目录在 path 中
    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    storage.update_run(run_id, status=RunStatus.running)
    _push_event(run_id, {"step": "pipeline", "status": "started"})

    try:
        from src.pipeline import Pipeline

        def on_progress(event: dict[str, Any]):
            _push_event(run_id, event)

        pipeline = Pipeline(
            facts_path=facts_path,
            measures_path=measures_path,
            output_dir=output_dir,
            use_llm=use_llm,
            on_progress=on_progress,
        )
        report_path = pipeline.run()

        # 提取结果
        project_name = ""
        total_score = 0
        if pipeline.state:
            project_name = pipeline.state.Static.meta.get("project_name", "")
            total_score = pipeline.state.Flags.get("final_score", 0)

        # 先推送最终事件，再更新 DB 状态为 done（避免 SSE 竞态丢失末条事件）
        _push_event(run_id, {"step": "pipeline", "status": "done",
                             "report_path": str(report_path)})
        storage.update_run(
            run_id,
            status=RunStatus.done,
            finished_at=datetime.now().isoformat(),
            project_name=project_name,
            total_score=total_score,
            output_dir=str(output_dir),
        )

    except Exception as e:
        logger.exception(f"Pipeline run {run_id} failed")
        # 先推送错误事件，再更新 DB 状态
        _push_event(run_id, {"step": "pipeline", "status": "error",
                             "error": str(e)})
        storage.update_run(
            run_id,
            status=RunStatus.error,
            finished_at=datetime.now().isoformat(),
            error_message=str(e),
        )


def cleanup_events(run_id: str):
    """清理已完成 run 的内存事件。"""
    with _lock:
        _events.pop(run_id, None)


# 已通知完成的 run_id 集合，用于延迟清理内存
_finished_runs: set[str] = set()


def _auto_cleanup():
    """自动清理已完成 run 的内存事件（防止内存泄漏）。"""
    with _lock:
        for run_id in list(_finished_runs):
            _events.pop(run_id, None)
        _finished_runs.clear()
