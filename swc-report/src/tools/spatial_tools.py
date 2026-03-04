"""Planner Agent 空间分析工具 — 查询空间布局 + 图集规范。

工具列表:
  5. spatial_context_tool  — 查询项目空间布局信息
  6. atlas_reference_tool  — 查询标准图集绘图规范
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.context import get_state_or_none, get_atlas_rag

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Tool 5: spatial_context_tool
# ═══════════════════════════════════════════════════════════════

SPATIAL_CONTEXT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "spatial_context_tool",
        "description": "查询项目空间布局信息（建筑位置、道路走向、坡度、排水方向）。可指定分区名称获取该分区的空间信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "zone_name": {
                    "type": "string",
                    "description": "分区名称，如'建(构)筑物区'。不指定则返回全局空间布局。",
                },
            },
            "required": [],
        },
    },
}


def spatial_context_tool(zone_name: str | None = None) -> dict:
    """查询项目空间布局信息。

    从 state.ETL.spatial_layout 读取 VL + GIS 分析的空间数据。
    """
    _state = get_state_or_none()
    if _state is None:
        return {"error": "状态未初始化", "spatial_layout": {}}

    layout = getattr(_state.ETL, "spatial_layout", {})

    if not layout:
        # 空间分析未执行或无 CAD/GIS 数据
        return {
            "available": False,
            "message": "未检测到 CAD/GIS 数据，无空间布局信息。请根据分区面积和常规布局规划措施位置。",
            "zones": [{"name": z["name"], "area_hm2": z["area_hm2"]}
                      for z in _state.ETL.zones],
        }

    if zone_name:
        # 返回指定分区的空间信息
        zone_info = None
        for z in layout.get("zones", []):
            if z.get("name") == zone_name or zone_name in z.get("name", ""):
                zone_info = z
                break
        # 也查 GIS 分区
        gis_zone = None
        for gz in layout.get("gis_zones", []):
            if gz.get("name") == zone_name or zone_name in gz.get("name", ""):
                gis_zone = gz
                break

        return {
            "available": True,
            "zone_name": zone_name,
            "zone_info": zone_info,
            "gis_zone": gis_zone,
            "drainage_direction": layout.get("drainage_direction", ""),
            "slopes": layout.get("slopes", []),
            "nearby_roads": [r for r in layout.get("roads", [])],
            "nearby_buildings": [b for b in layout.get("buildings", [])],
        }

    # 返回全局空间布局
    return {
        "available": True,
        "buildings": layout.get("buildings", []),
        "roads": layout.get("roads", []),
        "zones": layout.get("zones", []),
        "slopes": layout.get("slopes", []),
        "drainage_direction": layout.get("drainage_direction", ""),
        "site_boundary": layout.get("site_boundary", {}),
        "key_facilities": layout.get("key_facilities", []),
        "gis_zones_count": len(layout.get("gis_zones", [])),
    }


# ═══════════════════════════════════════════════════════════════
# Tool 6: atlas_reference_tool
# ═══════════════════════════════════════════════════════════════

ATLAS_REFERENCE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "atlas_reference_tool",
        "description": "查询标准图集中的措施绘图规范（符号、标注、布置要求）。用于指导措施的空间布置决策。",
        "parameters": {
            "type": "object",
            "properties": {
                "measure_type": {
                    "type": "string",
                    "description": "措施类型，如'排水沟'、'挡土墙'、'植草护坡'",
                },
                "map_type": {
                    "type": "string",
                    "enum": ["layout", "detail", "section"],
                    "description": "地图类型: layout=总布置, detail=详图, section=断面",
                    "default": "layout",
                },
            },
            "required": ["measure_type"],
        },
    },
}


def atlas_reference_tool(measure_type: str, map_type: str = "layout") -> dict:
    """查询标准图集中的措施绘图规范。"""
    _atlas_rag = get_atlas_rag()
    if _atlas_rag is not None:
        try:
            conv = _atlas_rag.query_conventions(measure_type, map_type)
            return {
                "measure_type": measure_type,
                "map_type": map_type,
                "conventions": conv,
                "source": "atlas_rag",
            }
        except Exception as e:
            logger.warning(f"图集查询失败: {e}")

    # 回退: 从内置规范返回
    from src.measure_symbols import get_style, SECTION_TEMPLATES

    style = get_style(measure_type)
    section = None
    for key, tmpl in SECTION_TEMPLATES.items():
        if measure_type in key or key in measure_type:
            section = tmpl
            break

    return {
        "measure_type": measure_type,
        "map_type": map_type,
        "conventions": {
            "symbol_style": style,
            "section_template": section,
            "layout_rules": {
                "排水沟": "沿道路两侧或场地边界布设，保持纵坡≥0.3%",
                "截水沟": "设于坡顶或填方边坡上方，拦截坡面径流",
                "挡墙": "设于填方边坡坡脚，墙高根据填方高度确定",
                "沉沙池": "设于排水沟末端、出水口前，便于清淤",
                "绿化": "建筑周边、道路两侧、空地，优先恢复表土区域",
                "围挡": "施工区外围全封闭，高度≥2m",
                "临时覆盖": "裸露超过30天的区域全覆盖",
            }.get(measure_type, "按标准规范布设"),
        },
        "source": "builtin",
    }


# ── 工具注册表 ──

SPATIAL_TOOLS = [
    (spatial_context_tool, SPATIAL_CONTEXT_SCHEMA),
    (atlas_reference_tool, ATLAS_REFERENCE_SCHEMA),
]

SPATIAL_TOOL_MAP = {
    "spatial_context_tool": spatial_context_tool,
    "atlas_reference_tool": atlas_reference_tool,
}
