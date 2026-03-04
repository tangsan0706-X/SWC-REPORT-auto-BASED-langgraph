"""造价估算计算测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.state import init_state
from src.settings import CONFIG_DIR
from src.calculators.earthwork import calc_earthwork
from src.calculators.erosion import calc_erosion
from src.calculators.cost import calc_cost
from src.agents.planner import _default_measures


def test_cost():
    """测试造价计算 — 六层叠加正确。"""
    state = init_state(CONFIG_DIR / "facts_v2.json", CONFIG_DIR / "measures_v2.csv")
    calc_earthwork(state)
    calc_erosion(state)

    # 添加默认措施
    new_measures = _default_measures()
    for m in new_measures:
        m["source"] = "planned"
        state.Measures.append(m)

    result = calc_cost(state)

    # 基本字段
    assert "c_grand_total" in result
    assert "c1_total" in result
    assert "c2_total" in result
    assert "c3_total" in result

    # 总投资 > 0
    assert result["c_grand_total"] > 0, "总投资应大于0"

    # 一~三部分合计检查
    c123 = result["c1_total"] + result["c2_total"] + result["c3_total"]
    assert abs(result["c123_total"] - c123) < 0.01, \
        f"一~三部分不一致: {result['c123_total']} vs {c123}"

    # 总投资 = 一~四部分 + 预备费 + 补偿费
    expected = result["c1234_total"] + result["c_contingency"] + result["c_compensation"]
    assert abs(result["c_grand_total"] - expected) < 0.01, \
        f"总投资不一致: {result['c_grand_total']} vs {expected}"

    # 预备费 = 一~四部分 × 6%
    expected_cont = result["c1234_total"] * 0.06
    assert abs(result["c_contingency"] - round(expected_cont, 2)) < 0.01

    # 补偿费 > 0
    assert result["c_compensation"] > 0

    print(f"水保总投资: {result['c_grand_total']:.2f}万元")
    print(f"  工程措施: {result['c1_total']:.2f}万元")
    print(f"  植物措施: {result['c2_total']:.2f}万元")
    print(f"  临时措施: {result['c3_total']:.2f}万元")
    print(f"  独立费用: {result['c4_total']:.2f}万元")
    print(f"  预备费: {result['c_contingency']:.2f}万元")
    print(f"  补偿费: {result['c_compensation']:.2f}万元")
    print("test_cost PASSED")


if __name__ == "__main__":
    test_cost()
