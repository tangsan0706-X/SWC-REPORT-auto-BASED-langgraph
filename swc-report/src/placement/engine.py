"""PlacementEngine v2 — 6阶段措施布置引擎。

Pipeline:
  Phase 1: Place    — 专用布置函数 → 通用策略回退
  Phase 2: Linkage  — 联动解析 (排水沟→沉砂池等)
  Phase 3: Collision — 碰撞检测 + 距离规则
  Phase 4: Optimize — 全局碰撞二次优化
  Phase 5: Summary  — 生成摘要

向后兼容: 所有旧 API 保持不变。
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from src.geo_utils import (
    shoelace_area, polyline_length, polygon_centroid,
    polygons_overlap, clip_polyline,
)
from src.site_model import SiteModel, ZoneModel
from .types import MeasureType, Strategy, PlacementResult
from .classifier import classify_measure, route_strategy
from .placers import GeometryClipper, lookup_placer
from .collision import CollisionResolver, CollisionResolverV2
from .linkage import LinkageResolver
from .hydro_adapter import HydroAdapter

logger = logging.getLogger(__name__)


class PlacementEngine:
    """几何布置引擎 v2 — 统一接口。

    向后兼容: resolve() 返回与旧 MeasurePlacementResolver.resolve() 相同格式。
    新增: 水文感知 + 联动 + 增强碰撞。
    """

    def __init__(self, site_model: SiteModel, hydro_report: Any = None):
        self._model = site_model
        self._clipper = GeometryClipper(site_model)
        self._collision = CollisionResolverV2()
        self._linkage = LinkageResolver(site_model)
        self._registry: Dict[str, PlacementResult] = {}

        # 水文适配器
        self._hydro: Optional[HydroAdapter] = None
        if hydro_report is not None or (
            site_model.terrain and site_model.terrain.elevation_points
        ):
            self._hydro = HydroAdapter(site_model, hydro_report)

    def resolve(self, measure_name: str, zone_id: str = "",
                unit: str = "", quantity: float = 0,
                zone_bounds: tuple | None = None,
                **kw) -> dict | None:
        """向后兼容接口。

        返回 {"polyline"|"polygon"|"points": ..., "label_anchor": ..., "strategy": ...}
        或 None (无法布置)。
        """
        zone = self._model.get_zone(zone_id)
        if zone is None:
            if zone_bounds:
                x0, y0, x1, y1 = zone_bounds
                zone = ZoneModel(
                    zone_id=zone_id or "temp",
                    polygon=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                    area_m2=(x1 - x0) * (y1 - y0),
                    centroid=((x0 + x1) / 2, (y0 + y1) / 2),
                    bbox=zone_bounds,
                )
            else:
                # Fallback: 从边界生成临时分区
                zone = self._create_fallback_zone(zone_id)
                if zone is None:
                    return None

        # 分类 → 策略
        mtype = classify_measure(measure_name, unit)
        strategy = route_strategy(measure_name, mtype)

        # Phase 1: 尝试专用布置函数
        result = None
        placer = lookup_placer(measure_name)
        if placer:
            try:
                result = placer(
                    self._clipper, zone, measure_name,
                    hydro_adapter=self._hydro, **kw,
                )
            except Exception as e:
                logger.warning(f"Specialized placer failed for '{measure_name}': {e}")
                result = None

        # 回退: 通用策略
        if result is None or result.skipped:
            result = self._clipper.generate(strategy, zone, measure_name)

        result.measure_type = mtype
        result.strategy = strategy
        result.zone_id = zone.zone_id
        result.measure_name = measure_name

        # Phase 3: 碰撞消解
        result = self._collision.resolve(result)

        if result.skipped:
            return None

        # Phase 3.5: 边界 clamp — 确保措施在场地边界内
        result = self._clamp_to_boundary(result)

        # Phase 3.6: 建筑排斥 — 措施不得覆盖建筑
        result = self._avoid_buildings(result)

        # 注册
        key = f"{zone_id}::{measure_name}"
        self._registry[key] = result

        return result.to_legacy_dict()

    def resolve_all(self, measures: List[dict],
                    zone_assignments: Dict[str, List[dict]] | None = None,
                    ) -> Dict[str, Dict[str, PlacementResult]]:
        """批量布置 (按 LINE→AREA→POINT→OVERLAY 顺序)。

        6阶段流水线:
          Phase 1: Place (专用→通用回退)
          Phase 2: Linkage (联动创建)
          Phase 3: Collision (碰撞检测) — 在 resolve() 内
          Phase 4: Optimize — 在 optimize_batch() 中
          Phase 5: Summary — 在 get_placement_summary() 中

        Args:
            measures: 措施列表 [{措施名称, 分区, 单位, 数量, ...}]
            zone_assignments: {zone_id: [measure_dict, ...]}

        Returns:
            {zone_id: {measure_name: PlacementResult}}
        """
        # 构建分区分配
        if zone_assignments is None:
            zone_assignments = {}
            for m in measures:
                zone_id = m.get("分区", m.get("zone", ""))
                if not zone_id:
                    continue
                zone_assignments.setdefault(zone_id, []).append(m)

        # 分类所有措施
        typed_measures: Dict[MeasureType, List[tuple]] = {
            MeasureType.LINE: [],
            MeasureType.AREA: [],
            MeasureType.POINT: [],
            MeasureType.OVERLAY: [],
        }
        for zone_id, measures_list in zone_assignments.items():
            for m in measures_list:
                name = m.get("措施名称", m.get("name", ""))
                unit = m.get("单位", m.get("unit", ""))
                mtype = classify_measure(name, unit)
                typed_measures[mtype].append((zone_id, m, mtype))

        # Phase 1+3: 按顺序布置 (LINE → AREA → POINT → OVERLAY)
        results: Dict[str, Dict[str, PlacementResult]] = {}
        order = [MeasureType.LINE, MeasureType.AREA, MeasureType.POINT, MeasureType.OVERLAY]

        for mtype in order:
            for zone_id, m, _ in typed_measures[mtype]:
                name = m.get("措施名称", m.get("name", ""))
                unit = m.get("单位", m.get("unit", ""))
                quantity = float(m.get("数量", m.get("quantity", 0)) or 0)

                resolved = self.resolve(name, zone_id, unit, quantity)
                if resolved is not None:
                    if zone_id not in results:
                        results[zone_id] = {}
                    key = f"{zone_id}::{name}"
                    results[zone_id][name] = self._registry.get(key,
                        PlacementResult(measure_name=name, zone_id=zone_id))

        # Phase 2: 联动解析
        results = self._linkage.resolve(results, self._hydro)

        # 将联动新增的措施注册到 _registry
        for zone_id, zone_results in results.items():
            for name, r in zone_results.items():
                key = f"{zone_id}::{name}"
                if key not in self._registry:
                    self._registry[key] = r

        return results

    def get_placement_summary(self) -> str:
        """生成摘要 (供 VL sanity check 使用)。含联动/水文信息。"""
        lines = []
        linkage_count = 0
        hydro_count = 0

        for key, result in self._registry.items():
            zone_id, name = key.split("::", 1) if "::" in key else (key, "")
            status = "OK" if not result.skipped else f"SKIP({result.skip_reason})"
            geom_type = ("lines" if result.polylines else
                        ("line" if result.polyline else ("area" if result.polygon else
                        ("point" if result.points else "none"))))

            extra = ""
            if result.linked_to:
                extra += f" → linked:{','.join(result.linked_to)}"
                linkage_count += 1
            if result.hydro_info:
                hydro_count += 1
                tier = result.hydro_info.get("tier", "?")
                extra += f" [hydro:T{tier}]"

            lines.append(f"  [{zone_id}] {name}: {result.strategy.value} → {geom_type} ({status}){extra}")

        header = f"已布置 {len(self._registry)} 项措施"
        if linkage_count > 0:
            header += f", {linkage_count} 项联动"
        if hydro_count > 0:
            header += f", {hydro_count} 项水文感知"
        if self._hydro:
            header += f" (水文Tier{self._hydro.tier})"

        return header + ":\n" + "\n".join(lines)

    def get_placement(self, measure_name: str, zone_id: str = "") -> dict | None:
        """查找 resolve_all() 预计算的布置结果。

        Args:
            measure_name: 措施名称
            zone_id: 分区 ID (可选, 为空时模糊匹配)

        Returns:
            旧格式 dict 或 None
        """
        key = f"{zone_id}::{measure_name}"
        result = self._registry.get(key)
        if result is None:
            for k, v in self._registry.items():
                if k.endswith(f"::{measure_name}"):
                    result = v
                    break
        if result is not None and not result.skipped:
            return result.to_legacy_dict()
        return None

    def _create_fallback_zone(self, zone_id: str) -> Optional[ZoneModel]:
        """从场地边界生成一个临时分区 (用于未被 CAD 识别的分区)。

        策略: 在边界内未被已有分区占据的区域, 划分一个子矩形。
        使用确定性哈希确保同一 zone_id 总是得到相同位置。
        """
        boundary = self._model.boundary
        if not boundary or not boundary.polyline or len(boundary.polyline) < 3:
            return None

        bx = [p[0] for p in boundary.polyline]
        by = [p[1] for p in boundary.polyline]
        x_min, x_max = min(bx), max(bx)
        y_min, y_max = min(by), max(by)
        w = x_max - x_min
        h = y_max - y_min

        if w < 1 or h < 1:
            return None

        # 已有分区的质心列表 (用于避免重叠)
        existing_centroids = []
        for z in self._model.zones.values():
            existing_centroids.append(z.centroid)

        # 确定性偏移: 根据 zone_id 的哈希选择角落
        seed = sum(ord(c) for c in zone_id) % 4
        margin = 0.1  # 10% 内缩
        sub_w = w * 0.3
        sub_h = h * 0.3

        corners = [
            (x_min + w * margin, y_min + h * margin),                       # 左下
            (x_max - w * margin - sub_w, y_min + h * margin),               # 右下
            (x_min + w * margin, y_max - h * margin - sub_h),               # 左上
            (x_max - w * margin - sub_w, y_max - h * margin - sub_h),       # 右上
        ]

        # 选择离已有分区质心最远的角落
        best_corner = corners[seed]
        if existing_centroids:
            def min_dist(corner):
                return min(
                    math.hypot(corner[0] + sub_w/2 - c[0],
                               corner[1] + sub_h/2 - c[1])
                    for c in existing_centroids
                )
            # 排序: 距已有分区最远的优先
            ranked = sorted(corners, key=min_dist, reverse=True)
            best_corner = ranked[seed % len(ranked)]

        cx, cy = best_corner
        polygon = [
            (cx, cy), (cx + sub_w, cy),
            (cx + sub_w, cy + sub_h), (cx, cy + sub_h),
        ]
        centroid = (cx + sub_w / 2, cy + sub_h / 2)
        bbox = (cx, cy, cx + sub_w, cy + sub_h)

        logger.info(f"Fallback zone created for '{zone_id}': bbox={tuple(round(b,1) for b in bbox)}")
        return ZoneModel(
            zone_id=zone_id,
            polygon=polygon,
            area_m2=sub_w * sub_h,
            centroid=centroid,
            bbox=bbox,
        )

    def _clamp_to_boundary(self, result: PlacementResult) -> PlacementResult:
        """将超出场地边界的措施坐标裁剪/拉回场地内。

        对 polyline 使用 Cohen-Sutherland 裁剪 (保留在边界内的线段部分)。
        对 polygon/points 使用逐点 clamp (5% 内缩)。
        """
        boundary = self._model.boundary
        if not boundary or not boundary.polyline or len(boundary.polyline) < 3:
            return result

        bx = [p[0] for p in boundary.polyline]
        by = [p[1] for p in boundary.polyline]
        x_min, x_max = min(bx), max(bx)
        y_min, y_max = min(by), max(by)
        margin_x = (x_max - x_min) * 0.03
        margin_y = (y_max - y_min) * 0.03
        clip_bounds = (x_min + margin_x, y_min + margin_y,
                       x_max - margin_x, y_max - margin_y)

        def clamp_pts(pts):
            if not pts:
                return pts
            x_lo, y_lo, x_hi, y_hi = clip_bounds
            clamped = False
            out = []
            for x, y in pts:
                nx = max(x_lo, min(x_hi, x))
                ny = max(y_lo, min(y_hi, y))
                if nx != x or ny != y:
                    clamped = True
                out.append((nx, ny))
            return out if clamped else pts

        changed = False

        # Polyline: 用线段裁剪而非逐点 clamp
        if result.polyline and len(result.polyline) >= 2:
            segments = clip_polyline(result.polyline, clip_bounds)
            if segments:
                best = max(segments, key=lambda s: polyline_length(s))
                if best != result.polyline:
                    result.polyline = best
                    changed = True
            else:
                result.polyline = clamp_pts(result.polyline)
                changed = True

        # Polylines: 逐条裁剪
        if result.polylines:
            new_polylines = []
            for pl in result.polylines:
                if len(pl) < 2:
                    continue
                segments = clip_polyline(pl, clip_bounds)
                for seg in (segments or []):
                    if len(seg) >= 2:
                        new_polylines.append(seg)
            if new_polylines and new_polylines != result.polylines:
                result.polylines = new_polylines
                changed = True

        if result.polygon:
            new_pg = clamp_pts(result.polygon)
            if new_pg is not result.polygon:
                result.polygon = new_pg
                changed = True
        if result.points:
            new_pp = clamp_pts(result.points)
            if new_pp is not result.points:
                result.points = new_pp
                changed = True

        if changed:
            # 重新计算 label_anchor
            coords = result.polyline or result.polygon or result.points
            if coords and len(coords) >= 1:
                mid = len(coords) // 2
                result.label_anchor = coords[mid]

        return result

    def _avoid_buildings(self, result: PlacementResult) -> PlacementResult:
        """确保措施不与建筑重叠。临时苫盖豁免。"""
        if result.skipped:
            return result
        if "苫盖" in (result.measure_name or ""):
            return result  # 临时苫盖豁免

        from src.geo_utils import point_in_polygon, polygon_centroid

        buildings = []
        for z in self._model.zones.values():
            for obs in z.obstacles:
                if "building" in obs.label and len(obs.polygon) >= 3:
                    buildings.append(obs.polygon)
        if not buildings:
            return result

        # 点状: 落在建筑内则推到建筑外
        if result.points:
            new_pts = []
            for pt in result.points:
                inside = False
                for bpoly in buildings:
                    if point_in_polygon(pt, bpoly):
                        inside = True
                        bc = polygon_centroid(bpoly)
                        dx = pt[0] - bc[0]
                        dy = pt[1] - bc[1]
                        d = math.hypot(dx, dy)
                        if d < 1e-6:
                            dx, dy = 5.0, 0.0
                        else:
                            dx, dy = dx / d * 8.0, dy / d * 8.0
                        pt = (bc[0] + dx, bc[1] + dy)
                        break
                new_pts.append(pt)
            result.points = new_pts

        return result

    def has_precomputed(self) -> bool:
        """是否有预计算结果。"""
        return len(self._registry) > 0

    def optimize_batch(self) -> int:
        """全局碰撞二次优化: 大面积固定, 小面积挪让。

        Returns:
            调整次数
        """
        entries = [(k, r) for k, r in self._registry.items() if not r.skipped]
        if len(entries) < 2:
            return 0

        adjustments = 0
        entries.sort(key=lambda e: self._geom_area(e[1]), reverse=True)

        for i in range(1, len(entries)):
            key_i, ri = entries[i]
            pi = self._to_polygon_approx(ri)
            if not pi:
                continue
            for j in range(i):
                _, rj = entries[j]
                pj = self._to_polygon_approx(rj)
                if not pj:
                    continue
                if polygons_overlap(pi, pj):
                    shifted = self._shift_away(ri, pi, pj)
                    if shifted:
                        self._registry[key_i] = shifted
                        ri = shifted
                        entries[i] = (key_i, shifted)
                        pi = self._to_polygon_approx(ri)
                        adjustments += 1
                        if not pi:
                            break
        return adjustments

    @staticmethod
    def _geom_area(result: PlacementResult) -> float:
        """估算 PlacementResult 的面积。"""
        if result.polygon and len(result.polygon) >= 3:
            return abs(shoelace_area(result.polygon))
        if result.polyline and len(result.polyline) >= 2:
            return polyline_length(result.polyline) * 4.0
        if result.points:
            return len(result.points) * 4.0
        return 0.0

    @staticmethod
    def _to_polygon_approx(result: PlacementResult) -> list | None:
        """将 PlacementResult 转为近似多边形 (碰撞检测用)。"""
        if result.polygon and len(result.polygon) >= 3:
            return result.polygon
        if result.polyline and len(result.polyline) >= 2:
            pts = result.polyline
            buf = 2.0
            poly = []
            for k in range(len(pts) - 1):
                dx = pts[k + 1][0] - pts[k][0]
                dy = pts[k + 1][1] - pts[k][1]
                seg_len = math.hypot(dx, dy)
                if seg_len < 1e-12:
                    continue
                nx = -dy / seg_len * buf
                ny = dx / seg_len * buf
                poly.append((pts[k][0] + nx, pts[k][1] + ny))
            for k in range(len(pts) - 1, 0, -1):
                dx = pts[k][0] - pts[k - 1][0]
                dy = pts[k][1] - pts[k - 1][1]
                seg_len = math.hypot(dx, dy)
                if seg_len < 1e-12:
                    continue
                nx = dy / seg_len * buf
                ny = -dx / seg_len * buf
                poly.append((pts[k][0] + nx, pts[k][1] + ny))
            return poly if len(poly) >= 3 else None
        return None

    @staticmethod
    def _shift_away(result: PlacementResult,
                    new_poly: list, old_poly: list) -> PlacementResult | None:
        """将 result 沿远离 old_poly 的方向平移。"""
        c1 = polygon_centroid(new_poly)
        c2 = polygon_centroid(old_poly)
        dx = c1[0] - c2[0]
        dy = c1[1] - c2[1]
        d = math.hypot(dx, dy)
        if d < 1e-6:
            dx, dy = 1.0, 0.0
            d = 1.0
        nx, ny = dx / d, dy / d

        for shift_dist in (10, 20, 30, 50):
            sx, sy = nx * shift_dist, ny * shift_dist
            shifted = PlacementResult(
                measure_name=result.measure_name,
                zone_id=result.zone_id,
                measure_type=result.measure_type,
                strategy=result.strategy,
            )
            if result.polyline:
                shifted.polyline = [(p[0] + sx, p[1] + sy) for p in result.polyline]
            if result.polylines:
                shifted.polylines = [
                    [(p[0] + sx, p[1] + sy) for p in pl]
                    for pl in result.polylines
                ]
            if result.polygon:
                shifted.polygon = [(p[0] + sx, p[1] + sy) for p in result.polygon]
            if result.points:
                shifted.points = [(p[0] + sx, p[1] + sy) for p in result.points]
            if result.label_anchor:
                shifted.label_anchor = (result.label_anchor[0] + sx,
                                        result.label_anchor[1] + sy)
            sp = PlacementEngine._to_polygon_approx(shifted)
            if sp and not polygons_overlap(sp, old_poly):
                return shifted
        return None
