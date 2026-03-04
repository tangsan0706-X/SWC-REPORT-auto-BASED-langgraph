"""空间分析模块 — 综合 VL 对 CAD 图纸的分析 + GIS 精确数据。

功能:
  - 读取 SHP/GeoJSON → GeoDataFrame
  - 调用 VL 模型分析 CAD 图纸 (DWG 需先转 PNG)
  - 综合生成空间布局描述 JSON
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── GIS 读取 ────────────────────────────────────────────────────

def read_gis_file(file_path: Path) -> Any:
    """读取 SHP/GeoJSON 文件为 GeoDataFrame。

    Returns:
        GeoDataFrame 或 None (如果 geopandas 不可用或文件不存在)。
    """
    if not file_path.exists():
        logger.warning(f"GIS 文件不存在: {file_path}")
        return None

    try:
        import geopandas as gpd
        gdf = gpd.read_file(str(file_path))
        logger.info(f"GIS 读取成功: {file_path.name}, {len(gdf)} 个要素, CRS={gdf.crs}")
        return gdf
    except ImportError:
        logger.warning("geopandas 未安装，无法读取 GIS 文件")
        return None
    except Exception as e:
        logger.error(f"GIS 文件读取失败: {e}")
        return None


def scan_gis_files(directory: Path) -> list[Path]:
    """扫描目录中的 GIS 文件 (shp/geojson/gpkg)。"""
    gis_exts = {".shp", ".geojson", ".gpkg"}
    files = []
    if directory.exists():
        for f in directory.iterdir():
            if f.suffix.lower() in gis_exts:
                files.append(f)
    return files


def scan_cad_files(directory: Path) -> list[Path]:
    """扫描目录中的 CAD 文件 (dwg/dxf) 和已转换的图片。"""
    cad_exts = {".dwg", ".dxf"}
    img_exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    files = []
    if directory.exists():
        for f in directory.iterdir():
            if f.suffix.lower() in cad_exts or f.suffix.lower() in img_exts:
                files.append(f)
    return files


# ── CAD → PNG 转换 ──────────────────────────────────────────────

def convert_cad_to_png(cad_path: Path, output_dir: Path) -> Path | None:
    """将 DWG/DXF 转换为 PNG 图片。

    尝试使用 ezdxf (DXF) 或 ODA File Converter (DWG)。
    如果都不可用，返回 None。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / f"{cad_path.stem}.png"

    if png_path.exists():
        return png_path

    suffix = cad_path.suffix.lower()

    if suffix == ".dxf":
        return _convert_dxf_to_png(cad_path, png_path)
    elif suffix == ".dwg":
        return _convert_dwg_to_png(cad_path, png_path)
    elif suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        # 已经是图片，直接返回
        return cad_path

    return None


def _convert_dxf_to_png(dxf_path: Path, png_path: Path) -> Path | None:
    """使用 ezdxf + matplotlib 将 DXF 转 PNG。"""
    try:
        import ezdxf
        from ezdxf.addons.drawing import matplotlib as draw_mpl

        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig = plt.figure(figsize=(20, 16), dpi=200)
        ax = fig.add_axes([0, 0, 1, 1])
        draw_mpl.qfigure(doc.modelspace(), fig=fig)
        fig.savefig(str(png_path), dpi=200, bbox_inches="tight")
        plt.close(fig)

        logger.info(f"DXF → PNG 转换成功: {png_path.name}")
        return png_path
    except ImportError:
        logger.warning("ezdxf 未安装，无法转换 DXF 文件")
        return None
    except Exception as e:
        logger.error(f"DXF 转换失败: {e}")
        return None


def _convert_dwg_to_png(dwg_path: Path, png_path: Path) -> Path | None:
    """DWG 转 PNG — 需要 ODA File Converter 或用户预转换。"""
    logger.warning(
        f"DWG 文件 ({dwg_path.name}) 需先转换为 DXF 或 PNG。"
        "请使用 AutoCAD/ODA File Converter 转换后重新上传。"
    )
    return None


# ── VL 空间分析 ─────────────────────────────────────────────────

VL_SPATIAL_PROMPT = """请分析这张工程施工总平面图/CAD图纸，提取以下空间布局信息：

1. **建筑物**: 标识所有建筑物的位置、名称、大致轮廓
2. **道路**: 识别道路的走向、宽度
3. **场地边界**: 整个项目场地的边界范围
4. **分区**: 识别可能的功能分区 (建筑区/道路区/绿化区/施工区)
5. **坡度/高程**: 如有等高线或标高，描述地形走势
6. **排水方向**: 根据地形判断自然排水方向
7. **关键设施**: 大门、围墙、变电站等

请用以下 JSON 格式输出 (只输出 JSON):
{
  "buildings": [{"name": "...", "position": "场地中部偏北", "type": "住宅/商业/工业"}],
  "roads": [{"name": "...", "direction": "东西走向", "width_m": 6}],
  "zones": [{"name": "建筑区", "position": "场地中部", "area_ratio": 0.4}],
  "slopes": [{"direction": "NE→SW", "gradient": "3%"}],
  "drainage_direction": "西北→东南",
  "site_boundary": {"shape": "不规则矩形", "orientation": "南北长东西短"},
  "key_facilities": [{"name": "大门", "position": "场地南侧"}]
}"""


def analyze_cad_with_vl(image_paths: list[Path]) -> dict:
    """使用 VL 模型分析 CAD 图片，提取空间布局。

    Returns:
        空间布局字典, 失败时返回空 dict。
    """
    if not image_paths:
        return {}

    try:
        from openai import OpenAI
        from src.settings import VL_URL, VL_MODEL_NAME, VL_MAX_TOKENS
    except ImportError:
        logger.warning("OpenAI 客户端不可用")
        return {}

    client = OpenAI(base_url=VL_URL, api_key="not-needed")

    # 构建多图消息
    content = [{"type": "text", "text": VL_SPATIAL_PROMPT}]
    for img_path in image_paths[:3]:  # 最多分析 3 张
        import base64
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        suffix = img_path.suffix.lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "tif": "image/tiff", "tiff": "image/tiff"}.get(suffix, "image/png")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })

    try:
        response = client.chat.completions.create(
            model=VL_MODEL_NAME,
            messages=[{"role": "user", "content": content}],
            max_tokens=VL_MAX_TOKENS,
            temperature=0.2,
        )
        text = response.choices[0].message.content or ""
        return _parse_spatial_json(text)
    except Exception as e:
        logger.error(f"VL 空间分析失败: {e}")
        return {}


def _parse_spatial_json(text: str) -> dict:
    """从 VL 输出中提取 JSON。"""
    import re
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 提取 JSON 块
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # 提取 {...}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logger.warning("无法解析 VL 空间分析输出")
    return {}


# ── GIS 数据提取 ────────────────────────────────────────────────

def extract_gis_zones(gis_gdf) -> list[dict]:
    """从 GeoDataFrame 提取分区信息。"""
    if gis_gdf is None:
        return []

    zones = []
    for _, row in gis_gdf.iterrows():
        geom = row.geometry
        zone = {
            "name": str(row.get("name", row.get("NAME", f"Zone_{len(zones)+1}"))),
            "area_m2": geom.area if geom else 0,
            "area_hm2": round(geom.area / 10000, 4) if geom else 0,
            "centroid": [geom.centroid.x, geom.centroid.y] if geom else [0, 0],
            "bounds": list(geom.bounds) if geom else [0, 0, 0, 0],
        }
        zones.append(zone)
    return zones


# ── 综合空间分析 ────────────────────────────────────────────────

def analyze_spatial_layout(
    cad_images: list[Path] | None = None,
    gis_gdf: Any = None,
    zones: list[dict] | None = None,
) -> dict:
    """综合 VL 对 CAD 图纸的分析 + GIS 精确数据，生成空间布局描述。

    Args:
        cad_images: CAD 图纸图片路径列表 (VL 分析)
        gis_gdf: GeoDataFrame (GIS 精确数据)
        zones: 配置文件中的分区信息 (facts_v2.json)

    Returns:
        {
            "buildings": [...],
            "roads": [...],
            "zones": [...],
            "slopes": [...],
            "drainage_direction": "...",
            "site_boundary": {...},
            "gis_zones": [...],   # GIS 提供的精确分区
        }
    """
    layout = {
        "buildings": [],
        "roads": [],
        "zones": [],
        "slopes": [],
        "drainage_direction": "",
        "site_boundary": {},
        "key_facilities": [],
        "gis_zones": [],
    }

    # 1. VL 分析 CAD 图纸
    if cad_images:
        vl_result = analyze_cad_with_vl(cad_images)
        if vl_result:
            layout.update({k: v for k, v in vl_result.items() if v})
            logger.info(f"VL 空间分析: {len(vl_result.get('buildings', []))} 建筑, "
                        f"{len(vl_result.get('roads', []))} 道路")

    # 2. GIS 精确数据
    if gis_gdf is not None:
        layout["gis_zones"] = extract_gis_zones(gis_gdf)
        logger.info(f"GIS 分区: {len(layout['gis_zones'])} 个")

    # 3. 从配置补充分区信息 (如果 VL 和 GIS 都未提供)
    if not layout["zones"] and zones:
        for z in zones:
            layout["zones"].append({
                "name": z["name"],
                "area_hm2": z["area_hm2"],
                "area_m2": z.get("area_m2", z["area_hm2"] * 10000),
                "position": "待确定",
            })

    return layout


def generate_default_spatial_layout(zones: list[dict]) -> dict:
    """在无 CAD/GIS 数据时，基于分区面积生成默认空间布局。

    使用简单的矩形排列方式模拟场地布局。
    """
    import math

    layout = {
        "buildings": [],
        "roads": [{"name": "场内主干道", "direction": "南北走向", "width_m": 6}],
        "zones": [],
        "slopes": [{"direction": "N→S", "gradient": "2%"}],
        "drainage_direction": "北→南",
        "site_boundary": {"shape": "矩形", "orientation": "南北长"},
        "key_facilities": [{"name": "大门", "position": "场地南侧"}],
        "gis_zones": [],
    }

    # 计算总面积，用于布局
    total_area_m2 = sum(z.get("area_m2", z["area_hm2"] * 10000) for z in zones)
    site_width = math.sqrt(total_area_m2 * 1.5)  # 假设长宽比 1.5:1
    site_height = total_area_m2 / site_width

    # 简单排列各分区
    x_offset = 0.0
    y_offset = 0.0
    row_height = 0.0

    for z in zones:
        area_m2 = z.get("area_m2", z["area_hm2"] * 10000)
        zone_width = math.sqrt(area_m2)
        zone_height = area_m2 / zone_width

        if x_offset + zone_width > site_width:
            x_offset = 0.0
            y_offset += row_height + 10  # 10m 间距
            row_height = 0.0

        layout["zones"].append({
            "name": z["name"],
            "area_hm2": z["area_hm2"],
            "area_m2": area_m2,
            "position": f"({x_offset:.0f}, {y_offset:.0f})",
            "bbox": [x_offset, y_offset, x_offset + zone_width, y_offset + zone_height],
        })

        x_offset += zone_width + 10
        row_height = max(row_height, zone_height)

    return layout
