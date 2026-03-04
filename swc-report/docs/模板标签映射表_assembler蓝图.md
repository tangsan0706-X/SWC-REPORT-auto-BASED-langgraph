# 模板标签 ↔ GlobalState 映射表（assembler.py 蓝图）

> 基于「水土保持方案报告书_Jinja2模板.docx」实际提取的 229 个标签 + 6 个循环语句。
> assembler.py 的唯一职责：读取 GlobalState 各分区数据，生成这张表右侧的值，输出 TplCtx 字典。

---

## 一、项目概况标签（16个）→ 来源：State.Static.meta (facts_v2.json)

| 模板标签 | GlobalState 路径 | 说明 |
|----------|-----------------|------|
| `project_name` | `meta.project_name` | 项目名称 |
| `construction_unit` | `meta.investor` | 建设单位 |
| `city` | `meta.location.city` | 城市 |
| `project_nature` | `meta.project_nature` | 项目性质（新建） |
| `total_investment` | `meta.total_investment_万元` | 项目总投资 |
| `civil_investment` | `meta.civil_investment_万元` | 土建投资 |
| `total_land` | `meta.land_area_hm2` | 总占地面积 |
| `permanent_land` | `meta.land_area_hm2`（房地产=永久占地） | 永久占地 |
| `temporary_land` | `0.0`（房地产项目无临时占地） | 临时占地 |
| `responsibility_area` | `meta.land_area_hm2` | 防治责任范围=总占地 |
| `construction_period` | `meta.schedule.construction_period_months` | 工期（月） |
| `start_date` | `meta.schedule.start_date` → 格式化 "YYYY年M月" | 开工日期 |
| `end_date` | `meta.schedule.end_date` → 格式化 | 竣工日期 |
| `design_level_year` | `meta.design_level_year` | 设计水平年 |
| `prevention_standard` | `meta.prevention_level` | 防治标准等级 |
| `greening_rate` | `meta.prevention_targets.林草覆盖率` | 绿化率目标 |

---

## 二、分区面积标签（7个）→ 来源：State.ETL.zones

| 模板标签 | GlobalState 路径 | 说明 |
|----------|-----------------|------|
| `z_建构筑物区` | `zones[0].area_hm2` | 建(构)筑物区面积 |
| `z_道路广场区` | `zones[1].area_hm2` | 道路广场区面积 |
| `z_绿化区` | `zones[2].area_hm2` | 绿化工程区面积 |
| `z_施工生活区` | `zones[3].area_hm2` | 施工生产生活区面积 |
| `z_临时堆土区` | `zones[4].area_hm2` | 临时堆土区面积 |
| `z_total` | `meta.land_area_hm2` | 合计 |
| `dig_total` / `fill_total` | `meta.earthwork.excavation_m3` / `fill_m3` | 总挖/填方 |

---

## 三、土方平衡标签（12个）→ 来源：State.Calc.earthwork

| 模板标签 | 计算逻辑 | 说明 |
|----------|----------|------|
| `ew_dig` | `earthwork.excavation_m3` | 挖方 |
| `ew_fill` | `earthwork.fill_m3` | 填方 |
| `ew_strip` | `earthwork.topsoil_strip_m3` | 表土剥离 |
| `ew_backfill` | `earthwork.topsoil_backfill_m3` | 表土回覆 |
| `ew_in` | `0`（无借方） | 调入 |
| `ew_out` | `earthwork.surplus_m3` if >0 else 0 | 调出（余方外运） |
| `ew_surplus` | `excavation - strip + backfill - fill` | 余方（正=弃方） |
| `ew_dig_total` | = `ew_dig` | 挖方合计（单分区=合计） |
| `ew_fill_total` | = `ew_fill` | 填方合计 |
| `ew_in_total` | = `ew_in` | 调入合计 |
| `ew_out_total` | = `ew_out` | 调出合计 |
| `ew_surplus_total` | = `ew_surplus` | 余方合计 |

---

## 四、侵蚀预测标签（24个）→ 来源：State.Calc.erosion_df

模板中按 **时段(s1/s2/s3)** 和 **分区(1~5)** 组织，另有合计行。

### 4.1 按时段汇总行（表7，11行×4列）

| 模板标签 | 含义 | 计算 |
|----------|------|------|
| `ep_s1_pred` | 已开工时段预测流失量(t) | Σ zones W[z][p1] |
| `ep_s1_bg` | 已开工时段背景流失量(t) | bg_modulus × total_area × T_p1 |
| `ep_s1_new` | 已开工时段新增流失量(t) | pred - bg |
| `ep_s2_pred` | 施工期预测流失量 | 同上逻辑 |
| `ep_s2_bg` | 施工期背景流失量 | |
| `ep_s2_new` | 施工期新增流失量 | |
| `ep_s3_pred` | 恢复期预测流失量 | |
| `ep_s3_bg` | 恢复期背景流失量 | |
| `ep_s3_new` | 恢复期新增流失量 | |
| `ep_total_pred` | 总预测流失量 | s1+s2+s3 |
| `ep_total_bg` | 总背景流失量 | |
| `ep_total_new` | 总新增流失量 | |

### 4.2 按分区汇总行

| 模板标签 | 含义 |
|----------|------|
| `ep_1_name` ~ `ep_3_name` | 分区名称（前3个分区，模板只列了3行明细） |
| `ep_1_pred` ~ `ep_3_pred` | 分区预测流失量 |
| `ep_1_bg` ~ `ep_3_bg` | 分区背景流失量 |
| `ep_1_new` ~ `ep_3_new` | 分区新增流失量 |

**注意**：模板表7只有3行分区明细 + 3行时段汇总 + 1行总计 = 固定结构。5个分区需要按时段横向聚合，或调整模板增加行。建议 assembler 做法：ep_1/2/3 分别对应5个分区中流失量最大的3个，其余合并为"其他"。或者把 erosion_table 循环改为5行。

---

## 五、措施界定标签（10个）→ 来源：State.Measures + 判断逻辑

| 模板标签 | 含义 | 计算逻辑 |
|----------|------|----------|
| `def_eng_yes` | 界定为水保的工程措施 | measures 中 type=工程措施 的描述 |
| `def_eng_no` | 不界定为水保的工程措施 | "无" 或 主体工程的非水保措施 |
| `def_veg_yes` | 界定为水保的植物措施 | |
| `def_veg_no` | 不界定为水保的植物措施 | |
| `def_tmp_yes` | 界定为水保的临时措施 | |
| `def_tmp_no` | 不界定为水保的临时措施 | |
| `def_tmp2_yes` | 第二类临时措施界定 | |
| `def_tmp2_no` | 第二类临时措施不界定 | |

---

## 六、措施布局标签（10个）→ 来源：State.Measures 按分区×类型统计

| 模板标签 | 含义 |
|----------|------|
| `lo_主体_eng_exist` | 建筑物区已有工程措施描述 |
| `lo_主体_eng_new` | 建筑物区新增工程措施描述 |
| `lo_主体_veg_exist` | 建筑物区已有植物措施 |
| `lo_主体_veg_new` | 建筑物区新增植物措施 |
| `lo_主体_tmp_exist` | 建筑物区已有临时措施 |
| `lo_主体_tmp_new` | 建筑物区新增临时措施 |
| `lo_施工_eng_exist` | 施工生活区已有工程措施 |
| `lo_施工_eng_new` | 施工生活区新增工程措施 |
| `lo_施工_tmp_exist` | 施工生活区已有临时措施 |
| `lo_施工_tmp_new` | 施工生活区新增临时措施 |

**生成逻辑**：遍历 measures_list，按 zone+type+source 分组，拼接名称列表字符串。

---

## 七、造价投资标签（约55个）→ 来源：State.Calc.cost_summary

### 7.1 投资估算总表（表12，15行×4列）

| 模板标签 | 含义 | 对应费率层 |
|----------|------|----------|
| `c1_exist` | 工程措施主体已列 | |
| `c1_new` | 工程措施方案新增 | |
| `c1_total` | 工程措施合计 | 第一部分 |
| `c1a_exist/new/total` | 其中：建安工程费 | L1~L5叠加后 |
| `c1b_new/total` | 其中：设备购置费 | 通常为0 |
| `c2_exist/new/total` | 植物措施 | 第二部分 |
| `c3_exist/new/total` | 临时措施 | 第三部分 |
| `c3a_exist/new/total` | 其中：临时防护 | |
| `c3b_exist/new/total` | 其中：临时拦挡 | |
| `c3c_new/total` | 其中：其他临时 | |
| `c123_exist/new/total` | 一~三部分小计 | |
| `c4_total` | 第四部分独立费用 | |
| `c1234_total` | 一~四部分合计 | |
| `c_contingency` | 基本预备费 | ×6% |
| `c_compensation` | 水保补偿费 | 面积×单价 |
| `c_grand_total` | **水保总投资** | 最终总计 |

### 7.2 独立费用明细表（表15，7行×4列）

| 模板标签 | 含义 |
|----------|------|
| `if_mgmt` / `if_mgmt_exist` / `if_mgmt_new` | 建设管理费 |
| `if_supv` / `if_supv_exist` / `if_supv_new` | 监理费 |
| `if_design` | 科研勘测设计费 |
| `if_monitor` | 监测费 |
| `if_accept` | 验收费 |
| `if_exist` / `if_new` / `if_total` | 独立费用合计 |

### 7.3 分年度投资表（表14，8行×5列）

| 模板标签 | 含义 |
|----------|------|
| `year1` / `year2` / `year3` | 年度标题（如 2023、2024、2025） |
| `ay_c1` / `ay_c1_y1` / `ay_c1_y2` / `ay_c1_y3` | 工程措施分年度 |
| `ay_c2` / `ay_c2_y1` ~ `ay_c2_y3` | 植物措施分年度 |
| `ay_c3` / `ay_c3_y1` ~ `ay_c3_y3` | 临时措施分年度 |
| `ay_c4` / `ay_c4_y1` ~ `ay_c4_y3` | 独立费用分年度 |
| `ay_cp` / `ay_cp_y1` ~ `ay_cp_y3` | 预备费分年度 |
| `ay_cc` / `ay_cc_y3` | 补偿费（通常全部计入最后一年） |
| `ay_gt` / `ay_gt_y1` ~ `ay_gt_y3` | 总投资分年度 |

**分年度逻辑**：按工期分配，施工期措施按年度均摊，植物措施集中在最后一年，补偿费在竣工年。

---

## 八、第1章综合说明标签（7个）→ 来源：State.Calc + 交叉引用

| 模板标签 | 含义 | 数据来源 |
|----------|------|----------|
| `total_swc_investment` | 水保总投资 | `= c_grand_total` |
| `cost_engineering` | 工程措施费 | `= c1_total` |
| `cost_vegetation` | 植物措施费 | `= c2_total` |
| `cost_temporary` | 临时措施费 | `= c3_total` |
| `cost_independent` | 独立费用 | `= c4_total` |
| `cost_contingency` | 预备费 | `= c_contingency` |
| `cost_compensation` | 补偿费 | `= c_compensation` |

---

## 九、效益指标标签（18个）→ 来源：State.Calc.benefit

| 模板标签 | 含义 | 来源 |
|----------|------|------|
| `t_治理度` | 目标值 | `prevention_targets.水土流失治理度` |
| `r_治理度` | 预测实现值 | `benefit.治理度_actual` |
| `ok_治理度` | 是否达标 | `"达标"` if actual >= target else `"未达标"` |
| `t_控制比` | 目标值 | |
| `r_控制比` | 预测值 | |
| `ok_控制比` | 达标判断 | |
| `t_渣土防护率` | 目标值 | |
| `r_渣土防护率` | 预测值 | |
| `ok_渣土防护率` | 达标判断 | |
| `t_表土保护率` | 目标值 | |
| `r_表土保护率` | 预测值 | |
| `ok_表土保护率` | 达标判断 | |
| `t_植被恢复率` | 目标值 | |
| `r_植被恢复率` | 预测值 | |
| `ok_植被恢复率` | 达标判断 | |
| `t_覆盖率` | 目标值 | |
| `r_覆盖率` | 预测值 | |
| `ok_覆盖率` | 达标判断 | |

---

## 十、章节文本标签（~30个）→ 来源：State.Draft（撰稿Agent输出）

### 第1章（7个子段）
| 模板标签 | Agent 生成内容 |
|----------|---------------|
| `chapter1_brief` | 项目概况简述 |
| `chapter1_legal_basis` | 编制依据（法规清单） |
| `chapter1_evaluation` | 水保评价概述 |
| `chapter1_prediction_summary` | 预测结论概述 |
| `chapter1_measures_summary` | 措施概述 |
| `chapter1_monitoring_summary` | 监测概述 |
| `chapter1_conclusion` | 综合结论 |

### 第2章（4个子段）
| `chapter2_composition` | 项目组成描述 |
| `chapter2_construction_org` | 施工组织描述 |
| `chapter2_relocation` | 拆迁安置描述 |
| `chapter2_natural` | 自然概况（气候/土壤/植被/水文） |

### 第3章（3个子段）
| `chapter3_site_eval` | 场址评价 |
| `chapter3_layout_eval` | 总平面布置评价 |
| `chapter3_measures_definition` | 措施界定说明文字 |

### 第4章（5个子段）
| `chapter4_status` | 扰动现状描述 |
| `chapter4_factors` | 预测因子说明 |
| `chapter4_prediction_text` | 预测计算过程文字 |
| `chapter4_hazard` | 危害分析 |
| `chapter4_guidance` | 指导意见 |

### 第5章（4个子段）
| `chapter5_zone_division` | 分区划分说明 |
| `chapter5_layout` | 措施总体布局 |
| `chapter5_measures_detail` | 措施详细设计描述 |
| `chapter5_construction_req` | 施工要求 |

### 第6章（3个子段）
| `chapter6_content_method` | 监测内容与方法 |
| `chapter6_monitoring_points` | 监测点位布设 |
| `chapter6_implementation` | 监测实施方案 |

### 第7章（4个子段）
| `chapter7_principles` | 编制原则 |
| `chapter7_basis` | 编制依据 |
| `chapter7_method` | 编制方法 |
| `chapter7_benefit` | 效益分析文字 |

### 第8章（6个子段）
| `chapter8_1_组织管理` | 组织管理保障 |
| `chapter8_2_后续设计` | 后续设计保障 |
| `chapter8_3_水土保持监测` | 监测保障 |
| `chapter8_4_水土保持监理` | 监理保障 |
| `chapter8_5_水土保持施工` | 施工保障 |
| `chapter8_6_水土保持设施验收` | 验收保障 |

---

## 十一、循环表格（6个）→ 来源：State.Measures + State.Calc

| 循环语句 | 循环变量字段 | 数据来源 |
|----------|-------------|----------|
| `{%tr for row in land_use_table %}` | `row.zone`, `row.area`, `row.type` | zones → [{zone, area, "永久"}] |
| `{%tr for em in existing_measures %}` | `em.id`, `em.name`, `em.unit`, `em.qty`, `em.location`, `em.cost` | measures where source=existing |
| `{%tr for row in erosion_table %}` | 需确认模板内部结构 | erosion_df 展平 |
| `{%tr for m in zone1_measures %}` | `m.type`, `m.name`, `m.form`, `m.location`, `m.period`, `m.qty`, `m.unit` | measures where zone=建(构)筑物区 |
| `{%tr for m in zone2_measures %}` | 同上 | measures where zone=道路广场区（或第二个分区） |
| `{%tr for cd in cost_detail_table %}` | `cd.id`, `cd.name`, `cd.unit`, `cd.qty`, `cd.price`, `cd.total` | measures_planned → 投资明细 |

---

## 十二、assembler.py 输出结构

```python
def assemble(state: GlobalState) -> dict:
    """
    读取 GlobalState 所有分区，输出 TplCtx 字典。
    这个字典直接传给 docxtpl.render(tpl_ctx)。
    """
    ctx = {}

    # 1. 项目概况 (16个)
    ctx["project_name"] = state.Static.meta["project_name"]
    ctx["construction_unit"] = state.Static.meta["investor"]
    # ... 共16个

    # 2. 分区面积 (7个)
    # ... 从 zones 映射

    # 3. 土方平衡 (12个)
    # ... 从 Calc.earthwork 映射

    # 4. 侵蚀预测 (24个)
    # ... 从 Calc.erosion_df 映射

    # 5. 造价投资 (55个)
    # ... 从 Calc.cost_summary 映射

    # 6. 效益指标 (18个)
    # ... 从 Calc.benefit 映射

    # 7. 章节文本 (30个)
    # ... 从 Draft 映射

    # 8. 循环列表 (6个)
    ctx["land_use_table"] = [...]
    ctx["existing_measures"] = [...]
    ctx["zone1_measures"] = [...]
    ctx["zone2_measures"] = [...]
    ctx["cost_detail_table"] = [...]
    ctx["erosion_table"] = [...]

    # 9. 第1章交叉引用 (7个)
    ctx["total_swc_investment"] = ctx["c_grand_total"]
    # ...

    return ctx  # 共229个key
```

---

## 注意事项

1. **标签名不要改**：模板已定义好的 229 个标签名是最终版，assembler 输出的 key 必须精确匹配
2. **数值格式化**：面积保留4位小数(hm²)、流失量保留2位(t)、投资保留2位(万元)
3. **中文标签**：`ok_治理度` 等含中文的标签完全合法，docxtpl 支持
4. **循环变量**：循环内的字段名（如 `em.name`）由 list[dict] 的 key 决定，必须匹配
