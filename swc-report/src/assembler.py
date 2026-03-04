"""状态装配器 — 将 GlobalState 全部 7 个分区映射为 229 个模板标签。

输出的 TplCtx dict 直接传给 docxtpl.render()。
数值格式化: 面积 4 位小数(hm²)、流失量 2 位(t)、投资 2 位(万元)。
"""

from __future__ import annotations
import logging
import re
from datetime import datetime
from src.state import GlobalState

logger = logging.getLogger(__name__)


def _clean_chapter_text(text: str) -> str:
    """装配器端安全网：清洗 writer._sanitize_text() 遗漏的残留。

    覆盖: ===TAG===、Markdown标题、LLM元文本、docxtpl指令、工具引用、Markdown粗体。
    """
    if not text:
        return text
    # 移除残留的 ===TAG=== 标记
    text = re.sub(r"===\w+===", "", text)
    # 移除 Markdown 标题行 (### xxx)
    text = re.sub(r"^#{1,6}\s+.*$", "", text, flags=re.MULTILINE)
    # 移除残留 tag 名称行
    text = re.sub(r"^chapter\d+_\w+\s*$", "", text, flags=re.MULTILINE)
    # 移除 LLM 元文本行
    text = re.sub(r"^.*(?:请允许我|以上内容基于|以上信息均通过|如有需要|希望以上).*$", "", text, flags=re.MULTILINE)
    # 移除 docxtpl 模板指令泄露
    text = re.sub(r"(?:tr\s+for\s+\w+\s+in\s+\w+|tr\s+endfor)", "", text)
    # 移除裸露的工具调用文本
    text = re.sub(r"(?:calc_lookup|rag_search|self_checker|prev_chapter)\s*\(['\"][^'\"]*['\"]\)", "", text)
    # 移除内联工具引用 (括号内提及工具名)
    text = re.sub(r"[（(][^)）]*(?:calc_lookup|rag_search|self_checker|prev_chapter)[^)）]*[）)]", "", text)
    # 移除整行工具元文本
    text = re.sub(r"^.*(?:calc_lookup|rag_search).*工具.*(?:获取|确认).*$", "", text, flags=re.MULTILINE)
    # 移除 Markdown 粗体/斜体标记 (保留内部文字)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    # 压缩连续空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fmt_date(s: str) -> str:
    """'2023-08-01' → '2023年8月'"""
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
        return f"{d.year}年{d.month}月"
    except (ValueError, TypeError):
        return str(s)


def _f4(v) -> str:
    """面积格式化: 4位小数。"""
    return f"{float(v):.4f}"


def _f2(v) -> str:
    """投资/流失量格式化: 2位小数。"""
    return f"{float(v):.2f}"


def _f1(v) -> str:
    """百分比格式化: 1位小数。"""
    return f"{float(v):.1f}"


def _f0(v) -> str:
    """整数格式化。"""
    return f"{int(float(v))}"


def assemble(state: GlobalState) -> dict:
    """读取 GlobalState 所有分区，输出 TplCtx 字典 (229 key)。"""
    ctx = {}
    meta = state.Static.meta
    zones = state.ETL.zones
    ew = state.Calc.earthwork
    erosion = state.Calc.erosion_df
    cost = state.Calc.cost_summary
    benefit = state.Calc.benefit
    measures = state.Measures
    draft = state.Draft

    # ═══════════════════════════════════════════════════════════
    # 一、项目概况标签 (16个)
    # ═══════════════════════════════════════════════════════════
    ctx["project_name"] = meta["project_name"]
    ctx["construction_unit"] = meta["investor"]
    ctx["city"] = meta["location"]["city"]
    ctx["project_nature"] = meta.get("project_nature", "新建")
    ctx["total_investment"] = _f2(meta["total_investment_万元"])
    ctx["civil_investment"] = _f2(meta["civil_investment_万元"])
    ctx["total_land"] = _f4(meta["land_area_hm2"])
    ctx["permanent_land"] = _f4(meta["land_area_hm2"])  # 房地产=永久占地
    ctx["temporary_land"] = "0"  # 房地产无临时占地
    ctx["responsibility_area"] = _f4(meta["land_area_hm2"])
    ctx["construction_period"] = str(meta["schedule"]["construction_period_months"])
    ctx["start_date"] = _fmt_date(meta["schedule"]["start_date"])
    ctx["end_date"] = _fmt_date(meta["schedule"]["end_date"])
    ctx["design_level_year"] = str(meta.get("design_level_year", ""))
    ctx["prevention_standard"] = meta.get("prevention_level", "一级")
    ctx["greening_rate"] = str(meta.get("prevention_targets", {}).get("林草覆盖率", 27))

    # ═══════════════════════════════════════════════════════════
    # 二、分区面积标签 (7个)
    # ═══════════════════════════════════════════════════════════
    zone_names = ["建(构)筑物区", "道路广场区", "绿化工程区", "施工生产生活区", "临时堆土区"]
    zone_keys = ["z_建构筑物区", "z_道路广场区", "z_绿化区", "z_施工生活区", "z_临时堆土区"]
    zone_map = {z["name"]: z for z in zones}
    for zn, zk in zip(zone_names, zone_keys):
        z = zone_map.get(zn, {})
        ctx[zk] = _f4(z.get("area_hm2", 0))
    ctx["z_total"] = _f4(meta["land_area_hm2"])
    ctx["dig_total"] = _f0(meta["earthwork"]["excavation_m3"])
    ctx["fill_total"] = _f0(meta["earthwork"]["fill_m3"])

    # ═══════════════════════════════════════════════════════════
    # 三、土方平衡标签 (12个)
    # ═══════════════════════════════════════════════════════════
    ctx["ew_dig"] = _f0(ew.get("excavation_m3", 0))
    ctx["ew_fill"] = _f0(ew.get("fill_m3", 0))
    ctx["ew_strip"] = _f0(ew.get("topsoil_strip_m3", 0))
    ctx["ew_backfill"] = _f0(ew.get("topsoil_backfill_m3", 0))
    ctx["ew_in"] = _f0(ew.get("borrow_in_m3", 0))
    ctx["ew_out"] = _f0(ew.get("export_out_m3", 0))
    ctx["ew_surplus"] = _f0(ew.get("surplus_m3", 0))
    ctx["ew_dig_total"] = ctx["ew_dig"]
    ctx["ew_fill_total"] = ctx["ew_fill"]
    ctx["ew_in_total"] = ctx["ew_in"]
    ctx["ew_out_total"] = ctx["ew_out"]
    ctx["ew_surplus_total"] = ctx["ew_surplus"]

    # ═══════════════════════════════════════════════════════════
    # 四、侵蚀预测标签 (24个)
    # ═══════════════════════════════════════════════════════════
    pp = erosion.get("period_pred", {})
    pb = erosion.get("period_bg", {})
    pn = erosion.get("period_new", {})

    for pid in ("s1", "s2", "s3"):
        ctx[f"ep_{pid}_pred"] = _f2(pp.get(pid, 0))
        ctx[f"ep_{pid}_bg"] = _f2(pb.get(pid, 0))
        ctx[f"ep_{pid}_new"] = _f2(pn.get(pid, 0))

    ctx["ep_total_pred"] = _f2(erosion.get("total_pred", 0))
    ctx["ep_total_bg"] = _f2(erosion.get("total_bg", 0))
    ctx["ep_total_new"] = _f2(erosion.get("total_new", 0))

    # 按分区: 取流失量最大的 3 个分区
    zt = erosion.get("zone_totals", {})
    zbg = erosion.get("zone_bg", {})
    znew = erosion.get("zone_new", {})
    sorted_zones = sorted(zt.items(), key=lambda x: x[1], reverse=True)

    for i in range(3):
        if i < len(sorted_zones):
            zname, zpred = sorted_zones[i]
            ctx[f"ep_{i+1}_name"] = zname
            ctx[f"ep_{i+1}_pred"] = _f2(zpred)
            ctx[f"ep_{i+1}_bg"] = _f2(zbg.get(zname, 0))
            ctx[f"ep_{i+1}_new"] = _f2(znew.get(zname, 0))
        else:
            ctx[f"ep_{i+1}_name"] = ""
            ctx[f"ep_{i+1}_pred"] = _f2(0)
            ctx[f"ep_{i+1}_bg"] = _f2(0)
            ctx[f"ep_{i+1}_new"] = _f2(0)

    # ═══════════════════════════════════════════════════════════
    # 五、措施界定标签 (10个)
    # ═══════════════════════════════════════════════════════════
    def _measures_by_type_source(m_type, source=None):
        result = []
        for m in measures:
            mt = m.get("类型", m.get("type", ""))
            ms = m.get("source", "existing")
            if mt == m_type and (source is None or ms == source):
                result.append(m.get("措施名称", m.get("name", "")))
        return "、".join(result) if result else "无"

    ctx["def_eng_yes"] = _measures_by_type_source("工程措施")
    ctx["def_eng_no"] = "无"
    ctx["def_veg_yes"] = _measures_by_type_source("植物措施")
    ctx["def_veg_no"] = "无"
    ctx["def_tmp_yes"] = _measures_by_type_source("临时措施")
    ctx["def_tmp_no"] = "无"
    ctx["def_tmp2_yes"] = "无"
    ctx["def_tmp2_no"] = "无"

    # ═══════════════════════════════════════════════════════════
    # 六、措施布局标签 (10个)
    # ═══════════════════════════════════════════════════════════
    def _layout(zone_key, m_type, source):
        result = []
        for m in measures:
            mz = m.get("分区", m.get("zone", ""))
            mt = m.get("类型", m.get("type", ""))
            ms = m.get("source", "existing")
            if zone_key in mz and mt == m_type and ms == source:
                result.append(m.get("措施名称", m.get("name", "")))
        return "、".join(result) if result else "无"

    ctx["lo_主体_eng_exist"] = _layout("建(构)筑物区", "工程措施", "existing")
    ctx["lo_主体_eng_new"] = _layout("建(构)筑物区", "工程措施", "planned")
    ctx["lo_主体_veg_exist"] = _layout("建(构)筑物区", "植物措施", "existing")
    ctx["lo_主体_veg_new"] = _layout("建(构)筑物区", "植物措施", "planned")
    ctx["lo_主体_tmp_exist"] = _layout("建(构)筑物区", "临时措施", "existing")
    ctx["lo_主体_tmp_new"] = _layout("建(构)筑物区", "临时措施", "planned")
    ctx["lo_施工_eng_exist"] = _layout("施工生产生活区", "工程措施", "existing")
    ctx["lo_施工_eng_new"] = _layout("施工生产生活区", "工程措施", "planned")
    ctx["lo_施工_tmp_exist"] = _layout("施工生产生活区", "临时措施", "existing")
    ctx["lo_施工_tmp_new"] = _layout("施工生产生活区", "临时措施", "planned")

    # ═══════════════════════════════════════════════════════════
    # 七、造价投资标签 (~55个)
    # ═══════════════════════════════════════════════════════════
    cost_keys = [
        "c1_exist", "c1_new", "c1_total",
        "c1a_exist", "c1a_new", "c1a_total",
        "c1b_new", "c1b_total",
        "c2_exist", "c2_new", "c2_total",
        "c3_exist", "c3_new", "c3_total",
        "c3a_exist", "c3a_new", "c3a_total",
        "c3b_exist", "c3b_new", "c3b_total",
        "c3c_new", "c3c_total",
        "c123_exist", "c123_new", "c123_total",
        "c4_total", "c1234_total",
        "c_contingency", "c_compensation", "c_grand_total",
        "if_mgmt", "if_mgmt_exist", "if_mgmt_new",
        "if_supv", "if_supv_exist", "if_supv_new",
        "if_design", "if_monitor", "if_accept",
        "if_exist", "if_new", "if_total",
    ]
    for k in cost_keys:
        ctx[k] = _f2(cost.get(k, 0))

    # 分年度投资
    years = cost.get("years", [])
    annual = cost.get("annual", {})
    for i, yr in enumerate(years[:3]):
        ctx[f"year{i+1}"] = str(yr)
    # 填充到3年
    for i in range(len(years), 3):
        ctx[f"year{i+1}"] = ""

    for prefix in ("c1", "c2", "c3", "c4", "cp", "cc", "gt"):
        cost_key = prefix if prefix != "gt" else "total"
        total_val = 0.0
        for i, yr in enumerate(years[:3]):
            yr_data = annual.get(yr, {})
            val = yr_data.get(cost_key if cost_key != "total" else "total", 0)
            ctx[f"ay_{prefix}_y{i+1}"] = _f2(val)
            total_val += val
        ctx[f"ay_{prefix}"] = _f2(total_val)

    # ═══════════════════════════════════════════════════════════
    # 八、第1章综合说明标签 (7个)
    # ═══════════════════════════════════════════════════════════
    ctx["total_swc_investment"] = ctx["c_grand_total"]
    ctx["cost_engineering"] = ctx["c1_total"]
    ctx["cost_vegetation"] = ctx["c2_total"]
    ctx["cost_temporary"] = ctx["c3_total"]
    ctx["cost_independent"] = ctx["c4_total"]
    ctx["cost_contingency"] = ctx["c_contingency"]
    ctx["cost_compensation"] = ctx["c_compensation"]

    # ═══════════════════════════════════════════════════════════
    # 九、效益指标标签 (18个)
    # ═══════════════════════════════════════════════════════════
    indicators = benefit.get("indicators", {})
    indicator_names = [
        "水土流失治理度", "土壤流失控制比", "渣土防护率",
        "表土保护率", "林草植被恢复率", "林草覆盖率",
    ]
    short_names = ["治理度", "控制比", "渣土防护率", "表土保护率", "植被恢复率", "覆盖率"]

    for full, short in zip(indicator_names, short_names):
        ind = indicators.get(full, {})
        ctx[f"t_{short}"] = str(ind.get("target", ""))
        ctx[f"r_{short}"] = str(ind.get("actual", ""))
        ctx[f"ok_{short}"] = ind.get("status", "未计算")

    # ═══════════════════════════════════════════════════════════
    # 十、章节文本标签 (~30个)
    # ═══════════════════════════════════════════════════════════
    chapter_tags = [
        # 第1章
        "chapter1_brief", "chapter1_legal_basis", "chapter1_evaluation",
        "chapter1_prediction_summary", "chapter1_measures_summary",
        "chapter1_monitoring_summary", "chapter1_conclusion",
        # 第2章
        "chapter2_composition", "chapter2_construction_org",
        "chapter2_relocation", "chapter2_natural",
        # 第3章
        "chapter3_site_eval", "chapter3_layout_eval",
        "chapter3_measures_definition",
        # 第4章
        "chapter4_status", "chapter4_factors",
        "chapter4_prediction_text", "chapter4_hazard", "chapter4_guidance",
        # 第5章
        "chapter5_zone_division", "chapter5_layout",
        "chapter5_measures_detail", "chapter5_construction_req",
        # 第6章
        "chapter6_content_method", "chapter6_monitoring_points",
        "chapter6_implementation",
        # 第7章
        "chapter7_principles", "chapter7_basis",
        "chapter7_method", "chapter7_benefit",
        # 第8章
        "chapter8_1_组织管理", "chapter8_2_后续设计",
        "chapter8_3_水土保持监测", "chapter8_4_水土保持监理",
        "chapter8_5_水土保持施工", "chapter8_6_水土保持设施验收",
    ]
    for tag in chapter_tags:
        raw = draft.get(tag, "")
        cleaned = _clean_chapter_text(raw)
        if raw and len(cleaned) < len(raw) * 0.8:
            logger.debug(f"章节清洗 {tag}: {len(raw)}→{len(cleaned)} 字符 "
                         f"(削减 {len(raw) - len(cleaned)} 字符)")
        ctx[tag] = cleaned

    # ═══════════════════════════════════════════════════════════
    # 十一、循环表格 (6个)
    # ═══════════════════════════════════════════════════════════

    # 1. land_use_table — 临时堆土区等临时用地标注为"临时"
    _TEMP_KEYWORDS = ("临时", "堆土", "堆料", "弃渣", "取土")
    ctx["land_use_table"] = [
        {
            "zone": z["name"],
            "area": _f4(z["area_hm2"]),
            "type": "临时" if any(k in z["name"] for k in _TEMP_KEYWORDS) else "永久",
        }
        for z in zones
    ]

    # 2. existing_measures
    em_list = []
    for i, m in enumerate(state.Static.measures_existing, 1):
        em_list.append({
            "id": str(i),
            "name": m.get("措施名称", ""),
            "unit": m.get("单位", ""),
            "qty": m.get("数量", ""),
            "location": m.get("分区", ""),
            "cost": m.get("合价(万元)", ""),
        })
    ctx["existing_measures"] = em_list

    # 3. erosion_table
    erosion_rows = []
    matrix = erosion.get("matrix", {})
    for z in zones:
        row = {"zone": z["name"]}
        for pid in ("s1", "s2", "s3"):
            row[pid] = _f2(matrix.get(z["name"], {}).get(pid, 0))
        row["total"] = _f2(erosion.get("zone_totals", {}).get(z["name"], 0))
        erosion_rows.append(row)
    ctx["erosion_table"] = erosion_rows

    # 4. zone1_measures (建(构)筑物区)
    ctx["zone1_measures"] = _zone_measures_list("建(构)筑物区", measures)

    # 5. zone2_measures (道路广场区)
    ctx["zone2_measures"] = _zone_measures_list("道路广场区", measures)

    # 6. cost_detail_table
    mc = cost.get("measure_costs", [])
    cost_rows = []
    for i, item in enumerate(mc, 1):
        if item.get("source") == "planned":
            cost_rows.append({
                "id": str(i),
                "name": item["name"],
                "unit": item.get("unit", ""),
                "qty": str(item.get("quantity", "")),
                "price": _f2(item.get("unit_price", 0)),
                "total": _f2(item.get("construction_cost_wan", 0)),
            })
    ctx["cost_detail_table"] = cost_rows

    # ── 写入 State ──
    state.TplCtx = ctx
    return ctx


def _zone_measures_list(zone_name: str, measures: list[dict]) -> list[dict]:
    """构建分区措施列表（供模板循环）。"""
    result = []
    for m in measures:
        mz = m.get("分区", m.get("zone", ""))
        if zone_name in mz:
            result.append({
                "type": m.get("类型", m.get("type", "")),
                "name": m.get("措施名称", m.get("name", "")),
                "form": m.get("功能", m.get("function", "")),
                "location": zone_name,
                "period": "施工期" if m.get("类型", m.get("type", "")) == "临时措施" else "设计水平年",
                "qty": str(m.get("数量", m.get("quantity", ""))),
                "unit": m.get("单位", m.get("unit", "")),
            })
    return result
