"""C2 预测师 — 水土流失预测计算。

输入: facts.zones + soil_map.json + schedule
输出: erosion_df 矩阵 (5 zones × 3 periods) + 行列合计 → State.Calc.erosion_df

公式: W[zone][period] = M × A × T / 100
  M: 侵蚀模数 (t/km²·a) — soil_map 查表
  A: 分区面积 (km²) = hm² / 100
  T: 时段年数 = days / 365
"""

from __future__ import annotations

from datetime import datetime, date
from src.state import GlobalState


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _days_between(d1: date, d2: date) -> int:
    return max((d2 - d1).days, 0)


def calc_erosion(state: GlobalState) -> dict:
    """
    三时段水土流失预测。

    时段划分:
      P1 已开工时段: start_date → plan_submit_date (施工扰动, construction模数)
      P2 施工时段:   plan_submit_date → end_date     (施工扰动, construction模数)
      P3 恢复期:     end_date → end_date+1年          (自然恢复, recovery模数)
    """
    meta = state.Static.meta
    soil_data = state.Static.soil_map["data"]
    city = meta["location"]["city"]
    city_data = soil_data[city]

    bg_modulus = city_data["background_modulus"]  # 背景模数 t/km²·a
    zones = state.ETL.zones

    # 时段划分
    start = _parse_date(meta["schedule"]["start_date"])
    submit = _parse_date(meta["schedule"]["plan_submit_date"])
    end = _parse_date(meta["schedule"]["end_date"])
    # 恢复期终点: 竣工后1年
    try:
        recovery_end = date(end.year + 1, end.month, end.day)
    except ValueError:
        # 闰年2月29日 → 次年2月28日
        recovery_end = date(end.year + 1, end.month, end.day - 1)

    periods = [
        {"id": "s1", "name": "已开工时段", "start": start, "end": submit,
         "modulus_key": "construction"},
        {"id": "s2", "name": "施工时段", "start": submit, "end": end,
         "modulus_key": "construction"},
        {"id": "s3", "name": "恢复期", "start": end, "end": recovery_end,
         "modulus_key": "recovery"},
    ]

    # 总面积 (km²)
    total_area_hm2 = meta["land_area_hm2"]
    total_area_km2 = total_area_hm2 / 100

    # 总时段年数
    total_start = start
    total_end = recovery_end
    total_T = _days_between(total_start, total_end) / 365.0

    # 矩阵计算
    matrix = {}  # {zone_name: {period_id: predicted_loss_t}}
    zone_totals = {}  # {zone_name: total_predicted}

    for z in zones:
        zone_name = z["name"]
        area_km2 = z["area_hm2"] / 100
        zone_soil = city_data["zones"].get(zone_name, {})
        matrix[zone_name] = {}
        zone_total = 0.0

        for p in periods:
            T = _days_between(p["start"], p["end"]) / 365.0
            M = zone_soil.get(p["modulus_key"], 0)
            W = M * area_km2 * T
            matrix[zone_name][p["id"]] = round(W, 2)
            zone_total += W

        zone_totals[zone_name] = round(zone_total, 2)

    # 按时段汇总
    period_pred = {}  # {period_id: total_predicted}
    period_bg = {}    # {period_id: background_loss}
    period_new = {}   # {period_id: new_loss}

    for p in periods:
        T = _days_between(p["start"], p["end"]) / 365.0
        pred = sum(matrix[z["name"]][p["id"]] for z in zones)
        bg = bg_modulus * total_area_km2 * T
        period_pred[p["id"]] = round(pred, 2)
        period_bg[p["id"]] = round(bg, 2)
        period_new[p["id"]] = round(pred - bg, 2)

    # 总计
    total_pred = round(sum(period_pred.values()), 2)
    total_bg = round(sum(period_bg.values()), 2)
    total_new = round(total_pred - total_bg, 2)

    # 按分区的背景/新增
    zone_bg = {}
    zone_new = {}
    for z in zones:
        area_km2 = z["area_hm2"] / 100
        zbg = bg_modulus * area_km2 * total_T
        zone_bg[z["name"]] = round(zbg, 2)
        zone_new[z["name"]] = round(zone_totals[z["name"]] - zbg, 2)

    result = {
        "matrix": matrix,                  # {zone: {period: W}}
        "zone_totals": zone_totals,        # {zone: total_W}
        "zone_bg": zone_bg,                # {zone: bg_loss}
        "zone_new": zone_new,              # {zone: new_loss}
        "period_pred": period_pred,        # {period: pred}
        "period_bg": period_bg,            # {period: bg}
        "period_new": period_new,          # {period: new}
        "total_pred": total_pred,
        "total_bg": total_bg,
        "total_new": total_new,
        "bg_modulus": bg_modulus,
        "total_area_km2": total_area_km2,
        "total_T_years": round(total_T, 4),
        "periods": [
            {"id": p["id"], "name": p["name"],
             "T_years": round(_days_between(p["start"], p["end"]) / 365.0, 4)}
            for p in periods
        ],
    }

    state.Calc.erosion_df = result
    return result
