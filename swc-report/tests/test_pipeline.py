"""端到端流水线测试 (无 LLM 模式)。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.settings import CONFIG_DIR, OUTPUT_DIR
from src.pipeline import Pipeline


def test_pipeline_no_llm():
    """测试完整流水线 (--no-llm 模式)。"""
    output_dir = OUTPUT_DIR / "test_run"

    pipeline = Pipeline(
        facts_path=CONFIG_DIR / "facts_v2.json",
        measures_path=CONFIG_DIR / "measures_v2.csv",
        output_dir=output_dir,
        use_llm=False,
    )

    output_path = pipeline.run()

    # 检查输出文件
    assert output_path.exists() or (output_dir / "report.docx").exists(), \
        "report.docx 未生成"

    # 检查审计日志
    audit_path = output_dir / "audit.json"
    assert audit_path.exists(), "audit.json 未生成"

    # 检查图表
    for chart_name in ["erosion_chart", "investment_pie", "benefit_bar", "zone_pie"]:
        chart_path = output_dir / f"{chart_name}.png"
        assert chart_path.exists(), f"{chart_name}.png 未生成"

    # 验证 State
    state = pipeline.state
    assert state.Calc.earthwork["surplus_m3"] == 25000.0
    assert state.Calc.erosion_df["total_pred"] > 0
    assert state.Calc.cost_summary["c_grand_total"] > 0
    assert len(state.TplCtx) >= 150

    print(f"输出目录: {output_dir}")
    print(f"报告: {output_path}")
    print(f"标签数: {len(state.TplCtx)}")
    print(f"审计分: {state.Flags.get('final_score', 0)}")
    print("test_pipeline_no_llm PASSED")


if __name__ == "__main__":
    test_pipeline_no_llm()
