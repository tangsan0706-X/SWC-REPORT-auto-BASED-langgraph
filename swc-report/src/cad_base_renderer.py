"""CAD 底图解析 + 背景渲染 — 从 DXF 提取几何实体并渲染为半透明背景层。

流程:  DXF → parse_dxf_geometry() → CadGeometry → CadBaseMapRenderer → matplotlib ax

功能:
  - 解析 DXF 实体 (LWPOLYLINE, LINE, ARC, CIRCLE, TEXT, HATCH, INSERT)
  - 按图层名启发式分类 (building/road/boundary/greenery/text/other)
  - 在 matplotlib axes 上渲染淡化 CAD 底图
  - 支持裁剪到指定区域 (用于分区详图)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class CadEntity:
    """单个 CAD 实体的简化表示。"""
    entity_type: str      # "polyline", "line", "arc", "circle", "text", "hatch"
    layer: str            # DXF 图层名
    category: str         # "building", "road", "boundary", "greenery", "text", "other"
    points: list[tuple[float, float]]
    closed: bool = False
    text_content: str = ""
    properties: dict = field(default_factory=dict)


@dataclass
class CadGeometry:
    """从 DXF 文件解析出的全部几何信息。"""
    entities: list[CadEntity]
    bounds: tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)
    buildings: list[CadEntity] = field(default_factory=list)
    roads: list[CadEntity] = field(default_factory=list)
    boundaries: list[CadEntity] = field(default_factory=list)
    greenery: list[CadEntity] = field(default_factory=list)
    texts: list[CadEntity] = field(default_factory=list)
    others: list[CadEntity] = field(default_factory=list)

    @property
    def content_bounds(self) -> tuple[float, float, float, float]:
        """仅建筑+道路实体的紧凑边界 (排除文字/红线等稀疏元素)。

        用于将分区矩形对齐到实际建筑内容区域。
        """
        content = self.buildings + self.roads
        if not content:
            return self.bounds
        xs, ys = [], []
        for ent in content:
            for px, py in ent.points:
                xs.append(px)
                ys.append(py)
        if not xs:
            return self.bounds
        cb = _compute_robust_bounds(xs, ys)
        return cb


# ═══════════════════════════════════════════════════════════════
# 图层分类
# ═══════════════════════════════════════════════════════════════

# 关键词 → 分类 (优先级从高到低)
_LAYER_KEYWORDS: list[tuple[str, list[str]]] = [
    ("building", [
        "建筑", "build", "bldg", "buid", "house", "构筑", "结构", "struct",
        "wall", "墙", "柱", "column", "arch", "foundation", "基础",
        "地下室", "basement", "roof", "屋顶", "楼梯", "stair",
        "flor", "floor", "elev", "cons", "fenc",
    ]),
    ("road", [
        "道路", "road", "path", "drive", "drwy", "车道", "人行", "sidewalk",
        "广场", "plaza", "square", "parking", "停车", "铺装", "pave",
        "dmtz", "车行道", "land-road", "land_road",
    ]),
    ("boundary", [
        "红线", "redline", "用地", "site", "boundary", "边界", "bound",
        "范围", "scope", "征地", "land", "规划", "plan", "limt",
    ]),
    ("greenery", [
        "绿化", "green", "landscape", "植物", "plant", "grass", "草",
        "树", "tree", "garden", "花园", "绿地", "绿带",
    ]),
    ("text", [
        "标注", "dim", "text", "anno", "label", "note", "文字",
        "尺寸", "dimension", "coord", "坐标", "numb", "pltb",
    ]),
]


def _categorize_layer(layer_name: str) -> str:
    """根据图层名称启发式分类。"""
    low = layer_name.lower()
    for category, keywords in _LAYER_KEYWORDS:
        for kw in keywords:
            if kw in low:
                return category
    return "other"


# ═══════════════════════════════════════════════════════════════
# DXF 实体提取
# ═══════════════════════════════════════════════════════════════

def _extract_dxf_color(entity) -> dict:
    """提取 DXF 实体颜色属性。"""
    props = {}
    try:
        props["dxf_color"] = entity.dxf.color
    except AttributeError:
        pass
    return props


def _extract_lwpolyline(entity) -> CadEntity | None:
    """提取 LWPOLYLINE 实体。"""
    try:
        pts = [(p[0], p[1]) for p in entity.get_points(format="xy")]
        if not pts:
            return None
        layer = entity.dxf.layer if entity.dxf.hasattr("layer") else "0"
        return CadEntity(
            entity_type="polyline",
            layer=layer,
            category=_categorize_layer(layer),
            points=pts,
            closed=entity.closed,
            properties=_extract_dxf_color(entity),
        )
    except Exception:
        return None


def _extract_line(entity) -> CadEntity | None:
    """提取 LINE 实体。"""
    try:
        start = entity.dxf.start
        end = entity.dxf.end
        layer = entity.dxf.layer if entity.dxf.hasattr("layer") else "0"
        return CadEntity(
            entity_type="line",
            layer=layer,
            category=_categorize_layer(layer),
            points=[(start.x, start.y), (end.x, end.y)],
            properties=_extract_dxf_color(entity),
        )
    except Exception:
        return None


def _extract_arc(entity, num_segments: int = 16) -> CadEntity | None:
    """提取 ARC 实体 — 离散化为折线。"""
    try:
        cx, cy = entity.dxf.center.x, entity.dxf.center.y
        r = entity.dxf.radius
        start_angle = math.radians(entity.dxf.start_angle)
        end_angle = math.radians(entity.dxf.end_angle)

        if end_angle <= start_angle:
            end_angle += 2 * math.pi

        pts = []
        for i in range(num_segments + 1):
            t = start_angle + (end_angle - start_angle) * i / num_segments
            pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))

        layer = entity.dxf.layer if entity.dxf.hasattr("layer") else "0"
        return CadEntity(
            entity_type="arc",
            layer=layer,
            category=_categorize_layer(layer),
            points=pts,
            properties=_extract_dxf_color(entity),
        )
    except Exception:
        return None


def _extract_circle(entity, num_segments: int = 32) -> CadEntity | None:
    """提取 CIRCLE 实体 — 离散化为闭合折线。"""
    try:
        cx, cy = entity.dxf.center.x, entity.dxf.center.y
        r = entity.dxf.radius
        pts = []
        for i in range(num_segments):
            t = 2 * math.pi * i / num_segments
            pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
        layer = entity.dxf.layer if entity.dxf.hasattr("layer") else "0"
        props = {"radius": r, "center": (cx, cy)}
        props.update(_extract_dxf_color(entity))
        return CadEntity(
            entity_type="circle",
            layer=layer,
            category=_categorize_layer(layer),
            points=pts,
            closed=True,
            properties=props,
        )
    except Exception:
        return None


def _extract_polyline2d(entity) -> CadEntity | None:
    """提取 POLYLINE (2D/3D) 实体 — 旧格式, 与 LWPOLYLINE 不同。"""
    try:
        pts = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        if not pts:
            return None
        layer = entity.dxf.layer if entity.dxf.hasattr("layer") else "0"
        closed = entity.is_closed
        return CadEntity(
            entity_type="polyline",
            layer=layer,
            category=_categorize_layer(layer),
            points=pts,
            closed=closed,
            properties=_extract_dxf_color(entity),
        )
    except Exception:
        return None


def _extract_text(entity) -> CadEntity | None:
    """提取 TEXT / MTEXT 实体。"""
    try:
        dxftype = entity.dxftype()
        if dxftype == "TEXT":
            text = entity.dxf.text
            pos = entity.dxf.insert
        elif dxftype == "MTEXT":
            text = entity.text  # plain text
            pos = entity.dxf.insert
        else:
            return None

        layer = entity.dxf.layer if entity.dxf.hasattr("layer") else "0"
        return CadEntity(
            entity_type="text",
            layer=layer,
            category="text",
            points=[(pos.x, pos.y)],
            text_content=text or "",
        )
    except Exception:
        return None


def _resolve_insert(entity, doc, depth: int = 0, max_depth: int = 5,
                    _cache: dict | None = None) -> list[CadEntity]:
    """递归解析 INSERT 块引用。"""
    if depth >= max_depth:
        return []
    if _cache is None:
        _cache = {}

    try:
        block_name = entity.dxf.name
        insert_point = entity.dxf.insert
        ox, oy = insert_point.x, insert_point.y

        # 缩放和旋转
        sx = entity.dxf.get("xscale", 1.0)
        sy = entity.dxf.get("yscale", 1.0)
        rotation = math.radians(entity.dxf.get("rotation", 0.0))

        block = doc.blocks.get(block_name)
        if block is None:
            return []

        results = []
        for sub_entity in block:
            dxftype = sub_entity.dxftype()

            if dxftype == "INSERT":
                sub_results = _resolve_insert(
                    sub_entity, doc, depth + 1, max_depth, _cache
                )
                for ent in sub_results:
                    ent.points = [_transform_point(p, ox, oy, sx, sy, rotation)
                                  for p in ent.points]
                results.extend(sub_results)
                continue

            ent = _extract_entity(sub_entity)
            if ent is not None:
                ent.points = [_transform_point(p, ox, oy, sx, sy, rotation)
                              for p in ent.points]
                results.append(ent)

        return results
    except Exception:
        return []


def _transform_point(
    p: tuple[float, float],
    ox: float, oy: float,
    sx: float, sy: float,
    rotation: float,
) -> tuple[float, float]:
    """对点应用缩放+旋转+平移变换。"""
    x, y = p[0] * sx, p[1] * sy
    cos_r, sin_r = math.cos(rotation), math.sin(rotation)
    rx = x * cos_r - y * sin_r
    ry = x * sin_r + y * cos_r
    return (rx + ox, ry + oy)


def _extract_entity(entity) -> CadEntity | None:
    """分发实体提取。"""
    dxftype = entity.dxftype()
    if dxftype == "LWPOLYLINE":
        return _extract_lwpolyline(entity)
    elif dxftype == "POLYLINE":
        return _extract_polyline2d(entity)
    elif dxftype == "LINE":
        return _extract_line(entity)
    elif dxftype == "ARC":
        return _extract_arc(entity)
    elif dxftype == "CIRCLE":
        return _extract_circle(entity)
    elif dxftype in ("TEXT", "MTEXT"):
        return _extract_text(entity)
    return None


# ═══════════════════════════════════════════════════════════════
# 主解析函数
# ═══════════════════════════════════════════════════════════════

def _compute_robust_bounds(
    xs: list[float], ys: list[float],
) -> tuple[float, float, float, float]:
    """使用 MAD (中位数绝对偏差) 过滤离群点后计算稳健边界。

    CAD 文件常有多个坐标簇 (总图+放大图+图框)，
    用 MAD 方法锁定最大密度簇作为主体区域。
    """
    if not xs or not ys:
        return (0, 0, 1, 1)

    n = len(xs)
    if n < 10:
        return (min(xs), min(ys), max(xs), max(ys))

    sx = sorted(xs)
    sy = sorted(ys)

    # 中位数
    med_x = sx[n // 2]
    med_y = sy[n // 2]

    # MAD (中位数绝对偏差)
    mad_x = sorted(abs(v - med_x) for v in xs)[n // 2]
    mad_y = sorted(abs(v - med_y) for v in ys)[n // 2]

    # 防止 MAD=0 (所有点相同)
    mad_x = max(mad_x, 1.0)
    mad_y = max(mad_y, 1.0)

    # 保留 median ± 6*MAD 范围内的点
    k = 6.0
    x_lo = med_x - k * mad_x
    x_hi = med_x + k * mad_x
    y_lo = med_y - k * mad_y
    y_hi = med_y + k * mad_y

    fx = [v for v in xs if x_lo <= v <= x_hi]
    fy = [v for v in ys if y_lo <= v <= y_hi]

    if not fx or not fy:
        return (min(xs), min(ys), max(xs), max(ys))

    return (min(fx), min(fy), max(fx), max(fy))


def parse_dxf_geometry(dxf_path: str | Path) -> CadGeometry | None:
    """解析 DXF 文件，提取所有几何实体并分类。

    Args:
        dxf_path: DXF 文件路径

    Returns:
        CadGeometry 对象，或 None (文件不存在/解析失败)
    """
    try:
        import ezdxf
    except ImportError:
        logger.warning("ezdxf 未安装, 无法解析 DXF 几何")
        return None

    dxf_path = Path(dxf_path)
    if not dxf_path.exists():
        logger.warning(f"DXF 文件不存在: {dxf_path}")
        return None

    try:
        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()
    except Exception as e:
        logger.error(f"DXF 读取失败 ({dxf_path.name}): {e}")
        return None

    entities: list[CadEntity] = []
    insert_cache: dict = {}

    for entity in msp:
        dxftype = entity.dxftype()

        if dxftype == "INSERT":
            sub_entities = _resolve_insert(entity, doc, _cache=insert_cache)
            entities.extend(sub_entities)
        else:
            ent = _extract_entity(entity)
            if ent is not None:
                entities.append(ent)

    if not entities:
        logger.warning(f"DXF 无可用实体: {dxf_path.name}")
        return None

    # 计算边界 (使用 IQR 过滤远离主体的零散实体)
    all_x = []
    all_y = []
    for ent in entities:
        for px, py in ent.points:
            all_x.append(px)
            all_y.append(py)

    if not all_x:
        return None

    bounds = _compute_robust_bounds(all_x, all_y)

    # 按分类分组
    buildings = [e for e in entities if e.category == "building"]
    roads = [e for e in entities if e.category == "road"]
    boundaries = [e for e in entities if e.category == "boundary"]
    greenery = [e for e in entities if e.category == "greenery"]
    texts = [e for e in entities if e.category == "text"]
    others = [e for e in entities if e.category == "other"]

    geom = CadGeometry(
        entities=entities,
        bounds=bounds,
        buildings=buildings,
        roads=roads,
        boundaries=boundaries,
        greenery=greenery,
        texts=texts,
        others=others,
    )

    logger.info(
        f"DXF 几何解析: {len(entities)} 实体 "
        f"(建筑 {len(buildings)}, 道路 {len(roads)}, "
        f"红线 {len(boundaries)}, 绿化 {len(greenery)}, "
        f"文字 {len(texts)}, 其他 {len(others)})"
    )

    return geom


# ═══════════════════════════════════════════════════════════════
# CAD 底图渲染器
# ═══════════════════════════════════════════════════════════════

# 分类 → 渲染样式 (升级版: 更清晰的分层与颜色)
_CAD_RENDER_STYLES = {
    "building": {
        "facecolor": "#E8E8E8",
        "edgecolor": "#1A1A1A",
        "linewidth": 1.5,
        "alpha_fill": 0.85,
        "alpha_line": 1.0,
        "zorder": 3,
    },
    "road": {
        "facecolor": "#F0F0F0",
        "edgecolor": "#444444",
        "linewidth": 1.8,
        "alpha_fill": 0.7,
        "alpha_line": 0.95,
        "zorder": 2,
    },
    "boundary": {
        "facecolor": "none",
        "edgecolor": "#CC0000",
        "linewidth": 2.5,
        "alpha_fill": 0.0,
        "alpha_line": 1.0,
        "linestyle": "--",
        "zorder": 5,
    },
    "greenery": {
        "facecolor": "#C8E6C9",
        "edgecolor": "#388E3C",
        "linewidth": 0.8,
        "alpha_fill": 0.6,
        "alpha_line": 0.8,
        "zorder": 1,
    },
    "other": {
        "facecolor": "none",
        "edgecolor": "#9E9E9E",
        "linewidth": 0.5,
        "alpha_fill": 0.0,
        "alpha_line": 0.5,
        "zorder": 0,
    },
}


# ── 全色渲染样式表 (用于 render_foreground, CAD 作为图面主体) ──
_FOREGROUND_STYLES = {
    "building": {
        "facecolor": "#D0D0D0",
        "edgecolor": "#1A1A1A",
        "linewidth": 1.5,
        "alpha": 0.95,
        "zorder": 3,
    },
    "road": {
        "facecolor": "#E8E8E8",
        "edgecolor": "#666666",
        "linewidth": 1.2,
        "alpha": 0.9,
        "zorder": 2,
    },
    "boundary": {
        "facecolor": "none",
        "edgecolor": "#FF0000",
        "linewidth": 3.0,
        "linestyle": "-",
        "alpha": 1.0,
        "zorder": 10,
    },
    "greenery": {
        "facecolor": "#C8E6C9",
        "edgecolor": "#388E3C",
        "linewidth": 0.8,
        "alpha": 0.5,
        "zorder": 1,
    },
    "other": {
        "facecolor": "none",
        "edgecolor": "#999999",
        "linewidth": 0.5,
        "alpha": 0.7,
        "zorder": 0,
    },
}


class CadBaseMapRenderer:
    """在 matplotlib axes 上渲染 CAD 底图。

    支持两种模式:
    - render_background(): 半透明背景层 (旧模式, 向后兼容)
    - render_foreground(): 全色渲染, CAD 作为图面主体 (专业制图模式)
    """

    def __init__(self, cad_geometry: CadGeometry, dxf_path: str | Path | None = None,
                 focus_bounds: tuple[float, float, float, float] | None = None):
        self._geom = cad_geometry
        self._dxf_path = Path(dxf_path) if dxf_path else None
        self._focus_bounds = focus_bounds  # 聚焦区域 (红线 bbox 或内容边界)
        # 预渲染的栅格底图 (numpy RGBA array)
        self._raster = None       # np.ndarray | None
        self._raster_extent = None  # (x0, x1, y0, y1)
        self._prerender()

    def _prerender(self):
        """使用 ezdxf 原生渲染器预渲染 DXF → 高清栅格图。"""
        if self._dxf_path is None or not self._dxf_path.exists():
            logger.info("无 DXF 路径, 使用实体模式渲染 CAD 底图")
            return

        try:
            import ezdxf
            from ezdxf.addons.drawing import RenderContext, Frontend
            from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np
        except ImportError:
            logger.warning("ezdxf/matplotlib 未安装, 使用实体模式渲染")
            return

        try:
            doc = ezdxf.readfile(str(self._dxf_path))
            msp = doc.modelspace()

            # 裁剪到 focus_bounds (优先) 或 MAD bounds (排除远处坐标簇)
            if self._focus_bounds:
                bx0, by0, bx1, by1 = self._focus_bounds
            else:
                bx0, by0, bx1, by1 = self._geom.bounds
            margin_x = (bx1 - bx0) * 0.05
            margin_y = (by1 - by0) * 0.05
            x0 = bx0 - margin_x
            x1 = bx1 + margin_x
            y0 = by0 - margin_y
            y1 = by1 + margin_y

            # figsize 精确匹配数据宽高比, 避免 letterbox
            data_w = x1 - x0
            data_h = y1 - y0
            aspect = data_w / data_h if data_h > 0 else 1.5
            render_dpi = 300
            if aspect >= 1:
                fig_w = 24.0  # inches
                fig_h = fig_w / aspect
            else:
                fig_h = 24.0
                fig_w = fig_h * aspect

            # 最大分辨率保护: 如果像素 > 8000x8000 则自适应降低 DPI
            max_px = 8000
            px_w = fig_w * render_dpi
            px_h = fig_h * render_dpi
            if px_w > max_px or px_h > max_px:
                scale_factor = max_px / max(px_w, px_h)
                render_dpi = int(render_dpi * scale_factor)

            # 先让 ezdxf 渲染 (它会改 figsize, 后面修正)
            fig = plt.figure(dpi=render_dpi)
            ax = fig.add_axes([0, 0, 1, 1])

            ctx = RenderContext(doc)
            backend = MatplotlibBackend(ax)
            Frontend(ctx, backend).draw_layout(msp)

            # ezdxf 会修改 figsize, 这里强制恢复
            fig.set_size_inches(fig_w, fig_h)
            ax.set_position([0, 0, 1, 1])
            ax.set_xlim(x0, x1)
            ax.set_ylim(y0, y1)
            ax.axis("off")

            # 渲染到 numpy RGBA 数组
            fig.canvas.draw()
            buf = fig.canvas.buffer_rgba()
            self._raster = np.asarray(buf).copy()
            self._raster_extent = (x0, x1, y0, y1)
            plt.close(fig)

            h, w = self._raster.shape[:2]
            logger.info(f"CAD 栅格预渲染完成: {w}x{h} px, "
                        f"范围 ({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f})")
        except Exception as e:
            logger.warning(f"CAD 栅格预渲染失败: {e}")
            self._raster = None

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self._geom.bounds

    @property
    def content_bounds(self) -> tuple[float, float, float, float]:
        """返回聚焦区域边界 (focus_bounds 优先, 否则回退到 geom content_bounds)。"""
        if self._focus_bounds:
            return self._focus_bounds
        return self._geom.content_bounds

    def render_background(
        self,
        ax,
        fade: float = 0.5,
        crop_bounds: tuple[float, float, float, float] | None = None,
        show_text: bool = False,
    ):
        """在 matplotlib axes 上绘制 CAD 底图。

        Args:
            ax: matplotlib Axes
            fade: 透明度 (0=透明, 1=不透明). 默认0.5
            crop_bounds: 裁剪区域 (min_x, min_y, max_x, max_y).
                         None=使用 CadGeometry.bounds
            show_text: 是否显示文字标注 (仅实体模式)
        """
        if self._raster is not None:
            self._render_raster(ax, fade, crop_bounds)
        else:
            self._render_entities(ax, fade, crop_bounds, show_text)

    def render_foreground(
        self,
        ax,
        crop_bounds: tuple[float, float, float, float] | None = None,
        show_text: bool = False,
        highlight_boundary: bool = True,
    ):
        """全色渲染 CAD 实体（作为图面主体，非背景）。

        始终使用实体分类渲染 (不用 ezdxf 栅格), 确保按类别着色:
        - 建筑: 深灰填充 + 黑色轮廓 (alpha=0.95)
        - 道路: 浅灰填充 (alpha=0.9)
        - 红线: 红色粗实线 (3.0px, #FF0000)
        - 绿化: 浅绿填充 (alpha=0.5)
        - 其他: 灰色线条 (alpha=0.7)

        Args:
            ax: matplotlib Axes
            crop_bounds: 裁剪区域 (min_x, min_y, max_x, max_y)
            show_text: 是否显示文字标注
            highlight_boundary: 是否在最顶层额外高亮红线
        """
        # 始终用实体分类渲染，而非 ezdxf 栅格 (栅格不区分分类颜色)
        self._render_entities_foreground(ax, crop_bounds, show_text)

        if highlight_boundary:
            self.render_boundary_highlight(ax)

    def render_boundary_highlight(self, ax, color="#FF0000", linewidth=3.0):
        """在最顶层渲染项目红线。"""
        for ent in self._geom.boundaries:
            if ent.points and len(ent.points) >= 2:
                xs = [p[0] for p in ent.points]
                ys = [p[1] for p in ent.points]
                if ent.closed:
                    xs.append(ent.points[0][0])
                    ys.append(ent.points[0][1])
                ax.plot(xs, ys, color=color, linewidth=linewidth,
                        linestyle="-", zorder=10, solid_capstyle="round")

    def _render_entities_foreground(
        self,
        ax,
        crop_bounds: tuple[float, float, float, float] | None,
        show_text: bool = False,
    ):
        """全色实体渲染 (非背景模式)。"""
        if crop_bounds is None:
            # 优先用 focus_bounds (聚类/红线 bbox), 避免渲染远处图框实体
            crop_bounds = self._focus_bounds or self._geom.bounds

        for ent in self._geom.entities:
            if ent.category == "text" and not show_text:
                continue
            if crop_bounds and not self._entity_in_bounds(ent, crop_bounds):
                continue

            style = _FOREGROUND_STYLES.get(ent.category,
                                           _FOREGROUND_STYLES["other"])

            if ent.entity_type == "text" and show_text:
                if ent.points:
                    ax.text(
                        ent.points[0][0], ent.points[0][1],
                        ent.text_content,
                        fontsize=5, color="#333333",
                        alpha=0.8, zorder=1,
                    )
                continue

            if not ent.points or len(ent.points) < 2:
                continue

            xs = [p[0] for p in ent.points]
            ys = [p[1] for p in ent.points]

            alpha = style["alpha"]
            lw = style["linewidth"]
            ls = style.get("linestyle", "-")
            zorder = style["zorder"]

            if ent.closed and style["facecolor"] != "none":
                ax.fill(
                    xs, ys,
                    facecolor=style["facecolor"],
                    edgecolor=style["edgecolor"],
                    linewidth=lw,
                    alpha=alpha,
                    zorder=zorder,
                    linestyle=ls,
                )
            else:
                ax.plot(
                    xs, ys,
                    color=style["edgecolor"],
                    linewidth=lw,
                    alpha=alpha,
                    zorder=zorder,
                    linestyle=ls,
                )

    def _render_raster(
        self,
        ax,
        fade: float,
        crop_bounds: tuple[float, float, float, float] | None,
    ):
        """使用预渲染栅格图作为底图 (高质量)。"""
        import numpy as np

        x0, x1, y0, y1 = self._raster_extent

        # 制作半透明版本: 非白色像素保持 alpha=fade，白色背景透明
        img = self._raster.copy().astype(np.float32) / 255.0
        # 检测非白色像素 (R+G+B < 2.8 即认为有内容)
        brightness = img[:, :, 0] + img[:, :, 1] + img[:, :, 2]
        content_mask = brightness < 2.85
        # 有内容的像素: alpha=fade; 白色背景: alpha=0 (完全透明)
        img[:, :, 3] = 0.0
        img[content_mask, 3] = fade

        ax.imshow(
            img,
            extent=[x0, x1, y0, y1],
            aspect="auto",
            zorder=0,
            interpolation="bilinear",
            origin="upper",  # numpy 数组 y 轴自上而下
        )

    def _render_entities(
        self,
        ax,
        fade: float,
        crop_bounds: tuple[float, float, float, float] | None,
        show_text: bool = False,
    ):
        """使用手动实体渲染 (回退模式, 当无 DXF 文件时)。"""
        if crop_bounds is None:
            crop_bounds = self._focus_bounds or self._geom.bounds

        for ent in self._geom.entities:
            if ent.category == "text" and not show_text:
                continue
            if crop_bounds and not self._entity_in_bounds(ent, crop_bounds):
                continue

            style = _CAD_RENDER_STYLES.get(ent.category, _CAD_RENDER_STYLES["other"])

            if ent.entity_type == "text" and show_text:
                if ent.points:
                    ax.text(
                        ent.points[0][0], ent.points[0][1],
                        ent.text_content,
                        fontsize=4, color="#AAAAAA",
                        alpha=fade * 0.5, zorder=0,
                    )
                continue

            if not ent.points or len(ent.points) < 2:
                continue

            xs = [p[0] for p in ent.points]
            ys = [p[1] for p in ent.points]

            line_alpha = style["alpha_line"] * fade
            fill_alpha = style["alpha_fill"] * fade
            lw = style["linewidth"]
            ls = style.get("linestyle", "-")
            zorder = style["zorder"]

            if ent.closed and style["facecolor"] != "none":
                # 闭合建筑实体: 填充 + 清晰边线
                ax.fill(
                    xs, ys,
                    facecolor=style["facecolor"],
                    edgecolor=style["edgecolor"],
                    linewidth=lw,
                    alpha=fill_alpha,
                    zorder=zorder,
                    linestyle=ls,
                )
                # 闭合道路实体: 双线渲染 (外轮廓 + 内缩 85% 的内线)
                if ent.category == "road" and len(ent.points) >= 3:
                    cx = sum(p[0] for p in ent.points) / len(ent.points)
                    cy = sum(p[1] for p in ent.points) / len(ent.points)
                    inner_xs = [cx + (x - cx) * 0.85 for x in xs]
                    inner_ys = [cy + (y - cy) * 0.85 for y in ys]
                    ax.plot(inner_xs, inner_ys,
                            color=style["edgecolor"],
                            linewidth=lw * 0.5,
                            alpha=line_alpha * 0.6,
                            zorder=zorder,
                            linestyle="--")
            else:
                ax.plot(
                    xs, ys,
                    color=style["edgecolor"],
                    linewidth=lw,
                    alpha=line_alpha,
                    zorder=zorder,
                    linestyle=ls,
                )

    @staticmethod
    def _entity_in_bounds(
        ent: CadEntity,
        bounds: tuple[float, float, float, float],
    ) -> bool:
        """检查实体是否与裁剪区域相交。"""
        x0, y0, x1, y1 = bounds
        margin_x = (x1 - x0) * 0.1
        margin_y = (y1 - y0) * 0.1
        x0 -= margin_x
        y0 -= margin_y
        x1 += margin_x
        y1 += margin_y

        for px, py in ent.points:
            if x0 <= px <= x1 and y0 <= py <= y1:
                return True
        return False
