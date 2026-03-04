"""CAD 特征分析器 + 措施放置解析器 — 从 CadGeometry 提取场地特征并智能布局措施。

流程:
  CadGeometry → CadFeatureAnalyzer.analyze() → CadSiteFeatures
  CadSiteFeatures + measure_name → MeasurePlacementResolver.resolve() → coords

几何工具已迁移到 src.geo_utils (纯 Python, 无 scipy/shapely 依赖)。
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

import json
from collections import Counter

from src.geo_utils import (
    dist as _dist,
    polyline_length as _polyline_length,
    shoelace_area as _shoelace_area,
    polygon_centroid as _polygon_centroid,
    points_bounds as _points_bounds,
    convex_hull as _convex_hull,
    knn_concave_hull as _knn_concave_hull,
    line_segment_intersection as _line_segment_intersection,
    point_in_polygon as _point_in_polygon,
    merge_close_points as _merge_close_points,
    nearest_point_on_polyline as _nearest_point_on_polyline,
)

logger = logging.getLogger(__name__)

# ── 图框常见图层名 ──
_TITLE_BLOCK_LAYERS = {"border", "frame", "图框", "defpoints", "tk", "titleblock"}


# ═══════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class PolylineFeature:
    """线状特征 (道路边缘/边界线)。"""
    points: list[tuple[float, float]]
    closed: bool = False
    category: str = ""       # "road", "boundary", ...
    source_layer: str = ""
    length: float = 0.0
    centroid: tuple[float, float] = (0.0, 0.0)


@dataclass
class PointFeature:
    """点状特征 (出入口/排水出口)。"""
    position: tuple[float, float]
    feature_type: str = ""   # "entrance", "drainage_outlet"
    confidence: float = 0.5


@dataclass
class AreaFeature:
    """面状特征 (建筑轮廓/道路面/绿地)。"""
    points: list[tuple[float, float]]
    category: str = ""       # "building", "road", "greenery"
    area: float = 0.0
    centroid: tuple[float, float] = (0.0, 0.0)
    bounds: tuple[float, float, float, float] = (0, 0, 0, 0)


@dataclass
class CadSiteFeatures:
    """完整场地分析结果。"""
    boundary_polyline: list[tuple[float, float]] = field(default_factory=list)
    zone_polygons: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    road_edges: list[PolylineFeature] = field(default_factory=list)
    boundary_segments: list[PolylineFeature] = field(default_factory=list)
    entrances: list[PointFeature] = field(default_factory=list)
    drainage_outlets: list[PointFeature] = field(default_factory=list)
    building_footprints: list[AreaFeature] = field(default_factory=list)
    road_surfaces: list[AreaFeature] = field(default_factory=list)
    green_spaces: list[AreaFeature] = field(default_factory=list)
    drainage_direction: str = "SE"  # "NW->SE" 等
    cluster_bounds: tuple[float, float, float, float] | None = None  # 主聚类区域边界
    elevation_points: list[tuple[float, float, float]] = field(default_factory=list)
    # [(x, y, z), ...] 从 TEXT 实体提取的标高点
    computed_slope_pct: float | None = None      # 拟合坡度 (%)
    computed_slope_direction: str | None = None   # 拟合坡向 ("NW→SE" 等)
    computed_elev_range: tuple[float, float] | None = None  # (min_z, max_z)


# ═══════════════════════════════════════════════════════════════
# CadFeatureAnalyzer
# ═══════════════════════════════════════════════════════════════

class CadFeatureAnalyzer:
    """从 CadGeometry 提取场地特征。"""

    def __init__(self, cad_geometry: Any, spatial_layout: dict | None = None,
                 project_meta: dict | None = None):
        self._geom = cad_geometry
        self._spatial = spatial_layout or {}
        self._project_meta = project_meta or {}
        self._bounds = cad_geometry.bounds
        # 初始化为原始实体列表 (聚类过滤后会替换)
        self._buildings = cad_geometry.buildings
        self._roads = cad_geometry.roads
        self._boundaries = cad_geometry.boundaries
        self._greenery = cad_geometry.greenery
        self._entities = cad_geometry.entities

    def analyze(self) -> CadSiteFeatures:
        """执行完整场地分析。"""
        try:
            # Step 0: 诊断报告
            self._diagnose()

            # Step 1: 检测主图簇，过滤远处详图/图框实体
            self._filter_to_main_cluster()

            # Step 1.5: 几何特征分类 (补充图层名分类的不足)
            self._classify_by_geometry()

            features = CadSiteFeatures()
            features.cluster_bounds = self._bounds  # 聚类过滤后的边界

            features.boundary_polyline = self._extract_boundary()
            # 确保红线闭合: 如果首尾不连接, 追加首点
            if features.boundary_polyline and len(features.boundary_polyline) >= 3:
                first = features.boundary_polyline[0]
                last = features.boundary_polyline[-1]
                gap = math.hypot(first[0] - last[0], first[1] - last[1])
                if gap > 0.01:
                    features.boundary_polyline.append(first)
                    logger.debug(f"红线闭合修补: gap={gap:.2f}m, 追加首点")
            features.boundary_segments = self._extract_boundary_segments()
            features.road_edges = self._extract_road_edges()
            features.building_footprints = self._classify_areas("building", self._buildings)
            features.road_surfaces = self._classify_areas("road", self._roads)
            features.green_spaces = self._classify_areas("greenery", self._greenery)
            features.zone_polygons = self._compute_zone_polygons()
            features.drainage_direction = self._infer_drainage_direction()

            # Step 7: 标高提取 + 地形拟合
            features.elevation_points = self._extract_elevation_points()
            if features.elevation_points:
                slope_pct, direction, elev_range = self._compute_terrain(features.elevation_points)
                if slope_pct is not None:
                    features.computed_slope_pct = slope_pct
                    features.computed_slope_direction = direction
                    features.computed_elev_range = elev_range
                    if direction:
                        features.drainage_direction = direction

            features.entrances = self._detect_entrances(
                features.road_edges, features.boundary_polyline
            )
            features.drainage_outlets = self._detect_drainage_outlets(
                features.boundary_polyline, features.drainage_direction
            )

            # 优先用红线 bbox 作为 cluster_bounds (更精确)
            if features.boundary_polyline and len(features.boundary_polyline) >= 3:
                bpts = features.boundary_polyline
                bx = [p[0] for p in bpts]
                by = [p[1] for p in bpts]
                features.cluster_bounds = (min(bx), min(by), max(bx), max(by))

            logger.info(
                f"CAD 特征分析: boundary={len(features.boundary_polyline)}pts, "
                f"zones={list(features.zone_polygons.keys())}, "
                f"roads={len(features.road_edges)}, "
                f"entrances={len(features.entrances)}, "
                f"drains={len(features.drainage_outlets)}, "
                f"elev_pts={len(features.elevation_points)}, "
                f"cluster_bounds={features.cluster_bounds}"
            )
            return features
        except Exception as e:
            logger.warning(f"CAD 特征分析异常: {e}")
            return CadSiteFeatures()

    # ── 诊断 ──────────────────────────────────────────────────────

    def _diagnose(self):
        """输出 CAD 文件诊断报告，帮助理解 DXF 数据。"""
        entities = self._geom.entities
        if not entities:
            logger.info("=== CAD 诊断: 无实体 ===")
            return

        type_dist = Counter(e.entity_type for e in entities)
        cat_dist = Counter(e.category for e in entities)
        layer_dist = Counter(e.layer for e in entities)

        xs, ys = [], []
        for e in entities:
            for p in (e.points or []):
                xs.append(p[0])
                ys.append(p[1])

        closed_count = sum(1 for e in entities if e.closed and len(e.points or []) >= 3)

        text_samples = []
        for e in entities:
            if e.entity_type == "text" and e.text_content:
                text_samples.append(e.text_content[:50])
                if len(text_samples) >= 30:
                    break

        logger.info("=== CAD 诊断报告 ===")
        logger.info(f"总实体数: {len(entities)}")
        logger.info(f"实体类型分布: {dict(type_dist)}")
        logger.info(f"分类分布: {dict(cat_dist)}")
        logger.info(f"图层数: {len(layer_dist)}")
        # 只显示前 15 个高频图层
        top_layers = layer_dist.most_common(15)
        logger.info(f"主要图层: {dict(top_layers)}")
        if xs:
            logger.info(
                f"坐标范围: X[{min(xs):.1f}, {max(xs):.1f}], "
                f"Y[{min(ys):.1f}, {max(ys):.1f}], "
                f"跨度: {max(xs)-min(xs):.0f} x {max(ys)-min(ys):.0f}"
            )
        logger.info(f"闭合多边形数: {closed_count}")
        if text_samples:
            logger.info(f"文本样本(前{len(text_samples)}个): {text_samples[:10]}")

        # 保存诊断 JSON (静默失败)
        try:
            from pathlib import Path
            diag = {
                "total_entities": len(entities),
                "type_distribution": dict(type_dist),
                "category_distribution": dict(cat_dist),
                "layer_count": len(layer_dist),
                "top_layers": dict(top_layers),
                "x_range": [min(xs), max(xs)] if xs else None,
                "y_range": [min(ys), max(ys)] if ys else None,
                "span": [max(xs) - min(xs), max(ys) - min(ys)] if xs else None,
                "closed_polyline_count": closed_count,
                "text_samples": text_samples[:30],
                "all_layers": sorted(layer_dist.keys()),
            }
            diag_path = Path("data/output/cad_diagnosis.json")
            diag_path.parent.mkdir(parents=True, exist_ok=True)
            with open(diag_path, "w", encoding="utf-8") as f:
                json.dump(diag, f, ensure_ascii=False, indent=2)
            logger.info(f"诊断报告已保存: {diag_path}")
        except Exception as e:
            logger.debug(f"诊断报告保存失败 (非致命): {e}")

    # ── 几何特征分类 ────────────────────────────────────────────

    def _classify_by_geometry(self):
        """当图层名无法分类时，从几何特征推断实体类别。

        补充分类 'other' 类实体:
        - 闭合矩形, 面积 50-10000m², 顶点4-8个, 长宽比<5 → building
        - 长线段 (>20m), 直线度>0.7 → road (候选)
        - 面积特别大的闭合多边形 → boundary 候选
        """
        reclassified = 0
        other_entities = [e for e in self._entities if e.category == "other"]
        if not other_entities:
            return

        # 计算整体面积参考值
        overall_span = self._calc_entity_span()
        site_area_approx = overall_span[0] * overall_span[1] if all(s > 0 for s in overall_span) else 0

        for ent in other_entities:
            pts = ent.points or []
            if len(pts) < 2:
                continue

            new_cat = None
            dxf_color = (ent.properties or {}).get("dxf_color")

            if ent.closed and len(pts) >= 3:
                area = _shoelace_area(pts)
                bnd = _points_bounds(pts)
                w = bnd[2] - bnd[0]
                h = bnd[3] - bnd[1]
                aspect = max(w, h) / min(w, h) if min(w, h) > 0.1 else 999
                n_verts = len(pts)

                # 黄色闭合多边形 → 建筑 (CAD惯例: ACI 2 = yellow)
                if dxf_color == 2 and area > 10:
                    new_cat = "building"
                # 建筑: 闭合矩形, 面积适中, 顶点少, 长宽比小
                elif 100 < area < 15000 and n_verts <= 12 and aspect < 4:
                    new_cat = "building"
                # 道路面: 闭合, 面积适中, 长条形
                elif 50 < area < 20000 and aspect >= 3 and n_verts <= 20:
                    new_cat = "road"
                # 绿地: 闭合, 不规则, 面积适中
                elif 100 < area < 50000 and n_verts > 10:
                    new_cat = "greenery"
                # 边界候选: 面积特别大 (>= 50% 场地面积)
                elif site_area_approx > 0 and area > site_area_approx * 0.3:
                    new_cat = "boundary"

            elif not ent.closed and len(pts) >= 2:
                length = _polyline_length(pts)
                # 长线段: 道路候选
                if length > 30:
                    # 计算直线度 (端点距离 / 折线长度)
                    end_dist = _dist(pts[0], pts[-1])
                    straightness = end_dist / length if length > 0 else 0
                    if straightness > 0.6:
                        new_cat = "road"

            if new_cat is not None:
                ent.category = new_cat
                reclassified += 1
                # 同步到分类列表
                if new_cat == "building":
                    self._buildings.append(ent)
                elif new_cat == "road":
                    self._roads.append(ent)
                elif new_cat == "greenery":
                    self._greenery.append(ent)
                elif new_cat == "boundary":
                    self._boundaries.append(ent)

        if reclassified > 0:
            logger.info(
                f"几何分类: {reclassified}/{len(other_entities)} 'other' 实体被重新分类 "
                f"(buildings={len(self._buildings)}, roads={len(self._roads)}, "
                f"boundaries={len(self._boundaries)}, greenery={len(self._greenery)})"
            )

    # ── 离群值过滤 ────────────────────────────────────────────

    @staticmethod
    def _remove_coordinate_outliers(
        ent_centroids: list[tuple[float, float, Any]],
        all_x: list[float],
        all_y: list[float],
        mad_threshold: float = 6.0,
    ) -> tuple[list, list, list]:
        """用 MAD (Median Absolute Deviation) 剔除坐标离群值。

        DXF 文件常有极端坐标实体 (如 X=-40M 或 X=81M)，使得全域跨度 >100M，
        导致网格聚类的 cell_size 过大而完全失效。

        MAD 比 IQR 更鲁棒: median ± threshold * MAD。threshold=6 约等于 ±4σ。
        """
        import statistics

        n = len(all_x)
        if n < 20:
            return ent_centroids, all_x, all_y

        med_x = statistics.median(all_x)
        med_y = statistics.median(all_y)

        # MAD = median(|x_i - median(x)|)
        mad_x = statistics.median(abs(x - med_x) for x in all_x) or 1.0
        mad_y = statistics.median(abs(y - med_y) for y in all_y) or 1.0

        # 阈值: 至少 500m (避免对小图过度过滤)
        limit_x = max(mad_threshold * mad_x, 500.0)
        limit_y = max(mad_threshold * mad_y, 500.0)

        filtered = []
        fx, fy = [], []
        for cx, cy, ent in ent_centroids:
            if abs(cx - med_x) <= limit_x and abs(cy - med_y) <= limit_y:
                filtered.append((cx, cy, ent))
                fx.append(cx)
                fy.append(cy)

        removed = n - len(filtered)
        if removed > 0:
            span_before = f"{max(all_x)-min(all_x):.0f}x{max(all_y)-min(all_y):.0f}"
            span_after = f"{max(fx)-min(fx):.0f}x{max(fy)-min(fy):.0f}" if fx else "0x0"
            logger.info(
                f"坐标离群值过滤: 剔除 {removed}/{n} 实体, "
                f"跨度 {span_before} → {span_after} (MAD阈值={mad_threshold})"
            )

        return filtered, fx, fy

    # ── 空间聚类 (过滤多图纸空间) ────────────────────────────────

    def _filter_to_main_cluster(self):
        """DXF 常将主图+详图+图框放在不同坐标区域。
        用 2D 网格密度聚类 (BFS 连通分量)，选最像施工总平面图的密集区域。

        算法:
        1. 收集所有实体质心
        2. 将坐标空间划分为 NxN 网格 (自适应 cell_size)
        3. 统计每个 cell 的实体数
        4. BFS 找连通分量 (非空 cell 相邻则连通)
        5. 对每个连通分量评分 (类型丰富度/面积/HATCH/DIMENSION)
        6. 选最高分连通分量作为主图簇
        7. 在主图簇中检测并排除图框实体
        8. 过滤实体到主图簇 bbox
        """
        from collections import deque

        # 收集所有有几何的实体 (质心 + 引用)
        ent_centroids: list[tuple[float, float, Any]] = []
        for ent in self._geom.entities:
            pts = ent.points if ent.points else []
            if not pts:
                continue
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            ent_centroids.append((cx, cy, ent))

        if len(ent_centroids) < 10:
            return

        # ── 离群值过滤 (MAD): DXF 常有极端坐标实体 (-40M~81M) ──
        all_x = [c[0] for c in ent_centroids]
        all_y = [c[1] for c in ent_centroids]
        ent_centroids, all_x, all_y = self._remove_coordinate_outliers(
            ent_centroids, all_x, all_y
        )
        if len(ent_centroids) < 10:
            return

        # 全局 extent (离群值已剔除)
        gx0, gx1 = min(all_x), max(all_x)
        gy0, gy1 = min(all_y), max(all_y)
        total_w = gx1 - gx0
        total_h = gy1 - gy0

        if total_w < 1 or total_h < 1:
            return

        # 自适应 cell_size: 使较长边约 50~80 格
        cell_size = max(total_w, total_h) / 80.0
        if cell_size < 1.0:
            cell_size = 1.0
        nx = max(1, int(math.ceil(total_w / cell_size)))
        ny = max(1, int(math.ceil(total_h / cell_size)))

        # 映射: cell → 实体列表
        grid_entities: dict[tuple[int, int], list] = {}
        for cx, cy, ent in ent_centroids:
            col = min(int((cx - gx0) / cell_size), nx - 1)
            row = min(int((cy - gy0) / cell_size), ny - 1)
            grid_entities.setdefault((col, row), []).append(ent)

        grid_count = {k: len(v) for k, v in grid_entities.items()}

        if not grid_count:
            return

        # BFS 找连通分量 (8-邻域连通)
        visited: set[tuple[int, int]] = set()
        components: list[list[tuple[int, int]]] = []

        for cell in grid_count:
            if cell in visited:
                continue
            queue = deque([cell])
            visited.add(cell)
            component = [cell]
            while queue:
                c, r = queue.popleft()
                for dc in (-1, 0, 1):
                    for dr in (-1, 0, 1):
                        if dc == 0 and dr == 0:
                            continue
                        nb = (c + dc, r + dr)
                        if nb in grid_count and nb not in visited:
                            visited.add(nb)
                            queue.append(nb)
                            component.append(nb)
            components.append(component)

        if len(components) <= 1:
            return  # 只有一个连通分量

        total_count = len(ent_centroids)

        # ── 评分选择最佳聚类 (替代简单的实体数量选择) ──
        best_comp = self._score_and_select_cluster(
            components, grid_entities, grid_count, gx0, gy0, cell_size, total_count
        )

        best_count = sum(grid_count[c] for c in best_comp)
        if best_count >= total_count * 0.95:
            return  # 主聚类占 95%+, 无需过滤

        # 主聚类的 cell 范围 → 坐标 bbox
        cols = [c[0] for c in best_comp]
        rows = [c[1] for c in best_comp]
        x_min = gx0 + min(cols) * cell_size
        x_max = gx0 + (max(cols) + 1) * cell_size
        y_min = gy0 + min(rows) * cell_size
        y_max = gy0 + (max(rows) + 1) * cell_size

        # ── 图框检测: 在主图簇中标记并排除图框实体 ──
        cluster_entities = []
        for cell in best_comp:
            cluster_entities.extend(grid_entities.get(cell, []))
        content_entities, title_block = self._detect_title_block(cluster_entities)

        if title_block:
            logger.info(f"检测到图框: {len(title_block)} 实体已排除")
            # 用排除图框后的内容实体重新计算 bbox
            content_pts_x = []
            content_pts_y = []
            for ent in content_entities:
                for p in (ent.points or []):
                    content_pts_x.append(p[0])
                    content_pts_y.append(p[1])
            if content_pts_x:
                x_min, x_max = min(content_pts_x), max(content_pts_x)
                y_min, y_max = min(content_pts_y), max(content_pts_y)

        # 加 10% 余量
        dx = (x_max - x_min) * 0.1 or 100.0
        dy = (y_max - y_min) * 0.1 or 100.0
        bbox = (x_min - dx, y_min - dy, x_max + dx, y_max + dy)

        # 过滤实体到主聚类
        def _centroid_in_bbox(ent) -> bool:
            pts = ent.points if ent.points else []
            if not pts:
                return False
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            return bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]

        # 排除图框实体
        title_block_set = set(id(e) for e in title_block) if title_block else set()

        def _keep(ent) -> bool:
            return _centroid_in_bbox(ent) and id(ent) not in title_block_set

        orig_total = len(self._entities)
        self._buildings = [e for e in self._buildings if _keep(e)]
        self._roads = [e for e in self._roads if _keep(e)]
        self._boundaries = [e for e in self._boundaries if _keep(e)]
        self._greenery = [e for e in self._greenery if _keep(e)]
        self._entities = [e for e in self._entities if _keep(e)]
        self._bounds = bbox

        logger.info(
            f"CAD 2D聚类过滤: {len(self._entities)}/{orig_total} entities in main cluster "
            f"({len(components)} components found, best={best_count}/{total_count}), "
            f"bbox=({bbox[0]:.0f},{bbox[1]:.0f})-({bbox[2]:.0f},{bbox[3]:.0f}), "
            f"size={x_max-x_min:.0f}x{y_max-y_min:.0f}m, "
            f"cell_size={cell_size:.0f}m, grid={nx}x{ny}, "
            f"buildings={len(self._buildings)}, roads={len(self._roads)}, "
            f"boundaries={len(self._boundaries)}, greenery={len(self._greenery)}"
        )

    def _score_and_select_cluster(
        self,
        components: list[list[tuple[int, int]]],
        grid_entities: dict[tuple[int, int], list],
        grid_count: dict[tuple[int, int], int],
        gx0: float, gy0: float, cell_size: float,
        total_count: int,
    ) -> list[tuple[int, int]]:
        """对每个聚类簇评分，选择最像施工总平面图的那个。

        评分规则 (满分 100):
        - 实体类型丰富度 (同时有 line/polyline/text/circle 等): 0-30
        - 有建筑/道路分类实体 (专业图的标志): 0-20
        - 实体数量归一化: 0-20
        - 面积适中 (100-2000m 边长): 0-10
        - 分类多样性 (building+road+boundary+greenery): 0-20
        """
        max_count = max(sum(grid_count[c] for c in comp) for comp in components)
        scores = []

        for i, comp in enumerate(components):
            score = 0.0
            cluster_ents = []
            for cell in comp:
                cluster_ents.extend(grid_entities.get(cell, []))

            entity_types = Counter(e.entity_type for e in cluster_ents)
            categories = Counter(e.category for e in cluster_ents)
            count = len(cluster_ents)

            # 类型丰富度 (polyline/line/circle/arc/text/hatch)
            key_types = {"polyline", "line", "circle", "arc", "text"}
            type_coverage = len(set(entity_types.keys()) & key_types) / max(len(key_types), 1)
            score += type_coverage * 30

            # 分类多样性 (building + road + boundary + greenery)
            key_cats = {"building", "road", "boundary", "greenery"}
            cat_coverage = len(set(categories.keys()) & key_cats) / max(len(key_cats), 1)
            score += cat_coverage * 20

            # 有建筑或道路 (专业图标志)
            if categories.get("building", 0) > 0:
                score += 10
            if categories.get("road", 0) > 0:
                score += 10

            # 实体数量归一化
            score += (count / max_count) * 20 if max_count > 0 else 0

            # 面积合理性 (施工图通常 100m-2000m 边长)
            cols = [c[0] for c in comp]
            rows = [c[1] for c in comp]
            width = (max(cols) - min(cols) + 1) * cell_size
            height = (max(rows) - min(rows) + 1) * cell_size
            if 50 < width < 3000 and 50 < height < 3000:
                score += 10

            scores.append(score)
            logger.debug(
                f"簇 {i}: 评分={score:.1f}, 实体数={count}, "
                f"尺寸={width:.0f}x{height:.0f}m, "
                f"类型={dict(entity_types)}, 分类={dict(categories)}"
            )

        best_idx = max(range(len(scores)), key=lambda i: scores[i])
        logger.info(
            f"选择簇 {best_idx} (评分={scores[best_idx]:.1f}/{max(scores):.1f}, "
            f"共 {len(components)} 簇)"
        )
        return components[best_idx]

    @staticmethod
    def _detect_title_block(entities: list) -> tuple[list, list]:
        """检测图框实体并分离出来。

        策略1: 图层名匹配 (BORDER/FRAME/图框/DEFPOINTS/TK)
        策略2: 找面积最大的矩形 (长宽比 < 1.6, 包含 >80% 其他实体)
        """
        # 策略1: 图层名匹配
        tb_entities = []
        content_entities = []
        for e in entities:
            layer_upper = (e.layer or "").upper()
            if layer_upper in _TITLE_BLOCK_LAYERS or any(
                kw in layer_upper for kw in ("BORDER", "FRAME", "图框", "TITLEBLOCK")
            ):
                tb_entities.append(e)
            else:
                content_entities.append(e)

        if tb_entities:
            return content_entities, tb_entities

        # 策略2: 找面积最大的闭合矩形
        # (顶点4个, 长宽比 < 1.6, 面积是所有实体 bbox 面积的 0.8~1.5 倍)
        all_pts_x = []
        all_pts_y = []
        for e in entities:
            for p in (e.points or []):
                all_pts_x.append(p[0])
                all_pts_y.append(p[1])
        if not all_pts_x:
            return entities, []

        total_area = (max(all_pts_x) - min(all_pts_x)) * (max(all_pts_y) - min(all_pts_y))

        largest_frame = None
        largest_area = 0.0
        for e in entities:
            if not e.closed or not e.points or len(e.points) < 4 or len(e.points) > 6:
                continue
            area = _shoelace_area(e.points)
            if area < total_area * 0.7:  # 图框应接近全域面积
                continue
            # 检查近似矩形 (长宽比)
            bnd = _points_bounds(e.points)
            w = bnd[2] - bnd[0]
            h = bnd[3] - bnd[1]
            if w < 1 or h < 1:
                continue
            aspect = max(w, h) / min(w, h)
            if aspect < 2.0 and area > largest_area:
                largest_area = area
                largest_frame = e

        if largest_frame is not None:
            content = [e for e in entities if id(e) != id(largest_frame)]
            return content, [largest_frame]

        return entities, []

    # ── 边界提取 ──────────────────────────────────────────────

    def _extract_boundary(self) -> list[tuple[float, float]]:
        """提取项目红线 — 多级优先回退。

        Level 0: 用户在 project_meta 提供的 project_boundary (coordinates/bbox)
        Level 0.5: 扩展图层名搜索 (非矩形闭合多边形)
        Level 0.7: 颜色过滤 (DXF color=1 红色闭合多边形)
        Level 0.8: 开放折线端到端拼接 (如 P-LIMT 多段红线)
        Level 1: 最长闭合边界折线
        Level 1.5: 面积匹配搜索 (基于 land_area_hm2)
        Level 1.6: 最大非矩形闭合多边形
        Level 1.7: 矩形边界回退
        Level 2: 所有边界实体点集凸包
        Level 3: 分类实体凸包
        Level 4: 全部非文字实体凸包

        验证逻辑: 找到的边界 span 必须 >= 整体实体 span 的 10%，
        否则视为标记/符号而非真正红线，回退到凸包。
        """
        overall_span = self._calc_entity_span()

        # Level 0: 用户提供的项目边界坐标
        user_boundary = self._extract_user_boundary()
        if user_boundary and len(user_boundary) >= 3:
            logger.info(f"边界提取 Level 0: 用户提供坐标 ({len(user_boundary)} pts)")
            return user_boundary

        # Level 0.5: 扩展图层名搜索 (搜索全部实体, 不限 boundary 类别)
        # 图层名已经是强信号 (如 P-LIMT-BUID), 用面积阈值替代 span 验证
        # (span 验证对大坐标偏移的 DXF 无效, 因为 outlier 拉大 overall_span)
        layer_boundary = self._extract_boundary_by_layer()
        if layer_boundary and len(layer_boundary) >= 3:
            area = _shoelace_area(layer_boundary)
            if area >= 1000:  # 面积 >= 1000m² 即认为是真实边界, 非标记符号
                logger.info(f"边界提取 Level 0.5: 图层名匹配非矩形多边形 "
                            f"({len(layer_boundary)} pts, area={area:.0f}m²)")
                return layer_boundary

        # Level 0.7: 颜色过滤 (DXF color index 1 = 红色)
        color_boundary = self._extract_boundary_by_color()
        if color_boundary and len(color_boundary) >= 3:
            area = _shoelace_area(color_boundary)
            if area >= 1000:
                logger.info(f"边界提取 Level 0.7: 红色非矩形多边形 "
                            f"({len(color_boundary)} pts, area={area:.0f}m²)")
                return color_boundary

        # Level 0.8: 开放折线端到端拼接 (如 P-LIMT 图层多段红线)
        joined_boundary = self._extract_boundary_by_joining_open_polylines()
        if joined_boundary and len(joined_boundary) >= 3:
            if self._boundary_is_valid(joined_boundary, overall_span):
                if self._boundary_contains_most_entities(joined_boundary):
                    logger.info(f"边界提取 Level 0.8: 开放折线拼接闭合边界 ({len(joined_boundary)} pts)")
                    return joined_boundary

        # Level 1: 尝试最长闭合边界折线 (跳过矩形图框)
        candidates = []
        for ent in self._boundaries:
            if ent.closed and len(ent.points) >= 3:
                length = _polyline_length(ent.points)
                candidates.append((length, ent.points))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            # 优先选择非矩形的候选 (矩形多为图框)
            for length, pts in candidates:
                best_pts = list(pts)
                if self._is_near_rectangle(best_pts):
                    logger.debug(
                        f"边界提取 Level 1: 跳过矩形候选 "
                        f"({len(best_pts)} pts, length={length:.0f})"
                    )
                    continue
                if self._boundary_is_valid(best_pts, overall_span):
                    logger.info(
                        f"边界提取 Level 1: 最长非矩形闭合折线 "
                        f"({len(best_pts)} pts)"
                    )
                    return best_pts
            # 所有候选都是矩形 → 暂不返回, 让 Level 1.5 面积匹配优先

        # Level 1.5: 面积匹配搜索
        area_match = self._extract_boundary_by_area()
        if area_match and len(area_match) >= 3:
            logger.info(f"边界提取 Level 1.5: 面积匹配 ({len(area_match)} pts)")
            return area_match

        # Level 1.6: 所有闭合多边形中面积最大的 (忽略分类, 跳过矩形)
        largest = self._extract_largest_closed_polygon()
        if largest and self._boundary_is_valid(largest, overall_span):
            if not self._is_near_rectangle(largest):
                logger.info(f"边界提取 Level 1.6: 最大非矩形闭合多边形 ({len(largest)} pts)")
                return largest

        # Level 1.7: Level 1 的矩形候选 (优于凸包, 至少是闭合边界)
        if candidates:
            rect_pts = list(candidates[0][1])
            if self._boundary_is_valid(rect_pts, overall_span):
                logger.info(
                    f"边界提取 Level 1.7: 矩形边界回退 ({len(rect_pts)} pts)"
                )
                return rect_pts

        # Level 2: 回退: 所有边界实体点集凸包
        all_pts = []
        for ent in self._boundaries:
            all_pts.extend(ent.points)
        if len(all_pts) >= 3:
            hull = _convex_hull(all_pts)
            if self._boundary_is_valid(hull, overall_span):
                logger.info(f"边界提取 Level 2: 边界实体凸包 ({len(hull)} pts)")
                return hull

        # Level 3: 回退: 分类实体 (building/road/greenery/boundary) 凸包
        all_pts = []
        for ent in self._entities:
            if ent.category in ("building", "road", "greenery", "boundary"):
                all_pts.extend(ent.points)
        if len(all_pts) >= 3:
            hull = _convex_hull(all_pts)
            logger.info(f"边界提取 Level 3: 分类实体凸包 ({len(hull)} pts)")
            return hull

        # Level 4: 最终回退: 全部非文字实体凸包
        all_pts = []
        for ent in self._entities:
            if ent.category != "text":
                all_pts.extend(ent.points)
        if len(all_pts) >= 3:
            return _convex_hull(all_pts)

        return []

    def _extract_user_boundary(self) -> list[tuple[float, float]] | None:
        """从 project_meta.project_boundary 提取用户指定边界。"""
        pb = self._project_meta.get("project_boundary", {})
        if not pb or not isinstance(pb, dict):
            return None

        # 优先使用 coordinates (完整多边形)
        coords = pb.get("coordinates")
        if coords and isinstance(coords, list) and len(coords) >= 3:
            try:
                return [(float(p[0]), float(p[1])) for p in coords]
            except (TypeError, IndexError, ValueError):
                pass

        # 其次使用 bbox → 矩形边界
        bbox = pb.get("bbox")
        if bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            except (TypeError, ValueError):
                pass

        return None

    def _extract_boundary_by_layer(self) -> list[tuple[float, float]] | None:
        """Level 0.5: 在所有实体中搜索图层名包含红线/boundary等关键词的最大闭合非矩形多边形。"""
        BOUNDARY_LAYER_KEYWORDS = [
            "红线", "redline", "用地", "边界", "boundary", "bound",
            "scope", "范围", "site", "规划", "建设用地",
            "limt", "limit",  # P-LIMT, P-LIMT-BUID 等图层
        ]
        candidates = []
        for ent in self._entities:
            layer_lower = (ent.layer or "").lower()
            if not any(kw in layer_lower for kw in BOUNDARY_LAYER_KEYWORDS):
                continue
            if not ent.closed or len(ent.points) < 3:
                continue
            if self._is_near_rectangle(ent.points):
                continue  # 跳过矩形（可能是图框）
            area = _shoelace_area(ent.points)
            candidates.append((area, ent.points))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return list(candidates[0][1])
        return None

    def _extract_boundary_by_color(self) -> list[tuple[float, float]] | None:
        """Level 0.7: 在所有红色(color=1)闭合多边形中，选面积最大且非矩形的。"""
        candidates = []
        for ent in self._entities:
            dxf_color = (ent.properties or {}).get("dxf_color")
            if dxf_color != 1:  # DXF color 1 = red
                continue
            if not ent.closed or len(ent.points) < 3:
                continue
            if self._is_near_rectangle(ent.points):
                continue
            area = _shoelace_area(ent.points)
            candidates.append((area, ent.points))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return list(candidates[0][1])
        return None

    def _extract_boundary_by_joining_open_polylines(self) -> list[tuple[float, float]] | None:
        """Level 0.8: 将开放折线端到端拼接成闭合边界。

        许多 DXF 文件中项目红线存储为多段开放折线 (如 P-LIMT 图层),
        需要按端点匹配顺序拼接成闭合多边形。

        策略: 按图层分组尝试拼接, 避免跨图层噪声干扰。
        """
        BOUNDARY_LAYER_KEYWORDS = [
            "红线", "redline", "用地", "边界", "boundary", "bound",
            "scope", "范围", "site", "规划", "建设用地", "limt", "limit",
        ]

        # 按图层分组收集开放折线 (仅匹配边界类图层, 忽略通用图层 "0")
        layer_groups: dict[str, list[list[tuple[float, float]]]] = {}
        for ent in self._entities:
            if ent.closed or len(ent.points) < 2:
                continue
            layer = ent.layer or ""
            layer_lower = layer.lower()
            # 跳过通用图层 "0" (太多噪声短线)
            if layer_lower in ("0", ""):
                continue
            is_boundary_layer = any(kw in layer_lower for kw in BOUNDARY_LAYER_KEYWORDS)
            if not is_boundary_layer:
                continue
            # 优先要求: 红色 + 足够长 (>=3点)，或边界图层 + 足够长
            dxf_color = (ent.properties or {}).get("dxf_color")
            is_red = (dxf_color == 1)
            # 至少 3 个点才有意义, 除非是红色边界图层的 2 点段
            if len(ent.points) < 3 and not is_red:
                continue
            # 过滤掉子图层中的短线段 (如 P-LIMT-BUID 的 2pt 线)
            # 只保留纯边界图层或红色实体
            base_layer = layer_lower.split("-buid")[0].split("-elev")[0]
            key = base_layer if is_red else layer_lower
            layer_groups.setdefault(key, []).append(list(ent.points))

        if not layer_groups:
            return None

        overall_span = self._calc_entity_span()
        tol = max(max(overall_span) * 0.001, 1.0)

        # 对每个图层组尝试拼接
        best_chain = None
        for layer_key, segs in layer_groups.items():
            if len(segs) < 2:
                continue
            # 去重: 端点相同的段只保留一个 (保留更长的)
            deduped = self._dedup_segments(segs, tol)
            if len(deduped) < 2:
                continue
            chain = self._chain_polylines(deduped, tol)
            if chain is None or len(chain) < 6:
                continue
            if self._is_near_rectangle(chain):
                continue
            if best_chain is None or len(chain) > len(best_chain):
                best_chain = chain
                logger.debug(
                    f"开放折线拼接: layer_key={layer_key}, "
                    f"{len(chain)} pts (从 {len(deduped)} 段)"
                )

        return best_chain

    @staticmethod
    def _dedup_segments(
        segments: list[list[tuple[float, float]]], tol: float
    ) -> list[list[tuple[float, float]]]:
        """去除端点相同的重复折线段, 保留点数更多的。"""
        result: list[list[tuple[float, float]]] = []
        for seg in segments:
            s_start, s_end = seg[0], seg[-1]
            is_dup = False
            for i, existing in enumerate(result):
                e_start, e_end = existing[0], existing[-1]
                # 正向或反向端点匹配
                fwd = (math.hypot(s_start[0] - e_start[0], s_start[1] - e_start[1]) <= tol
                       and math.hypot(s_end[0] - e_end[0], s_end[1] - e_end[1]) <= tol)
                rev = (math.hypot(s_start[0] - e_end[0], s_start[1] - e_end[1]) <= tol
                       and math.hypot(s_end[0] - e_start[0], s_end[1] - e_start[1]) <= tol)
                if fwd or rev:
                    # 保留点数更多的
                    if len(seg) > len(existing):
                        result[i] = seg
                    is_dup = True
                    break
            if not is_dup:
                result.append(seg)
        return result

    @staticmethod
    def _chain_polylines(
        segments: list[list[tuple[float, float]]], tol: float
    ) -> list[tuple[float, float]] | None:
        """贪心端点匹配拼接折线段为闭合环。

        Args:
            segments: 开放折线列表
            tol: 端点匹配容差 (欧氏距离)

        Returns:
            拼接后的闭合多边形点列表, 或 None
        """
        if not segments:
            return None

        def pts_close(a, b):
            return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol

        # 复制一份，避免修改原数据
        remaining = [list(s) for s in segments]
        # 从最长段开始
        remaining.sort(key=len, reverse=True)

        chain = remaining.pop(0)  # 第一段作为起始

        max_iters = len(remaining) * 2 + 10  # 防止无限循环
        for _ in range(max_iters):
            if not remaining:
                break

            matched = False
            chain_start = chain[0]
            chain_end = chain[-1]

            for i, seg in enumerate(remaining):
                seg_start = seg[0]
                seg_end = seg[-1]

                if pts_close(chain_end, seg_start):
                    # chain_end → seg_start: 正向追加 (跳过首点避免重复)
                    chain.extend(seg[1:])
                    remaining.pop(i)
                    matched = True
                    break
                elif pts_close(chain_end, seg_end):
                    # chain_end → seg_end: 反向追加
                    chain.extend(reversed(seg[:-1]))
                    remaining.pop(i)
                    matched = True
                    break
                elif pts_close(chain_start, seg_end):
                    # seg_end → chain_start: 正向前插
                    chain = seg[:-1] + chain
                    remaining.pop(i)
                    matched = True
                    break
                elif pts_close(chain_start, seg_start):
                    # seg_start → chain_start: 反向前插
                    chain = list(reversed(seg[1:])) + chain
                    remaining.pop(i)
                    matched = True
                    break

            if not matched:
                break

        # 检查是否闭合
        if len(chain) >= 3 and pts_close(chain[0], chain[-1]):
            # 去掉尾部重复点
            if chain[0] == chain[-1] or pts_close(chain[0], chain[-1]):
                chain = chain[:-1]
            return chain

        return None

    def _boundary_contains_most_entities(self, boundary_pts, threshold=0.6) -> bool:
        """检查候选边界是否包含 >=threshold 比例的关键地物实体。

        仅统计 building/road/greenery/boundary 类别实体,
        忽略 other/text 等噪声类别 (这些实体常散布在红线之外)。
        """
        if len(boundary_pts) < 3:
            return False
        _KEY_CATEGORIES = {"building", "road", "greenery", "boundary"}
        total = 0
        inside = 0
        for ent in self._entities:
            if ent.category not in _KEY_CATEGORIES or not ent.points:
                continue
            total += 1
            cx = sum(p[0] for p in ent.points) / len(ent.points)
            cy = sum(p[1] for p in ent.points) / len(ent.points)
            if _point_in_polygon((cx, cy), boundary_pts):
                inside += 1
        return total > 0 and (inside / total) >= threshold

    def _extract_boundary_by_area(self) -> list[tuple[float, float]] | None:
        """遍历所有闭合多边形，找面积最接近 land_area_hm2 的作为项目红线。"""
        target_hm2 = self._project_meta.get("land_area_hm2", 0)
        if not target_hm2 or target_hm2 <= 0:
            return None

        target_m2 = target_hm2 * 10000  # hm2 → m2
        tolerance_pct = self._project_meta.get("project_boundary", {}).get(
            "area_tolerance_pct", 30) if isinstance(
            self._project_meta.get("project_boundary"), dict) else 30
        lo = target_m2 * (1 - tolerance_pct / 100.0)
        hi = target_m2 * (1 + tolerance_pct / 100.0)

        best_poly = None
        best_diff = float("inf")

        # 遍历所有实体 (不限 boundary 类别)
        for ent in self._entities:
            if not ent.closed or len(ent.points) < 3:
                continue
            area = _shoelace_area(ent.points)
            if lo <= area <= hi:
                diff = abs(area - target_m2)
                if diff < best_diff:
                    best_diff = diff
                    best_poly = list(ent.points)

        if best_poly:
            actual_area = _shoelace_area(best_poly)
            logger.info(
                f"面积匹配边界: target={target_m2:.0f}m², "
                f"found={actual_area:.0f}m², "
                f"diff={best_diff:.0f}m² ({best_diff/target_m2*100:.1f}%)"
            )
        return best_poly

    def _extract_largest_closed_polygon(self) -> list[tuple[float, float]] | None:
        """遍历所有实体，找面积最大的闭合多边形作为项目红线候选。"""
        best_poly = None
        best_area = 0.0
        for ent in self._entities:
            if not ent.closed or len(ent.points) < 3:
                continue
            area = _shoelace_area(ent.points)
            if area > best_area:
                best_area = area
                best_poly = list(ent.points)
        if best_poly:
            logger.debug(f"最大闭合多边形: area={best_area:.0f}m², points={len(best_poly)}")
        return best_poly

    def _calc_entity_span(self) -> tuple[float, float]:
        """计算所有分类实体的 X/Y span。"""
        xs, ys = [], []
        for ent in self._entities:
            if ent.category in ("building", "road", "greenery", "boundary"):
                for p in (ent.points or []):
                    xs.append(p[0])
                    ys.append(p[1])
        if not xs:
            return (0.0, 0.0)
        return (max(xs) - min(xs), max(ys) - min(ys))

    @staticmethod
    def _is_near_rectangle(
        pts: list[tuple[float, float]], angle_tol: float = 12.0
    ) -> bool:
        """检测多边形是否为近似矩形 (4-5个顶点, 角度接近90°)。

        图框/边界框通常是精确矩形, 而真正的项目红线通常有更多顶点
        或不规则角度。
        """
        # 去除首尾重复点
        unique = list(pts)
        if len(unique) >= 2 and (
            abs(unique[-1][0] - unique[0][0]) < 0.1
            and abs(unique[-1][1] - unique[0][1]) < 0.1
        ):
            unique = unique[:-1]

        # 只有 4 个唯一顶点才可能是矩形
        if len(unique) != 4:
            return False

        # 检查所有 4 个内角是否接近 90°
        import math
        for i in range(4):
            p0 = unique[(i - 1) % 4]
            p1 = unique[i]
            p2 = unique[(i + 1) % 4]
            v1 = (p0[0] - p1[0], p0[1] - p1[1])
            v2 = (p2[0] - p1[0], p2[1] - p1[1])
            dot = v1[0] * v2[0] + v1[1] * v2[1]
            mag1 = math.hypot(v1[0], v1[1])
            mag2 = math.hypot(v2[0], v2[1])
            if mag1 < 1e-6 or mag2 < 1e-6:
                return False
            cos_angle = max(-1.0, min(1.0, dot / (mag1 * mag2)))
            angle = math.degrees(math.acos(cos_angle))
            if abs(angle - 90.0) > angle_tol:
                return False

        return True

    def _boundary_is_valid(
        self, pts: list[tuple[float, float]], overall_span: tuple[float, float],
    ) -> bool:
        """边界是否足够大 (span >= 整体 span 的 10%)。"""
        if len(pts) < 3:
            return False
        bnd = _points_bounds(pts)
        bnd_dx = bnd[2] - bnd[0]
        bnd_dy = bnd[3] - bnd[1]
        min_span = min(overall_span) * 0.1 if min(overall_span) > 0 else 0
        return bnd_dx >= min_span and bnd_dy >= min_span

    def _extract_boundary_segments(self) -> list[PolylineFeature]:
        """提取所有边界类折线。"""
        results = []
        for ent in self._boundaries:
            if len(ent.points) >= 2:
                length = _polyline_length(ent.points)
                centroid = _polygon_centroid(ent.points) if ent.closed else (
                    sum(p[0] for p in ent.points) / len(ent.points),
                    sum(p[1] for p in ent.points) / len(ent.points),
                )
                results.append(PolylineFeature(
                    points=list(ent.points),
                    closed=ent.closed,
                    category="boundary",
                    source_layer=ent.layer,
                    length=length,
                    centroid=centroid,
                ))
        results.sort(key=lambda f: f.length, reverse=True)
        return results

    # ── 道路边缘提取 ──────────────────────────────────────────

    def _extract_road_edges(self) -> list[PolylineFeature]:
        """提取道路类折线，按长度排序。"""
        results = []
        for ent in self._roads:
            if len(ent.points) >= 2:
                length = _polyline_length(ent.points)
                centroid = (
                    sum(p[0] for p in ent.points) / len(ent.points),
                    sum(p[1] for p in ent.points) / len(ent.points),
                )
                results.append(PolylineFeature(
                    points=list(ent.points),
                    closed=ent.closed,
                    category="road",
                    source_layer=ent.layer,
                    length=length,
                    centroid=centroid,
                ))
        results.sort(key=lambda f: f.length, reverse=True)
        return results

    # ── 面状特征分类 ──────────────────────────────────────────

    def _classify_areas(self, category: str, entities: list) -> list[AreaFeature]:
        """将闭合折线转为 AreaFeature。"""
        results = []
        for ent in entities:
            if not ent.closed or len(ent.points) < 3:
                continue
            area = _shoelace_area(ent.points)
            dxf_color = (ent.properties or {}).get("dxf_color")
            # 黄色(ACI=2)是CAD建筑强信号, 门槛降至10m²; 其它建筑保持50m²过滤围墙
            if category == "building":
                min_area = 10.0 if dxf_color == 2 else 50.0
            else:
                min_area = 1.0
            if area < min_area:
                continue
            centroid = _polygon_centroid(ent.points)
            bounds = _points_bounds(ent.points)
            results.append(AreaFeature(
                points=list(ent.points),
                category=category,
                area=area,
                centroid=centroid,
                bounds=bounds,
            ))
        results.sort(key=lambda f: f.area, reverse=True)
        return results

    # ── 分区多边形推算 ─────────────────────────────────────────

    def _compute_zone_polygons(self) -> dict[str, list[tuple[float, float]]]:
        """各分类实体 → 分区多边形 (4 级策略)。

        映射:
          建(构)筑物区 ← building 实体
          道路广场区   ← road 实体
          绿化工程区   ← greenery 实体

        策略 1: DXF 闭合多边形轮廓合并 — 用实际闭合折线外轮廓
        策略 1.5: AreaFeature 推断 — 从 _classify_areas 产出的面状特征凸包
        策略 2: KNN 凹包 (k=5) — 比凸包更贴合实际轮廓
        策略 3: 凸包回退 — Graham scan (现有逻辑)
        """
        zone_map = {
            "建(构)筑物区": self._buildings,
            "道路广场区": self._roads,
            "绿化工程区": self._greenery,
        }
        # 预计算 AreaFeature (供策略 1.5 使用)
        area_features_map = {
            "建(构)筑物区": self._classify_areas("building", self._buildings),
            "道路广场区": self._classify_areas("road", self._roads),
            "绿化工程区": self._classify_areas("greenery", self._greenery),
        }
        result = {}
        for zone_name, entity_list in zone_map.items():
            # 策略 1: 合并闭合多边形外轮廓
            polygon = self._merge_polygon_outlines(entity_list)
            if polygon and len(polygon) >= 3:
                result[zone_name] = polygon
                continue

            # 策略 1.5: 从 AreaFeature 收集点做凸包 (当实体列表为空但有面状特征时)
            area_features = area_features_map.get(zone_name, [])
            if area_features:
                af_pts = []
                for af in area_features:
                    af_pts.extend(af.points)
                if len(af_pts) >= 3:
                    concave = _knn_concave_hull(af_pts, k=5)
                    if concave and len(concave) >= 3:
                        result[zone_name] = concave
                        continue
                    hull = _convex_hull(af_pts)
                    if len(hull) >= 3:
                        result[zone_name] = hull
                        continue

            # 策略 2 & 3: 收集所有点
            pts = []
            for ent in entity_list:
                pts.extend(ent.points)
            if len(pts) < 3:
                continue

            # 策略 2: KNN 凹包
            concave = _knn_concave_hull(pts, k=5)
            if concave and len(concave) >= 3:
                result[zone_name] = concave
                continue

            # 策略 3: 凸包回退
            hull = _convex_hull(pts)
            if len(hull) >= 3:
                result[zone_name] = hull

        return result

    @staticmethod
    def _merge_polygon_outlines(
        entities: list,
    ) -> list[tuple[float, float]] | None:
        """将多个闭合多边形的顶点汇聚后求凹包。

        仅使用闭合多边形 (closed=True, len>=3) 的顶点，
        这些顶点代表实际建筑/道路边界，比散点更精确。
        """
        outline_pts = []
        for ent in entities:
            if ent.closed and len(ent.points) >= 3:
                outline_pts.extend(ent.points)
        if len(outline_pts) < 6:
            return None
        # 用凹包包裹所有闭合多边形的顶点
        concave = _knn_concave_hull(outline_pts, k=5)
        if concave and len(concave) >= 3:
            return concave
        return None

    # ── 标高提取 + 地形拟合 ─────────────────────────────────────

    _ELEV_PATTERNS = [
        re.compile(r"[▽△∇][=:：]?\s*([+-]?\d+\.?\d*)"),        # ▽52.30
        re.compile(r"[Hh]\s*[=:：]\s*([+-]?\d+\.?\d*)"),        # H=52.30
        re.compile(r"标高[=:：]?\s*([+-]?\d+\.?\d*)"),           # 标高52.30
        re.compile(r"高程[=:：]?\s*([+-]?\d+\.?\d*)"),           # 高程42.0
        re.compile(r"EL\.?\s*([+-]?\d+\.?\d*)", re.IGNORECASE), # EL.52.30
        re.compile(r"[±+-]0\.00"),                               # ±0.00 (相对标高原点)
    ]

    def _extract_elevation_points(self) -> list[tuple[float, float, float]]:
        """从 TEXT 实体提取标高点 (x, y, z)。"""
        points = []
        for ent in self._entities:
            if ent.entity_type != "text" or not ent.text_content or not ent.points:
                continue
            text = ent.text_content.strip()
            x, y = ent.points[0]
            for pat in self._ELEV_PATTERNS:
                m = pat.search(text)
                if m:
                    try:
                        z = float(m.group(1)) if m.lastindex else 0.0
                        if -100 <= z <= 9999:
                            points.append((x, y, z))
                    except ValueError:
                        pass
                    break
        logger.info(f"标高提取: {len(points)} 点 from TEXT entities")
        return points

    def _compute_terrain(self, elev_pts: list[tuple[float, float, float]]):
        """最小二乘平面拟合 → 坡度 + 坡向。"""
        if len(elev_pts) < 3:
            return None, None, None

        cx = sum(p[0] for p in elev_pts) / len(elev_pts)
        cy = sum(p[1] for p in elev_pts) / len(elev_pts)

        sxx = syy = sxy = sxz = syz = 0.0
        for x, y, z in elev_pts:
            dx, dy = x - cx, y - cy
            sxx += dx * dx
            syy += dy * dy
            sxy += dx * dy
            sxz += dx * z
            syz += dy * z

        det = sxx * syy - sxy * sxy
        if abs(det) < 1e-12:
            return None, None, None

        a = (syy * sxz - sxy * syz) / det
        b = (sxx * syz - sxy * sxz) / det

        gradient = math.sqrt(a * a + b * b)
        slope_pct = gradient * 100

        angle_rad = math.atan2(-b, -a)
        angle_deg = math.degrees(angle_rad) % 360

        directions = [
            (0, "E"), (45, "NE"), (90, "N"), (135, "NW"),
            (180, "W"), (225, "SW"), (270, "S"), (315, "SE"), (360, "E")
        ]
        closest = min(directions, key=lambda d: abs(d[0] - angle_deg))
        opposite = {"N": "S", "S": "N", "E": "W", "W": "E",
                    "NE": "SW", "SW": "NE", "NW": "SE", "SE": "NW"}
        high_side = opposite.get(closest[1], "N")
        direction_str = f"{high_side}→{closest[1]}"

        zs = [p[2] for p in elev_pts]
        elev_range = (min(zs), max(zs))

        return slope_pct, direction_str, elev_range

    # ── 排水方向推断 ──────────────────────────────────────────

    def _infer_drainage_direction(self) -> str:
        """从空间布局或默认推断排水方向。"""
        spatial_dir = self._spatial.get("drainage_direction", "")
        if spatial_dir:
            return spatial_dir
        # 默认: 基于边界中心和 bounds 关系推断 SE
        return "SE"

    # ── 出入口检测 ────────────────────────────────────────────

    def _detect_entrances(
        self,
        road_edges: list[PolylineFeature],
        boundary: list[tuple[float, float]],
    ) -> list[PointFeature]:
        """道路折线 × 边界线段交叉 → 出入口。"""
        if not boundary or len(boundary) < 2 or not road_edges:
            return []

        intersections = []
        # 边界线段
        boundary_segs = []
        for i in range(len(boundary)):
            j = (i + 1) % len(boundary)
            boundary_segs.append((boundary[i], boundary[j]))

        for road in road_edges[:30]:  # 只检测前30条最长道路
            for k in range(len(road.points) - 1):
                p1, p2 = road.points[k], road.points[k + 1]
                for seg in boundary_segs:
                    pt = _line_segment_intersection(p1, p2, seg[0], seg[1])
                    if pt is not None:
                        intersections.append(pt)

        if not intersections:
            return []

        # 合并临近交叉点
        bounds_diag = math.hypot(
            self._bounds[2] - self._bounds[0],
            self._bounds[3] - self._bounds[1],
        )
        threshold = bounds_diag * 0.02
        merged = _merge_close_points(intersections, threshold)

        return [
            PointFeature(position=pt, feature_type="entrance", confidence=0.7)
            for pt in merged[:10]  # 最多 10 个
        ]

    # ── 排水出口检测 ──────────────────────────────────────────

    def _detect_drainage_outlets(
        self,
        boundary: list[tuple[float, float]],
        drainage_dir: str,
    ) -> list[PointFeature]:
        """边界上沿排水方向最远点 → 排水出口。"""
        if not boundary or len(boundary) < 3:
            return []

        # 排水方向 → 目标方位角
        dir_map = {
            "SE": (1, -1), "S": (0, -1), "SW": (-1, -1),
            "E": (1, 0), "W": (-1, 0),
            "NE": (1, 1), "N": (0, 1), "NW": (-1, 1),
        }
        # 提取方向简写
        dir_short = drainage_dir.upper().replace("->", "").strip()
        if "->" in drainage_dir.upper():
            dir_short = drainage_dir.upper().split("->")[-1].strip()
        dx, dy = dir_map.get(dir_short, (1, -1))

        # 沿排水方向对边界点排序 (点积投影)
        scored = [(p[0] * dx + p[1] * dy, p) for p in boundary]
        scored.sort(key=lambda x: x[0], reverse=True)

        # 取前 2-3 个最远点
        top_pts = [s[1] for s in scored[:3]]
        merged = _merge_close_points(top_pts, _dist(boundary[0], boundary[1]) * 0.5 if len(boundary) >= 2 else 10)

        return [
            PointFeature(position=pt, feature_type="drainage_outlet", confidence=0.6)
            for pt in merged[:3]
        ]


# ═══════════════════════════════════════════════════════════════
# MeasurePlacementResolver
# ═══════════════════════════════════════════════════════════════

# 措施关键词 → (放置策略, 目标特征列表)
_PLACEMENT_RULES: list[tuple[list[str], str, str]] = [
    # (keywords, strategy, feature_attr)
    (["排水沟", "截水沟"],         "follow_edge",     "road_edges"),
    (["临时排水"],                 "follow_boundary",  "boundary_segments"),
    (["施工围挡", "围挡"],         "follow_boundary",  "boundary_segments"),
    (["临时拦挡"],                 "follow_boundary",  "boundary_segments"),
    (["沉沙池"],                   "at_point",         "drainage_outlets"),
    (["车辆冲洗", "冲洗平台"],     "at_point",         "entrances"),
    (["临时沉沙"],                 "at_point",         "drainage_outlets"),
    (["综合绿化", "绿化", "草籽", "草皮", "植草", "液力喷播"],
                                   "fill_area",        "green_spaces"),
    (["透水", "铺装"],             "fill_area",        "road_surfaces"),
    (["表土剥离", "表土回覆"],     "fill_area",        "building_footprints"),
    (["密目", "安全网", "防尘网"], "fill_area",        "building_footprints"),
    (["彩条布"],                   "fill_area",        "building_footprints"),
    (["屋顶绿化"],                 "fill_area",        "building_footprints"),
    (["行道树", "乔木"],           "along_edge",       "road_edges"),
]


class MeasurePlacementResolver:
    """基于 CAD 特征解析措施放置位置。"""

    # 关键锚点属性及中文描述
    _CRITICAL_ANCHORS = [
        ("boundary_polyline", "红线边界"),
        ("road_edges", "道路边缘"),
        ("entrances", "出入口"),
        ("drainage_outlets", "排水口"),
        ("building_footprints", "建筑轮廓"),
    ]

    def __init__(self, site_features: CadSiteFeatures):
        self._features = site_features
        self._logged_anchors = False

    def _log_anchor_availability(self):
        """首次调用时记录锚点可用性并发出降级警告。"""
        if self._logged_anchors:
            return
        self._logged_anchors = True

        available, missing = [], []
        for attr, desc in self._CRITICAL_ANCHORS:
            val = getattr(self._features, attr, None)
            count = len(val) if val else 0
            if count > 0:
                available.append(f"{desc}({count})")
            else:
                missing.append(desc)

        extras = [
            ("road_surfaces", "道路面"),
            ("green_spaces", "绿地"),
            ("zone_polygons", "分区多边形"),
        ]
        for attr, desc in extras:
            val = getattr(self._features, attr, None)
            count = len(val) if val else 0
            if count > 0:
                available.append(f"{desc}({count})")

        logger.info("锚点可用: %s", ", ".join(available) if available else "无")
        if missing:
            logger.warning(
                "锚点缺失 (措施放置将降级为矩形回退): %s", ", ".join(missing)
            )

    def resolve(
        self,
        measure_name: str,
        zone_name: str = "",
        zone_bounds: tuple[float, float, float, float] | None = None,
    ) -> dict | None:
        """返回放置几何或 None (回退到现有逻辑)。

        Returns:
            {"polyline": [(x,y),...]} — 线状放置
            {"polygon": [(x,y),...]}  — 面状放置
            {"points": [(x,y),...]}   — 点状放置
            None — 无匹配, 回退
        """
        self._log_anchor_availability()

        rule = self._match_rule(measure_name)
        if rule is None:
            return None

        _, strategy, feature_attr = rule
        features = getattr(self._features, feature_attr, [])
        if not features:
            logger.debug("措施 '%s' 需要 %s 锚点但为空, 降级回退", measure_name, feature_attr)
            return None

        try:
            if strategy == "follow_edge":
                return self._resolve_follow_edge(features, zone_name, zone_bounds)
            elif strategy == "follow_boundary":
                return self._resolve_follow_boundary(zone_bounds)
            elif strategy == "at_point":
                return self._resolve_at_point(features, zone_bounds)
            elif strategy == "fill_area":
                return self._resolve_fill_area(features, zone_name, zone_bounds)
            elif strategy == "along_edge":
                return self._resolve_along_edge(features, zone_bounds)
        except Exception as e:
            logger.debug(f"Placement resolve failed for '{measure_name}': {e}")
        return None

    def _match_rule(self, measure_name: str) -> tuple | None:
        """关键词匹配放置规则。"""
        for keywords, strategy, feature_attr in _PLACEMENT_RULES:
            for kw in keywords:
                if kw in measure_name:
                    return (keywords, strategy, feature_attr)
        return None

    def _resolve_follow_edge(
        self,
        road_edges: list[PolylineFeature],
        zone_name: str,
        zone_bounds: tuple | None,
    ) -> dict | None:
        """线状措施沿道路边缘。选最近的道路线段。"""
        if not road_edges:
            return None

        # 如果有 zone_bounds，选与 zone 重叠的最长道路
        best = road_edges[0]
        if zone_bounds:
            x0, y0, x1, y1 = zone_bounds
            zcx, zcy = (x0 + x1) / 2, (y0 + y1) / 2
            scored = []
            for edge in road_edges[:20]:
                d = _dist(edge.centroid, (zcx, zcy))
                scored.append((d, edge))
            scored.sort(key=lambda x: x[0])
            if scored:
                best = scored[0][1]

        # 裁剪到 zone_bounds 附近
        pts = best.points
        if zone_bounds and len(pts) >= 2:
            pts = self._clip_to_bounds(pts, zone_bounds, margin=0.3)

        if len(pts) >= 2:
            return {"polyline": pts}
        return None

    def _resolve_follow_boundary(
        self, zone_bounds: tuple | None,
    ) -> dict | None:
        """线状措施沿边界线。"""
        boundary = self._features.boundary_polyline
        if not boundary or len(boundary) < 2:
            return None
        pts = list(boundary)
        if zone_bounds:
            pts = self._clip_to_bounds(pts, zone_bounds, margin=0.3)
        if len(pts) >= 2:
            return {"polyline": pts}
        return None

    def _resolve_at_point(
        self,
        point_features: list[PointFeature],
        zone_bounds: tuple | None,
    ) -> dict | None:
        """点状措施在特征点处。"""
        if not point_features:
            return None
        pts = [f.position for f in point_features]
        if zone_bounds:
            # 选离 zone 中心最近的点
            x0, y0, x1, y1 = zone_bounds
            zcx, zcy = (x0 + x1) / 2, (y0 + y1) / 2
            pts.sort(key=lambda p: _dist(p, (zcx, zcy)))
        return {"points": pts[:3]}

    def _resolve_fill_area(
        self,
        area_features: list[AreaFeature],
        zone_name: str,
        zone_bounds: tuple | None,
    ) -> dict | None:
        """面状措施填充区域。选与 zone 最相关的面。"""
        if not area_features:
            return None

        # 选离 zone 中心最近且面积最大的区域
        best = area_features[0]
        if zone_bounds:
            x0, y0, x1, y1 = zone_bounds
            zcx, zcy = (x0 + x1) / 2, (y0 + y1) / 2
            scored = []
            for af in area_features:
                d = _dist(af.centroid, (zcx, zcy))
                # 面积权重 (面积大的优先)
                score = d - math.log1p(af.area) * 10
                scored.append((score, af))
            scored.sort(key=lambda x: x[0])
            if scored:
                best = scored[0][1]

        return {"polygon": best.points}

    def _resolve_along_edge(
        self,
        road_edges: list[PolylineFeature],
        zone_bounds: tuple | None,
    ) -> dict | None:
        """沿道路边缘散点 (行道树等)。"""
        result = self._resolve_follow_edge(road_edges, "", zone_bounds)
        if result and "polyline" in result:
            pts = result["polyline"]
            total_len = _polyline_length(pts)
            if total_len < 1:
                return None
            # 每 15m 一个点
            spacing = max(15, total_len / 20)
            samples = []
            accum = 0.0
            samples.append(pts[0])
            for i in range(len(pts) - 1):
                seg_len = _dist(pts[i], pts[i + 1])
                accum += seg_len
                while accum >= spacing:
                    accum -= spacing
                    t = 1.0 - accum / seg_len if seg_len > 0 else 0.5
                    t = max(0.0, min(1.0, t))
                    sx = pts[i][0] + t * (pts[i + 1][0] - pts[i][0])
                    sy = pts[i][1] + t * (pts[i + 1][1] - pts[i][1])
                    samples.append((sx, sy))
            if samples:
                return {"points": samples}
        return None

    @staticmethod
    def _clip_to_bounds(
        pts: list[tuple[float, float]],
        bounds: tuple[float, float, float, float],
        margin: float = 0.2,
    ) -> list[tuple[float, float]]:
        """粗略裁剪折线到 bounds 附近 (保留 margin 范围内的点)。"""
        x0, y0, x1, y1 = bounds
        dx = (x1 - x0) * margin
        dy = (y1 - y0) * margin
        clipped = [
            p for p in pts
            if (x0 - dx) <= p[0] <= (x1 + dx) and (y0 - dy) <= p[1] <= (y1 + dy)
        ]
        return clipped if len(clipped) >= 2 else pts
