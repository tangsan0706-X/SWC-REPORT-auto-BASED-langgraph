"""诊断脚本 — 按照 ClaudeCode-逐步调试修复指令.md 的方法论
打印红线数据、措施坐标、线性措施渲染数据等关键中间结果。
"""

import sys
import io
from pathlib import Path

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_DIR = Path(__file__).resolve().parent.parent
DXF_PATH = BASE_DIR / "data" / "output" / "cad_dxf" / "20221215博雅园总图（原坐标）.dxf"


def diagnose_step1_boundary(cad_geometry, cad_site_features):
    """第一步：诊断红线数据"""
    print("=" * 60)
    print("【诊断-第1步】红线数据")
    boundary = getattr(cad_site_features, 'boundary_polyline', None)
    if boundary is not None and isinstance(boundary, list) and len(boundary) > 0:
        print(f"  顶点数: {len(boundary)}")
        print(f"  前5个顶点: {boundary[:5]}")
        is_closed = (len(boundary) > 1 and
                     abs(boundary[0][0] - boundary[-1][0]) < 1.0 and
                     abs(boundary[0][1] - boundary[-1][1]) < 1.0)
        print(f"  是否闭合: {is_closed}")

        xs = [p[0] for p in boundary]
        ys = [p[1] for p in boundary]
        print(f"  X 范围: [{min(xs):.1f}, {max(xs):.1f}], 宽度: {max(xs)-min(xs):.1f}")
        print(f"  Y 范围: [{min(ys):.1f}, {max(ys):.1f}], 高度: {max(ys)-min(ys):.1f}")

        unique = len(set((round(x, 1), round(y, 1)) for x, y in boundary))
        print(f"  唯一顶点数: {unique} {'<- 矩形!' if unique <= 5 else '<- 非矩形 OK'}")
    else:
        print("  红线为 None 或空!")
    print("=" * 60)
    print()


def diagnose_step1b_dxf(dxf_path):
    """第一步补充：直接扫描 DXF 闭合多边形"""
    import ezdxf
    print("=" * 60)
    print("【诊断-第1步补充】DXF 闭合多边形 TOP 10")
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    # 红线关键词搜索
    keywords = ["红线", "REDLINE", "BOUND", "边界", "SITE", "用地",
                "SCOPE", "范围", "LIMT", "LIMIT"]
    print("\n候选红线实体 (图层名匹配):")
    found_kw = 0
    for entity in msp:
        layer = entity.dxf.layer.upper() if hasattr(entity.dxf, 'layer') else ""
        if any(kw.upper() in layer for kw in keywords):
            found_kw += 1
            etype = entity.dxftype()
            color = getattr(entity.dxf, 'color', 'bylayer')
            if etype == "LWPOLYLINE":
                points = list(entity.get_points())
                closed = getattr(entity, 'closed', False)
                print(f"  layer={entity.dxf.layer}, type={etype}, color={color}, "
                      f"顶点={len(points)}, 闭合={closed}")
            else:
                print(f"  layer={entity.dxf.layer}, type={etype}, color={color}")
    if found_kw == 0:
        print("  (无匹配)")

    # 红色闭合多边形
    red_closed = []
    for entity in msp:
        color = getattr(entity.dxf, 'color', None)
        if color == 1 and entity.dxftype() == "LWPOLYLINE":
            closed = getattr(entity, 'closed', False)
            points = list(entity.get_points())
            if len(points) >= 3:
                area = abs(sum(
                    points[i][0] * points[(i+1) % len(points)][1] -
                    points[(i+1) % len(points)][0] * points[i][1]
                    for i in range(len(points))
                )) / 2.0
                red_closed.append({
                    "layer": entity.dxf.layer,
                    "vertices": len(points),
                    "area": area,
                    "closed": closed,
                })

    red_closed.sort(key=lambda x: x["area"], reverse=True)
    print(f"\n红色(color=1)多边形 TOP 10 (含开放):")
    for i, rc in enumerate(red_closed[:10]):
        print(f"  {i+1}. layer={rc['layer']}, 顶点={rc['vertices']}, "
              f"面积={rc['area']:.0f}m², 闭合={rc['closed']}")

    # 所有闭合多边形面积 TOP 10
    all_closed = []
    for entity in msp:
        if entity.dxftype() == "LWPOLYLINE":
            closed = getattr(entity, 'closed', False)
            if closed:
                points = list(entity.get_points())
                if len(points) >= 4:
                    area = abs(sum(
                        points[i][0] * points[(i+1) % len(points)][1] -
                        points[(i+1) % len(points)][0] * points[i][1]
                        for i in range(len(points))
                    )) / 2.0
                    all_closed.append({
                        "layer": entity.dxf.layer,
                        "color": getattr(entity.dxf, 'color', 'bylayer'),
                        "vertices": len(points),
                        "area": area,
                    })

    all_closed.sort(key=lambda x: x["area"], reverse=True)
    print(f"\n所有闭合多边形面积 TOP 10:")
    for i, ac in enumerate(all_closed[:10]):
        print(f"  {i+1}. layer={ac['layer']}, color={ac['color']}, "
              f"顶点={ac['vertices']}, 面积={ac['area']:.0f}m²")
    print("=" * 60)
    print()


def diagnose_step2_measures(engine, boundary, zones):
    """第二步：诊断措施坐标"""
    print("=" * 60)
    print("【诊断-第2步】所有措施的坐标位置")

    # 场地范围
    if boundary and len(boundary) >= 3:
        bx = [p[0] for p in boundary]
        by = [p[1] for p in boundary]
        site_x_min, site_x_max = min(bx), max(bx)
        site_y_min, site_y_max = min(by), max(by)
        print(f"场地(红线) X 范围: [{site_x_min:.1f}, {site_x_max:.1f}]")
        print(f"场地(红线) Y 范围: [{site_y_min:.1f}, {site_y_max:.1f}]")
    else:
        print("  无红线, 无法判断场地范围")
        site_x_min = site_x_max = site_y_min = site_y_max = 0

    print()

    # 遍历 PlacementEngine 的结果 (_registry)
    results = engine._registry if hasattr(engine, '_registry') else {}
    print(f"PlacementEngine._registry 条目数: {len(results)}")
    in_count = 0
    out_count = 0
    none_count = 0

    for key, pr in results.items():
        if pr is None or pr.skipped:
            none_count += 1
            reason = pr.skip_reason if pr else "None"
            print(f"  X {key}: skipped ({reason})")
            continue

        # PlacementResult has polyline/polygon/points attributes
        coords = None
        geom_type = "none"
        if pr.polyline and len(pr.polyline) >= 2:
            coords = pr.polyline
            geom_type = "polyline"
        elif pr.polygon and len(pr.polygon) >= 3:
            coords = pr.polygon
            geom_type = "polygon"
        elif pr.points and len(pr.points) >= 1:
            coords = pr.points
            geom_type = "points"

        if coords is None:
            none_count += 1
            print(f"  X {key}: 无有效几何 (polyline={pr.polyline}, polygon={pr.polygon}, points={pr.points})")
            continue

        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)

        in_site = (site_x_min <= cx <= site_x_max and
                   site_y_min <= cy <= site_y_max)
        if in_site:
            in_count += 1
            status = "V 场地内"
        else:
            out_count += 1
            status = "X 场地外!"
        print(f"  {status} {key}: {geom_type}, center=({cx:.1f}, {cy:.1f}), 点数={len(coords)}, "
              f"策略={pr.strategy.value}")

    print(f"\n统计: 场地内={in_count}, 场地外={out_count}, 无坐标={none_count}")
    print("=" * 60)
    print()


def diagnose_step3_linear(engine):
    """第三步：诊断线性措施的渲染数据"""
    print("=" * 60)
    print("【诊断-第3步】线性措施渲染数据")

    LINEAR_KEYWORDS = ["排水沟", "截水沟", "临时排水", "围挡"]
    results = engine._registry if hasattr(engine, '_registry') else {}

    for key, pr in results.items():
        is_linear = any(kw in key for kw in LINEAR_KEYWORDS)
        if not is_linear:
            continue

        print(f"\n{key}:")
        if pr is None:
            print(f"  X PlacementResult 为 None")
            continue

        if pr.skipped:
            print(f"  X skipped: {pr.skip_reason}")
            continue

        # PlacementResult has polyline/polygon/points
        coords = None
        if pr.polyline and len(pr.polyline) >= 2:
            coords = pr.polyline
            print(f"  V 类型: polyline")
        elif pr.polygon and len(pr.polygon) >= 2:
            coords = pr.polygon
            print(f"  V 类型: polygon (非典型线性)")
        else:
            print(f"  X 无polyline/polygon: polyline={pr.polyline}, polygon={pr.polygon}, points={pr.points}")
            continue

        if coords and len(coords) >= 2:
            print(f"  坐标点数: {len(coords)}")
            print(f"  前3个点: {coords[:3]}")
            length = sum(
                ((coords[i+1][0]-coords[i][0])**2 +
                 (coords[i+1][1]-coords[i][1])**2)**0.5
                for i in range(len(coords)-1)
            )
            print(f"  线段总长: {length:.1f}")
            print(f"  策略: {pr.strategy.value}")
        else:
            print(f"  X 坐标点不足: 只有 {len(coords)} 个点")

    print("=" * 60)
    print()


def main():
    if not DXF_PATH.exists():
        print(f"错误: DXF 文件不存在: {DXF_PATH}")
        return

    # ── Step 1: 解析 + 分析 ──
    from src.cad_base_renderer import parse_dxf_geometry
    cad_geometry = parse_dxf_geometry(DXF_PATH)
    if cad_geometry is None:
        print("DXF 解析失败")
        return

    from src.cad_feature_analyzer import CadFeatureAnalyzer
    analyzer = CadFeatureAnalyzer(cad_geometry, spatial_layout=None)
    cad_site_features = analyzer.analyze()

    # 诊断 1: 红线
    diagnose_step1_boundary(cad_geometry, cad_site_features)
    diagnose_step1b_dxf(DXF_PATH)

    # ── Step 2-3: PlacementEngine ──
    from src.site_model import SiteModelBuilder
    builder = SiteModelBuilder()
    builder.from_ezdxf(cad_geometry, cad_site_features)
    builder.from_meta({"project_name": "金石博雅园", "total_area_hm2": 8.24})
    site_model = builder.build()

    zones = [
        {"name": "建(构)筑物区", "area_hm2": 3.67, "area_m2": 36700},
        {"name": "道路广场区", "area_hm2": 2.10, "area_m2": 21000},
        {"name": "绿化工程区", "area_hm2": 1.17, "area_m2": 11700},
        {"name": "施工生产生活区", "area_hm2": 0.85, "area_m2": 8500},
        {"name": "临时堆土区", "area_hm2": 0.45, "area_m2": 4500},
    ]
    measures = [
        {"措施名称": "排水沟C20(40×40)", "分区": "建(构)筑物区",
         "类型": "工程措施", "单位": "m", "数量": 230},
        {"措施名称": "排水沟C20(60×60)", "分区": "道路广场区",
         "类型": "工程措施", "单位": "m", "数量": 180},
        {"措施名称": "截水沟C20(30×30)", "分区": "绿化工程区",
         "类型": "工程措施", "单位": "m", "数量": 150},
        {"措施名称": "截水沟C20(40×40)", "分区": "施工生产生活区",
         "类型": "工程措施", "单位": "m", "数量": 120},
        {"措施名称": "沉砂池(2×2×1.5m)", "分区": "建(构)筑物区",
         "类型": "工程措施", "单位": "座", "数量": 3},
        {"措施名称": "沉砂池(3×3×2m)", "分区": "道路广场区",
         "类型": "工程措施", "单位": "座", "数量": 2},
        {"措施名称": "洗车平台", "分区": "施工生产生活区",
         "类型": "工程措施", "单位": "台", "数量": 1},
        {"措施名称": "雨水收集池", "分区": "绿化工程区",
         "类型": "工程措施", "单位": "座", "数量": 1},
        {"措施名称": "透水砖铺装", "分区": "道路广场区",
         "类型": "工程措施", "单位": "m²", "数量": 3500},
        {"措施名称": "表土回覆", "分区": "绿化工程区",
         "类型": "工程措施", "单位": "m²", "数量": 5000},
        {"措施名称": "综合绿化(乔灌草)", "分区": "绿化工程区",
         "类型": "植物措施", "单位": "m²", "数量": 8000},
        {"措施名称": "行道树(香樟)", "分区": "道路广场区",
         "类型": "植物措施", "单位": "株", "数量": 60},
        {"措施名称": "防尘网苫盖", "分区": "临时堆土区",
         "类型": "临时措施", "单位": "m²", "数量": 3000},
        {"措施名称": "临时排水沟(土质)", "分区": "施工生产生活区",
         "类型": "临时措施", "单位": "m", "数量": 200},
        {"措施名称": "施工围挡(彩钢板)", "分区": "建(构)筑物区",
         "类型": "临时措施", "单位": "m", "数量": 350},
        {"措施名称": "监测点位", "分区": "建(构)筑物区",
         "类型": "临时措施", "单位": "处", "数量": 5},
    ]

    from src.placement import PlacementEngine
    engine = PlacementEngine(site_model)
    engine.resolve_all(measures)
    engine.optimize_batch()

    boundary = getattr(cad_site_features, 'boundary_polyline', [])

    # 诊断 2: 措施坐标
    diagnose_step2_measures(engine, boundary, zones)

    # 诊断 3: 线性措施
    diagnose_step3_linear(engine)


if __name__ == "__main__":
    main()
