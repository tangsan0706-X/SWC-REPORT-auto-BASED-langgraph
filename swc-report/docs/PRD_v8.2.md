# 水土保持方案自动生成系统 — 产品需求文档 (PRD)

> **文档编号**: SWCP-PRD-2026-002
> **版本**: v8.2 — PlacementEngine v2 + CAD 智能识别 + 颜色辅助分类
> **日期**: 2026-03-04
> **密级**: 内部

---

## 修订记录

| 版本 | 日期 | 修订人 | 修订内容 |
|------|------|--------|----------|
| v1.0 | 2026-02-09 | 作者 | 初稿，基础架构设计 |
| v2.0 | 2026-02-10 | Claude | 补充6层费率引擎、229模板标签映射、状态装配器、双轨校验 |
| v3.0 | 2026-02-10 | Claude | 重组处理层为编制集群+审计集群，审计智能体替代原双轨校验 |
| v4.0 | 2026-02-10 | Claude | 新增措施规划师Agent、撰稿升级为Agent、11个工具定义、GPU分配方案、完整前后端规格 |
| v5.0 | 2026-02-12 | Claude | 绘图智能体(4工具)、GPTQ-Int8双实例GPU方案、AutoDL一键部署、措施图渲染引擎 |
| v8.0 | 2026-02-26 | Claude | ContextVar状态解耦 + ThreadPoolExecutor并行 + DAG调度器 |
| v8.1 | 2026-02-26 | Claude | LLM韧性层 + 数据适配器(Step 9.5) + 消息窗口管理 + 并行AgentContext隔离 |
| **v8.2** | **2026-03-04** | **Claude** | **全量代码审计重写PRD: (1) PlacementEngine v2 — 6阶段×13专用布置×8联动×4级碰撞; (2) CAD新架构 — 8步特征分析+7级红线回退+颜色辅助分类(ACI 2→建筑/ACI 1→红线); (3) SiteModel多源融合(4数据源×置信度); (4) 绘图双引擎(Drawing Agent→MeasureMapRenderer fallback); (5) 纯Python几何库geo_utils(~850行); (6) measure_symbols专业样式系统; (7) 完善96 tests覆盖** |

---

## 目录

1. [产品概述](#1-产品概述)
2. [系统架构](#2-系统架构)
3. [数据规格](#3-数据规格)
4. [计算引擎详细规格](#4-计算引擎详细规格)
5. [智能体详细规格](#5-智能体详细规格)
6. [CAD 解析与空间分析](#6-cad-解析与空间分析)
7. [PlacementEngine v2 几何布置引擎](#7-placementengine-v2-几何布置引擎)
8. [绘图与渲染系统](#8-绘图与渲染系统)
9. [并行执行与 DAG 调度](#9-并行执行与-dag-调度)
10. [LLM 韧性与上下文管理](#10-llm-韧性与上下文管理)
11. [前后端与部署规格](#11-前后端与部署规格)
12. [报告模板与渲染规格](#12-报告模板与渲染规格)
13. [测试体系](#13-测试体系)
14. [非功能性需求](#14-非功能性需求)
15. [已知架构债务](#15-已知架构债务)

---

# 1 产品概述

## 1.1 产品定位

本系统是一套面向水土保持咨询机构的自动化方案编制工具。系统接收项目基本信息、已有措施清单等输入数据，通过计算引擎完成土方平衡、侵蚀预测、造价估算等确定性计算，再由多智能体协作完成措施规划、报告撰写、措施图绘制和质量审计，最终输出符合《生产建设项目水土保持方案编制技术规范》(GB/T 51240) 的完整方案报告书 (.docx) 及附图包 (.zip)。

## 1.2 目标用户

水土保持咨询公司的方案编制工程师。典型使用场景：接到房地产/市政/工业项目的水保方案编制委托后，工程师将设计院提供的项目概况和施工图中的已有措施信息录入系统，系统在 5-10 分钟内生成初稿，工程师在此基础上人工修改和完善。

## 1.3 核心价值主张

**将一份水保方案的编制周期从 3-5 个工作日压缩至 1 小时以内（含人工审校）。**

- **v8.0 性能提升**：DAG 并行调度 + Agent 内并行执行，端到端 **5-8 分钟**
- **v8.1 可靠性提升**：LLM 韧性层 + 数据适配器 + 结构化摘要
- **v8.2 精度提升**：PlacementEngine v2 基于 CAD 地理特征的智能空间布置 + 颜色辅助建筑/红线识别

## 1.4 产品范围

### 1.4.1 MVP 范围

仅支持**江苏省内的房地产类开发建设项目**。

### 1.4.2 后续扩展方向

市政道路项目 → 工业项目 → 线性工程（公路/管线） → 多省份支持。

## 1.5 系统边界

| 维度 | 系统负责 | 系统不负责 |
|------|----------|------------|
| 计算 | 土方平衡、侵蚀预测(RUSLE)、6层费率造价、效益分析 | 精确 RUSLE 因子推导 |
| 措施 | Agent 根据分区特征+标准库+空间布局规划新增措施 | 施工图级别的措施详细设计 |
| 制图 | Drawing Agent + PlacementEngine v2 生成措施图 | CAD 级精确制图 |
| CAD解析 | DXF 解析→建筑/道路/红线/绿化智能分类→SiteModel | DWG 直接编辑 |
| 文本 | 8 章全文初稿生成、数字引用自动对齐 | 法律条文有效性验证 |
| 审计 | 数值一致性、文本幻觉检测、范文结构对比 | 替代人工专家终审 |
| 输出 | .docx 报告 + PNG/DXF 措施图 + 审计日志.json | PDF 盖章版 |
| 调度 | DAG 18步 + 步骤自动并行 + 失败传播 | 分布式多机调度 |
| 韧性 | LLM 超时重试 + 上下文管理 + 数据完整性校验 | 跨节点故障恢复 |

## 1.6 关键指标

| 指标 | v8.2 目标 | 度量方式 |
|------|-----------|----------|
| 生成耗时 | ≤8 分钟 | API 返回到下载可用 |
| 审计通过率 | ≥60% | 审计智能体评分 ≥80 |
| 数值一致性 | 100% | Python 硬校验 0 错误 |
| 人工修改量 | ≤30% | 人工审校后差异统计 |
| 措施图生成率 | ≥10 张 | PlacementEngine + DrawingRenderer |
| 并发 Agent | 7+3 | 同时运行 Agent 数 |
| LLM 调用成功率 | ≥99% (含重试) | 成功次数 / 总次数 |
| 数据完整率 | ≥95% 标签非空 | 适配器校验 |
| 措施布置成功率 | ≥12/16 | PlacementEngine resolve_all |
| CAD 建筑识别精度 | 过滤围墙<50m² | 面积+颜色双重过滤 |

---

# 2 系统架构

## 2.1 七层架构

| 层级 | 名称 | 技术栈 | 职责 |
|------|------|--------|------|
| L0 | 前端层 | Vue 3 + Element Plus | 双端口 SPA：用户端(:8080) + 管理端(:8081) |
| L1 | 后端 API 层 | FastAPI + uvicorn (双端口) | REST API、SSE 进度推送、文件上传 |
| L2 | 输入层 | JSON/CSV/文件存储 | 用户输入 + 系统配置 + 可选文件 |
| L3 | 预处理层 | ezdxf/geopandas/ChromaDB/VL | CAD 解析、GIS 解析、RAG 构建、VL 空间分析 |
| L4 | 全局状态机 | Python dataclass (7分区) + ContextVar | Static/ETL/Calc/TplCtx/Draft/Measures/Flags |
| L5 | 处理层 | DAGScheduler × 5 Agent × 23 Tool | 编制集群 + 审计集群 |
| L5.5 | LLM 韧性层 | LLMClient (超时+重试) + 消息窗口 | LLM 调用可靠性 + 上下文不溢出 |
| L6 | 存储交付层 | 本地文件系统 + SQLite | 文件存储、历史记录 |

## 2.2 18步 DAG 流水线

```
1_load_config
    │
2_preprocess
    │
  ┌─────────┬─────────┐
  │         │         │
3_spatial 4_earthwork 5_erosion    ← 并行组A
  │         │         │
  └────┬────┘    ┌────┘
       │         │
     6_planner (依赖 3+5)
       │
     7_cost (依赖 6+4)
       │
     8_benefit
       │
     9_assemble
       │
   9.5_adapter (校验+回调修复)
       │
  ┌────┼────┬────┐
  │    │    │    │
10_writer 11_charts 12_drawings   ← 并行组B
  │    │    │    │
  └────┴────┴────┘
       │
    13_render (依赖 10+11+12)
       │
    14_audit → 15_retry → 16_final → 17_package
```

## 2.3 智能体总览

| 智能体 | 角色 | 工具数 | 并行模式 |
|--------|------|--------|----------|
| 措施规划师 (Planner) | 分区特征→措施规划+空间布置 | 6 | 串行 |
| 数据适配器 (Adapter) | 229标签校验+回调修复 | 6 | 串行 |
| 撰稿智能体 (Writer) | 8章报告文本生成 | 4 | 7章并行+1章串行 |
| 绘图智能体 (Drawing) | DrawingPlan JSON→渲染引擎 | 4 | 全图并行 |
| 审计智能体 (Auditor) | 4维质量审查+评分+重试策略 | 3 | 串行(重写可并行) |

## 2.4 技术选型

| 组件 | 技术选择 | 选择理由 |
|------|----------|----------|
| LLM 推理 | vLLM + Qwen2.5-72B-Instruct-GPTQ-Int8 | 72B 水保专业优秀；Int8 双卡可跑 |
| 视觉模型 | Qwen2.5-VL-72B-Instruct-GPTQ-Int8 | CAD 空间分析 + 图集索引 + VL 验证 |
| 向量数据库 | ChromaDB (双库) | 范文 RAG + 图集 RAG |
| Embedding | BAAI/bge-m3 (dense+sparse) | 1024d，中文优秀 |
| 文档渲染 | docxtpl + python-docx | 3阶段: 变量→循环表→图插入 |
| CAD 解析 | ezdxf (DXF) + ODA/LibreCAD (DWG) | 3级回退渲染 |
| 几何计算 | geo_utils.py (纯Python) | 无 scipy/shapely 依赖，~850行 |
| 措施布置 | PlacementEngine v2 | 6阶段×13专用函数×8联动×4级碰撞 |
| 状态管理 | contextvars.ContextVar | 线程安全状态隔离 |
| 调度引擎 | DAGScheduler (自研) | ThreadPoolExecutor + FIRST_COMPLETED |
| LLM 客户端 | LLMClient (OpenAI SDK) | 超时120s + 重试2次 + 指数退避 |

## 2.5 GPU 部署方案

| vLLM 实例 | GPU 分配 | 模型 | 端口 | 用途 |
|-----------|----------|------|------|------|
| Text LLM | GPU 0-1 (TP=2) | Qwen2.5-72B-Instruct-GPTQ-Int8 | 8000 | 5 Agent 共用 |
| VL Model | GPU 2-3 (TP=2) | Qwen2.5-VL-72B-Instruct-GPTQ-Int8 | 8001 | CAD 分析 + VL 验证 |

---

# 3 数据规格

## 3.1 用户输入

| 文件 | 格式 | 必填 | 内容 |
|------|------|------|------|
| facts_v2.json | JSON | 是 | 项目名/地点/工期/投资/分区面积/目标指标 |
| measures_v2.csv | CSV | 是 | 已列措施: ID/名称/单位/数量/单价/合价/位置 |
| CAD 图纸 | DXF/DWG | 否 | 总平面图 → 建筑/道路/红线/绿化自动识别 |
| GIS 数据 | GeoJSON/SHP | 否 | 地形/水系/土壤 |

## 3.2 系统内置数据

| 文件 | 内容 |
|------|------|
| soil_map.json | 土壤类型→侵蚀参数映射 |
| price_v2.csv | 35种措施单价表 |
| fee_rate_config.json | 6层费率参数 |
| measure_library.json | 35种标准措施(名称/类型/单位/优先级/适用分区) |
| measure_symbols.py | 35种措施样式+12种断面模板+分区色彩 |
| legal_refs.json | 法律法规引用 |
| template.docx | 229变量模板 |
| ChromaDB | 范文 RAG 语料库 |

## 3.3 全局状态机 GlobalState (7 分区)

| 分区 | 类型 | 内容 | 并行安全性 |
|------|------|------|------------|
| Static | StaticData | meta, soil_map, price, fee_rate, legal, measure_lib, existing_measures | 只读 |
| ETL | ETLData | zones, rag_ready, site_desc, spatial_layout, gis_gdf, cad_geometry, cad_site_features, site_model, measure_layout | Step 2-3 写入后只读 |
| Calc | CalcData | earthwork, erosion_df, cost_summary, benefit | 各步写不同字段 |
| TplCtx | dict | 229 模板标签 | Step 9 一次性写入后只读 |
| Draft | dict | {chapter_tag: text} | 各章写不同 key |
| Measures | list | existing + planned measures | Step 6 写入后只读 |
| Flags | dict | retry_count, scores, audit_log, final_score, adapter_result | 单线程写入 |

---

# 4 计算引擎详细规格

## 4.1 土方计算 (earthwork.py, ~64行)

挖方/填方/剥离/回填/借方/弃方平衡计算。输出 `Calc.earthwork` dict。

## 4.2 侵蚀预测 (erosion.py, ~141行)

RUSLE 查表法: 3个时期(施工准备期/施工期/自然恢复期) × N个分区。输出 `Calc.erosion_df` DataFrame。

## 4.3 造价估算 (cost.py, ~256行)

6层费率:
```
L1 工程量×单价 → 直接费
L2 + 间接费率 → 间接费
L3 + 利润率 → 利润
L4 + 税金率 → 含税造价
L5 + 预备费率 → 静态投资
L6 + 水保补偿费 → 总投资
```

## 4.4 效益分析 (benefit.py, ~160行)

6项指标: 扰动土地治理率/水土流失治理度/水土流失控制比/拦渣率/林草植被恢复率/林草覆盖率。

## 4.5 状态装配器 (assembler.py, ~405行)

将 7 分区 GlobalState → 229 标签 TplCtx dict (11 个类别):

| 类别 | 标签数 | 示例 |
|------|--------|------|
| 项目元数据 | 16 | project_name, total_investment |
| 分区面积 | 7 | z_建构筑物区, z_total |
| 土方平衡 | 12 | ew_dig, ew_surplus |
| 侵蚀预测 | 24 | ep_total_pred, ep_s1_new |
| 措施定义 | 10 | def_eng_yes/no |
| 措施布局 | 10 | lo_主体_eng_exist/new |
| 费用投资 | ~55 | c_grand_total, c1_total |
| 章节摘要 | 7 | total_swc_investment |
| 效益指标 | 18 | t_治理度, ok_覆盖率 |
| 章节文本 | ~30 | chapter2_组成, chapter5_措施 |
| 循环表格 | 6 | land_use_table, erosion_table, cost_detail_table |

辅助函数: `_clean_chapter_text()` — 移除 `===TAG===`、Markdown、LLM 元文本、docxtpl 泄漏。

---

# 5 智能体详细规格

## 5.1 基础框架 (base.py, ~380行)

### 5.1.1 LLMClient

```python
class LLMClient:
    def __init__(self, base_url, model, timeout=120, max_retries=2)
    def chat(messages, tools, temperature) → response
    # 内置: httpx超时120s + 重试2次 + 指数退避(1s→2s)
```

### 5.1.2 ToolCallingAgent

```python
class ToolCallingAgent:
    TOOL_RESULT_MAX_CHARS = 8000  # 工具返回截断

    def run(prompt, max_turns=AGENT_MAX_TURNS) → str
    # ReAct 循环: prompt → LLM → tool_calls → execute → append → repeat
    # 消息窗口: _trim_messages() 自动管理上下文
```

### 5.1.3 消息窗口管理

| 层级 | 方法 | 耗时 | 功能 |
|------|------|------|------|
| L1 | _extract_structured_summary() | 0ms | 提取工具名(次数)+关键数值+错误 |
| L2 | _llm_summarize_dropped() | 2-5s | 可选 LLM 256-token 摘要 |
| L3 | _trim_messages() | 0ms | 48K 硬截断，保留 head+tail |

## 5.2 措施规划师 Agent (planner.py, ~224行)

**System Prompt**: 高级水保措施规划师，分析分区→查库→估量→合规。

**输出格式**: JSON 数组 (措施名称/分区/类型/单位/数量/功能/**空间布置**)

**6 个工具** (planner_tools.py + spatial_tools.py):
| 工具 | 功能 |
|------|------|
| measure_library | 查询标准措施库(35种) |
| quantity_estimator | 基于面积/周长估算工程量 |
| spatial_context_tool | 获取分区边界+道路+建筑空间数据 |
| atlas_reference_tool | 查询图集RAG标准设计规则 |
| regulation_lookup | 查询法规条文 |
| existing_measures | 查询已列措施避免重复 |

**Fallback**: `_default_measures()` 纯规则硬逻辑 + quantity_estimator。

## 5.3 数据适配器 Agent (adapter.py, ~219行)

**位置**: Step 9.5 (assemble 之后、writer 之前)

**校验规则** (按标签类别):

| 类别 | 缺失时回调 |
|------|-----------|
| project_meta | 不可回调(用户输入) |
| earthwork/erosion | rerun_calculator |
| measures_def/layout | callback_planner |
| cost/benefit | rerun_calculator |
| loop_tables | 依赖上游修复 |

**6 个工具** (adapter_tools.py):
validate_completeness / validate_cross_refs / rerun_calculator / callback_planner / reassemble / get_fix_suggestion

**降级**: `_fallback_adapter()` 最多 2 轮 Python 硬逻辑校验+修复+reassemble。

## 5.4 撰稿智能体 Agent (writer.py, ~645行)

**8 章配置** (CHAPTER_CONFIGS):

| 章节 | 标签数 | 内容 |
|------|--------|------|
| Ch2 | 4 | 项目概况: 组成/施工组织/拆迁/自然条件 |
| Ch3 | 3 | 水保评价: 场地/布局/措施定义 |
| Ch4 | 5 | 流失预测: 现状/因素/预测/危害/指导 |
| Ch5 | 4 | 措施设计: 分区/布局/措施详情/施工要求 |
| Ch6 | 3 | 监测: 内容方法/监测点/实施 |
| Ch7 | 4 | 投资效益: 原则/依据/方法/效益 |
| Ch8 | 6 | 实施保障: 组织管理/后续设计/施工管理/监理/竣工/验收 |
| Ch1 | 6+ | 综合说明: 简述/法律/评价/... (最后生成) |

**并行策略**: Phase1 Ch2-8 并行(4 workers) → Phase2 Ch1 串行

**文本清洗** (_sanitize_text): 移除 16 类 LLM 元文本 + Markdown + 工具引用

**解析回退** (_parse_chapter_output): ===TAG=== → ### 标题 → 关键词行 → 编号段落 → 全文兜底

**4 个工具** (writer_tools.py):
calc_lookup / rag_search / self_checker / prev_chapter

## 5.5 绘图智能体 Agent (drawing.py, ~281行)

**工作流**: 获取数据 → 获取样式参考 → 生成 DrawingPlan JSON → 提交渲染引擎 → 验证图像

**关键规则**: 只输出 JSON，不输出坐标 — 几何引擎自动处理

**图像验证**: `_is_valid_image()` — PNG 头校验 + 文件大小 + matplotlib 像素方差

**4 个工具** (drawing_tools.py):
get_project_data / get_style_reference / submit_drawing_plan / verify_image

**Fallback**: 产出 < 2 张 → 回退到 MeasureMapRenderer 确定性渲染

## 5.6 审计智能体 Agent (auditor.py, ~256行)

**4 维评分** (加权总分):

| 维度 | 权重 | 方法 |
|------|------|------|
| 数值一致性 | 40% | numeric_validator (Python 硬校验) |
| 文本质量 | 30% | text_validator (逐章校验) |
| 结构完整性 | 20% | rag_comparator (范文对比) |
| 标签覆盖率 | 10% | 非空标签/总标签 |

**3 个工具** (auditor_tools.py):
numeric_validator / text_validator / rag_comparator

**重试策略**: 60-79分 → 章节级重写(并行) + AgentContext 隔离

**failure_details**: severity(critical/major/minor) + failure_source(writer/calc/render) + suggested_action

---

# 6 CAD 解析与空间分析

## 6.1 DXF 解析管线

```
DXF 文件
  │
  ├── cad.py: convert_cad_to_png()
  │   3级回退: ezdxf+matplotlib → ODA → LibreCAD
  │
  └── cad_base_renderer.py: parse_dxf_geometry()
      │
      ├── 提取 6 类实体: LWPOLYLINE/LINE/ARC/CIRCLE/TEXT/HATCH
      ├── 图层关键词分类 → building/road/boundary/greenery/annotation/other
      ├── 颜色提取: _extract_dxf_color() → properties["dxf_color"] (ACI 0-255)
      │
      └── CadGeometry 数据结构
          ├── entities: List[CadEntity]      # 62838个实体 (demo)
          ├── boundaries: List[CadEntity]     # 92个边界实体
          ├── bounds: (xmin, ymin, xmax, ymax)
          └── content_bounds: MAD稳健边界(排除离群点)
```

## 6.2 图层分类关键词 (cad_base_renderer.py)

| 分类 | 关键词 |
|------|--------|
| building | 建筑, build, bldg, buid, house, 构筑, 结构, struct, 地下室, basement, roof, 屋顶, 楼梯, stair, flor, floor |
| road | 道路, road, path, drive, 车道, 人行, sidewalk, 广场, plaza, parking, 停车, 铺装, pave |
| boundary | 红线, redline, 用地, site, boundary, 边界, bound, 范围, scope |
| greenery | 绿化, green, 景观, landscape, 植物, plant, 树, tree, 草, grass |
| annotation | 标注, dim, text, anno, label, 文字, 尺寸, dimension |

**v8.2 变更**: 从 building 移除 `wall/墙/柱/column/arch/foundation/基础/fenc/elev/cons` 共10个词 → 回退到 `other` 分类。

## 6.3 特征分析器 (cad_feature_analyzer.py, ~1784行)

### 6.3.1 8步分析管线

```
CadGeometry
  │
  ├── Step 1: 2D网格密度聚类 (BFS过滤离群点)
  ├── Step 2: 几何特征分类 (_classify_by_geometry)
  │   ├── 颜色优先: ACI 2 (黄色) 闭合 + area>10m² → building (v8.2)
  │   ├── 建筑: 100<area<15000 + verts≤12 + aspect<4
  │   ├── 道路: 50<area<20000 + aspect≥3
  │   ├── 绿地: 100<area<50000 + verts>10
  │   └── 边界: area > 30% 场地面积
  ├── Step 3: 红线提取 (7级回退)
  ├── Step 4: 道路边缘提取
  ├── Step 5: 建筑足迹提取 (_classify_areas)
  │   └── building min_area: 50m² (普通) / 10m² (黄色ACI=2)
  ├── Step 6: 入口/排水口提取
  ├── Step 7: 标高点提取 (TEXT正则匹配)
  └── Step 8: 地形拟合 (最小二乘平面→坡度/坡向)
```

### 6.3.2 红线提取 7 级回退

| 级别 | 方法 | 信号强度 |
|------|------|----------|
| L0 | 用户 project_meta 提供坐标 | 最强 |
| L0.5 | 扩展图层名搜索 (非矩形, area≥1000m²) | 强 |
| **L0.7** | **颜色过滤: ACI=1 (红色) 最大非矩形闭合多边形** | **强** |
| L0.8 | 开放折线端到端拼接 (如 P-LIMT 多段) | 中 |
| L1 | 最长闭合边界折线 | 中 |
| L1.5 | 面积匹配搜索 (基于 land_area_hm2) | 弱 |
| L1.6-L4 | 最大多边形 → 凸包回退 | 兜底 |

### 6.3.3 颜色辅助分类 (v8.2)

| ACI 颜色 | 用途 | 实现位置 |
|-----------|------|----------|
| ACI 1 (红色) | 项目红线 | _extract_boundary_by_color() L0.7 |
| ACI 2 (黄色) | 建筑足迹 | _classify_by_geometry() + _classify_areas() |

### 6.3.4 输出: CadSiteFeatures

```python
@dataclass
class CadSiteFeatures:
    boundary: List[Point]           # 红线边界
    road_edges: List[EdgeInfo]      # 道路边缘线段
    building_footprints: List[AreaFeature]  # 建筑足迹(已过滤围墙)
    entrances: List[PointFeature]   # 出入口
    drainage_outlets: List[PointFeature]  # 排水口
    zone_polygons: Dict[str, List[Point]] # 分区多边形
    greenery_areas: List[AreaFeature]     # 绿化区域
    elevation_points: List[ElevPoint]     # 标高点(x,y,z)
    drainage_direction: str               # 排水方向
    computed_slope_pct: float             # 计算坡度
    computed_slope_direction: str         # 计算坡向
    computed_elev_range: Tuple[float,float] # 高程范围
```

## 6.4 SiteModel 多源融合 (site_model.py, ~514行)

### 6.4.1 数据源置信度

| 数据源 | 置信度 | 来源 |
|--------|--------|------|
| GIS (GeoJSON/SHP) | 0.95 | 测量数据 |
| ezdxf (DXF 解析) | 0.85 | CAD 设计图 |
| VL (视觉语言模型) | 0.60-0.80 | 图像理解 |
| META (用户输入) | 0.50 | 手动录入 |

### 6.4.2 SiteModelBuilder 4 阶段构建

```python
model = (SiteModelBuilder()
    .from_ezdxf(cad_geometry, cad_site_features)   # Phase 1: CAD → 边界+道路+建筑+POI
    .from_gis(gis_gdf)                              # Phase 2: GIS → 高精度覆盖
    .from_meta(facts, zones)                         # Phase 3: 用户输入 → 基本信息
    .from_vl(vl_description, vl_scene_type)          # Phase 4: VL → 语义描述
    .build())                                        # 合并 → SiteModel
```

### 6.4.3 障碍物过滤 (v8.2)

```python
# from_ezdxf() 中:
for bldg in cad_site_features.building_footprints:
    if bldg.area < 50.0:  # 过滤围墙/小构筑物
        continue
    model.global_obstacles.append(Obstacle(...))
```

### 6.4.4 SiteModel 数据结构

```python
@dataclass
class SiteModel:
    boundary: BoundaryInfo              # 项目红线
    zones: Dict[str, ZoneModel]         # 分区 (含边缘/障碍/POI/地形)
    terrain: TerrainInfo                # 全局地形
    global_edges: List[EdgeFeature]     # 全局道路边缘
    global_obstacles: List[Obstacle]    # 全局障碍物(建筑)
    global_pois: List[PointOfInterest]  # 全局POI(入口/排水口)
    vl_global_description: str          # VL 场景描述
    vl_scene_type: str                  # VL 场景类型
    build_log: List[str]                # 构建日志
```

---

# 7 PlacementEngine v2 几何布置引擎

## 7.1 架构总览

**包结构**: `src/placement/` (~2700行)

| 文件 | 行数 | 功能 |
|------|------|------|
| `__init__.py` | 52 | 包导出 |
| `types.py` | 215 | 枚举/数据类/常量表 |
| `classifier.py` | 51 | 措施分类 + 策略路由 |
| `hydro_adapter.py` | 279 | 3级水文降级 |
| `placers.py` | 1356 | 7通用策略 + 13专用函数 |
| `linkage.py` | 256 | 8条联动规则 |
| `collision.py` | 308 | 4级碰撞检测 |
| `engine.py` | 561 | 6阶段主引擎 |
| `placement_engine.py` | 38 | 向后兼容 shim |

## 7.2 6阶段流水线

```
Phase 1: Place     → 专用布置函数(13个) / 通用策略(7个) 回退
Phase 2: Linkage   → 8条联动规则 + auto_create 目标措施
Phase 3: Collision  → 距离规则 + 互斥规则 + 4级碰撞解决
Phase 4: Optimize  → 全局二次优化 (大固定,小调整)
Phase 5: Summary   → 统计信息 (联动/水文/tier)
Phase 6: Clamp     → 边界裁剪 + 建筑避让
```

## 7.3 类型系统 (types.py)

### 7.3.1 枚举

| 枚举 | 值 |
|------|-----|
| MeasureType | LINE, AREA, POINT, OVERLAY |
| Strategy | EDGE_FOLLOW, BOUNDARY_FOLLOW, AREA_FILL, AREA_COVER, POINT_AT, POINT_ALONG, OVERLAY |
| LinkageType | DOWNSTREAM, UPSTREAM, ADJACENT, PERIMETER |

### 7.3.2 PlacementResult

```python
@dataclass
class PlacementResult:
    measure_name: str
    zone_id: str
    measure_type: MeasureType
    strategy: Strategy
    polyline: Optional[List[Point]]         # 单段线
    polylines: Optional[List[List[Point]]]  # 多段线
    polygon: Optional[List[Point]]          # 面
    points: Optional[List[Point]]           # 点集
    label_anchor: Optional[Point]           # 标注锚点
    skipped: bool                           # 是否跳过
    skip_reason: str                        # 跳过原因
    linked_to: Optional[List[str]]          # 联动目标
    linkage_lines: Optional[List[List[Point]]]  # 联动连接线
    hydro_info: Optional[Dict]              # 水文信息
```

### 7.3.3 规则表

**距离规则** (DISTANCE_RULES): 13对措施最小间距

**互斥规则** (EXCLUSION_RULES): 4对措施互斥

**联动规则** (LINKAGE_RULES): 9条自动创建链

**沟/池尺寸表**: 5级汇水面积→(宽,深)/(长,宽,深) 自动选型

## 7.4 分类与路由 (classifier.py)

```python
classify_measure(name, unit) → MeasureType
# 3级回退: 关键词(30+) → 单位(12) → 默认AREA

route_strategy(name, measure_type) → Strategy
# 2级回退: 关键词 → 类型默认
```

## 7.5 水文适配器 (hydro_adapter.py)

### 3 级降级

| Tier | 数据源 | 精度 |
|------|--------|------|
| Tier 1 | HydroReport (汇水面积/径流系数) | 最高 |
| Tier 2 | 标高点 IDW 插值 (SiteModel) | 中 |
| Tier 3 | 规范默认值 | 兜底 |

**功能**: 排水沟断面自动选型 / 沉砂池尺寸选型 / 汇流方向 / 最低点

## 7.6 布置函数 (placers.py, ~1356行)

### 7.6.1 GeometryClipper — 7 通用策略

| 策略 | 适用 | 算法 |
|------|------|------|
| EDGE_FOLLOW | 排水沟 | 沿道路边缘平行偏移 |
| BOUNDARY_FOLLOW | 围挡 | 沿红线内缩 |
| AREA_FILL | 绿化 | 分区85%内缩填充 |
| AREA_COVER | 防尘网 | 整区覆盖 |
| POINT_AT | 沉砂池 | POI感知+最低点 |
| POINT_ALONG | 监测点 | 沿边缘均匀间距 |
| OVERLAY | 绿色屋顶 | 叠加建筑足迹 |

### 7.6.2 13 专用布置函数

| 函数 | 措施 | 特殊逻辑 |
|------|------|----------|
| place_drainage_ditch | 排水沟 | 全局道路搜索+坡向感知+多段 |
| place_intercept_ditch | 截水沟 | 垂直坡向+多段 |
| place_temp_drainage | 临时排水 | 分区92%内缩+排水口断口 |
| place_construction_fence | 围挡 | 红线环路+入口8m断口 |
| place_sedimentation_basin | 沉砂池 | 最低点+水文选型 |
| place_vehicle_wash | 洗车平台 | 入口内退12m |
| place_monitoring_points | 监测点 | 上游参照+下游影响双点 |
| place_rainwater_tank | 雨水收集 | 多标准评分(远建筑+近低点) |
| place_greening | 绿化 | 建筑凸包±8m缓冲 |
| place_dust_net_cover | 防尘网 | 整区覆盖 |
| place_temp_cover | 苫盖 | 分区减硬化障碍 |
| place_roadside_trees | 行道树 | 6m间距+跳入口8m+跳建筑3m |
| place_topsoil_recovery | 表土回覆 | 绿化区减障碍80%内缩 |

### 7.6.3 PLACER_REGISTRY

```python
PLACER_REGISTRY = [
    (["排水沟"], place_drainage_ditch),
    (["截水沟","拦水沟"], place_intercept_ditch),
    (["围挡","围墙","围栏"], place_construction_fence),
    (["沉沙池","沉淀池","沉砂池"], place_sedimentation_basin),
    (["洗车","冲洗台"], place_vehicle_wash),
    # ... 共13条
]
```

## 7.7 联动解析器 (linkage.py)

### 9 条联动规则

| 源措施 | 目标措施 | 方向 | auto_create |
|--------|----------|------|-------------|
| 排水沟 | 沉砂池 | DOWNSTREAM | ✅ |
| 截水沟 | 沉砂池 | DOWNSTREAM | ✅ |
| 洗车平台 | 三级沉淀池 | DOWNSTREAM | ✅ |
| 防尘网 | 截水沟 | PERIMETER | ❌ |
| 排水沟 | 雨水收集 | DOWNSTREAM | ❌ |
| 绿化 | 排水沟 | ADJACENT | ❌ |
| 围挡 | 排水沟 | ADJACENT | ❌ |
| 苫盖 | 截水沟 | PERIMETER | ❌ |
| 临时排水 | 沉砂池 | DOWNSTREAM | ✅ |

auto_create=✅: 目标不存在时自动创建。

## 7.8 碰撞检测 (collision.py)

### CollisionResolverV2 — 4+1 级

| 级别 | 检查 | 动作 |
|------|------|------|
| L0 | 互斥规则 (EXCLUSION_RULES) | skip |
| L1 | 距离规则 (DISTANCE_RULES) | shift to satisfy |
| L2 | 重叠检测 | shift (10/20/30/40/50m) |
| L3 | 仍然重叠 | scale 70% |
| L4 | 仍然失败 | skip |

**优化**: 同区 LINE+LINE 跳过碰撞(沟+围挡可共存)；跨区跳过(自然邻接)。

## 7.9 API

```python
# 单措施 API (向后兼容)
engine.resolve(measure_name, zone_id, unit, quantity, zone_bounds) → dict | None

# 批量 API (6阶段完整流水线)
engine.resolve_all(measures, zone_assignments) → Dict[zone_id, Dict[measure_name, PlacementResult]]

# 查询 API
engine.get_placement(measure_name, zone_id) → dict | None
engine.get_placement_summary() → str
engine.has_precomputed() → bool
```

---

# 8 绘图与渲染系统

## 8.1 双引擎架构

```
Step 12_drawings:
  │
  ├── 路线A: Drawing Agent (LLM)
  │   ├── DrawingPlan JSON → DrawingRenderer 确定性渲染
  │   ├── PNG + DXF 双输出
  │   └── 失败(<2张) → 路线B
  │
  └── 路线B: MeasureMapRenderer (确定性)
      ├── PlacementEngine v2 → 空间布置数据
      ├── CAD 底图 + 彩色措施叠加
      └── 专业装饰 (指北针/比例尺/图例/工程量表)
```

## 8.2 DrawingPlan (drawing_plan.py, ~481行)

LLM 输出结构化数据:

```python
@dataclass
class DrawingPlan:
    map_type: str           # zone_boundary/measure_layout/zone_detail/typical_section
    title: str              # 图名
    zones: List[ZoneSpec]   # 分区(position/emphasis)
    measures: List[MeasureSpec]  # 措施(position/direction/coverage)
    sections: List[SectionSpec]  # 断面(structure/dimensions/annotation_notes)
    layout_hints: Dict      # 布局提示
```

**JSON 解析 4 级回退**: 直接解析 → 代码块 → {} 正则 → 错误修复

**位置词汇** (封闭集): north/south/east/west/center/northeast/... + perimeter
**方向词汇**: north-south/east-west/clockwise/along-road/along-boundary
**覆盖词汇**: full/partial/edge

## 8.3 DrawingRenderer (drawing_renderer.py, ~1400行)

### 4 种图型

| 图型 | 内容 | 输出 |
|------|------|------|
| zone_boundary | 防治分区图 | 分区色块+面积标注+红线 |
| measure_layout | 措施总体布置图 | CAD底图+全部措施+图例+工程量表 |
| zone_detail | 分区措施详图 | 单分区放大+措施详情 |
| typical_section | 典型断面图 | 断面模板+尺寸标注 |

### 专业装饰

指北针 / 比例尺 / 坐标网格 / 图例 / 工程量表 / 标题栏

### DXF 输出

分层: 0-zone(分区色块) + 1-measure(措施) + 2-annotation(标注)

## 8.4 MeasureMapRenderer (measure_map.py, ~1901行)

**确定性回退引擎**: 不依赖 LLM，纯 Python 渲染。

```
SiteModel/CadGeometry + PlacementEngine
  │
  ├── 渲染 CAD 底图 (CadBaseMapRenderer)
  ├── 叠加分区色块 (zone_boundary_map)
  ├── 叠加措施几何 (measure_layout_map)
  │   ├── PlacementResult → 线/面/点渲染
  │   ├── 联动连接线
  │   └── 标注文字
  ├── 分区详图 (zone_detail)
  └── 典型断面图 (typical_section)
```

## 8.5 措施样式系统 (measure_symbols.py, ~501行)

### 35 种措施样式

```python
MEASURE_STYLES = {
    "排水沟": {"line": True, "color": "#2196F3", "linewidth": 2.0, ...},
    "沉砂池": {"point": True, "marker": "s", "color": "#FF5722", ...},
    "综合绿化": {"fill": True, "facecolor": "#A5D6A7", ...},
    # ... 35种
}
```

### 12 种断面模板 (SECTION_TEMPLATES)

矩形沟 / 梯形沟 / 重力式挡墙 / 沉砂池 / 透水砖铺装 / 洗车平台 / 苫盖 / ...

### 分区色彩

灰度 (ZONE_COLORS) + 彩色 (ZONE_COLORS_PROFESSIONAL)

### Z-Order 层级

background(0) → zones(10) → measures(20) → labels(30) → decorations(40)

## 8.6 CadBaseMapRenderer (cad_base_renderer.py, ~920行)

**两种渲染模式**:

| 模式 | 用途 | 特点 |
|------|------|------|
| render_background() | 底图 | 半透明, 浅色 |
| render_foreground() | 主图 | 全色, 建筑填充+道路+红线 |

**MAD 稳健边界**: 中位绝对偏差过滤离群点，自动计算 content_bounds

## 8.7 纯 Python 几何库 (geo_utils.py, ~850行)

**无 scipy/shapely 依赖**:

| 类别 | 函数 |
|------|------|
| 基础 | dist, polyline_length, shoelace_area, polygon_centroid, points_bounds |
| 凸包/凹包 | convex_hull (Graham scan), knn_concave_hull (KNN) |
| 碰撞 | line_segment_intersection, point_in_polygon, aabb_overlap, polygons_overlap |
| 裁剪 | clip_polygon (Sutherland-Hodgman), clip_polyline (Cohen-Sutherland) |
| 偏移 | offset_polyline, buffer_polygon, scale_polygon |
| 采样 | sample_points_in_polygon, sample_along_polyline, polygon_edges |
| 工具 | nearest_point_on_polyline, merge_close_points, polyline_trim, find_lowest_point |

---

# 9 并行执行与 DAG 调度

## 9.1 DAGScheduler (dag_scheduler.py, ~190行)

```python
@dataclass
class StepNode:
    name: str
    func: Callable
    depends_on: list[str]
    status: str = "pending"   # pending/running/done/failed/skipped
    error: Exception | None
    critical: bool = True
```

**调度算法**:
```
while 有 pending/running 步骤:
    ready = [s if 所有依赖 "done" 且自身 "pending"]
    for s if 有依赖 "failed"/"skipped":
        s.status = "skipped"     # 失败传播
    submit ready → ThreadPoolExecutor
    wait(FIRST_COMPLETED)
    update status + emit on_progress()
```

## 9.2 ContextVar 状态隔离 (context.py, ~114行)

| 组件 | 用途 |
|------|------|
| `_ctx_state: ContextVar` | 当前线程 GlobalState |
| `_ctx_atlas_rag: ContextVar` | 当前线程 AtlasRAG |
| `_ctx_output_dir: ContextVar` | 当前线程输出目录 |
| `AgentContext` | with 语句管理器 (set/reset token) |

**隔离保证**: 每个 ThreadPoolExecutor 任务创建独立 AgentContext → 线程安全

## 9.3 并行组读写集合分析

| 并行组 | 步骤 | 读 | 写 | 竞态 |
|--------|------|----|----|------|
| A | 3_spatial | ETL.zones | ETL.spatial_layout | 无 |
| A | 4_earthwork | Static, ETL.zones | Calc.earthwork | 无 |
| A | 5_erosion | Static, ETL.zones | Calc.erosion_df | 无 |
| B | 10_writer | Static,Calc,TplCtx | Draft | 无(不同key) |
| B | 11_charts | Calc | PNG文件 | 无 |
| B | 12_drawings | Static,ETL,Measures | PNG文件 | 无 |

## 9.4 配置与降级

| 变量 | 默认 | 说明 |
|------|------|------|
| WRITER_WORKERS | 4 | Writer 并行章节数 |
| DRAWING_WORKERS | 3 | Drawing 并行图数 |
| PIPELINE_PARALLEL | true | DAG/线性模式切换 |

`PIPELINE_PARALLEL=false` 一键回退线性模式。

---

# 10 LLM 韧性与上下文管理

## 10.1 LLMClient 韧性层

```python
class LLMClient:
    timeout = 120s        # httpx 超时
    max_retries = 2       # 指数退避 (1s → 2s)
```

覆盖所有 5 个 Agent 的 LLM 调用。

## 10.2 消息窗口管理

| 层级 | 策略 | 耗时 |
|------|------|------|
| L1 | 结构化摘要: 工具名(次数)+数值+错误 | 0ms |
| L2 | 可选 LLM 256-token 摘要 (CONTEXT_SUMMARIZE_LLM=true) | 2-5s |
| L3 | 48K 硬截断 (keep head+tail) | 0ms |

**工具结果截断**: 8000 字符/个。

## 10.3 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| LLM_TIMEOUT | 120 | httpx 超时(秒) |
| LLM_MAX_RETRIES | 2 | 重试次数 |
| ADAPTER_MAX_TURNS | 8 | 适配器最大轮次 |
| ADAPTER_MAX_CALLBACKS | 2 | 适配器修复循环次数 |
| CONTEXT_SUMMARIZE_LLM | false | 启用 LLM 摘要压缩 |
| CONTEXT_SUMMARY_MAX_TOKENS | 256 | 摘要输出token数 |

---

# 11 前后端与部署规格

## 11.1 Web UI

| 端口 | 服务 | 功能 |
|------|------|------|
| :8080 | user_app | 报告生成、项目数据、下载 |
| :8081 | admin_app | 知识库管理、LLM 设置 |

**前端技术**: Vue 3 + Vite + Element Plus
**SSE 进度推送**: /api/pipelines/{id}/events
**数据库**: SQLite (server.db)

## 11.2 部署模式

### AutoDL 一键 (autodl_start.py, ~609行)

```bash
python autodl_start.py              # 完整: 下载+安装+vLLM+Web
python autodl_start.py --cli        # CLI: vLLM+Pipeline
python autodl_start.py --web-only   # 仅Web
python autodl_start.py --no-vl      # 跳过VL模型(双卡机)
```

### 手动部署

```bash
# Text LLM (GPU 0-1)
python -m vllm.entrypoints.openai.api_server \
  --model Qwen2.5-72B-Instruct-GPTQ-Int8 --tp 2 --port 8000

# VL (GPU 2-3)
python -m vllm.entrypoints.openai.api_server \
  --model Qwen2.5-VL-72B-Instruct-GPTQ-Int8 --tp 2 --port 8001

# Web
python run_server.py

# CLI
python scripts/run.py -v
```

### 本地开发 (run_local.py)

Ollama + qwen3:8b，单线程模式。

---

# 12 报告模板与渲染规格

## 12.1 三阶段渲染 (renderer.py, ~374行)

| 阶段 | 方法 | 功能 |
|------|------|------|
| Phase 1 | docxtpl | 229 变量替换 |
| Phase 2 | python-docx | 循环表格填充 (4张表) |
| Phase 3 | python-docx | 措施图后插入 (第五章后) |

### Phase 2 循环表格

| 表 | 内容 | 字段 |
|----|------|------|
| T5 | existing_measures | id/name/unit/qty/location/cost |
| T9 | zone1_measures | type/name/form/location/period/qty/unit |
| T10 | zone2_measures | 同上 |
| T12 | cost_detail_table | id/name/unit/qty/price/total |

### Phase 3 图插入顺序

zone_boundary_map → measure_layout_map → zone_detail_* → typical_section_*

## 12.2 完整性检查

```python
check_completeness(docx_path) → {pass, issues}
# 文件大小: 50KB-20MB
# 残留标签: {{ }} 或 {%...%}
# 空表格数
# 非空段落比: ≥30%
```

---

# 13 测试体系

## 13.1 测试覆盖 (96 tests)

| 测试文件 | 测试数 | 覆盖模块 |
|----------|--------|----------|
| test_placement.py | 47 (6组) | PlacementEngine v2 全流程 |
| test_measure_map.py | ~15 | MeasureMapRenderer |
| test_repair_e2e.py | ~8 | CAD→措施图端到端 |
| test_drawing_agent.py | ~6 | Drawing Agent |
| test_writer_sanitize.py | ~8 | 文本清洗 |
| test_assembler.py | ~4 | 229标签装配 |
| test_cost.py | ~3 | 造价计算 |
| test_pipeline.py | ~2 | Pipeline 集成 |
| test_benefit.py | ~2 | 效益分析 |
| test_erosion.py | ~1 | 侵蚀预测 |

## 13.2 关键测试场景

- **test_placement.py 6 组**: 分类器/水文适配/布置函数/联动/碰撞/引擎集成
- **test_repair_e2e.py**: DXF→CadGeometry→CadSiteFeatures→SiteModel→PlacementEngine→措施图 完整链路
- **test_measure_map.py**: 需传入 PlacementEngine (无矩形回退,无数据时返回空)

---

# 14 非功能性需求

| 需求 | 规格 |
|------|------|
| 生成时间 | ≤8分钟 (4×A800) |
| 并发用户 | MVP: 1 (单机) |
| 文件大小 | 输出 .docx: 50KB-20MB |
| 措施图 | ≥10张 PNG (≥500KB/张) |
| GPU 显存 | 4×80G (Text:2卡 + VL:2卡) |
| 可观测性 | SSE 进度 + audit.json + build_log |
| 降级 | use_llm=False → 全 Python 硬逻辑 |
| 线性回退 | PIPELINE_PARALLEL=false |

---

# 15 已知架构债务

## P1 — 高优先级

| 编号 | 问题 | 影响 | 建议 |
|------|------|------|------|
| P1-1 | GlobalState 无序列化 | 无断点恢复 | JSON snapshot on step done |
| P1-2 | DAG 读写集合无自动验证 | 新步骤可能引入竞态 | 声明式读写集合 + RLock |
| P1-3 | 工具错误 4 种格式 | LLM 解析困难 | 统一 ToolResult(success,data,error) |
| P1-4 | Pipeline 无 critical/non-critical 分级 | 图表失败=土方失败 | 步骤分级+回退处理器 |

## P2 — 中优先级

| 编号 | 问题 | 建议 |
|------|------|------|
| P2-1 | CAD 仅识别 3 分区(建筑/道路/绿化) | 增加施工生产生活区+临时堆土区识别 |
| P2-2 | 仅提取 ACI 颜色索引 | 扩展 true_color (24-bit RGB) 支持 |
| P2-3 | measure_library.json 仅 35 种 | 扩展至 50+ 种措施 |
| P2-4 | 单省份(江苏)费率 | 多省份费率表 |

---

## 代码量统计

| 目录 | 行数 | 说明 |
|------|------|------|
| src/ (核心) | ~22,360 | 含 agents/ tools/ placement/ calculators/ web/ |
| scripts/ | ~1,720 | CLI/诊断/demo |
| tests/ | ~2,490 | 96 tests |
| **总计** | **~26,570** | |

### 核心文件清单

| 文件 | 行数 | 功能 |
|------|------|------|
| measure_map.py | 1901 | MeasureMapRenderer (确定性回退) |
| cad_feature_analyzer.py | 1784 | 8步CAD特征分析 |
| drawing_renderer.py | 1493 | 4图型PNG+DXF渲染 |
| placers.py | 1356 | 7通用+13专用布置函数 |
| cad_base_renderer.py | 920 | DXF解析+底图渲染 |
| pipeline.py | 874 | 18步DAG流水线 |
| geo_utils.py | 842 | 纯Python几何库 |
| atlas_rag.py | 685 | 图集RAG索引 |
| writer.py | 645 | 撰稿Agent |
| engine.py | 561 | PlacementEngine v2 |
| drawing_tools.py | 520 | 绘图工具4个 |
| site_model.py | 514 | 多源融合SiteModel |
| measure_symbols.py | 501 | 样式/断面/色彩 |
| adapter_tools.py | 492 | 适配器工具6个 |
| drawing_plan.py | 481 | DrawingPlan数据结构 |
| assembler.py | 405 | 229标签装配 |
| base.py | 380 | LLMClient+ToolCallingAgent |
| renderer.py | 374 | 3阶段docx渲染 |
