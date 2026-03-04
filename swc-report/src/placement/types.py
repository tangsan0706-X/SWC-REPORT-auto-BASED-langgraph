"""措施布置引擎 — 类型定义、枚举与常量表。

所有数据类和枚举集中管理，避免循环导入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 措施类型 (4大类)
# ═══════════════════════════════════════════════════════════════

class MeasureType(Enum):
    LINE = "line"
    AREA = "area"
    POINT = "point"
    OVERLAY = "overlay"


# ═══════════════════════════════════════════════════════════════
# 布置策略 (7种)
# ═══════════════════════════════════════════════════════════════

class Strategy(Enum):
    EDGE_FOLLOW = "edge_follow"           # 沿分区边线偏移布置
    BOUNDARY_FOLLOW = "boundary_follow"   # 沿项目边界内缩布置
    AREA_FILL = "area_fill"               # 缩进填充
    AREA_COVER = "area_cover"             # 全覆盖分区多边形
    POINT_AT = "point_at"                 # POI 附近
    POINT_ALONG = "point_along"           # 沿线均匀分布
    OVERLAY = "overlay"                   # 叠加在建筑上方


# ═══════════════════════════════════════════════════════════════
# 联动关系类型
# ═══════════════════════════════════════════════════════════════

class LinkageType(Enum):
    DOWNSTREAM = "downstream"   # 上游→下游 (排水沟→沉砂池)
    UPSTREAM = "upstream"       # 下游→上游 (雨水收集池→沉砂池)
    ADJACENT = "adjacent"       # 紧邻 (洗车平台→三级沉淀池)
    PERIMETER = "perimeter"     # 围绕 (防尘网苫盖→截水沟)


# ═══════════════════════════════════════════════════════════════
# PlacementResult — 布置结果
# ═══════════════════════════════════════════════════════════════

@dataclass
class PlacementResult:
    """单个措施的布置结果。"""
    measure_name: str = ""
    zone_id: str = ""
    measure_type: MeasureType = MeasureType.AREA
    strategy: Strategy = Strategy.AREA_FILL
    polyline: Optional[List[Tuple[float, float]]] = None
    polygon: Optional[List[Tuple[float, float]]] = None
    points: Optional[List[Tuple[float, float]]] = None
    label_anchor: Optional[Tuple[float, float]] = None
    skipped: bool = False
    skip_reason: str = ""
    # v2: 联动字段
    linked_to: Optional[List[str]] = None
    linkage_lines: Optional[List[List[Tuple[float, float]]]] = None
    # v2: 水文信息
    hydro_info: Optional[Dict[str, Any]] = None

    def to_legacy_dict(self) -> dict:
        """转换为旧 MeasurePlacementResolver 格式。"""
        result: Dict[str, Any] = {
            "strategy": self.strategy.value,
            "measure_type": self.measure_type.value,
        }
        if self.polyline:
            result["polyline"] = self.polyline
        if self.polygon:
            result["polygon"] = self.polygon
        if self.points:
            result["points"] = self.points
        if self.label_anchor:
            result["label_anchor"] = self.label_anchor
        if self.skipped:
            result["skipped"] = True
            result["skip_reason"] = self.skip_reason
        if self.linked_to:
            result["linked_to"] = self.linked_to
        if self.linkage_lines:
            result["linkage_lines"] = self.linkage_lines
        return result


# ═══════════════════════════════════════════════════════════════
# 关键词分类表
# ═══════════════════════════════════════════════════════════════

# 30+ 关键词规则
TYPE_KEYWORDS: list[tuple[list[str], MeasureType]] = [
    # LINE 类型
    (["排水沟", "截水沟", "挡土墙", "护坡", "围墙", "围挡", "管网",
      "雨水管", "护栏", "拦挡", "临时排水", "边沟", "急流槽", "跌水",
      "导流沟", "排洪沟", "挡水墙", "浆砌石"], MeasureType.LINE),
    # AREA 类型
    (["绿化", "草皮", "透水砖", "覆土", "覆盖", "防尘网", "土工布",
      "植被恢复", "绿地", "草坪", "植草", "液力喷播", "草籽", "撒播",
      "铺装", "硬化", "表土剥离", "表土回覆", "密目网", "彩条布",
      "安全网", "苫盖"], MeasureType.AREA),
    # POINT 类型
    (["沉沙池", "沉淀池", "蓄水池", "冲洗台", "监测点", "冲洗平台",
      "洗车台", "洗车池", "检查井", "雨水口", "集水井"], MeasureType.POINT),
    # OVERLAY 类型
    (["屋顶绿化", "临时硬化", "路面硬化"], MeasureType.OVERLAY),
]

# 单位推断
UNIT_TYPE_MAP = {
    "m": MeasureType.LINE,
    "米": MeasureType.LINE,
    "m²": MeasureType.AREA,
    "平方米": MeasureType.AREA,
    "hm²": MeasureType.AREA,
    "公顷": MeasureType.AREA,
    "座": MeasureType.POINT,
    "个": MeasureType.POINT,
    "台": MeasureType.POINT,
    "处": MeasureType.POINT,
}

# 措施关键词 → 策略路由
STRATEGY_RULES: list[tuple[list[str], Strategy]] = [
    (["排水沟", "截水沟", "管网", "雨水管", "边沟", "导流沟", "排洪沟",
      "急流槽"], Strategy.EDGE_FOLLOW),
    (["围挡", "围墙", "护栏", "拦挡", "临时排水"], Strategy.BOUNDARY_FOLLOW),
    (["绿化", "草皮", "植草", "液力喷播", "草籽", "撒播",
      "植被恢复"], Strategy.AREA_FILL),
    (["透水", "铺装", "硬化", "覆盖", "土工布", "密目网", "彩条布",
      "安全网", "苫盖", "防尘网", "表土剥离", "表土回覆",
      "覆土"], Strategy.AREA_COVER),
    (["沉沙池", "沉淀池", "蓄水池", "冲洗台", "冲洗平台", "洗车台",
      "洗车池", "检查井", "集水井"], Strategy.POINT_AT),
    (["监测点", "行道树", "乔木", "雨水口"], Strategy.POINT_ALONG),
    (["屋顶绿化"], Strategy.OVERLAY),
]

# ═══════════════════════════════════════════════════════════════
# 碰撞距离规则
# ═══════════════════════════════════════════════════════════════

# (措施A关键词, 措施B关键词, 最小距离m)
DISTANCE_RULES: list[tuple[str, str, float]] = [
    ("沉沙池", "建筑", 5.0),
    ("沉淀池", "建筑", 5.0),
    ("洗车", "建筑", 10.0),
    ("冲洗", "建筑", 10.0),
    ("排水沟", "建筑", 3.0),
    ("截水沟", "建筑", 3.0),
    ("行道树", "建筑", 3.0),
    ("沉沙池", "沉沙池", 20.0),
    ("沉淀池", "沉淀池", 20.0),
    ("排水沟", "截水沟", 5.0),
    ("围挡", "建筑", 2.0),
    ("监测点", "建筑", 5.0),
    ("雨水收集", "建筑", 8.0),
]

# (措施A关键词, 措施B关键词) — 互斥，不可在同一位置
EXCLUSION_RULES: list[tuple[str, str]] = [
    ("防尘网", "绿化"),
    ("排水沟", "截水沟"),
    ("苫盖", "绿化"),
    ("表土回覆", "硬化"),
]

# ═══════════════════════════════════════════════════════════════
# 水文断面选型表
# ═══════════════════════════════════════════════════════════════

# (汇水面积上限hm², 宽度m, 深度m, 描述)
DITCH_SIZE_TABLE: list[tuple[float, float, float, str]] = [
    (0.5, 0.3, 0.3, "小型梯形断面 0.3×0.3m"),
    (2.0, 0.4, 0.4, "标准梯形断面 0.4×0.4m"),
    (5.0, 0.5, 0.5, "中型梯形断面 0.5×0.5m"),
    (10.0, 0.6, 0.6, "大型梯形断面 0.6×0.6m"),
    (float("inf"), 0.8, 0.8, "特大梯形断面 0.8×0.8m"),
]

# (汇水面积上限hm², 长m, 宽m, 深m, 描述)
BASIN_SIZE_TABLE: list[tuple[float, float, float, float, str]] = [
    (1.0, 2.0, 1.5, 1.0, "小型沉砂池 2.0×1.5×1.0m"),
    (3.0, 3.0, 2.0, 1.5, "标准沉砂池 3.0×2.0×1.5m"),
    (8.0, 4.0, 3.0, 1.5, "中型沉砂池 4.0×3.0×1.5m"),
    (15.0, 5.0, 4.0, 2.0, "大型沉砂池 5.0×4.0×2.0m"),
    (float("inf"), 6.0, 5.0, 2.0, "特大沉砂池 6.0×5.0×2.0m"),
]

# 联动规则表
# (源措施关键词, 目标措施关键词, 联动类型, 自动创建)
LINKAGE_RULES: list[tuple[str, str, LinkageType, bool]] = [
    ("排水沟", "沉砂池", LinkageType.DOWNSTREAM, True),
    ("截水沟", "沉砂池", LinkageType.DOWNSTREAM, True),
    ("临时排水沟", "临时沉砂池", LinkageType.DOWNSTREAM, True),
    ("洗车", "三级沉淀池", LinkageType.ADJACENT, True),
    ("冲洗", "三级沉淀池", LinkageType.ADJACENT, True),
    ("防尘网", "截水沟", LinkageType.PERIMETER, True),
    ("苫盖", "临时排水沟", LinkageType.PERIMETER, True),
    ("沉砂池", "雨水管网", LinkageType.DOWNSTREAM, False),
    ("雨水收集", "沉砂池", LinkageType.UPSTREAM, False),
]
