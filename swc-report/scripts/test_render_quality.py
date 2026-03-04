"""出图效果测试 — 生成完整措施图集, 验证渲染质量。

使用多分区 + 多措施, 全面测试:
  1. 分区图 (zone_boundary_map)
  2. 措施总体布置图 (measure_layout_map) ← 核心重点
  3. 分区详图 ×N
  4. 典型断面图 ×N
  5. PlacementEngine 预计算 + optimize_batch
  6. LabelPlacer 碰撞避让
  7. Z-Order 渲染层次
  8. 专业图例/坐标标注/图签
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.measure_map import MeasureMapRenderer
from src.settings import OUTPUT_DIR


def main():
    output_dir = OUTPUT_DIR / "render_quality_test"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 5 个标准分区 ──
    zones = [
        {"name": "建(构)筑物区", "area_hm2": 3.67, "area_m2": 36700},
        {"name": "道路广场区", "area_hm2": 2.10, "area_m2": 21000},
        {"name": "绿化工程区", "area_hm2": 1.17, "area_m2": 11700},
        {"name": "施工生产生活区", "area_hm2": 0.85, "area_m2": 8500},
        {"name": "临时堆土区", "area_hm2": 0.45, "area_m2": 4500},
    ]

    # ── 丰富措施列表 (工程+植物+临时, 线+面+点) ──
    measures = [
        # 工程措施 - 线状
        {"措施名称": "排水沟C20(40×40)", "分区": "建(构)筑物区",
         "类型": "工程措施", "单位": "m", "数量": 230, "source": "planned"},
        {"措施名称": "排水沟C20(60×60)", "分区": "道路广场区",
         "类型": "工程措施", "单位": "m", "数量": 180, "source": "planned"},
        {"措施名称": "截水沟C20(30×30)", "分区": "绿化工程区",
         "类型": "工程措施", "单位": "m", "数量": 150, "source": "planned"},
        {"措施名称": "截水沟C20(40×40)", "分区": "施工生产生活区",
         "类型": "工程措施", "单位": "m", "数量": 120, "source": "planned"},
        {"措施名称": "急流槽C20", "分区": "临时堆土区",
         "类型": "工程措施", "单位": "m", "数量": 60, "source": "planned"},
        {"措施名称": "浆砌石挡墙", "分区": "临时堆土区",
         "类型": "工程措施", "单位": "m", "数量": 80, "source": "planned"},

        # 工程措施 - 点状
        {"措施名称": "沉沙池(2×2×1.5m)", "分区": "建(构)筑物区",
         "类型": "工程措施", "单位": "座", "数量": 3, "source": "planned"},
        {"措施名称": "沉沙池(3×3×2m)", "分区": "道路广场区",
         "类型": "工程措施", "单位": "座", "数量": 2, "source": "planned"},
        {"措施名称": "车辆冲洗平台", "分区": "施工生产生活区",
         "类型": "工程措施", "单位": "台", "数量": 1, "source": "planned"},

        # 工程措施 - 面状
        {"措施名称": "透水砖铺装", "分区": "道路广场区",
         "类型": "工程措施", "单位": "m²", "数量": 3500, "source": "planned"},
        {"措施名称": "场地平整", "分区": "建(构)筑物区",
         "类型": "工程措施", "单位": "m²", "数量": 5000, "source": "planned"},
        {"措施名称": "表土剥离", "分区": "临时堆土区",
         "类型": "工程措施", "单位": "m³", "数量": 2000, "source": "planned"},

        # 植物措施
        {"措施名称": "撒播草籽(混播)", "分区": "绿化工程区",
         "类型": "植物措施", "单位": "m²", "数量": 8000, "source": "planned"},
        {"措施名称": "综合绿化(乔灌草)", "分区": "建(构)筑物区",
         "类型": "植物措施", "单位": "m²", "数量": 5000, "source": "planned"},
        {"措施名称": "栽植乔木", "分区": "道路广场区",
         "类型": "植物措施", "单位": "株", "数量": 120, "source": "planned"},
        {"措施名称": "栽植灌木", "分区": "绿化工程区",
         "类型": "植物措施", "单位": "株", "数量": 300, "source": "planned"},
        {"措施名称": "铺设草皮", "分区": "施工生产生活区",
         "类型": "植物措施", "单位": "m²", "数量": 2000, "source": "planned"},

        # 临时措施
        {"措施名称": "密目安全网覆盖(6针)", "分区": "临时堆土区",
         "类型": "临时措施", "单位": "m²", "数量": 3000, "source": "planned"},
        {"措施名称": "临时排水沟(土质)", "分区": "施工生产生活区",
         "类型": "临时措施", "单位": "m", "数量": 200, "source": "planned"},
        {"措施名称": "临时沉沙池(简易)", "分区": "施工生产生活区",
         "类型": "临时措施", "单位": "座", "数量": 4, "source": "planned"},
        {"措施名称": "施工围挡(彩钢板)", "分区": "建(构)筑物区",
         "类型": "临时措施", "单位": "m", "数量": 350, "source": "planned"},
        {"措施名称": "洒水降尘", "分区": "道路广场区",
         "类型": "临时措施", "单位": "次/天", "数量": 2, "source": "planned"},
    ]

    print(f"分区数: {len(zones)}")
    print(f"措施数: {len(measures)}")
    print(f"输出目录: {output_dir}")
    print()

    # ── 渲染 ──
    t0 = time.time()
    renderer = MeasureMapRenderer(
        zones=zones,
        measures=measures,
        output_dir=output_dir,
    )
    print(f"初始化耗时: {time.time() - t0:.2f}s")

    t1 = time.time()
    result = renderer.render_all()
    elapsed = time.time() - t1

    print(f"\n渲染耗时: {elapsed:.2f}s")
    print(f"生成 {len(result)} 张图:")
    for name, path in sorted(result.items()):
        size_kb = path.stat().st_size / 1024 if path.exists() else 0
        print(f"  {name}: {path.name} ({size_kb:.0f} KB)")

    print(f"\n输出目录: {output_dir}")
    print("请检查生成的 PNG 文件以验证渲染质量。")


if __name__ == "__main__":
    main()
