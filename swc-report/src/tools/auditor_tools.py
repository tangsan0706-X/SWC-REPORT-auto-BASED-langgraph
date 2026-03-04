"""审计智能体工具 — 3 个函数。

工具列表:
  1. numeric_validator  — Python 硬逻辑数值校验
  2. text_validator     — LLM 调用逐章检查 (简化版)
  3. rag_comparator     — ChromaDB 范文结构对比
"""

from __future__ import annotations

import re
from typing import Any

from src.context import get_state_or_none


# ═══════════════════════════════════════════════════════════
# Tool 1: numeric_validator
# ═══════════════════════════════════════════════════════════

NUMERIC_VALIDATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "numeric_validator",
        "description": "校验计算结果、模板标签和报告文本之间的数值一致性",
        "parameters": {
            "type": "object",
            "properties": {
                "check_scope": {
                    "type": "string",
                    "enum": ["all", "earthwork", "erosion", "cost", "benefit"],
                    "description": "校验范围",
                    "default": "all",
                },
            },
        },
    },
}


def numeric_validator(check_scope: str = "all") -> dict:
    """Python 硬逻辑校验数值一致性。"""
    _state = get_state_or_none()
    if _state is None:
        return {"pass": False, "errors": ["State 未初始化"]}

    errors = []
    calc = _state.Calc
    tpl = _state.TplCtx

    # ── 土方平衡校验 ──
    if check_scope in ("all", "earthwork"):
        ew = calc.earthwork
        if ew:
            # 余方 = (挖方-剥离) - (填方-回覆)
            expected_surplus = (ew["excavation_m3"] - ew["topsoil_strip_m3"]) - \
                               (ew["fill_m3"] - ew["topsoil_backfill_m3"])
            if abs(ew.get("surplus_m3", 0) - expected_surplus) > 0.01:
                errors.append(f"土方余方不一致: calc={ew.get('surplus_m3')}, expected={expected_surplus}")

            # 检查 TplCtx
            if tpl.get("ew_surplus") and str(int(expected_surplus)) != tpl["ew_surplus"]:
                errors.append(f"TplCtx ew_surplus 不匹配: {tpl['ew_surplus']} vs {int(expected_surplus)}")

    # ── 侵蚀预测校验 ──
    if check_scope in ("all", "erosion"):
        ep = calc.erosion_df
        if ep:
            # 总预测 = s1+s2+s3
            pp = ep.get("period_pred", {})
            expected_total = sum(pp.values())
            if abs(ep.get("total_pred", 0) - expected_total) > 0.1:
                errors.append(f"侵蚀预测总量不一致: {ep['total_pred']} vs {expected_total:.2f}")

            # 新增 = 预测 - 背景
            if abs(ep.get("total_new", 0) - (ep.get("total_pred", 0) - ep.get("total_bg", 0))) > 0.1:
                errors.append("新增流失量 ≠ 预测 - 背景")

    # ── 造价校验 ──
    if check_scope in ("all", "cost"):
        cs = calc.cost_summary
        if cs:
            # 一~三部分合计
            expected_123 = cs.get("c1_total", 0) + cs.get("c2_total", 0) + cs.get("c3_total", 0)
            if abs(cs.get("c123_total", 0) - expected_123) > 0.01:
                errors.append(f"一~三部分合计不一致: {cs['c123_total']} vs {expected_123:.2f}")

            # 总投资
            expected_grand = cs.get("c1234_total", 0) + cs.get("c_contingency", 0) + cs.get("c_compensation", 0)
            if abs(cs.get("c_grand_total", 0) - expected_grand) > 0.01:
                errors.append(f"总投资不一致: {cs['c_grand_total']} vs {expected_grand:.2f}")

    # ── 效益校验 ──
    if check_scope in ("all", "benefit"):
        bf = calc.benefit
        if bf and bf.get("indicators"):
            for name, ind in bf["indicators"].items():
                if ind.get("met") is False:
                    errors.append(f"效益指标未达标: {name} = {ind['actual']} < {ind['target']}")

    return {
        "pass": len(errors) == 0,
        "errors": errors,
        "checks_performed": check_scope,
    }


# ═══════════════════════════════════════════════════════════
# Tool 2: text_validator
# ═══════════════════════════════════════════════════════════

TEXT_VALIDATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "text_validator",
        "description": "检查章节文本的质量:长度、数字引用、法规引用等",
        "parameters": {
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节编号"},
            },
            "required": ["chapter_id"],
        },
    },
}


def text_validator(chapter_id: str) -> dict:
    """检查指定章节文本的质量。"""
    _state = get_state_or_none()
    if _state is None:
        return {"pass": False, "errors": ["State 未初始化"]}

    draft = _state.Draft
    tpl = _state.TplCtx
    legal = _state.Static.legal_refs

    errors = []
    warnings = []

    # 找到该章节所有标签的文本
    # 提取章节号：从 "chapter8_1_组织管理" 或 "ch8" 中提取 "8"
    ch_match = re.match(r"(?:chapter|ch)(\d+)", chapter_id)
    ch_num = ch_match.group(1) if ch_match else "".join(filter(str.isdigit, chapter_id))
    ch_prefix = f"chapter{ch_num}"
    chapter_texts = {k: v for k, v in draft.items() if k.startswith(ch_prefix)}

    if not chapter_texts:
        errors.append(f"章节 {chapter_id} 无文本内容")
        return {"pass": False, "errors": errors, "warnings": warnings}

    full_text = "\n".join(chapter_texts.values())

    # 1. 长度检查
    if len(full_text) < 200:
        errors.append(f"章节 {chapter_id} 文本过短: {len(full_text)} 字")
    elif len(full_text) < 500:
        warnings.append(f"章节 {chapter_id} 文本较短: {len(full_text)} 字")

    # 2. 数字引用检查: 文本中的关键数字是否正确
    money_refs = re.findall(r"([\d.]+)\s*万元", full_text)
    for val in money_refs:
        # 检查是否在 TplCtx 中有对应值
        found = False
        for k, v in tpl.items():
            if str(v) == val:
                found = True
                break
        if not found and float(val) > 1.0:
            warnings.append(f"金额 {val}万元 未在计算结果中找到对应值")

    # 3. 法规引用检查 (仅第1、5、7章)
    if ch_num in ("1", "5", "7"):
        chapter_refs = legal.get("chapter_mapping", {}).get(ch_num, [])
        ref_map = {r["id"]: r["name"] for r in legal.get("references", [])}
        for ref_id in chapter_refs[:3]:
            ref_name = ref_map.get(ref_id, "")
            if ref_name and ref_name not in full_text:
                warnings.append(f"章节{ch_num}应引用: {ref_name}")

    return {
        "pass": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "chapter_id": chapter_id,
        "text_length": len(full_text),
    }


# ═══════════════════════════════════════════════════════════
# Tool 3: rag_comparator
# ═══════════════════════════════════════════════════════════

RAG_COMPARATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "rag_comparator",
        "description": "将生成的报告与 RAG 范文进行结构对比",
        "parameters": {
            "type": "object",
            "properties": {
                "chapter_id": {
                    "type": "string",
                    "description": "要对比的章节编号，如'ch5'，留空对比全文",
                    "default": "",
                },
            },
        },
    },
}


def rag_comparator(chapter_id: str = "") -> dict:
    """与 RAG 范文进行结构对比。"""
    _state = get_state_or_none()
    if _state is None:
        return {"similarity": 0, "issues": ["State 未初始化"]}

    draft = _state.Draft
    issues = []

    # 检查每章是否都有内容
    expected_chapters = [
        "chapter1", "chapter2", "chapter3", "chapter4",
        "chapter5", "chapter6", "chapter7", "chapter8",
    ]

    missing = []
    for ch in expected_chapters:
        has_content = any(k.startswith(ch) and v for k, v in draft.items())
        if not has_content:
            missing.append(ch)

    if missing:
        issues.append(f"缺少章节内容: {', '.join(missing)}")

    # 尝试 RAG 检索对比
    try:
        from src.rag import search
        if chapter_id:
            ch_num = "".join(filter(str.isdigit, chapter_id))
            ch_prefix = f"chapter{ch_num}"
            ch_texts = [v for k, v in draft.items() if k.startswith(ch_prefix) and v]
            if ch_texts:
                exemplars = search(ch_texts[0][:200], chapter_id=chapter_id, top_k=1)
                if exemplars:
                    issues.append(f"RAG 对比: 找到 {len(exemplars)} 条范文参考")
    except Exception:
        pass

    # 评分: 基于完整性
    completeness = 1.0 - len(missing) / len(expected_chapters)
    score = round(completeness * 100, 1)

    return {
        "similarity_score": score,
        "missing_chapters": missing,
        "issues": issues,
    }


# ── 工具注册表 ──
AUDITOR_TOOLS = [
    (numeric_validator, NUMERIC_VALIDATOR_SCHEMA),
    (text_validator, TEXT_VALIDATOR_SCHEMA),
    (rag_comparator, RAG_COMPARATOR_SCHEMA),
]

AUDITOR_TOOL_MAP = {
    "numeric_validator": numeric_validator,
    "text_validator": text_validator,
    "rag_comparator": rag_comparator,
}
