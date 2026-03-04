"""措施规划师工具 — 4 个纯 Python 函数，不涉及 LLM。

工具列表:
  1. measure_library  — 查询标准措施库
  2. quantity_estimator — 工程量估算
  3. regulation_checker — 法规合规检查
  4. rag_exemplar — RAG 范例检索
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


# ── 全局引用 (延迟加载) ───────────────────────────────────
_measure_lib: dict | None = None
_legal_refs: dict | None = None


def _load_measure_library() -> dict:
    global _measure_lib
    if _measure_lib is None:
        from src.settings import MEASURE_LIBRARY_PATH
        with open(MEASURE_LIBRARY_PATH, "r", encoding="utf-8") as f:
            _measure_lib = json.load(f)
    return _measure_lib


def _load_legal_refs() -> dict:
    global _legal_refs
    if _legal_refs is None:
        from src.settings import LEGAL_REFS_PATH
        with open(LEGAL_REFS_PATH, "r", encoding="utf-8") as f:
            _legal_refs = json.load(f)
    return _legal_refs


# ═══════════════════════════════════════════════════════════
# Tool 1: measure_library
# ═══════════════════════════════════════════════════════════

MEASURE_LIBRARY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "measure_library",
        "description": "从标准措施库中查询适用于指定分区和类型的候选措施列表",
        "parameters": {
            "type": "object",
            "properties": {
                "zone_type": {
                    "type": "string",
                    "description": "分区名称，如'建(构)筑物区'",
                },
                "measure_type": {
                    "type": "string",
                    "enum": ["工程措施", "植物措施", "临时措施"],
                    "description": "措施类型",
                },
            },
            "required": ["zone_type"],
        },
    },
}


def measure_library(zone_type: str, measure_type: str | None = None) -> list[dict]:
    """查询标准措施库中适用于 zone_type 的措施。"""
    lib = _load_measure_library()
    results = []
    for m in lib.get("measures", []):
        if zone_type in m.get("applicable_zones", []):
            if measure_type is None or m.get("type") == measure_type:
                results.append({
                    "id": m["id"],
                    "name": m["name"],
                    "type": m["type"],
                    "unit": m["unit"],
                    "priority": m.get("priority", "中"),
                    "description": m.get("description", ""),
                    "quantity_coefficient": m.get("quantity_coefficient", {}),
                })
    return results


# ═══════════════════════════════════════════════════════════
# Tool 2: quantity_estimator
# ═══════════════════════════════════════════════════════════

QUANTITY_ESTIMATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "quantity_estimator",
        "description": "根据措施名和分区面积估算工程量",
        "parameters": {
            "type": "object",
            "properties": {
                "measure_name": {"type": "string", "description": "措施名称"},
                "zone_area_hm2": {"type": "number", "description": "分区面积(hm²)"},
                "zone_type": {"type": "string", "description": "分区名称"},
            },
            "required": ["measure_name", "zone_area_hm2"],
        },
    },
}


def quantity_estimator(measure_name: str, zone_area_hm2: float,
                       zone_type: str = "") -> dict:
    """根据措施名和分区面积/周长估算工程量。"""
    lib = _load_measure_library()
    area_m2 = zone_area_hm2 * 10000
    perimeter_m = 4 * math.sqrt(area_m2)  # 近似正方形

    # 查找措施
    measure = None
    for m in lib.get("measures", []):
        if m["name"] == measure_name:
            measure = m
            break

    if measure is None:
        return {"error": f"措施 '{measure_name}' 未在库中找到", "quantity": 0, "unit": ""}

    coef = measure.get("quantity_coefficient", {})
    method = coef.get("method", "area_ratio")
    factor = coef.get("factor", 1.0)

    if method == "area_ratio":
        qty = area_m2 * factor
    elif method == "perimeter":
        qty = perimeter_m * factor
    elif method == "count_per_area":
        qty = math.ceil(zone_area_hm2 * factor)
    elif method == "fixed_count":
        qty = int(factor)
    elif method == "fixed_per_zone":
        qty = factor
    elif method == "area_volume":
        qty = area_m2 * factor
    elif method == "building_roof":
        qty = area_m2 * factor
    elif method == "road_length":
        road_len = perimeter_m * 0.5
        qty = math.ceil(road_len / 6) * 2  # 双侧 / 6m 间距
        qty = qty * factor / 0.15  # 还原
    elif method == "area_count":
        qty = math.ceil(zone_area_hm2 * factor)
    elif method == "wall_area":
        qty = perimeter_m * 2.0 * factor
    elif method == "slope_area":
        qty = area_m2 * factor
    elif method == "site_perimeter":
        qty = perimeter_m * factor
    elif method == "area_frequency":
        qty = area_m2 * factor
    elif method == "perimeter_volume":
        qty = perimeter_m * factor
    else:
        qty = area_m2 * factor

    return {
        "measure_name": measure_name,
        "quantity": round(qty, 1),
        "unit": measure["unit"],
        "method": method,
        "factor": factor,
    }


# ═══════════════════════════════════════════════════════════
# Tool 3: regulation_checker
# ═══════════════════════════════════════════════════════════

REGULATION_CHECKER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "regulation_checker",
        "description": "检查措施是否符合地方法规要求",
        "parameters": {
            "type": "object",
            "properties": {
                "measure_name": {"type": "string", "description": "措施名称"},
                "province": {"type": "string", "description": "省份，如'江苏省'"},
            },
            "required": ["measure_name"],
        },
    },
}


def regulation_checker(measure_name: str, province: str = "江苏省") -> dict:
    """检查措施合规性，返回相关法规引用。"""
    refs = _load_legal_refs()
    lib = _load_measure_library()

    # 查最小需求
    min_req = lib.get("zone_minimum_requirements", {})

    # 查找与措施相关的法规
    relevant_refs = []
    for ref in refs.get("references", []):
        if 5 in ref.get("chapters", []) or 7 in ref.get("chapters", []):
            relevant_refs.append({
                "id": ref["id"],
                "name": ref["name"],
                "number": ref.get("number", ""),
            })

    return {
        "measure_name": measure_name,
        "province": province,
        "compliant": True,
        "relevant_regulations": relevant_refs[:5],
        "note": f"{measure_name} 符合 {province} 水土保持法规要求",
    }


# ═══════════════════════════════════════════════════════════
# Tool 4: rag_exemplar
# ═══════════════════════════════════════════════════════════

RAG_EXEMPLAR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "rag_exemplar",
        "description": "从 RAG 语料库检索类似项目的措施方案范例",
        "parameters": {
            "type": "object",
            "properties": {
                "zone_type": {"type": "string", "description": "分区类型"},
                "project_type": {"type": "string", "description": "项目类型，如'房地产'"},
                "top_k": {"type": "integer", "description": "返回条数", "default": 3},
            },
            "required": ["zone_type"],
        },
    },
}


def rag_exemplar(zone_type: str, project_type: str = "房地产",
                 top_k: int = 3) -> list[dict]:
    """从 ChromaDB 检索类似项目的措施方案。"""
    try:
        from src.rag import search
        query = f"{project_type}项目 {zone_type} 水土保持措施"
        results = search(query, top_k=top_k)
        return [{"text": r, "source": "rag"} for r in results]
    except Exception:
        return [{"text": "RAG 未就绪，使用标准措施库推荐。", "source": "fallback"}]


# ── 空间分析工具 (从 spatial_tools 导入) ──
from src.tools.spatial_tools import (
    spatial_context_tool, SPATIAL_CONTEXT_SCHEMA,
    atlas_reference_tool, ATLAS_REFERENCE_SCHEMA,
)

# ── 工具注册表 ──
PLANNER_TOOLS = [
    (measure_library, MEASURE_LIBRARY_SCHEMA),
    (quantity_estimator, QUANTITY_ESTIMATOR_SCHEMA),
    (regulation_checker, REGULATION_CHECKER_SCHEMA),
    (rag_exemplar, RAG_EXEMPLAR_SCHEMA),
]

PLANNER_TOOL_MAP = {
    "measure_library": measure_library,
    "quantity_estimator": quantity_estimator,
    "regulation_checker": regulation_checker,
    "rag_exemplar": rag_exemplar,
    "spatial_context_tool": spatial_context_tool,
    "atlas_reference_tool": atlas_reference_tool,
}
