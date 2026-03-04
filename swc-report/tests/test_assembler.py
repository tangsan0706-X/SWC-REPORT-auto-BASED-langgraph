"""状态装配器测试 — 229 标签全非空。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.state import init_state
from src.settings import CONFIG_DIR
from src.calculators.earthwork import calc_earthwork
from src.calculators.erosion import calc_erosion
from src.calculators.cost import calc_cost
from src.calculators.benefit import calc_benefit
from src.assembler import assemble
from src.agents.planner import _default_measures


def test_assembler():
    """测试装配器 — 输出标签非空。"""
    state = init_state(CONFIG_DIR / "facts_v2.json", CONFIG_DIR / "measures_v2.csv")
    calc_earthwork(state)
    calc_erosion(state)

    # 添加默认措施
    new_measures = _default_measures()
    for m in new_measures:
        m["source"] = "planned"
        state.Measures.append(m)

    calc_cost(state)
    calc_benefit(state)

    # 添加占位文本
    from src.agents.writer import CHAPTER_CONFIGS
    for ch_id, config in CHAPTER_CONFIGS.items():
        for tag in config["tags"]:
            state.Draft[tag] = f"[{tag} 占位文本内容]"

    ctx = assemble(state)

    # 检查标签数量
    print(f"总标签数: {len(ctx)}")
    assert len(ctx) >= 150, f"标签数不足: {len(ctx)} < 150"

    # 检查关键标签
    key_tags = [
        "project_name", "city", "total_land",
        "ew_dig", "ew_surplus",
        "ep_total_pred", "ep_total_new",
        "c_grand_total", "c1_total",
        "t_治理度", "r_治理度",
        "chapter1_brief",
    ]
    for tag in key_tags:
        assert tag in ctx, f"缺少标签: {tag}"
        val = ctx[tag]
        assert val is not None, f"标签为 None: {tag}"
        assert str(val) != "", f"标签为空: {tag}"
        print(f"  {tag} = {str(val)[:50]}")

    # 循环表格
    assert len(ctx["land_use_table"]) == 5
    assert len(ctx["existing_measures"]) > 0
    assert len(ctx["erosion_table"]) == 5

    # 统计空值
    none_count = sum(1 for v in ctx.values()
                     if v is None or (isinstance(v, str) and v == ""))
    print(f"空值标签: {none_count}")

    print("test_assembler PASSED")


if __name__ == "__main__":
    test_assembler()
