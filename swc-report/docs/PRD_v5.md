# 水土保持方案自动生成系统 — 产品需求文档 (PRD)

> **文档编号**: SWCP-PRD-2026-001
> **版本**: v5.0 — 4-Agent Architecture + AutoDL 一键部署
> **日期**: 2026-02-12
> **密级**: 内部

---

## 修订记录

| 版本 | 日期 | 修订人 | 修订内容 |
|------|------|--------|----------|
| v1.0 | 2026-02-09 | 作者 | 初稿，基础架构设计 |
| v2.0 | 2026-02-10 | Claude | 补充6层费率引擎、229模板标签映射、状态装配器、双轨校验 |
| v3.0 | 2026-02-10 | Claude | 重组处理层为编制集群+审计集群，审计智能体替代原双轨校验 |
| v4.0 | 2026-02-10 | Claude | 新增措施规划师Agent、撰稿升级为Agent、11个工具定义、GPU分配方案、完整前后端规格 |
| v5.0 | 2026-02-12 | Claude | **新增绘图智能体(4工具)**、技术栈对齐实际代码(Vue3/SQLite)、GPTQ-Int8双实例GPU方案、AutoDL一键部署、措施图渲染引擎、17步流水线完整定义 |

---

## 目录

1. [产品概述](#1-产品概述)
2. [系统架构](#2-系统架构)
3. [数据规格](#3-数据规格)
4. [计算引擎详细规格](#4-计算引擎详细规格)
5. [智能体详细规格](#5-智能体详细规格)
6. [前端详细规格](#6-前端详细规格)
7. [后端API详细规格](#7-后端api详细规格)
8. [报告模板与渲染规格](#8-报告模板与渲染规格)
9. [部署规格](#9-部署规格)
10. [非功能性需求](#10-非功能性需求)
11. [实施计划](#11-实施计划)

---

# 1 产品概述

## 1.1 产品定位

本系统是一套面向水土保持咨询机构的自动化方案编制工具。系统接收项目基本信息、已有措施清单等输入数据，通过计算引擎完成土方平衡、侵蚀预测、造价估算等确定性计算，再由多智能体协作完成措施规划、报告撰写、措施图绘制和质量审计，最终输出符合《生产建设项目水土保持方案编制技术规范》(GB/T 51240) 的完整方案报告书 (.docx) 及附图包 (.zip)。

## 1.2 目标用户

水土保持咨询公司的方案编制工程师。典型使用场景：接到房地产/市政/工业项目的水保方案编制委托后，工程师将设计院提供的项目概况和施工图中的已有措施信息录入系统，系统在 10-15 分钟内生成初稿，工程师在此基础上人工修改和完善。

## 1.3 核心价值主张

**将一份水保方案的编制周期从 3-5 个工作日压缩至 1 小时以内（含人工审校）。**

当前行业痛点：一份标准的水保方案报告书约 80-120 页，包含 20+ 张专业计算表格、8 个章节的技术文本、7+ 张附图。即使是经验丰富的工程师，从零编制也需要 3-5 天。其中约 70% 的工作量是重复性的计算填表和格式化文本，本系统自动完成这 70%。

## 1.4 产品范围

### 1.4.1 MVP 范围（本版本）

仅支持**江苏省内的房地产类开发建设项目**。原因：房地产项目的分区模式和措施体系相对标准化，江苏省的地方标准和费率体系已完成数据采集。

### 1.4.2 后续扩展方向

市政道路项目 → 工业项目 → 线性工程（公路/管线） → 多省份支持。每新增一个项目类型需要：新增措施库模板、调整计算参数、训练对应的 RAG 语料。

## 1.5 系统边界

| 维度 | 系统负责 | 系统不负责 |
|------|----------|------------|
| 计算 | 土方平衡、侵蚀预测(RUSLE查表)、6层费率造价、效益分析 | 精确的 RUSLE 因子推导（使用查表近似值） |
| 措施 | Agent 根据分区特征+标准库+空间布局智能规划新增措施 | 施工图级别的措施详细设计 |
| 制图 | Drawing Agent 生成措施分区图/总布置图/详图/断面图 | CAD 级别的精确制图 |
| 文本 | 8 章全文初稿生成、数字引用自动对齐 | 法律条文的有效性验证 |
| 审计 | 数值一致性校验、文本幻觉检测、范文结构对比 | 替代人工专家终审 |
| 输出 | .docx 报告书 + 措施图 PNG + 审计日志.json | PDF 盖章版、在线协作编辑 |

## 1.6 关键指标

| 指标 | MVP 目标 | 量产目标 | 度量方式 |
|------|----------|----------|----------|
| 生成耗时 | ≤15 分钟 | ≤8 分钟 | API 返回到下载可用 |
| 审计通过率 | ≥60% 章节首次通过 | ≥85% | 审计智能体评分 ≥80 |
| 数值一致性 | 100% | 100% | Python 硬校验 0 错误 |
| 人工修改量 | ≤30% 页面需修改 | ≤15% | 人工审校后差异统计 |
| 模板覆盖率 | 12 张核心表格 | 20+ 张表格 | 非空表格 / 总表格 |
| 措施图生成率 | ≥4 张/项目 | ≥8 张/项目 | Drawing Agent 成功数 |
| 并发能力 | 1 个项目/次 | 3 个项目/次 | 队列吞吐 |

---

# 2 系统架构

## 2.1 架构总览

系统采用分层架构，共 7 层。数据从前端上传经 API 进入输入层，预处理后写入全局状态机，处理层的编制集群和审计集群协作完成方案编制，最终渲染输出存储交付。

### 2.1.1 七层架构

| 层级 | 名称 | 技术栈 | 职责 |
|------|------|--------|------|
| L0 | 前端层 | Vue 3 + Vite + Element Plus | 双端口 SPA：用户端(:8080)报告生成 + 管理端(:8081)知识库/设置 |
| L1 | 后端 API 层 | FastAPI + uvicorn (双端口) | REST API、SSE 进度推送、文件上传 |
| L2 | 输入层 | JSON/CSV/文件存储 | 用户输入 + 系统配置 + 可选文件的统一入口 |
| L3 | 预处理层 | geopandas/ezdxf/ChromaDB/VL Agent | CAD 转图、GIS 解析、RAG 语料构建、VL 空间分析、图集 RAG 索引 |
| L4 | 全局状态机 | Python dataclass (7分区) | Static/ETL/Calc/TplCtx/Draft/Measures/Flags |
| L5 | 处理层 | 2 集群 × 4 智能体 × 17 工具 | 编制集群（计算+规划+撰稿+制图+渲染）+ 审计集群（审计 Agent） |
| L6 | 存储交付层 | 本地文件系统 + SQLite | 文件存储、历史记录、运行日志 |

### 2.1.2 处理层内部结构

处理层是系统核心，内含两个集群：

**编制集群 (Compilation Cluster)**

负责方案的实际编制工作。内含子模块按 17 步流水线执行：

```
Step 1-3:  输入加载 + 预处理 + 空间分析
Step 4-5:  计算 Phase1（土方师 + 预测师）
Step 6:    措施规划师 Agent（决策新增措施 + 空间布置）
Step 7-8:  计算 Phase2（造价师 + 效益分析）
Step 9:    状态装配器（Calc → 229 模板标签）
Step 10:   撰稿智能体 Agent（逐章生成）
Step 11:   数据图表生成（4张: erosion/pie/bar/zone）
Step 12:   绘图智能体 Agent → fallback MeasureMapRenderer
Step 13:   docxtpl 渲染 + 循环表格 + 措施图后插入
```

**审计集群 (Audit Cluster)**

```
Step 14:   审计智能体（全文质量审查）
Step 15:   章节级重试（仅回弹失败章节给撰稿人重写）
Step 16:   最终渲染
Step 17:   打包输出
```

审计智能体通过 3 个工具（数值校验/文本校验/范文对比）评估质量，给出 0-100 分评分：

- **≥80 分**：通过 → 直接进入存储交付
- **60-79 分**：生成修改指令 → 仅回弹失败章节给撰稿人重写（每章最多 3 次）
- **<60 分**：强制通过 → 标记需人工复核

**审计退回闭环**：审计智能体生成的精准 feedback（chapter_id + 问题原因 + 期望值 + 修改指令）直接传给撰稿智能体，撰稿人仅重新生成失败章节，不影响已通过章节。

## 2.2 智能体总览

系统包含 **4 个智能体 (Agent)** 和 **17 个工具 (Tool)**，全部基于 Qwen2.5-72B-Instruct-GPTQ-Int8，通过 vLLM 部署。

| 智能体 | 所属集群 | 角色 | 工具数 | vLLM 实例 |
|--------|----------|------|--------|-----------|
| 措施规划师 | 编制集群 | 根据分区特征+侵蚀数据+空间布局+标准库，决策新增措施的类型/数量/位置/空间布置 | 6 | Text (GPU 0-1) |
| 撰稿智能体 | 编制集群 | 逐章生成报告文本，自主检索范文、查询计算结果、自查数字引用 | 4 | Text (GPU 0-1) |
| 绘图智能体 | 编制集群 | 根据项目数据和制图规范，LLM 编写 matplotlib 代码生成措施图，VL 模型验证质量 | 4 | Text (GPU 0-1) + VL (GPU 2-3) |
| 审计智能体 | 审计集群 | 审查全文质量，调用校验工具，打分，生成精准修改指令 | 3 | Text (GPU 0-1) |

## 2.3 技术选型

| 组件 | 技术选择 | 选择理由 |
|------|----------|----------|
| LLM 推理 | vLLM + Qwen2.5-72B-Instruct-GPTQ-Int8 | 72B 参数量水保专业表现优秀；GPTQ-Int8 量化 2 卡可跑；vLLM 连续批处理 |
| 视觉模型 | Qwen2.5-VL-72B-Instruct-GPTQ-Int8 | CAD 空间分析 + 图集索引 + 措施图 VL 验证 |
| 向量数据库 | ChromaDB (双库) | 范文 RAG (chromadb/) + 图集 RAG (atlas_db/)，轻量、Python 原生集成 |
| Embedding | sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 多语言支持、中文表现优秀、轻量 |
| 文档渲染 | docxtpl + python-docx | Phase1: Jinja2 变量替换; Phase2: 手动循环表格填充; Phase3: 措施图后插入 |
| 图表生成 | matplotlib | 数据图表 (Sankey/Pie/Bar/Zone) + Drawing Agent 措施图 (matplotlib 代码生成) |
| 前端框架 | Vue 3 + Vite + Element Plus | 轻量 SPA、Element Plus 丰富组件库、Vite 快速构建 |
| 后端框架 | FastAPI + uvicorn (双端口) | 异步支持、SSE 推送、自动 API 文档 |
| 数据库 | SQLite (server.db) | MVP 阶段轻量存储，无需独立部署 |
| 文件存储 | 本地文件系统 (data/) | MVP 阶段简单可靠，后续可迁移到 OSS/MinIO |
| GIS 处理 | geopandas + shapely（可选） | 仅在用户上传 .shp 文件时启用 |
| 模型下载 | ModelScope (国内直连) | AutoDL 无法访问 HuggingFace，ModelScope 国内镜像 |

## 2.4 GPU 部署方案

**硬件**：AutoDL 4×A800-80G（或 4×RTX 6000 Ada 48G）

**部署策略**：双 vLLM 实例常驻，所有 Agent 共享同一 Text 实例。

| vLLM 实例 | GPU 分配 | 模型 | 端口 | 用途 |
|-----------|----------|------|------|------|
| Text LLM | GPU 0-1 (TP=2) | Qwen2.5-72B-Instruct-GPTQ-Int8 | 8000 | 规划/撰稿/审计/绘图 4 个 Agent 共用 |
| VL Model | GPU 2-3 (TP=2) | Qwen2.5-VL-72B-Instruct-GPTQ-Int8 | 8001 | CAD 空间分析 + 图集索引 + 措施图验证 |

**关键设计**：
- 4 个 Agent 均使用同一个 Text vLLM 实例 (port 8000)，仅切换 system prompt 角色
- VL 模型仅在空间分析 (Step 3) 和措施图验证 (Step 12) 时调用
- GPTQ-Int8 量化: 72B 模型仅需 ~40GB 显存，2 卡轻松运行
- `max-model-len=32768` (Text) / `16384` (VL)

---

# 3 数据规格

## 3.1 用户必填输入

### 3.1.1 项目概况表 facts_v2.json

由前端表单自动生成。用户填写基本信息后，前端自动构建 JSON 并校验。

| 字段路径 | 类型 | 必填 | 说明 |
|----------|------|------|------|
| `project_name` | string | 是 | 项目全称，如"XX花园住宅项目" |
| `location.province` | string | 是 | MVP 固定为"江苏省" |
| `location.city` | string | 是 | 地级市名称，用于查询 soil_map 和 climate_db |
| `location.district` | string | 是 | 区/县名称 |
| `location.address` | string | 是 | 详细地址 |
| `location.longitude` | float | 否 | 经度，有 GIS 时自动填充 |
| `location.latitude` | float | 否 | 纬度，有 GIS 时自动填充 |
| `investor` | string | 是 | 建设单位名称 |
| `total_investment_万元` | float | 是 | 项目总投资（万元） |
| `land_area_hm2` | float | 是 | 总占地面积（hm²） |
| `construction_area_m2` | float | 是 | 总建筑面积（m²） |
| `earthwork.excavation_m3` | float | 是 | 总挖方量（m³） |
| `earthwork.fill_m3` | float | 是 | 总填方量（m³） |
| `earthwork.topsoil_strip_m3` | float | 是 | 表土剥离量（m³） |
| `earthwork.topsoil_backfill_m3` | float | 是 | 表土回覆量（m³） |
| `schedule.start_date` | date | 是 | 开工日期 YYYY-MM-DD |
| `schedule.end_date` | date | 是 | 竣工日期 YYYY-MM-DD |
| `schedule.plan_submit_date` | date | 是 | 方案编制基准日期 |
| `zones[].name` | string | 是 | 分区名称（见下方枚举） |
| `zones[].area_hm2` | float | 是 | 分区面积（hm²），前端校验 ∑=land_area_hm2 |
| `zones[].excavation_m3` | float | 否 | 分区挖方量 |
| `zones[].fill_m3` | float | 否 | 分区填方量 |
| `prevention_level` | string | 是 | 防治标准等级：一级/二级/三级 |
| `design_level_year` | int | 是 | 设计水平年（通常=竣工年+1） |

**分区名称枚举**（房地产项目标准 5 分区）：建(构)筑物区、道路广场区、绿化工程区、施工生产生活区、临时堆土区。

### 3.1.2 已列措施清单 measures_v2.csv

用户从主体工程设计资料中提取已有水保措施，按以下格式上传 CSV：

| 措施名称 | 分区 | 类型 | 单位 | 数量 | 单价(元) | 合价(万元) |
|----------|------|------|------|------|----------|------------|
| 排水沟C20 | 建(构)筑物区 | 工程措施 | m | 320 | 400.00 | 12.80 |
| 场地绿化 | 绿化工程区 | 植物措施 | hm² | 1.17 | 500000 | 58.50 |
| 临时覆盖 | 临时堆土区 | 临时措施 | m² | 1500 | 25.00 | 3.75 |

**字段约束**：
- `类型`字段仅允许 3 个值：工程措施、植物措施、临时措施
- `分区`必须匹配 facts_v2.json 中 zones[].name
- `合价`是后续区分"主体已列投资"和"方案新增投资"的关键

## 3.2 系统内置数据

### 3.2.1 土壤侵蚀模数映射表 soil_map.json

按城市 × 分区类型 × 时段存储 RUSLE 查表结果。MVP 阶段使用查表值（不做因子级计算），但保留因子字段以便后续升级。

```json
{
  "南通市": {
    "建(构)筑物区": {
      "background_modulus": 250,
      "construction_modulus": 5000,
      "recovery_modulus": 800,
      "allowable_modulus": 500
    }
  }
}
```

### 3.2.2 造价信息价 price_v2.csv

按措施名称存储单价信息，含人工/材料/机械分项明细。约 50 条记录覆盖常见水保措施。

| 措施名称 | 单位 | 人工(元) | 材料(元) | 机械(元) | 合计单价(元) | 适用类型 |
|----------|------|----------|----------|----------|--------------|----------|
| 排水沟C20 | m | 80 | 280 | 40 | 400 | 工程措施 |
| 截水沟C20 | m | 90 | 310 | 50 | 450 | 工程措施 |
| 撒播草籽 | m² | 5 | 12 | 3 | 20 | 植物措施 |

### 3.2.3 费率配置 fee_rate_config.json

6 层费率叠加体系的完整参数：

| 费率层级 | 计算基数 | 工程措施费率 | 植物措施费率 | 临时措施费率 |
|----------|----------|-------------|-------------|-------------|
| L1 其他直接费 | 直接费 | 2.3% | 2.3% | 2.3% |
| L2 现场经费 | 直接费 | 5.0% | 4.0% | 4.0% |
| L3 间接费 | 直接工程费 | 5.5% | 3.3% | 3.3% |
| L4 企业利润 | 直接工程费+间接费 | 7.0% | 5.0% | 5.0% |
| L5 税金 | 前四项合计 | 9.0% | 9.0% | 9.0% |
| L6 独立费用 | 建安费合计 | 建设管理费2%+监理费3%+科研勘测设计费+监测费+验收费 | 同左 | 同左 |

**L6 独立费用明细**：
- 建设管理费：建安费 × 2%
- 工程建设监理费：建安费 × 3%
- 科研勘测设计费：查表（按投资规模分档）
- 水土保持监测费：查表（按扰动面积分档）
- 水土保持设施验收费：查表
- 水土保持补偿费：占地面积 × 地区单价（如盐城 1.0 元/m²）

**预备费**：(一至四部分合计) × 6%

### 3.2.4 标准措施库 measure_library.json

35 种标准水保措施，按分区类型和措施类型分类。措施规划师 Agent 从此库中选取候选措施。

### 3.2.5 措施符号与样式 measure_symbols.py

措施图绘制的标准化配置：
- **符号定义**：每种措施类型的 matplotlib 图形符号（形状、颜色、大小）
- **样式规范**：线型、字体、颜色配置（SL73_6-2015 标准）
- **断面模板**：排水沟/截水沟/挡土墙等典型断面的参数化绘图模板
- **分区底色**：5 种分区的标准底色 RGBA 值

### 3.2.6 法规引用库 legal_refs.json

结构化存储所有需引用的法规和技术标准，避免 LLM 幻觉生成错误编号。约 40 条记录，按章节关联。

### 3.2.7 报告模板 template.docx

使用 docxtpl（Jinja2 语法）的 Word 模板，预置 **229 个标签位**。

**标签分类统计**：

| 标签类别 | 数量 | 示例 |
|----------|------|------|
| 项目概况 (facts→) | 16 | `{{project_name}}`, `{{location_city}}` |
| 分区面积 (zones→) | 6 | `{{z1_name}}`, `{{z1_area}}` |
| 土方平衡 (ew→) | 12 | `{{ew_excavation}}`, `{{ew_net_cut}}` |
| 侵蚀预测 (ep→) | 20 | `{{ep_z1_p1}}`, `{{ep_total}}` |
| 造价投资 (c→) | 80 | `{{c_eng_new}}`, `{{c_total}}` |
| 效益指标 (bf→) | 12 | `{{bf_治理度_actual}}`, `{{bf_治理度_target}}` |
| 措施列表 (循环) | 4 组 | 手动循环表格填充 (python-docx) |
| 章节文本 (draft→) | 8 | `{{ch1_text}}`, `{{ch2_text}}` |
| 其他 (附图/日期) | 71 | `{{submit_date}}`, `{{attachment_list}}` |

**12 张核心表格**：

| 表号 | 表名 | 渲染方式 | 数据来源 |
|------|------|----------|----------|
| 表 2-1 | 土方平衡表 | 固定行标签 | Calc.earthwork |
| 表 3.2-1 | 主体已列措施汇总表 | python-docx 循环行 | Measures(source=existing) |
| 表 3.2-2 | 主体已列措施投资表 | python-docx 循环行 | Measures(source=existing) |
| 表 4.3-1 | 侵蚀预测因子表 | 固定行标签 | soil_map 查表值 |
| 表 4.3-10 | 土壤流失预测总表 | zones×periods 矩阵标签 | Calc.erosion_df |
| 表 5.1-1 | 防治分区面积表 | 固定行标签 | State.ETL.zones |
| 表 5.3-1 | 方案新增措施汇总表 | python-docx 循环行 | Measures(source=planned) |
| 表 7.1-1 | 投资估算总表 | 固定行标签+循环行 | Calc.cost_summary |
| 表 7.1-2 | 分类投资表 | 固定行标签 | Calc.cost_summary |
| 表 7.1-3 | 分年度投资表 | 固定行标签 | Calc.cost_summary |
| 表 8.1-1 | 防治效果预测表 | 固定行标签 | Calc.benefit |
| 表 8.2-1 | 六项指标达标表 | 固定行标签 | Calc.benefit |

### 3.2.8 范文语料库 ChromaDB (chromadb/)

预加载 3-5 份已审批的优质方案报告，按章节切分为约 500 条文本块。每条文本块带元数据标签。

### 3.2.9 制图标准知识库 (data/atlas/)

20 个文件，包含：
- **制图标准**: SL73_6-2015 水利水电工程制图标准·水土保持图
- **标准化图集**: 标准图集(md+docx)
- **技术标准**: GB50433-2018, GB50434-2018, DB64T
- **法规**: 江苏省水土保持条例、管理办法
- **范文**: 报批稿、标准厂房报告书、房地产项目方案
- **CAD**: 水土保持措施典型设计图.dwg
- **规划**: 江苏/南京/南通/盐城 水土保持规划

通过 atlas_rag.py 分块索引到 ChromaDB (atlas_db/)，支持文本+图片+CAD 的混合检索。

## 3.3 可选输入

| 文件类型 | 用途 | 不提供时的 Fallback | 处理模块 |
|----------|------|---------------------|----------|
| CAD .dwg/.dxf | 转 PNG 供 VL Agent 分析场地形态 | 使用模板化矩形近似布局 | ezdxf/ODA → VL 分析 |
| GIS .shp/.geojson | 自动提取分区面积并与手填值容差校验 | 直接使用 facts.zones 手填值 | geopandas → spatial_analyzer |
| PDF 附件 | 补充到 RAG 语料库供撰稿参考 | RAG 仅使用内置范文库 | pdfplumber → ChromaDB |
| 标准图集 PNG/JPG/PDF | VL 分析绘图规范，供 Drawing Agent 参考 | 使用内置 measure_symbols 样式 | atlas_rag VL 索引 |

## 3.4 全局状态机 GlobalState

整个流水线的数据总线。所有模块通过读写 GlobalState 通信，不直接传递数据。

| 分区 | 类型 | 内容 |
|------|------|------|
| Static | StaticData | meta(facts_v2), soil_map, price_table, fee_rate, legal_refs, measure_library, measures_existing |
| ETL | ETLData | zones(标准化分区), rag_ready, site_desc, spatial_layout(VL+GIS空间分析), gis_gdf(GeoDataFrame), measure_layout(规划空间布置) |
| Calc | CalcData | earthwork(土方平衡), erosion_df(侵蚀预测矩阵), cost_summary(造价汇总), benefit(效益分析) |
| TplCtx | dict | 229 个模板标签的完整字典，由状态装配器生成 |
| Draft | dict | chapters: {chapter_id: text}，撰稿智能体输出的 8 章文本 |
| Measures | list | full_measures_list: 已有措施 + Agent 新增措施的合并清单（含空间布置字段） |
| Flags | dict | retry_count, failed_list, audit_score, audit_log |

---

# 4 计算引擎详细规格

计算引擎是纯 Python 确定性逻辑，**不涉及 LLM**，保证 100% 可复现。分为 Phase1（基础数据）和 Phase2（基于措施）两阶段，中间插入措施规划师 Agent。

## 4.1 Phase1: 土方师

根据 facts_v2.json 中的土方数据计算土方平衡。

**核心公式**：

```
净挖方 = 挖方量 - 表土剥离量 + 表土回覆量
余方量 = 净挖方 - 填方量  （正值为弃方，负值为借方）
表土利用率 = 表土回覆量 / 表土剥离量 × 100%
```

**输出到 State.Calc.earthwork**：分区级和项目级的挖方/填方/剥离/回覆/净挖/余方/利用率共 12 个标签。

## 4.2 Phase1: 预测师

按分区 × 时段计算土壤流失量预测矩阵。

### 4.2.1 三时段自动切分

根据 schedule 中的日期自动切分：

| 时段 | 起止 | 侵蚀特征 |
|------|------|----------|
| 已开工时段 | start_date → plan_submit_date | 实际已发生的侵蚀，按施工进度估算扰动面积 |
| 施工期 | plan_submit_date → end_date | 扰动最强烈，面积最大 |
| 自然恢复期 | end_date → design_level_year 年末 | 植被逐步恢复，侵蚀递减 |

**时长计算**：`T = (结束日期 - 开始日期).days / 365`，精确到 0.01 年。

### 4.2.2 RUSLE 查表逻辑

MVP 阶段使用查表近似值。从 soil_map.json 按城市 + 分区类型查询扰动期侵蚀模数和自然恢复期侵蚀模数，乘以面积和时长得到各时段流失量。

**单元格公式**：

```
W[zone][period] = M[zone][period] × A[zone] × T[period] / 100
```

其中 W=流失量(t)，M=侵蚀模数(t/km²·a)，A=面积(hm²→换算km²)，T=时长(年)。

**输出**：`erosion_df`，一个 zones × periods 的矩阵 + 行列合计 + 背景值差额。共 20 个标签。

### 4.2.3 背景流失量扣减

项目新增流失量 = 预测总流失量 - 背景流失量。背景流失量 = 背景侵蚀模数 × 总面积 × 总时长。

## 4.3 Phase2: 造价师

在措施规划师输出完整措施清单后执行。将每条措施的工程量 × 单价经过 6 层费率叠加得到投资额。

### 4.3.1 六层费率叠加流程

```
直接费 (工程量 × 单价)
  → + 其他直接费 (直接费 × L1)
  → + 现场经费 (直接费 × L2)
  = 直接工程费
    → + 间接费 (直接工程费 × L3)
    → + 企业利润 ((直接工程费 + 间接费) × L4)
    → + 税金 ((直接工程费 + 间接费 + 利润) × L5)
    = 建安工程费
      → + 独立费用 (L6)
      → + 预备费 ((一至四部分) × 6%)
      → + 水保补偿费 (面积 × 地区单价)
      = 水保总投资
```

### 4.3.2 新增/已有拆分

措施清单中 `source="existing"` 的汇总为"主体已列投资"，`source="planned"` 的汇总为"方案新增投资"。两者相加为水保总投资。这个拆分是报告表 7.1-1 的核心。

### 4.3.3 分类汇总维度

按 **措施类型(工程/植物/临时) × 分区 × 新增/已有** 三维汇总，输出约 80 个造价标签到 State.Calc.cost_summary。

## 4.4 Phase2: 效益分析

基于措施清单和流失预测结果，计算 GB/T 50434 要求的六项防治指标：

| 指标 | 计算公式 | 一级目标 | 二级目标 | 说明 |
|------|----------|----------|----------|------|
| 水土流失治理度 | 治理面积/流失面积 × 100% | ≥95% | ≥85% | 有措施覆盖的分区面积占比 |
| 土壤流失控制比 | 容许流失量/实际流失量 | ≥1.0 | ≥0.7 | 方案实施后的侵蚀模数降至容许值 |
| 渣土防护率 | 防护渣土量/渣土总量 × 100% | ≥95% | ≥90% | 拦挡+覆盖的弃渣占比 |
| 表土保护率 | 保护表土量/可保护总量 × 100% | ≥97% | ≥90% | 剥离+回覆利用率 |
| 林草植被恢复率 | 恢复面积/可恢复面积 × 100% | ≥97% | ≥90% | 绿化区+恢复区面积占比 |
| 林草覆盖率 | 林草面积/总面积 × 100% | ≥27% | ≥20% | 最终绿化覆盖比例 |

所有六项指标均需达标，否则审计智能体会标记为不通过。

## 4.5 状态装配器

纯 Python 映射模块，将 Calc 结果 + facts + measures 转换为 229 个模板标签。

| 标签类别 | 数量 | 来源和映射逻辑 |
|----------|------|----------------|
| 项目概况 (facts→) | 16 | facts_v2.json 直接映射 |
| 分区面积 (zones→) | 6 | zones 数组汇总 |
| 土方平衡 (ew→) | 12 | Calc.earthwork 直接映射 |
| 侵蚀预测 (ep→) | 20 | Calc.erosion_df 矩阵展平为各时段×分区标签 |
| 造价投资 (c→) | 80 | Calc.cost_summary 按三维汇总展平 |
| 效益指标 (bf→) | 12 | Calc.benefit 六指标实际值+目标值 |
| 措施列表 (循环) | 4 组 list | Measures 清单按分区/类型分组，供 python-docx 循环渲染 |
| 章节文本 (draft→) | 8 | 从 State.Draft 直接映射 |
| 其他 (日期/附图等) | 71 | 杂项：格式化日期、附图清单、审核人信息等 |

装配器的输出直接写入 State.TplCtx，是渲染引擎的**唯一数据源**。

---

# 5 智能体详细规格

## 5.1 措施规划师 Agent

### 5.1.1 角色定义

**System Prompt 角色**：资深水土保持措施设计专家，熟悉江苏省水保技术规范和常见措施体系。你的任务是根据项目的分区特征、侵蚀预测数据和空间布局，决策方案需要新增哪些水保措施及其空间布置。

### 5.1.2 输入

- `State.Static.meta`：项目概况（面积、工期、投资）
- `State.ETL.zones`：标准化分区列表（名称、面积、挖填方）
- `State.ETL.spatial_layout`：VL+GIS 空间分析结果（建筑位置/道路走向/坡度/排水方向）
- `State.Calc.erosion_df`：侵蚀预测矩阵（各分区各时段流失量）
- `State.Static.measures_existing`：用户上传的已有措施清单

### 5.1.3 决策逻辑

Agent 的 reasoning chain：

1. **缺口分析**：遍历每个分区，检查已有措施是否覆盖了该分区的 3 类措施（工程/植物/临时）
2. **空间查询**：调用 `spatial_context` 获取分区的空间布局特征（建筑位置、坡度、排水方向）
3. **措施查询**：对缺失的类型，调用 `measure_library` 查询标准库中适用的候选措施
4. **工程量估算**：调用 `quantity_estimator` 根据分区面积和特征估算工程量
5. **合规校验**：调用 `regulation_checker` 校验选定措施是否符合江苏省地方标准
6. **图集参考**（可选）：调用 `atlas_reference` 参考制图规范和典型设计

### 5.1.4 工具定义 (6 个)

| 工具名 | 输入参数 | 输出 | 实现方式 |
|--------|----------|------|----------|
| `measure_library` | zone_type: str, measure_type: str | 适用措施列表 [{name, unit, typical_quantity_range, description}] | Python 查表，measure_library.json 35 条 |
| `quantity_estimator` | measure_name: str, zone_area: float, zone_type: str | {quantity: float, unit: str, basis: str} | Python 公式：面积×系数 |
| `regulation_checker` | measure_name: str, province: str | {compliant: bool, reference: str, notes: str} | Python 查表，legal_refs.json |
| `rag_exemplar` | zone_type: str, project_type: str, top_k: int=3 | [相似项目的措施方案段落] | ChromaDB 向量检索 |
| `spatial_context` | zone_name: str | {buildings, roads, slopes, drainage_direction, ...} | State.ETL.spatial_layout 查询 |
| `atlas_reference` | measure_type: str, query: str | [图集绘图规范/典型设计段落] | atlas_rag ChromaDB 检索 |

### 5.1.5 输出格式

JSON 数组，每条记录含空间布置信息：

```json
{
  "name": "截水沟C20",
  "zone": "建(构)筑物区",
  "type": "工程措施",
  "unit": "m",
  "quantity": 180,
  "source": "planned",
  "basis": "按建筑物区周边长度估算",
  "unit_price_ref": "截水沟C20",
  "position": "建筑物北侧边界",
  "coverage": "沿场地北边界全长",
  "direction": "东西走向",
  "note": "与排水沟连通"
}
```

输出写入 `State.Measures`，与已有措施合并后传给 Phase2 造价师。空间布置字段 (position/coverage/direction/note) 供 Drawing Agent 使用。

## 5.2 撰稿智能体 Agent

### 5.2.1 角色定义

**System Prompt 角色**：资深水土保持方案报告撰稿专家，精通 GB/T 51240 技术规范，文风严谨规范。你的任务是根据提供的计算数据和范文参考，逐章生成方案报告文本。

### 5.2.2 生成顺序

**Ch2→Ch3→Ch4→Ch5→Ch6→Ch7→Ch8→Ch1**

第 1 章（综合说明）最后生成，因为它是全文摘要，需要引用所有其他章节的关键数据。

### 5.2.3 工具定义 (4 个)

| 工具名 | 输入参数 | 输出 | 实现方式 |
|--------|----------|------|----------|
| `rag_search` | query: str, chapter_id: int, top_k: int=3 | [范文中对应章节的相关段落] | ChromaDB 检索，按 chapter_id 过滤 |
| `calc_lookup` | key_path: str (如 "cost_summary.total") | 对应的计算结果数值 | 直接查 State 字典 |
| `self_checker` | chapter_text: str, chapter_id: int | [{field, in_text, in_state, match: bool}] | Python 正则提取文本中的数字 → 与 State 对比 |
| `prev_chapter` | chapter_id: int | 前序章节的 200 字摘要 | 从 State.Draft 中提取并截断 |

### 5.2.4 各章节生成策略

| 章节 | 内容特征 | 生成策略 | 工具调用 |
|------|----------|----------|----------|
| Ch2 项目概况 | 数据密集，大量数字 | TplCtx 标签直接填充为主，仅描述性段落用 LLM | calc_lookup 频繁 |
| Ch3 措施界定 | 措施列表+分类描述 | 措施列表从 State.Measures 渲染，分类描述用 LLM | rag_search |
| Ch4 侵蚀预测 | 公式+表格+分析 | 表格从 TplCtx 渲染，分析文字用 LLM | calc_lookup |
| Ch5 措施布设 | 措施详细描述+设计参数 | RAG 辅助生成描述，参数从 State 查询 | rag_search + calc_lookup |
| Ch6 监测 | 高度模板化 | 90% 模板文本 + 10% 参数填充 | 几乎不需要工具 |
| Ch7 投资估算 | 费率表格+说明 | 表格从 TplCtx 渲染，说明用 LLM | calc_lookup |
| Ch8 效益分析 | 指标计算+结论 | 指标从 TplCtx 渲染，分析文字用 LLM | calc_lookup |
| Ch1 综合说明 | 全文摘要 | 需要引用所有其他章节关键数据 | prev_chapter × 7 + calc_lookup |

### 5.2.5 输出格式

每章输出使用 `===TAG_NAME===` 标记分隔，经 `_sanitize_text()` 清洗后写入 State.Draft。

### 5.2.6 上下文窗口管理

Qwen2.5-72B 支持 128K 上下文，实际使用控制在 32K 以内以保证生成质量：

- System Prompt: ~2K tokens
- State snapshot (TplCtx 子集): ~3K tokens（按章节裁剪）
- RAG context: ~3K tokens (top_k=3)
- Prev summary: ~0.5K tokens
- Legal refs (相关子集): ~1K tokens
- Feedback (如有): ~0.5K tokens
- **总输入**: ~10K tokens
- **留给输出**: ~22K tokens

## 5.3 审计智能体 Agent

### 5.3.1 角色定义

**System Prompt 角色**：水土保持方案审查专家，负责审查方案报告的数值准确性、文本逻辑性和结构规范性。

### 5.3.2 工具定义 (3 个)

| 工具名 | 输入参数 | 输出 | 实现方式 |
|--------|----------|------|----------|
| `numeric_validator` | State.Calc, State.TplCtx, State.Draft | [{chapter, field, expected, actual, severity}] | **Python 硬逻辑**：投资总计=分项和、面积/流失量一致性、费率计算验证、六指标达标检查 |
| `text_validator` | State.Draft, State.TplCtx, State.Static.legal | [{chapter, issue, severity, suggestion}] | **LLM 调用**：逐章检查摘要数字与计算值匹配、章节间无矛盾、法规编号存在于 legal_refs、无明显幻觉 |
| `rag_comparator` | State.Draft | {structure_score, deviations: [{chapter, issue}]} | **ChromaDB 检索**范文各章节结构 → 与当前报告章节标题/段落结构对比 |

### 5.3.3 评分体系

| 评分维度 | 权重 | 满分条件 | 扣分规则 |
|----------|------|----------|----------|
| 数值一致性 | 40% | numeric_validator 零错误 | 每个数值错误扣 10 分 |
| 文本质量 | 30% | 无幻觉、无矛盾、法规正确 | 每个幻觉/矛盾扣 8 分 |
| 结构规范性 | 20% | 章节结构与范文偏差 <10% | 偏差每增 10% 扣 5 分 |
| 完整性 | 10% | 8 章 + 12 表全部非空 | 每个空章/空表扣 5 分 |

**总分 = Σ(维度得分 × 权重)**，满分 100。

### 5.3.4 重试机制

```
总分 ≥ 80 → 通过 → 存储交付
总分 60-79 → 生成精准 feedback → 回弹给撰稿智能体 (仅失败章节)
总分 < 60 → 强制通过 + 标记需人工复核
每章最多重试 3 次，超限后强制通过。
```

## 5.4 绘图智能体 Agent

### 5.4.1 角色定义

**System Prompt 角色**：专业水土保持措施图绘制工程师，精通 SL73_6-2015《水利水电工程制图标准·水土保持图》。通过编写 matplotlib Python 代码生成专业措施图。

### 5.4.2 工作流

```
1. 调用 get_project_data → 获取项目分区/措施/空间布局
2. 调用 get_style_reference → 获取 SL73_6-2015 制图规范和内置样式
3. LLM 编写完整可执行的 matplotlib Python 代码
4. 调用 execute_drawing_code → 沙箱执行生成 PNG
5. 调用 verify_image → VL 模型验证图片质量
6. 不合格则修改代码重试 (max_turns=8)
```

### 5.4.3 工具定义 (4 个)

| 工具名 | 输入参数 | 输出 | 实现方式 |
|--------|----------|------|----------|
| `get_project_data` | zone_name: str (可选) | {zones, measures, spatial_layout, project_info} | State → 分区/措施/空间布局提取 |
| `get_style_reference` | map_type: str, query: str | {atlas_conventions, builtin_styles, templates} | atlas_rag ChromaDB检索 + measure_symbols 内置样式 |
| `execute_drawing_code` | code: str | {success, output_path, file_size, error} | 沙箱exec: 受限builtins + 白名单import + 60s超时 + 自动代码修正 |
| `verify_image` | image_path: str, map_type: str | {passed, score, issues} | VL模型评分(≥70通过) / fallback(>10KB通过) |

### 5.4.4 图类型

| 图类型 | 代码标识 | 说明 | 数量 |
|--------|----------|------|------|
| 分区图 | zone_boundary | 各分区边界+面积标注+图例 | 1 |
| 总布置图 | measure_layout | 底图+全部措施符号+图例 | 1 |
| 分区详图 | zone_detail | 放大标注+措施明细 (每分区1张) | N (≤5) |
| 典型断面 | typical_section | 排水沟/挡墙/沉沙池横断面 | N (≤5) |

### 5.4.5 代码执行安全

`execute_drawing_code` 工具在受控沙箱中执行 LLM 生成的代码：

- **受限 builtins**: 仅允许 `range`, `len`, `int`, `float`, `str`, `list`, `dict`, `tuple`, `max`, `min`, `abs`, `round`, `enumerate`, `zip`, `sorted`, `print` 等
- **白名单 import**: 仅允许 `matplotlib`, `numpy`, `math`
- **超时**: 60 秒硬限制
- **预注入变量**: `plt`, `np`, `math`, `mpatches`, `mlines`, `output_path`
- **自动代码修正** (6 层):
  1. `output_path` 覆盖 → regex 替换保持注入路径
  2. `savefig` 写死文件名 → regex 替换为 `output_path`
  3. `plt.Rectangle` 等不存在 → 预注入 patches 类到 namespace
  4. `plt.show()` → 自动移除
  5. 文件保存到 CWD → 文件回收 (shutil.move)
  6. 特殊字符 → `_safe_text()` 替换 (²→2, ³→3, ×→x)

### 5.4.6 Fallback 机制

当 Drawing Agent 产出 < 2 张合格图时，整体回退到 `MeasureMapRenderer` (纯 Python 确定性渲染)，保证至少有基础措施图输出。

### 5.4.7 措施图后插入

生成的措施图 PNG 在 docxtpl 渲染完成后，通过 python-docx 后插入到报告中。插入顺序按优先级排序：分区图 → 总布置图 → 详图 → 断面图。

---

# 6 前端详细规格

## 6.1 技术栈

- **框架**: Vue 3 + Vite
- **UI 库**: Element Plus
- **路由**: Vue Router 4
- **HTTP**: Axios
- **构建**: Vite 6

## 6.2 双端口架构

| 端口 | 用途 | 前端路由 |
|------|------|----------|
| 8080 | 用户端 — 报告生成/项目数据 | `/` 首页, `/project` 项目表单, `/status` 进度看板, `/download` 交付 |
| 8081 | 管理端 — 知识库/LLM 设置 | `/admin/knowledge` 知识库, `/admin/settings` LLM 设置 |

## 6.3 用户端功能

### 6.3.1 项目表单 (上传区)

- 步骤 1：基本信息表单 (项目名/地点/工期/投资/土方)
- 步骤 2：分区面积填写 (动态表格，5 行默认，可增删)
- 步骤 3：文件上传 (必填: CSV，可选: CAD/GIS/PDF/图集)
- 前端校验：面积合计、日期逻辑、必填字段

### 6.3.2 进度看板

- 实时进度条：17 步流水线百分比
- 章节状态卡片：Ch1~Ch8 各章当前状态
- 日志流：SSE 实时推送

### 6.3.3 交付区

- 报告摘要卡片：总投资/流失量/六指标/审计评分
- 下载按钮：报告书.docx + 措施图包.zip + 审计日志.json

## 6.4 管理端功能

### 6.4.1 知识库管理

- RAG 语料库状态查看
- 图集知识库管理 (上传/删除)
- 措施库编辑

### 6.4.2 LLM 设置

- vLLM 地址/模型名称/温度/token 配置
- VL 模型地址/名称配置
- 预设方案选择 (72B/7B/VL)

---

# 7 后端 API 详细规格

## 7.1 架构

- **框架**: FastAPI + uvicorn
- **双端口**: user_app (8080) + admin_app (8081)
- **数据库**: SQLite (data/server.db)
- **文件存储**: 本地 data/ 目录

## 7.2 API 模块

| 模块 | 端口 | 路径前缀 | 功能 |
|------|------|----------|------|
| pipelines | 8080 | `/api/pipelines` | 创建/查询/执行生成任务 |
| config | 8080 | `/api/config` | 项目数据配置 (facts/measures) |
| vision | 8080 | `/api/vision` | CAD/图片分析 |
| system | 8080+8081 | `/api/system` | 健康检查/预设/设置 |
| knowledge | 8081 | `/api/knowledge` | 知识库管理 (RAG/图集) |

## 7.3 核心端点

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/pipelines/run` | 触发生成流水线 |
| GET | `/api/pipelines/{id}` | 查询任务状态 |
| GET | `/api/pipelines/{id}/events` | SSE 进度流 |
| GET | `/api/pipelines/{id}/download/{type}` | 下载报告/图包/日志 |
| GET/PUT | `/api/config/facts` | 获取/更新项目概况 |
| GET/PUT | `/api/config/measures` | 获取/更新措施清单 |
| POST | `/api/config/upload` | 上传文件 |
| GET/PUT | `/api/system/settings` | LLM 设置 |
| GET | `/api/system/health` | 健康检查 |
| GET | `/api/system/presets` | 预设方案列表 |

## 7.4 数据库 Schema (SQLite)

### runs 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | 运行 ID (UUID) |
| status | TEXT | pending/running/done/error |
| facts | TEXT (JSON) | 项目概况 |
| created_at | TEXT | 创建时间 |
| finished_at | TEXT | 完成时间 |
| output_dir | TEXT | 输出目录路径 |
| error | TEXT | 错误信息 |
| audit_score | INTEGER | 审计评分 |

---

# 8 报告模板与渲染规格

## 8.1 三阶段渲染引擎

渲染分三个阶段执行：

| 阶段 | 引擎 | 任务 |
|------|------|------|
| Phase 1 | docxtpl (Jinja2) | 229 个 `{{ }}` 变量替换 |
| Phase 2 | python-docx | 手动复制行填充 4 个循环表格 (existing_measures, zone1_measures, zone2_measures, cost_detail) |
| Phase 3 | python-docx | 措施图 PNG 后插入 (InlineImage 式追加到指定位置) |

### 8.1.1 标签语法 (Phase 1)

| 语法 | 用途 | 示例 |
|------|------|------|
| `{{variable}}` | 简单值替换 | `{{project_name}}` |
| `{{item.field}}` | 占位符 (Phase2 填充) | `{{em.name}}` |

> 注意：模板已清除所有 `{%...%}` 块标签，循环表格由 Phase 2 手动处理。

### 8.1.2 循环表格填充 (Phase 2)

python-docx 在渲染后的 docx 中定位 4 个目标表格，复制模板行并填入数据。

### 8.1.3 措施图后插入 (Phase 3)

`renderer._insert_measure_maps()` 在最终 docx 中追加措施图页面。排序规则：

1. 分区图 (zone_boundary)
2. 总布置图 (measure_layout)
3. 分区详图 (zone_detail_xxx)
4. 典型断面 (typical_section_xxx)

## 8.2 图表生成

### 8.2.1 数据图表 (Step 11, 4 张)

| 图表名 | 类型 | 数据来源 | 插入位置 |
|--------|------|----------|----------|
| 水土流失预测图 | Sankey/Area | erosion_df | 第4章后 |
| 投资构成图 | Pie | cost_summary | 第7章后 |
| 六指标达标对比图 | Bar | benefit (实际值 vs 目标值) | 第8章后 |
| 分区面积占比图 | Pie | zones | 附图包 |

### 8.2.2 措施图 (Step 12, Drawing Agent)

| 图类型 | 描述 | 数据来源 |
|--------|------|----------|
| 分区图 | 各分区边界 + 面积标注 + 图例 | zones + spatial_layout |
| 总布置图 | 场地底图 + 全部措施符号 + 图例 | measures + spatial_layout + measure_symbols |
| 分区详图 ×N | 单分区放大 + 措施明细标注 | zone measures + spatial_layout |
| 典型断面 ×N | 单措施横断面 (排水沟/挡墙等) | measure_symbols 断面模板 |

措施图由 Drawing Agent (LLM 编写 matplotlib 代码) 生成。当 Agent 产出不足时回退到 MeasureMapRenderer (确定性 Python 渲染)。

### 8.2.3 图表技术参数

- DPI: 300
- 格式: PNG
- 尺寸: 16cm × 10cm (数据图表) / A4 幅面 (措施图)
- 字体: SimHei (标题) / FangSong (标注)
- `_safe_text()`: 特殊字符替换 (²→2, ³→3, ×→x) 避免字体缺字

## 8.3 完整性检查

| 检查项 | 方法 | 失败处理 |
|--------|------|----------|
| 无残留标签 | 正则扫描 `{{` 和 `{%` | 记录到审计日志，标记需人工复核 |
| 12 表非空 | 检查每张表格的行数 > 0 | 记录到审计日志 |
| 章节文本非空 | 检查 8 个 chapter 字段 | 记录到审计日志 |
| 图表插入成功 | 检查 InlineImage 占位符已替换 | fallback：保留文字描述 |
| 文件大小合理 | docx > 50KB 且 < 20MB | 异常则记录 |

---

# 9 部署规格

## 9.1 AutoDL 一键部署 (推荐)

**环境**: AutoDL 4×A800-80G (或 4×RTX 6000 Ada 48G)

```bash
cd /root/autodl-tmp/swc-report
python autodl_start.py              # 全自动: 下载模型 + 安装依赖 + vLLM + Web UI
python autodl_start.py --cli        # 全自动: 下载模型 + vLLM + CLI Pipeline
python autodl_start.py --web-only   # 仅 Web (vLLM 已启动)
python autodl_start.py --install    # 仅安装依赖 + 下载模型
python autodl_start.py --check      # 仅检查环境
python autodl_start.py --no-vl      # 不启动视觉模型 (仅2卡时使用)
```

**自动处理**:
- 模型从 ModelScope 下载 (国内直连，无需学术加速)
- HuggingFace 通过 `HF_ENDPOINT=https://hf-mirror.com` 镜像
- pip 安装使用清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`
- embedding 模型自动预下载
- 中文字体自动安装 (fonts-noto-cjk/fonts-wqy-zenhei)
- vLLM 双实例启动 (Text port 8000 + VL port 8001)
- Web UI 双端口启动 (用户端 8080 + 管理端 8081)

## 9.2 手动部署

```bash
# 1. 下载模型
pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple
modelscope download --model Qwen/Qwen2.5-72B-Instruct-GPTQ-Int8 \
  --local_dir /root/autodl-tmp/LLM/Qwen2.5-72B-Instruct-GPTQ-Int8
modelscope download --model Qwen/Qwen2.5-VL-72B-Instruct-GPTQ-Int8 \
  --local_dir /root/autodl-tmp/LLM/Qwen2.5-VL-72B-Instruct-GPTQ-Int8

# 2. 安装依赖
cd /root/autodl-tmp/swc-report
bash scripts/setup.sh

# 3. 启动 vLLM (终端1: Text, 终端2: VL)
CUDA_VISIBLE_DEVICES=0,1 bash scripts/start_vllm.sh 72b-int8
CUDA_VISIBLE_DEVICES=2,3 PORT=8001 bash scripts/start_vllm.sh vl

# 4. 启动 Web UI (终端3)
python run_server.py
```

## 9.3 Docker 部署

```bash
docker compose up -d    # Web UI → http://localhost:8080
docker compose down     # 停止
```

> 注意: vLLM 需在宿主机上独立启动，Docker 容器通过 `network_mode: host` 访问。

## 9.4 CLI 模式

```bash
python scripts/run.py -v                    # 使用默认配置
python scripts/run.py --no-llm              # 仅计算引擎 (不调用 LLM)
python scripts/run.py --vllm-url URL --model NAME  # 指定 vLLM 地址
```

## 9.5 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VLLM_URL` | 自动检测 (Ollama/vLLM) | Text LLM API 地址 |
| `VL_URL` | http://localhost:8001/v1 | VL 模型 API 地址 |
| `MODEL_NAME` | 自动检测 | Text 模型名称 |
| `VL_MODEL_NAME` | 自动检测 | VL 模型名称 |
| `MAX_TOKENS` | 4096 | 最大输出 token |
| `TEMPERATURE` | 0.3 | 生成温度 |
| `HF_ENDPOINT` | https://hf-mirror.com | HuggingFace 镜像 (AutoDL) |
| `HF_HOME` | /root/autodl-tmp/LLM/huggingface | HF 缓存目录 |

## 9.6 Windows 本地开发

```bash
# 先启动 Ollama 桌面应用
python run_local.py     # 自动检测 Ollama + 跑 Pipeline
```

- 自动检测: Windows → Ollama (port 11434, qwen2.5:7b)，Linux → vLLM (port 8000, 72B)
- 7B 模型用于本地开发测试，72B 用于生产

---

# 10 非功能性需求

## 10.1 性能

| 指标 | 要求 | 备注 |
|------|------|------|
| 端到端生成时间 | ≤15 分钟（单项目） | A800×4 环境，含 4 个 Agent 总推理时间 |
| API 响应时间 | ≤500ms（非生成接口） | config/upload/status/download |
| SSE 延迟 | ≤2 秒 | 从后端事件到前端更新 |
| 文件上传速度 | ≥10MB/s | 内网环境 |
| docx 渲染时间 | ≤30 秒 | 229 标签 + 12 表格 + 措施图插入 |
| 措施图生成 | ≤5 分钟 | Drawing Agent 4-8 张图总耗时 |

## 10.2 可靠性

- **章节级重试**：每章最多重试 3 次，仅重写失败章节
- **Drawing Agent fallback**：LLM 绘图失败时回退到确定性 MeasureMapRenderer
- **审计日志持久化**：所有生成过程记录写入 SQLite
- **优雅退出**：autodl_start.py 注册 SIGINT/SIGTERM 信号处理，终止所有子进程

## 10.3 安全性

- **代码沙箱**：Drawing Agent execute_drawing_code 使用受限 builtins + 白名单 import + 60s 超时
- **文件隔离**：每次运行的输出存储在独立目录下
- **输入校验**：后端对所有用户输入做二次校验
- **CORS**：FastAPI CORS 中间件，允许所有来源（MVP 阶段）

## 10.4 可观测性

- **日志**：Python logging 模块，格式：`HH:MM:SS [LEVEL] module: message`
- **进度推送**：17 步流水线每步完成后推送 SSE 事件
- **审计报告**：逐章评分 + 问题清单 + 修改建议，JSON 格式输出

## 10.5 可扩展性

- **新增项目类型**：仅需新增 measure_library 条目 + 调整 RUSLE 查表参数 + 训练 RAG 语料，不改代码架构
- **新增省份**：新增 fee_rate_config 省份配置 + soil_map 条目 + legal_refs 省级法规
- **模型升级**：vLLM 实例无状态，更换模型仅需修改启动参数
- **存储升级**：SQLite → PostgreSQL，本地文件 → MinIO/OSS，仅需修改 storage.py

---

# 11 实施计划

## 11.1 里程碑规划

| 阶段 | 时间 | 交付物 | 验收标准 |
|------|------|--------|----------|
| M1 | 第1-2周 | 计算引擎 + 状态装配器 | 土方/侵蚀/造价/效益 4 个模块单测通过；229 标签输出完整 |
| M2 | 第3-4周 | 措施规划师 Agent | 5 个测试项目，规划师输出覆盖所有分区，合规校验通过 |
| M3 | 第5-6周 | 撰稿智能体 + 模板渲染 | 8 章全文生成，docx 无残留标签，12 表非空 |
| M4 | 第7-8周 | 审计智能体 + 绘图智能体 | 审计评分 >80 的项目 ≥60%；措施图 ≥4 张/项目 |
| M5 | 第9-10周 | 前端 + API + 端到端集成 | 上传到下载完整跑通；SSE 进度实时推送 |
| M6 | 第11-12周 | AutoDL 部署 + 测试 + 上线 | 一键部署成功；10 个真实项目测试；平均 ≤15 分钟 |

## 11.2 风险评估

| 风险项 | 概率 | 影响 | 缓解措施 |
|--------|------|------|----------|
| 72B 模型在水保领域专业度不足 | 中 | 高 | 收集 20+ 份范文构建 RAG 增强；关键数字全部由计算引擎产出 |
| 措施规划师幻觉（推荐不合理措施） | 中 | 中 | measure_library 限定候选集；regulation_checker 校验合规性 |
| Drawing Agent 代码质量低 | 中 | 中 | 6 层自动代码修正 + fallback MeasureMapRenderer |
| AutoDL 网络限制 | 高 | 高 | ModelScope 国内源 + HF 镜像 + 清华 pip 镜像 + embedding 预下载 |
| docxtpl 循环表格渲染异常 | 低 | 高 | python-docx 手动填充替代 {%for%} 块标签 |
| GPU 显存不足导致 OOM | 低 | 高 | GPTQ-Int8 量化 (72B→~40GB)；GPU_UTIL=0.90 |

## 11.3 验收标准

### 11.3.1 功能验收

使用 10 个真实项目数据端到端测试。每个项目需满足：

- 生成完成无报错
- docx 可正常打开，格式正确
- 12 张核心表格数据完整
- 投资总额 = 各分项之和（精确到 0.01 万元）
- 六项指标全部计算并展示
- 措施图 ≥4 张且可读

### 11.3.2 部署验收

- `python autodl_start.py` 在全新 AutoDL 实例上一键运行成功
- 模型自动从 ModelScope 下载
- 无需手动配置网络/镜像
- 双 vLLM 实例 (Text + VL) 正常启动
- Web UI 可通过 AutoDL 端口映射访问

### 11.3.3 性能验收

- 单项目端到端生成时间 ≤15 分钟
- API 响应时间 ≤500ms
- SSE 推送延迟 ≤2 秒

---

## 附录 A：拓扑图

完整架构拓扑图见 `topology_v6.mermaid`（Mermaid 源码）。

## 附录 B：术语表

| 缩写 | 全称 | 说明 |
|------|------|------|
| RUSLE | Revised Universal Soil Loss Equation | 修正通用土壤流失方程 |
| RAG | Retrieval-Augmented Generation | 检索增强生成 |
| TplCtx | Template Context | 模板渲染上下文（229 个标签的字典） |
| VL | Vision-Language | 视觉语言模型 |
| GPTQ | GPT Quantization | 后训练量化方法 |
| vLLM | Virtual LLM | 高性能 LLM 推理框架 |
| MVP | Minimum Viable Product | 最小可行产品 |
| SSE | Server-Sent Events | 服务端推送事件 |
| SPA | Single Page Application | 单页应用 |

## 附录 C：关联文件

| 文件 | 说明 |
|------|------|
| `topology_v6.mermaid` | 架构拓扑图源码（4 Agent, 17 Tools, Drawing Agent） |
| `autodl_start.py` | AutoDL 一键启动脚本 |
| `config/facts_v2.json` | 项目概况表 |
| `config/measures_v2.csv` | 已列措施清单 |
| `config/measure_library.json` | 35 种标准措施库 |
| `templates/template.docx` | 报告模板（229 标签位） |
| `src/pipeline.py` | 17 步流水线编排 |
| `src/agents/drawing.py` | 绘图智能体 |
| `src/tools/drawing_tools.py` | 绘图工具 (4个) |
| `src/measure_symbols.py` | 措施符号/样式/断面模板 |
| `src/measure_map.py` | 措施图 fallback 渲染引擎 |
| `src/atlas_rag.py` | 图集 RAG 索引 |
| `src/spatial_analyzer.py` | 空间分析 (GIS+VL) |
| `data/atlas/` | 制图标准知识库 (20 个文件) |
