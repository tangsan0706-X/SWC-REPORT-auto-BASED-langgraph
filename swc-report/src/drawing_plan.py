"""DrawingPlan 数据定义 + JSON 解析 + 校验 + 默认计划生成。

LLM 只输出结构化 JSON 描述"画什么、放哪里"，
渲染引擎 (DrawingRenderer) 负责"怎么画"。

JSON Schema 设计原则:
  - 7B 模型友好: 扁平结构、封闭词汇表、最少必填字段
  - 四层降级: 合法JSON → 修复JSON → 默认计划 → MeasureMapRenderer
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 封闭词汇表
# ═══════════════════════════════════════════════════════════════

MAP_TYPES = {"zone_boundary", "measure_layout", "zone_detail", "typical_section"}

POSITION_VOCAB = {
    "north", "south", "east", "west", "center",
    "northeast", "northwest", "southeast", "southwest",
    "perimeter",
}

DIRECTION_VOCAB = {
    "north-south", "east-west", "clockwise",
    "along-road", "along-boundary",
}

COVERAGE_VOCAB = {"full", "partial", "edge"}

EMPHASIS_VOCAB = {"normal", "highlight"}

# 中文 → 英文映射 (方便 7B 模型输出中文时自动转换)
_POSITION_CN_MAP = {
    "北": "north", "南": "south", "东": "east", "西": "west",
    "中": "center", "中心": "center", "中央": "center",
    "东北": "northeast", "西北": "northwest",
    "东南": "southeast", "西南": "southwest",
    "周边": "perimeter", "周围": "perimeter", "四周": "perimeter",
}

_DIRECTION_CN_MAP = {
    "南北": "north-south", "东西": "east-west",
    "顺时针": "clockwise",
    "沿路": "along-road", "沿道路": "along-road",
    "沿边界": "along-boundary", "沿边": "along-boundary",
}

_COVERAGE_CN_MAP = {
    "全覆盖": "full", "全部": "full",
    "部分": "partial", "局部": "partial",
    "边缘": "edge", "沿边": "edge",
}


# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class ZoneSpec:
    """分区规格。"""
    name: str
    emphasis: str = "normal"  # normal | highlight


@dataclass
class MeasureSpec:
    """措施放置规格。"""
    name: str
    zone: str
    position: str = "center"
    direction: str = "north-south"
    coverage: str = "partial"
    note: str = ""
    # resolver 注入的实际坐标 (程序填充, LLM 不感知)
    cad_coords: list[tuple[float, float]] | None = None
    cad_geom_type: str | None = None  # "polyline" | "polygon" | "points"


@dataclass
class SectionSpec:
    """典型断面规格。"""
    structure: str
    annotation_notes: list[str] = field(default_factory=list)


@dataclass
class DrawingPlan:
    """绘图计划 — LLM 输出的结构化描述。"""
    map_type: str
    title: str
    zones: list[ZoneSpec] = field(default_factory=list)
    measures: list[MeasureSpec] = field(default_factory=list)
    sections: list[SectionSpec] = field(default_factory=list)
    layout_hints: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# JSON 解析 (多层容错)
# ═══════════════════════════════════════════════════════════════

def parse_plan_json(raw: str) -> DrawingPlan | None:
    """多层 JSON 提取: 直接解析 → 代码块提取 → {} 正则 → 修复常见错误。

    Returns:
        DrawingPlan 或 None (完全无法解析时)
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # 尝试 1: 直接解析
    obj = _try_parse(text)
    if obj is not None:
        return _dict_to_plan(obj)

    # 尝试 2: 提取 ```json ... ``` 代码块
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if code_block:
        obj = _try_parse(code_block.group(1).strip())
        if obj is not None:
            return _dict_to_plan(obj)

    # 尝试 3: 提取第一个 {...} 块
    brace_match = _extract_outermost_braces(text)
    if brace_match:
        obj = _try_parse(brace_match)
        if obj is not None:
            return _dict_to_plan(obj)

    # 尝试 4: 修复常见 JSON 错误后重试
    fixed = _fix_common_json_errors(text)
    if fixed != text:
        obj = _try_parse(fixed)
        if obj is not None:
            return _dict_to_plan(obj)
        # 再提取 {}
        brace_match = _extract_outermost_braces(fixed)
        if brace_match:
            obj = _try_parse(brace_match)
            if obj is not None:
                return _dict_to_plan(obj)

    logger.warning("DrawingPlan JSON 解析完全失败")
    return None


def _try_parse(text: str) -> dict | None:
    """尝试 json.loads，失败返回 None。"""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _extract_outermost_braces(text: str) -> str | None:
    """提取最外层的 {} 内容。"""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _fix_common_json_errors(text: str) -> str:
    """修复 LLM 常见 JSON 错误。"""
    # 移除 JavaScript 风格的注释
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    # 移除尾部逗号 (数组/对象最后一项后面)
    text = re.sub(r",\s*([\]}])", r"\1", text)
    # 单引号 → 双引号 (简单替换，不处理嵌套)
    text = text.replace("'", '"')
    # 修复 key 没加引号: {key: "val"} → {"key": "val"}
    text = re.sub(r"(?<=[\{,])\s*(\w+)\s*:", r' "\1":', text)
    return text


def _dict_to_plan(d: dict) -> DrawingPlan:
    """将原始 dict 转换为 DrawingPlan 数据类。"""
    map_type = d.get("map_type", "measure_layout")
    title = d.get("title", "")

    zones = []
    for z in d.get("zones", []):
        if isinstance(z, str):
            zones.append(ZoneSpec(name=z))
        elif isinstance(z, dict):
            zones.append(ZoneSpec(
                name=z.get("name", ""),
                emphasis=z.get("emphasis", "normal"),
            ))

    measures = []
    for m in d.get("measures", []):
        if isinstance(m, dict):
            measures.append(MeasureSpec(
                name=m.get("name", ""),
                zone=m.get("zone", ""),
                position=m.get("position", "center"),
                direction=m.get("direction", "north-south"),
                coverage=m.get("coverage", "partial"),
                note=m.get("note", ""),
            ))

    sections = []
    for s in d.get("sections", []):
        if isinstance(s, dict):
            sections.append(SectionSpec(
                structure=s.get("structure", ""),
                annotation_notes=s.get("annotation_notes", []),
            ))

    layout_hints = d.get("layout_hints", {})
    if not isinstance(layout_hints, dict):
        layout_hints = {}

    return DrawingPlan(
        map_type=map_type,
        title=title,
        zones=zones,
        measures=measures,
        sections=sections,
        layout_hints=layout_hints,
    )


# ═══════════════════════════════════════════════════════════════
# 校验 + 修复
# ═══════════════════════════════════════════════════════════════

def validate_plan(
    plan: DrawingPlan,
    etl_zones: list[dict],
    state_measures: list[dict],
) -> tuple[DrawingPlan, list[str]]:
    """校验并修复 DrawingPlan。

    修复内容:
      - map_type 枚举校验
      - zone 名模糊匹配到实际分区名
      - 措施名模糊匹配到实际措施名
      - position/direction/coverage 枚举校验 + 中文转换

    Returns:
        (修复后的 plan, 警告列表)
    """
    warnings: list[str] = []

    # 1) map_type
    if plan.map_type not in MAP_TYPES:
        warnings.append(f"map_type '{plan.map_type}' 无效, 默认 'measure_layout'")
        plan.map_type = "measure_layout"

    # 2) 构建实际名称表
    real_zone_names = [z.get("name", "") for z in etl_zones]
    real_measure_names = [
        m.get("措施名称", m.get("name", "")) for m in state_measures
    ]

    # 3) 校验 zones
    for zs in plan.zones:
        matched = _fuzzy_match_name(zs.name, real_zone_names)
        if matched and matched != zs.name:
            warnings.append(f"zone '{zs.name}' → '{matched}'")
            zs.name = matched
        if zs.emphasis not in EMPHASIS_VOCAB:
            zs.emphasis = "normal"

    # 4) 校验 measures
    for ms in plan.measures:
        # 措施名匹配
        matched = _fuzzy_match_name(ms.name, real_measure_names)
        if matched and matched != ms.name:
            warnings.append(f"measure '{ms.name}' → '{matched}'")
            ms.name = matched
        # zone 名匹配
        matched_zone = _fuzzy_match_name(ms.zone, real_zone_names)
        if matched_zone and matched_zone != ms.zone:
            ms.zone = matched_zone
        # 枚举校验
        ms.position = _normalize_enum(ms.position, POSITION_VOCAB, _POSITION_CN_MAP, "center")
        ms.direction = _normalize_enum(ms.direction, DIRECTION_VOCAB, _DIRECTION_CN_MAP, "north-south")
        ms.coverage = _normalize_enum(ms.coverage, COVERAGE_VOCAB, _COVERAGE_CN_MAP, "partial")

    # 5) 校验 sections
    from src.measure_symbols import SECTION_TEMPLATES
    for ss in plan.sections:
        matched = _fuzzy_match_name(ss.structure, list(SECTION_TEMPLATES.keys()))
        if matched and matched != ss.structure:
            warnings.append(f"section '{ss.structure}' → '{matched}'")
            ss.structure = matched

    return plan, warnings


def _fuzzy_match_name(candidate: str, targets: list[str]) -> str | None:
    """模糊匹配: 精确 → 包含 → difflib。"""
    if not candidate or not targets:
        return None
    # 精确
    if candidate in targets:
        return candidate
    # 包含
    for t in targets:
        if candidate in t or t in candidate:
            return t
    # difflib (cutoff=0.5)
    matches = get_close_matches(candidate, targets, n=1, cutoff=0.5)
    return matches[0] if matches else None


def _normalize_enum(
    value: str,
    vocab: set[str],
    cn_map: dict[str, str],
    default: str,
) -> str:
    """枚举值标准化: 原值 → 中文映射 → 默认值。"""
    if not value:
        return default
    low = value.lower().strip()
    if low in vocab:
        return low
    # 中文映射
    if value in cn_map:
        return cn_map[value]
    for cn_key, en_val in cn_map.items():
        if cn_key in value:
            return en_val
    return default


# ═══════════════════════════════════════════════════════════════
# 默认计划生成 (无 LLM 时的 fallback)
# ═══════════════════════════════════════════════════════════════

def generate_default_plan(
    map_type: str,
    zones: list[dict],
    measures: list[dict],
    spatial_layout: dict | None = None,
) -> DrawingPlan:
    """从 State 数据直接生成默认 DrawingPlan (供 fallback 路径使用)。

    Args:
        map_type: 图类型
        zones: ETL zones
        measures: State.Measures
        spatial_layout: 空间布局信息 (可选)
    """
    spatial = spatial_layout or {}
    project_name = "水土保持"

    # 基础 layout_hints
    layout_hints = {
        "drainage_direction": spatial.get("drainage_direction", "south"),
        "main_road_orientation": "north-south",
    }

    # zone specs
    zone_specs = [ZoneSpec(name=z.get("name", ""), emphasis="normal") for z in zones]

    if map_type == "zone_boundary":
        return DrawingPlan(
            map_type="zone_boundary",
            title=f"{project_name} 水土保持防治分区图",
            zones=zone_specs,
            layout_hints=layout_hints,
        )

    if map_type == "measure_layout":
        measure_specs = _measures_to_specs(measures, zones, spatial)
        return DrawingPlan(
            map_type="measure_layout",
            title=f"{project_name} 水土保持措施总体布置图",
            zones=zone_specs,
            measures=measure_specs,
            layout_hints=layout_hints,
        )

    if map_type == "zone_detail":
        # 默认取第一个分区
        target_zone = zones[0].get("name", "") if zones else ""
        zone_measures = [
            m for m in measures
            if m.get("分区", m.get("zone", "")) == target_zone
            or target_zone in m.get("分区", m.get("zone", ""))
        ]
        measure_specs = _measures_to_specs(zone_measures, zones, spatial)
        return DrawingPlan(
            map_type="zone_detail",
            title=f"{project_name} {target_zone}措施详图",
            zones=[ZoneSpec(name=target_zone, emphasis="highlight")],
            measures=measure_specs,
            layout_hints=layout_hints,
        )

    if map_type == "typical_section":
        from src.measure_symbols import SECTION_TEMPLATES, match_section_template
        section_specs = []
        seen = set()
        for m in measures:
            mname = m.get("措施名称", m.get("name", ""))
            matched = match_section_template(mname)
            if matched:
                tmpl_key, _ = matched
                if tmpl_key not in seen:
                    seen.add(tmpl_key)
                    section_specs.append(SectionSpec(structure=tmpl_key))
        return DrawingPlan(
            map_type="typical_section",
            title=f"{project_name} 典型工程断面图",
            sections=section_specs,
            layout_hints=layout_hints,
        )

    # fallback
    return DrawingPlan(
        map_type=map_type,
        title=f"{project_name} 措施图",
        zones=zone_specs,
        measures=_measures_to_specs(measures, zones, spatial),
        layout_hints=layout_hints,
    )


def _measures_to_specs(
    measures: list[dict],
    zones: list[dict],
    spatial: dict,
) -> list[MeasureSpec]:
    """将 State.Measures 转换为 MeasureSpec 列表。"""
    specs = []
    # 自动分配位置 (简单轮转)
    positions = ["south", "north", "east", "west", "center",
                 "southeast", "southwest", "northeast", "northwest"]

    for i, m in enumerate(measures):
        name = m.get("措施名称", m.get("name", ""))
        zone = m.get("分区", m.get("zone", ""))
        placement = m.get("空间布置", {})

        # 从空间布置提取位置信息
        pos_raw = placement.get("position", "") if isinstance(placement, dict) else ""
        position = _normalize_enum(pos_raw, POSITION_VOCAB, _POSITION_CN_MAP, positions[i % len(positions)])

        dir_raw = placement.get("direction", "") if isinstance(placement, dict) else ""
        direction = _normalize_enum(dir_raw, DIRECTION_VOCAB, _DIRECTION_CN_MAP, "north-south")

        specs.append(MeasureSpec(
            name=name,
            zone=zone,
            position=position,
            direction=direction,
            coverage="partial",
        ))

    return specs
