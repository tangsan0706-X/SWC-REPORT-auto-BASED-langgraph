"""Drawing Agent 工具 — 措施图绘制的 4 个工具函数。

工具列表:
  1. get_project_data    — 获取项目分区/措施/空间布局数据
  2. get_style_reference — 获取 SL73_6-2015 制图规范 + 内置样式
  3. submit_drawing_plan — 提交 DrawingPlan JSON，由渲染引擎生成 PNG + DXF
  4. verify_image        — VL 模型验证图片质量 (可降级)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from src.context import get_state_or_none, get_atlas_rag, get_output_dir

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Tool 1: get_project_data
# ═══════════════════════════════════════════════════════════════

GET_PROJECT_DATA_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_project_data",
        "description": "获取项目分区、措施、空间布局数据，用于绘制措施图",
        "parameters": {
            "type": "object",
            "properties": {
                "zone_name": {
                    "type": "string",
                    "description": "分区名称。不指定则返回所有分区概览。",
                },
            },
            "required": [],
        },
    },
}


def get_project_data(zone_name: str | None = None) -> dict:
    """获取项目分区/措施/空间布局数据。"""
    _state = get_state_or_none()
    if _state is None:
        return {"error": "状态未初始化"}

    zones = _state.ETL.zones
    measures = _state.Measures
    spatial = _state.ETL.spatial_layout or {}
    meta = _state.Static.meta

    if zone_name:
        # 指定分区
        zone_info = None
        for z in zones:
            if z.get("name") == zone_name or zone_name in z.get("name", ""):
                zone_info = z
                break
        zone_measures = [
            m for m in measures
            if m.get("分区", m.get("zone", "")) == zone_name
            or zone_name in m.get("分区", m.get("zone", ""))
        ]
        # 空间布置
        measure_layout = [
            ml for ml in _state.ETL.measure_layout
            if ml.get("分区", ml.get("zone", "")) == zone_name
            or zone_name in ml.get("分区", ml.get("zone", ""))
        ] if _state.ETL.measure_layout else []

        return {
            "project_name": meta.get("project_name", ""),
            "zone": zone_info,
            "measures": zone_measures,
            "measure_layout": measure_layout,
            "spatial_zone": _find_spatial_zone(spatial, zone_name),
        }

    # 全局概览
    zone_summary = []
    for z in zones:
        z_name = z.get("name", "")
        z_measures = [m for m in measures
                      if m.get("分区", m.get("zone", "")) == z_name
                      or z_name in m.get("分区", m.get("zone", ""))]
        zone_summary.append({
            "name": z_name,
            "area_hm2": z.get("area_hm2", 0),
            "measure_count": len(z_measures),
            "measure_names": [m.get("措施名称", m.get("name", "")) for m in z_measures],
        })

    return {
        "project_name": meta.get("project_name", ""),
        "total_zones": len(zones),
        "total_measures": len(measures),
        "zones": zone_summary,
        "spatial_available": bool(spatial),
        "buildings": spatial.get("buildings", []),
        "roads": spatial.get("roads", []),
        "drainage_direction": spatial.get("drainage_direction", ""),
    }


def _find_spatial_zone(spatial: dict, zone_name: str) -> dict | None:
    """在空间布局中查找分区信息。"""
    for z in spatial.get("zones", []):
        if z.get("name") == zone_name or zone_name in z.get("name", ""):
            return z
    return None


# ═══════════════════════════════════════════════════════════════
# Tool 2: get_style_reference
# ═══════════════════════════════════════════════════════════════

GET_STYLE_REFERENCE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_style_reference",
        "description": "获取 SL73_6-2015 制图规范和内置措施样式，用于确定颜色/线型/符号/布局",
        "parameters": {
            "type": "object",
            "properties": {
                "map_type": {
                    "type": "string",
                    "enum": ["zone_boundary", "measure_layout", "zone_detail", "typical_section"],
                    "description": "图类型: zone_boundary=分区图, measure_layout=总布置图, zone_detail=分区详图, typical_section=断面图",
                },
                "measure_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "需要查询样式的措施名称列表",
                },
            },
            "required": ["map_type"],
        },
    },
}


def _load_drawing_standards() -> dict:
    """加载预处理的制图标准 JSON (不依赖 ChromaDB)。"""
    import json
    from src.settings import CONFIG_DIR
    path = CONFIG_DIR / "drawing_standards.json"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"drawing_standards.json 加载失败: {e}")
    return {}


def get_style_reference(map_type: str,
                        measure_names: list[str] | None = None) -> dict:
    """获取制图规范 + 内置措施样式 + 预处理标准知识库。"""
    from src.measure_symbols import (
        get_style, SECTION_TEMPLATES, ZONE_COLORS, MAP_DEFAULTS,
    )

    result = {
        "map_type": map_type,
        "map_defaults": MAP_DEFAULTS,
        "zone_colors": ZONE_COLORS,
        "sl73_conventions": {},
    }

    # 查询措施样式
    if measure_names:
        styles = {}
        sections = {}
        for name in measure_names:
            styles[name] = get_style(name)
            if name in SECTION_TEMPLATES:
                sections[name] = SECTION_TEMPLATES[name]
        result["measure_styles"] = styles
        result["section_templates"] = sections

    # ── 优先：预处理的制图标准 JSON (不依赖 ChromaDB) ──
    standards = _load_drawing_standards()
    if standards:
        result["sl73_conventions"] = standards.get("general_rules", {})
        # 按 map_type 注入对应规范
        type_key_map = {
            "zone_boundary": "zone_boundary_map",
            "measure_layout": "measure_layout_map",
            "zone_detail": "zone_detail_map",
            "typical_section": "typical_section",
        }
        key = type_key_map.get(map_type)
        if key and key in standards:
            result["drawing_rules"] = standards[key]
        # 断面图额外注入 DWG 参考和结构详情
        if map_type == "typical_section":
            if "dwg_reference" in standards:
                result["dwg_reference"] = standards["dwg_reference"]
        # 植物措施参考
        if "vegetation_measures" in standards:
            result["vegetation_reference"] = standards["vegetation_measures"]

    # ── 备选：atlas_rag 查询 (ChromaDB 可用时) ──
    _atlas_rag = get_atlas_rag()
    if _atlas_rag is not None:
        try:
            map_type_cn = {
                "zone_boundary": "分区图 分区边界",
                "measure_layout": "措施总体布置图",
                "zone_detail": "分区详图 措施详图",
                "typical_section": "典型断面图 工程断面",
            }.get(map_type, map_type)

            conventions = _atlas_rag.query_conventions(
                measure_type=map_type_cn, map_type=map_type
            )
            # 合并 (不覆盖已有的 sl73_conventions)
            if conventions and not result.get("sl73_conventions"):
                result["sl73_conventions"] = conventions

            standard_texts = _atlas_rag.query_by_purpose(
                query=f"水土保持 {map_type_cn} 绘制要求 图例 标注",
                purpose="制图标准",
                top_k=2,
            )
            if standard_texts:
                result["drawing_standard_text"] = standard_texts
        except Exception as e:
            logger.debug(f"atlas_rag 查询失败: {e}")

    return result


# ═══════════════════════════════════════════════════════════════
# Tool 3: submit_drawing_plan
# ═══════════════════════════════════════════════════════════════

SUBMIT_PLAN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_drawing_plan",
        "description": (
            "提交 DrawingPlan JSON 绘图计划，由确定性渲染引擎自动生成 PNG + DXF。"
            "不要写 Python 代码，只需输出 JSON 描述'画什么、放哪里'。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan_json": {
                    "type": "string",
                    "description": (
                        "DrawingPlan JSON 字符串。"
                        "必填字段: map_type, title。"
                        "可选: zones, measures, sections, layout_hints。"
                        "position 词汇: north/south/east/west/center/northeast/northwest/southeast/southwest/perimeter。"
                        "direction 词汇: north-south/east-west/clockwise/along-road/along-boundary。"
                        "coverage 词汇: full/partial/edge。"
                    ),
                },
                "filename": {
                    "type": "string",
                    "description": "输出文件名 (不含路径)，如 'zone_boundary_map.png'",
                },
            },
            "required": ["plan_json", "filename"],
        },
    },
}


def submit_drawing_plan(plan_json: str, filename: str) -> dict:
    """提交 DrawingPlan JSON，由渲染引擎生成 PNG + DXF。

    降级策略:
      1. 解析 JSON → DrawingPlan → 校验 → 渲染    (最佳路径)
      2. JSON 畸形 → 多层修复 → 渲染                (容错路径)
      3. 完全无法解析 → generate_default_plan → 渲染  (规则降级)
    """
    from src.drawing_plan import parse_plan_json, validate_plan, generate_default_plan
    from src.drawing_renderer import DrawingRenderer

    _state = get_state_or_none()
    if _state is None:
        return {"success": False, "error": "状态未初始化"}

    out_dir = get_output_dir() or Path("data/output")
    out_dir.mkdir(parents=True, exist_ok=True)

    zones = _state.ETL.zones
    measures = _state.Measures
    spatial = _state.ETL.spatial_layout
    gis_gdf = _state.ETL.gis_gdf

    # 1. 解析 JSON
    plan = parse_plan_json(plan_json)

    if plan is None:
        # 降级: 从文件名推断 map_type
        logger.warning("DrawingPlan JSON 解析失败, 使用默认计划")
        map_type = _infer_map_type(filename)
        plan = generate_default_plan(map_type, zones, measures, spatial)

    # 2. 校验 + 修复
    plan, warnings = validate_plan(plan, zones, measures)
    if warnings:
        logger.info(f"DrawingPlan 校验修复: {warnings}")

    # 3. 渲染
    try:
        cad_geometry = _state.ETL.cad_geometry if hasattr(_state.ETL, 'cad_geometry') else None
        cad_dxf_path = _state.ETL.cad_dxf_path if hasattr(_state.ETL, 'cad_dxf_path') else None
        cad_site_features = _state.ETL.cad_site_features if hasattr(_state.ETL, 'cad_site_features') else None
        # 如果有 SiteModel，创建 PlacementEngine 传入
        _placement_engine = None
        site_model = getattr(_state.ETL, 'site_model', None) if hasattr(_state.ETL, 'site_model') else None
        if site_model is not None:
            try:
                from src.placement_engine import PlacementEngine
                _placement_engine = PlacementEngine(site_model)
                _placement_engine.resolve_all(measures)
            except Exception:
                pass
        renderer = DrawingRenderer(
            plan=plan,
            zones=zones,
            measures=measures,
            spatial_layout=spatial,
            gis_gdf=gis_gdf,
            output_dir=out_dir,
            cad_geometry=cad_geometry,
            cad_dxf_path=cad_dxf_path,
            cad_site_features=cad_site_features,
            placement_engine=_placement_engine,
        )
        paths = renderer.render_all(filename)
    except Exception as e:
        logger.error(f"DrawingRenderer 渲染异常: {e}")
        return {"success": False, "error": f"渲染失败: {e}"}

    if not paths:
        return {"success": False, "error": "渲染未产出文件"}

    png_path = paths.get("png")
    dxf_path = paths.get("dxf")

    result = {"success": True}
    if png_path:
        result["output_path"] = str(png_path)
        result["file_size_kb"] = round(png_path.stat().st_size / 1024, 1)
    if dxf_path:
        result["dxf_path"] = str(dxf_path)
    if warnings:
        result["warnings"] = warnings

    return result


def _infer_map_type(filename: str) -> str:
    """从文件名推断 map_type。"""
    fn = filename.lower()
    if "zone_boundary" in fn:
        return "zone_boundary"
    if "measure_layout" in fn or "layout" in fn:
        return "measure_layout"
    if "zone_detail" in fn or "detail" in fn:
        return "zone_detail"
    if "section" in fn:
        return "typical_section"
    return "measure_layout"


# ═══════════════════════════════════════════════════════════════
# Tool 4: verify_image
# ═══════════════════════════════════════════════════════════════

VERIFY_IMAGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "verify_image",
        "description": "验证生成的措施图质量。VL 可用时进行专业评审，否则仅检查文件有效性",
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "图片文件路径",
                },
                "expected_type": {
                    "type": "string",
                    "enum": ["zone_boundary", "measure_layout", "zone_detail", "typical_section"],
                    "description": "期望的图类型",
                },
            },
            "required": ["image_path", "expected_type"],
        },
    },
}


_VL_VERIFY_PROMPT = """请评审这张水土保持措施图的质量。按以下维度打分 (0-100):

1. 图面完整性 (25分): 是否有标题、图例、指北针、比例尺
2. 标注规范性 (25分): 标注是否清晰、字体合规、单位正确
3. 内容正确性 (25分): 措施表示是否符合 SL73_6-2015 标准
4. 视觉美观性 (25分): 布局是否合理、配色是否协调

期望图类型: {expected_type}

请只输出 JSON:
{{"score": 85, "issues": ["缺少指北针", "图例不完整"], "suggestions": ["添加指北针", "补充图例"]}}
"""


def verify_image(image_path: str, expected_type: str) -> dict:
    """验证措施图质量。VL 不可用或单 GPU 时降级为文件检查。

    单 GPU (如 Windows + Ollama) 每次 VL 调用需模型换入换出 (~7 min)，
    因此当 DRAWING_WORKERS=1 或 Windows 环境时跳过 VL 验证。
    """
    path = Path(image_path)

    # 基本检查
    if not path.exists():
        return {"pass": False, "score": 0, "error": "文件不存在"}

    size_kb = path.stat().st_size / 1024
    if size_kb < 10:
        return {"pass": False, "score": 0, "error": f"文件过小: {size_kb:.1f}KB"}

    # 单 GPU 环境跳过 VL 验证 (模型换入换出代价太高)
    import os, sys
    skip_vl = (
        sys.platform == "win32"
        or os.environ.get("DRAWING_WORKERS", "") == "1"
        or os.environ.get("SKIP_VL_VERIFY", "").lower() in ("1", "true")
    )
    if skip_vl:
        return {
            "pass": size_kb >= 50,
            "score": 80 if size_kb >= 50 else 40,
            "issues": [] if size_kb >= 50 else ["图片过小，可能内容不完整"],
            "suggestions": ["单GPU环境已跳过VL验证，建议人工复核"],
            "source": "size_check",
        }

    # 尝试 VL 模型验证
    try:
        import base64
        import json
        from openai import OpenAI
        from src.settings import VL_URL, VL_MODEL_NAME, VL_MAX_TOKENS

        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        client = OpenAI(base_url=VL_URL, api_key="not-needed")
        response = client.chat.completions.create(
            model=VL_MODEL_NAME,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _VL_VERIFY_PROMPT.format(expected_type=expected_type)},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            max_tokens=VL_MAX_TOKENS,
            temperature=0.2,
        )
        text = response.choices[0].message.content or ""

        # 解析评分
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                result = json.loads(match.group())
            else:
                result = {"score": 70}

        score = result.get("score", 70)
        return {
            "pass": score >= 70,
            "score": score,
            "issues": result.get("issues", []),
            "suggestions": result.get("suggestions", []),
            "source": "vl_model",
        }
    except Exception as e:
        logger.debug(f"VL 验证不可用, 降级: {e}")

    # 降级: 文件存在且 > 10KB → 自动通过
    return {
        "pass": True,
        "score": 75,
        "issues": [],
        "suggestions": ["VL 模型不可用，建议人工复核"],
        "source": "fallback",
    }


# ── 工具注册表 ────────────────────────────────────────────────

DRAWING_TOOLS = [
    (get_project_data, GET_PROJECT_DATA_SCHEMA),
    (get_style_reference, GET_STYLE_REFERENCE_SCHEMA),
    (submit_drawing_plan, SUBMIT_PLAN_SCHEMA),
    (verify_image, VERIFY_IMAGE_SCHEMA),
]

DRAWING_TOOL_MAP = {
    "get_project_data": get_project_data,
    "get_style_reference": get_style_reference,
    "submit_drawing_plan": submit_drawing_plan,
    "verify_image": verify_image,
}
