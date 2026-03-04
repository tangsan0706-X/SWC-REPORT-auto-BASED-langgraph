"""侵蚀预测计算测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.state import init_state
from src.settings import CONFIG_DIR
from src.calculators.earthwork import calc_earthwork
from src.calculators.erosion import calc_erosion


def test_erosion():
    """测试侵蚀预测 — 5×3 矩阵非零。"""
    state = init_state(CONFIG_DIR / "facts_v2.json", CONFIG_DIR / "measures_v2.csv")
    calc_earthwork(state)
    result = calc_erosion(state)

    # 矩阵非空
    matrix = result["matrix"]
    assert len(matrix) == 5, f"分区数应为5，实际 {len(matrix)}"

    # 每个分区3个时段
    for zone_name, periods in matrix.items():
        assert len(periods) == 3, f"{zone_name} 时段数应为3"
        for pid, val in periods.items():
            assert val >= 0, f"{zone_name}/{pid} 流失量不应为负"

    # 所有值非零 (至少总计非零)
    assert result["total_pred"] > 0, "总预测流失量应大于0"
    assert result["total_bg"] > 0, "总背景流失量应大于0"
    assert result["total_new"] > 0, "新增流失量应大于0"

    # 新增 = 预测 - 背景
    assert abs(result["total_new"] - (result["total_pred"] - result["total_bg"])) < 0.1

    # 时段合计 = 总计
    pp = result["period_pred"]
    assert abs(sum(pp.values()) - result["total_pred"]) < 0.1

    print(f"总预测: {result['total_pred']:.2f}t")
    print(f"新增: {result['total_new']:.2f}t")
    print("test_erosion PASSED")


if __name__ == "__main__":
    test_erosion()
