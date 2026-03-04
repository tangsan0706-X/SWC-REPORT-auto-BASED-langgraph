"""确定性渲染引擎 — 接收 DrawingPlan + 项目数据 → PNG + DXF。

LLM 只输出 DrawingPlan JSON，本模块负责所有确定性绘制。
复用 measure_map.py 的几何构建 + measure_symbols.py 的样式。

输出:
  - PNG: matplotlib 渲染 (300 DPI)
  - DXF: ezdxf 渲染 (甲方可在 CAD 中编辑)
"""

from __future__ import annotations

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
import numpy as np

from src.drawing_plan import DrawingPlan, MeasureSpec, SectionSpec
from src.measure_map import (
    build_zone_geometries,
    draw_professional_legend, draw_coordinate_annotations,
    draw_flow_arrows, draw_measure_table, draw_title_block,
)
from src.measure_symbols import (
    MEASURE_STYLES, SECTION_TEMPLATES, ZONE_COLORS,
    MAP_DEFAULTS, ZORDER, get_style, get_zone_color, get_measure_color,
    ZONE_COLORS_PROFESSIONAL, BOUNDARY_COLORS,
    match_section_template, get_zone_hatch,
    get_measure_category,
)

logger = logging.getLogger(__name__)

# ── 中文字体 ────────────────────────────────────────────────────
_CN_FONT = None
for _font_name in ["SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC",
                    "Microsoft YaHei", "Noto Sans SC", "Source Han Sans SC",
                    "AR PL UMing CN", "DejaVu Sans"]:
    try:
        fp = fm.FontProperties(family=_font_name)
        found = fm.findfont(fp, fallback_to_default=False)
        if found:
            _CN_FONT = fp
            break
    except Exception:
        continue
if _CN_FONT:
    plt.rcParams["font.family"] = _CN_FONT.get_name()
else:
    for f in fm.fontManager.ttflist:
        name_lower = f.name.lower()
        if any(k in name_lower for k in ["cjk", "hei", "song", "kai", "ming",
                                          "yahei", "simsun", "fangsong",
                                          "wqy", "noto sans"]):
            _CN_FONT = fm.FontProperties(family=f.name)
            plt.rcParams["font.family"] = f.name
            break
plt.rcParams["axes.unicode_minus"] = False

# ── 语义位置 → 几何偏移映射 ─────────────────────────────────────
_POSITION_OFFSETS = {
    "north":     (0.5,  0.85),
    "south":     (0.5,  0.15),
    "east":      (0.85, 0.5),
    "west":      (0.15, 0.5),
    "center":    (0.5,  0.5),
    "northeast": (0.8,  0.8),
    "northwest": (0.2,  0.8),
    "southeast": (0.8,  0.2),
    "southwest": (0.2,  0.2),
    "perimeter": (0.5,  0.5),  # 特殊处理
}

# ── DXF 图层名称 ────────────────────────────────────────────────
DXF_LAYERS = {
    "ZONE_BOUNDARIES":  {"color": 7},   # 白色 (AutoCAD 7=白/黑)
    "ZONE_FILL":        {"color": 9},
    "ZONE_LABELS":      {"color": 7},
    "MEASURES_LINE":    {"color": 1},   # 红色
    "MEASURES_FILL":    {"color": 3},   # 绿色
    "MEASURES_POINT":   {"color": 5},   # 蓝色
    "ANNOTATIONS":      {"color": 7},
    "LEGEND":           {"color": 7},
    "TITLE_BAR":        {"color": 7},
}


def _safe_text(text: str) -> str:
    """替换字体可能缺失的 Unicode 字符。"""
    return text.replace("²", "2").replace("³", "3").replace("×", "x")


# ═══════════════════════════════════════════════════════════════
# DrawingRenderer
# ═══════════════════════════════════════════════════════════════

class DrawingRenderer:
    """确定性渲染引擎: DrawingPlan → PNG + DXF。"""

    def __init__(
        self,
        plan: DrawingPlan,
        zones: list[dict],
        measures: list[dict],
        spatial_layout: dict | None = None,
        gis_gdf: Any = None,
        output_dir: Path | None = None,
        cad_geometry: Any = None,
        cad_dxf_path: str | None = None,
        cad_site_features: Any = None,
        placement_engine: Any = None,
    ):
        self._plan = plan
        self._zones = zones
        self._measures = measures
        self._spatial = spatial_layout or {}
        self._gis_gdf = gis_gdf
        self._output_dir = output_dir or Path("data/output")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._cad_geometry = cad_geometry  # CadGeometry 对象
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

        # 预计算几何 — 优先使用聚类边界 (仅主图簇) 而非全域 CAD 边界
        cluster_b = getattr(cad_site_features, 'cluster_bounds', None) if cad_site_features else None
        cad_bounds = cluster_b or (cad_geometry.bounds if cad_geometry else None)
        cad_content = cluster_b or (cad_geometry.content_bounds if cad_geometry else None)
        site_model = getattr(placement_engine, '_model', None) if placement_engine else None
        self._zone_geoms = build_zone_geometries(zones, gis_gdf,
                                                  cad_bounds=cad_bounds,
                                                  cad_content_bounds=cad_content,
                                                  cad_site_features=cad_site_features,
                                                  site_model=site_model)

    # ═══════════════════════════════════════════════════════════
    # 统一入口
    # ═══════════════════════════════════════════════════════════

    def render_all(self, filename: str) -> dict[str, Path]:
        """渲染 PNG + DXF，返回 {"png": Path, "dxf": Path}。"""
        results = {}

        # PNG
        try:
            png_path = self.render_png(filename)
            if png_path:
                results["png"] = png_path
        except Exception as e:
            logger.error(f"PNG 渲染失败: {e}")

        # DXF
        try:
            dxf_filename = filename.replace(".png", ".dxf") if filename.endswith(".png") else filename + ".dxf"
            dxf_path = self.render_dxf(dxf_filename)
            if dxf_path:
                results["dxf"] = dxf_path
        except Exception as e:
            logger.warning(f"DXF 渲染失败 (非致命): {e}")

        return results

    # ═══════════════════════════════════════════════════════════
    # PNG 渲染 (matplotlib)
    # ═══════════════════════════════════════════════════════════

    def render_png(self, filename: str) -> Path | None:
        """根据 map_type 分发到对应渲染方法。"""
        if not filename.endswith(".png"):
            filename += ".png"

        dpi = MAP_DEFAULTS["dpi"]
        map_type = self._plan.map_type

        if map_type == "typical_section":
            figsize = MAP_DEFAULTS["figsize_section"]
        elif map_type == "zone_detail":
            figsize = MAP_DEFAULTS["figsize_detail"]
        else:
            figsize = MAP_DEFAULTS["figsize_single"]

        fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

        dispatch = {
            "zone_boundary":  self._render_zone_boundary,
            "measure_layout": self._render_measure_layout,
            "zone_detail":    self._render_zone_detail,
            "typical_section": self._render_typical_section,
        }

        renderer = dispatch.get(map_type, self._render_measure_layout)
        renderer(fig, ax)

        path = self._output_dir / filename

        # 安全检查: 预估像素尺寸, 超限时降低 DPI
        save_dpi = dpi
        fig_w, fig_h = fig.get_size_inches()
        max_px = 65000  # matplotlib/Pillow 硬限制 2^16
        est_w = fig_w * save_dpi
        est_h = fig_h * save_dpi
        if est_w > max_px or est_h > max_px:
            scale = max_px / max(est_w, est_h)
            save_dpi = max(72, int(save_dpi * scale))
            logger.warning(
                f"图像像素预估 {est_w:.0f}x{est_h:.0f} 超限, "
                f"降低 DPI: {dpi}→{save_dpi}"
            )

        fig.savefig(str(path), dpi=save_dpi, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        logger.info(f"PNG 已生成: {path.name} ({path.stat().st_size // 1024}KB)")
        return path

    # ── 图1: 分区图 ──

    def _render_zone_boundary(self, fig, ax):
        """渲染分区边界图。"""
        # CAD 全色底图
        if self._cad_renderer:
            self._cad_renderer.render_foreground(ax, highlight_boundary=True)

        legend_patches = []

        for zs in self._plan.zones:
            geom = self._zone_geoms.get(zs.name)
            if not geom:
                continue

            color = get_zone_color(zs.name, professional=True)
            alpha = 0.5 if zs.emphasis == "highlight" else 0.35

            # 查找面积
            area_hm2 = 0.0
            for z in self._zones:
                if z.get("name") == zs.name:
                    area_hm2 = z.get("area_hm2", 0)
                    break

            if geom["type"] == "gis":
                self._plot_gis_polygon(ax, geom["geometry"], color, zs.name, alpha=alpha)
            elif "polygon" in geom and len(geom.get("polygon", [])) >= 3:
                polygon = geom["polygon"]
                xs = [p[0] for p in polygon] + [polygon[0][0]]
                ys = [p[1] for p in polygon] + [polygon[0][1]]
                ax.fill(xs, ys, facecolor=color, edgecolor="#333333",
                        linewidth=1.5, alpha=alpha)
            else:
                bounds = geom["bounds"]
                rect = plt.Rectangle(
                    (bounds[0], bounds[1]),
                    bounds[2] - bounds[0], bounds[3] - bounds[1],
                    facecolor=color, edgecolor="#333333",
                    linewidth=1.5, alpha=alpha,
                )
                ax.add_patch(rect)

            cx, cy = geom["centroid"]
            ax.text(cx, cy, f"{zs.name}\n{area_hm2} hm2",
                    ha="center", va="center",
                    fontsize=MAP_DEFAULTS["label_fontsize"],
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.85))

            legend_patches.append(mpatches.Patch(
                facecolor=color, edgecolor="#333", alpha=0.6,
                label=f"{zs.name} ({area_hm2} hm2)"))

        title = self._plan.title or "水土保持防治分区图"
        ax.set_title(_safe_text(title),
                     fontsize=MAP_DEFAULTS["title_fontsize"],
                     fontweight="bold", pad=15)
        if legend_patches:
            ax.legend(handles=legend_patches, loc="lower right",
                      fontsize=MAP_DEFAULTS["legend_fontsize"],
                      framealpha=0.9, title="图例")
        ax.set_aspect("equal")
        self._set_content_view_limits(ax)
        self._add_professional_decorations(fig, ax, show_area_table=True)

    # ── 图2: 总布置图 ──

    def _render_measure_layout(self, fig, ax):
        """渲染措施总体布置图。"""
        # CAD 全色底图
        if self._cad_renderer:
            self._cad_renderer.render_foreground(ax, highlight_boundary=True)

        # 底图: 半透明分区边界
        for zs in self._plan.zones:
            geom = self._zone_geoms.get(zs.name)
            if not geom:
                continue
            color = get_zone_color(zs.name, professional=True)
            if geom["type"] == "gis":
                self._plot_gis_polygon(ax, geom["geometry"], color, zs.name, alpha=0.2)
            elif "polygon" in geom and len(geom.get("polygon", [])) >= 3:
                polygon = geom["polygon"]
                xs = [p[0] for p in polygon] + [polygon[0][0]]
                ys = [p[1] for p in polygon] + [polygon[0][1]]
                ax.fill(xs, ys, facecolor=color, edgecolor="#888888",
                        linewidth=0.8, alpha=0.15, linestyle="--",
                        zorder=ZORDER["zone_fill"])
                ax.text(geom["centroid"][0], geom["centroid"][1],
                        zs.name, ha="center", va="center",
                        fontsize=7, color="#555", alpha=0.8,
                        bbox=dict(boxstyle="round,pad=0.15",
                                  facecolor="white", alpha=0.6, edgecolor="none"),
                        zorder=ZORDER["labels"])
            else:
                bounds = geom["bounds"]
                rect = plt.Rectangle(
                    (bounds[0], bounds[1]),
                    bounds[2] - bounds[0], bounds[3] - bounds[1],
                    facecolor=color, edgecolor="#888888",
                    linewidth=0.8, alpha=0.15, linestyle="--",
                    zorder=ZORDER["zone_fill"],
                )
                ax.add_patch(rect)
                ax.text(geom["centroid"][0], geom["centroid"][1],
                        zs.name, ha="center", va="center",
                        fontsize=7, color="#555", alpha=0.8,
                        bbox=dict(boxstyle="round,pad=0.15",
                                  facecolor="white", alpha=0.6, edgecolor="none"),
                        zorder=ZORDER["labels"])

        # 叠加彩色措施 (按 z-order 排序: fill → line → point)
        _TYPE_ORDER = {"fill": 0, "line": 1, "point": 2}
        sorted_plan_measures = sorted(
            self._plan.measures,
            key=lambda ms: _TYPE_ORDER.get(
                get_style(ms.name, professional=True).get("type", "fill"), 0
            )
        )
        legend_handles = {}
        for ms in sorted_plan_measures:
            zone_geom = self._zone_geoms.get(ms.zone)
            if not zone_geom:
                continue
            style = get_style(ms.name, professional=True)
            self._draw_measure_on_ax(ax, ms, zone_geom, style, legend_handles)

        # 4. 专业分类图例 (替代简单 legend)
        measures_present = [ms.name for ms in self._plan.measures]
        draw_professional_legend(ax, self._zones, measures_present)

        # 5. 坐标标注
        boundary = self._get_boundary_polyline()
        draw_coordinate_annotations(ax, boundary)

        # 6. 水流方向箭头
        draw_flow_arrows(ax, self._placement_engine)

        title = self._plan.title or "水土保持措施总体布置图"
        ax.set_title(_safe_text(title),
                     fontsize=MAP_DEFAULTS["title_fontsize"],
                     fontweight="bold", pad=15)
        ax.set_aspect("equal")
        self._set_content_view_limits(ax)
        self._add_professional_decorations(fig, ax)

        # 7. 图签
        draw_title_block(fig, title, ax, self._spatial)

        # 8. 措施汇总表
        draw_measure_table(ax, self._measures)

    # ── 图3: 分区详图 ──

    def _render_zone_detail(self, fig, ax):
        """渲染单个分区的措施详图。"""
        target_zone = self._plan.zones[0].name if self._plan.zones else ""
        geom = self._zone_geoms.get(target_zone)
        if not geom:
            if self._zone_geoms:
                target_zone = next(iter(self._zone_geoms))
                geom = self._zone_geoms[target_zone]
            else:
                ax.text(0.5, 0.5, "无分区数据", transform=ax.transAxes,
                        ha="center", fontsize=14)
                return

        # CAD 全色底图 (裁剪到分区范围, 不绘制全域红线)
        if self._cad_renderer:
            crop = geom.get("bounds")
            self._cad_renderer.render_foreground(ax, crop_bounds=crop,
                                                  highlight_boundary=False)

        # 分区边界高亮 (粗彩色边框 + 浅填充)
        color = get_zone_color(target_zone, professional=True)
        if geom["type"] == "gis":
            self._plot_gis_polygon(ax, geom["geometry"], color, target_zone, alpha=0.2)
        elif "polygon" in geom and len(geom.get("polygon", [])) >= 3:
            polygon = geom["polygon"]
            xs = [p[0] for p in polygon] + [polygon[0][0]]
            ys = [p[1] for p in polygon] + [polygon[0][1]]
            ax.fill(xs, ys, facecolor=color, edgecolor=color,
                    linewidth=2.5, alpha=0.15)
            ax.plot(xs, ys, color=color, linewidth=2.5,
                    linestyle="-", zorder=8)
        else:
            bounds = geom["bounds"]
            rect = plt.Rectangle(
                (bounds[0], bounds[1]),
                bounds[2] - bounds[0], bounds[3] - bounds[1],
                facecolor=color, edgecolor=color,
                linewidth=2.5, alpha=0.15,
            )
            ax.add_patch(rect)

        # 绘制该分区的措施 (带详细标注, 彩色)
        legend_handles = {}
        for ms in self._plan.measures:
            if ms.zone != target_zone:
                if target_zone not in ms.zone and ms.zone not in target_zone:
                    continue
            zone_geom = geom
            style = get_style(ms.name, professional=True)
            self._draw_measure_on_ax(ax, ms, zone_geom, style, legend_handles, detail=True)

        if legend_handles:
            handles = [h for h in legend_handles.values()
                       if not str(getattr(h, '_label', '')).startswith('_')]
            if handles:
                ax.legend(handles=handles, loc="lower right",
                          fontsize=MAP_DEFAULTS["legend_fontsize"],
                          framealpha=0.9)

        title = self._plan.title or f"{target_zone} — 措施详图"
        ax.set_title(_safe_text(title),
                     fontsize=MAP_DEFAULTS["title_fontsize"],
                     fontweight="bold", pad=15)
        ax.set_aspect("equal")

        # 必须先设置视图范围，再添加装饰元素
        # (装饰元素用 data 坐标定位，依赖 xlim/ylim)
        if geom["type"] != "gis":
            bounds = geom["bounds"]
            margin = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.1
            ax.set_xlim(bounds[0] - margin, bounds[2] + margin)
            ax.set_ylim(bounds[1] - margin, bounds[3] + margin)
        self._add_professional_decorations(fig, ax)

    # ── 图4: 断面图 ──

    def _render_typical_section(self, fig, ax):
        """渲染典型工程断面图。"""
        if not self._plan.sections:
            ax.text(0.5, 0.5, "无断面数据", transform=ax.transAxes,
                    ha="center", fontsize=14)
            return

        # 取第一个断面 (每次调用只画一个)
        sec = self._plan.sections[0]
        # 使用共享模糊匹配
        matched = match_section_template(sec.structure)
        if matched:
            tmpl_key, tmpl = matched
            sec.structure = tmpl_key
        else:
            tmpl = SECTION_TEMPLATES.get(sec.structure)
        if not tmpl:
            ax.text(0.5, 0.5, f"无断面模板: {sec.structure}",
                    transform=ax.transAxes, ha="center", fontsize=12)
            return

        shape = tmpl.get("shape", "rectangular_channel")
        if shape == "gravity_wall":
            self._draw_wall_section(ax, sec.structure, tmpl)
        elif shape == "sedimentation_tank":
            self._draw_tank_section(ax, sec.structure, tmpl)
        elif shape == "trapezoidal_channel":
            self._draw_trapezoidal_section(ax, sec.structure, tmpl)
        elif shape == "pavement_section":
            self._draw_pavement_section(ax, sec.structure, tmpl)
        elif shape == "wash_platform":
            self._draw_wash_platform_section(ax, sec.structure, tmpl)
        else:
            self._draw_channel_section(ax, sec.structure, tmpl)

        # 附加注释
        if sec.annotation_notes:
            note_text = "\n".join(sec.annotation_notes)
            ax.text(0.02, 0.02, _safe_text(note_text), transform=ax.transAxes,
                    fontsize=7, va="bottom", ha="left",
                    bbox=dict(boxstyle="round,pad=0.3", fc="#F5F5F5", alpha=0.8))

        title = self._plan.title or f"典型断面 — {_safe_text(sec.structure)}"
        ax.set_title(_safe_text(title), fontsize=12, fontweight="bold")
        ax.set_xlabel("宽度 (m)", fontsize=9)
        ax.set_ylabel("深度 (m)", fontsize=9)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)

    # ═══════════════════════════════════════════════════════════
    # 视图范围控制
    # ═══════════════════════════════════════════════════════════

    def _get_boundary_polyline(self) -> list[tuple[float, float]] | None:
        """获取项目红线坐标点 (从 SiteModel 或 CAD geometry)。"""
        if self._placement_engine is not None:
            model = getattr(self._placement_engine, '_model', None)
            if model is not None:
                boundary = getattr(model, 'boundary_polygon', None)
                if boundary and len(boundary) >= 3:
                    return list(boundary)
        if self._cad_geometry is not None:
            for ent in self._cad_geometry.boundaries:
                if ent.points and len(ent.points) >= 3:
                    return list(ent.points)
        return None

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
        elif self._zone_geoms:
            # 优先级2: 分区几何并集
            all_bounds = [g["bounds"] for g in self._zone_geoms.values()]
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

    # ═══════════════════════════════════════════════════════════
    # 语义位置 → 坐标
    # ═══════════════════════════════════════════════════════════

    def _resolve_position(self, zone_geom: dict, spec: MeasureSpec) -> tuple[float, float]:
        """将语义位置 (north/south/...) 转换为分区内的 (x, y) 坐标。"""
        bounds = zone_geom.get("bounds", (0, 0, 100, 100))
        x0, y0, x1, y1 = bounds

        offsets = _POSITION_OFFSETS.get(spec.position, (0.5, 0.5))
        fx, fy = offsets

        x = x0 + (x1 - x0) * fx
        y = y0 + (y1 - y0) * fy
        return x, y

    # ═══════════════════════════════════════════════════════════
    # 单措施绘制
    # ═══════════════════════════════════════════════════════════

    def _draw_measure_on_ax(self, ax, spec: MeasureSpec, zone_geom: dict,
                             style: dict, legend_handles: dict,
                             detail: bool = False):
        """在 ax 上绘制单个措施。"""
        m_type = style.get("type", "fill")
        label = style.get("label", spec.name[:8])
        color = style.get("color", "#666")
        bounds = zone_geom.get("bounds", (0, 0, 100, 100))
        x0, y0, x1, y1 = bounds
        w = x1 - x0
        h = y1 - y0

        # 尝试 CAD 智能放置 (spec.cad_coords 或 resolver)
        resolved = None
        if spec.cad_coords and spec.cad_geom_type:
            resolved = {spec.cad_geom_type: spec.cad_coords}
        elif self._resolver:
            # 优先查找预计算结果
            if hasattr(self._resolver, 'get_placement'):
                resolved = self._resolver.get_placement(spec.name, spec.zone)
            # 回退到实时计算
            if resolved is None:
                resolved = self._resolver.resolve(spec.name, spec.zone, zone_bounds=bounds)
        if resolved:
            self._draw_resolved_on_ax(ax, resolved, style, label,
                                       legend_handles, detail, spec)
            return

        pos_x, pos_y = self._resolve_position(zone_geom, spec)

        if m_type == "line":
            lw = style.get("linewidth", 2.0)
            ls = style.get("linestyle", "-")
            line_pts = self._generate_line_points(bounds, spec)
            xs = [p[0] for p in line_pts]
            ys = [p[1] for p in line_pts]
            line, = ax.plot(xs, ys, color=color, linewidth=lw, linestyle=ls)
            if label not in legend_handles:
                legend_handles[label] = line
            if detail and line_pts:
                mid = len(line_pts) // 2
                ax.annotate(_safe_text(f"{label}\n{spec.note}" if spec.note else label),
                            xy=(xs[mid], ys[mid]),
                            fontsize=7, ha="center",
                            bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.7))

        elif m_type == "fill":
            alpha = style.get("alpha", 0.3)
            hatch = style.get("hatch")
            fill_bounds = self._generate_fill_bounds(bounds, spec)
            rect = plt.Rectangle(
                (fill_bounds[0], fill_bounds[1]),
                fill_bounds[2] - fill_bounds[0],
                fill_bounds[3] - fill_bounds[1],
                facecolor=color, edgecolor=color,
                linewidth=0.8, alpha=alpha, hatch=hatch,
            )
            ax.add_patch(rect)
            if label not in legend_handles:
                legend_handles[label] = mpatches.Patch(
                    facecolor=color, edgecolor=color,
                    alpha=alpha, hatch=hatch, label=label)
            if detail:
                fcx = (fill_bounds[0] + fill_bounds[2]) / 2
                fcy = (fill_bounds[1] + fill_bounds[3]) / 2
                ax.text(fcx, fcy,
                        _safe_text(f"{label}\n{spec.note}" if spec.note else label),
                        ha="center", va="center", fontsize=6,
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.7))

        elif m_type == "point":
            marker = style.get("marker", "o")
            size = style.get("size", 60)
            pts = self._generate_point_positions(bounds, spec)
            for px, py in pts:
                ax.scatter(px, py, c=color, marker=marker, s=size,
                           zorder=5, edgecolors="#333", linewidths=0.5)
            if label not in legend_handles and pts:
                legend_handles[label] = ax.scatter(
                    [], [], c=color, marker=marker, s=size,
                    edgecolors="#333", linewidths=0.5, label=label)
            if detail and pts:
                ax.annotate(_safe_text(f"{label}\n{spec.note}" if spec.note else label),
                            xy=(pts[0][0], pts[0][1]),
                            xytext=(10, 10), textcoords="offset points",
                            fontsize=7, ha="left",
                            arrowprops=dict(arrowstyle="->", color="#666"),
                            bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.7))

    def _draw_resolved_on_ax(
        self, ax, resolved: dict, style: dict, label: str,
        legend_handles: dict, detail: bool, spec: MeasureSpec,
    ):
        """绘制 resolver 返回的精确几何措施 (彩色渲染)。"""
        color = style.get("color", "#666")
        # 获取专业色覆盖
        pro_color = get_measure_color(spec.name)
        if pro_color:
            color = pro_color

        if "polyline" in resolved:
            pts = resolved["polyline"]
            if len(pts) >= 2:
                lw = style.get("linewidth", 2.0)
                ls = style.get("linestyle", "-")
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                line, = ax.plot(xs, ys, color=color, linewidth=lw,
                                linestyle=ls, zorder=ZORDER["measure_line"])
                if label not in legend_handles:
                    legend_handles[label] = line
                # 方向箭头
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
                if detail and pts:
                    mid = len(pts) // 2
                    note_text = _safe_text(f"{label}\n{spec.note}" if spec.note else label)
                    ax.annotate(note_text, xy=(xs[mid], ys[mid]),
                                fontsize=7, ha="center",
                                bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.8),
                                zorder=ZORDER["labels"])

        elif "polygon" in resolved:
            pts = resolved["polygon"]
            if len(pts) >= 3:
                alpha = 0.4
                xs = [p[0] for p in pts] + [pts[0][0]]
                ys = [p[1] for p in pts] + [pts[0][1]]
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
                if detail:
                    pcx = sum(p[0] for p in pts) / len(pts)
                    pcy = sum(p[1] for p in pts) / len(pts)
                    note_text = _safe_text(f"{label}\n{spec.note}" if spec.note else label)
                    ax.text(pcx, pcy, note_text,
                            ha="center", va="center", fontsize=6,
                            bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.8),
                            zorder=ZORDER["labels"])

        elif "points" in resolved:
            pts = resolved["points"]
            marker = style.get("marker", "o")
            size = style.get("size", 80)
            for px, py in pts:
                ax.scatter(px, py, c=color, marker=marker, s=size,
                           zorder=ZORDER["measure_point"], edgecolors="#333", linewidths=0.8)
            if label not in legend_handles and pts:
                legend_handles[label] = ax.scatter(
                    [], [], c=color, marker=marker, s=size,
                    edgecolors="#333", linewidths=0.8, label=label)
            if detail and pts:
                note_text = _safe_text(f"{label}\n{spec.note}" if spec.note else label)
                ax.annotate(note_text, xy=(pts[0][0], pts[0][1]),
                            xytext=(10, 10), textcoords="offset points",
                            fontsize=7, ha="left",
                            arrowprops=dict(arrowstyle="->", color=color),
                            bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.8),
                            zorder=ZORDER["labels"])

    def _generate_line_points(self, bounds: tuple, spec: MeasureSpec) -> list[tuple[float, float]]:
        """基于语义位置+方向生成线段点。"""
        x0, y0, x1, y1 = bounds
        w, h = x1 - x0, y1 - y0
        margin = min(w, h) * 0.05

        direction = spec.direction
        position = spec.position

        if position == "south" or direction == "east-west":
            return [(x0 + margin, y0 + h * 0.05), (x1 - margin, y0 + h * 0.05)]
        elif position == "north":
            return [(x0 + margin, y1 - h * 0.05), (x1 - margin, y1 - h * 0.05)]
        elif position == "east":
            return [(x1 - w * 0.05, y0 + margin), (x1 - w * 0.05, y1 - margin)]
        elif position == "west":
            return [(x0 + w * 0.05, y0 + margin), (x0 + w * 0.05, y1 - margin)]
        elif position == "perimeter":
            m = min(w, h) * 0.08
            return [(x0 + m, y0 + m), (x1 - m, y0 + m),
                    (x1 - m, y1 - m), (x0 + m, y1 - m), (x0 + m, y0 + m)]
        else:
            # 默认: 沿底+右
            m = min(w, h) * 0.08
            return [(x0 + m, y0 + m), (x1 - m, y0 + m), (x1 - m, y1 - m)]

    def _generate_fill_bounds(self, bounds: tuple, spec: MeasureSpec) -> tuple:
        """基于语义位置+覆盖范围生成填充区域。"""
        x0, y0, x1, y1 = bounds
        w, h = x1 - x0, y1 - y0
        mx, my = w * 0.1, h * 0.1

        coverage = spec.coverage
        position = spec.position

        if coverage == "full" or position == "center":
            return (x0 + mx, y0 + my, x1 - mx, y1 - my)
        elif position == "south":
            return (x0 + mx, y0 + my, x1 - mx, y0 + h * 0.4)
        elif position == "north":
            return (x0 + mx, y0 + h * 0.6, x1 - mx, y1 - my)
        elif position == "east":
            return (x0 + w * 0.6, y0 + my, x1 - mx, y1 - my)
        elif position == "west":
            return (x0 + mx, y0 + my, x0 + w * 0.4, y1 - my)
        elif position == "perimeter":
            return (x0 + mx * 0.5, y0 + my * 0.5, x1 - mx * 0.5, y1 - my * 0.5)
        else:
            # 使用名称 hash 做偏移以避免重叠
            idx = hash(spec.name) % 4
            offsets = [(0.15, 0.15, 0.55, 0.55),
                       (0.45, 0.15, 0.85, 0.55),
                       (0.15, 0.45, 0.55, 0.85),
                       (0.45, 0.45, 0.85, 0.85)]
            o = offsets[idx]
            return (x0 + w * o[0], y0 + h * o[1], x0 + w * o[2], y0 + h * o[3])

    def _generate_point_positions(self, bounds: tuple, spec: MeasureSpec) -> list[tuple[float, float]]:
        """基于语义位置生成散点坐标。"""
        x0, y0, x1, y1 = bounds
        pos_offsets = _POSITION_OFFSETS.get(spec.position, (0.5, 0.5))
        cx = x0 + (x1 - x0) * pos_offsets[0]
        cy = y0 + (y1 - y0) * pos_offsets[1]
        return [(cx, cy)]

    # ── 断面图绘制方法 ─────────────────────────────────────────

    def _draw_channel_section(self, ax, name: str, tmpl: dict):
        """矩形排水沟/截水沟/急流槽断面。"""
        w = tmpl.get("width", 0.4)
        d = tmpl.get("depth", 0.4)
        tw = tmpl.get("wall_thickness", 0.08)
        tf = tmpl.get("floor_thickness", 0.08)
        mat = tmpl.get("material", "C20混凝土")

        outer_x = [-tw, w + tw, w + tw, -tw, -tw]
        outer_y = [0, 0, -(d + tf), -(d + tf), 0]
        ax.fill(outer_x, outer_y, color="#C0C0C0", edgecolor="#000",
                linewidth=1.5, hatch="///", label=mat)

        inner_x = [0, w, w, 0, 0]
        inner_y = [0, 0, -d, -d, 0]
        ax.fill(inner_x, inner_y, color="white", edgecolor="#000",
                linewidth=1.0, label="水流断面")

        ground_ext = max(w, 0.5)
        ax.plot([-ground_ext, -tw], [0, 0], "k-", linewidth=2)
        ax.plot([w + tw, w + ground_ext + 0.5], [0, 0], "k-", linewidth=2)
        ax.fill_between([-ground_ext, -tw], [0, 0], [0.15, 0.15],
                        color="#D0D0D0", alpha=0.5, hatch="...")
        ax.fill_between([w + tw, w + ground_ext + 0.5], [0, 0], [0.15, 0.15],
                        color="#D0D0D0", alpha=0.5)

        self._dim_line(ax, 0, -d - tf - 0.15, w, -d - tf - 0.15, f"{w*100:.0f}cm")
        self._dim_line_v(ax, w + tw + 0.1, 0, w + tw + 0.1, -d, f"{d*100:.0f}cm")
        self._dim_line_v(ax, -tw - 0.15, 0, -tw - 0.15, -(d + tf), f"{(d+tf)*100:.0f}cm")

        ax.legend(loc="upper right", fontsize=7)

    def _draw_wall_section(self, ax, name: str, tmpl: dict):
        """重力式挡土墙断面。"""
        h = tmpl.get("height", 2.0)
        tw = tmpl.get("top_width", 0.5)
        bw = tmpl.get("bottom_width", 1.2)
        fd = tmpl.get("foundation_depth", 0.5)
        mat = tmpl.get("material", "M7.5浆砌石")

        wall_x = [0, tw, bw, 0, 0]
        wall_y = [h, h, 0, 0, h]
        ax.fill(wall_x, wall_y, color="#A0A0A0", edgecolor="#000",
                linewidth=1.5, hatch="xxx", label=mat)

        base_w = bw + 0.3
        ax.fill([-0.15, base_w, base_w, -0.15, -0.15],
                [0, 0, -fd, -fd, 0],
                color="#C0C0C0", edgecolor="#000", linewidth=1.0,
                hatch="///", label="基础")

        ax.fill([bw, bw + 1.5, bw + 1.5, bw + 0.3, bw],
                [0, 0, h * 0.7, h, h],
                color="#D0D0D0", alpha=0.5, hatch="...", label="回填土")

        ax.plot([-1, 0], [0, 0], "k-", linewidth=2)
        ax.plot([bw, bw + 2], [0, 0], "k-", linewidth=2)

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

        outer_x = [-tw, length + tw, length + tw, -tw, -tw]
        outer_y = [0.3, 0.3, -(depth + tf), -(depth + tf), 0.3]
        ax.fill(outer_x, outer_y, color="#C0C0C0", edgecolor="#000",
                linewidth=1.5, hatch="///", label=mat)

        inner_x = [0, length, length, 0, 0]
        inner_y = [0, 0, -depth, -depth, 0]
        ax.fill(inner_x, inner_y, color="white", edgecolor="#000",
                linewidth=1.0, label="蓄水空间")

        ax.plot([-1, -tw], [0, 0], "k-", linewidth=2)
        ax.plot([length + tw, length + 1.5], [0, 0], "k-", linewidth=2)

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

        offset = (tw - bw) / 2
        trap_x = [0, tw, tw - offset, offset, 0]
        trap_y = [0, 0, -d, -d, 0]
        ax.fill(trap_x, trap_y, color="#D2B48C", edgecolor="#000",
                linewidth=1.5, hatch="...", label=f"{mat}沟体")

        wall_t = 0.03
        inner_x = [wall_t, tw - wall_t, tw - offset - wall_t * 0.5,
                   offset + wall_t * 0.5, wall_t]
        inner_y = [0, 0, -(d - wall_t), -(d - wall_t), 0]
        ax.fill(inner_x, inner_y, color="white", edgecolor="#666",
                linewidth=0.5, label="过水断面")

        ground_ext = max(tw, 0.5)
        ax.plot([-ground_ext * 0.5, 0], [0, 0], "k-", linewidth=2)
        ax.plot([tw, tw + ground_ext * 0.5], [0, 0], "k-", linewidth=2)
        ax.fill_between([-ground_ext * 0.5, 0], [0, 0], [0.1, 0.1],
                        color="#D0D0D0", alpha=0.5, hatch="...")
        ax.fill_between([tw, tw + ground_ext * 0.5], [0, 0], [0.1, 0.1],
                        color="#D0D0D0", alpha=0.5)

        self._dim_line(ax, 0, 0.12, tw, 0.12, f"{tw*100:.0f}cm")
        self._dim_line(ax, offset, -d - 0.12, tw - offset, -d - 0.12,
                       f"{bw*100:.0f}cm")
        self._dim_line_v(ax, tw + 0.1, 0, tw + 0.1, -d, f"{d*100:.0f}cm")
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
            ax.text(total_w + 0.05, (y_top + y_bottom) / 2,
                    f"{lname} ({thickness*100:.0f}cm)",
                    fontsize=7, va="center", ha="left")
            y_top = y_bottom

        ax.plot([-0.2, 0], [0, 0], "k-", linewidth=2)
        ax.plot([total_w, total_w + 0.2], [0, 0], "k-", linewidth=2)

        total_d = sum(l.get("thickness", 0.05) for l in layers)
        self._dim_line_v(ax, -0.15, 0, -0.15, -total_d,
                         f"{total_d*100:.0f}cm")
        self._dim_line(ax, 0, -total_d - 0.08, total_w, -total_d - 0.08,
                       f"{total_w*100:.0f}cm")
        ax.legend(loc="upper right", fontsize=7)

    def _draw_wash_platform_section(self, ax, name: str, tmpl: dict):
        """车辆冲洗平台断面。"""
        length = tmpl.get("length", 6.0)
        depth = tmpl.get("depth", 0.3)
        slab_t = tmpl.get("slab_thickness", 0.20)
        mat = tmpl.get("material", "C20混凝土")

        pool_w = length * 0.3
        pool_d = depth + 0.2
        pool_x0 = (length - pool_w) / 2

        ax.fill([0, length, length, 0, 0],
                [0, 0, -slab_t, -slab_t, 0],
                color="#C0C0C0", edgecolor="#000", linewidth=1.5,
                hatch="///", label=f"{mat}基础")

        ax.fill([pool_x0, pool_x0 + pool_w, pool_x0 + pool_w, pool_x0, pool_x0],
                [-slab_t, -slab_t, -slab_t - pool_d, -slab_t - pool_d, -slab_t],
                color="#B0C4DE", edgecolor="#000", linewidth=1.0,
                hatch="...", label="集水坑")

        mid_x = length / 2
        arrow_y = 0.08
        ax.annotate("", xy=(mid_x, arrow_y), xytext=(0.3, arrow_y + 0.05),
                    arrowprops=dict(arrowstyle="->", color="#1E90FF", lw=1.2))
        ax.annotate("", xy=(mid_x, arrow_y), xytext=(length - 0.3, arrow_y + 0.05),
                    arrowprops=dict(arrowstyle="->", color="#1E90FF", lw=1.2))
        ax.text(mid_x, arrow_y + 0.08, "2%坡", fontsize=7, ha="center",
                color="#1E90FF")

        ax.plot([-0.5, 0], [0, 0], "k-", linewidth=2)
        ax.plot([length, length + 0.5], [0, 0], "k-", linewidth=2)

        self._dim_line(ax, 0, -slab_t - pool_d - 0.2, length,
                       -slab_t - pool_d - 0.2, f"{length:.1f}m")
        self._dim_line_v(ax, length + 0.2, 0, length + 0.2, -slab_t,
                         f"{slab_t*100:.0f}cm")
        self._dim_line(ax, pool_x0, -slab_t - pool_d - 0.1,
                       pool_x0 + pool_w, -slab_t - pool_d - 0.1,
                       f"{pool_w:.1f}m")
        ax.legend(loc="upper right", fontsize=7)

    # ── 装饰与标注辅助 ────────────────────────────────────────

    def _add_professional_decorations(self, fig, ax,
                                       show_area_table: bool = False):
        """添加专业装饰: 指北针、比例尺、标题栏、网格、坐标轴格式化。

        Args:
            show_area_table: 是否显示分区面积表 (zone_boundary 图专用)
        """
        from matplotlib.ticker import FuncFormatter

        # ── 修复科学记数法坐标轴 ──
        ax.ticklabel_format(style='plain', useOffset=False)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, p: f"{x:.0f}"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f"{x:.0f}"))

        # ── 双层网格 ──
        ax.grid(True, which='major', alpha=0.2, linestyle="-", linewidth=0.6)
        ax.grid(True, which='minor', alpha=0.08, linestyle=":", linewidth=0.3)
        ax.minorticks_on()

        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        dx = xlim[1] - xlim[0]
        dy = ylim[1] - ylim[0]

        # ── 指北针 (左上角, 填充三角箭头) ──
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

        # ── 比例尺 (右下角, 分格黑白尺 + 1:N 标注) ──
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
            # 比例标注 1:N
            fig_w_inches = fig.get_size_inches()[0]
            if fig_w_inches > 0 and dx > 0:
                scale_n = int(dx / (fig_w_inches * 0.0254))
                if scale_n > 0:
                    nice = self._nice_scale_number(scale_n)
                    ax.text(bx + bar_len / 2, by + bar_h + dy * 0.008,
                            f"1:{nice}",
                            fontsize=7, ha="center", va="bottom", zorder=10)

        # ── 标题栏 (底部, 带边框分格的工程图签) ──
        project_name = ""
        if hasattr(self, '_spatial') and isinstance(self._spatial, dict):
            project_name = self._spatial.get("project_name", "")
        title_text = self._plan.title or "水土保持措施图"

        # 构造工程图签: 项目名 | 图名 | 比例
        parts = []
        if project_name:
            parts.append(_safe_text(project_name))
        parts.append(_safe_text(title_text))
        if bar_len > 0 and fig_w_inches > 0 and dx > 0:
            scale_n = int(dx / (fig_w_inches * 0.0254))
            if scale_n > 0:
                parts.append(f"1:{self._nice_scale_number(scale_n)}")
        tb_text = "  |  ".join(parts)
        fig.text(0.5, 0.01, tb_text, fontsize=8, ha="center", va="bottom",
                 bbox=dict(boxstyle="round,pad=0.4", fc="#F8F8F8",
                           ec="#333", linewidth=1.0))

        # ── 分区面积表 (左下角, zone_boundary 图专用) ──
        if show_area_table and self._zones:
            table_lines = ["分区面积表:"]
            total_area = 0.0
            for z in self._zones:
                name = z.get("name", "")
                area = z.get("area_hm2", 0)
                total_area += area
                table_lines.append(f"  {name}: {area} hm2")
            table_lines.append(f"  合计: {total_area:.4f} hm2")
            table_text = "\n".join(table_lines)
            ax.text(
                xlim[0] + dx * 0.02, ylim[0] + dy * 0.02,
                _safe_text(table_text),
                fontsize=6, va="bottom", ha="left",
                family="monospace",
                bbox=dict(boxstyle="round,pad=0.4", fc="white",
                          ec="#666", alpha=0.9, linewidth=0.5),
                zorder=10,
            )

        # ── 移除 "X (m)" / "Y (m)" 标签, 缩小坐标轴字号 ──
        ax.set_xlabel("", fontsize=0)
        ax.set_ylabel("", fontsize=0)
        ax.tick_params(labelsize=6)

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

    def _dim_line(self, ax, x1, y1, x2, y2, text: str):
        """水平尺寸标注线。"""
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="<->", color="#333", lw=0.8))
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 - 0.05, text,
                ha="center", va="top", fontsize=8, color="#333")

    def _dim_line_v(self, ax, x1, y1, x2, y2, text: str):
        """垂直尺寸标注线。"""
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="<->", color="#333", lw=0.8))
        ax.text((x1 + x2) / 2 + 0.05, (y1 + y2) / 2, text,
                ha="left", va="center", fontsize=8, color="#333",
                rotation=90)

    @staticmethod
    def _plot_gis_polygon(ax, geometry, color: str, name: str,
                           alpha: float = 0.5):
        """绘制 GIS 多边形。"""
        try:
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

    # ═══════════════════════════════════════════════════════════
    # DXF 渲染 (ezdxf)
    # ═══════════════════════════════════════════════════════════

    def render_dxf(self, filename: str) -> Path | None:
        """渲染 DXF 文件 — 甲方可在 CAD 中直接编辑。"""
        try:
            import ezdxf
        except ImportError:
            logger.warning("ezdxf 未安装, 跳过 DXF 生成")
            return None

        if not filename.endswith(".dxf"):
            filename += ".dxf"

        doc = ezdxf.new("R2010")
        self._setup_dxf_layers(doc)
        msp = doc.modelspace()

        map_type = self._plan.map_type

        if map_type == "typical_section":
            self._dxf_add_sections(msp)
        else:
            self._dxf_add_zones(msp)
            if map_type in ("measure_layout", "zone_detail"):
                self._dxf_add_measures(msp)

        self._dxf_add_title_block(msp)

        path = self._output_dir / filename
        doc.saveas(str(path))
        logger.info(f"DXF 已生成: {path.name}")
        return path

    def _setup_dxf_layers(self, doc):
        """创建 DXF 图层。"""
        for layer_name, props in DXF_LAYERS.items():
            doc.layers.add(layer_name, color=props["color"])

    def _dxf_add_zones(self, msp):
        """向 DXF 添加分区多边形。"""
        for zs in self._plan.zones:
            geom = self._zone_geoms.get(zs.name)
            if not geom:
                continue

            if geom["type"] == "cad":
                polygon = geom["polygon"]
                msp.add_lwpolyline(
                    polygon, close=True,
                    dxfattribs={"layer": "ZONE_BOUNDARIES"}
                )
            elif geom["type"] == "rect":
                bounds = geom["bounds"]
                x0, y0, x1, y1 = bounds
                points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                msp.add_lwpolyline(
                    points, close=True,
                    dxfattribs={"layer": "ZONE_BOUNDARIES"}
                )
            elif geom["type"] == "gis":
                try:
                    geometry = geom["geometry"]
                    if geometry.geom_type == "Polygon":
                        coords = list(geometry.exterior.coords)
                        msp.add_lwpolyline(
                            [(c[0], c[1]) for c in coords], close=True,
                            dxfattribs={"layer": "ZONE_BOUNDARIES"}
                        )
                    elif geometry.geom_type == "MultiPolygon":
                        for poly in geometry.geoms:
                            coords = list(poly.exterior.coords)
                            msp.add_lwpolyline(
                                [(c[0], c[1]) for c in coords], close=True,
                                dxfattribs={"layer": "ZONE_BOUNDARIES"}
                            )
                except Exception as e:
                    logger.warning(f"DXF GIS 多边形写入失败: {e}")

            # 标注
            cx, cy = geom["centroid"]
            area_hm2 = 0.0
            for z in self._zones:
                if z.get("name") == zs.name:
                    area_hm2 = z.get("area_hm2", 0)
                    break

            text_height = max(1.0, (geom.get("area_m2", 1000) ** 0.5) * 0.02)
            msp.add_mtext(
                f"{zs.name}\n{area_hm2} hm2",
                dxfattribs={
                    "layer": "ZONE_LABELS",
                    "insert": (cx, cy),
                    "char_height": text_height,
                }
            )

    def _dxf_add_measures(self, msp):
        """向 DXF 添加措施实体。"""
        for ms in self._plan.measures:
            zone_geom = self._zone_geoms.get(ms.zone)
            if not zone_geom:
                continue

            style = get_style(ms.name)
            m_type = style.get("type", "fill")
            bounds = zone_geom.get("bounds", (0, 0, 100, 100))

            # 尝试 resolver (优先预计算)
            resolved = None
            if ms.cad_coords and ms.cad_geom_type:
                resolved = {ms.cad_geom_type: ms.cad_coords}
            elif self._resolver:
                if hasattr(self._resolver, 'get_placement'):
                    resolved = self._resolver.get_placement(ms.name, ms.zone)
                if resolved is None:
                    resolved = self._resolver.resolve(ms.name, ms.zone, zone_bounds=bounds)
            if resolved:
                self._dxf_add_resolved_measure(msp, resolved, ms.name)
                continue

            if m_type == "line":
                line_pts = self._generate_line_points(bounds, ms)
                if len(line_pts) >= 2:
                    msp.add_lwpolyline(
                        line_pts,
                        dxfattribs={"layer": "MEASURES_LINE"}
                    )
                # 标注
                if line_pts:
                    mid = len(line_pts) // 2
                    msp.add_mtext(
                        ms.name,
                        dxfattribs={
                            "layer": "ANNOTATIONS",
                            "insert": line_pts[mid],
                            "char_height": 0.8,
                        }
                    )

            elif m_type == "fill":
                fb = self._generate_fill_bounds(bounds, ms)
                points = [(fb[0], fb[1]), (fb[2], fb[1]),
                          (fb[2], fb[3]), (fb[0], fb[3])]
                msp.add_lwpolyline(
                    points, close=True,
                    dxfattribs={"layer": "MEASURES_FILL"}
                )
                cx = (fb[0] + fb[2]) / 2
                cy = (fb[1] + fb[3]) / 2
                msp.add_mtext(
                    ms.name,
                    dxfattribs={
                        "layer": "ANNOTATIONS",
                        "insert": (cx, cy),
                        "char_height": 0.6,
                    }
                )

            elif m_type == "point":
                pts = self._generate_point_positions(bounds, ms)
                for px, py in pts:
                    msp.add_circle(
                        (px, py), radius=0.5,
                        dxfattribs={"layer": "MEASURES_POINT"}
                    )
                    msp.add_mtext(
                        ms.name,
                        dxfattribs={
                            "layer": "ANNOTATIONS",
                            "insert": (px + 1, py),
                            "char_height": 0.5,
                        }
                    )

    def _dxf_add_resolved_measure(self, msp, resolved: dict, name: str):
        """向 DXF 添加 resolver 解析的措施实体。"""
        if "polyline" in resolved:
            pts = resolved["polyline"]
            if len(pts) >= 2:
                msp.add_lwpolyline(
                    pts, dxfattribs={"layer": "MEASURES_LINE"})
                mid = len(pts) // 2
                msp.add_mtext(
                    name,
                    dxfattribs={"layer": "ANNOTATIONS",
                                "insert": pts[mid], "char_height": 0.8})
        elif "polygon" in resolved:
            pts = resolved["polygon"]
            if len(pts) >= 3:
                msp.add_lwpolyline(
                    pts, close=True, dxfattribs={"layer": "MEASURES_FILL"})
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                msp.add_mtext(
                    name,
                    dxfattribs={"layer": "ANNOTATIONS",
                                "insert": (cx, cy), "char_height": 0.6})
        elif "points" in resolved:
            for px, py in resolved["points"]:
                msp.add_circle(
                    (px, py), radius=0.5,
                    dxfattribs={"layer": "MEASURES_POINT"})
                msp.add_mtext(
                    name,
                    dxfattribs={"layer": "ANNOTATIONS",
                                "insert": (px + 1, py), "char_height": 0.5})

    def _dxf_add_sections(self, msp):
        """向 DXF 添加断面图。"""
        for sec in self._plan.sections:
            tmpl = SECTION_TEMPLATES.get(sec.structure)
            if not tmpl:
                for tk, tv in SECTION_TEMPLATES.items():
                    if tk in sec.structure or sec.structure in tk:
                        tmpl = tv
                        break
            if not tmpl:
                continue

            shape = tmpl.get("shape", "rectangular_channel")
            if shape in ("rectangular_channel", "chute"):
                w = tmpl.get("width", 0.4)
                d = tmpl.get("depth", 0.4)
                tw = tmpl.get("wall_thickness", 0.08)
                tf = tmpl.get("floor_thickness", 0.08)
                # 外轮廓
                outer = [(-tw, 0), (w + tw, 0), (w + tw, -(d + tf)), (-tw, -(d + tf))]
                msp.add_lwpolyline(outer, close=True,
                                   dxfattribs={"layer": "MEASURES_LINE"})
                # 内腔
                inner = [(0, 0), (w, 0), (w, -d), (0, -d)]
                msp.add_lwpolyline(inner, close=True,
                                   dxfattribs={"layer": "MEASURES_LINE"})
            elif shape == "gravity_wall":
                h = tmpl.get("height", 2.0)
                tw = tmpl.get("top_width", 0.5)
                bw = tmpl.get("bottom_width", 1.2)
                wall = [(0, h), (tw, h), (bw, 0), (0, 0)]
                msp.add_lwpolyline(wall, close=True,
                                   dxfattribs={"layer": "MEASURES_LINE"})
            elif shape == "sedimentation_tank":
                length = tmpl.get("length", 2.0)
                depth = tmpl.get("depth", 1.5)
                tw = tmpl.get("wall_thickness", 0.24)
                tf = tmpl.get("floor_thickness", 0.15)
                outer = [(-tw, 0.3), (length + tw, 0.3),
                         (length + tw, -(depth + tf)), (-tw, -(depth + tf))]
                msp.add_lwpolyline(outer, close=True,
                                   dxfattribs={"layer": "MEASURES_LINE"})
                inner = [(0, 0), (length, 0), (length, -depth), (0, -depth)]
                msp.add_lwpolyline(inner, close=True,
                                   dxfattribs={"layer": "MEASURES_LINE"})

            # 标注
            msp.add_mtext(
                sec.structure,
                dxfattribs={
                    "layer": "ANNOTATIONS",
                    "insert": (0, 1.0),
                    "char_height": 0.3,
                }
            )

    def _dxf_add_title_block(self, msp):
        """向 DXF 添加标题栏。"""
        title = self._plan.title or "水土保持措施图"
        msp.add_mtext(
            title,
            dxfattribs={
                "layer": "TITLE_BAR",
                "char_height": 2.0,
            }
        )
