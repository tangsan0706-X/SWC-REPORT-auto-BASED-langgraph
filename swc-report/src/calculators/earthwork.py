"""C1 土方师 — 土方平衡计算。

输入: facts_v2.json 的 earthwork 和 zones
输出: 12 个 ew_* 标签值 → State.Calc.earthwork
"""

from __future__ import annotations
from src.state import GlobalState


def calc_earthwork(state: GlobalState) -> dict:
    """
    计算土方平衡。

    公式（工程语义正确版本）:
      可用挖方 = 挖方 - 表土剥离
      需填方   = 填方 - 表土回覆
      余方     = 可用挖方 - 需填方  (正=外运弃方, 负=需借方)

    返回:
      dict 写入 state.Calc.earthwork
    """
    ew = state.Static.meta["earthwork"]

    excavation = ew["excavation_m3"]        # 总挖方
    fill = ew["fill_m3"]                    # 总填方
    topsoil_strip = ew["topsoil_strip_m3"]  # 表土剥离
    topsoil_backfill = ew["topsoil_backfill_m3"]  # 表土回覆

    # 核心计算
    usable_cut = excavation - topsoil_strip      # 可用挖方
    need_fill = fill - topsoil_backfill          # 需填方
    surplus = usable_cut - need_fill             # 余方 (正=弃方)

    # 调入/调出
    borrow_in = 0.0       # 无借方 (has_borrow_area=false)
    export_out = max(surplus, 0.0)  # 余方外运

    result = {
        # 原始数据
        "excavation_m3": excavation,
        "fill_m3": fill,
        "topsoil_strip_m3": topsoil_strip,
        "topsoil_backfill_m3": topsoil_backfill,
        # 计算值
        "usable_cut_m3": usable_cut,
        "need_fill_m3": need_fill,
        "surplus_m3": surplus,
        "borrow_in_m3": borrow_in,
        "export_out_m3": export_out,
    }

    # 分区土方汇总
    zone_earthwork = []
    for z in state.ETL.zones:
        zone_earthwork.append({
            "name": z["name"],
            "excavation_m3": z.get("excavation_m3", 0),
            "fill_m3": z.get("fill_m3", 0),
        })
    result["zone_earthwork"] = zone_earthwork

    state.Calc.earthwork = result
    return result
