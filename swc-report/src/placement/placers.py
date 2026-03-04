"""几何生成器 — GeometryClipper (通用7策略) + 13个措施专用布置函数。

GeometryClipper 从 placement_engine.py 搬迁，保持行为一致。
专用布置函数在 Phase C 中添加。
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.geo_utils import (
    dist, polyline_length, shoelace_area, polygon_centroid, points_bounds,
    point_in_polygon, polygons_overlap,
    offset_polyline, scale_polygon, clip_polyline, clip_polygon,
    polygon_edges, longest_edge, edges_facing,
    sample_points_in_polygon, sample_along_polyline,
    nearest_point_on_polyline, polygon_subtract_obstacles,
    find_lowest_point, slope_direction_vector,
    convex_hull, buffer_polygon, line_segment_intersection,
)
from src.site_model import SiteModel, ZoneModel, EdgeFeature, PointOfInterest
from .types import MeasureType, Strategy, PlacementResult

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# GeometryClipper — 通用7策略 (从 placement_engine.py 搬迁)
# ═══════════════════════════════════════════════════════════════

class GeometryClipper:
    """按策略生成布置几何。"""

    def __init__(self, site_model: SiteModel):
        self._model = site_model

    def generate(self, strategy: Strategy, zone: ZoneModel,
                 measure_name: str = "", **kwargs) -> PlacementResult:
        """按策略生成几何。"""
        dispatch = {
            Strategy.EDGE_FOLLOW: self._edge_follow,
            Strategy.BOUNDARY_FOLLOW: self._boundary_follow,
            Strategy.AREA_FILL: self._area_fill,
            Strategy.AREA_COVER: self._area_cover,
            Strategy.POINT_AT: self._point_at,
            Strategy.POINT_ALONG: self._point_along,
            Strategy.OVERLAY: self._overlay,
        }
        handler = dispatch.get(strategy, self._area_fill)
        result = handler(zone, measure_name, **kwargs)
        result.strategy = strategy
        result.zone_id = zone.zone_id
        result.measure_name = measure_name
        return result

    def _get_terrain(self):
        """获取地形信息 (坡向向量 + 坡度 + 标高点)。"""
        terrain = self._model.terrain
        if terrain is None:
            return None, None, []
        vec = slope_direction_vector(terrain.slope_direction) if terrain.slope_direction else None
        return vec, terrain.avg_slope_pct, terrain.elevation_points

    def _filter_edges_inside_boundary(self, edges: List[EdgeFeature]) -> List[EdgeFeature]:
        """过滤只保留中点在项目红线内的边线。

        分区多边形常远大于红线 (凸包扩展), 导致外围道路被分配到分区。
        此过滤确保排水沟等措施只沿红线内的道路布置。
        """
        boundary = self._model.boundary
        if not boundary or not boundary.polyline or len(boundary.polyline) < 3:
            return edges
        bp = boundary.polyline
        result = []
        for edge in edges:
            if len(edge.polyline) < 2:
                continue
            mid = edge.polyline[len(edge.polyline) // 2]
            if point_in_polygon(mid, bp):
                result.append(edge)
        return result

    def _get_internal_edges_near_zone(self, zone: ZoneModel) -> List[EdgeFeature]:
        """获取红线内、离分区质心最近的道路边线。

        当分区自己的 edges 全在红线外时 (如绿化区凸包远超红线),
        搜索全局 global_edges 中红线内的道路, 按距分区质心距离排序。
        """
        boundary = self._model.boundary
        if not boundary or not boundary.polyline or len(boundary.polyline) < 3:
            return []
        bp = boundary.polyline
        cx, cy = zone.centroid

        internal = []
        for edge in self._model.global_edges:
            if edge.feature_type != "road_edge" or len(edge.polyline) < 2:
                continue
            mid = edge.polyline[len(edge.polyline) // 2]
            if point_in_polygon(mid, bp):
                d = dist(mid, (cx, cy))
                internal.append((d, edge))

        # 按距离排序, 取最近的 20 条
        internal.sort(key=lambda x: x[0])
        return [e for _, e in internal[:20]]

    def _find_edge_by_direction(self, zone: ZoneModel, target_vec: tuple) -> Optional[EdgeFeature]:
        """选与目标方向最对齐的边。优先选红线内的边。"""
        candidates = list(zone.edges) if zone.edges else []

        # 优先过滤到红线内的边
        internal = self._filter_edges_inside_boundary(candidates)
        if internal:
            candidates = internal
        else:
            # 分区自己没有红线内道路 → 搜索全局红线内道路
            nearby = self._get_internal_edges_near_zone(zone)
            if nearby:
                candidates = nearby

        # 也加入分区多边形边作为候选 (最后回退)
        if not candidates and len(zone.polygon) >= 3:
            for p1, p2 in polygon_edges(zone.polygon):
                edge_len = dist(p1, p2)
                if edge_len > 1.0:
                    candidates.append(EdgeFeature(
                        polyline=[p1, p2], feature_type="polygon_edge",
                        length_m=edge_len, source=None,
                    ))

        best_edge = None
        best_score = -1.0
        for edge in candidates:
            if len(edge.polyline) < 2:
                continue
            p0, p1 = edge.polyline[0], edge.polyline[-1]
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            end_dist = math.sqrt(dx * dx + dy * dy)
            if end_dist < 1e-6:
                continue
            cos_sim = abs(dx * target_vec[0] + dy * target_vec[1]) / end_dist
            # 直线度: 端点距离 / 折线总长, 排除环形车道 (直线度<0.3的几乎是闭环)
            straightness = end_dist / edge.length_m if edge.length_m > 0 else 0
            if straightness < 0.3:
                continue  # 跳过环形道路
            score = cos_sim * edge.length_m * straightness
            if score > best_score:
                best_score = score
                best_edge = edge

        return best_edge

    def _get_clip_bbox(self, zone: ZoneModel) -> Tuple[float, float, float, float]:
        """获取裁剪 bbox: 优先用 boundary bbox (红线内道路可能不在 zone.bbox 内)。"""
        boundary = self._model.boundary
        if boundary and boundary.bbox:
            # 取 zone.bbox 和 boundary.bbox 的并集
            zb = zone.bbox
            bb = boundary.bbox
            return (min(zb[0], bb[0]), min(zb[1], bb[1]),
                    max(zb[2], bb[2]), max(zb[3], bb[3]))
        return zone.bbox

    def _edge_follow(self, zone: ZoneModel, name: str, **kw) -> PlacementResult:
        """沿分区边线偏移布置 (排水沟/截水沟)。坡向感知。"""
        result = PlacementResult(measure_type=MeasureType.LINE)
        slope_vec, _, _ = self._get_terrain()

        # 决定偏好方向
        prefer_vec = None
        if slope_vec:
            if any(k in name for k in ["截水", "拦水"]):
                prefer_vec = (-slope_vec[1], slope_vec[0])
            elif any(k in name for k in ["排水", "急流"]):
                prefer_vec = slope_vec

        # 有偏好方向时: 选与偏好方向最对齐的边
        if prefer_vec:
            edge = self._find_edge_by_direction(zone, prefer_vec)
        else:
            edge = self._find_best_edge(zone, "road_edge")

        if edge and len(edge.polyline) >= 2:
            offset_pts = offset_polyline(edge.polyline, 2.0, side="left")
            if offset_pts and len(offset_pts) >= 2:
                clip_bbox = self._get_clip_bbox(zone)
                segments = clip_polyline(offset_pts, clip_bbox)
                if segments:
                    result.polyline = segments[0]
                    result.label_anchor = result.polyline[len(result.polyline) // 2]
                    return result

        # 回退: 沿分区最长边偏移
        if len(zone.polygon) >= 3:
            le = longest_edge(zone.polygon)
            pts = [le[0], le[1]]
            offset_pts = offset_polyline(pts, 3.0, side="left")
            if offset_pts and len(offset_pts) >= 2:
                result.polyline = offset_pts
                result.label_anchor = offset_pts[len(offset_pts) // 2]
                return result

        result.skipped = True
        result.skip_reason = "no suitable edge found"
        return result

    def _boundary_follow(self, zone: ZoneModel, name: str, **kw) -> PlacementResult:
        """沿项目边界内缩布置 (围挡/围墙)。"""
        result = PlacementResult(measure_type=MeasureType.LINE)

        boundary = self._model.boundary
        if boundary and len(boundary.polyline) >= 3:
            boundary_pts = boundary.polyline
            bx0, by0, bx1, by1 = zone.bbox
            margin_x = (bx1 - bx0) * 0.1
            margin_y = (by1 - by0) * 0.1
            expanded_bbox = (bx0 - margin_x, by0 - margin_y,
                            bx1 + margin_x, by1 + margin_y)
            segments = clip_polyline(boundary_pts + [boundary_pts[0]], expanded_bbox)
            if segments:
                offset_pts = offset_polyline(segments[0], 1.5, side="right")
                if offset_pts and len(offset_pts) >= 2:
                    result.polyline = offset_pts
                    result.label_anchor = offset_pts[len(offset_pts) // 2]
                    return result

        # 回退: 沿分区边界
        if len(zone.polygon) >= 3:
            inset = scale_polygon(zone.polygon, 0.95)
            if inset:
                result.polyline = inset + [inset[0]]  # 闭合
                result.label_anchor = polygon_centroid(inset)
                return result

        result.skipped = True
        result.skip_reason = "no boundary for follow"
        return result

    def _area_fill(self, zone: ZoneModel, name: str, **kw) -> PlacementResult:
        """缩进填充 (绿化)。"""
        result = PlacementResult(measure_type=MeasureType.AREA)

        if len(zone.polygon) < 3:
            result.skipped = True
            result.skip_reason = "zone has no polygon"
            return result

        obstacles = [obs.polygon for obs in zone.obstacles if len(obs.polygon) >= 3]
        if obstacles:
            filled = polygon_subtract_obstacles(zone.polygon, obstacles, 0.85)
        else:
            filled = scale_polygon(zone.polygon, 0.85)

        if filled and len(filled) >= 3:
            result.polygon = filled
            result.label_anchor = polygon_centroid(filled)
        else:
            result.skipped = True
            result.skip_reason = "area_fill produced empty polygon"
        return result

    def _area_cover(self, zone: ZoneModel, name: str, **kw) -> PlacementResult:
        """全覆盖分区多边形 (透水铺装/覆盖)。"""
        result = PlacementResult(measure_type=MeasureType.AREA)

        if len(zone.polygon) < 3:
            result.skipped = True
            result.skip_reason = "zone has no polygon"
            return result

        result.polygon = list(zone.polygon)
        result.label_anchor = zone.centroid
        return result

    def _point_at(self, zone: ZoneModel, name: str, **kw) -> PlacementResult:
        """在 POI 附近放置 (沉沙池/冲洗台)。低点感知。"""
        result = PlacementResult(measure_type=MeasureType.POINT)

        # 沉沙池/集水池: 优先选标高最低点
        if any(k in name for k in ["沉沙", "沉淀", "集水"]):
            _, _, elev_pts = self._get_terrain()
            if elev_pts:
                raw_pts = [(ep.position[0], ep.position[1], ep.elevation)
                           for ep in elev_pts]
                low_pt = find_lowest_point(raw_pts, within_bbox=zone.bbox)
                if low_pt:
                    result.points = [low_pt]
                    result.label_anchor = low_pt
                    return result

        # 查找合适的 POI
        target_types = []
        if any(kw_str in name for kw_str in ["冲洗", "洗车"]):
            target_types = ["entrance"]
        elif any(kw_str in name for kw_str in ["沉沙", "沉淀", "集水"]):
            target_types = ["drain_outlet"]

        candidates = []
        for poi in zone.pois:
            if not target_types or poi.poi_type in target_types:
                candidates.append(poi.position)

        if not candidates:
            for poi in self._model.global_pois:
                if not target_types or poi.poi_type in target_types:
                    d = dist(poi.position, zone.centroid)
                    zone_diag = dist((zone.bbox[0], zone.bbox[1]),
                                     (zone.bbox[2], zone.bbox[3]))
                    if d < zone_diag * 1.5:
                        candidates.append(poi.position)

        if candidates:
            candidates.sort(key=lambda p: dist(p, zone.centroid))
            result.points = candidates[:3]
            result.label_anchor = candidates[0]
        else:
            cx, cy = zone.centroid
            bw = zone.bbox[2] - zone.bbox[0]
            bh = zone.bbox[3] - zone.bbox[1]
            offset_x = bw * 0.2
            offset_y = bh * 0.2
            result.points = [(cx + offset_x, cy - offset_y)]
            result.label_anchor = result.points[0]

        return result

    def _point_along(self, zone: ZoneModel, name: str, **kw) -> PlacementResult:
        """沿线均匀分布 (监测点/行道树)。"""
        result = PlacementResult(measure_type=MeasureType.POINT)

        edge = self._find_best_edge(zone, "road_edge")
        if edge and len(edge.polyline) >= 2:
            spacing = 15.0
            if "监测" in name:
                spacing = 50.0
            samples = sample_along_polyline(edge.polyline, spacing)
            if samples:
                result.points = samples
                result.label_anchor = samples[len(samples) // 2]
                return result

        if len(zone.polygon) >= 3:
            le = longest_edge(zone.polygon)
            edge_pts = [le[0], le[1]]
            spacing = 15.0
            samples = sample_along_polyline(edge_pts, spacing)
            if samples:
                result.points = samples
                result.label_anchor = samples[len(samples) // 2]
                return result

        result.skipped = True
        result.skip_reason = "no edge for point_along"
        return result

    def _overlay(self, zone: ZoneModel, name: str, **kw) -> PlacementResult:
        """叠加在建筑轮廓上方 (屋顶绿化)。"""
        result = PlacementResult(measure_type=MeasureType.OVERLAY)

        buildings = [obs for obs in zone.obstacles if "building" in obs.label]
        if buildings:
            buildings.sort(key=lambda b: b.area_m2, reverse=True)
            result.polygon = list(buildings[0].polygon)
            result.label_anchor = polygon_centroid(buildings[0].polygon)
            return result

        if len(zone.polygon) >= 3:
            result.polygon = scale_polygon(zone.polygon, 0.5)
            result.label_anchor = zone.centroid
            return result

        result.skipped = True
        result.skip_reason = "no building for overlay"
        return result

    def _find_all_qualifying_edges(
        self, zone: ZoneModel, direction_vec: Optional[Tuple[float, float]] = None,
    ) -> List[EdgeFeature]:
        """收集红线内所有合格道路边线。

        过滤:
          - 中点在红线内
          - 直线度 >= 0.3 (排除环形车道)
          - 如有 direction_vec, 方向对齐度 > 0.3

        Returns:
            按长度降序排序的 EdgeFeature 列表, 上限 50 条
        """
        # 收集候选: 分区道路 + 全局红线内道路
        candidates = list(zone.edges) if zone.edges else []
        internal = self._filter_edges_inside_boundary(candidates)
        if not internal:
            internal = self._get_internal_edges_near_zone(zone)
        if internal:
            candidates = internal

        # 过滤直线度
        qualifying = []
        for edge in candidates:
            if len(edge.polyline) < 2:
                continue
            straightness = self._edge_straightness(edge)
            if straightness < 0.3:
                continue
            # 方向过滤
            if direction_vec:
                p0, p1 = edge.polyline[0], edge.polyline[-1]
                dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                end_dist = math.sqrt(dx * dx + dy * dy)
                if end_dist < 1e-6:
                    continue
                cos_sim = abs(dx * direction_vec[0] + dy * direction_vec[1]) / end_dist
                if cos_sim < 0.3:
                    continue
            qualifying.append(edge)

        qualifying.sort(key=lambda e: e.length_m, reverse=True)
        return qualifying[:50]

    def _filter_edges_away_from_buildings(
        self, edges: List[EdgeFeature], min_dist_m: float = 5.0,
    ) -> List[EdgeFeature]:
        """过滤掉中点离建筑太近的边线。"""
        buildings = [
            obs for z in self._model.zones.values()
            for obs in z.obstacles
            if "building" in obs.label and len(obs.polygon) >= 3
        ]
        if not buildings:
            return edges
        result = []
        for edge in edges:
            if len(edge.polyline) < 2:
                continue
            mid = edge.polyline[len(edge.polyline) // 2]
            too_close = False
            for bldg in buildings:
                bc = polygon_centroid(bldg.polygon)
                if dist(mid, bc) < min_dist_m:
                    too_close = True
                    break
            if not too_close:
                result.append(edge)
        return result if result else edges  # 全被过滤则返回原始

    def _find_entrances(self) -> List[dict]:
        """找出入口 = 红线边界与道路的交叉处, 最多2个。"""
        boundary = self._model.boundary
        if not boundary or not boundary.polyline or len(boundary.polyline) < 3:
            return []
        bp = boundary.polyline
        road_edges = [e for e in self._model.global_edges
                      if e.feature_type == "road_edge" and len(e.polyline) >= 2]

        raw_entrances = []
        for edge in road_edges:
            for i in range(len(edge.polyline) - 1):
                for j in range(len(bp)):
                    inter = line_segment_intersection(
                        edge.polyline[i], edge.polyline[i + 1],
                        bp[j], bp[(j + 1) % len(bp)],
                    )
                    if inter:
                        # 计算道路方向
                        dx = edge.polyline[i + 1][0] - edge.polyline[i][0]
                        dy = edge.polyline[i + 1][1] - edge.polyline[i][1]
                        d = math.hypot(dx, dy)
                        road_dir = (dx / d, dy / d) if d > 1e-6 else (1, 0)
                        raw_entrances.append({
                            "position": inter,
                            "road_dir": road_dir,
                        })

        if not raw_entrances:
            # 回退: 使用 POI 中的 entrance
            for poi in self._model.global_pois:
                if poi.poi_type == "entrance":
                    raw_entrances.append({
                        "position": poi.position,
                        "road_dir": (1, 0),
                    })

        # 去重 (距离 < 20m 合并)
        merged = []
        for ent in raw_entrances:
            found = False
            for m in merged:
                if dist(ent["position"], m["position"]) < 20.0:
                    found = True
                    break
            if not found:
                merged.append(ent)

        return merged[:2]

    @staticmethod
    def _edge_straightness(edge: EdgeFeature) -> float:
        """计算边线直线度: 端点距离 / 折线总长。1.0=完全直线, 接近0=环形。"""
        if len(edge.polyline) < 2 or edge.length_m <= 0:
            return 0.0
        p0, p1 = edge.polyline[0], edge.polyline[-1]
        end_dist = dist(p0, p1)
        return end_dist / edge.length_m

    def _find_best_edge(self, zone: ZoneModel, feature_type: str) -> Optional[EdgeFeature]:
        """找分区内最匹配的边线。优先选红线内的直线型边。"""
        # 先过滤到红线内
        internal = self._filter_edges_inside_boundary(zone.edges)
        if not internal:
            # 分区自己没有红线内道路 → 搜索全局红线内道路
            internal = self._get_internal_edges_near_zone(zone)
        pool = internal if internal else list(zone.edges)

        # 过滤掉环形道路 (直线度 < 0.3)
        linear = [e for e in pool if self._edge_straightness(e) >= 0.3]
        if linear:
            pool = linear

        matching = [e for e in pool if e.feature_type == feature_type]
        if matching:
            matching.sort(key=lambda e: e.length_m, reverse=True)
            return matching[0]

        if pool:
            return max(pool, key=lambda e: e.length_m)

        return None


# ═══════════════════════════════════════════════════════════════
# 13个措施专用布置函数 (Phase C)
# ═══════════════════════════════════════════════════════════════

# 类型签名: (clipper, zone, name, hydro_adapter, **kw) → PlacementResult
PlacerFunc = Callable[..., PlacementResult]


def place_drainage_ditch(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """排水沟: 沿所有道路全长铺设 (多段线)。"""
    result = PlacementResult(measure_type=MeasureType.LINE)
    slope_vec, _, _ = clipper._get_terrain()

    # 水文感知
    flow_dir = None
    ditch_info = None
    if hydro_adapter:
        flow_dir = hydro_adapter.get_flow_direction_for_zone(zone)
        ditch_info = hydro_adapter.estimate_ditch_size(zone)

    prefer_vec = flow_dir or slope_vec

    # 获取所有合格道路边线
    all_edges = clipper._find_all_qualifying_edges(zone, prefer_vec)
    all_edges = clipper._filter_edges_away_from_buildings(all_edges)

    offset_dist = 2.0
    if ditch_info:
        offset_dist = ditch_info.get("width", 0.4) / 2 + 1.0

    clip_bbox = clipper._get_clip_bbox(zone)
    all_polylines = []

    for edge in all_edges:
        if len(edge.polyline) < 2:
            continue
        offset_pts = offset_polyline(edge.polyline, offset_dist, side="left")
        if offset_pts and len(offset_pts) >= 2:
            segments = clip_polyline(offset_pts, clip_bbox)
            for seg in (segments or []):
                if len(seg) >= 2:
                    all_polylines.append(seg)

    if all_polylines:
        # 最长段作为主 polyline (向后兼容)
        longest = max(all_polylines, key=lambda s: polyline_length(s))
        result.polyline = longest
        result.polylines = all_polylines
        result.label_anchor = longest[len(longest) // 2]
        if ditch_info:
            result.hydro_info = ditch_info
        return result

    # 回退: 单条边
    edge = clipper._find_edge_by_direction(zone, prefer_vec) if prefer_vec else clipper._find_best_edge(zone, "road_edge")
    if edge and len(edge.polyline) >= 2:
        offset_pts = offset_polyline(edge.polyline, offset_dist, side="left")
        if offset_pts and len(offset_pts) >= 2:
            segments = clip_polyline(offset_pts, clip_bbox)
            if segments:
                result.polyline = segments[0]
                result.label_anchor = result.polyline[len(result.polyline) // 2]
                if ditch_info:
                    result.hydro_info = ditch_info
                return result

    # 最终回退
    if len(zone.polygon) >= 3:
        le = longest_edge(zone.polygon)
        pts = [le[0], le[1]]
        offset_pts = offset_polyline(pts, 3.0, side="left")
        if offset_pts and len(offset_pts) >= 2:
            result.polyline = offset_pts
            result.label_anchor = offset_pts[len(offset_pts) // 2]
            if ditch_info:
                result.hydro_info = ditch_info
            return result

    result.skipped = True
    result.skip_reason = "no suitable edge for drainage ditch"
    return result


def place_intercept_ditch(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """截水沟: 垂直于坡向, 沿所有合格道路全长铺设 (多段线)。"""
    result = PlacementResult(measure_type=MeasureType.LINE)
    slope_vec, _, _ = clipper._get_terrain()

    flow_dir = None
    ditch_info = None
    if hydro_adapter:
        flow_dir = hydro_adapter.get_flow_direction_for_zone(zone)
        ditch_info = hydro_adapter.estimate_ditch_size(zone)

    base_vec = flow_dir or slope_vec
    if base_vec:
        prefer_vec = (-base_vec[1], base_vec[0])
    else:
        prefer_vec = None

    # 获取所有合格道路边线
    all_edges = clipper._find_all_qualifying_edges(zone, prefer_vec)
    all_edges = clipper._filter_edges_away_from_buildings(all_edges)

    offset_dist = 2.0
    if ditch_info:
        offset_dist = ditch_info.get("width", 0.4) / 2 + 1.0

    clip_bbox = clipper._get_clip_bbox(zone)
    all_polylines = []

    for edge in all_edges:
        if len(edge.polyline) < 2:
            continue
        side = "left"
        if base_vec:
            mid = edge.polyline[len(edge.polyline) // 2]
            cx, cy = zone.centroid
            dot = (mid[0] - cx) * base_vec[0] + (mid[1] - cy) * base_vec[1]
            if dot < 0:
                side = "right"
        offset_pts = offset_polyline(edge.polyline, offset_dist, side=side)
        if offset_pts and len(offset_pts) >= 2:
            segments = clip_polyline(offset_pts, clip_bbox)
            for seg in (segments or []):
                if len(seg) >= 2:
                    all_polylines.append(seg)

    if all_polylines:
        longest = max(all_polylines, key=lambda s: polyline_length(s))
        result.polyline = longest
        result.polylines = all_polylines
        result.label_anchor = longest[len(longest) // 2]
        if ditch_info:
            result.hydro_info = ditch_info
        return result

    # 回退: 单条边
    edge = clipper._find_edge_by_direction(zone, prefer_vec) if prefer_vec else clipper._find_best_edge(zone, "road_edge")
    if edge and len(edge.polyline) >= 2:
        side = "left"
        if base_vec:
            mid = edge.polyline[len(edge.polyline) // 2]
            cx, cy = zone.centroid
            dot = (mid[0] - cx) * base_vec[0] + (mid[1] - cy) * base_vec[1]
            if dot < 0:
                side = "right"
        offset_pts = offset_polyline(edge.polyline, offset_dist, side=side)
        if offset_pts and len(offset_pts) >= 2:
            segments = clip_polyline(offset_pts, clip_bbox)
            if segments:
                result.polyline = segments[0]
                result.label_anchor = result.polyline[len(result.polyline) // 2]
                if ditch_info:
                    result.hydro_info = ditch_info
                return result

    # 最终回退
    if len(zone.polygon) >= 3:
        le = longest_edge(zone.polygon)
        pts = [le[0], le[1]]
        offset_pts = offset_polyline(pts, 3.0, side="left")
        if offset_pts and len(offset_pts) >= 2:
            result.polyline = offset_pts
            result.label_anchor = offset_pts[len(offset_pts) // 2]
            if ditch_info:
                result.hydro_info = ditch_info
            return result

    result.skipped = True
    result.skip_reason = "no suitable edge for intercept ditch"
    return result


def place_temp_drainage(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """临时排水沟: 区域边界内缩 + 最低点断开 (留排水口)。"""
    result = PlacementResult(measure_type=MeasureType.LINE)

    if len(zone.polygon) < 3:
        result.skipped = True
        result.skip_reason = "zone has no polygon"
        return result

    # 内缩边界形成临时排水沟
    inset = scale_polygon(zone.polygon, 0.92)
    if not inset or len(inset) < 3:
        result.skipped = True
        result.skip_reason = "inset polygon too small"
        return result

    # 找最低点位置(如果有水文数据)，在该位置断开留出口
    low_pt = None
    if hydro_adapter:
        low_pt = hydro_adapter.get_lowest_point_in_zone(zone)

    polyline = inset + [inset[0]]  # 闭合

    if low_pt:
        # 找最近段断开 (留出3m缺口)
        best_idx = 0
        best_d = float("inf")
        for i, pt in enumerate(polyline):
            d = dist(pt, low_pt)
            if d < best_d:
                best_d = d
                best_idx = i
        # 移除最近点附近的点 (简化断开)
        if len(polyline) > 4:
            remove_start = max(0, best_idx - 1)
            remove_end = min(len(polyline), best_idx + 2)
            polyline = polyline[:remove_start] + polyline[remove_end:]

    if len(polyline) >= 2:
        result.polyline = polyline
        result.label_anchor = polygon_centroid(inset)
    else:
        result.skipped = True
        result.skip_reason = "temp drainage polyline too short"
    return result


def place_construction_fence(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """施工围挡: 沿红线完整一圈, 出入口处断开8m。"""
    result = PlacementResult(measure_type=MeasureType.LINE)

    # 优先用项目红线边界
    boundary = clipper._model.boundary
    use_poly = None
    if boundary and len(boundary.polyline) >= 3:
        use_poly = boundary.polyline
    elif len(zone.polygon) >= 3:
        use_poly = zone.polygon

    if not use_poly or len(use_poly) < 3:
        result.skipped = True
        result.skip_reason = "no boundary for fence"
        return result

    # 内缩 0.3m (法向内缩)
    fence_poly = buffer_polygon(use_poly, -0.3)
    if not fence_poly or len(fence_poly) < 3:
        fence_poly = scale_polygon(use_poly, 0.99)
    if not fence_poly or len(fence_poly) < 3:
        fence_poly = use_poly

    # 找出入口
    entrances = clipper._find_entrances()

    if not entrances:
        # 无出入口: 完整闭合一圈
        polyline = list(fence_poly) + [fence_poly[0]]
        result.polyline = polyline
        result.polylines = [polyline]
        result.label_anchor = polygon_centroid(use_poly)
        return result

    # 在出入口处断开 → 多段线
    segments = _split_polygon_at_entrances(fence_poly, entrances, gate_width=8.0)

    if segments:
        longest = max(segments, key=lambda s: polyline_length(s))
        result.polyline = longest
        result.polylines = segments
        result.label_anchor = polygon_centroid(use_poly)
    else:
        polyline = list(fence_poly) + [fence_poly[0]]
        result.polyline = polyline
        result.polylines = [polyline]
        result.label_anchor = polygon_centroid(use_poly)
    return result


def _split_polygon_at_entrances(
    polygon: List[Tuple[float, float]],
    entrances: List[dict],
    gate_width: float = 8.0,
) -> List[List[Tuple[float, float]]]:
    """在出入口处将闭合多边形断开为多段线。"""
    if not entrances:
        return [list(polygon) + [polygon[0]]]

    n = len(polygon)
    # 收集所有需要断开的索引位置和对应的多边形弧长位置
    ring = list(polygon) + [polygon[0]]

    # 计算每个顶点沿环的累计距离
    cum_dist = [0.0]
    for i in range(len(ring) - 1):
        cum_dist.append(cum_dist[-1] + dist(ring[i], ring[i + 1]))
    total_len = cum_dist[-1]

    if total_len < 1e-6:
        return [ring]

    # 找每个出入口在环上最近的弧长位置
    cut_positions = []  # (弧长, 半宽)
    for ent in entrances:
        pos = ent["position"]
        best_d = float("inf")
        best_arc = 0.0
        for i in range(len(ring) - 1):
            d = dist(pos, ring[i])
            if d < best_d:
                best_d = d
                best_arc = cum_dist[i]
        half = gate_width / 2.0
        cut_positions.append((best_arc - half, best_arc + half))

    # 按弧长排序
    cut_positions.sort()

    # 生成线段: 在 cuts 之间的部分
    segments = []
    current_start = cut_positions[-1][1]  # 从最后一个出入口之后开始

    for cut_start, cut_end in cut_positions:
        # 提取从 current_start 到 cut_start 的段
        seg = _extract_ring_segment(ring, cum_dist, total_len, current_start, cut_start)
        if seg and len(seg) >= 2:
            segments.append(seg)
        current_start = cut_end

    return segments if segments else [ring]


def _extract_ring_segment(
    ring: List[Tuple[float, float]],
    cum_dist: List[float],
    total_len: float,
    start_arc: float,
    end_arc: float,
) -> List[Tuple[float, float]]:
    """从环上提取 [start_arc, end_arc] 的段。支持绕环。"""
    # 标准化到 [0, total_len)
    start_arc = start_arc % total_len
    end_arc = end_arc % total_len

    if end_arc <= start_arc:
        # 绕环: 提取两段拼接
        seg1 = _extract_linear_segment(ring, cum_dist, start_arc, total_len)
        seg2 = _extract_linear_segment(ring, cum_dist, 0.0, end_arc)
        return seg1 + seg2[1:] if seg1 and seg2 else (seg1 or seg2)

    return _extract_linear_segment(ring, cum_dist, start_arc, end_arc)


def _extract_linear_segment(
    ring: List[Tuple[float, float]],
    cum_dist: List[float],
    start_arc: float,
    end_arc: float,
) -> List[Tuple[float, float]]:
    """从环上线性提取 [start_arc, end_arc] 的顶点。"""
    result = []
    for i in range(len(ring)):
        d = cum_dist[i]
        if d >= start_arc and d <= end_arc:
            result.append(ring[i])
    return result


def place_sedimentation_basin(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """沉砂池: 最低点 + 排水沟末端 + 汇水面积→尺寸。"""
    result = PlacementResult(measure_type=MeasureType.POINT)

    # 水文感知: 尺寸和最低点
    basin_info = None
    low_pt = None
    if hydro_adapter:
        basin_info = hydro_adapter.estimate_basin_size(zone)
        low_pt = hydro_adapter.get_lowest_point_in_zone(zone)

    if low_pt:
        result.points = [low_pt]
        result.label_anchor = low_pt
        if basin_info:
            result.hydro_info = basin_info
        return result

    # 回退: 标高最低点
    _, _, elev_pts = clipper._get_terrain()
    if elev_pts:
        raw_pts = [(ep.position[0], ep.position[1], ep.elevation)
                   for ep in elev_pts]
        lowest = find_lowest_point(raw_pts, within_bbox=zone.bbox)
        if lowest:
            result.points = [lowest]
            result.label_anchor = lowest
            if basin_info:
                result.hydro_info = basin_info
            return result

    # 回退: 排水口 POI
    drain_pois = [poi for poi in zone.pois if poi.poi_type == "drain_outlet"]
    if not drain_pois:
        drain_pois = [poi for poi in clipper._model.global_pois
                      if poi.poi_type == "drain_outlet"]
    if drain_pois:
        drain_pois.sort(key=lambda p: dist(p.position, zone.centroid))
        result.points = [drain_pois[0].position]
        result.label_anchor = drain_pois[0].position
        if basin_info:
            result.hydro_info = basin_info
        return result

    # 最终回退: 出入口旁5m 或 分区下游角
    entrances = clipper._find_entrances()
    if entrances:
        ent = entrances[0]
        ex, ey = ent["position"]
        # 垂直于道路方向偏移5m
        rd = ent["road_dir"]
        perp_x, perp_y = -rd[1], rd[0]
        basin_pt = (ex + perp_x * 5.0, ey + perp_y * 5.0)
        result.points = [basin_pt]
        result.label_anchor = basin_pt
        if basin_info:
            result.hydro_info = basin_info
        return result

    cx, cy = zone.centroid
    bw = zone.bbox[2] - zone.bbox[0]
    bh = zone.bbox[3] - zone.bbox[1]
    result.points = [(cx + bw * 0.3, cy - bh * 0.3)]
    result.label_anchor = result.points[0]
    if basin_info:
        result.hydro_info = basin_info
    return result


def place_vehicle_wash(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """洗车平台: 出入口内侧12m + 道路方向对齐。"""
    result = PlacementResult(measure_type=MeasureType.POINT)

    # 优先: 红线-道路交叉点找出入口
    geo_entrances = clipper._find_entrances()
    if geo_entrances:
        ent = geo_entrances[0]
        ex, ey = ent["position"]
        cx, cy = zone.centroid
        dx = cx - ex
        dy = cy - ey
        d = math.hypot(dx, dy)
        if d > 1e-6:
            nx, ny = dx / d, dy / d
            wash_pt = (ex + nx * 12.0, ey + ny * 12.0)
        else:
            wash_pt = (ex + 12.0, ey)
        result.points = [wash_pt]
        result.label_anchor = wash_pt
        return result

    # 回退: POI 出入口
    poi_entrances = [poi for poi in zone.pois if poi.poi_type == "entrance"]
    if not poi_entrances:
        poi_entrances = [poi for poi in clipper._model.global_pois
                         if poi.poi_type == "entrance"]
        zone_diag = dist((zone.bbox[0], zone.bbox[1]),
                         (zone.bbox[2], zone.bbox[3]))
        poi_entrances = [e for e in poi_entrances
                         if dist(e.position, zone.centroid) < zone_diag * 1.5]

    if poi_entrances:
        poi_entrances.sort(key=lambda p: dist(p.position, zone.centroid))
        ent = poi_entrances[0]
        ex, ey = ent.position
        cx, cy = zone.centroid
        dx = cx - ex
        dy = cy - ey
        d = math.hypot(dx, dy)
        if d > 1e-6:
            nx, ny = dx / d, dy / d
            wash_pt = (ex + nx * 12.0, ey + ny * 12.0)
        else:
            wash_pt = (ex + 12.0, ey)
        result.points = [wash_pt]
        result.label_anchor = wash_pt
        return result

    # 最终回退: 分区边缘偏内12m
    cx, cy = zone.centroid
    bw = zone.bbox[2] - zone.bbox[0]
    result.points = [(zone.bbox[0] + 12.0, cy)]
    result.label_anchor = result.points[0]
    return result


def place_monitoring_points(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """监测点位: 上游对照 + 下游影响 (仅2个)。"""
    result = PlacementResult(measure_type=MeasureType.POINT)
    pts: List[Tuple[float, float]] = []

    slope_vec, _, _ = clipper._get_terrain()
    bp = (clipper._model.boundary.polyline
          if clipper._model.boundary and len(clipper._model.boundary.polyline) >= 3
          else zone.polygon if len(zone.polygon) >= 3 else [])

    # 点1 (上游对照): 红线边界上, 来水方向一侧 (坡向投影最小)
    if bp and slope_vec:
        upstream = min(bp, key=lambda p: p[0] * slope_vec[0] + p[1] * slope_vec[1])
        pts.append(upstream)
    elif bp:
        pts.append(bp[0])
    else:
        cx, cy = zone.centroid
        bw = zone.bbox[2] - zone.bbox[0]
        pts.append((zone.bbox[0] - bw * 0.05, cy))

    # 点2 (下游影响): 排水出口附近 或 坡向投影最大
    drain_pois = [poi for poi in clipper._model.global_pois
                  if poi.poi_type == "drain_outlet"]
    if drain_pois:
        pts.append(drain_pois[0].position)
    elif bp and slope_vec:
        downstream = max(bp, key=lambda p: p[0] * slope_vec[0] + p[1] * slope_vec[1])
        pts.append(downstream)
    elif bp:
        pts.append(bp[len(bp) // 2])
    else:
        cx, cy = zone.centroid
        bw = zone.bbox[2] - zone.bbox[0]
        pts.append((zone.bbox[2] + bw * 0.05, cy))

    result.points = pts
    result.label_anchor = pts[0] if pts else zone.centroid
    return result


def place_rainwater_tank(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """雨水收集池: 候选点评分 (远离建筑 + 靠近沉砂池 + 靠近绿化)。"""
    result = PlacementResult(measure_type=MeasureType.POINT)

    cx, cy = zone.centroid
    bw = zone.bbox[2] - zone.bbox[0]
    bh = zone.bbox[3] - zone.bbox[1]

    # 生成候选点网格
    candidates: List[Tuple[float, float]] = []
    step = max(bw, bh) / 5
    if step < 5.0:
        step = 5.0
    for ix in range(5):
        for iy in range(5):
            px = zone.bbox[0] + bw * (0.1 + 0.2 * ix)
            py = zone.bbox[1] + bh * (0.1 + 0.2 * iy)
            if len(zone.polygon) >= 3 and not point_in_polygon((px, py), zone.polygon):
                continue
            candidates.append((px, py))

    if not candidates:
        candidates.append((cx, cy))

    # 评分: 远离建筑 + 靠近低点
    buildings = [obs for obs in zone.obstacles if len(obs.polygon) >= 3]
    low_pt = None
    if hydro_adapter:
        low_pt = hydro_adapter.get_lowest_point_in_zone(zone)

    def score(pt: Tuple[float, float]) -> float:
        s = 0.0
        # 远离建筑 (越远越好，归一化)
        for obs in buildings:
            obs_c = polygon_centroid(obs.polygon)
            d = dist(pt, obs_c)
            s += min(d / 50.0, 1.0)  # 50m以上满分
        # 靠近低点 (越近越好)
        if low_pt:
            d = dist(pt, low_pt)
            s += max(0.0, 1.0 - d / 100.0)
        return s

    candidates.sort(key=score, reverse=True)
    result.points = [candidates[0]]
    result.label_anchor = candidates[0]
    return result


def place_greening(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """综合绿化: 建筑群凸包外扩8m的环形绿化带。"""
    result = PlacementResult(measure_type=MeasureType.AREA)

    if len(zone.polygon) < 3:
        result.skipped = True
        result.skip_reason = "zone has no polygon"
        return result

    # 收集建筑
    buildings = [obs for obs in zone.obstacles
                 if "building" in obs.label and len(obs.polygon) >= 3]

    if buildings:
        # 所有建筑点的凸包
        all_pts = [p for b in buildings for p in b.polygon]
        if len(all_pts) >= 3:
            hull = convex_hull(all_pts)
            if len(hull) >= 3:
                # 外扩 8m
                outer = buffer_polygon(hull, 8.0)
                # 裁剪到红线内
                boundary = clipper._model.boundary
                if boundary and len(boundary.polyline) >= 3:
                    clipped = clip_polygon(outer, boundary.polyline)
                    if clipped and len(clipped) >= 3:
                        outer = clipped
                result.polygon = outer
                result.label_anchor = polygon_centroid(outer)
                return result

    # 无建筑时回退到缩进填充
    obstacles = [obs.polygon for obs in zone.obstacles if len(obs.polygon) >= 3]
    if obstacles:
        filled = polygon_subtract_obstacles(zone.polygon, obstacles, 0.85)
    else:
        filled = scale_polygon(zone.polygon, 0.85)

    if filled and len(filled) >= 3:
        result.polygon = filled
        result.label_anchor = polygon_centroid(filled)
    else:
        result.skipped = True
        result.skip_reason = "greening area too small"
    return result


def place_dust_net_cover(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """防尘网苫盖: 覆盖堆土区 + 联动四周截水沟/沉砂池 (联动由linkage处理)。"""
    result = PlacementResult(measure_type=MeasureType.AREA)

    if len(zone.polygon) < 3:
        result.skipped = True
        result.skip_reason = "zone has no polygon"
        return result

    # 覆盖整个分区 (堆土区域)
    result.polygon = list(zone.polygon)
    result.label_anchor = zone.centroid
    return result


def place_temp_cover(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """临时苫盖: 扣除已硬化区域。"""
    result = PlacementResult(measure_type=MeasureType.AREA)

    if len(zone.polygon) < 3:
        result.skipped = True
        result.skip_reason = "zone has no polygon"
        return result

    # 扣除硬化区域 (obstacles中标记为hardened)
    hardened = [obs.polygon for obs in zone.obstacles
                if len(obs.polygon) >= 3 and any(
                    k in obs.label for k in ["hardened", "road", "building"])]
    if hardened:
        filled = polygon_subtract_obstacles(zone.polygon, hardened, 0.95)
    else:
        filled = list(zone.polygon)

    if filled and len(filled) >= 3:
        result.polygon = filled
        result.label_anchor = polygon_centroid(filled) if isinstance(filled[0], tuple) else zone.centroid
    else:
        result.skipped = True
        result.skip_reason = "temp cover area too small"
    return result


def place_roadside_trees(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """行道树: 道路两侧6m间距 + 跳过出入口/建筑。"""
    result = PlacementResult(measure_type=MeasureType.POINT)

    # 找道路边线
    road_edges = [e for e in zone.edges if e.feature_type == "road_edge"]
    if not road_edges:
        road_edges = [e for e in zone.edges if e.length_m > 10]
    if not road_edges and len(zone.polygon) >= 3:
        le = longest_edge(zone.polygon)
        from src.site_model import SourceTag
        road_edges = [EdgeFeature(
            polyline=[le[0], le[1]], feature_type="polygon_edge",
            length_m=dist(le[0], le[1]), source=None,
        )]

    if not road_edges:
        result.skipped = True
        result.skip_reason = "no road edge for trees"
        return result

    # 沿最长道路边两侧采样
    road_edges.sort(key=lambda e: e.length_m, reverse=True)
    edge = road_edges[0]

    spacing = 6.0
    samples_left = sample_along_polyline(
        offset_polyline(edge.polyline, 2.0, side="left"), spacing)
    samples_right = sample_along_polyline(
        offset_polyline(edge.polyline, 2.0, side="right"), spacing)

    all_pts = (samples_left or []) + (samples_right or [])

    # 跳过出入口附近 (8m) 和建筑附近 (3m)
    entrances = [poi.position for poi in zone.pois if poi.poi_type == "entrance"]
    entrances += [poi.position for poi in clipper._model.global_pois
                  if poi.poi_type == "entrance"]
    buildings = [obs for obs in zone.obstacles if "building" in obs.label]

    filtered = []
    for pt in all_pts:
        skip = False
        for ent in entrances:
            if dist(pt, ent) < 8.0:
                skip = True
                break
        if not skip:
            for bldg in buildings:
                bc = polygon_centroid(bldg.polygon)
                if dist(pt, bc) < 3.0:
                    skip = True
                    break
        if not skip:
            filtered.append(pt)

    if filtered:
        result.points = filtered
        result.label_anchor = filtered[len(filtered) // 2]
    else:
        result.skipped = True
        result.skip_reason = "all tree positions blocked"
    return result


def place_topsoil_recovery(
    clipper: GeometryClipper, zone: ZoneModel, name: str,
    hydro_adapter: Any = None, **kw,
) -> PlacementResult:
    """表土回覆: 绿化区内按体积计算覆盖面积。"""
    result = PlacementResult(measure_type=MeasureType.AREA)

    if len(zone.polygon) < 3:
        result.skipped = True
        result.skip_reason = "zone has no polygon"
        return result

    # 表土回覆与绿化区重合，但缩小一点
    obstacles = [obs.polygon for obs in zone.obstacles if len(obs.polygon) >= 3]
    if obstacles:
        filled = polygon_subtract_obstacles(zone.polygon, obstacles, 0.80)
    else:
        filled = scale_polygon(zone.polygon, 0.80)

    if filled and len(filled) >= 3:
        result.polygon = filled
        result.label_anchor = polygon_centroid(filled)
    else:
        result.skipped = True
        result.skip_reason = "topsoil area too small"
    return result


# ═══════════════════════════════════════════════════════════════
# PLACER_REGISTRY — 关键词→专用函数分发表
# ═══════════════════════════════════════════════════════════════

# (关键词列表, 布置函数)
PLACER_REGISTRY: list[tuple[list[str], PlacerFunc]] = [
    (["排水沟"], place_drainage_ditch),
    (["截水沟", "拦水沟"], place_intercept_ditch),
    (["临时排水"], place_temp_drainage),
    (["围挡", "围墙", "围栏"], place_construction_fence),
    (["沉沙池", "沉淀池", "沉砂池"], place_sedimentation_basin),
    (["洗车", "冲洗台", "冲洗平台"], place_vehicle_wash),
    (["监测点"], place_monitoring_points),
    (["雨水收集", "蓄水池"], place_rainwater_tank),
    (["绿化", "草皮", "植草", "植被恢复", "液力喷播"], place_greening),
    (["防尘网"], place_dust_net_cover),
    (["苫盖", "临时苫盖", "彩条布"], place_temp_cover),
    (["行道树", "乔木"], place_roadside_trees),
    (["表土回覆", "表土剥离"], place_topsoil_recovery),
]


def lookup_placer(measure_name: str) -> Optional[PlacerFunc]:
    """根据措施名查找专用布置函数。"""
    for keywords, func in PLACER_REGISTRY:
        for kw in keywords:
            if kw in measure_name:
                return func
    return None
