"""融合层数据结构 — SiteModel + ZoneModel + SiteModelBuilder。

Zone-centric 数据模型: 每个分区拥有自己的要素 (替代 feature-centric 的 CadSiteFeatures)。

融合优先级: GIS (0.95) > ezdxf (0.85) > VL (0.6~0.8) > META (0.5)
同一要素多来源冲突时取置信度最高的；VL 确认可提升 ezdxf 置信度 +0.1。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.geo_utils import (
    shoelace_area, polygon_centroid, points_bounds, point_in_polygon,
    dist, polyline_length, nearest_point_on_polyline,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 数据来源标记
# ═══════════════════════════════════════════════════════════════

class SourceType(Enum):
    EZDXF = "ezdxf"         # 结构解析 (confidence=0.85)
    VL = "vl"               # 视觉模型 (confidence=0.6~0.8)
    GIS = "gis"             # GIS 数据 (confidence=0.95)
    META = "meta"           # 配置/用户输入 (confidence=0.5)
    COMPUTED = "computed"    # 计算推导


@dataclass
class SourceTag:
    origin: SourceType
    confidence: float      # 0.0 ~ 1.0
    detail: str = ""       # "layer=boundary", "vl_round=1" 等


# ═══════════════════════════════════════════════════════════════
# 核心数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class BoundaryInfo:
    polyline: List[Tuple[float, float]]
    area_m2: float
    source: SourceTag
    bbox: Tuple[float, float, float, float]


@dataclass
class EdgeFeature:
    """边线要素: 道路边、围墙线、排水沟线、边坡顶/趾线。"""
    polyline: List[Tuple[float, float]]
    feature_type: str      # "road_edge", "wall", "drain", "slope_top", "slope_toe"
    length_m: float
    source: SourceTag
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Obstacle:
    """障碍物: 建筑、构筑物、已有设施。"""
    polygon: List[Tuple[float, float]]
    label: str
    area_m2: float
    source: SourceTag


@dataclass
class PointOfInterest:
    """兴趣点: 出入口、交叉口、排水口。"""
    position: Tuple[float, float]
    poi_type: str          # "entrance", "intersection", "drain_outlet", "corner"
    source: SourceTag


@dataclass
class ElevationPoint:
    """标高点。"""
    position: Tuple[float, float]
    elevation: float
    source: Optional[SourceTag] = None


@dataclass
class TerrainInfo:
    slope_direction: Optional[str] = None    # "NW→SE"
    avg_slope_pct: Optional[float] = None
    elevation_range: Optional[Tuple[float, float]] = None
    elevation_points: List[ElevationPoint] = field(default_factory=list)
    source: Optional[SourceTag] = None


@dataclass
class ZoneModel:
    """单个分区的完整模型 — 核心数据单元。"""
    zone_id: str
    polygon: List[Tuple[float, float]]
    area_m2: float
    centroid: Tuple[float, float]
    bbox: Tuple[float, float, float, float]
    edges: List[EdgeFeature] = field(default_factory=list)
    obstacles: List[Obstacle] = field(default_factory=list)
    pois: List[PointOfInterest] = field(default_factory=list)
    terrain: Optional[TerrainInfo] = None
    vl_description: str = ""
    vl_confirmed: bool = False
    source: Optional[SourceTag] = None


@dataclass
class SiteModel:
    """整个项目的融合场景模型。"""
    boundary: Optional[BoundaryInfo] = None
    zones: Dict[str, ZoneModel] = field(default_factory=dict)
    terrain: Optional[TerrainInfo] = None
    global_edges: List[EdgeFeature] = field(default_factory=list)
    global_obstacles: List[Obstacle] = field(default_factory=list)
    global_pois: List[PointOfInterest] = field(default_factory=list)
    vl_global_description: str = ""
    vl_scene_type: str = ""
    build_log: List[str] = field(default_factory=list)

    def get_zone(self, zone_id: str) -> Optional[ZoneModel]:
        """根据 zone_id 获取分区 (精确匹配 → 包含匹配)。"""
        if zone_id in self.zones:
            return self.zones[zone_id]
        for k, v in self.zones.items():
            if k in zone_id or zone_id in k:
                return v
        return None


# ═══════════════════════════════════════════════════════════════
# SiteModelBuilder — 流式构建器
# ═══════════════════════════════════════════════════════════════

class SiteModelBuilder:
    """流式构建 SiteModel。

    用法:
        site_model = (SiteModelBuilder()
            .from_ezdxf(cad_geometry, cad_site_features)
            .from_gis(gis_gdf)
            .from_meta(facts_meta)
            .from_vl(vl_result)
            .build())
    """

    def __init__(self):
        self._model = SiteModel()
        self._cad_geometry = None
        self._cad_features = None
        self._gis_gdf = None
        self._meta = {}
        self._vl_result = None

    def from_ezdxf(self, cad_geometry: Any, cad_site_features: Any) -> "SiteModelBuilder":
        """Phase 1: 从 ezdxf 解析结果构建几何骨架。"""
        self._cad_geometry = cad_geometry
        self._cad_features = cad_site_features
        if cad_site_features is None:
            self._model.build_log.append("ezdxf: no CadSiteFeatures")
            return self

        tag = SourceTag(SourceType.EZDXF, 0.85, "cad_feature_analyzer")

        # 边界
        boundary_pts = cad_site_features.boundary_polyline
        if boundary_pts and len(boundary_pts) >= 3:
            self._model.boundary = BoundaryInfo(
                polyline=list(boundary_pts),
                area_m2=shoelace_area(boundary_pts),
                source=tag,
                bbox=points_bounds(boundary_pts),
            )

        # 分区多边形
        zone_polygons = getattr(cad_site_features, 'zone_polygons', {})
        for zone_name, polygon in zone_polygons.items():
            if len(polygon) < 3:
                continue
            self._model.zones[zone_name] = ZoneModel(
                zone_id=zone_name,
                polygon=list(polygon),
                area_m2=shoelace_area(polygon),
                centroid=polygon_centroid(polygon),
                bbox=points_bounds(polygon),
                source=tag,
            )

        # 全局要素: 道路边线
        for road in getattr(cad_site_features, 'road_edges', []):
            self._model.global_edges.append(EdgeFeature(
                polyline=list(road.points),
                feature_type="road_edge",
                length_m=road.length,
                source=tag,
                properties={"category": road.category, "layer": road.source_layer},
            ))

        # 全局要素: 边界段
        for seg in getattr(cad_site_features, 'boundary_segments', []):
            self._model.global_edges.append(EdgeFeature(
                polyline=list(seg.points),
                feature_type="boundary",
                length_m=seg.length,
                source=tag,
                properties={"category": seg.category, "layer": seg.source_layer},
            ))

        # 全局障碍物: 建筑
        for bldg in getattr(cad_site_features, 'building_footprints', []):
            self._model.global_obstacles.append(Obstacle(
                polygon=list(bldg.points),
                label=f"building_{bldg.category}",
                area_m2=bldg.area,
                source=tag,
            ))

        # 全局 POI: 出入口
        for ent in getattr(cad_site_features, 'entrances', []):
            self._model.global_pois.append(PointOfInterest(
                position=ent.position,
                poi_type="entrance",
                source=tag,
            ))

        # 全局 POI: 排水口
        for drain in getattr(cad_site_features, 'drainage_outlets', []):
            self._model.global_pois.append(PointOfInterest(
                position=drain.position,
                poi_type="drain_outlet",
                source=tag,
            ))

        # 排水方向 + 标高数据
        drain_dir = getattr(cad_site_features, 'drainage_direction', '')
        slope_pct = getattr(cad_site_features, 'computed_slope_pct', None)
        elev_range = getattr(cad_site_features, 'computed_elev_range', None)
        elev_pts_raw = getattr(cad_site_features, 'elevation_points', [])

        elev_pts = [ElevationPoint(position=(x, y), elevation=z, source=tag)
                    for x, y, z in elev_pts_raw]

        if drain_dir or slope_pct is not None:
            self._model.terrain = TerrainInfo(
                slope_direction=drain_dir or None,
                avg_slope_pct=slope_pct,
                elevation_range=elev_range,
                elevation_points=elev_pts,
                source=tag,
            )

        self._model.build_log.append(
            f"ezdxf: boundary={len(boundary_pts) if boundary_pts else 0}pts, "
            f"zones={len(zone_polygons)}, "
            f"edges={len(self._model.global_edges)}, "
            f"obstacles={len(self._model.global_obstacles)}, "
            f"pois={len(self._model.global_pois)}"
        )
        return self

    def from_gis(self, gis_gdf: Any) -> "SiteModelBuilder":
        """Phase 2: GIS 数据补充 (最高置信度)。"""
        self._gis_gdf = gis_gdf
        if gis_gdf is None:
            self._model.build_log.append("gis: no data")
            return self

        tag = SourceTag(SourceType.GIS, 0.95, "geopandas")
        count = 0

        try:
            for _, row in gis_gdf.iterrows():
                geom = row.geometry
                if geom is None:
                    continue
                name = str(row.get("name", row.get("NAME", f"GIS_Zone_{count}")))

                # GIS 覆盖已有分区 (高置信度)
                polygon_pts = list(geom.exterior.coords) if hasattr(geom, 'exterior') else []
                if len(polygon_pts) >= 3:
                    # 移除闭合重复点
                    if polygon_pts[0] == polygon_pts[-1]:
                        polygon_pts = polygon_pts[:-1]
                    self._model.zones[name] = ZoneModel(
                        zone_id=name,
                        polygon=polygon_pts,
                        area_m2=geom.area,
                        centroid=(geom.centroid.x, geom.centroid.y),
                        bbox=tuple(geom.bounds),
                        source=tag,
                    )
                    count += 1
        except Exception as e:
            logger.warning(f"GIS 数据融合异常: {e}")

        self._model.build_log.append(f"gis: {count} zones added/updated")
        return self

    def from_meta(self, facts_meta: dict) -> "SiteModelBuilder":
        """Phase 3: 配置/用户输入补充。"""
        self._meta = facts_meta or {}
        if not self._meta:
            self._model.build_log.append("meta: no data")
            return self

        tag = SourceTag(SourceType.META, 0.5, "facts_v2.json")

        # 从 meta.zones 创建缺失分区
        zones_conf = self._meta.get("zones", [])
        for z in zones_conf:
            zname = z.get("name", "")
            if zname and zname not in self._model.zones:
                area_m2 = z.get("area_hm2", 0) * 10000
                if area_m2 <= 0:
                    area_m2 = z.get("area_m2", 0)
                # 无几何 → 空多边形，后续 build() 会生成矩形
                self._model.zones[zname] = ZoneModel(
                    zone_id=zname,
                    polygon=[],
                    area_m2=area_m2,
                    centroid=(0, 0),
                    bbox=(0, 0, 0, 0),
                    source=tag,
                )

        # 项目边界 (低优先级，仅在无边界时使用)
        if self._model.boundary is None:
            land_area = self._meta.get("land_area_hm2", 0) * 10000
            if land_area > 0:
                import math
                w = math.sqrt(land_area * 1.5)
                h = land_area / w
                rect = [(0, 0), (w, 0), (w, h), (0, h)]
                self._model.boundary = BoundaryInfo(
                    polyline=rect,
                    area_m2=land_area,
                    source=tag,
                    bbox=(0, 0, w, h),
                )

        self._model.build_log.append(f"meta: {len(zones_conf)} zones from config")
        return self

    def from_vl(self, vl_result: Any) -> "SiteModelBuilder":
        """Phase 4: VL 语义融合 (验证 + 补充描述)。"""
        self._vl_result = vl_result
        if vl_result is None:
            self._model.build_log.append("vl: no data")
            return self

        tag_base = SourceTag(SourceType.VL, 0.7, "vl_analyzer")

        # Round 1 全局场景
        global_scene = getattr(vl_result, 'global_scene', None)
        if isinstance(global_scene, dict):
            self._model.vl_scene_type = global_scene.get("scene_type", "")
            self._model.vl_global_description = global_scene.get("description", "")

            # 排水方向: VL 确认可提升 ezdxf 置信度
            vl_drain = global_scene.get("terrain_direction", "")
            if vl_drain and self._model.terrain:
                self._model.terrain.slope_direction = vl_drain
                if self._model.terrain.source:
                    self._model.terrain.source.confidence = min(
                        1.0, self._model.terrain.source.confidence + 0.1
                    )
            elif vl_drain:
                self._model.terrain = TerrainInfo(
                    slope_direction=vl_drain,
                    source=tag_base,
                )

        # Round 2 分区验证
        zone_validation = getattr(vl_result, 'zone_validation', None)
        if isinstance(zone_validation, dict):
            for zone_id, vdata in zone_validation.items():
                zone = self._model.get_zone(zone_id)
                if zone is None:
                    continue
                if isinstance(vdata, dict):
                    zone.vl_confirmed = vdata.get("exists", False)
                    zone.vl_description = vdata.get("location_description", "")
                    # VL 确认提升源置信度
                    if zone.vl_confirmed and zone.source:
                        zone.source.confidence = min(1.0, zone.source.confidence + 0.1)

        self._model.build_log.append("vl: semantic fusion applied")
        return self

    def build(self) -> SiteModel:
        """最终构建: 分配全局要素到分区 + 补全缺失几何。"""
        model = self._model

        # 1. 为无几何的分区生成矩形 (META 来源的分区)
        self._fill_missing_polygons()

        # 2. 将 global_edges/obstacles/pois 按 point_in_polygon 分配到对应分区
        self._assign_global_features()

        model.build_log.append(
            f"build: final zones={len(model.zones)}, "
            f"boundary={'yes' if model.boundary else 'no'}"
        )
        logger.info(f"SiteModel 构建完成: {model.build_log[-1]}")

        return model

    def _fill_missing_polygons(self):
        """为没有几何数据的分区生成矩形。"""
        import math

        missing = [z for z in self._model.zones.values() if len(z.polygon) < 3]
        if not missing:
            return

        # 参考已有分区或边界确定排列位置
        if self._model.boundary:
            bbox = self._model.boundary.bbox
        else:
            # 从已有分区推断
            all_pts = []
            for z in self._model.zones.values():
                if z.polygon:
                    all_pts.extend(z.polygon)
            if all_pts:
                bbox = points_bounds(all_pts)
            else:
                bbox = (0, 0, 1000, 1000)

        x_start = bbox[0] + (bbox[2] - bbox[0]) * 0.1
        y_start = bbox[1] + (bbox[3] - bbox[1]) * 0.1
        max_width = (bbox[2] - bbox[0]) * 0.8
        x_cursor = x_start
        y_cursor = y_start
        row_height = 0.0
        padding = max_width * 0.02

        for zone in missing:
            area = zone.area_m2 or 10000
            w = math.sqrt(area * 1.2)
            h = area / w if w > 0 else w

            if x_cursor + w > x_start + max_width:
                x_cursor = x_start
                y_cursor += row_height + padding
                row_height = 0.0

            polygon = [
                (x_cursor, y_cursor),
                (x_cursor + w, y_cursor),
                (x_cursor + w, y_cursor + h),
                (x_cursor, y_cursor + h),
            ]
            zone.polygon = polygon
            zone.centroid = polygon_centroid(polygon)
            zone.bbox = points_bounds(polygon)
            x_cursor += w + padding
            row_height = max(row_height, h)

    def _assign_global_features(self):
        """将全局要素按几何位置分配到分区。"""
        zones_with_poly = [z for z in self._model.zones.values() if len(z.polygon) >= 3]
        if not zones_with_poly:
            return

        def _find_zone(pt: Tuple[float, float]) -> Optional[ZoneModel]:
            for zone in zones_with_poly:
                if point_in_polygon(pt, zone.polygon):
                    return zone
            # 找最近分区
            best_zone = None
            best_dist = float("inf")
            for zone in zones_with_poly:
                d = dist(pt, zone.centroid)
                if d < best_dist:
                    best_dist = d
                    best_zone = zone
            return best_zone

        # 分配边线要素
        for edge in self._model.global_edges:
            if not edge.polyline:
                continue
            mid_idx = len(edge.polyline) // 2
            mid_pt = edge.polyline[mid_idx]
            zone = _find_zone(mid_pt)
            if zone:
                zone.edges.append(edge)

        # 分配障碍物
        for obs in self._model.global_obstacles:
            if not obs.polygon:
                continue
            cx, cy = polygon_centroid(obs.polygon)
            zone = _find_zone((cx, cy))
            if zone:
                zone.obstacles.append(obs)

        # 分配 POI
        for poi in self._model.global_pois:
            zone = _find_zone(poi.position)
            if zone:
                zone.pois.append(poi)
