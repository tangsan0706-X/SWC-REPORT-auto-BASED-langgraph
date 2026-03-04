"""数据适配器工具 — 6 个函数。

工具列表:
  1. validate_completeness  — 遍历必填标签，检查完整性
  2. validate_cross_refs    — 交叉数值校验（土方/侵蚀/造价）
  3. rerun_calculator       — 重新执行指定计算器
  4. callback_planner       — 重新执行措施规划师
  5. reassemble             — 重新执行状态装配器
  6. get_fix_suggestion     — 根据缺失类别推导修复动作链
"""

from __future__ import annotations

import logging
from typing import Any

from src.context import get_state_or_none

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 必填标签 Schema
# ═══════════════════════════════════════════════════════════

REQUIRED_TAGS: dict[str, list[tuple[str, str]]] = {
    "project_meta": [
        ("project_name", "non_empty"),
        ("city", "non_empty"),
        ("total_investment", "positive_number"),
        ("total_land", "positive_number"),
        ("construction_unit", "non_empty"),
        ("start_date", "non_empty"),
        ("end_date", "non_empty"),
    ],
    "zone_areas": [
        ("z_total", "positive_number"),
        ("z_建构筑物区", "positive_number"),
    ],
    "earthwork": [
        ("ew_dig", "non_negative_number"),
        ("ew_fill", "non_negative_number"),
        ("ew_strip", "non_negative_number"),
        ("ew_surplus", "number"),
    ],
    "erosion": [
        ("ep_total_pred", "positive_number"),
        ("ep_total_bg", "non_negative_number"),
        ("ep_total_new", "non_negative_number"),
        ("ep_s1_pred", "non_negative_number"),
        ("ep_s2_pred", "non_negative_number"),
        ("ep_s3_pred", "non_negative_number"),
    ],
    "measures_def": [
        ("def_eng_yes", "non_empty"),
        ("def_veg_yes", "non_empty"),
    ],
    "measures_layout": [
        ("lo_主体_eng_exist", "non_empty"),
    ],
    "cost": [
        ("c_grand_total", "positive_number"),
        ("c123_total", "positive_number"),
        ("c1_total", "non_negative_number"),
        ("c2_total", "non_negative_number"),
        ("c3_total", "non_negative_number"),
        ("c4_total", "non_negative_number"),
    ],
    "ch1_summary": [
        ("total_swc_investment", "positive_number"),
    ],
    "benefit": [
        ("t_治理度", "non_empty"),
        ("r_治理度", "non_empty"),
        ("ok_治理度", "valid_status"),
        ("t_控制比", "non_empty"),
        ("r_控制比", "non_empty"),
        ("ok_控制比", "valid_status"),
        ("t_渣土防护率", "non_empty"),
        ("r_渣土防护率", "non_empty"),
        ("ok_渣土防护率", "valid_status"),
        ("t_表土保护率", "non_empty"),
        ("r_表土保护率", "non_empty"),
        ("ok_表土保护率", "valid_status"),
        ("t_植被恢复率", "non_empty"),
        ("r_植被恢复率", "non_empty"),
        ("ok_植被恢复率", "valid_status"),
        ("t_覆盖率", "non_empty"),
        ("r_覆盖率", "non_empty"),
        ("ok_覆盖率", "valid_status"),
    ],
    "loop_tables": [
        ("land_use_table", "non_empty_list"),
        ("erosion_table", "non_empty_list"),
        ("cost_detail_table", "list"),
    ],
}

# 回调依赖映射: category → 修复所需 calculator/planner
_CALLBACK_MAP: dict[str, str | None] = {
    "project_meta": None,       # 用户输入，不可回调
    "zone_areas": None,         # 用户输入
    "earthwork": "earthwork",
    "erosion": "erosion",
    "measures_def": "planner",
    "measures_layout": "planner",
    "cost": "cost",
    "ch1_summary": "cost",      # 派生自 cost
    "benefit": "benefit",
    "loop_tables": None,        # 依赖上游修复
}

# 修复依赖链: 执行某个回调前需先完成哪些前置
_FIX_DEPENDENCIES: dict[str, list[str]] = {
    "planner": [],
    "earthwork": [],
    "erosion": [],
    "cost": ["planner"],
    "benefit": ["cost"],
}


# ═══════════════════════════════════════════════════════════
# 校验辅助
# ═══════════════════════════════════════════════════════════

def _check_tag(value: Any, rule: str) -> bool:
    """根据规则检查单个标签值。"""
    if rule == "non_empty":
        return value is not None and str(value).strip() not in ("", "无", "未计算")
    elif rule == "positive_number":
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return False
    elif rule == "non_negative_number":
        try:
            return float(value) >= 0
        except (TypeError, ValueError):
            return False
    elif rule == "number":
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False
    elif rule == "valid_status":
        return value is not None and str(value).strip() not in ("", "未计算")
    elif rule == "non_empty_list":
        return isinstance(value, list) and len(value) > 0
    elif rule == "list":
        return isinstance(value, list)
    return True


# ═══════════════════════════════════════════════════════════
# Tool 1: validate_completeness
# ═══════════════════════════════════════════════════════════

VALIDATE_COMPLETENESS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "validate_completeness",
        "description": "遍历 REQUIRED_TAGS，检查 TplCtx 中所有必填标签的完整性，返回各类别状态",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}


def validate_completeness() -> dict:
    """遍历 REQUIRED_TAGS，检查 TplCtx，返回各类别状态。"""
    _state = get_state_or_none()
    if _state is None:
        return {"error": "State 未初始化"}

    tpl = _state.TplCtx
    categories: dict[str, dict] = {}
    total_checked = 0
    total_valid = 0
    total_missing = 0

    for cat, tags in REQUIRED_TAGS.items():
        missing_tags = []
        for tag_name, rule in tags:
            total_checked += 1
            value = tpl.get(tag_name)
            if _check_tag(value, rule):
                total_valid += 1
            else:
                missing_tags.append({
                    "tag": tag_name,
                    "rule": rule,
                    "current_value": str(value) if value is not None else None,
                })
                total_missing += 1

        categories[cat] = {
            "status": "ok" if not missing_tags else "missing",
            "total": len(tags),
            "valid": len(tags) - len(missing_tags),
            "missing_tags": missing_tags,
        }

    return {
        "categories": categories,
        "summary": {
            "total_checked": total_checked,
            "total_valid": total_valid,
            "total_missing": total_missing,
        },
    }


# ═══════════════════════════════════════════════════════════
# Tool 2: validate_cross_refs
# ═══════════════════════════════════════════════════════════

VALIDATE_CROSS_REFS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "validate_cross_refs",
        "description": "交叉数值校验: 土方余额公式、侵蚀合计、造价合计等一致性检查",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}


def validate_cross_refs() -> dict:
    """交叉数值校验。"""
    _state = get_state_or_none()
    if _state is None:
        return {"pass": False, "errors": ["State 未初始化"]}

    errors = []
    calc = _state.Calc

    # 土方余额
    ew = calc.earthwork
    if ew:
        expected = (ew.get("excavation_m3", 0) - ew.get("topsoil_strip_m3", 0)) - \
                   (ew.get("fill_m3", 0) - ew.get("topsoil_backfill_m3", 0))
        if abs(ew.get("surplus_m3", 0) - expected) > 0.01:
            errors.append(f"土方余方不一致: {ew.get('surplus_m3')} vs expected {expected}")

    # 侵蚀合计
    ep = calc.erosion_df
    if ep:
        pp = ep.get("period_pred", {})
        expected_total = sum(pp.values())
        if abs(ep.get("total_pred", 0) - expected_total) > 0.1:
            errors.append(f"侵蚀总量不一致: {ep.get('total_pred')} vs {expected_total:.2f}")

        if abs(ep.get("total_new", 0) - (ep.get("total_pred", 0) - ep.get("total_bg", 0))) > 0.1:
            errors.append("新增流失量 ≠ 预测 - 背景")

    # 造价合计
    cs = calc.cost_summary
    if cs:
        expected_123 = cs.get("c1_total", 0) + cs.get("c2_total", 0) + cs.get("c3_total", 0)
        if abs(cs.get("c123_total", 0) - expected_123) > 0.01:
            errors.append(f"一~三部分合计不一致: {cs.get('c123_total')} vs {expected_123:.2f}")

        expected_grand = cs.get("c1234_total", 0) + cs.get("c_contingency", 0) + cs.get("c_compensation", 0)
        if abs(cs.get("c_grand_total", 0) - expected_grand) > 0.01:
            errors.append(f"总投资不一致: {cs.get('c_grand_total')} vs {expected_grand:.2f}")

    return {
        "pass": len(errors) == 0,
        "errors": errors,
    }


# ═══════════════════════════════════════════════════════════
# Tool 3: rerun_calculator
# ═══════════════════════════════════════════════════════════

RERUN_CALCULATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "rerun_calculator",
        "description": "重新执行指定计算器: earthwork / erosion / cost / benefit",
        "parameters": {
            "type": "object",
            "properties": {
                "calculator_name": {
                    "type": "string",
                    "enum": ["earthwork", "erosion", "cost", "benefit"],
                    "description": "要重新执行的计算器名称",
                },
            },
            "required": ["calculator_name"],
        },
    },
}


def rerun_calculator(calculator_name: str) -> dict:
    """重新执行指定计算器。"""
    _state = get_state_or_none()
    if _state is None:
        return {"success": False, "error": "State 未初始化"}

    try:
        if calculator_name == "earthwork":
            from src.calculators.earthwork import calc_earthwork
            result = calc_earthwork(_state)
            logger.info(f"[适配器] 重跑 earthwork: surplus={result.get('surplus_m3')}")
        elif calculator_name == "erosion":
            from src.calculators.erosion import calc_erosion
            result = calc_erosion(_state)
            logger.info(f"[适配器] 重跑 erosion: total_pred={result.get('total_pred')}")
        elif calculator_name == "cost":
            from src.calculators.cost import calc_cost
            result = calc_cost(_state)
            logger.info(f"[适配器] 重跑 cost: grand_total={result.get('c_grand_total')}")
        elif calculator_name == "benefit":
            from src.calculators.benefit import calc_benefit
            result = calc_benefit(_state)
            logger.info(f"[适配器] 重跑 benefit: all_met={result.get('all_met')}")
        else:
            return {"success": False, "error": f"未知计算器: {calculator_name}"}

        return {"success": True, "calculator": calculator_name}
    except Exception as e:
        logger.error(f"[适配器] 重跑 {calculator_name} 失败: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════
# Tool 4: callback_planner
# ═══════════════════════════════════════════════════════════

CALLBACK_PLANNER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "callback_planner",
        "description": "重新执行 Planner Agent 补充缺失措施",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}


def callback_planner() -> dict:
    """重新执行 Planner — 非 LLM 模式用默认措施。"""
    _state = get_state_or_none()
    if _state is None:
        return {"success": False, "error": "State 未初始化"}

    try:
        # 检查是否已有 planned 措施
        existing_planned = [m for m in _state.Measures if m.get("source") == "planned"]
        if existing_planned:
            logger.info(f"[适配器] 已有 {len(existing_planned)} 条规划措施，跳过 Planner 回调")
            return {"success": True, "skipped": True, "reason": "已有规划措施"}

        from src.agents.planner import _default_measures
        new_measures = _default_measures()
        for m in new_measures:
            m["source"] = "planned"
            _state.Measures.append(m)

        logger.info(f"[适配器] Planner 回调: 新增 {len(new_measures)} 条默认措施")
        return {"success": True, "new_measures": len(new_measures)}
    except Exception as e:
        logger.error(f"[适配器] Planner 回调失败: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════
# Tool 5: reassemble
# ═══════════════════════════════════════════════════════════

REASSEMBLE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "reassemble",
        "description": "重新执行状态装配器 (assembler)，更新 TplCtx 中的 229 个模板标签",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}


def reassemble() -> dict:
    """重新执行 assembler 更新 TplCtx。"""
    _state = get_state_or_none()
    if _state is None:
        return {"success": False, "error": "State 未初始化"}

    try:
        from src.assembler import assemble
        ctx = assemble(_state)
        none_count = sum(1 for v in ctx.values() if v is None or v == "")
        logger.info(f"[适配器] reassemble: {len(ctx)} 标签, {none_count} 空值")
        return {"success": True, "total_tags": len(ctx), "empty_tags": none_count}
    except Exception as e:
        logger.error(f"[适配器] reassemble 失败: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════
# Tool 6: get_fix_suggestion
# ═══════════════════════════════════════════════════════════

GET_FIX_SUGGESTION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_fix_suggestion",
        "description": "根据缺失类别推导修复动作链（含依赖顺序）",
        "parameters": {
            "type": "object",
            "properties": {
                "missing_categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "缺失数据的类别列表",
                },
            },
            "required": ["missing_categories"],
        },
    },
}


def get_fix_suggestion(missing_categories: list[str]) -> dict:
    """根据缺失类别推导修复动作链。"""
    actions: list[dict] = []
    added: set[str] = set()

    def _add_action(callback: str):
        """递归添加动作及其依赖。"""
        if callback in added:
            return
        # 先添加依赖
        for dep in _FIX_DEPENDENCIES.get(callback, []):
            _add_action(dep)
        added.add(callback)
        if callback == "planner":
            actions.append({"action": "callback_planner", "target": "planner"})
        else:
            actions.append({"action": "rerun_calculator", "target": callback})

    unfixable = []
    for cat in missing_categories:
        cb = _CALLBACK_MAP.get(cat)
        if cb is None:
            unfixable.append(cat)
        else:
            _add_action(cb)

    # 最后总是 reassemble
    if actions:
        actions.append({"action": "reassemble", "target": "assembler"})

    return {
        "fix_actions": actions,
        "unfixable_categories": unfixable,
        "total_actions": len(actions),
    }


# ═══════════════════════════════════════════════════════════
# 工具注册表
# ═══════════════════════════════════════════════════════════

ADAPTER_TOOLS = [
    (validate_completeness, VALIDATE_COMPLETENESS_SCHEMA),
    (validate_cross_refs, VALIDATE_CROSS_REFS_SCHEMA),
    (rerun_calculator, RERUN_CALCULATOR_SCHEMA),
    (callback_planner, CALLBACK_PLANNER_SCHEMA),
    (reassemble, REASSEMBLE_SCHEMA),
    (get_fix_suggestion, GET_FIX_SUGGESTION_SCHEMA),
]

ADAPTER_TOOL_MAP = {
    "validate_completeness": validate_completeness,
    "validate_cross_refs": validate_cross_refs,
    "rerun_calculator": rerun_calculator,
    "callback_planner": callback_planner,
    "reassemble": reassemble,
    "get_fix_suggestion": get_fix_suggestion,
}
