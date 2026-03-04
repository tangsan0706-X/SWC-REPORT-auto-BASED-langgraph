"""撰稿智能体工具 — 4 个纯 Python 函数。

工具列表:
  1. rag_search   — ChromaDB 按章节检索范文
  2. calc_lookup   — State 字典取值
  3. self_checker  — 正则提取数字对比 State
  4. prev_chapter  — Draft 中前序章节 800 字摘要
"""

from __future__ import annotations

import re
from typing import Any

from src.context import get_state_or_none


# ═══════════════════════════════════════════════════════════
# Tool 1: rag_search
# ═══════════════════════════════════════════════════════════

RAG_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "rag_search",
        "description": "从 RAG 语料库按章节检索相关范文段落",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"},
                "chapter_id": {"type": "string", "description": "章节编号，如'ch4'"},
                "top_k": {"type": "integer", "description": "返回条数", "default": 3},
            },
            "required": ["query"],
        },
    },
}


def rag_search(query: str, chapter_id: str | None = None,
               top_k: int = 3) -> list[str]:
    """从 ChromaDB 检索与 query 相关的段落。"""
    try:
        from src.rag import search
        return search(query, chapter_id=chapter_id, top_k=top_k)
    except Exception:
        return ["RAG 未就绪。"]


# ═══════════════════════════════════════════════════════════
# Tool 2: calc_lookup
# ═══════════════════════════════════════════════════════════

CALC_LOOKUP_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calc_lookup",
        "description": "从全局状态中查询计算结果值",
        "parameters": {
            "type": "object",
            "properties": {
                "key_path": {
                    "type": "string",
                    "description": "点分路径，如 'earthwork.surplus_m3' 或 'cost_summary.c_grand_total'",
                },
            },
            "required": ["key_path"],
        },
    },
}


def calc_lookup(key_path: str) -> Any:
    """从 State.Calc 中按路径取值。"""
    _state = get_state_or_none()
    if _state is None:
        return {"error": "State 未初始化"}

    parts = key_path.split(".")

    # 尝试从 Calc 分区查找
    obj: Any = None
    calc = _state.Calc
    if parts[0] == "earthwork":
        obj = calc.earthwork
        parts = parts[1:]
    elif parts[0] == "erosion_df":
        obj = calc.erosion_df
        parts = parts[1:]
    elif parts[0] == "cost_summary":
        obj = calc.cost_summary
        parts = parts[1:]
    elif parts[0] == "benefit":
        obj = calc.benefit
        parts = parts[1:]
    else:
        # 直接从 TplCtx 查找
        val = _state.TplCtx.get(key_path)
        if val is not None:
            return val
        # 尝试 Calc 的各子字典
        for d in [calc.earthwork, calc.erosion_df, calc.cost_summary, calc.benefit]:
            if key_path in d:
                return d[key_path]
        return {"error": f"未找到: {key_path}"}

    for p in parts:
        if isinstance(obj, dict):
            obj = obj.get(p)
        else:
            return {"error": f"路径错误: {key_path}"}
        if obj is None:
            return {"error": f"未找到: {key_path}"}

    return obj


# ═══════════════════════════════════════════════════════════
# Tool 3: self_checker
# ═══════════════════════════════════════════════════════════

SELF_CHECKER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "self_checker",
        "description": "检查章节文本中引用的数字是否与计算结果一致",
        "parameters": {
            "type": "object",
            "properties": {
                "chapter_text": {"type": "string", "description": "章节全文"},
                "chapter_id": {"type": "string", "description": "章节编号"},
            },
            "required": ["chapter_text", "chapter_id"],
        },
    },
}


def self_checker(chapter_text: str, chapter_id: str) -> dict:
    """正则提取文本中的数字，与 State/TplCtx 对比。"""
    _state = get_state_or_none()
    if _state is None:
        return {"errors": [], "warnings": ["State 未初始化"]}

    errors = []
    warnings = []
    tpl = _state.TplCtx

    # 提取 "XX万元" 格式的数字
    money_pattern = re.findall(r"([\d.]+)\s*万元", chapter_text)
    # 提取 "XX hm²" 格式
    area_pattern = re.findall(r"([\d.]+)\s*hm[²2]", chapter_text)
    # 提取 "XX m³"
    vol_pattern = re.findall(r"([\d.]+)\s*m[³3]", chapter_text)

    # 对比关键值
    key_values = {
        "c_grand_total": tpl.get("c_grand_total", ""),
        "total_land": tpl.get("total_land", ""),
        "ew_surplus": tpl.get("ew_surplus", ""),
        "ep_total_new": tpl.get("ep_total_new", ""),
    }

    # 对比关键数值: 金额
    ref_grand_total = key_values.get("c_grand_total", "")
    for val_str in money_pattern:
        if val_str == ref_grand_total:
            continue
        try:
            val = float(val_str)
            ref = float(ref_grand_total) if ref_grand_total else 0
            if ref > 0 and abs(val - ref) / ref > 0.1:
                errors.append(f"金额 {val_str}万元 与计算值 {ref} 偏差超过10%")
            else:
                warnings.append(f"文本引用金额: {val_str}万元")
        except (ValueError, TypeError):
            warnings.append(f"文本引用金额: {val_str}万元")

    # 对比关键数值: 面积
    ref_total_land = key_values.get("total_land", "")
    for val_str in area_pattern:
        try:
            val = float(val_str)
            ref = float(ref_total_land) if ref_total_land else 0
            if ref > 0 and abs(val - ref) / ref > 0.1:
                errors.append(f"面积 {val_str}hm2 与计算值 {ref} 偏差超过10%")
        except (ValueError, TypeError):
            pass

    return {
        "chapter_id": chapter_id,
        "errors": errors,
        "warnings": warnings,
        "numbers_found": {
            "money": money_pattern,
            "area": area_pattern,
            "volume": vol_pattern,
        },
    }


# ═══════════════════════════════════════════════════════════
# Tool 4: prev_chapter
# ═══════════════════════════════════════════════════════════

PREV_CHAPTER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "prev_chapter",
        "description": "获取前序章节的 800 字摘要",
        "parameters": {
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "当前章节编号，如'ch3'"},
            },
            "required": ["chapter_id"],
        },
    },
}


def prev_chapter(chapter_id: str) -> str:
    """返回所有前序章节的 800 字摘要。"""
    _state = get_state_or_none()
    if _state is None:
        return "State 未初始化"

    # 章节顺序
    chapter_order = [
        "chapter2", "chapter3", "chapter4", "chapter5",
        "chapter6", "chapter7", "chapter8", "chapter1",
    ]

    # 提取章节号
    ch_num = "".join(filter(str.isdigit, chapter_id))
    target = f"chapter{ch_num}"

    # 收集前序章节文本
    prev_texts = []
    for ch in chapter_order:
        if ch == target:
            break
        # 查找所有此章节的标签
        for key, val in _state.Draft.items():
            if key.startswith(ch) and val:
                prev_texts.append(val[:200])
                break

    if not prev_texts:
        return "无前序章节内容。"

    # 拼接所有前序章节摘要, 总长不超过 800 字
    combined = "\n---\n".join(prev_texts)
    return combined[:800]


# ── 工具注册表 ──
WRITER_TOOLS = [
    (rag_search, RAG_SEARCH_SCHEMA),
    (calc_lookup, CALC_LOOKUP_SCHEMA),
    (self_checker, SELF_CHECKER_SCHEMA),
    (prev_chapter, PREV_CHAPTER_SCHEMA),
]

WRITER_TOOL_MAP = {
    "rag_search": rag_search,
    "calc_lookup": calc_lookup,
    "self_checker": self_checker,
    "prev_chapter": prev_chapter,
}
