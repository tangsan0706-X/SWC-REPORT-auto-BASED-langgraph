"""效益分析计算测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.state import init_state
from src.settings import CONFIG_DIR
from src.calculators.earthwork import calc_earthwork
from src.calculators.erosion import calc_erosion
from src.calculators.benefit import calc_benefit
from src.agents.planner import _default_measures


def test_benefit():
    """测试效益分析 — 六项指标全部计算。"""
    state = init_state(CONFIG_DIR / "facts_v2.json", CONFIG_DIR / "measures_v2.csv")
    calc_earthwork(state)
    calc_erosion(state)

    # 添加默认措施
    new_measures = _default_measures()
    for m in new_measures:
        m["source"] = "planned"
        state.Measures.append(m)

    result = calc_benefit(state)

    # 六项指标都有
    indicators = result["indicators"]
    expected_names = [
        "水土流失治理度", "土壤流失控制比", "渣土防护率",
        "表土保护率", "林草植被恢复率", "林草覆盖率",
    ]
    for name in expected_names:
        assert name in indicators, f"缺少指标: {name}"
        ind = indicators[name]
        assert "target" in ind
        assert "actual" in ind
        assert "status" in ind
        assert ind["actual"] >= 0, f"{name} 实际值不应为负"
        print(f"  {name}: 目标={ind['target']}, 实际={ind['actual']}, {ind['status']}")

    # 表土保护率 = 100% (回覆=剥离=15000)
    assert indicators["表土保护率"]["actual"] == 100.0

    print("test_benefit PASSED")


if __name__ == "__main__":
    test_benefit()
