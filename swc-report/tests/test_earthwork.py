"""土方平衡计算测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.state import init_state
from src.settings import CONFIG_DIR
from src.calculators.earthwork import calc_earthwork


def test_earthwork():
    """测试土方平衡计算 — 余方应为 25000m³。"""
    state = init_state(CONFIG_DIR / "facts_v2.json", CONFIG_DIR / "measures_v2.csv")
    result = calc_earthwork(state)

    # 基本字段存在
    assert "excavation_m3" in result
    assert "fill_m3" in result
    assert "surplus_m3" in result

    # 核心计算验证
    # 可用挖方 = 135000 - 15000 = 120000
    assert result["usable_cut_m3"] == 120000.0
    # 需填方 = 110000 - 15000 = 95000
    assert result["need_fill_m3"] == 95000.0
    # 余方 = 120000 - 95000 = 25000
    assert result["surplus_m3"] == 25000.0
    # 外运 = max(25000, 0) = 25000
    assert result["export_out_m3"] == 25000.0
    # 无借方
    assert result["borrow_in_m3"] == 0.0

    # 分区数据
    assert len(result["zone_earthwork"]) == 5

    print("test_earthwork PASSED")


if __name__ == "__main__":
    test_earthwork()
