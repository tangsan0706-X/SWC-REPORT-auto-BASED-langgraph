"""PlacementEngine v2 演示 — 基于 CAD 底图生成全局措施规划图。

完整链路:
  1. parse_dxf_geometry → CadGeometry (CAD 底图)
  2. CadFeatureAnalyzer → CadSiteFeatures (红线/建筑/道路)
  3. SiteModelBuilder → SiteModel (融合场景模型)
  4. PlacementEngine v2 (专用布置+联动+碰撞)
  5. MeasureMapRenderer (CAD底图 + 彩色措施叠加)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── 配置 ──
BASE_DIR = Path(__file__).resolve().parent.parent
DXF_PATH = BASE_DIR / "data" / "output" / "cad_dxf" / "20221215博雅园总图（原坐标）.dxf"
OUTPUT_DIR = BASE_DIR / "data" / "output" / "placement_v2_demo"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not DXF_PATH.exists():
        print(f"错误: DXF 文件不存在: {DXF_PATH}")
        return

    print(f"DXF 文件: {DXF_PATH.name}")
    print(f"输出目录: {OUTPUT_DIR}")
    print()

    # ═══════════════════════════════════════════════════════════
    # Step 1: 解析 DXF → CadGeometry
    # ═══════════════════════════════════════════════════════════
    print("=" * 60)
    print("Step 1: 解析 DXF 几何")
    t0 = time.time()

    from src.cad_base_renderer import parse_dxf_geometry
    cad_geometry = parse_dxf_geometry(DXF_PATH)

    if cad_geometry is None:
        print("错误: DXF 解析失败")
        return

    print(f"  实体数: {len(cad_geometry.entities)}")
    print(f"  边界数: {len(cad_geometry.boundaries)}")
    print(f"  bounds: {tuple(round(b, 1) for b in cad_geometry.bounds)}")
    print(f"  content_bounds: {tuple(round(b, 1) for b in cad_geometry.content_bounds)}")
    print(f"  耗时: {time.time() - t0:.2f}s")
    print()

    # ═══════════════════════════════════════════════════════════
    # Step 2: CAD 特征分析 → CadSiteFeatures
    # ═══════════════════════════════════════════════════════════
    print("=" * 60)
    print("Step 2: CAD 特征分析")
    t1 = time.time()

    from src.cad_feature_analyzer import CadFeatureAnalyzer
    analyzer = CadFeatureAnalyzer(cad_geometry, spatial_layout=None)
    cad_site_features = analyzer.analyze()

    boundary = getattr(cad_site_features, 'boundary_polyline', [])
    buildings = getattr(cad_site_features, 'building_footprints', [])
    roads = getattr(cad_site_features, 'road_edges', [])
    zones_cad = getattr(cad_site_features, 'zone_polygons', {})
    cluster_b = getattr(cad_site_features, 'cluster_bounds', None)

    print(f"  红线点数: {len(boundary)}")
    print(f"  建筑轮廓: {len(buildings)}")
    print(f"  道路边线: {len(roads)}")
    print(f"  CAD分区: {list(zones_cad.keys()) if zones_cad else '无'}")
    print(f"  聚类边界: {tuple(round(b, 1) for b in cluster_b) if cluster_b else '无'}")
    print(f"  耗时: {time.time() - t1:.2f}s")
    print()

    # ═══════════════════════════════════════════════════════════
    # Step 3: SiteModel 融合构建
    # ═══════════════════════════════════════════════════════════
    print("=" * 60)
    print("Step 3: SiteModel 构建")
    t2 = time.time()

    from src.site_model import SiteModelBuilder
    builder = SiteModelBuilder()
    builder.from_ezdxf(cad_geometry, cad_site_features)
    # 可以补充 meta 信息
    builder.from_meta({
        "project_name": "金石博雅园",
        "total_area_hm2": 8.24,
    })
    site_model = builder.build()

    print(f"  边界: {len(site_model.boundary.polyline) if site_model.boundary else 0} 点")
    print(f"  分区: {list(site_model.zones.keys())}")
    print(f"  全局POI: {len(site_model.global_pois)}")
    terrain = site_model.terrain
    if terrain:
        print(f"  地形: 坡向={terrain.slope_direction}, "
              f"坡度={terrain.avg_slope_pct}%, "
              f"标高={terrain.elevation_range}")
    print(f"  耗时: {time.time() - t2:.2f}s")
    print()

    # ═══════════════════════════════════════════════════════════
    # Step 4: 定义分区 + 措施 (项目数据)
    # ═══════════════════════════════════════════════════════════
    zones = [
        {"name": "建(构)筑物区", "area_hm2": 3.67, "area_m2": 36700},
        {"name": "道路广场区", "area_hm2": 2.10, "area_m2": 21000},
        {"name": "绿化工程区", "area_hm2": 1.17, "area_m2": 11700},
        {"name": "施工生产生活区", "area_hm2": 0.85, "area_m2": 8500},
        {"name": "临时堆土区", "area_hm2": 0.45, "area_m2": 4500},
    ]

    measures = [
        # 工程措施 - 线状
        {"措施名称": "排水沟C20(40×40)", "分区": "建(构)筑物区",
         "类型": "工程措施", "单位": "m", "数量": 230},
        {"措施名称": "排水沟C20(60×60)", "分区": "道路广场区",
         "类型": "工程措施", "单位": "m", "数量": 180},
        {"措施名称": "截水沟C20(30×30)", "分区": "绿化工程区",
         "类型": "工程措施", "单位": "m", "数量": 150},
        {"措施名称": "截水沟C20(40×40)", "分区": "施工生产生活区",
         "类型": "工程措施", "单位": "m", "数量": 120},
        # 工程措施 - 点状
        {"措施名称": "沉砂池(2×2×1.5m)", "分区": "建(构)筑物区",
         "类型": "工程措施", "单位": "座", "数量": 3},
        {"措施名称": "沉砂池(3×3×2m)", "分区": "道路广场区",
         "类型": "工程措施", "单位": "座", "数量": 2},
        {"措施名称": "洗车平台", "分区": "施工生产生活区",
         "类型": "工程措施", "单位": "台", "数量": 1},
        {"措施名称": "雨水收集池", "分区": "绿化工程区",
         "类型": "工程措施", "单位": "座", "数量": 1},
        # 植物措施
        {"措施名称": "综合绿化(乔灌草)", "分区": "建(构)筑物区",
         "类型": "植物措施", "单位": "m²", "数量": 8000},
        {"措施名称": "行道树(香樟)", "分区": "道路广场区",
         "类型": "植物措施", "单位": "株", "数量": 60},
        # 临时措施
        {"措施名称": "防尘网苫盖", "分区": "临时堆土区",
         "类型": "临时措施", "单位": "m²", "数量": 3000},
        {"措施名称": "临时排水沟(土质)", "分区": "施工生产生活区",
         "类型": "临时措施", "单位": "m", "数量": 200},
        {"措施名称": "施工围挡(彩钢板)", "分区": "建(构)筑物区",
         "类型": "临时措施", "单位": "m", "数量": 350},
        {"措施名称": "监测点位", "分区": "建(构)筑物区",
         "类型": "临时措施", "单位": "处", "数量": 5},
    ]

    print(f"分区数: {len(zones)}")
    print(f"措施数: {len(measures)}")
    print()

    # ═══════════════════════════════════════════════════════════
    # Step 5: PlacementEngine v2
    # ═══════════════════════════════════════════════════════════
    print("=" * 60)
    print("Step 5: PlacementEngine v2 布置")
    t3 = time.time()

    from src.placement import PlacementEngine
    engine = PlacementEngine(site_model)
    print(f"  水文Tier: {engine._hydro.tier if engine._hydro else 'None'}")

    results = engine.resolve_all(measures)
    adj = engine.optimize_batch()
    summary = engine.get_placement_summary()

    print(f"  布置耗时: {time.time() - t3:.3f}s")
    print(f"  碰撞优化: {adj} 次调整")
    print()
    print(summary)
    print()

    # ═══════════════════════════════════════════════════════════
    # Step 6: MeasureMapRenderer (CAD底图 + 措施叠加)
    # ═══════════════════════════════════════════════════════════
    print("=" * 60)
    print("Step 6: 渲染措施图 (CAD底图)")
    t4 = time.time()

    from src.measure_map import MeasureMapRenderer
    renderer = MeasureMapRenderer(
        zones=zones,
        measures=measures,
        output_dir=OUTPUT_DIR,
        cad_geometry=cad_geometry,
        cad_dxf_path=str(DXF_PATH),
        cad_site_features=cad_site_features,
        placement_engine=engine,
    )
    result = renderer.render_all()
    elapsed = time.time() - t4

    print(f"\n渲染耗时: {elapsed:.2f}s")
    print(f"生成 {len(result)} 张图:")
    for name, path in sorted(result.items()):
        size_kb = path.stat().st_size / 1024 if path.exists() else 0
        print(f"  {name}: {path.name} ({size_kb:.0f} KB)")

    total = time.time() - t0
    print(f"\n总耗时: {total:.2f}s")
    print(f"输出目录: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
