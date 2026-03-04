"""C3 造价师 — 水土保持投资估算。

输入: State.Measures + price_v2.csv + fee_rate_config.json
输出: ~80 个 c_* 标签 → State.Calc.cost_summary

计算流程:
  1. 每条措施 → 查单价表 → 直接费
  2. 直接费 → L1~L5 六层叠加 → 建安费
  3. 按类型(工程/植物/临时) × 来源(existing/planned) 分组汇总
  4. 独立费用: 管理费+监理费+科研+监测+验收
  5. 预备费: (一~四部分合计) × 6%
  6. 补偿费: 面积(m²) × 城市单价
"""

from __future__ import annotations
from src.state import GlobalState


def _build_price_lookup(price_table: list[dict]) -> dict[str, dict]:
    """构建 {措施名称: {人工, 材料, 机械, 合计单价}} 查找表。"""
    lookup = {}
    for row in price_table:
        name = row.get("措施名称", "").strip()
        if name:
            lookup[name] = {
                "labor": float(row.get("人工(元)", 0)),
                "material": float(row.get("材料(元)", 0)),
                "machinery": float(row.get("机械(元)", 0)),
                "unit_price": float(row.get("合计单价(元)", 0)),
            }
    return lookup


def _calc_layers(direct_cost: float, measure_type: str, fee_rate: dict) -> dict:
    """
    六层费率叠加计算。

    返回:
      dict 含各层费用和最终建安费
    """
    layers = fee_rate["fee_layers"]

    # L1 其他直接费
    r1 = layers["L1_其他直接费"]["rates"].get(measure_type, 0)
    L1 = direct_cost * r1

    # L2 现场经费
    r2 = layers["L2_现场经费"]["rates"].get(measure_type, 0)
    L2 = direct_cost * r2

    # 直接工程费 = 直接费 + L1 + L2
    direct_eng = direct_cost + L1 + L2

    # L3 间接费
    r3 = layers["L3_间接费"]["rates"].get(measure_type, 0)
    L3 = direct_eng * r3

    # L4 企业利润
    r4 = layers["L4_企业利润"]["rates"].get(measure_type, 0)
    L4 = (direct_eng + L3) * r4

    # L5 税金
    r5 = layers["L5_税金"]["rates"].get(measure_type, 0)
    L5 = (direct_eng + L3 + L4) * r5

    construction_cost = direct_eng + L3 + L4 + L5  # 建安费

    return {
        "direct_cost": direct_cost,
        "L1": L1, "L2": L2,
        "direct_eng": direct_eng,
        "L3": L3, "L4": L4, "L5": L5,
        "construction_cost": construction_cost,
    }


def _lookup_independent_fee(table: list[dict], value: float,
                            value_key: str, fee_key: str = "fee_万元") -> float:
    """在阶梯查找表中查找费用。"""
    for entry in table:
        if value <= entry[value_key]:
            return entry[fee_key]
    return table[-1][fee_key] if table else 0.0


def calc_cost(state: GlobalState) -> dict:
    """主计算入口。"""
    meta = state.Static.meta
    fee_rate = state.Static.fee_rate
    price_lookup = _build_price_lookup(state.Static.price_table)
    measures = state.Measures

    # ── 1. 每条措施计算建安费 ──
    measure_costs = []
    for m in measures:
        name = m.get("措施名称", m.get("name", ""))
        m_type = m.get("类型", m.get("type", "工程措施"))
        source = m.get("source", "planned")
        unit = m.get("单位", m.get("unit", ""))

        # 数量和单价
        qty = float(m.get("数量", m.get("quantity", 0)))
        # 尝试从单价表查找
        price_info = price_lookup.get(name, {})
        unit_price = price_info.get("unit_price", 0)
        # 如果措施自带单价，优先使用
        if "单价(元)" in m:
            unit_price = float(m["单价(元)"])

        direct_cost = qty * unit_price  # 直接费(元)
        direct_cost_wan = direct_cost / 10000  # 转换为万元

        # 六层叠加
        layers = _calc_layers(direct_cost_wan, m_type, fee_rate)

        measure_costs.append({
            "name": name,
            "type": m_type,
            "source": source,
            "unit": unit,
            "quantity": qty,
            "unit_price": unit_price,
            "direct_cost_wan": round(direct_cost_wan, 4),
            "construction_cost_wan": round(layers["construction_cost"], 4),
            **{k: round(v, 4) for k, v in layers.items()},
        })

    # ── 2. 分组汇总 ──
    groups = {
        ("工程措施", "existing"): [], ("工程措施", "planned"): [],
        ("植物措施", "existing"): [], ("植物措施", "planned"): [],
        ("临时措施", "existing"): [], ("临时措施", "planned"): [],
    }
    for mc in measure_costs:
        key = (mc["type"], mc["source"])
        if key in groups:
            groups[key].append(mc)

    def _sum_field(items, field):
        return round(sum(i[field] for i in items), 2)

    # 各类型合计
    c1_exist = _sum_field(groups[("工程措施", "existing")], "construction_cost_wan")
    c1_new = _sum_field(groups[("工程措施", "planned")], "construction_cost_wan")
    c1_total = round(c1_exist + c1_new, 2)

    c2_exist = _sum_field(groups[("植物措施", "existing")], "construction_cost_wan")
    c2_new = _sum_field(groups[("植物措施", "planned")], "construction_cost_wan")
    c2_total = round(c2_exist + c2_new, 2)

    c3_exist = _sum_field(groups[("临时措施", "existing")], "construction_cost_wan")
    c3_new = _sum_field(groups[("临时措施", "planned")], "construction_cost_wan")
    c3_total = round(c3_exist + c3_new, 2)

    c123_exist = round(c1_exist + c2_exist + c3_exist, 2)
    c123_new = round(c1_new + c2_new + c3_new, 2)
    c123_total = round(c1_total + c2_total + c3_total, 2)

    # 建安费合计 (用于独立费用基数)
    total_construction = c123_total

    # ── 3. 独立费用 ──
    indep = fee_rate["independent_fees"]

    # 建设管理费
    if_mgmt = round(total_construction * indep["建设管理费"]["rate"], 2)
    # 监理费
    if_supv = round(total_construction * indep["工程建设监理费"]["rate"], 2)
    # 科研勘测设计费 (按新增投资规模查表)
    if_design = _lookup_independent_fee(
        indep["科研勘测设计费"]["lookup_table"],
        c123_new, "max_investment_万元")
    # 监测费 (按扰动面积查表)
    if_monitor = _lookup_independent_fee(
        indep["水土保持监测费"]["lookup_table"],
        meta["land_area_hm2"], "max_area_hm2")
    # 验收费
    if_accept = indep["水土保持设施验收费"]["fee_万元"]

    c4_total = round(if_mgmt + if_supv + if_design + if_monitor + if_accept, 2)

    # ── 4. 合计与预备费、补偿费 ──
    c1234_total = round(c123_total + c4_total, 2)

    # 预备费
    reserve_rate = fee_rate["reserve_fee"]["rate"]
    c_contingency = round(c1234_total * reserve_rate, 2)

    # 补偿费
    city = meta["location"]["city"]
    comp_rates = fee_rate["compensation_fee"]["rates_by_city"]
    comp_rate_per_m2 = comp_rates.get(city, fee_rate["compensation_fee"]["default"])
    land_m2 = meta["land_area_hm2"] * 10000
    c_compensation = round(land_m2 * comp_rate_per_m2 / 10000, 2)  # 转万元

    c_grand_total = round(c1234_total + c_contingency + c_compensation, 2)

    # ── 5. 分年度投资 ──
    schedule = meta["schedule"]
    start_year = int(schedule["start_date"][:4])
    end_year = int(schedule["end_date"][:4])
    years = list(range(start_year, end_year + 1))
    n_years = len(years)

    # 简化分配: 工程/临时措施按年均分，植物措施集中最后一年，补偿费最后一年
    annual = {}
    for i, yr in enumerate(years):
        is_last = (i == n_years - 1)
        annual[yr] = {
            "c1": round(c1_total / n_years, 2),
            "c2": round(c2_total, 2) if is_last else 0.0,
            "c3": round(c3_total / n_years, 2),
            "c4": round(c4_total / n_years, 2),
            "cp": round(c_contingency / n_years, 2),
            "cc": round(c_compensation, 2) if is_last else 0.0,
        }
        yr_total = sum(annual[yr].values())
        annual[yr]["total"] = round(yr_total, 2)

    # ── 构建输出 ──
    result = {
        "measure_costs": measure_costs,
        # 第一部分 工程措施
        "c1_exist": c1_exist, "c1_new": c1_new, "c1_total": c1_total,
        "c1a_exist": c1_exist, "c1a_new": c1_new, "c1a_total": c1_total,
        "c1b_new": 0.0, "c1b_total": 0.0,
        # 第二部分 植物措施
        "c2_exist": c2_exist, "c2_new": c2_new, "c2_total": c2_total,
        # 第三部分 临时措施
        "c3_exist": c3_exist, "c3_new": c3_new, "c3_total": c3_total,
        "c3a_exist": c3_exist, "c3a_new": c3_new, "c3a_total": c3_total,
        "c3b_exist": 0.0, "c3b_new": 0.0, "c3b_total": 0.0,
        "c3c_new": 0.0, "c3c_total": 0.0,
        # 一~三部分
        "c123_exist": c123_exist, "c123_new": c123_new, "c123_total": c123_total,
        # 独立费用
        "if_mgmt": if_mgmt, "if_mgmt_exist": round(if_mgmt * c123_exist / max(c123_total, 0.01), 2),
        "if_mgmt_new": round(if_mgmt * c123_new / max(c123_total, 0.01), 2),
        "if_supv": if_supv, "if_supv_exist": round(if_supv * c123_exist / max(c123_total, 0.01), 2),
        "if_supv_new": round(if_supv * c123_new / max(c123_total, 0.01), 2),
        "if_design": if_design, "if_monitor": if_monitor, "if_accept": if_accept,
        "if_exist": round(if_mgmt * c123_exist / max(c123_total, 0.01) + if_supv * c123_exist / max(c123_total, 0.01), 2),
        "if_new": round(c4_total - (if_mgmt * c123_exist / max(c123_total, 0.01) + if_supv * c123_exist / max(c123_total, 0.01)), 2),
        "if_total": c4_total, "c4_total": c4_total,
        # 合计
        "c1234_total": c1234_total,
        "c_contingency": c_contingency,
        "c_compensation": c_compensation,
        "c_grand_total": c_grand_total,
        # 分年度
        "years": years,
        "annual": annual,
    }

    state.Calc.cost_summary = result
    return result
