"""措施图渲染引擎 — 生成 4 类水土保持措施专业图 (PNG)。

输出:
  图1: 项目分区图 (zone_boundary_map)
  图2: 措施总体布置图 (measure_layout_map)
  图3: 分区措施详图 ×N (zone_detail_{分区名})
  图4: 典型工程断面图 ×N (typical_section_{结构名})
"""

from __future__ import annotations

import datetime
import logging
import math
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.font_manager as fm
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch
import numpy as np

from src.measure_symbols import (
    MEASURE_STYLES, SECTION_TEMPLATES, ZONE_COLORS,
    MAP_DEFAULTS, ZORDER, get_style, get_zone_color, get_measure_color,
    match_section_template, get_zone_hatch,
    MEASURE_COLORS_PROFESSIONAL, get_measure_category,
    BOUNDARY_COLORS, LEGEND_CATEGORIES,
)

logger = logging.getLogger(__name__)

# ── 中文字体 ────────────────────────────────────────────────────
_CN_FONT = None
for _font_name in ["SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC",
                    "Microsoft YaHei", "Noto Sans SC", "Source Han Sans SC",
                    "AR PL UMing CN", "DejaVu Sans"]:
    try:
        fp = fm.FontProperties(family=_font_name)
        # findfont 返回实际匹配的字体路径; 若找不到会返回默认字体
        found = fm.findfont(fp, fallback_to_default=False)
        if found:
            _CN_FONT = fp
            break
    except Exception:
        continue
if _CN_FONT:
    plt.rcParams["font.family"] = _CN_FONT.get_name()
    logger.info(f"中文字体: {_CN_FONT.get_name()}")
else:
    # 最终回退: 搜索系统中任何包含 CJK/中文 的字体
    for f in fm.fontManager.ttflist:
        name_lower = f.name.lower()
        if any(k in name_lower for k in ["cjk", "hei", "song", "kai", "ming",
                                          "yahei", "simsun", "fangsong",
                                          "wqy", "noto sans"]):
            _CN_FONT = fm.FontProperties(family=f.name)
            plt.rcParams["font.family"] = f.name
            logger.info(f"中文字体 (扫描发现): {f.name}")
            break
    if _CN_FONT is None:
        logger.warning("未找到中文字体, 中文可能显示为方框")
plt.rcParams["axes.unicode_minus"] = False


# ═══════════════════════════════════════════════════════════════
# 模块级几何构建函数 (共享: MeasureMapRenderer + DrawingRenderer)
# ═══════════════════════════════════════════════════════════════

def build_zone_geometries(zones: list[dict], gis_gdf: Any = None,
                          cad_bounds: tuple[float, float, float, float] | None = None,
                          cad_content_bounds: tuple[float, float, float, float] | None = None,
                          cad_site_features: Any = None,
                          site_model: Any = None,
                          ) -> dict[str, dict]:
    """为每个分区构建绘图用的几何信息。

    共享: MeasureMapRenderer + DrawingRenderer 都调用此函数。
    优先级: SiteModel > GIS > CAD zone_polygons > 矩形近似。

    Args:
        cad_bounds: CAD 底图全域边界 (用于坐标范围)
        cad_content_bounds: CAD 建筑/道路内容的紧凑边界 (用于对齐分区矩形)
        cad_site_features: CadSiteFeatures (场地特征分析结果, 含 zone_polygons)
        site_model: SiteModel 实例 (融合场景模型, 最高优先级)
    """
    geoms = {}

    # 尝试从 SiteModel 获取 (最高优先级)
    if site_model is not None:
        try:
            from src.geo_utils import shoelace_area as _sa, polygon_centroid as _pc, points_bounds as _pb
            site_zones = getattr(site_model, 'zones', {})
            for z in zones:
                zname = z["name"]
                zone_model = site_zones.get(zname)
                if zone_model is None:
                    # 包含匹配
                    for k, v in site_zones.items():
                        if k in zname or zname in k:
                            zone_model = v
                            break
                if zone_model and len(getattr(zone_model, 'polygon', [])) >= 3:
                    polygon = zone_model.polygon
                    geoms[zname] = {
                        "type": "site_model",
                        "polygon": list(polygon),
                        "centroid": zone_model.centroid,
                        "bounds": zone_model.bbox,
                        "area_m2": zone_model.area_m2,
                    }
            if geoms:
                # 检测坐标空间不匹配 (SiteModel 在 0~280, CAD 在 40M)
                align_bounds = cad_content_bounds or cad_bounds
                if align_bounds and not _check_coordinate_overlap(geoms, align_bounds):
                    logger.warning(
                        "SiteModel 分区坐标与 CAD 坐标不匹配, 重新对齐到 CAD 空间"
                    )
                    _align_to_cad_bounds(geoms, align_bounds)
                return geoms
        except Exception as e:
            logger.warning(f"SiteModel 几何提取失败: {e}")

    # 尝试从 GIS 获取
    if gis_gdf is not None:
        try:
            for _, row in gis_gdf.iterrows():
                name = str(row.get("name", row.get("NAME", "")))
                geom = row.geometry
                if geom is not None:
                    geoms[name] = {
                        "type": "gis",
                        "geometry": geom,
                        "centroid": (geom.centroid.x, geom.centroid.y),
                        "bounds": geom.bounds,
                        "area_m2": geom.area,
                    }
            if geoms:
                return geoms
        except Exception as e:
            logger.warning(f"GIS 几何提取失败: {e}")

    # 尝试从 CAD zone_polygons 获取
    if cad_site_features is not None:
        zone_polygons = getattr(cad_site_features, 'zone_polygons', {})
        if zone_polygons:
            for z in zones:
                zname = z["name"]
                polygon = None
                # 精确匹配 → 包含匹配
                if zname in zone_polygons:
                    polygon = zone_polygons[zname]
                else:
                    for k, v in zone_polygons.items():
                        if k in zname or zname in k:
                            polygon = v
                            break
                if polygon and len(polygon) >= 3:
                    from src.geo_utils import (
                        shoelace_area as _shoelace_area,
                        polygon_centroid as _polygon_centroid,
                        points_bounds as _points_bounds,
                    )
                    area = _shoelace_area(polygon)
                    centroid = _polygon_centroid(polygon)
                    bounds = _points_bounds(polygon)
                    geoms[zname] = {
                        "type": "cad",
                        "polygon": list(polygon),
                        "centroid": centroid,
                        "bounds": bounds,
                        "area_m2": area,
                    }
            if geoms:
                return geoms

    # 无可用数据源 → 尝试矩形 fallback (基于 CAD 边界)
    if len(geoms) < len(zones):
        ref_bounds = cad_content_bounds or cad_bounds
        if ref_bounds:
            missing_zones = [z for z in zones if z["name"] not in geoms]
            if missing_zones:
                fallback_geoms = _generate_rect_fallback(missing_zones, ref_bounds, geoms)
                geoms.update(fallback_geoms)
                if fallback_geoms:
                    logger.info(f"矩形回退: 为 {len(fallback_geoms)} 个缺失分区生成矩形几何")

    if not geoms:
        logger.warning("无可用几何数据源 (SiteModel/GIS/CAD), 分区几何为空")
    return geoms


def _generate_rect_fallback(
    missing_zones: list[dict],
    ref_bounds: tuple[float, float, float, float],
    existing_geoms: dict[str, dict],
) -> dict[str, dict]:
    """为缺失分区在参考边界内生成矩形几何 (紧凑排列)。"""
    from src.geo_utils import shoelace_area as _sa, polygon_centroid as _pc, points_bounds as _pb

    x0, y0, x1, y1 = ref_bounds
    w = x1 - x0
    h = y1 - y0
    if w <= 0 or h <= 0:
        return {}

    n = len(missing_zones)
    if n == 0:
        return {}

    # 在已有几何占用区域之外的空间排列矩形
    # 简单策略: 沿底部水平排列
    margin = min(w, h) * 0.02
    zone_w = (w - margin * (n + 1)) / max(n, 1)
    zone_h = h * 0.25  # 每个矩形占参考区域高度的 25%

    result = {}
    for i, z in enumerate(missing_zones):
        zname = z["name"]
        zx0 = x0 + margin + i * (zone_w + margin)
        zy0 = y0 + margin
        zx1 = zx0 + zone_w
        zy1 = zy0 + zone_h
        polygon = [(zx0, zy0), (zx1, zy0), (zx1, zy1), (zx0, zy1)]
        result[zname] = {
            "type": "fallback_rect",
            "polygon": polygon,
            "centroid": ((zx0 + zx1) / 2, (zy0 + zy1) / 2),
            "bounds": (zx0, zy0, zx1, zy1),
            "area_m2": zone_w * zone_h,
        }
    return result


def _check_coordinate_overlap(
    geoms: dict[str, dict],
    cad_bounds: tuple[float, float, float, float],
) -> bool:
    """检查分区几何是否与 CAD 坐标空间重叠。

    当 SiteModel 生成的分区坐标 (0~280) 与 CAD 坐标 (40M, 3.6M) 完全不重叠时,
    返回 False, 表示需要将分区对齐到 CAD 坐标空间。
    """
    all_b = [g["bounds"] for g in geoms.values()]
    if not all_b:
        return True

    zx0 = min(b[0] for b in all_b)
    zy0 = min(b[1] for b in all_b)
    zx1 = max(b[2] for b in all_b)
    zy1 = max(b[3] for b in all_b)

    cx0, cy0, cx1, cy1 = cad_bounds
    # 检查 X 和 Y 方向是否有重叠
    overlap_x = max(0, min(zx1, cx1) - max(zx0, cx0))
    overlap_y = max(0, min(zy1, cy1) - max(zy0, cy0))

    return overlap_x > 0 and overlap_y > 0


def _align_to_cad_bounds(
    geoms: dict[str, dict],
    cad_bounds: tuple[float, float, float, float],
):
    """将矩形布局的坐标平移到 CAD 底图坐标空间内。

    确保分区矩形叠加在 CAD 底图可见区域上，居中放置，并按
    CAD 场地尺寸等比缩放。
    """
    # 当前矩形布局的整体范围
    all_bounds = [g["bounds"] for g in geoms.values()]
    if not all_bounds:
        return

    rect_x0 = min(b[0] for b in all_bounds)
    rect_y0 = min(b[1] for b in all_bounds)
    rect_x1 = max(b[2] for b in all_bounds)
    rect_y1 = max(b[3] for b in all_bounds)

    rect_w = rect_x1 - rect_x0
    rect_h = rect_y1 - rect_y0
    if rect_w <= 0 or rect_h <= 0:
        return

    cad_x0, cad_y0, cad_x1, cad_y1 = cad_bounds
    cad_w = cad_x1 - cad_x0
    cad_h = cad_y1 - cad_y0

    # 缩放因子: 让矩形布局占 CAD 区域的 80%
    scale = min(cad_w * 0.8 / rect_w, cad_h * 0.8 / rect_h)

    # 缩放后居中偏移
    scaled_w = rect_w * scale
    scaled_h = rect_h * scale
    offset_x = cad_x0 + (cad_w - scaled_w) / 2 - rect_x0 * scale
    offset_y = cad_y0 + (cad_h - scaled_h) / 2 - rect_y0 * scale

    for name, g in geoms.items():
        bx0, by0, bx1, by1 = g["bounds"]
        new_x0 = bx0 * scale + offset_x
        new_y0 = by0 * scale + offset_y
        new_x1 = bx1 * scale + offset_x
        new_y1 = by1 * scale + offset_y
        g["bounds"] = (new_x0, new_y0, new_x1, new_y1)
        g["centroid"] = ((new_x0 + new_x1) / 2, (new_y0 + new_y1) / 2)
        g["width"] = new_x1 - new_x0
        g["height"] = new_y1 - new_y0
        # 同步变换多边形顶点 (SiteModel / CAD zone polygons)
        if "polygon" in g:
            g["polygon"] = [
                (p[0] * scale + offset_x, p[1] * scale + offset_y)
                for p in g["polygon"]
            ]


# ═══════════════════════════════════════════════════════════════
# 共享专业制图函数 (MeasureMapRenderer + DrawingRenderer 共用)
# ═══════════════════════════════════════════════════════════════

def _safe_text_shared(text: str) -> str:
    """替换字体可能缺失的 Unicode 字符。"""
    return text.replace("²", "2").replace("³", "3").replace("×", "x")


def _nice_scale_number(n: int) -> int:
    """将比例尺分母取整到 1/2/5 × 10^k。"""
    if n <= 0:
        return 1
    exp = math.floor(math.log10(n))
    base = 10 ** exp
    normalized = n / base
    if normalized < 1.5:
        return base
    elif normalized < 3.5:
        return 2 * base
    elif normalized < 7.5:
        return 5 * base
    else:
        return 10 * base


def draw_professional_legend(ax, zones: list[dict], measures_present: list[str]):
    """绘制专业分类彩色图例 (边界线 | 分区 | 工程 | 植物 | 临时)。

    共享: MeasureMapRenderer + DrawingRenderer 都可调用。
    """
    categories: dict[str, list] = {
        "边界线": [], "分区填充": [],
        "工程措施": [], "植物措施": [], "临时措施": [],
    }

    categories["边界线"].append(
        Line2D([0], [0], color="#FF0000", linewidth=2.0,
               linestyle="-", label="项目用地红线"))

    for z in zones:
        name = z.get("name", z) if isinstance(z, dict) else str(z)
        color = get_zone_color(name, professional=True)
        categories["分区填充"].append(
            mpatches.Patch(facecolor=color, edgecolor="#333",
                           alpha=0.5, label=name))

    seen_labels = set()
    for mname in measures_present:
        if mname in seen_labels:
            continue
        seen_labels.add(mname)
        cat = get_measure_category(mname)
        style = get_style(mname, professional=True)
        label = style.get("label", mname[:8])
        color = style.get("color", "#666")
        m_type = style.get("type", "fill")

        if cat in categories:
            if m_type == "line":
                lw = style.get("linewidth", 2.0)
                ls = style.get("linestyle", "-")
                categories[cat].append(
                    Line2D([0], [0], color=color, linewidth=lw,
                           linestyle=ls, label=label))
            elif m_type == "point":
                categories[cat].append(
                    Line2D([0], [0], marker=style.get("marker", "o"),
                           color="w", markerfacecolor=color,
                           markeredgecolor="#333", markersize=8,
                           label=label))
            else:
                categories[cat].append(
                    mpatches.Patch(facecolor=color, edgecolor=color,
                                   alpha=0.5, label=label))

    all_handles = []
    for cat_name in ["边界线", "分区填充", "工程措施", "植物措施", "临时措施"]:
        items = categories.get(cat_name, [])
        if not items:
            continue
        title_patch = mpatches.Patch(facecolor="none", edgecolor="none",
                                      label=f"── {cat_name} ──")
        all_handles.append(title_patch)
        all_handles.extend(items)

    if all_handles:
        ax.legend(
            handles=all_handles,
            loc="upper right",
            fontsize=6,
            framealpha=0.92,
            ncol=1,
            handlelength=1.5,
            handleheight=0.8,
            borderpad=0.5,
            fancybox=True,
            edgecolor="#666",
        )


def draw_coordinate_annotations(ax, boundary_polyline: list[tuple[float, float]] | None):
    """在红线角点标注坐标。

    共享: MeasureMapRenderer + DrawingRenderer 都可调用。
    """
    if not boundary_polyline or len(boundary_polyline) < 3:
        return
    # 选取角点 (均匀取样)
    polygon = boundary_polyline
    max_points = 6
    if len(polygon) <= max_points:
        corners = polygon
    else:
        step = max(1, len(polygon) // max_points)
        corners = [polygon[i] for i in range(0, len(polygon), step)][:max_points]

    for x, y in corners:
        ax.annotate(
            f"X={x:.1f}\nY={y:.1f}",
            xy=(x, y), fontsize=5, color="#CC0000",
            bbox=dict(boxstyle="round,pad=0.2", fc="white",
                      ec="#CC0000", alpha=0.8),
            zorder=ZORDER["decorations"] + 1,
        )


def draw_flow_arrows(ax, placement_engine):
    """绘制排水方向箭头。

    共享: MeasureMapRenderer + DrawingRenderer 都可调用。
    """
    if placement_engine is None:
        return
    model = getattr(placement_engine, '_model', None)
    if model is None:
        return
    terrain = getattr(model, 'terrain', None)
    if terrain is None:
        return

    slope_direction = getattr(terrain, 'slope_direction', None)
    if not slope_direction:
        return

    dir_map = {
        "N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0),
        "NE": (0.7, 0.7), "NW": (-0.7, 0.7),
        "SE": (0.7, -0.7), "SW": (-0.7, -0.7),
    }
    direction = dir_map.get(slope_direction)
    if not direction:
        return

    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    cx = (xlim[0] + xlim[1]) / 2
    cy = (ylim[0] + ylim[1]) / 2
    dx = (xlim[1] - xlim[0]) * 0.08
    dy = (ylim[1] - ylim[0]) * 0.08

    ax.annotate(
        "", xy=(cx + direction[0] * dx, cy + direction[1] * dy),
        xytext=(cx, cy),
        arrowprops=dict(arrowstyle="-|>", color="#1E90FF",
                        lw=2.0, mutation_scale=15),
        zorder=ZORDER["flow_arrows"],
    )
    ax.text(cx + direction[0] * dx * 1.3, cy + direction[1] * dy * 1.3,
            "排水方向", fontsize=6, color="#1E90FF", ha="center",
            fontweight="bold", zorder=ZORDER["flow_arrows"])


def draw_measure_table(ax, measures: list[dict]):
    """在图面右下区域嵌入措施汇总表。

    共享: MeasureMapRenderer + DrawingRenderer 都可调用。
    """
    if not measures:
        return

    table_data = []
    seen = set()
    for m in measures:
        zone = m.get("分区", m.get("zone", ""))
        name = m.get("措施名称", m.get("name", ""))
        mtype = get_measure_category(name)
        qty = m.get("数量", "")
        unit = str(m.get("单位", "")).replace("²", "2").replace("³", "3")
        key = (zone, name)
        if key in seen:
            continue
        seen.add(key)
        table_data.append([
            zone[:6] if len(zone) > 6 else zone,
            name[:8] if len(name) > 8 else name,
            mtype[:4],
            str(qty),
            str(unit),
        ])

    if not table_data:
        return

    if len(table_data) > 15:
        table_data = table_data[:14]
        table_data.append(["...", "...", "...", "...", "..."])

    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    dx = xlim[1] - xlim[0]
    dy = ylim[1] - ylim[0]

    header_text = "水土保持措施汇总表"
    lines = [header_text, "-" * 36]
    lines.append(f"{'分区':^6s}|{'措施':^8s}|{'类型':^4s}|{'数量':^6s}|{'单位':^4s}")
    lines.append("-" * 36)
    for row in table_data:
        lines.append(f"{row[0]:^6s}|{row[1]:^8s}|{row[2]:^4s}|{row[3]:^6s}|{row[4]:^4s}")

    table_text = "\n".join(lines)
    text_kw = dict(
        fontsize=5, va="bottom", ha="right",
        bbox=dict(boxstyle="round,pad=0.4", fc="white",
                  ec="#666", alpha=0.9, linewidth=0.5),
        zorder=ZORDER["title_block"],
    )
    if _CN_FONT:
        text_kw["fontproperties"] = _CN_FONT
    ax.text(
        xlim[1] - dx * 0.02, ylim[0] + dy * 0.02,
        table_text, **text_kw,
    )


def draw_title_block(fig, title: str, ax, spatial_layout: dict | None = None):
    """绘制专业图签框 (底部)。

    共享: MeasureMapRenderer + DrawingRenderer 都可调用。
    """
    project_name = ""
    if isinstance(spatial_layout, dict):
        project_name = spatial_layout.get("project_name", "")

    xlim = ax.get_xlim()
    fig_w_inches = fig.get_size_inches()[0]
    dx = xlim[1] - xlim[0]
    scale_text = ""
    if fig_w_inches > 0 and dx > 0:
        scale_n = int(dx / (fig_w_inches * 0.0254))
        if scale_n > 0:
            scale_text = f"1:{_nice_scale_number(scale_n)}"

    date_str = datetime.date.today().strftime("%Y.%m")

    parts = []
    if project_name:
        parts.append(f"项目: {_safe_text_shared(project_name)}")
    parts.append(f"图名: {_safe_text_shared(title)}")
    if scale_text:
        parts.append(f"比例: {scale_text}")
    parts.append(f"日期: {date_str}")
    tb_text = "  |  ".join(parts)

    fig.text(0.5, 0.01, tb_text, fontsize=7, ha="center", va="bottom",
             bbox=dict(boxstyle="round,pad=0.4", fc="#F8F8F8",
                       ec="#333333", linewidth=1.2),
             zorder=20)


# ═══════════════════════════════════════════════════════════════
# 标签碰撞避让器
# ═══════════════════════════════════════════════════════════════

class LabelPlacer:
    """轻量级标签批量避让器。收集所有标签后, 用贪心法偏移碰撞标签。"""

    def __init__(self, ax):
        self._ax = ax
        self._labels = []  # [{x, y, text, fontsize, kwargs}]

    def add(self, x, y, text, fontsize=7, **kwargs):
        """注册标签候选位置 (暂不绘制)。"""
        self._labels.append({"x": x, "y": y, "text": text,
                             "fontsize": fontsize, "kwargs": kwargs})

    def render_all(self):
        """批量避让后绘制所有标签 — 4 方向避让 + 偏移引线。"""
        if not self._labels:
            return

        xlim = self._ax.get_xlim()
        ylim = self._ax.get_ylim()
        dx = xlim[1] - xlim[0]
        dy = ylim[1] - ylim[0]
        if dx <= 0 or dy <= 0:
            dx = dy = 1.0

        placed = []  # [(x, y, w, h)]
        self._labels.sort(key=lambda l: (l["x"], l["y"]))

        for lbl in self._labels:
            x, y = lbl["x"], lbl["y"]
            orig_x, orig_y = x, y
            n_chars = max(len(lbl["text"].replace("\n", "")), 1)
            n_lines = lbl["text"].count("\n") + 1
            est_w = dx * 0.006 * n_chars
            est_h = dy * 0.018 * n_lines

            # 4 方向避让: 上→右→下→左, 每轮递增偏移
            shifted = False
            for attempt in range(1, 8):
                collision = False
                for px, py, pw, ph in placed:
                    if abs(x - px) < (est_w + pw) / 2 and abs(y - py) < (est_h + ph) / 2:
                        collision = True
                        break
                if not collision:
                    break
                # 4方向轮替
                direction = attempt % 4
                step = ((attempt - 1) // 4 + 1) * est_h * 0.6
                if direction == 0:
                    y = orig_y + step      # 上
                elif direction == 1:
                    x = orig_x + step      # 右
                elif direction == 2:
                    y = orig_y - step      # 下
                else:
                    x = orig_x - step      # 左
                shifted = True

            placed.append((x, y, est_w, est_h))
            kw = dict(lbl["kwargs"])  # 复制以避免修改原始
            self._ax.text(
                x, y, lbl["text"], fontsize=lbl["fontsize"],
                ha=kw.pop("ha", "center"), va=kw.pop("va", "center"),
                bbox=kw.pop("bbox", dict(boxstyle="round,pad=0.2",
                                          fc="white", alpha=0.8)),
                zorder=kw.pop("zorder", ZORDER["labels"]),
                **kw,
            )

            # 偏移标签加引线
            if shifted and (abs(x - orig_x) > est_w * 0.3 or abs(y - orig_y) > est_h * 0.3):
                self._ax.annotate(
                    "", xy=(orig_x, orig_y), xytext=(x, y),
                    arrowprops=dict(arrowstyle="-", color="#999", lw=0.5),
                    zorder=ZORDER["labels"] - 1)


# ═══════════════════════════════════════════════════════════════
# 主渲染器
# ═══════════════════════════════════════════════════════════════

class MeasureMapRenderer:
    """水土保持措施图渲染器。"""

    def __init__(
        self,
        zones: list[dict],
        measures: list[dict],
        spatial_layout: dict | None = None,
        gis_gdf: Any = None,
        atlas_conventions: dict | None = None,
        output_dir: Path | None = None,
        cad_geometry: Any = None,
        cad_dxf_path: str | None = None,
        cad_site_features: Any = None,
        placement_engine: Any = None,
    ):
        """
        Args:
            zones: 分区列表 (含 name, area_hm2, area_m2)
            measures: 措施列表 (含 措施名称, 分区, 类型, 空间布置 等)
            spatial_layout: VL+GIS 空间分析结果
            gis_gdf: GeoDataFrame (可选, 有则用真实几何)
            atlas_conventions: 图集 RAG 查询的规范 (可选)
            output_dir: 输出目录
            cad_geometry: CadGeometry 对象 (可选, 有则渲染 CAD 底图背景)
            cad_dxf_path: DXF 文件路径 (可选, 有则用 ezdxf 原生高清渲染)
            cad_site_features: CadSiteFeatures (可选, 有则用智能措施布局)
            placement_engine: PlacementEngine 实例 (可选, 有则用新架构布局)
        """
        self.zones = zones
        self.measures = measures
        self.spatial_layout = spatial_layout or {}
        self.gis_gdf = gis_gdf
        self.atlas_conventions = atlas_conventions or {}
        self.output_dir = output_dir or Path("data/output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._cad_geometry = cad_geometry
        self._cad_site_features = cad_site_features
        self._placement_engine = placement_engine  # 新架构
        self._cad_renderer = None
        if cad_geometry is not None:
            from src.cad_base_renderer import CadBaseMapRenderer
            # 优先用聚类/红线 bbox (精确), 回退到 content_bounds (建筑+道路)
            focus = None
            if cad_site_features is not None:
                focus = getattr(cad_site_features, 'cluster_bounds', None)
            if focus is None:
                focus = cad_geometry.content_bounds
            self._cad_renderer = CadBaseMapRenderer(
                cad_geometry, dxf_path=cad_dxf_path, focus_bounds=focus)
        self._resolver = None
        if placement_engine is not None:
            self._resolver = placement_engine

        # 预计算分区几何 (矩形近似或 GIS 真实多边形 或 CAD 凸包)
        self._zone_geometries = self._build_zone_geometries()

    # ── 分区几何构建 (委托到模块级函数) ────────────────────────

    def _build_zone_geometries(self) -> dict[str, dict]:
        """薄包装: 委托到模块级 build_zone_geometries。"""
        # 优先使用聚类边界 (仅主图簇) 而非全域 CAD 边界
        cluster_b = getattr(self._cad_site_features, 'cluster_bounds', None) if self._cad_site_features else None
        cad_bounds = cluster_b or (self._cad_geometry.bounds if self._cad_geometry else None)
        cad_content = cluster_b or (self._cad_geometry.content_bounds if self._cad_geometry else None)
        # 从 PlacementEngine 获取 SiteModel (如果是新架构)
        site_model = None
        if self._placement_engine is not None:
            site_model = getattr(self._placement_engine, '_model', None)
        return build_zone_geometries(self.zones, self.gis_gdf,
                                     cad_bounds=cad_bounds,
                                     cad_content_bounds=cad_content,
                                     cad_site_features=self._cad_site_features,
                                     site_model=site_model)

    # ── 图1: 项目分区图 ────────────────────────────────────────

    def render_zone_boundary_map(self) -> Path:
        """渲染项目分区图: 分区边界 + 面积标注 + 图例。"""
        dpi = MAP_DEFAULTS["dpi"]
        fig, ax = plt.subplots(figsize=MAP_DEFAULTS["figsize_single"], dpi=dpi)

        # CAD 全色底图 (作为图面主体)
        if self._cad_renderer:
            self._cad_renderer.render_foreground(ax, highlight_boundary=True)

        legend_patches = []

        for z in self.zones:
            name = z["name"]
            geom = self._zone_geometries.get(name)
            if not geom:
                continue

            color = get_zone_color(name, professional=True)
            area_hm2 = z["area_hm2"]

            if geom["type"] == "gis":
                self._plot_gis_polygon(ax, geom["geometry"], color, name, alpha=0.4)
            elif "polygon" in geom and len(geom.get("polygon", [])) >= 3:
                polygon = geom["polygon"]
                xs = [p[0] for p in polygon] + [polygon[0][0]]
                ys = [p[1] for p in polygon] + [polygon[0][1]]
                ax.fill(xs, ys, facecolor=color, edgecolor="#333333",
                        linewidth=1.5, alpha=0.4)
            else:
                continue  # 跳过无真实几何的分区

            # 面积标注
            cx, cy = geom["centroid"]
            ax.text(cx, cy, f"{name}\n{area_hm2} hm2",
                    ha="center", va="center",
                    fontsize=MAP_DEFAULTS["label_fontsize"],
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.85))

            legend_patches.append(mpatches.Patch(
                facecolor=color, edgecolor="#333", alpha=0.6,
                label=f"{name} ({area_hm2} hm2)"))

        # 装饰
        ax.set_title("水土保持防治分区图", fontsize=MAP_DEFAULTS["title_fontsize"],
                      fontweight="bold", pad=15)
        ax.legend(handles=legend_patches, loc="lower right",
                  fontsize=MAP_DEFAULTS["legend_fontsize"],
                  framealpha=0.9, title="图例")
        ax.set_aspect("equal")
        self._set_content_view_limits(ax)
        self._add_map_decorations(ax, fig=fig)

        path = self.output_dir / "zone_boundary_map.png"
        fig.savefig(str(path), dpi=dpi, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        logger.info(f"分区图已生成: {path}")
        return path

    # ── 图2: 措施总体布置图 ────────────────────────────────────

    def render_measure_layout_map(self) -> Path:
        """渲染措施总体布置图: CAD全色底图 + 彩色措施叠加 + 专业制图元素。"""
        dpi = MAP_DEFAULTS["dpi"]
        fig, ax = plt.subplots(figsize=MAP_DEFAULTS["figsize_single"], dpi=dpi)

        # 1. CAD 全色底图 (作为图面主体)
        if self._cad_renderer:
            self._cad_renderer.render_foreground(ax, highlight_boundary=True)

        # 2. 分区用半透明边界线标识 (不再填充矩形)
        for z in self.zones:
            name = z["name"]
            geom = self._zone_geometries.get(name)
            if not geom:
                continue
            color = get_zone_color(name, professional=True)
            if geom["type"] == "gis":
                self._plot_gis_polygon(ax, geom["geometry"], color, name, alpha=0.2)
            elif geom["type"] == "cad":
                polygon = geom["polygon"]
                xs = [p[0] for p in polygon] + [polygon[0][0]]
                ys = [p[1] for p in polygon] + [polygon[0][1]]
                # 半透明填充 + 彩色实线边界
                ax.fill(xs, ys, facecolor=color, edgecolor=color,
                        linewidth=1.8, alpha=0.25, linestyle="-",
                        zorder=ZORDER["zone_fill"])
                ax.text(geom["centroid"][0], geom["centroid"][1],
                        name, ha="center", va="center",
                        fontsize=8, fontweight="bold", color="#333",
                        bbox=dict(boxstyle="round,pad=0.2",
                                  facecolor="white", alpha=0.85, edgecolor=color,
                                  linewidth=0.8),
                        zorder=ZORDER["labels"])
            elif "polygon" in geom and len(geom.get("polygon", [])) >= 3:
                # site_model 或其他带 polygon 的类型 → 使用真实多边形
                polygon = geom["polygon"]
                xs = [p[0] for p in polygon] + [polygon[0][0]]
                ys = [p[1] for p in polygon] + [polygon[0][1]]
                ax.fill(xs, ys, facecolor=color, edgecolor=color,
                        linewidth=1.8, alpha=0.25, linestyle="-",
                        zorder=ZORDER["zone_fill"])
                ax.text(geom["centroid"][0], geom["centroid"][1],
                        name, ha="center", va="center",
                        fontsize=8, fontweight="bold", color="#333",
                        bbox=dict(boxstyle="round,pad=0.2",
                                  facecolor="white", alpha=0.85, edgecolor=color,
                                  linewidth=0.8),
                        zorder=ZORDER["labels"])
            else:
                continue  # 跳过无真实几何的分区

        # 3. 叠加彩色措施 (按 z-order 排序: fill(面) → line(线) → point(点))
        _TYPE_ORDER = {"fill": 0, "line": 1, "point": 2}
        sorted_measures = sorted(
            self.measures,
            key=lambda m: _TYPE_ORDER.get(
                get_style(m.get("措施名称", m.get("name", "")), professional=True).get("type", "fill"), 0
            )
        )
        legend_handles = {}
        label_placer = LabelPlacer(ax)
        for m in sorted_measures:
            measure_name = m.get("措施名称", m.get("name", ""))
            zone_name = m.get("分区", m.get("zone", ""))
            style = get_style(measure_name, professional=True)
            zone_geom = self._zone_geometries.get(zone_name)
            if not zone_geom:
                continue
            self._draw_measure(ax, m, style, zone_geom, legend_handles,
                               label_placer=label_placer)

        # 先设置视图范围, 再渲染标签 (LabelPlacer 需要 xlim/ylim)
        ax.set_aspect("equal")
        self._set_content_view_limits(ax)
        label_placer.render_all()

        # 4. 专业分类图例
        measures_present = [
            m.get("措施名称", m.get("name", "")) for m in self.measures
        ]
        self._draw_professional_legend(ax, measures_present)

        # 5. 坐标标注
        self._draw_coordinate_annotations(ax)

        # 6. 水流方向箭头
        self._draw_flow_arrows(ax)

        ax.set_title("水土保持措施总体布置图",
                      fontsize=MAP_DEFAULTS["title_fontsize"],
                      fontweight="bold", pad=15)
        self._add_map_decorations(ax, fig=fig)

        # 7. 图签
        self._draw_title_block(fig, "水土保持措施总体布置图", ax)

        # 8. 措施汇总表
        self._draw_measure_table(ax)

        path = self.output_dir / "measure_layout_map.png"
        fig.savefig(str(path), dpi=dpi, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        logger.info(f"总布置图已生成: {path}")
        return path

    # ── 图3: 分区措施详图 ──────────────────────────────────────

    def render_zone_detail_maps(self, skip_tags: set[str] | None = None) -> dict[str, Path]:
        """为每个有措施的分区渲染详图。"""
        _skip = skip_tags or set()
        results = {}
        dpi = MAP_DEFAULTS["dpi"]

        # 按分区分组措施
        zone_measures = {}
        for m in self.measures:
            zone = m.get("分区", m.get("zone", ""))
            if zone not in zone_measures:
                zone_measures[zone] = []
            zone_measures[zone].append(m)

        for z in self.zones:
            name = z["name"]
            if name not in zone_measures:
                continue
            geom = self._zone_geometries.get(name)
            if not geom:
                continue

            safe_name = name.replace("(", "").replace(")", "").replace("/", "_")
            tag = f"zone_detail_{safe_name}"
            if tag in _skip:
                continue

            fig, ax = plt.subplots(figsize=MAP_DEFAULTS["figsize_detail"], dpi=dpi)

            # CAD 全色底图 (裁剪到分区范围, 不绘制全域红线)
            if self._cad_renderer:
                crop = geom.get("bounds")
                self._cad_renderer.render_foreground(ax, crop_bounds=crop,
                                                      highlight_boundary=False)

            # 分区边界高亮 (粗彩色边框 + 浅填充)
            color = get_zone_color(name, professional=True)
            if geom["type"] == "gis":
                self._plot_gis_polygon(ax, geom["geometry"], color, name, alpha=0.2)
            elif "polygon" in geom and len(geom.get("polygon", [])) >= 3:
                polygon = geom["polygon"]
                xs = [p[0] for p in polygon] + [polygon[0][0]]
                ys = [p[1] for p in polygon] + [polygon[0][1]]
                ax.fill(xs, ys, facecolor=color, edgecolor=color,
                        linewidth=2.5, alpha=0.15)
                ax.plot(xs, ys, color=color, linewidth=2.5,
                        linestyle="-", zorder=8)

            # 绘制该分区的所有措施 (放大标注, 彩色)
            legend_handles = {}
            for m in zone_measures[name]:
                measure_name = m.get("措施名称", m.get("name", ""))
                style = get_style(measure_name, professional=True)
                self._draw_measure(ax, m, style, geom, legend_handles, detail=True)

            # 装饰
            if legend_handles:
                handles = [h for h in legend_handles.values()
                           if not str(getattr(h, '_label', '')).startswith('_')]
                if handles:
                    ax.legend(handles=handles,
                              loc="lower right",
                              fontsize=MAP_DEFAULTS["legend_fontsize"],
                              framealpha=0.9)

            ax.set_title(f"{name} — 措施详图",
                          fontsize=MAP_DEFAULTS["title_fontsize"],
                          fontweight="bold", pad=15)
            ax.set_aspect("equal")
            if geom["type"] != "gis":
                bounds = geom["bounds"]
                margin = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.1
                ax.set_xlim(bounds[0] - margin, bounds[2] + margin)
                ax.set_ylim(bounds[1] - margin, bounds[3] + margin)
            else:
                ax.autoscale()
            self._add_map_decorations(ax, fig=fig)

            # 图签
            self._draw_title_block(fig, f"{name} — 措施详图", ax)

            path = self.output_dir / f"{tag}.png"
            # 安全检查: 预估像素尺寸, 超限时降低 DPI
            save_dpi = dpi
            fig_w, fig_h = fig.get_size_inches()
            max_px = 65000
            est_w, est_h = fig_w * save_dpi, fig_h * save_dpi
            if est_w > max_px or est_h > max_px:
                scale = max_px / max(est_w, est_h)
                save_dpi = max(72, int(save_dpi * scale))
                logger.warning(
                    f"分区详图像素预估 {est_w:.0f}x{est_h:.0f} 超限, "
                    f"降低 DPI: {dpi}→{save_dpi}"
                )
            fig.savefig(str(path), dpi=save_dpi, bbox_inches="tight",
                        facecolor="white", edgecolor="none")
            plt.close(fig)
            results[tag] = path
            logger.info(f"分区详图已生成: {path.name}")

        return results

    # ── 图4: 典型工程断面图 ────────────────────────────────────

    def render_typical_sections(self, skip_tags: set[str] | None = None) -> dict[str, Path]:
        """渲染典型工程断面图。"""
        _skip = skip_tags or set()
        results = {}
        dpi = MAP_DEFAULTS["dpi"]

        # 找出需要断面图的措施 (使用共享模糊匹配)
        rendered_types = set()
        for m in self.measures:
            name = m.get("措施名称", m.get("name", ""))
            matched = match_section_template(name)
            if matched:
                tmpl_key, tmpl = matched
                if tmpl_key not in rendered_types:
                    rendered_types.add(tmpl_key)

                    safe_name = tmpl_key.replace("(", "").replace(")", "")
                    safe_name = safe_name.replace("×", "x").replace("/", "_")
                    tag = f"typical_section_{safe_name}"
                    if tag in _skip:
                        continue

                    fig, ax = plt.subplots(
                        figsize=MAP_DEFAULTS["figsize_section"], dpi=dpi)
                    self._draw_section(ax, tmpl_key, tmpl)

                    path = self.output_dir / f"{tag}.png"
                    fig.savefig(str(path), dpi=dpi, bbox_inches="tight",
                                facecolor="white", edgecolor="none")
                    plt.close(fig)
                    results[tag] = path
                    logger.info(f"断面图已生成: {path.name}")

        return results

    # ── 综合渲染 ────────────────────────────────────────────────

    def render_all(self, skip_tags: set[str] | None = None) -> dict[str, Path]:
        """生成所有措施图，返回 {tag_name: png_path}。

        Args:
            skip_tags: 已由 Drawing Agent 生成的 tag 集合，跳过以避免覆盖。
        """
        _skip = skip_tags or set()
        result = {}

        if "zone_boundary_map" not in _skip:
            try:
                result["zone_boundary_map"] = self.render_zone_boundary_map()
            except Exception as e:
                logger.error(f"分区图渲染失败: {e}")

        if "measure_layout_map" not in _skip:
            try:
                result["measure_layout_map"] = self.render_measure_layout_map()
            except Exception as e:
                logger.error(f"总布置图渲染失败: {e}")

        try:
            detail_maps = self.render_zone_detail_maps(skip_tags=_skip)
            result.update(detail_maps)
        except Exception as e:
            logger.error(f"分区详图渲染失败: {e}")

        try:
            sections = self.render_typical_sections(skip_tags=_skip)
            result.update(sections)
        except Exception as e:
            logger.error(f"断面图渲染失败: {e}")

        logger.info(f"措施图渲染完成: {len(result)} 张")
        return result

    # ═══════════════════════════════════════════════════════════
    # 辅助绘图方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _safe_text(text: str) -> str:
        """替换字体可能缺失的 Unicode 字符 (上标数字等)。"""
        return text.replace("²", "2").replace("³", "3").replace("×", "x")

    def _plot_gis_polygon(self, ax, geometry, color: str, name: str,
                           alpha: float = 0.5):
        """绘制 GIS 多边形。"""
        try:
            from shapely.geometry import mapping
            geom_type = geometry.geom_type
            if geom_type == "Polygon":
                xs, ys = geometry.exterior.xy
                ax.fill(xs, ys, facecolor=color, edgecolor="#000",
                        linewidth=1.5, alpha=alpha)
            elif geom_type == "MultiPolygon":
                for poly in geometry.geoms:
                    xs, ys = poly.exterior.xy
                    ax.fill(xs, ys, facecolor=color, edgecolor="#000",
                            linewidth=1.5, alpha=alpha)
        except Exception as e:
            logger.warning(f"GIS 多边形绘制失败 ({name}): {e}")

    def _draw_measure(self, ax, measure: dict, style: dict,
                       zone_geom: dict, legend_handles: dict,
                       detail: bool = False, label_placer: LabelPlacer | None = None):
        """在指定分区上绘制单个措施符号 (仅通过 PlacementEngine 解算)。"""
        label = style.get("label", measure.get("措施名称", "")[:8])
        bounds = zone_geom.get("bounds", (0, 0, 100, 100))

        measure_name = measure.get("措施名称", measure.get("name", ""))
        zone_name = measure.get("分区", measure.get("zone", ""))
        if not self._resolver:
            logger.debug(f"无 resolver, 跳过措施: {measure_name}")
            return

        # 查找预计算结果
        resolved = None
        if hasattr(self._resolver, 'get_placement'):
            resolved = self._resolver.get_placement(measure_name, zone_name)
        # 实时计算
        if resolved is None:
            resolved = self._resolver.resolve(
                measure_name, zone_name, zone_bounds=bounds,
            )
        if resolved:
            self._draw_resolved_measure(
                ax, resolved, style, label, legend_handles, detail,
                measure, label_placer=label_placer,
            )
        else:
            # Fallback: 根据样式类型生成默认几何
            m_type = style.get("type", "fill")
            fallback = self._generate_fallback_geometry(m_type, bounds)
            if fallback:
                logger.debug(f"resolver 未返回结果, 使用 fallback 渲染: {measure_name} ({m_type})")
                self._draw_resolved_measure(
                    ax, fallback, style, label, legend_handles, detail,
                    measure, label_placer=label_placer)
            else:
                logger.debug(f"resolver 未返回结果且无 fallback, 跳过措施: {measure_name}")

    @staticmethod
    def _generate_fallback_geometry(m_type: str, bounds: tuple) -> dict | None:
        """当 resolver 无结果时，根据样式类型在 zone_bounds 内生成默认几何。"""
        x0, y0, x1, y1 = bounds
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            return None
        margin = min(w, h) * 0.08
        if m_type == "line":
            # 沿底边和右侧边缘
            return {"polyline": [
                (x0 + margin, y0 + margin),
                (x1 - margin, y0 + margin),
                (x1 - margin, y1 - margin),
            ]}
        elif m_type == "fill":
            return {"polygon": [
                (x0 + margin, y0 + margin),
                (x1 - margin, y0 + margin),
                (x1 - margin, y1 - margin),
                (x0 + margin, y1 - margin),
            ]}
        elif m_type == "point":
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            return {"points": [(cx, cy)]}
        return None

    def _draw_resolved_measure(
        self, ax, resolved: dict, style: dict, label: str,
        legend_handles: dict, detail: bool, measure: dict,
        label_placer: LabelPlacer | None = None,
    ):
        """绘制 resolver 返回的精确几何措施 (彩色渲染)。"""
        color = style.get("color", "#666")
        # 获取专业色覆盖
        measure_name = measure.get("措施名称", measure.get("name", ""))
        pro_color = get_measure_color(measure_name)
        if pro_color:
            color = pro_color

        # 获取标签锚点 (label_anchor)
        label_anchor = resolved.get("label_anchor")

        if "polyline" in resolved:
            pts = resolved["polyline"]
            if len(pts) >= 2:
                lw = style.get("linewidth", 2.0)
                # 全局图上线宽加粗以确保可见 (detail=False 时)
                if not detail:
                    lw = max(lw * 2.0, 4.0)
                ls = style.get("linestyle", "-")
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                # 白色底层描边 (增加对比度)
                ax.plot(xs, ys, color="white", linewidth=lw + 2,
                        linestyle="-", zorder=ZORDER["measure_line"] - 0.5,
                        solid_capstyle="round")
                line, = ax.plot(xs, ys, color=color, linewidth=lw,
                                linestyle=ls, zorder=ZORDER["measure_line"])
                if label not in legend_handles:
                    legend_handles[label] = line
                # 方向箭头 (在线中间位置)
                if len(pts) >= 3:
                    mid = len(pts) // 2
                    dx = pts[mid][0] - pts[mid - 1][0]
                    dy = pts[mid][1] - pts[mid - 1][1]
                    ax.annotate("", xy=(pts[mid][0], pts[mid][1]),
                                xytext=(pts[mid][0] - dx * 0.3,
                                        pts[mid][1] - dy * 0.3),
                                arrowprops=dict(arrowstyle="->", color=color,
                                                lw=1.5),
                                zorder=ZORDER["measure_line"] + 1)
                if not label_anchor:
                    label_anchor = pts[len(pts) // 2]
                if detail:
                    qty = measure.get("数量", "")
                    unit = measure.get("单位", "")
                    lbl_text = self._safe_text(f"{label}\n{qty}{unit}")
                    if label_placer:
                        label_placer.add(label_anchor[0], label_anchor[1], lbl_text)
                    else:
                        ax.annotate(
                            lbl_text, xy=label_anchor,
                            fontsize=7, ha="center",
                            bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.8),
                            zorder=ZORDER["labels"],
                        )
                elif label_placer:
                    label_placer.add(label_anchor[0], label_anchor[1], label, fontsize=6)

        elif "polygon" in resolved:
            pts = resolved["polygon"]
            if len(pts) >= 3:
                alpha = 0.45 if detail else 0.35  # 全局图稍透明, 详图更深
                xs = [p[0] for p in pts] + [pts[0][0]]
                ys = [p[1] for p in pts] + [pts[0][1]]
                # 彩色填充 + 深色边框
                import matplotlib.colors as mcolors
                try:
                    rgb = mcolors.to_rgb(color)
                    edge_color = tuple(max(0, c * 0.6) for c in rgb)
                except Exception:
                    edge_color = color
                ax.fill(xs, ys, facecolor=color, edgecolor=edge_color,
                        linewidth=1.2, alpha=alpha, zorder=ZORDER["measure_area"])
                if label not in legend_handles:
                    legend_handles[label] = mpatches.Patch(
                        facecolor=color, edgecolor=edge_color,
                        alpha=alpha, label=label)
                if not label_anchor:
                    label_anchor = (sum(p[0] for p in pts) / len(pts),
                                    sum(p[1] for p in pts) / len(pts))
                if detail:
                    qty = measure.get("数量", "")
                    unit = measure.get("单位", "")
                    lbl_text = self._safe_text(f"{label}\n{qty}{unit}")
                    if label_placer:
                        label_placer.add(label_anchor[0], label_anchor[1], lbl_text)
                    else:
                        ax.text(label_anchor[0], label_anchor[1], lbl_text,
                                ha="center", va="center", fontsize=6,
                                bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.8),
                                zorder=ZORDER["labels"])
                elif label_placer:
                    label_placer.add(label_anchor[0], label_anchor[1], label, fontsize=6)

        elif "points" in resolved:
            pts = resolved["points"]
            marker = style.get("marker", "o")
            size = style.get("size", 80)
            if not detail:
                size = max(size * 1.5, 120)  # 全局图上放大点标记
            for px, py in pts:
                ax.scatter(px, py, c=color, marker=marker, s=size,
                           zorder=ZORDER["measure_point"], edgecolors="#333", linewidths=0.8)
            if label not in legend_handles and pts:
                legend_handles[label] = ax.scatter(
                    [], [], c=color, marker=marker, s=size,
                    edgecolors="#333", linewidths=0.8, label=label)
            if not label_anchor and pts:
                label_anchor = pts[0]
            if detail and label_anchor:
                qty = measure.get("数量", "")
                unit = measure.get("单位", "")
                lbl_text = self._safe_text(f"{label}\n{qty}{unit}")
                if label_placer:
                    label_placer.add(label_anchor[0], label_anchor[1], lbl_text)
                else:
                    ax.annotate(
                        lbl_text, xy=label_anchor,
                        xytext=(10, 10), textcoords="offset points",
                        fontsize=7, ha="left",
                        arrowprops=dict(arrowstyle="->", color=color),
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.8),
                        zorder=ZORDER["labels"],
                    )
            elif label_placer and label_anchor:
                label_placer.add(label_anchor[0], label_anchor[1], label, fontsize=6)

    # ── 断面图绘制 ─────────────────────────────────────────────

    def _draw_section(self, ax, name: str, tmpl: dict):
        """绘制典型工程断面图。"""
        shape = tmpl.get("shape", "rectangular_channel")

        if shape == "rectangular_channel":
            self._draw_channel_section(ax, name, tmpl)
        elif shape == "gravity_wall":
            self._draw_wall_section(ax, name, tmpl)
        elif shape == "sedimentation_tank":
            self._draw_tank_section(ax, name, tmpl)
        elif shape == "chute":
            self._draw_channel_section(ax, name, tmpl)
        elif shape == "trapezoidal_channel":
            self._draw_trapezoidal_section(ax, name, tmpl)
        elif shape == "pavement_section":
            self._draw_pavement_section(ax, name, tmpl)
        elif shape == "wash_platform":
            self._draw_wash_platform_section(ax, name, tmpl)
        else:
            self._draw_channel_section(ax, name, tmpl)

        ax.set_title(f"典型断面 — {self._safe_text(name)}", fontsize=12, fontweight="bold")
        ax.set_xlabel("宽度 (m)", fontsize=9)
        ax.set_ylabel("深度 (m)", fontsize=9)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)

    def _draw_channel_section(self, ax, name: str, tmpl: dict):
        """矩形排水沟/截水沟断面。"""
        w = tmpl.get("width", 0.4)
        d = tmpl.get("depth", 0.4)
        tw = tmpl.get("wall_thickness", 0.08)
        tf = tmpl.get("floor_thickness", 0.08)
        mat = tmpl.get("material", "C20混凝土")

        # 外轮廓 (混凝土 — 灰色斜线填充)
        outer_x = [-tw, w + tw, w + tw, -tw, -tw]
        outer_y = [0, 0, -(d + tf), -(d + tf), 0]
        ax.fill(outer_x, outer_y, color="#C0C0C0", edgecolor="#000",
                linewidth=1.5, hatch="///", label=mat)

        # 内腔 (水流空间 — 白色)
        inner_x = [0, w, w, 0, 0]
        inner_y = [0, 0, -d, -d, 0]
        ax.fill(inner_x, inner_y, color="white", edgecolor="#000",
                linewidth=1.0, label="水流断面")

        # 地面线
        ground_ext = max(w, 0.5)
        ax.plot([-ground_ext, -tw], [0, 0], "k-", linewidth=2)
        ax.plot([w + tw, w + ground_ext + 0.5], [0, 0], "k-", linewidth=2)
        # 地面填充 (土体 — 点阵)
        ax.fill_between([-ground_ext, -tw], [0, 0], [0.15, 0.15],
                        color="#D0D0D0", alpha=0.5, hatch="...")
        ax.fill_between([w + tw, w + ground_ext + 0.5], [0, 0], [0.15, 0.15],
                        color="#D0D0D0", alpha=0.5)

        # 尺寸标注
        self._dim_line(ax, 0, -d - tf - 0.15, w, -d - tf - 0.15, f"{w*100:.0f}cm")
        self._dim_line_v(ax, w + tw + 0.1, 0, w + tw + 0.1, -d, f"{d*100:.0f}cm")
        self._dim_line_v(ax, -tw - 0.15, 0, -tw - 0.15, -(d + tf),
                          f"{(d+tf)*100:.0f}cm")

        ax.legend(loc="upper right", fontsize=7)

    def _draw_wall_section(self, ax, name: str, tmpl: dict):
        """重力式挡土墙断面。"""
        h = tmpl.get("height", 2.0)
        tw = tmpl.get("top_width", 0.5)
        bw = tmpl.get("bottom_width", 1.2)
        fd = tmpl.get("foundation_depth", 0.5)
        mat = tmpl.get("material", "M7.5浆砌石")

        # 墙体 (梯形 — 浆砌石交叉填充)
        wall_x = [0, tw, bw, 0, 0]
        wall_y = [h, h, 0, 0, h]
        ax.fill(wall_x, wall_y, color="#A0A0A0", edgecolor="#000",
                linewidth=1.5, hatch="xxx", label=mat)

        # 基础 (斜线填充)
        base_w = bw + 0.3
        ax.fill([-0.15, base_w, base_w, -0.15, -0.15],
                [0, 0, -fd, -fd, 0],
                color="#C0C0C0", edgecolor="#000", linewidth=1.0,
                hatch="///", label="基础")

        # 回填土 (点阵填充)
        ax.fill([bw, bw + 1.5, bw + 1.5, bw + 0.3, bw],
                [0, 0, h * 0.7, h, h],
                color="#D0D0D0", alpha=0.5, hatch="...", label="回填土")

        # 地面线
        ax.plot([-1, 0], [0, 0], "k-", linewidth=2)
        ax.plot([bw, bw + 2], [0, 0], "k-", linewidth=2)

        # 标注
        self._dim_line_v(ax, -0.3, 0, -0.3, h, f"{h:.1f}m")
        self._dim_line(ax, 0, h + 0.15, tw, h + 0.15, f"{tw:.1f}m")
        self._dim_line(ax, 0, -fd - 0.2, bw, -fd - 0.2, f"{bw:.1f}m")

        ax.legend(loc="upper right", fontsize=7)

    def _draw_tank_section(self, ax, name: str, tmpl: dict):
        """沉沙池断面。"""
        length = tmpl.get("length", 2.0)
        depth = tmpl.get("depth", 1.5)
        tw = tmpl.get("wall_thickness", 0.24)
        tf = tmpl.get("floor_thickness", 0.15)
        mat = tmpl.get("material", "MU10砖+M5砂浆")

        # 池壁 (外轮廓 — 斜线填充)
        outer_x = [-tw, length + tw, length + tw, -tw, -tw]
        outer_y = [0.3, 0.3, -(depth + tf), -(depth + tf), 0.3]
        ax.fill(outer_x, outer_y, color="#C0C0C0", edgecolor="#000",
                linewidth=1.5, hatch="///", label=mat)

        # 池内空间 (白色)
        inner_x = [0, length, length, 0, 0]
        inner_y = [0, 0, -depth, -depth, 0]
        ax.fill(inner_x, inner_y, color="white", edgecolor="#000",
                linewidth=1.0, label="蓄水空间")

        # 地面线
        ax.plot([-1, -tw], [0, 0], "k-", linewidth=2)
        ax.plot([length + tw, length + 1.5], [0, 0], "k-", linewidth=2)

        # 标注
        self._dim_line(ax, 0, -depth - tf - 0.2, length, -depth - tf - 0.2,
                        f"{length:.1f}m")
        self._dim_line_v(ax, length + tw + 0.2, 0, length + tw + 0.2, -depth,
                          f"{depth:.1f}m")

        ax.legend(loc="upper right", fontsize=7)

    def _draw_trapezoidal_section(self, ax, name: str, tmpl: dict):
        """梯形断面 (土质临时排水沟)。"""
        tw = tmpl.get("top_width", 0.5)
        bw = tmpl.get("bottom_width", 0.3)
        d = tmpl.get("depth", 0.3)
        mat = tmpl.get("material", "土质")

        # 梯形断面轮廓
        offset = (tw - bw) / 2
        trap_x = [0, tw, tw - offset, offset, 0]
        trap_y = [0, 0, -d, -d, 0]
        ax.fill(trap_x, trap_y, color="#D2B48C", edgecolor="#000",
                linewidth=1.5, hatch="...", label=f"{mat}沟体")

        # 沟内空间 (白色，略内缩)
        wall_t = 0.03  # 土质壁厚约 3cm
        inner_x = [wall_t, tw - wall_t, tw - offset - wall_t * 0.5,
                   offset + wall_t * 0.5, wall_t]
        inner_y = [0, 0, -(d - wall_t), -(d - wall_t), 0]
        ax.fill(inner_x, inner_y, color="white", edgecolor="#666",
                linewidth=0.5, label="过水断面")

        # 地面线
        ground_ext = max(tw, 0.5)
        ax.plot([-ground_ext * 0.5, 0], [0, 0], "k-", linewidth=2)
        ax.plot([tw, tw + ground_ext * 0.5], [0, 0], "k-", linewidth=2)
        ax.fill_between([-ground_ext * 0.5, 0], [0, 0], [0.1, 0.1],
                        color="#D0D0D0", alpha=0.5, hatch="...")
        ax.fill_between([tw, tw + ground_ext * 0.5], [0, 0], [0.1, 0.1],
                        color="#D0D0D0", alpha=0.5)

        # 尺寸标注
        self._dim_line(ax, 0, 0.12, tw, 0.12, f"{tw*100:.0f}cm")
        self._dim_line(ax, offset, -d - 0.12, tw - offset, -d - 0.12,
                       f"{bw*100:.0f}cm")
        self._dim_line_v(ax, tw + 0.1, 0, tw + 0.1, -d, f"{d*100:.0f}cm")

        ax.set_title(f"典型断面 — {self._safe_text(name)}", fontsize=12,
                     fontweight="bold")
        ax.set_xlabel("宽度 (m)", fontsize=9)
        ax.set_ylabel("深度 (m)", fontsize=9)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=7)

    def _draw_pavement_section(self, ax, name: str, tmpl: dict):
        """分层铺装断面 (透水砖)。"""
        layers = tmpl.get("layers", [])
        total_w = tmpl.get("total_width", 1.0)

        if not layers:
            self._draw_channel_section(ax, name, tmpl)
            return

        y_top = 0.0
        colors = ["#C0C0C0", "#E0D8C0", "#B0B0B0", "#A08060"]

        for i, layer in enumerate(layers):
            thickness = layer.get("thickness", 0.05)
            lname = layer.get("name", f"层{i+1}")
            hatch = layer.get("hatch", None)
            color = colors[i % len(colors)]

            y_bottom = y_top - thickness
            rect_x = [0, total_w, total_w, 0, 0]
            rect_y = [y_top, y_top, y_bottom, y_bottom, y_top]
            ax.fill(rect_x, rect_y, color=color, edgecolor="#000",
                    linewidth=1.0, hatch=hatch, alpha=0.7, label=lname)

            # 层名标注
            ax.text(total_w + 0.05, (y_top + y_bottom) / 2,
                    f"{lname} ({thickness*100:.0f}cm)",
                    fontsize=7, va="center", ha="left")

            y_top = y_bottom

        # 地面线
        ax.plot([-0.2, 0], [0, 0], "k-", linewidth=2)
        ax.plot([total_w, total_w + 0.2], [0, 0], "k-", linewidth=2)

        # 总深度标注
        total_d = sum(l.get("thickness", 0.05) for l in layers)
        self._dim_line_v(ax, -0.15, 0, -0.15, -total_d,
                         f"{total_d*100:.0f}cm")
        self._dim_line(ax, 0, -total_d - 0.08, total_w, -total_d - 0.08,
                       f"{total_w*100:.0f}cm")

        ax.set_title(f"典型断面 — {self._safe_text(name)}", fontsize=12,
                     fontweight="bold")
        ax.set_xlabel("宽度 (m)", fontsize=9)
        ax.set_ylabel("深度 (m)", fontsize=9)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=7)

    def _draw_wash_platform_section(self, ax, name: str, tmpl: dict):
        """车辆冲洗平台断面。"""
        length = tmpl.get("length", 6.0)
        depth = tmpl.get("depth", 0.3)
        slab_t = tmpl.get("slab_thickness", 0.20)
        mat = tmpl.get("material", "C20混凝土")

        # 沉淀池 (中央凹槽)
        pool_w = length * 0.3
        pool_d = depth + 0.2
        pool_x0 = (length - pool_w) / 2

        # 基础平台
        ax.fill([0, length, length, 0, 0],
                [0, 0, -slab_t, -slab_t, 0],
                color="#C0C0C0", edgecolor="#000", linewidth=1.5,
                hatch="///", label=f"{mat}基础")

        # 凹槽 (集水坑)
        ax.fill([pool_x0, pool_x0 + pool_w, pool_x0 + pool_w, pool_x0, pool_x0],
                [-slab_t, -slab_t, -slab_t - pool_d, -slab_t - pool_d, -slab_t],
                color="#B0C4DE", edgecolor="#000", linewidth=1.0,
                hatch="...", label="集水坑")

        # 排水坡度箭头 (左右对称)
        mid_x = length / 2
        arrow_y = 0.08
        ax.annotate("", xy=(mid_x, arrow_y), xytext=(0.3, arrow_y + 0.05),
                    arrowprops=dict(arrowstyle="->", color="#1E90FF", lw=1.2))
        ax.annotate("", xy=(mid_x, arrow_y), xytext=(length - 0.3, arrow_y + 0.05),
                    arrowprops=dict(arrowstyle="->", color="#1E90FF", lw=1.2))
        ax.text(mid_x, arrow_y + 0.08, "2%坡", fontsize=7, ha="center",
                color="#1E90FF")

        # 地面线
        ax.plot([-0.5, 0], [0, 0], "k-", linewidth=2)
        ax.plot([length, length + 0.5], [0, 0], "k-", linewidth=2)

        # 尺寸标注
        self._dim_line(ax, 0, -slab_t - pool_d - 0.2, length,
                       -slab_t - pool_d - 0.2, f"{length:.1f}m")
        self._dim_line_v(ax, length + 0.2, 0, length + 0.2, -slab_t,
                         f"{slab_t*100:.0f}cm")
        self._dim_line(ax, pool_x0, -slab_t - pool_d - 0.1,
                       pool_x0 + pool_w, -slab_t - pool_d - 0.1,
                       f"{pool_w:.1f}m")

        ax.set_title(f"典型断面 — {self._safe_text(name)}", fontsize=12,
                     fontweight="bold")
        ax.set_xlabel("宽度 (m)", fontsize=9)
        ax.set_ylabel("深度 (m)", fontsize=9)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=7)

    def _dim_line(self, ax, x1, y1, x2, y2, text: str):
        """绘制水平尺寸标注线。"""
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="<->", color="#333", lw=0.8))
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 - 0.05, text,
                ha="center", va="top", fontsize=8, color="#333")

    def _dim_line_v(self, ax, x1, y1, x2, y2, text: str):
        """绘制垂直尺寸标注线。"""
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="<->", color="#333", lw=0.8))
        ax.text((x1 + x2) / 2 + 0.05, (y1 + y2) / 2, text,
                ha="left", va="center", fontsize=8, color="#333",
                rotation=90)

    # ── 视图范围控制 ─────────────────────────────────────────────

    def _set_content_view_limits(self, ax):
        """设置 axes 视图范围，优先使用红线边界多边形。"""
        # 优先级1: 红线边界多边形 (最精确的视口)
        boundary = None
        if self._cad_site_features is not None:
            boundary = getattr(self._cad_site_features, 'boundary_polyline', None)
        if boundary and len(boundary) >= 3:
            bxs = [p[0] for p in boundary]
            bys = [p[1] for p in boundary]
            x0, y0, x1, y1 = min(bxs), min(bys), max(bxs), max(bys)
            logger.debug("视口: 使用红线边界多边形 (%.1f,%.1f)-(%.1f,%.1f)", x0, y0, x1, y1)
        elif self._zone_geometries:
            # 优先级2: 分区几何并集
            all_bounds = [g["bounds"] for g in self._zone_geometries.values()]
            x0 = min(b[0] for b in all_bounds)
            y0 = min(b[1] for b in all_bounds)
            x1 = max(b[2] for b in all_bounds)
            y1 = max(b[3] for b in all_bounds)
            # 也包含 CAD 内容区域 (确保底图可见)
            if self._cad_renderer:
                cb = self._cad_renderer.content_bounds
                x0 = min(x0, cb[0])
                y0 = min(y0, cb[1])
                x1 = max(x1, cb[2])
                y1 = max(y1, cb[3])
        else:
            ax.autoscale()
            return
        margin_x = (x1 - x0) * 0.15
        margin_y = (y1 - y0) * 0.15
        ax.set_xlim(x0 - margin_x, x1 + margin_x)
        ax.set_ylim(y0 - margin_y, y1 + margin_y)

    # ── 专业制图元素 ─────────────────────────────────────────────

    def _get_boundary_polyline(self) -> list[tuple[float, float]] | None:
        """获取项目红线坐标点 (从 CAD geometry 或 SiteModel)。"""
        # 从 SiteModel 获取
        if self._placement_engine is not None:
            model = getattr(self._placement_engine, '_model', None)
            if model is not None:
                boundary = getattr(model, 'boundary_polygon', None)
                if boundary and len(boundary) >= 3:
                    return list(boundary)
        # 从 CAD geometry 获取
        if self._cad_geometry is not None:
            for ent in self._cad_geometry.boundaries:
                if ent.points and len(ent.points) >= 3:
                    return list(ent.points)
        return None

    def _draw_coordinate_annotations(self, ax):
        """薄包装: 委托到模块级 draw_coordinate_annotations。"""
        boundary = self._get_boundary_polyline()
        draw_coordinate_annotations(ax, boundary)

    def _draw_title_block(self, fig, title: str, ax):
        """薄包装: 委托到模块级 draw_title_block。"""
        draw_title_block(fig, title, ax, self.spatial_layout)

    def _draw_measure_table(self, ax):
        """薄包装: 委托到模块级 draw_measure_table。"""
        draw_measure_table(ax, self.measures)

    def _draw_flow_arrows(self, ax):
        """薄包装: 委托到模块级 draw_flow_arrows。"""
        draw_flow_arrows(ax, self._placement_engine)

    # ── 地图装饰 ───────────────────────────────────────────────

    def _add_map_decorations(self, ax, fig=None):
        """添加专业指北针、分格比例尺、双层网格、坐标轴格式化。"""
        from matplotlib.ticker import FuncFormatter

        if fig is None:
            fig = ax.get_figure()

        # ── 修复科学记数法坐标轴 ──
        ax.ticklabel_format(style='plain', useOffset=False)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, p: f"{x:.0f}"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f"{x:.0f}"))

        # ── 双层网格 (主/次网格) ──
        ax.grid(True, which='major', alpha=0.15, linestyle="-", linewidth=0.4)
        ax.grid(True, which='minor', alpha=0.06, linestyle=":", linewidth=0.2)
        ax.minorticks_on()

        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        dx = xlim[1] - xlim[0]
        dy = ylim[1] - ylim[0]

        # ── 专业指北针 (左上角, 填充三角 + "N" 标注) ──
        nx = xlim[0] + dx * 0.06
        ny = ylim[1] - dy * 0.04
        arrow_h = dy * 0.08
        arrow_w = dx * 0.015
        tri_x = [nx, nx - arrow_w, nx + arrow_w, nx]
        tri_y = [ny, ny - arrow_h, ny - arrow_h, ny]
        ax.fill(tri_x, tri_y, color="black", zorder=10)
        ax.text(nx, ny + dy * 0.015, "N",
                fontsize=10, fontweight="bold", ha="center", va="bottom",
                zorder=10)

        # ── 分格比例尺 (右下角, 黑白交替 4 段 + 比例标注 1:N) ──
        bar_len = self._nice_scale_length(dx * 0.2)
        if bar_len > 0:
            bx = xlim[1] - dx * 0.05 - bar_len
            by = ylim[0] + dy * 0.05
            bar_h = dy * 0.008
            n_segments = 4
            seg_len = bar_len / n_segments
            for i in range(n_segments):
                color_seg = "black" if i % 2 == 0 else "white"
                ax.add_patch(plt.Rectangle(
                    (bx + i * seg_len, by), seg_len, bar_h,
                    facecolor=color_seg, edgecolor="black",
                    linewidth=0.5, zorder=10,
                ))
            ax.text(bx, by - dy * 0.01, "0",
                    fontsize=6, ha="center", va="top", zorder=10)
            ax.text(bx + bar_len, by - dy * 0.01,
                    f"{bar_len:.0f}m" if bar_len >= 1 else f"{bar_len*100:.0f}cm",
                    fontsize=6, ha="center", va="top", zorder=10)
            fig_w_inches = fig.get_size_inches()[0]
            if fig_w_inches > 0 and dx > 0:
                scale_n = int(dx / (fig_w_inches * 0.0254))
                if scale_n > 0:
                    nice = self._nice_scale_number(scale_n)
                    ax.text(bx + bar_len / 2, by + bar_h + dy * 0.008,
                            f"1:{nice}",
                            fontsize=7, ha="center", va="bottom", zorder=10)

        # ── 移除 "X (m)" / "Y (m)" 标签, 缩小坐标轴字号 ──
        ax.set_xlabel("", fontsize=0)
        ax.set_ylabel("", fontsize=0)
        ax.tick_params(labelsize=6)

    @staticmethod
    def _nice_scale_length(approx_len: float) -> float:
        """计算比例尺的合适长度 (取整到 1/2/5 × 10^n)。"""
        if approx_len <= 0:
            return 0
        exp = math.floor(math.log10(approx_len))
        base = 10 ** exp
        normalized = approx_len / base
        if normalized < 1.5:
            return base
        elif normalized < 3.5:
            return 2 * base
        elif normalized < 7.5:
            return 5 * base
        else:
            return 10 * base

    @staticmethod
    def _nice_scale_number(n: int) -> int:
        """将比例尺分母取整到 1/2/5 × 10^k。"""
        if n <= 0:
            return 1
        exp = math.floor(math.log10(n))
        base = 10 ** exp
        normalized = n / base
        if normalized < 1.5:
            return base
        elif normalized < 3.5:
            return 2 * base
        elif normalized < 7.5:
            return 5 * base
        else:
            return 10 * base

    def _draw_professional_legend(self, ax, measures_present: list[str]):
        """薄包装: 委托到模块级 draw_professional_legend。"""
        draw_professional_legend(ax, self.zones, measures_present)
