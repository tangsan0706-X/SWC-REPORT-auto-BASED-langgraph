"""措施布置引擎 v2 — 包导出。

公开 API:
  - PlacementEngine      (核心引擎)
  - PlacementResult      (布置结果)
  - MeasureType, Strategy (枚举)
  - classify_measure, route_strategy (分类/路由)
  - GeometryClipper      (通用几何生成)
  - CollisionResolver, CollisionResolverV2 (碰撞检测)
  - LinkageResolver      (联动解析)
  - HydroAdapter         (水文适配)
"""

from .types import (
    MeasureType,
    Strategy,
    LinkageType,
    PlacementResult,
    DISTANCE_RULES,
    EXCLUSION_RULES,
    DITCH_SIZE_TABLE,
    BASIN_SIZE_TABLE,
    LINKAGE_RULES,
)
from .classifier import classify_measure, route_strategy
from .placers import GeometryClipper, lookup_placer, PLACER_REGISTRY
from .collision import CollisionResolver, CollisionResolverV2
from .linkage import LinkageResolver
from .hydro_adapter import HydroAdapter
from .engine import PlacementEngine

__all__ = [
    "PlacementEngine",
    "PlacementResult",
    "MeasureType",
    "Strategy",
    "LinkageType",
    "classify_measure",
    "route_strategy",
    "GeometryClipper",
    "CollisionResolver",
    "CollisionResolverV2",
    "LinkageResolver",
    "HydroAdapter",
    "lookup_placer",
    "PLACER_REGISTRY",
    "DISTANCE_RULES",
    "EXCLUSION_RULES",
    "DITCH_SIZE_TABLE",
    "BASIN_SIZE_TABLE",
    "LINKAGE_RULES",
]
