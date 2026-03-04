"""几何布置引擎 — 向后兼容 shim。

所有实现已迁移到 src/placement/ 包。
本文件仅 re-export 公开名称，确保现有导入不受影响:
    from src.placement_engine import PlacementEngine
    from src.placement_engine import classify_measure, MeasureType, ...
"""

# Re-export everything from the new package
from src.placement import (  # noqa: F401
    PlacementEngine,
    PlacementResult,
    MeasureType,
    Strategy,
    LinkageType,
    classify_measure,
    route_strategy,
    GeometryClipper,
    CollisionResolver,
    CollisionResolverV2,
    LinkageResolver,
    HydroAdapter,
)

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
]
