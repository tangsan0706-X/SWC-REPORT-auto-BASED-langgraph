"""联动解析器 — 8条措施联动规则。

措施间联动关系 (如排水沟→沉砂池、洗车台→三级沉淀池等)。
自动创建缺失的下游措施，计算连接线几何。
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from src.geo_utils import (
    dist, polygon_centroid, offset_polyline, scale_polygon,
)
from src.site_model import SiteModel, ZoneModel
from .types import (
    MeasureType, Strategy, PlacementResult,
    LinkageType, LINKAGE_RULES,
)

logger = logging.getLogger(__name__)


class LinkageResolver:
    """措施联动解析器。

    在所有措施布置完成后运行，解析联动关系:
    1. 找到源措施
    2. 找到/创建目标措施
    3. 计算连接线 (源末端→目标位置)
    4. 回写 linked_to, linkage_lines 到 PlacementResult
    """

    def __init__(self, site_model: SiteModel):
        self._model = site_model

    def resolve(
        self,
        results: Dict[str, Dict[str, PlacementResult]],
        hydro_adapter: Any = None,
    ) -> Dict[str, Dict[str, PlacementResult]]:
        """解析所有联动关系。

        Args:
            results: {zone_id: {measure_name: PlacementResult}}
            hydro_adapter: 水文适配器 (用于自动创建的沉砂池定位)

        Returns:
            更新后的 results (含新增的联动措施)
        """
        for rule_src, rule_tgt, link_type, auto_create in LINKAGE_RULES:
            self._apply_rule(
                results, rule_src, rule_tgt, link_type, auto_create,
                hydro_adapter,
            )
        return results

    def _apply_rule(
        self,
        results: Dict[str, Dict[str, PlacementResult]],
        src_kw: str, tgt_kw: str,
        link_type: LinkageType, auto_create: bool,
        hydro_adapter: Any,
    ):
        """应用单条联动规则。"""
        for zone_id, zone_results in list(results.items()):
            # 找源措施
            sources = [(name, r) for name, r in zone_results.items()
                       if src_kw in name and not r.skipped]
            if not sources:
                continue

            # 找目标措施
            targets = [(name, r) for name, r in zone_results.items()
                       if tgt_kw in name and not r.skipped]

            # 也在其他zone找目标
            if not targets:
                for other_zid, other_results in results.items():
                    if other_zid == zone_id:
                        continue
                    for name, r in other_results.items():
                        if tgt_kw in name and not r.skipped:
                            targets.append((name, r))

            for src_name, src_result in sources:
                if targets:
                    # 选最近的目标
                    src_anchor = self._get_anchor(src_result)
                    best_tgt = min(
                        targets,
                        key=lambda t: dist(src_anchor, self._get_anchor(t[1])),
                    )
                    tgt_name, tgt_result = best_tgt

                    # 计算连接线
                    link_line = self._compute_link_line(
                        src_result, tgt_result, link_type)

                    # 回写
                    if src_result.linked_to is None:
                        src_result.linked_to = []
                    src_result.linked_to.append(tgt_name)
                    if link_line:
                        if src_result.linkage_lines is None:
                            src_result.linkage_lines = []
                        src_result.linkage_lines.append(link_line)

                elif auto_create:
                    # 自动创建目标措施
                    new_result = self._auto_create_target(
                        zone_id, src_result, src_kw, tgt_kw,
                        link_type, hydro_adapter,
                    )
                    if new_result and not new_result.skipped:
                        zone_results[new_result.measure_name] = new_result

                        # 建立联动关系
                        link_line = self._compute_link_line(
                            src_result, new_result, link_type)
                        if src_result.linked_to is None:
                            src_result.linked_to = []
                        src_result.linked_to.append(new_result.measure_name)
                        if link_line:
                            if src_result.linkage_lines is None:
                                src_result.linkage_lines = []
                            src_result.linkage_lines.append(link_line)

                        targets.append((new_result.measure_name, new_result))
                        logger.info(
                            f"Linkage auto-created: [{zone_id}] "
                            f"{src_name} → {new_result.measure_name}"
                        )

    def _auto_create_target(
        self,
        zone_id: str,
        src_result: PlacementResult,
        src_kw: str, tgt_kw: str,
        link_type: LinkageType,
        hydro_adapter: Any,
    ) -> Optional[PlacementResult]:
        """自动创建联动目标措施。"""
        result = PlacementResult(
            measure_name=tgt_kw,
            zone_id=zone_id,
            measure_type=MeasureType.POINT,
            strategy=Strategy.POINT_AT,
        )

        src_anchor = self._get_anchor(src_result)

        if link_type == LinkageType.DOWNSTREAM:
            # 下游: 在源末端偏下游方向
            end_pt = self._get_downstream_end(src_result)
            if end_pt:
                result.points = [end_pt]
                result.label_anchor = end_pt
            else:
                # 使用水文适配器的最低点
                if hydro_adapter:
                    zone = self._model.get_zone(zone_id)
                    if zone:
                        low = hydro_adapter.get_lowest_point_in_zone(zone)
                        if low:
                            result.points = [low]
                            result.label_anchor = low
                            return result
                # 回退: 源锚点下游偏移
                result.points = [(src_anchor[0] + 10, src_anchor[1] - 10)]
                result.label_anchor = result.points[0]

        elif link_type == LinkageType.ADJACENT:
            # 紧邻: 源锚点旁5m
            result.points = [(src_anchor[0] + 5, src_anchor[1])]
            result.label_anchor = result.points[0]

        elif link_type == LinkageType.PERIMETER:
            # 围绕: 在源措施周围 (如果源是面)
            if src_result.polygon and len(src_result.polygon) >= 3:
                # 围绕外缘偏移2m
                expanded = scale_polygon(src_result.polygon, 1.05)
                result.measure_type = MeasureType.LINE
                result.strategy = Strategy.BOUNDARY_FOLLOW
                result.polyline = expanded + [expanded[0]]
                result.label_anchor = polygon_centroid(expanded)
            else:
                result.points = [(src_anchor[0], src_anchor[1] - 5)]
                result.label_anchor = result.points[0]

        else:
            result.points = [(src_anchor[0] - 5, src_anchor[1])]
            result.label_anchor = result.points[0]

        return result

    @staticmethod
    def _get_anchor(result: PlacementResult) -> Tuple[float, float]:
        """获取措施锚点。"""
        if result.label_anchor:
            return result.label_anchor
        if result.points:
            return result.points[0]
        if result.polygon:
            return polygon_centroid(result.polygon)
        if result.polyline:
            mid = len(result.polyline) // 2
            return result.polyline[mid]
        return (0.0, 0.0)

    @staticmethod
    def _get_downstream_end(result: PlacementResult) -> Optional[Tuple[float, float]]:
        """获取措施下游端 (排水沟末端)。多段线时选最下游端点。"""
        endpoints = []
        if result.polylines:
            for pl in result.polylines:
                if len(pl) >= 2:
                    endpoints.append(pl[-1])
                    endpoints.append(pl[0])
        elif result.polyline and len(result.polyline) >= 2:
            endpoints.append(result.polyline[-1])
            endpoints.append(result.polyline[0])
        if not endpoints:
            return None
        # 选 y 值最小的 (下游, CAD 坐标系通常 y 向上)
        return min(endpoints, key=lambda p: p[1])

    @staticmethod
    def _compute_link_line(
        src: PlacementResult, tgt: PlacementResult,
        link_type: LinkageType,
    ) -> Optional[List[Tuple[float, float]]]:
        """计算连接线几何。"""
        src_pt = LinkageResolver._get_anchor(src)
        tgt_pt = LinkageResolver._get_anchor(tgt)

        if link_type == LinkageType.DOWNSTREAM:
            # 下游方向: 源末端→目标
            src_end = LinkageResolver._get_downstream_end(src)
            if src_end:
                return [src_end, tgt_pt]
            return [src_pt, tgt_pt]

        elif link_type == LinkageType.UPSTREAM:
            return [tgt_pt, src_pt]

        elif link_type == LinkageType.ADJACENT:
            return [src_pt, tgt_pt]

        elif link_type == LinkageType.PERIMETER:
            # 围绕不需要连接线
            return None

        return [src_pt, tgt_pt]
