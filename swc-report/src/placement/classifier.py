"""措施分类器 + 策略路由。

从 placement_engine.py 提取，保持行为一致。
"""

from __future__ import annotations

from .types import (
    MeasureType, Strategy,
    TYPE_KEYWORDS, UNIT_TYPE_MAP, STRATEGY_RULES,
)


def classify_measure(name: str, unit: str = "") -> MeasureType:
    """分类措施为 LINE/AREA/POINT/OVERLAY。

    3 级回退: 关键词 → 单位推断 → 默认 AREA。
    """
    # Level 1: 关键词匹配
    for keywords, mtype in TYPE_KEYWORDS:
        for kw in keywords:
            if kw in name:
                return mtype

    # Level 2: 单位推断
    if unit:
        for u, mtype in UNIT_TYPE_MAP.items():
            if u in unit:
                return mtype

    # Level 3: 默认为 AREA (面积措施最常见)
    return MeasureType.AREA


def route_strategy(name: str, measure_type: MeasureType) -> Strategy:
    """根据措施名选择布置策略。"""
    # Level 1: 关键词匹配
    for keywords, strategy in STRATEGY_RULES:
        for kw in keywords:
            if kw in name:
                return strategy

    # Level 2: 按类型默认策略
    defaults = {
        MeasureType.LINE: Strategy.EDGE_FOLLOW,
        MeasureType.AREA: Strategy.AREA_FILL,
        MeasureType.POINT: Strategy.POINT_AT,
        MeasureType.OVERLAY: Strategy.OVERLAY,
    }
    return defaults.get(measure_type, Strategy.AREA_FILL)
