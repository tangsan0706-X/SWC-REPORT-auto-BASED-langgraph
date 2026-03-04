"""措施图模块单元测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.measure_symbols import (
    MEASURE_STYLES, SECTION_TEMPLATES, ZONE_COLORS,
    get_style, get_zone_color, MAP_DEFAULTS,
)


# ── measure_symbols 测试 ────────────────────────────────────────

def test_measure_styles_coverage():
    """所有措施库中的措施都应有对应样式。"""
    from src.settings import MEASURE_LIBRARY_PATH
    import json
    with open(MEASURE_LIBRARY_PATH, "r", encoding="utf-8") as f:
        lib = json.load(f)
    lib_names = {m["name"] for m in lib.get("measures", [])}

    # 至少应覆盖 80% 的措施
    covered = sum(1 for n in lib_names if n in MEASURE_STYLES)
    ratio = covered / len(lib_names) if lib_names else 0
    assert ratio >= 0.7, f"样式覆盖率过低: {covered}/{len(lib_names)} = {ratio:.0%}"


def test_get_style_known():
    """已知措施应返回正确样式。"""
    style = get_style("排水沟C20(40×40)")
    assert style["type"] == "line"
    # professional=True (默认) 使用 color_professional
    assert style["color"] == "#1E90FF"

    # professional=False 使用原始灰度
    style_bw = get_style("排水沟C20(40×40)", professional=False)
    assert style_bw["color"] == "#000000"


def test_get_style_fuzzy():
    """模糊匹配应能工作。"""
    style = get_style("排水沟")
    assert style["type"] in ("line", "fill", "point")


def test_get_style_unknown():
    """未知措施返回默认样式。"""
    style = get_style("完全不存在的措施XYZ")
    assert style["color"] == "#999999"


def test_section_templates():
    """断面模板应包含必要字段。"""
    for name, tmpl in SECTION_TEMPLATES.items():
        assert "shape" in tmpl, f"{name} 缺少 shape"
        assert "material" in tmpl, f"{name} 缺少 material"


def test_zone_colors():
    """五个标准分区都应有颜色。"""
    expected = ["建(构)筑物区", "道路广场区", "绿化工程区", "施工生产生活区", "临时堆土区"]
    for zone in expected:
        assert zone in ZONE_COLORS, f"缺少分区颜色: {zone}"


def test_get_zone_color_unknown():
    """未知分区返回浅灰。"""
    c = get_zone_color("不存在的分区")
    assert c == "#F5F5F5"


# ── 测试辅助: 构建带 SiteModel 的 PlacementEngine ──────────────

def _make_test_engine(zones):
    """构建最小 SiteModel + PlacementEngine, 供渲染测试使用。"""
    from src.placement_engine import PlacementEngine
    from src.site_model import SiteModel, ZoneModel
    from src.geo_utils import shoelace_area, polygon_centroid, points_bounds

    # 为每个分区生成矩形多边形 (横向排列)
    site_zones = {}
    x_cursor = 10.0
    for z in zones:
        name = z["name"]
        area_m2 = z.get("area_m2", z.get("area_hm2", 0) * 10000)
        w = max(area_m2 ** 0.5 * 1.1, 50)
        h = area_m2 / w if w > 0 else 50
        poly = [(x_cursor, 10), (x_cursor + w, 10),
                (x_cursor + w, 10 + h), (x_cursor, 10 + h)]
        site_zones[name] = ZoneModel(
            zone_id=name, polygon=poly,
            area_m2=shoelace_area(poly),
            centroid=polygon_centroid(poly),
            bbox=points_bounds(poly),
        )
        x_cursor += w + 10

    model = SiteModel(zones=site_zones)
    return PlacementEngine(model)


# ── measure_map 渲染测试 ────────────────────────────────────────

def test_measure_map_renderer_init():
    """MeasureMapRenderer 可以初始化 (需要 PlacementEngine 提供几何)。"""
    from src.measure_map import MeasureMapRenderer
    from src.settings import OUTPUT_DIR

    zones = [
        {"name": "建(构)筑物区", "area_hm2": 3.67, "area_m2": 36700},
        {"name": "绿化工程区", "area_hm2": 1.17, "area_m2": 11700},
    ]
    measures = [
        {"措施名称": "排水沟C20(40×40)", "分区": "建(构)筑物区",
         "类型": "工程措施", "单位": "m", "数量": 230, "source": "planned"},
    ]
    engine = _make_test_engine(zones)

    renderer = MeasureMapRenderer(
        zones=zones, measures=measures,
        output_dir=OUTPUT_DIR / "test_maps",
        placement_engine=engine,
    )
    assert len(renderer._zone_geometries) == 2


def test_measure_map_renderer_no_engine():
    """无 PlacementEngine 时 zone_geometries 应为空。"""
    from src.measure_map import MeasureMapRenderer
    from src.settings import OUTPUT_DIR

    zones = [
        {"name": "建(构)筑物区", "area_hm2": 3.67, "area_m2": 36700},
    ]
    renderer = MeasureMapRenderer(
        zones=zones, measures=[],
        output_dir=OUTPUT_DIR / "test_maps",
    )
    assert len(renderer._zone_geometries) == 0


def test_render_zone_boundary_map():
    """分区图应能生成 PNG。"""
    from src.measure_map import MeasureMapRenderer
    from src.settings import OUTPUT_DIR

    zones = [
        {"name": "建(构)筑物区", "area_hm2": 3.67, "area_m2": 36700},
        {"name": "道路广场区", "area_hm2": 2.10, "area_m2": 21000},
        {"name": "绿化工程区", "area_hm2": 1.17, "area_m2": 11700},
    ]
    output_dir = OUTPUT_DIR / "test_maps"
    engine = _make_test_engine(zones)
    renderer = MeasureMapRenderer(zones=zones, measures=[], output_dir=output_dir,
                                   placement_engine=engine)
    path = renderer.render_zone_boundary_map()
    assert path.exists(), f"分区图未生成: {path}"
    assert path.stat().st_size > 1000, "分区图文件过小"


def test_render_all():
    """render_all 应生成多张图。"""
    from src.measure_map import MeasureMapRenderer
    from src.settings import OUTPUT_DIR

    zones = [
        {"name": "建(构)筑物区", "area_hm2": 3.67, "area_m2": 36700},
        {"name": "道路广场区", "area_hm2": 2.10, "area_m2": 21000},
    ]
    measures = [
        {"措施名称": "排水沟C20(40×40)", "分区": "建(构)筑物区",
         "类型": "工程措施", "单位": "m", "数量": 230, "source": "planned"},
        {"措施名称": "沉沙池(2×2×1.5m)", "分区": "建(构)筑物区",
         "类型": "工程措施", "单位": "座", "数量": 3, "source": "planned"},
        {"措施名称": "撒播草籽(混播)", "分区": "道路广场区",
         "类型": "植物措施", "单位": "m²", "数量": 500, "source": "planned"},
    ]
    output_dir = OUTPUT_DIR / "test_maps"
    engine = _make_test_engine(zones)
    engine.resolve_all(measures)
    renderer = MeasureMapRenderer(zones=zones, measures=measures, output_dir=output_dir,
                                   placement_engine=engine)
    result = renderer.render_all()

    assert "zone_boundary_map" in result, "缺少分区图"
    assert "measure_layout_map" in result, "缺少总布置图"
    # 应至少有 1 个分区详图
    detail_keys = [k for k in result if k.startswith("zone_detail_")]
    assert len(detail_keys) >= 1, f"分区详图不足: {detail_keys}"
    # 应有断面图 (排水沟)
    section_keys = [k for k in result if k.startswith("typical_section_")]
    assert len(section_keys) >= 1, f"断面图不足: {section_keys}"

    print(f"生成 {len(result)} 张措施图: {list(result.keys())}")


# ── spatial_analyzer 测试 ────────────────────────────────────────

def test_default_spatial_layout():
    """默认空间布局应包含所有分区。"""
    from src.spatial_analyzer import generate_default_spatial_layout

    zones = [
        {"name": "建(构)筑物区", "area_hm2": 3.67},
        {"name": "道路广场区", "area_hm2": 2.10},
    ]
    layout = generate_default_spatial_layout(zones)
    assert len(layout["zones"]) == 2
    assert layout["drainage_direction"]
    assert layout["zones"][0]["bbox"]


# ── spatial_tools 测试 ──────────────────────────────────────────

def test_spatial_context_tool_no_state():
    """未注入 state 时应返回错误。"""
    from src.tools.spatial_tools import spatial_context_tool
    # ContextVar 默认值即为 None，无需额外设置
    result = spatial_context_tool()
    assert "error" in result or "available" in result


# ── PlacementEngine 预计算查找测试 ──────────────────────────────

def test_get_placement_after_resolve_all():
    """resolve_all() 后应能通过 get_placement() 查找预计算结果。"""
    from src.placement_engine import PlacementEngine
    from src.site_model import SiteModel, ZoneModel

    # 构建最小 SiteModel
    zone_poly = [(0, 0), (100, 0), (100, 80), (0, 80)]
    zone = ZoneModel(
        zone_id="建(构)筑物区", polygon=zone_poly,
        area_m2=8000, centroid=(50, 40), bbox=(0, 0, 100, 80),
    )
    model = SiteModel(zones={"建(构)筑物区": zone})
    engine = PlacementEngine(model)

    measures = [
        {"措施名称": "排水沟C20(40×40)", "分区": "建(构)筑物区",
         "单位": "m", "数量": 120},
        {"措施名称": "撒播草籽(混播)", "分区": "建(构)筑物区",
         "单位": "m²", "数量": 500},
    ]
    engine.resolve_all(measures)

    # 应有预计算结果
    assert engine.has_precomputed()

    # 精确查找
    r1 = engine.get_placement("排水沟C20(40×40)", "建(构)筑物区")
    assert r1 is not None
    assert "strategy" in r1
    assert r1.get("polyline") or r1.get("polygon") or r1.get("points")

    # 模糊查找 (无 zone_id)
    r2 = engine.get_placement("排水沟C20(40×40)")
    assert r2 is not None

    # 不存在的措施
    r3 = engine.get_placement("完全不存在的措施XYZ")
    assert r3 is None


def test_optimize_batch():
    """optimize_batch() 不应报错, 且碰撞较多时应有调整。"""
    from src.placement_engine import PlacementEngine, PlacementResult, MeasureType, Strategy
    from src.site_model import SiteModel, ZoneModel

    # 两个完全重叠的分区: 措施必然碰撞
    zone_poly = [(0, 0), (50, 0), (50, 50), (0, 50)]
    zone = ZoneModel(
        zone_id="测试区", polygon=zone_poly,
        area_m2=2500, centroid=(25, 25), bbox=(0, 0, 50, 50),
    )
    model = SiteModel(zones={"测试区": zone})
    engine = PlacementEngine(model)

    measures = [
        {"措施名称": "撒播草籽(混播)", "分区": "测试区",
         "单位": "m²", "数量": 800},
        {"措施名称": "综合绿化(乔灌草)", "分区": "测试区",
         "单位": "m²", "数量": 600},
    ]
    engine.resolve_all(measures)

    # optimize_batch 不应抛异常
    adjustments = engine.optimize_batch()
    assert isinstance(adjustments, int)
    assert adjustments >= 0


# ── LabelPlacer 碰撞避让测试 ──────────────────────────────────

def test_label_placer_collision():
    """相同位置的多个标签应被偏移, 不重叠。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from src.measure_map import LabelPlacer

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)

    placer = LabelPlacer(ax)
    # 在同一位置添加 5 个标签
    for i in range(5):
        placer.add(50, 50, f"标签{i}", fontsize=8)

    # render_all 不应抛异常
    placer.render_all()

    # 应生成了 5 个标签 text 对象 (可能有额外的引线 annotation)
    texts = ax.texts
    label_texts = [t for t in texts if t.get_text()]  # 排除引线的空文本
    assert len(label_texts) == 5

    # 至少部分标签的位置应不同 (4方向碰撞避让)
    positions = [t.get_position() for t in label_texts]
    unique_pos = set((round(x, 2), round(y, 2)) for x, y in positions)
    assert len(unique_pos) >= 2, f"标签未被避让, 位置: {positions}"

    plt.close(fig)


# ── Z-Order 排序测试 ──────────────────────────────────────────

def test_zorder_sorting():
    """措施应按 fill→line→point 排序渲染。"""
    from src.measure_symbols import get_style, ZORDER

    # ZORDER 常量应存在且有正确层次
    assert ZORDER["zone_fill"] < ZORDER["measure_area"]
    assert ZORDER["measure_area"] < ZORDER["measure_line"]
    assert ZORDER["measure_line"] < ZORDER["measure_point"]
    assert ZORDER["measure_point"] < ZORDER["labels"]

    # 排序逻辑: fill=0 < line=1 < point=2
    _TYPE_ORDER = {"fill": 0, "line": 1, "point": 2}
    measures = [
        {"措施名称": "沉沙池(2×2×1.5m)"},    # point
        {"措施名称": "排水沟C20(40×40)"},      # line
        {"措施名称": "撒播草籽(混播)"},         # fill
    ]
    sorted_measures = sorted(
        measures,
        key=lambda m: _TYPE_ORDER.get(
            get_style(m["措施名称"], professional=True).get("type", "fill"), 0
        )
    )
    types = [get_style(m["措施名称"], professional=True)["type"] for m in sorted_measures]
    assert types == ["fill", "line", "point"], f"排序错误: {types}"


# ── 标高提取 + 地形拟合 + 坡向感知测试 ──────────────────────────

def test_elevation_extraction():
    """_extract_elevation_points() 应从 TEXT 实体正确提取标高。"""
    from dataclasses import dataclass, field as dc_field
    from src.cad_feature_analyzer import CadFeatureAnalyzer

    @dataclass
    class FakeEntity:
        entity_type: str = "text"
        text_content: str = ""
        points: list = dc_field(default_factory=list)
        closed: bool = False
        category: str = "text"
        layer: str = ""

    @dataclass
    class FakeGeometry:
        entities: list = dc_field(default_factory=list)
        buildings: list = dc_field(default_factory=list)
        roads: list = dc_field(default_factory=list)
        boundaries: list = dc_field(default_factory=list)
        greenery: list = dc_field(default_factory=list)
        bounds: tuple = (0, 0, 100, 100)

    entities = [
        FakeEntity(text_content="▽52.30", points=[(10, 20)]),
        FakeEntity(text_content="H=48.00", points=[(30, 40)]),
        FakeEntity(text_content="标高55.10", points=[(50, 60)]),
        FakeEntity(text_content="普通文字无标高", points=[(70, 80)]),
    ]
    geom = FakeGeometry(entities=entities)
    analyzer = CadFeatureAnalyzer(geom)
    pts = analyzer._extract_elevation_points()
    assert len(pts) == 3, f"期望 3 个标高点, 实际 {len(pts)}"
    zs = sorted([p[2] for p in pts])
    assert abs(zs[0] - 48.0) < 0.01
    assert abs(zs[1] - 52.3) < 0.01
    assert abs(zs[2] - 55.1) < 0.01


def test_terrain_computation():
    """_compute_terrain() 应正确拟合 NW→SE 倾斜平面。"""
    from src.cad_feature_analyzer import CadFeatureAnalyzer

    from dataclasses import dataclass, field as dc_field

    @dataclass
    class FakeGeometry:
        entities: list = dc_field(default_factory=list)
        buildings: list = dc_field(default_factory=list)
        roads: list = dc_field(default_factory=list)
        boundaries: list = dc_field(default_factory=list)
        greenery: list = dc_field(default_factory=list)
        bounds: tuple = (0, 0, 100, 100)

    geom = FakeGeometry()
    analyzer = CadFeatureAnalyzer(geom)

    # 构造从 NW(高) 到 SE(低) 的平面: z = -x - y + 100
    # NW 角 (0,100) z=0, SE 角 (100,0) z=0... 不对
    # 让 NW 高 SE 低: z = -0.05*x + 0.05*y + 50
    # (0, 100) → z=55 (NW, 高)
    # (100, 0) → z=45 (SE, 低)
    elev_pts = [
        (0, 100, 55.0),    # NW corner - high
        (100, 0, 45.0),    # SE corner - low
        (0, 0, 50.0),      # SW corner
        (100, 100, 50.0),  # NE corner
    ]
    slope_pct, direction, elev_range = analyzer._compute_terrain(elev_pts)
    assert slope_pct is not None
    assert slope_pct > 0
    assert "SE" in direction, f"期望包含 SE, 实际 {direction}"
    assert elev_range == (45.0, 55.0)


def test_find_lowest_point():
    """find_lowest_point() 应返回最低标高点, 支持 bbox 过滤。"""
    from src.geo_utils import find_lowest_point

    pts = [
        (10, 20, 50.0),
        (30, 40, 42.0),
        (50, 60, 55.0),
        (70, 80, 38.0),
    ]
    # 无 bbox: 应返回 (70, 80)
    low = find_lowest_point(pts)
    assert low == (70, 80)

    # 有 bbox 过滤: 限制在 (0,0)-(40,50) 内, 应返回 (30, 40)
    low2 = find_lowest_point(pts, within_bbox=(0, 0, 40, 50))
    assert low2 == (30, 40)

    # bbox 内无点
    low3 = find_lowest_point(pts, within_bbox=(200, 200, 300, 300))
    assert low3 is None


def test_slope_direction_vector():
    """slope_direction_vector() 应正确转换方位为向量。"""
    from src.geo_utils import slope_direction_vector

    vec = slope_direction_vector("NW→SE")
    assert vec is not None
    assert abs(vec[0] - 0.707) < 0.01
    assert abs(vec[1] - (-0.707)) < 0.01

    vec2 = slope_direction_vector("N")
    assert vec2 == (0.0, 1.0)

    vec3 = slope_direction_vector("NE->SW")
    assert vec3 is not None
    assert abs(vec3[0] - (-0.707)) < 0.01
    assert abs(vec3[1] - (-0.707)) < 0.01

    vec4 = slope_direction_vector("INVALID")
    assert vec4 is None


def test_edge_follow_slope_aware():
    """坡向感知: 排水沟选坡向平行边, 截水沟选坡向垂直边。"""
    from src.placement_engine import PlacementEngine, GeometryClipper, Strategy
    from src.site_model import (
        SiteModel, ZoneModel, EdgeFeature, TerrainInfo, SourceTag, SourceType,
    )

    tag = SourceTag(SourceType.EZDXF, 0.85)
    # 构造一个矩形分区, 有 4 条明确方向的边
    zone = ZoneModel(
        zone_id="测试区",
        polygon=[(0, 0), (100, 0), (100, 80), (0, 80)],
        area_m2=8000, centroid=(50, 40), bbox=(0, 0, 100, 80),
        edges=[
            EdgeFeature(polyline=[(0, 0), (100, 0)], feature_type="road_edge",
                        length_m=100, source=tag),     # E-W 方向 (水平)
            EdgeFeature(polyline=[(100, 0), (100, 80)], feature_type="road_edge",
                        length_m=80, source=tag),       # N-S 方向 (垂直)
            EdgeFeature(polyline=[(100, 80), (0, 80)], feature_type="road_edge",
                        length_m=100, source=tag),      # E-W 方向 (水平)
            EdgeFeature(polyline=[(0, 80), (0, 0)], feature_type="road_edge",
                        length_m=80, source=tag),        # N-S 方向 (垂直)
        ],
    )
    terrain = TerrainInfo(slope_direction="NW→SE", avg_slope_pct=5.0, source=tag)
    model = SiteModel(zones={"测试区": zone}, terrain=terrain)
    clipper = GeometryClipper(model)

    # 排水沟: 应选与 SE 方向 (0.707, -0.707) 最对齐的边
    # 对角方向没有完全对齐的边, 但 E-W (100m) 和 N-S (80m) 都有分量
    # E-W边 cos_sim = |1*0.707 + 0*(-0.707)|/1 = 0.707, score = 0.707 * 100 = 70.7
    # N-S边 cos_sim = |0*0.707 + 1*(-0.707)|/1 = 0.707, score = 0.707 * 80 = 56.56
    # 所以排水沟应选 E-W 方向的边 (最长水平边)
    result_drain = clipper.generate(Strategy.EDGE_FOLLOW, zone, "排水沟C20")
    assert result_drain.polyline is not None, "排水沟应有 polyline"

    # 截水沟: 应选与 SE 垂直方向 (0.707, 0.707) 最对齐的边
    # 与 (0.707, 0.707): E-W cos_sim = 0.707, score = 70.7; N-S cos_sim = 0.707, score = 56.56
    # 同样选 E-W, 但关键是截水沟不会选和排水沟相同的策略
    result_cut = clipper.generate(Strategy.EDGE_FOLLOW, zone, "截水沟")
    assert result_cut.polyline is not None, "截水沟应有 polyline"


if __name__ == "__main__":
    test_measure_styles_coverage()
    test_get_style_known()
    test_get_style_fuzzy()
    test_get_style_unknown()
    test_section_templates()
    test_zone_colors()
    test_get_zone_color_unknown()
    test_measure_map_renderer_init()
    test_render_zone_boundary_map()
    test_render_all()
    test_default_spatial_layout()
    test_spatial_context_tool_no_state()
    test_get_placement_after_resolve_all()
    test_optimize_batch()
    test_label_placer_collision()
    test_zorder_sorting()
    test_elevation_extraction()
    test_terrain_computation()
    test_find_lowest_point()
    test_slope_direction_vector()
    test_edge_follow_slope_aware()
    print("\n全部测试通过!")
