"""水文适配器 — 3级降级: HydroReport → 标高点IDW → 规范默认值。

提供水文感知的自动尺寸计算和坡向判断。
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from src.geo_utils import (
    dist, polygon_centroid, points_bounds, point_in_polygon,
    find_lowest_point, slope_direction_vector,
)
from src.site_model import SiteModel, ZoneModel, ElevationPoint
from .types import DITCH_SIZE_TABLE, BASIN_SIZE_TABLE

logger = logging.getLogger(__name__)


def idw_interpolate(
    known_points: List[Tuple[float, float, float]],
    query_point: Tuple[float, float],
    power: float = 2.0,
) -> Optional[float]:
    """反距离加权插值 (IDW)。

    Args:
        known_points: [(x, y, value), ...]
        query_point: (x, y)
        power: 距离幂次 (默认2)

    Returns:
        插值结果或None
    """
    if not known_points:
        return None

    qx, qy = query_point
    weights = []
    values = []

    for kx, ky, kv in known_points:
        d = math.hypot(kx - qx, ky - qy)
        if d < 1e-6:
            return kv  # 精确匹配
        w = 1.0 / (d ** power)
        weights.append(w)
        values.append(kv)

    total_w = sum(weights)
    if total_w < 1e-12:
        return None

    return sum(w * v for w, v in zip(weights, values)) / total_w


class HydroAdapter:
    """水文适配器 — 3级降级。

    Tier 1: 完整 HydroReport (含汇水面积、径流系数等)
    Tier 2: 标高点 IDW 插值 (从 SiteModel 获取)
    Tier 3: 规范默认值

    Usage:
        adapter = HydroAdapter(site_model, hydro_report=None)
        ditch = adapter.estimate_ditch_size(zone)
        flow_dir = adapter.get_flow_direction_for_zone(zone)
        low_pt = adapter.get_lowest_point_in_zone(zone)
    """

    def __init__(self, site_model: SiteModel, hydro_report: Any = None):
        self._model = site_model
        self._hydro = hydro_report
        self._tier = self._determine_tier()
        logger.info(f"HydroAdapter initialized: tier={self._tier}")

    def _determine_tier(self) -> int:
        """确定数据等级。"""
        if self._hydro is not None:
            return 1
        terrain = self._model.terrain
        if terrain and terrain.elevation_points:
            return 2
        return 3

    @property
    def tier(self) -> int:
        return self._tier

    # ─────────────────────────────────────────────────────
    # 断面选型
    # ─────────────────────────────────────────────────────

    def estimate_ditch_size(self, zone: ZoneModel) -> Dict[str, Any]:
        """估算排水沟断面尺寸。

        Returns:
            {"width": m, "depth": m, "description": str,
             "catchment_area_hm2": float, "tier": int}
        """
        catchment = self._get_catchment_area(zone)

        for max_area, w, d, desc in DITCH_SIZE_TABLE:
            if catchment <= max_area:
                return {
                    "width": w, "depth": d,
                    "description": desc,
                    "catchment_area_hm2": catchment,
                    "tier": self._tier,
                }

        # 超大汇水面积
        last = DITCH_SIZE_TABLE[-1]
        return {
            "width": last[1], "depth": last[2],
            "description": last[3],
            "catchment_area_hm2": catchment,
            "tier": self._tier,
        }

    def estimate_basin_size(self, zone: ZoneModel) -> Dict[str, Any]:
        """估算沉砂池尺寸。

        Returns:
            {"length": m, "width": m, "depth": m, "description": str,
             "catchment_area_hm2": float, "tier": int}
        """
        catchment = self._get_catchment_area(zone)

        for max_area, l, w, d, desc in BASIN_SIZE_TABLE:
            if catchment <= max_area:
                return {
                    "length": l, "width": w, "depth": d,
                    "description": desc,
                    "catchment_area_hm2": catchment,
                    "tier": self._tier,
                }

        last = BASIN_SIZE_TABLE[-1]
        return {
            "length": last[1], "width": last[2], "depth": last[3],
            "description": last[4],
            "catchment_area_hm2": catchment,
            "tier": self._tier,
        }

    def _get_catchment_area(self, zone: ZoneModel) -> float:
        """获取分区汇水面积 (hm²)。3级降级。"""
        # Tier 1: HydroReport
        if self._hydro:
            catchments = getattr(self._hydro, 'catchment_areas', {})
            if zone.zone_id in catchments:
                return catchments[zone.zone_id]
            # 尝试模糊匹配
            for k, v in catchments.items():
                if k in zone.zone_id or zone.zone_id in k:
                    return v

        # Tier 2/3: 从分区面积估算 (假设径流系数0.6)
        area_m2 = zone.area_m2
        if area_m2 <= 0 and len(zone.polygon) >= 3:
            from src.geo_utils import shoelace_area
            area_m2 = shoelace_area(zone.polygon)
        return area_m2 / 10000.0  # m² → hm²

    # ─────────────────────────────────────────────────────
    # 坡向与低点
    # ─────────────────────────────────────────────────────

    def get_flow_direction_for_zone(self, zone: ZoneModel) -> Optional[Tuple[float, float]]:
        """获取分区内的水流方向向量。

        Returns:
            (dx, dy) 单位向量 或 None
        """
        # Tier 1: HydroReport
        if self._hydro:
            directions = getattr(self._hydro, 'flow_directions', {})
            for k, v in directions.items():
                if k == zone.zone_id or k in zone.zone_id or zone.zone_id in k:
                    if isinstance(v, (list, tuple)) and len(v) == 2:
                        return tuple(v)
                    if isinstance(v, str):
                        return slope_direction_vector(v)

        # Tier 2: 从标高点拟合
        terrain = self._model.terrain
        if terrain and terrain.elevation_points:
            pts_in_zone = self._filter_elevation_points(
                terrain.elevation_points, zone)
            if len(pts_in_zone) >= 2:
                return self._fit_slope_direction(pts_in_zone)

        # Tier 2.5: 全局坡向
        if terrain and terrain.slope_direction:
            return slope_direction_vector(terrain.slope_direction)

        # Tier 3: None
        return None

    def get_lowest_point_in_zone(self, zone: ZoneModel) -> Optional[Tuple[float, float]]:
        """获取分区内标高最低点。

        Returns:
            (x, y) 或 None
        """
        # Tier 1: HydroReport
        if self._hydro:
            low_points = getattr(self._hydro, 'lowest_points', {})
            for k, v in low_points.items():
                if k == zone.zone_id or k in zone.zone_id or zone.zone_id in k:
                    if isinstance(v, (list, tuple)) and len(v) >= 2:
                        return (v[0], v[1])

        # Tier 2: 标高点
        terrain = self._model.terrain
        if terrain and terrain.elevation_points:
            pts_in_zone = self._filter_elevation_points(
                terrain.elevation_points, zone)
            if pts_in_zone:
                raw = [(p.position[0], p.position[1], p.elevation)
                       for p in pts_in_zone]
                return find_lowest_point(raw)

        # Tier 2.5: 全局标高点在zone bbox内
        if terrain and terrain.elevation_points:
            raw = [(p.position[0], p.position[1], p.elevation)
                   for p in terrain.elevation_points]
            return find_lowest_point(raw, within_bbox=zone.bbox)

        # Tier 3: None
        return None

    def interpolate_elevation(
        self, point: Tuple[float, float],
    ) -> Optional[float]:
        """IDW插值估算某点标高。"""
        terrain = self._model.terrain
        if not terrain or not terrain.elevation_points:
            return None

        known = [(p.position[0], p.position[1], p.elevation)
                 for p in terrain.elevation_points]
        return idw_interpolate(known, point)

    # ─────────────────────────────────────────────────────
    # 内部工具
    # ─────────────────────────────────────────────────────

    @staticmethod
    def _filter_elevation_points(
        points: List[ElevationPoint], zone: ZoneModel,
    ) -> List[ElevationPoint]:
        """过滤在分区内的标高点。"""
        if len(zone.polygon) < 3:
            # 用bbox过滤
            x0, y0, x1, y1 = zone.bbox
            return [p for p in points
                    if x0 <= p.position[0] <= x1 and y0 <= p.position[1] <= y1]
        return [p for p in points if point_in_polygon(p.position, zone.polygon)]

    @staticmethod
    def _fit_slope_direction(points: List[ElevationPoint]) -> Optional[Tuple[float, float]]:
        """从标高点拟合坡向 (最高点→最低点方向)。"""
        if len(points) < 2:
            return None

        highest = max(points, key=lambda p: p.elevation)
        lowest = min(points, key=lambda p: p.elevation)

        dx = lowest.position[0] - highest.position[0]
        dy = lowest.position[1] - highest.position[1]
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return None
        return (dx / d, dy / d)
