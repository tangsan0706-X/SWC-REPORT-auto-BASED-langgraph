"""图表生成 — matplotlib 制图 + PNG 输出。

4 张图表:
  1. erosion_sankey  — 水土流失 Sankey 图 (简化为堆叠柱状图)
  2. investment_pie  — 投资构成饼图
  3. benefit_bar     — 六指标达标对比柱状图
  4. zone_pie        — 分区面积占比饼图
"""

from __future__ import annotations

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

from src.state import GlobalState
from src.settings import CHART_DPI, OUTPUT_DIR

# 尝试使用中文字体
import logging as _logging
_chart_logger = _logging.getLogger(__name__)

_CN_FONT = None
for font_name in ["SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC",
                   "Microsoft YaHei", "DejaVu Sans"]:
    try:
        _CN_FONT = fm.FontProperties(family=font_name)
        break
    except Exception:
        continue

if _CN_FONT:
    plt.rcParams["font.family"] = _CN_FONT.get_name()
else:
    _chart_logger.warning(
        "未找到中文字体 (SimHei/WenQuanYi/Noto Sans CJK/Microsoft YaHei)，"
        "图表中文可能显示为方块。请安装: apt install fonts-wqy-microhei 或手动安装 SimHei。"
    )
plt.rcParams["axes.unicode_minus"] = False


def _save(fig, name: str, output_dir: Path | None = None) -> Path:
    """保存图表到 PNG。"""
    out = output_dir or OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    fig.savefig(str(path), dpi=CHART_DPI, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    return path


def erosion_chart(state: GlobalState, output_dir: Path | None = None) -> Path:
    """水土流失预测柱状图 — 按分区×时段。"""
    erosion = state.Calc.erosion_df
    matrix = erosion.get("matrix", {})
    zones = list(matrix.keys())
    periods = ["s1", "s2", "s3"]
    period_names = ["已开工时段", "施工时段", "恢复期"]

    data = np.array([
        [matrix.get(z, {}).get(p, 0) for p in periods]
        for z in zones
    ])

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(zones))
    width = 0.25

    for i, (pname, color) in enumerate(zip(period_names, ["#e74c3c", "#f39c12", "#27ae60"])):
        bars = ax.bar(x + i * width, data[:, i], width, label=pname, color=color)
        for bar, val in zip(bars, data[:, i]):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f"{val:.1f}", ha="center", va="bottom", fontsize=7)

    ax.set_xlabel("防治分区")
    ax.set_ylabel("预测流失量 (t)")
    ax.set_title("水土流失预测结果")
    ax.set_xticks(x + width)
    ax.set_xticklabels(zones, rotation=15, ha="right")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    return _save(fig, "erosion_chart", output_dir)


def investment_pie(state: GlobalState, output_dir: Path | None = None) -> Path:
    """投资构成饼图。"""
    cost = state.Calc.cost_summary
    labels = ["工程措施", "植物措施", "临时措施", "独立费用", "基本预备费", "补偿费"]
    values = [
        cost.get("c1_total", 0),
        cost.get("c2_total", 0),
        cost.get("c3_total", 0),
        cost.get("c4_total", 0),
        cost.get("c_contingency", 0),
        cost.get("c_compensation", 0),
    ]

    # 过滤零值
    filtered = [(l, v) for l, v in zip(labels, values) if v > 0]
    if not filtered:
        filtered = [("无数据", 1)]
    labels, values = zip(*filtered)

    colors = ["#3498db", "#2ecc71", "#e67e22", "#9b59b6", "#95a5a6", "#e74c3c"]

    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct="%1.1f%%",
        colors=colors[:len(labels)],
        startangle=90, pctdistance=0.75,
    )
    for t in autotexts:
        t.set_fontsize(9)
    ax.set_title("水土保持投资构成")

    return _save(fig, "investment_pie", output_dir)


def benefit_bar(state: GlobalState, output_dir: Path | None = None) -> Path:
    """六指标达标对比柱状图。"""
    benefit = state.Calc.benefit
    indicators = benefit.get("indicators", {})

    names = list(indicators.keys())
    targets = [indicators[n]["target"] for n in names]
    actuals = [indicators[n]["actual"] for n in names]

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(names))
    width = 0.35

    bars1 = ax.bar(x - width / 2, targets, width, label="目标值",
                   color="#3498db", alpha=0.8)
    bars2 = ax.bar(x + width / 2, actuals, width, label="预测值",
                   color="#2ecc71", alpha=0.8)

    for bar, val in zip(bars1, targets):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                str(val), ha="center", va="bottom", fontsize=8)
    for bar, val in zip(bars2, actuals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                str(val), ha="center", va="bottom", fontsize=8)

    ax.set_xlabel("防治指标")
    ax.set_ylabel("指标值")
    ax.set_title("水土保持防治效果分析")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=15, ha="right")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    return _save(fig, "benefit_bar", output_dir)


def zone_pie(state: GlobalState, output_dir: Path | None = None) -> Path:
    """分区面积占比饼图。"""
    zones = state.ETL.zones
    labels = [z["name"] for z in zones]
    values = [z["area_hm2"] for z in zones]

    colors = ["#e74c3c", "#f39c12", "#2ecc71", "#3498db", "#9b59b6"]

    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct="%1.1f%%",
        colors=colors[:len(labels)],
        startangle=90,
    )
    for t in autotexts:
        t.set_fontsize(9)
    ax.set_title("防治分区面积构成")

    return _save(fig, "zone_pie", output_dir)


def generate_all_charts(state: GlobalState, output_dir: Path | None = None) -> dict[str, Path]:
    """生成全部 4 张图表。"""
    charts = {}
    charts["erosion_chart"] = erosion_chart(state, output_dir)
    charts["investment_pie"] = investment_pie(state, output_dir)
    charts["benefit_bar"] = benefit_bar(state, output_dir)
    charts["zone_pie"] = zone_pie(state, output_dir)
    return charts
