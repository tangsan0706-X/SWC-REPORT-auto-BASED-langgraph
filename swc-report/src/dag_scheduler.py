"""DAG 调度器 — 按依赖关系并行执行步骤。

用法:
    dag = DAGScheduler()
    dag.add_step("load",    load_fn)
    dag.add_step("calc_a",  calc_a_fn, ["load"])
    dag.add_step("calc_b",  calc_b_fn, ["load"])
    dag.add_step("merge",   merge_fn,  ["calc_a", "calc_b"])
    dag.run(max_workers=4)

依赖解析规则:
  - 就绪 = 所有依赖状态为 "done"
  - 失败传播 = 如果依赖失败，下游自动 skip
  - 致命步骤失败 → 立即取消未启动的步骤
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, Future, FIRST_COMPLETED, wait
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class StepNode:
    """DAG 中的一个步骤节点。"""
    name: str
    func: Callable
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"       # pending / running / done / failed / skipped
    error: Exception | None = None
    critical: bool = True         # 失败时是否终止整条链

    def __repr__(self):
        return f"StepNode({self.name!r}, status={self.status!r})"


class DAGScheduler:
    """基于 ThreadPoolExecutor 的 DAG 步骤调度器。"""

    def __init__(self):
        self._steps: dict[str, StepNode] = {}
        self._lock = threading.Lock()

    def add_step(self, name: str, func: Callable,
                 depends_on: list[str] | None = None,
                 critical: bool = True) -> None:
        """注册一个步骤。

        Args:
            name: 唯一步骤名
            func: 可调用对象 (无参数)
            depends_on: 依赖的步骤名列表
            critical: 如果为 True，失败时下游步骤会被 skip
        """
        if name in self._steps:
            raise ValueError(f"步骤名重复: {name}")
        deps = depends_on or []
        for d in deps:
            if d not in self._steps:
                raise ValueError(f"步骤 {name} 依赖的 {d} 尚未注册 (请按拓扑序注册)")
        self._steps[name] = StepNode(
            name=name, func=func, depends_on=deps, critical=critical,
        )

    def run(self, max_workers: int = 4,
            on_progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, str]:
        """执行 DAG，返回 {step_name: status} 映射。"""
        running_futures: dict[Future, str] = {}

        def _emit(step: str, status: str, error: str = ""):
            if on_progress:
                try:
                    on_progress({"step": step, "status": status, "error": error})
                except Exception:
                    pass

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while True:
                with self._lock:
                    # 找到就绪步骤
                    ready = self._get_ready_steps()
                    # 检查是否所有步骤都已完成
                    all_done = all(
                        s.status in ("done", "failed", "skipped")
                        for s in self._steps.values()
                    )

                if all_done and not running_futures:
                    break

                # 提交就绪步骤
                for step in ready:
                    with self._lock:
                        step.status = "running"
                    logger.info(f"[DAG] 启动: {step.name}")
                    _emit(step.name, "running")
                    future = executor.submit(self._run_step, step)
                    running_futures[future] = step.name

                if not running_futures:
                    # 没有正在运行的也没有就绪的 → 可能有环或全部 skipped
                    break

                # 等待至少一个完成
                done_futures, _ = wait(
                    running_futures.keys(), return_when=FIRST_COMPLETED,
                )

                for future in done_futures:
                    step_name = running_futures.pop(future)
                    step = self._steps[step_name]

                    try:
                        future.result()  # 抛出异常如果步骤失败
                    except Exception:
                        pass  # 已在 _run_step 中处理

                    if step.status == "done":
                        logger.info(f"[DAG] 完成: {step_name}")
                        _emit(step_name, "done")
                    elif step.status == "failed":
                        logger.error(f"[DAG] 失败: {step_name} — {step.error}")
                        _emit(step_name, "error", str(step.error))
                        # 传播 skip 到下游
                        self._skip_downstream(step_name)

        # 汇总
        summary = {name: s.status for name, s in self._steps.items()}
        failed = [n for n, s in summary.items() if s == "failed"]
        skipped = [n for n, s in summary.items() if s == "skipped"]
        if failed:
            logger.warning(f"[DAG] 失败步骤: {failed}")
        if skipped:
            logger.warning(f"[DAG] 跳过步骤: {skipped}")

        return summary

    def _get_ready_steps(self) -> list[StepNode]:
        """找出所有依赖已满足且状态为 pending 的步骤。"""
        ready = []
        for step in self._steps.values():
            if step.status != "pending":
                continue
            deps_met = all(
                self._steps[d].status == "done"
                for d in step.depends_on
            )
            # 如果有依赖失败/skipped，则 skip 本步骤
            deps_failed = any(
                self._steps[d].status in ("failed", "skipped")
                for d in step.depends_on
            )
            if deps_failed:
                step.status = "skipped"
                logger.info(f"[DAG] 跳过: {step.name} (依赖未满足)")
                continue
            if deps_met:
                ready.append(step)
        return ready

    def _run_step(self, step: StepNode) -> None:
        """执行单个步骤，更新状态。"""
        try:
            step.func()
            with self._lock:
                step.status = "done"
        except Exception as e:
            with self._lock:
                step.status = "failed"
                step.error = e
            logger.error(f"[DAG] 步骤 {step.name} 异常: {e}")

    def _skip_downstream(self, failed_name: str) -> None:
        """将依赖于失败步骤的所有下游步骤标记为 skipped。"""
        with self._lock:
            # BFS 传播
            queue = [failed_name]
            while queue:
                current = queue.pop(0)
                for step in self._steps.values():
                    if current in step.depends_on and step.status == "pending":
                        step.status = "skipped"
                        logger.info(f"[DAG] 级联跳过: {step.name}")
                        queue.append(step.name)
