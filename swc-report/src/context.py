"""ContextVar 状态管理 — 替代 module-level 全局变量。

每个 Agent 在执行前通过 AgentContext 上下文管理器设置自己的状态，
工具函数通过 get_state() / get_atlas_rag() / get_output_dir() 访问
当前线程/协程的状态副本，实现并行安全。

用法:
    with AgentContext(state=s, atlas_rag=a, output_dir=d):
        agent.run(...)  # 工具函数自动读取当前上下文
"""

from __future__ import annotations

import warnings
from contextvars import ContextVar
from pathlib import Path
from typing import Any

_ctx_state: ContextVar[Any] = ContextVar("agent_state", default=None)
_ctx_atlas_rag: ContextVar[Any] = ContextVar("atlas_rag", default=None)
_ctx_output_dir: ContextVar[Path | None] = ContextVar("output_dir", default=None)


# ── 工具函数调用的读取接口 ──────────────────────────────────────

def get_state():
    """获取当前上下文的 GlobalState (严格版，None 时调用方自行处理)。"""
    return _ctx_state.get()


def get_state_or_none():
    """获取当前上下文的 GlobalState，未设置时返回 None。"""
    return _ctx_state.get()


def get_atlas_rag():
    """获取当前上下文的 AtlasRAG 实例。"""
    return _ctx_atlas_rag.get()


def get_output_dir() -> Path | None:
    """获取当前上下文的输出目录。"""
    return _ctx_output_dir.get()


# ── 上下文管理器 ────────────────────────────────────────────────

class AgentContext:
    """为 Agent 执行设置线程/协程安全的上下文变量。

    用法:
        with AgentContext(state=state, atlas_rag=rag, output_dir=out):
            # 工具函数内 get_state() 返回此处的 state
            agent.run(prompt)
    """

    def __init__(self, state=None, atlas_rag=None, output_dir=None):
        self._state = state
        self._atlas_rag = atlas_rag
        self._output_dir = output_dir
        self._tokens: list = []

    def __enter__(self):
        if self._state is not None:
            self._tokens.append(("state", _ctx_state.set(self._state)))
        if self._atlas_rag is not None:
            self._tokens.append(("atlas_rag", _ctx_atlas_rag.set(self._atlas_rag)))
        if self._output_dir is not None:
            self._tokens.append(("output_dir", _ctx_output_dir.set(self._output_dir)))
        return self

    def __exit__(self, *exc):
        for name, token in reversed(self._tokens):
            if name == "state":
                _ctx_state.reset(token)
            elif name == "atlas_rag":
                _ctx_atlas_rag.reset(token)
            elif name == "output_dir":
                _ctx_output_dir.reset(token)
        self._tokens.clear()
        return False


# ── 向后兼容 deprecated wrappers ────────────────────────────────

def set_state(state) -> None:
    """[Deprecated] 直接设置全局 state，请改用 AgentContext。"""
    warnings.warn(
        "set_state() is deprecated, use AgentContext instead",
        DeprecationWarning,
        stacklevel=2,
    )
    _ctx_state.set(state)


def set_atlas_rag(atlas_rag) -> None:
    """[Deprecated] 直接设置全局 atlas_rag，请改用 AgentContext。"""
    warnings.warn(
        "set_atlas_rag() is deprecated, use AgentContext instead",
        DeprecationWarning,
        stacklevel=2,
    )
    _ctx_atlas_rag.set(atlas_rag)


def set_output_dir(output_dir) -> None:
    """[Deprecated] 直接设置全局 output_dir，请改用 AgentContext。"""
    warnings.warn(
        "set_output_dir() is deprecated, use AgentContext instead",
        DeprecationWarning,
        stacklevel=2,
    )
    _ctx_output_dir.set(output_dir)
