"""碰撞检测与消解 — CollisionResolver (v1兼容) + CollisionResolverV2 (距离规则)。

v1: 3级消解 (平移→缩放→跳过)
v2: 4级消解 (距离校验→平移→缩放→跳过) + 距离规则 + 互斥规则
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

from src.geo_utils import (
    dist, polygon_centroid, polygons_overlap, scale_polygon,
)
from .types import (
    MeasureType, Strategy, PlacementResult,
    DISTANCE_RULES, EXCLUSION_RULES,
)

logger = logging.getLogger(__name__)


class CollisionResolver:
    """3 级碰撞消解: 平移 → 缩放 → 跳过。(v1 兼容)"""

    def __init__(self):
        self._placed: List[PlacementResult] = []

    def resolve(self, result: PlacementResult) -> PlacementResult:
        """检测碰撞并消解。"""
        if result.skipped:
            return result

        new_poly = self._to_polygon(result)
        if not new_poly or len(new_poly) < 3:
            self._placed.append(result)
            return result

        for placed in self._placed:
            old_poly = self._to_polygon(placed)
            if not old_poly or len(old_poly) < 3:
                continue
            if not polygons_overlap(new_poly, old_poly):
                continue

            # Level 1: 平移
            shifted = self._try_shift(result, new_poly, old_poly)
            if shifted:
                result = shifted
                new_poly = self._to_polygon(result)
                if not new_poly:
                    break
                continue

            # Level 2: 缩放
            scaled = self._try_scale(result)
            if scaled:
                result = scaled
                new_poly = self._to_polygon(result)
                if not new_poly:
                    break
                continue

            # Level 3: 跳过
            result.skipped = True
            result.skip_reason = "collision unresolvable"
            break

        self._placed.append(result)
        return result

    def _to_polygon(self, result: PlacementResult) -> Optional[List[Tuple[float, float]]]:
        """将 PlacementResult 转为多边形用于碰撞检测。"""
        if result.polygon:
            return result.polygon
        if result.polyline and len(result.polyline) >= 2:
            pts = result.polyline
            buf = 2.0
            poly = []
            for i in range(len(pts) - 1):
                dx = pts[i + 1][0] - pts[i][0]
                dy = pts[i + 1][1] - pts[i][1]
                seg_len = math.hypot(dx, dy)
                if seg_len < 1e-12:
                    continue
                nx = -dy / seg_len * buf
                ny = dx / seg_len * buf
                poly.append((pts[i][0] + nx, pts[i][1] + ny))
            for i in range(len(pts) - 1, 0, -1):
                dx = pts[i][0] - pts[i - 1][0]
                dy = pts[i][1] - pts[i - 1][1]
                seg_len = math.hypot(dx, dy)
                if seg_len < 1e-12:
                    continue
                nx = dy / seg_len * buf
                ny = -dx / seg_len * buf
                poly.append((pts[i][0] + nx, pts[i][1] + ny))
            return poly if len(poly) >= 3 else None
        return None

    def _try_shift(self, result: PlacementResult,
                   new_poly: List, old_poly: List) -> Optional[PlacementResult]:
        """Level 1: 平移消解。"""
        c1 = polygon_centroid(new_poly)
        c2 = polygon_centroid(old_poly)
        dx = c1[0] - c2[0]
        dy = c1[1] - c2[1]
        d = math.hypot(dx, dy)
        if d < 1e-6:
            dx, dy = 1.0, 0.0
            d = 1.0
        nx, ny = dx / d, dy / d

        for shift_dist in (10, 20, 30, 40, 50):
            sx, sy = nx * shift_dist, ny * shift_dist
            shifted = self._shift_result(result, sx, sy)
            shifted_poly = self._to_polygon(shifted)
            if shifted_poly and not polygons_overlap(shifted_poly, old_poly):
                return shifted

        return None

    def _try_scale(self, result: PlacementResult) -> Optional[PlacementResult]:
        """Level 2: 缩放消解。"""
        if result.polygon and len(result.polygon) >= 3:
            scaled_poly = scale_polygon(result.polygon, 0.7)
            new_result = PlacementResult(
                measure_name=result.measure_name,
                zone_id=result.zone_id,
                measure_type=result.measure_type,
                strategy=result.strategy,
                polygon=scaled_poly,
                label_anchor=polygon_centroid(scaled_poly),
            )
            return new_result
        return None

    def _shift_result(self, result: PlacementResult,
                      dx: float, dy: float) -> PlacementResult:
        """平移 PlacementResult 的所有几何。"""
        new = PlacementResult(
            measure_name=result.measure_name,
            zone_id=result.zone_id,
            measure_type=result.measure_type,
            strategy=result.strategy,
        )
        if result.polyline:
            new.polyline = [(p[0] + dx, p[1] + dy) for p in result.polyline]
        if result.polygon:
            new.polygon = [(p[0] + dx, p[1] + dy) for p in result.polygon]
        if result.points:
            new.points = [(p[0] + dx, p[1] + dy) for p in result.points]
        if result.label_anchor:
            new.label_anchor = (result.label_anchor[0] + dx,
                               result.label_anchor[1] + dy)
        return new


class CollisionResolverV2(CollisionResolver):
    """增强碰撞检测: 距离规则 + 互斥规则 + 4级消解。

    继承 v1 的基础碰撞检测，新增:
    - 措施间最小距离校验 (DISTANCE_RULES)
    - 互斥规则 (EXCLUSION_RULES)
    - 距离校验作为第一级
    """

    def resolve(self, result: PlacementResult) -> PlacementResult:
        """检测碰撞并消解 (v2: 4级)。"""
        if result.skipped:
            return result

        # Level 0: 互斥检查
        for placed in self._placed:
            if self._check_exclusion(result.measure_name, placed.measure_name):
                # 同一zone中互斥措施不能共存
                if result.zone_id == placed.zone_id:
                    result.skipped = True
                    result.skip_reason = f"exclusive with {placed.measure_name}"
                    self._placed.append(result)
                    return result

        new_poly = self._to_polygon(result)
        if not new_poly or len(new_poly) < 3:
            self._placed.append(result)
            return result

        for placed in self._placed:
            old_poly = self._to_polygon(placed)
            if not old_poly or len(old_poly) < 3:
                continue

            # Level 1: 距离规则校验
            min_dist = self._get_min_distance(result.measure_name, placed.measure_name)
            if min_dist > 0:
                actual_dist = self._polygon_distance(new_poly, old_poly)
                if actual_dist < min_dist:
                    # 需要平移到满足距离
                    shifted = self._try_shift_to_distance(
                        result, new_poly, old_poly, min_dist)
                    if shifted:
                        result = shifted
                        new_poly = self._to_polygon(result)
                        if not new_poly:
                            break
                        continue

            # Level 2: 重叠检测 + 平移
            if polygons_overlap(new_poly, old_poly):
                shifted = self._try_shift(result, new_poly, old_poly)
                if shifted:
                    result = shifted
                    new_poly = self._to_polygon(result)
                    if not new_poly:
                        break
                    continue

                # Level 3: 缩放
                scaled = self._try_scale(result)
                if scaled:
                    result = scaled
                    new_poly = self._to_polygon(result)
                    if not new_poly:
                        break
                    continue

                # Level 4: 跳过
                result.skipped = True
                result.skip_reason = f"collision with {placed.measure_name}"
                break

        self._placed.append(result)
        return result

    @staticmethod
    def _check_exclusion(name_a: str, name_b: str) -> bool:
        """检查两个措施是否互斥。"""
        for kw_a, kw_b in EXCLUSION_RULES:
            if (kw_a in name_a and kw_b in name_b) or \
               (kw_b in name_a and kw_a in name_b):
                return True
        return False

    @staticmethod
    def _get_min_distance(name_a: str, name_b: str) -> float:
        """获取两个措施间的最小距离要求。"""
        for kw_a, kw_b, min_d in DISTANCE_RULES:
            if (kw_a in name_a and kw_b in name_b) or \
               (kw_b in name_a and kw_a in name_b):
                return min_d
        return 0.0

    @staticmethod
    def _polygon_distance(poly_a: List[Tuple[float, float]],
                          poly_b: List[Tuple[float, float]]) -> float:
        """两多边形间近似最小距离 (质心距离 - 半径估算)。"""
        ca = polygon_centroid(poly_a)
        cb = polygon_centroid(poly_b)
        center_dist = dist(ca, cb)

        # 估算半径: max(各顶点到质心距离)
        ra = max(dist(p, ca) for p in poly_a) if poly_a else 0
        rb = max(dist(p, cb) for p in poly_b) if poly_b else 0

        return max(0.0, center_dist - ra - rb)

    def _try_shift_to_distance(
        self, result: PlacementResult,
        new_poly: List, old_poly: List,
        min_distance: float,
    ) -> Optional[PlacementResult]:
        """平移直到满足最小距离。"""
        c1 = polygon_centroid(new_poly)
        c2 = polygon_centroid(old_poly)
        dx = c1[0] - c2[0]
        dy = c1[1] - c2[1]
        d = math.hypot(dx, dy)
        if d < 1e-6:
            dx, dy = 1.0, 0.0
            d = 1.0
        nx, ny = dx / d, dy / d

        for shift_dist in (min_distance, min_distance * 1.5, min_distance * 2):
            sx, sy = nx * shift_dist, ny * shift_dist
            shifted = self._shift_result(result, sx, sy)
            shifted_poly = self._to_polygon(shifted)
            if shifted_poly:
                new_dist = self._polygon_distance(shifted_poly, old_poly)
                if new_dist >= min_distance * 0.8:  # 允许20%容差
                    return shifted

        return None
