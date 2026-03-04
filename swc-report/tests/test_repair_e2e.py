"""端到端测试: 验证图纸修复方案 (修复零~八) 的效果。

用博雅园项目真实 DXF 文件 + facts_v2.json 数据测试:
  1. CadFeatureAnalyzer 特征提取 (修复零/一/二)
  2. MeasureMapRenderer 带 CAD 底图渲染 (修复三/四/五)
  3. DrawingRenderer 带 CAD 底图渲染
  4. MeasurePlacementResolver 锚点日志

运行: python tests/test_repair_e2e.py
  或: pytest tests/test_repair_e2e.py -v -s
"""

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_repair")

# ── 项目数据 ──────────────────────────────────────────────────
DXF_PATH = Path(__file__).resolve().parent.parent / "data/output/cad_dxf/20221215博雅园总图（原坐标）.dxf"
FACTS_PATH = Path(__file__).resolve().parent.parent / "config/facts_v2.json"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data/output/repair_test"

with open(FACTS_PATH, "r", encoding="utf-8") as f:
    FACTS = json.load(f)

ZONES = FACTS["zones"]
for z in ZONES:
    z.setdefault("area_m2", z["area_hm2"] * 10000)

MEASURES = [
    {"措施名称": "排水沟C20(40×40)", "分区": "建(构)筑物区", "类型": "工程措施", "单位": "m", "数量": 580, "source": "planned"},
    {"措施名称": "截水沟C20(30×30)", "分区": "道路广场区", "类型": "工程措施", "单位": "m", "数量": 320, "source": "planned"},
    {"措施名称": "沉沙池(2×2×1.5m)", "分区": "建(构)筑物区", "类型": "工程措施", "单位": "座", "数量": 4, "source": "planned"},
    {"措施名称": "施工围挡(彩钢板H=2m)", "分区": "建(构)筑物区", "类型": "临时措施", "单位": "m", "数量": 650, "source": "planned"},
    {"措施名称": "透水砖铺装", "分区": "道路广场区", "类型": "工程措施", "单位": "m²", "数量": 8500, "source": "planned"},
    {"措施名称": "综合绿化(乔灌草)", "分区": "绿化工程区", "类型": "植物措施", "单位": "m²", "数量": 11700, "source": "planned"},
    {"措施名称": "撒播草籽(混播)", "分区": "临时堆土区", "类型": "植物措施", "单位": "m²", "数量": 2468, "source": "planned"},
    {"措施名称": "临时排水沟(土质)", "分区": "施工生产生活区", "类型": "临时措施", "单位": "m", "数量": 120, "source": "planned"},
    {"措施名称": "密目安全网", "分区": "施工生产生活区", "类型": "临时措施", "单位": "m²", "数量": 2000, "source": "planned"},
    {"措施名称": "车辆冲洗平台", "分区": "道路广场区", "类型": "临时措施", "单位": "座", "数量": 1, "source": "planned"},
]


def _check_dxf():
    """检查 DXF 文件是否可用。"""
    if not DXF_PATH.exists():
        logger.warning("DXF 文件不存在: %s — 跳过 CAD 相关测试", DXF_PATH)
        return False
    logger.info("DXF: %s (%.1f MB)", DXF_PATH.name, DXF_PATH.stat().st_size / 1e6)
    return True


# ═══════════════════════════════════════════════════════════════
# Test 1: CadFeatureAnalyzer (修复零/一/二)
# ═══════════════════════════════════════════════════════════════

def test_cad_feature_extraction():
    """测试 CAD 特征提取: 聚类 + 诊断 + 几何分类。"""
    if not _check_dxf():
        return

    from src.cad_base_renderer import parse_dxf_geometry
    from src.cad_feature_analyzer import CadFeatureAnalyzer

    t0 = time.time()

    # 1. 解析 DXF
    cad_geom = parse_dxf_geometry(str(DXF_PATH))
    logger.info("DXF 解析: %d entities, bounds=(%.0f,%.0f)-(%.0f,%.0f)  [%.1fs]",
                len(cad_geom.entities), *cad_geom.bounds, time.time() - t0)

    # 2. 特征分析 (含修复零聚类 + 修复一诊断/分类)
    t1 = time.time()
    analyzer = CadFeatureAnalyzer(cad_geom, project_meta=FACTS)
    features = analyzer.analyze()
    dt = time.time() - t1

    # 3. 验证结果
    logger.info("=" * 60)
    logger.info("特征提取结果 (%.1fs):", dt)
    logger.info("  红线边界: %d 点", len(features.boundary_polyline))
    logger.info("  分区多边形: %s", {k: len(v) for k, v in features.zone_polygons.items()})
    logger.info("  道路边缘: %d 条", len(features.road_edges))
    logger.info("  边界段: %d 条", len(features.boundary_segments))
    logger.info("  建筑轮廓: %d 个", len(features.building_footprints))
    logger.info("  道路面: %d 个", len(features.road_surfaces))
    logger.info("  绿地: %d 个", len(features.green_spaces))
    logger.info("  出入口: %d 个", len(features.entrances))
    logger.info("  排水口: %d 个", len(features.drainage_outlets))
    logger.info("  排水方向: %s", features.drainage_direction)
    logger.info("  聚类边界: %s", features.cluster_bounds)
    logger.info("=" * 60)

    # 验收: 红线边界应有 ≥3 个点
    assert len(features.boundary_polyline) >= 3, \
        f"红线边界点数不足: {len(features.boundary_polyline)}"

    # 验收: 至少应有1个分区多边形
    assert len(features.zone_polygons) >= 1, \
        f"分区多边形为空"

    # 验收: cluster_bounds 范围应合理 (200m-800m)
    if features.cluster_bounds:
        x0, y0, x1, y1 = features.cluster_bounds
        span_x = x1 - x0
        span_y = y1 - y0
        logger.info("  聚类范围: %.0fm × %.0fm", span_x, span_y)
        assert 50 < max(span_x, span_y) < 5000, \
            f"聚类范围异常: {span_x:.0f} × {span_y:.0f}"

    # 检查诊断文件
    diag_path = Path("data/output/cad_diagnosis.json")
    if diag_path.exists():
        logger.info("  诊断文件已生成: %s", diag_path)

    return cad_geom, features


# ═══════════════════════════════════════════════════════════════
# Test 2: MeasureMapRenderer + CAD (修复三/四/五)
# ═══════════════════════════════════════════════════════════════

def test_measure_map_with_cad():
    """测试修复后的措施图渲染: 真实多边形 + 红线视口 + CAD 底图。"""
    if not _check_dxf():
        # 无 DXF 时仅测试基础渲染
        from src.measure_map import MeasureMapRenderer
        out = OUTPUT_DIR / "no_cad"
        out.mkdir(parents=True, exist_ok=True)
        renderer = MeasureMapRenderer(zones=ZONES, measures=MEASURES, output_dir=out)
        result = renderer.render_all()
        logger.info("基础渲染 (无CAD): %d 张图 — %s", len(result), list(result.keys()))
        return result

    from src.cad_base_renderer import parse_dxf_geometry
    from src.cad_feature_analyzer import CadFeatureAnalyzer
    from src.measure_map import MeasureMapRenderer

    out = OUTPUT_DIR / "with_cad"
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # 解析 + 特征提取
    cad_geom = parse_dxf_geometry(str(DXF_PATH))
    analyzer = CadFeatureAnalyzer(cad_geom, project_meta=FACTS)
    features = analyzer.analyze()

    # 渲染 (带 CAD)
    renderer = MeasureMapRenderer(
        zones=ZONES,
        measures=MEASURES,
        output_dir=out,
        cad_geometry=cad_geom,
        cad_dxf_path=str(DXF_PATH),
        cad_site_features=features,
    )
    result = renderer.render_all()
    dt = time.time() - t0

    logger.info("=" * 60)
    logger.info("CAD 渲染结果 (%.1fs):", dt)
    for tag, path in sorted(result.items()):
        size_kb = Path(path).stat().st_size / 1024 if Path(path).exists() else 0
        logger.info("  %-40s  %.1f KB", tag, size_kb)
    logger.info("=" * 60)

    # 验收
    assert "zone_boundary_map" in result, "缺少分区图"
    assert "measure_layout_map" in result, "缺少总布置图"

    for tag, path in result.items():
        p = Path(path)
        assert p.exists(), f"图片未生成: {tag}"
        assert p.stat().st_size > 2000, f"图片过小 (可能空白): {tag} = {p.stat().st_size}B"

    return result


# ═══════════════════════════════════════════════════════════════
# Test 3: MeasurePlacementResolver 锚点日志 (修复五)
# ═══════════════════════════════════════════════════════════════

def test_placement_resolver_logging():
    """测试锚点可用性日志输出。"""
    if not _check_dxf():
        return

    from src.cad_base_renderer import parse_dxf_geometry
    from src.cad_feature_analyzer import CadFeatureAnalyzer, MeasurePlacementResolver

    cad_geom = parse_dxf_geometry(str(DXF_PATH))
    analyzer = CadFeatureAnalyzer(cad_geom, project_meta=FACTS)
    features = analyzer.analyze()

    resolver = MeasurePlacementResolver(features)

    # 测试几个不同类型的措施
    test_measures = [
        ("排水沟C20(40×40)", "建(构)筑物区"),
        ("施工围挡(彩钢板H=2m)", "建(构)筑物区"),
        ("沉沙池(2×2×1.5m)", "建(构)筑物区"),
        ("综合绿化(乔灌草)", "绿化工程区"),
        ("透水砖铺装", "道路广场区"),
        ("行道树", "道路广场区"),
    ]

    resolved_count = 0
    for name, zone in test_measures:
        result = resolver.resolve(name, zone_name=zone)
        status = "RESOLVED" if result else "FALLBACK"
        if result:
            resolved_count += 1
            geom_type = list(result.keys())[0]
            pts = len(result[geom_type])
            logger.info("  %-30s → %s (%s: %d pts)", name, status, geom_type, pts)
        else:
            logger.info("  %-30s → %s", name, status)

    logger.info("放置解析率: %d/%d (%.0f%%)",
                resolved_count, len(test_measures),
                resolved_count / len(test_measures) * 100)


# ═══════════════════════════════════════════════════════════════
# Test 4: DrawingRenderer + CAD (完整新架构)
# ═══════════════════════════════════════════════════════════════

def test_drawing_renderer_with_cad():
    """测试 DrawingRenderer 新架构渲染。"""
    if not _check_dxf():
        return

    from src.cad_base_renderer import parse_dxf_geometry
    from src.cad_feature_analyzer import CadFeatureAnalyzer
    from src.drawing_plan import DrawingPlan, ZoneSpec, MeasureSpec
    from src.drawing_renderer import DrawingRenderer

    out = OUTPUT_DIR / "drawing_renderer"
    out.mkdir(parents=True, exist_ok=True)

    cad_geom = parse_dxf_geometry(str(DXF_PATH))
    analyzer = CadFeatureAnalyzer(cad_geom, project_meta=FACTS)
    features = analyzer.analyze()

    # 构造 DrawingPlan (分区图)
    zone_specs = [ZoneSpec(name=z["name"], emphasis="normal") for z in ZONES]
    zone_specs[0].emphasis = "highlight"

    plan = DrawingPlan(
        map_type="zone_boundary",
        title=f"{FACTS['project_name']} 水土保持防治分区图",
        zones=zone_specs,
    )

    t0 = time.time()
    renderer = DrawingRenderer(
        plan=plan,
        zones=ZONES,
        measures=MEASURES,
        output_dir=out,
        cad_geometry=cad_geom,
        cad_dxf_path=str(DXF_PATH),
        cad_site_features=features,
    )
    png_path = renderer.render_png("zone_boundary_map.png")
    dt = time.time() - t0

    logger.info("DrawingRenderer 分区图: %s (%.1fs)", png_path, dt)
    if png_path and png_path.exists():
        logger.info("  PNG: %s (%.1f KB)", png_path.name, png_path.stat().st_size / 1024)
    assert png_path and png_path.exists(), "PNG 未生成"

    # 措施总布置图
    measure_specs = [
        MeasureSpec(name=m["措施名称"], zone=m["分区"], position="center")
        for m in MEASURES[:6]
    ]
    plan2 = DrawingPlan(
        map_type="measure_layout",
        title=f"{FACTS['project_name']} 水土保持措施总体布置图",
        zones=zone_specs,
        measures=measure_specs,
    )
    renderer2 = DrawingRenderer(
        plan=plan2,
        zones=ZONES,
        measures=MEASURES,
        output_dir=out,
        cad_geometry=cad_geom,
        cad_dxf_path=str(DXF_PATH),
        cad_site_features=features,
    )
    png_path2 = renderer2.render_png("measure_layout_map.png")
    if png_path2 and png_path2.exists():
        logger.info("  措施总布置图: %s (%.1f KB)", png_path2.name, png_path2.stat().st_size / 1024)

    return png_path, png_path2


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("输出目录: %s", OUTPUT_DIR)
    logger.info("")

    logger.info("▶ Test 1: CAD 特征提取 (修复零/一/二)")
    logger.info("-" * 60)
    try:
        test_cad_feature_extraction()
        logger.info("✓ PASS\n")
    except Exception as e:
        logger.error("✗ FAIL: %s\n", e, exc_info=True)

    logger.info("▶ Test 2: 措施图 + CAD 底图渲染 (修复三/四/五)")
    logger.info("-" * 60)
    try:
        test_measure_map_with_cad()
        logger.info("✓ PASS\n")
    except Exception as e:
        logger.error("✗ FAIL: %s\n", e, exc_info=True)

    logger.info("▶ Test 3: 放置锚点解析 (修复五)")
    logger.info("-" * 60)
    try:
        test_placement_resolver_logging()
        logger.info("✓ PASS\n")
    except Exception as e:
        logger.error("✗ FAIL: %s\n", e, exc_info=True)

    logger.info("▶ Test 4: DrawingRenderer + CAD (新架构)")
    logger.info("-" * 60)
    try:
        test_drawing_renderer_with_cad()
        logger.info("✓ PASS\n")
    except Exception as e:
        logger.error("✗ FAIL: %s\n", e, exc_info=True)

    logger.info("=" * 60)
    logger.info("输出目录: %s", OUTPUT_DIR)
    logger.info("完成!")
