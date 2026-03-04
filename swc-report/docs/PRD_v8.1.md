# 水土保持方案自动生成系统 — 产品需求文档 (PRD)

> **文档编号**: SWCP-PRD-2026-001
> **版本**: v8.1 — LLM 韧性层 + 数据适配器 + 结构化摘要
> **日期**: 2026-02-26
> **密级**: 内部

---

## 修订记录

| 版本 | 日期 | 修订人 | 修订内容 |
|------|------|--------|----------|
| v1.0 | 2026-02-09 | 作者 | 初稿，基础架构设计 |
| v2.0 | 2026-02-10 | Claude | 补充6层费率引擎、229模板标签映射、状态装配器、双轨校验 |
| v3.0 | 2026-02-10 | Claude | 重组处理层为编制集群+审计集群，审计智能体替代原双轨校验 |
| v4.0 | 2026-02-10 | Claude | 新增措施规划师Agent、撰稿升级为Agent、11个工具定义、GPU分配方案、完整前后端规格 |
| v5.0 | 2026-02-12 | Claude | 新增绘图智能体(4工具)、技术栈对齐实际代码(Vue3/SQLite)、GPTQ-Int8双实例GPU方案、AutoDL一键部署、措施图渲染引擎、17步流水线完整定义 |
| v8.0 | 2026-02-26 | Claude | 三大架构升级: (1) ContextVar 状态解耦替代 module-level 全局变量; (2) ThreadPoolExecutor 并行执行 — Writer 7章并行+Drawing 全图并行+审计重写并行; (3) DAG 调度器替代线性 Pipeline |
| **v8.1** | **2026-02-26** | **Claude** | **四项增强: (1) LLM 韧性层 — 超时+重试+指数退避; (2) 数据适配器智能体 Step 9.5 — 校验+回调修复+reassemble; (3) 消息窗口管理 — 结构化摘要+可选 LLM 摘要替代硬截断; (4) 并行线程 AgentContext 隔离修复; 新增 6 个环境变量; 记录 4 项 P1 架构债务** |

---

## 目录

1. [产品概述](#1-产品概述)
2. [系统架构](#2-系统架构)
3. [数据规格](#3-数据规格)
4. [计算引擎详细规格](#4-计算引擎详细规格)
5. [智能体详细规格](#5-智能体详细规格)
6. [并行执行与 DAG 调度](#6-并行执行与-dag-调度)
7. [LLM 韧性与上下文管理](#7-llm-韧性与上下文管理)
8. [前端详细规格](#8-前端详细规格)
9. [后端API详细规格](#9-后端api详细规格)
10. [报告模板与渲染规格](#10-报告模板与渲染规格)
11. [部署规格](#11-部署规格)
12. [非功能性需求](#12-非功能性需求)
13. [已知架构债务](#13-已知架构债务)
14. [实施计划](#14-实施计划)

---

# 1 产品概述

## 1.1 产品定位

本系统是一套面向水土保持咨询机构的自动化方案编制工具。系统接收项目基本信息、已有措施清单等输入数据，通过计算引擎完成土方平衡、侵蚀预测、造价估算等确定性计算，再由多智能体协作完成措施规划、报告撰写、措施图绘制和质量审计，最终输出符合《生产建设项目水土保持方案编制技术规范》(GB/T 51240) 的完整方案报告书 (.docx) 及附图包 (.zip)。

## 1.2 目标用户

水土保持咨询公司的方案编制工程师。典型使用场景：接到房地产/市政/工业项目的水保方案编制委托后，工程师将设计院提供的项目概况和施工图中的已有措施信息录入系统，系统在 5-10 分钟内生成初稿，工程师在此基础上人工修改和完善。

## 1.3 核心价值主张

**将一份水保方案的编制周期从 3-5 个工作日压缩至 1 小时以内（含人工审校）。**

当前行业痛点：一份标准的水保方案报告书约 80-120 页，包含 20+ 张专业计算表格、8 个章节的技术文本、7+ 张附图。即使是经验丰富的工程师，从零编制也需要 3-5 天。其中约 70% 的工作量是重复性的计算填表和格式化文本，本系统自动完成这 70%。

**v8.0 性能提升**：通过 DAG 并行调度和 Agent 内并行执行，端到端生成时间从 15 分钟缩短至 **5-8 分钟**。

**v8.1 可靠性提升**：LLM 韧性层确保单次推理失败不中断流水线；数据适配器在写稿前校验并修复数据缺失；结构化摘要保留被裁剪上下文的关键信息。

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
| 调度 | DAG 依赖分析、步骤自动并行、失败传播与降级 | 分布式多机调度 |
| **韧性** | **LLM 超时重试、上下文窗口管理、数据完整性校验** | **跨节点故障恢复** |

## 1.6 关键指标

| 指标 | v5 目标 | v8 目标 | **v8.1 目标** | 度量方式 |
|------|---------|---------|---------------|----------|
| 生成耗时 | ≤15 分钟 | ≤8 分钟 | ≤8 分钟 | API 返回到下载可用 |
| 审计通过率 | ≥60% | ≥60% | ≥60% | 审计智能体评分 ≥80 |
| 数值一致性 | 100% | 100% | 100% | Python 硬校验 0 错误 |
| 人工修改量 | ≤30% | ≤30% | ≤30% | 人工审校后差异统计 |
| 模板覆盖率 | 12 张 | 12 张 | 12 张 | 非空表格 / 总表格 |
| 措施图生成率 | ≥4 张 | ≥4 张 | ≥4 张 | Drawing Agent 成功数 |
| 并发 Agent | 1 (串行) | 7+3 | 7+3 | 同时运行 Agent 数 |
| 步骤并行度 | 1 (线性) | 最大3 | 最大3 | 同时执行 Pipeline 步骤数 |
| **LLM 调用成功率** | **无保障** | **无保障** | **≥99% (含重试)** | **LLM 调用成功次数 / 总次数** |
| **数据完整率** | **无校验** | **无校验** | **≥95% 标签非空** | **适配器校验通过标签数 / 必填标签数** |

---

# 2 系统架构

## 2.1 架构总览

系统采用分层架构，共 7 层。数据从前端上传经 API 进入输入层，预处理后写入全局状态机，处理层的编制集群和审计集群协作完成方案编制，最终渲染输出存储交付。

**v8.0 关键架构升级**：
1. **ContextVar 状态解耦** — 工具函数不再依赖 module-level 全局变量，通过 `contextvars.ContextVar` 实现线程/协程安全的状态访问
2. **并行执行引擎** — Writer Agent 7 章并行 + Drawing Agent 全图并行 + 审计重写并行
3. **DAG 调度器** — 替代线性 17 步 Pipeline，自动分析依赖关系并行执行无依赖步骤

**v8.1 关键架构升级**：
4. **LLM 韧性层** — LLMClient 内置超时 (120s) + 重试 (2次) + 指数退避，单次推理失败不中断流水线
5. **数据适配器智能体** — Step 9.5 校验 229 标签完整性，回调 Planner/Calculator 修复缺失数据
6. **消息窗口管理** — 三层策略: 结构化摘要 (Python) → 可选 LLM 摘要 → 硬截断兜底
7. **并行线程安全修复** — 审计重写线程增加 AgentContext 包裹

### 2.1.1 七层架构

| 层级 | 名称 | 技术栈 | 职责 |
|------|------|--------|------|
| L0 | 前端层 | Vue 3 + Vite + Element Plus | 双端口 SPA：用户端(:8080)报告生成 + 管理端(:8081)知识库/设置 |
| L1 | 后端 API 层 | FastAPI + uvicorn (双端口) | REST API、SSE 进度推送、文件上传 |
| L2 | 输入层 | JSON/CSV/文件存储 | 用户输入 + 系统配置 + 可选文件的统一入口 |
| L3 | 预处理层 | geopandas/ezdxf/ChromaDB/VL Agent | CAD 转图、GIS 解析、RAG 语料构建、VL 空间分析、图集 RAG 索引 |
| L4 | 全局状态机 | Python dataclass (7分区) + **ContextVar** | Static/ETL/Calc/TplCtx/Draft/Measures/Flags |
| L5 | 处理层 | **DAG 调度器** × 2 集群 × **5 智能体** × **23 工具** | 编制集群（计算+规划+适配+撰稿+制图+渲染）+ 审计集群（审计 Agent） |
| L5.5 | **LLM 韧性层** | **LLMClient (超时+重试) + 消息窗口管理** | **保障 LLM 调用可靠性 + Agent 上下文不溢出** |
| L6 | 存储交付层 | 本地文件系统 + SQLite | 文件存储、历史记录、运行日志 |

### 2.1.2 处理层内部结构 (v8.1 DAG 模式)

处理层是系统核心，内含两个集群。**DAG 调度器自动识别步骤间依赖，最大化并行执行**：

**DAG 依赖图 (18 步)**：

```
1_load_config
    |
2_preprocess
    |
  +---------+---------+
  |         |         |
3_spatial 4_earthwork 5_erosion    <-- 并行组A (互不依赖)
  |         |         |
  +----+----+   +-----+
       |        |
     6_planner (依赖 3+5)
       |
     7_cost (依赖 6+4)
       |
     8_benefit
       |
     9_assemble
       |
   9.5_adapter (校验+回调修复)    <-- v8.1 新增
       |
  +----+----+----+
  |    |    |    |
10_writer 11_charts 12_drawings   <-- 并行组B (读写集合无交集)
  |    |    |    |
  +----+----+----+
       |
    13_render (依赖 10+11+12)
       |
    14_audit -> 15_retry -> 16_final -> 17_package
```

**并行组**：
- **组 A (Step 3/4/5)**：空间分析、土方计算、侵蚀预测可同时执行
- **Step 9.5 (adapter)**：数据适配器校验 + 回调修复，确保写入前数据完整
- **组 B (Step 10/11/12)**：Writer、Charts、Drawing 读写集合无交集，可同时执行（依赖 9.5_adapter）
- **Writer 内部**：chapter2-8 共 7 章并行生成，chapter1 串行（依赖前序章节 Draft）
- **Drawing 内部**：所有图（分区图/总布置图/详图/断面图）并行生成
- **审计重写**：多个失败章节可并行重写

**编制集群 (Compilation Cluster)**

```
Step 1-2:  输入加载 + 预处理 (串行)
Step 3-5:  空间分析 ∥ 土方计算 ∥ 侵蚀预测 (并行组A)
Step 6:    措施规划师 Agent (依赖 3+5)
Step 7:    造价估算 (依赖 6+4)
Step 8:    效益分析 (依赖 7)
Step 9:    状态装配器 (依赖 7+8)
Step 9.5:  数据适配器 — 校验必填标签 + 回调修复 + reassemble
Step 10:   撰稿智能体 — 7章并行 + 1章串行
Step 11:   数据图表生成
Step 12:   绘图智能体 — 全图并行 → fallback MeasureMapRenderer
           (10/11/12 并行组B)
Step 13:   docxtpl 渲染 + 循环表格 + 措施图后插入
```

**审计集群 (Audit Cluster)**

```
Step 14:   审计智能体（全文质量审查）
Step 15:   章节级重试 — 多章并行重写 (v8.1: 各线程 AgentContext 隔离)
Step 16:   最终渲染
Step 17:   打包输出
```

**降级策略**：`PIPELINE_PARALLEL=false` 一键回退线性模式，行为与 v5 完全一致。

## 2.2 状态管理架构

### 2.2.1 ContextVar 状态解耦

**问题**：v5 中 4 个工具模块通过 module-level 全局变量 `_state = None` + `set_state()` 注入状态。这导致：
- 不可能并行执行多个 Agent（全局变量互相覆盖）
- 工具与 Agent 强耦合，单元测试必须先 `set_state()`
- 线程不安全，并行场景下竞态条件

**方案**：`contextvars.ContextVar` + `AgentContext` 上下文管理器。

```python
# src/context.py
from contextvars import ContextVar

_ctx_state: ContextVar = ContextVar("agent_state", default=None)
_ctx_atlas_rag: ContextVar = ContextVar("atlas_rag", default=None)
_ctx_output_dir: ContextVar = ContextVar("output_dir", default=None)

# 工具函数内部:
def calc_lookup(key_path):
    _state = get_state_or_none()  # 读取当前线程/协程的状态
    ...

# Agent 调用方:
with AgentContext(state=state, atlas_rag=rag, output_dir=out):
    agent.run(prompt)  # 工具函数自动读取此处设置的上下文
```

### 2.2.2 上下文隔离保证

| 场景 | 隔离机制 |
|------|----------|
| ThreadPoolExecutor 并行章节 | 每个线程任务创建独立 `AgentContext`，ContextVar 天然线程隔离 |
| ThreadPoolExecutor 并行绘图 | 同上，每个绘图任务拥有独立上下文 |
| **ThreadPoolExecutor 并行重写 (v8.1)** | **`_rewrite_task()` 包装函数内创建 AgentContext，修复 v8.0 遗漏** |
| DAG 并行步骤 | 步骤函数在独立线程运行，读写 GlobalState 不同分区无竞态 |
| 串行回退 | AgentContext 退出时通过 token.reset 恢复上层上下文 |

## 2.3 智能体总览

系统包含 **5 个智能体 (Agent)** 和 **23 个工具 (Tool)**，全部基于 Qwen2.5-72B-Instruct-GPTQ-Int8，通过 vLLM 部署。

| 智能体 | 所属集群 | 角色 | 工具数 | 并行模式 | vLLM 实例 |
|--------|----------|------|--------|----------|-----------|
| 措施规划师 | 编制集群 | 根据分区特征+侵蚀数据+空间布局+标准库，决策新增措施 | 6 | 串行 | Text (GPU 0-1) |
| 撰稿智能体 | 编制集群 | 逐章生成报告文本 | 4 | 7 章并行 + 1 章串行 | Text (GPU 0-1) |
| **数据适配器** | **编制集群** | **校验 229 标签完整性 + 回调修复 + reassemble** | **6** | **串行** | **Text (GPU 0-1)** |
| 绘图智能体 | 编制集群 | LLM 编写 matplotlib 代码生成措施图 | 4 | 全图并行 | Text + VL |
| 审计智能体 | 审计集群 | 全文质量审查 | 3 | 串行 (重写可并行) | Text (GPU 0-1) |

## 2.4 技术选型

| 组件 | 技术选择 | 选择理由 |
|------|----------|----------|
| LLM 推理 | vLLM + Qwen2.5-72B-Instruct-GPTQ-Int8 | 72B 参数量水保专业表现优秀；GPTQ-Int8 量化 2 卡可跑；vLLM 连续批处理 |
| 视觉模型 | Qwen2.5-VL-72B-Instruct-GPTQ-Int8 | CAD 空间分析 + 图集索引 + 措施图 VL 验证 |
| 向量数据库 | ChromaDB (双库) | 范文 RAG (chromadb/) + 图集 RAG (atlas_db/)，轻量、Python 原生集成 |
| Embedding | BAAI/bge-m3 (v2) + MiniLM (v1 兼容) | 1024d dense + sparse，中文表现优秀 |
| 文档渲染 | docxtpl + python-docx | Phase1: Jinja2 变量替换; Phase2: 手动循环表格填充; Phase3: 措施图后插入 |
| 图表生成 | matplotlib | 数据图表 + Drawing Agent 措施图 |
| 状态管理 | contextvars.ContextVar | 线程/协程安全的上下文变量，替代全局变量 |
| 并行引擎 | concurrent.futures.ThreadPoolExecutor | 标准库，GIL 下 I/O 密集型任务 (LLM API 调用) 天然适合线程并行 |
| 调度引擎 | DAGScheduler (自研) | 基于 ThreadPoolExecutor + FIRST_COMPLETED 的轻量 DAG 执行器 |
| **LLM 客户端** | **LLMClient (OpenAI SDK)** | **封装 超时+重试+指数退避，统一 vLLM API 调用** |
| 前端框架 | Vue 3 + Vite + Element Plus | 轻量 SPA、Element Plus 丰富组件库 |
| 后端框架 | FastAPI + uvicorn (双端口) | 异步支持、SSE 推送、自动 API 文档 |
| 数据库 | SQLite (server.db) | MVP 阶段轻量存储 |

## 2.5 GPU 部署方案

**硬件**：AutoDL 4×A800-80G（或 4×RTX 6000 Ada 48G）

| vLLM 实例 | GPU 分配 | 模型 | 端口 | 用途 |
|-----------|----------|------|------|------|
| Text LLM | GPU 0-1 (TP=2) | Qwen2.5-72B-Instruct-GPTQ-Int8 | 8000 | 规划/撰稿/适配/审计/绘图 5 个 Agent 共用 |
| VL Model | GPU 2-3 (TP=2) | Qwen2.5-VL-72B-Instruct-GPTQ-Int8 | 8001 | CAD 空间分析 + 图集索引 + 措施图验证 |

**v8.1 并发说明**：
- Writer 并行 7 章时，vLLM 同时处理 4 个并发请求（`WRITER_WORKERS=4`）
- Drawing 并行全图时，vLLM 同时处理 3 个并发请求（`DRAWING_WORKERS=3`）
- vLLM 的连续批处理 (continuous batching) 天然支持并发请求，吞吐量不降反升
- **LLMClient 超时 120s + 重试 2 次**，防止 vLLM 负载高峰期单次推理超时导致流水线中断

---

# 3 数据规格

## 3.1 用户必填输入

### 3.1.1 项目概况表 facts_v2.json

（内容与 v5 一致，此处省略重复。详见 v5 PRD 第 3.1.1 节。）

### 3.1.2 已列措施清单 measures_v2.csv

（内容与 v5 一致，此处省略重复。详见 v5 PRD 第 3.1.2 节。）

## 3.2 系统内置数据

（soil_map.json / price_v2.csv / fee_rate_config.json / measure_library.json / measure_symbols.py / legal_refs.json / template.docx / ChromaDB / atlas 等内容与 v5 一致。详见 v5 PRD 第 3.2 节。）

## 3.3 全局状态机 GlobalState

整个流水线的数据总线。所有模块通过读写 GlobalState 通信，不直接传递数据。

| 分区 | 类型 | 内容 | 并行安全性 |
|------|------|------|------------|
| Static | StaticData | meta, soil_map, price_table, fee_rate, legal_refs, measure_library, measures_existing | 只读，天然安全 |
| ETL | ETLData | zones, rag_ready, site_desc, spatial_layout, gis_gdf, measure_layout | Step 2-3 写入后只读 |
| Calc | CalcData | earthwork, erosion_df, cost_summary, benefit | 各计算步骤写入不同子字段 |
| TplCtx | dict | 229 个模板标签 | Step 9 一次性写入后只读 |
| Draft | dict | chapters: {tag: text} | 各章写入不同 key，无竞态 |
| Measures | list | full_measures_list | Step 6 写入后只读 |
| Flags | dict | retry_count, failed_list, audit_score, audit_log, **adapter_result** | Step 14+ 单线程写入 |

**线程安全分析**：
- Writer 并行：各章写入 Draft 的 key 不同（`chapter2_xxx` vs `chapter3_xxx`），Python dict 单键赋值在 GIL 下原子操作
- Drawing 并行：各图写入不同 PNG 文件，不写 State
- DAG 并行：读写集合设计为无交集（见 DAG 依赖图）
- **审计重写并行 (v8.1 修复)**：各线程通过 `_rewrite_task()` 包装函数创建独立 AgentContext

---

# 4 计算引擎详细规格

（土方师 / 预测师 / 造价师 / 效益分析 / 状态装配器的规格与 v5 一致。详见 v5 PRD 第 4 节。）

---

# 5 智能体详细规格

## 5.1 措施规划师 Agent

（角色定义 / 输入 / 决策逻辑 / 6 个工具定义 / 输出格式与 v5 一致。）

**v8 变更**：
- 移除 `set_state()` / `set_atlas_rag()` 调用
- 使用 `AgentContext(state=state, atlas_rag=atlas_rag)` 包裹 agent.run()
- 工具函数 `spatial_context_tool()` / `atlas_reference_tool()` 内部通过 `get_state_or_none()` / `get_atlas_rag()` 读取上下文

## 5.2 撰稿智能体 Agent

### 5.2.1 角色定义

（System Prompt / 生成策略 / 4 个工具定义 / 输出格式 / 上下文窗口管理与 v5 一致。）

### 5.2.2 生成顺序与并行策略 (v8 新增)

**v5**：Ch2→Ch3→Ch4→Ch5→Ch6→Ch7→Ch8→Ch1 全部串行。

**v8**：两阶段执行。

| 阶段 | 章节 | 执行模式 | 并发数 | 原因 |
|------|------|----------|--------|------|
| Phase 1 | Ch2, Ch3, Ch4, Ch5, Ch6, Ch7, Ch8 | ThreadPoolExecutor 并行 | max_workers=4 | 7 章互相无依赖：各读 Static/Calc/TplCtx (只读)，各写 Draft[自己的 tags] (不同 key) |
| Phase 2 | Ch1 | 串行 | 1 | Ch1 (综合说明) 依赖前序章节 Draft (通过 `prev_chapter` 工具读取) |

**实现**：
```python
# Phase 1: 7章并行
with ThreadPoolExecutor(max_workers=WRITER_PARALLEL_WORKERS) as executor:
    futures = {
        executor.submit(_generate_chapter_task, state, ch, config, llm): ch
        for ch in PARALLEL_CHAPTERS  # ["chapter2"..."chapter8"]
    }
    for future in as_completed(futures):
        ch_id, texts, err = future.result()
        for tag, text in texts.items():
            state.Draft[tag] = text

# Phase 2: ch1 串行
with AgentContext(state=state):
    texts = generate_chapter(state, "chapter1", config, llm)
```

**错误隔离**：单章失败 → 写入占位文本 `[chapter_id 生成失败]`，其他章继续。

### 5.2.3 v8 状态访问变更

| 工具函数 | v5 | v8 |
|----------|----|----|
| `calc_lookup()` | 读取全局 `_state` | `_state = get_state_or_none()` |
| `self_checker()` | 读取全局 `_state` | 同上 |
| `prev_chapter()` | 读取全局 `_state` | 同上 |
| `rag_search()` | 无状态依赖 | 无变化 |

## 5.3 数据适配器智能体 Agent (v8.1 新增)

### 5.3.1 角色定义

数据适配器位于 Step 9 (assemble) 和 Step 10 (writer) 之间，校验 229 个模板标签的数据完整性。发现必填指标缺失时，主动回调 Planner 或 Calculator 补充，然后 reassemble。

**运行模式**:
- **LLM 模式**: ToolCallingAgent 分析缺失字段 → 调用回调工具 → 最多 2 轮修复循环
- **非 LLM 模式**: `_fallback_adapter()` 纯 Python 硬逻辑: 逐类检查 → 自动重跑缺失的 calculator → reassemble

### 5.3.2 校验规则

按 assembler.py 的标签类别定义必填字段:

| 类别 | 示例标签 | 校验规则 | 缺失时回调 |
|------|----------|----------|-----------|
| project_meta (7) | `project_name`, `total_investment` | non_empty / positive_number | 不可回调（用户输入） |
| earthwork (4) | `ew_dig`, `ew_surplus` | non_negative_number / number | `rerun_calculator("earthwork")` |
| erosion (6) | `ep_total_pred`, `ep_s1_new` | positive/non_negative_number | `rerun_calculator("erosion")` |
| measures_def (2) | `def_eng_yes` | non_empty | `callback_planner()` |
| measures_layout (1) | `lo_主体_eng_exist` | non_empty | `callback_planner()` |
| cost (6) | `c_grand_total`, `c1_total` | positive/non_negative_number | `rerun_calculator("cost")` |
| ch1_summary (1) | `total_swc_investment` | positive_number | 自动从 cost 派生 |
| benefit (18) | `t_治理度`, `ok_覆盖率` | non_empty / valid_status | `rerun_calculator("benefit")` |
| loop_tables (3) | `land_use_table`, `erosion_table` | non_empty_list / list | 依赖上游修复 |

### 5.3.3 回调依赖链

修复顺序自动推导:
```
Measures 为空 → callback_planner → rerun_calculator("cost")
                                  → rerun_calculator("benefit") → reassemble
Erosion 为空  → rerun_calculator("erosion")
              → rerun_calculator("benefit") → reassemble
Cost 为空     → (检查 Measures 是否存在)
              → rerun_calculator("cost") → reassemble
```

### 5.3.4 工具定义 (6 个)

| 工具 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `validate_completeness` | 遍历必填标签，返回各类别缺失状态 | 无 | `{categories: {cat: {status, missing_tags}}}` |
| `validate_cross_refs` | 交叉数值校验（土方/侵蚀/造价公式一致性） | 无 | `{checks: [{name, pass, expected, actual}]}` |
| `rerun_calculator` | 重新执行指定计算器 | `calculator_name: str` | `{success: bool, message: str}` |
| `callback_planner` | 重新执行 Planner 补充缺失措施 | 无 | `{success: bool, measures_count: int}` |
| `reassemble` | 重新执行状态装配器更新 TplCtx | 无 | `{success: bool, tag_count: int}` |
| `get_fix_suggestion` | 根据缺失类别推导修复动作链 | `missing_categories: list[str]` | `{actions: [{action, target, reason}]}` |

### 5.3.5 降级策略

`use_llm=False` 时使用 `_fallback_adapter()` 纯 Python 硬逻辑: 最多 2 轮校验→修复→reassemble 循环。

### 5.3.6 输出格式

```json
{
  "status": "pass | pass_with_warnings | fail",
  "total_tags": 229,
  "valid_tags": 220,
  "fixed_tags": 9,
  "remaining_issues": [],
  "callbacks_made": [
    {"action": "rerun_calculator", "target": "cost", "success": true}
  ]
}
```

### 5.3.7 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `ADAPTER_MAX_TURNS` | 8 | LLM 模式最大工具调用轮次 |
| `ADAPTER_MAX_CALLBACKS` | 2 | 最大修复循环次数 |

## 5.4 审计智能体 Agent

（角色定义 / 3 个工具定义 / 评分体系与 v5 一致。）

**v8 变更**：
- `run_auditor()` 使用 `AgentContext(state=state)` 包裹 agent.run() 和 fallback 解析
- `_fallback_audit()` 中调用的 `numeric_validator()` / `text_validator()` / `rag_comparator()` 自动从 ContextVar 读取状态
- 审计重试时多章并行重写（见 6.3 节）

**v8.1 变更**：
- 并行重写路径增加 `_rewrite_task()` 包装函数，确保每个重写线程拥有独立 AgentContext
- 串行重写路径增加 `with AgentContext(state=self.state)` 包裹

## 5.5 绘图智能体 Agent

### 5.5.1 并行绘图 (v8 新增)

**v5**：所有图串行生成（分区图 → 总布置图 → 详图×N → 断面图×N）。

**v8**：所有图并行生成。

| 维度 | v5 | v8 |
|------|----|----|
| 执行模式 | 串行逐图 | ThreadPoolExecutor 全图并行 |
| 并发数 | 1 | max_workers=3 (DRAWING_WORKERS) |
| 上下文管理 | `set_drawing_context()` 全局注入 | 每个线程任务创建 `AgentContext` |
| 文件冲突 | 无 | 无 (各图文件名不同) |

**实现**：
```python
def _draw_single_task(map_type, prompt, filename):
    with AgentContext(state=state, atlas_rag=atlas_rag, output_dir=out_dir):
        agent = ToolCallingAgent(...)
        agent.run(prompt)
        return tag, path, error

with ThreadPoolExecutor(max_workers=DRAWING_PARALLEL_WORKERS) as executor:
    futures = [executor.submit(_draw_single_task, ...) for t in tasks]
```

**错误隔离**：单图失败 → 跳过该图；产出 < 2 张 → 回退到 MeasureMapRenderer。

### 5.5.2 工具定义 / 安全沙箱 / Fallback

（4 个工具定义、代码执行安全、Fallback 机制与 v5 一致。）

---

# 6 并行执行与 DAG 调度

## 6.1 DAG 调度器

### 6.1.1 核心组件

**文件**: `src/dag_scheduler.py` (~155 行)

```python
@dataclass
class StepNode:
    name: str
    func: Callable
    depends_on: list[str]
    status: str = "pending"   # pending / running / done / failed / skipped
    error: Exception | None = None
    critical: bool = True

class DAGScheduler:
    def add_step(name, func, depends_on=[])
    def run(max_workers=4, on_progress=None) -> dict[str, str]
```

### 6.1.2 调度算法

```
while 有 pending 或 running 步骤:
    ready = [s for s if 所有依赖 "done" 且自身 "pending"]
    for s in 有依赖 "failed"/"skipped" 的 pending 步骤:
        s.status = "skipped"     # 失败传播
    submit ready to ThreadPoolExecutor
    wait(FIRST_COMPLETED)
    update status
```

**关键特性**：
- **自动并行**：依赖满足即提交，最大化并行度
- **失败传播**：上游步骤失败时自动 skip 所有下游
- **进度回调**：每个步骤状态变更时调用 `on_progress` 回调
- **线程安全**：内部使用 `threading.Lock` 保护状态更新

### 6.1.3 Pipeline DAG 定义 (18 步)

```python
dag.add_step("1_load_config",   self._load_config)
dag.add_step("2_preprocess",    self._preprocess,           ["1_load_config"])
dag.add_step("3_spatial",       self._spatial_analysis,     ["2_preprocess"])
dag.add_step("4_earthwork",     self._calc_earthwork,       ["2_preprocess"])
dag.add_step("5_erosion",       self._calc_erosion,         ["2_preprocess"])
dag.add_step("6_planner",       self._run_planner,          ["3_spatial", "5_erosion"])
dag.add_step("7_cost",          self._calc_cost,            ["6_planner", "4_earthwork"])
dag.add_step("8_benefit",       self._calc_benefit,         ["7_cost"])
dag.add_step("9_assemble",      self._assemble,             ["7_cost", "8_benefit"])
dag.add_step("9.5_adapter",     self._run_adapter,          ["9_assemble"])
dag.add_step("10_writer",       self._run_writer,           ["9.5_adapter"])
dag.add_step("11_charts",       self._generate_charts,      ["9.5_adapter"])
dag.add_step("12_drawings",     self._generate_measure_maps,["9.5_adapter"])
dag.add_step("13_render",       self._render_draft,         ["10_writer","11_charts","12_drawings"])
dag.add_step("14_audit",        self._run_auditor,          ["13_render"])
dag.add_step("15_retry",        self._retry_if_needed,      ["14_audit"])
dag.add_step("16_final",        self._final_render,         ["15_retry"])
dag.add_step("17_package",      self._package_output,       ["16_final"])
```

### 6.1.4 并行组读写集合分析

| 并行组 | 步骤 | 读 | 写 | 竞态风险 |
|--------|------|----|----|----------|
| A | 3_spatial | ETL.zones | ETL.spatial_layout | 无 (不同字段) |
| A | 4_earthwork | Static, ETL.zones | Calc.earthwork | 无 |
| A | 5_erosion | Static, ETL.zones | Calc.erosion_df | 无 |
| B | 10_writer | Static, Calc, TplCtx | Draft | 无 (不同字段) |
| B | 11_charts | Calc | PNG files | 无 (文件系统) |
| B | 12_drawings | Static, ETL, Measures | PNG files | 无 |

## 6.2 ContextVar 状态隔离

### 6.2.1 架构

**文件**: `src/context.py` (~105 行)

| 组件 | 用途 |
|------|------|
| `_ctx_state: ContextVar` | 当前线程的 GlobalState |
| `_ctx_atlas_rag: ContextVar` | 当前线程的 AtlasRAG 实例 |
| `_ctx_output_dir: ContextVar` | 当前线程的输出目录 |
| `get_state_or_none()` | 工具函数调用的统一入口 |
| `get_atlas_rag()` | 获取图集 RAG |
| `get_output_dir()` | 获取输出目录 |
| `AgentContext` | with 语句上下文管理器 |

### 6.2.2 工具模块改造

| 文件 | 移除 | 新增 |
|------|------|------|
| `src/tools/writer_tools.py` | `_state`, `set_state()` | `from src.context import get_state_or_none` |
| `src/tools/auditor_tools.py` | `_state`, `set_state()` | 同上 |
| `src/tools/spatial_tools.py` | `_state`, `_atlas_rag`, `set_state()`, `set_atlas_rag()` | `from src.context import get_state_or_none, get_atlas_rag` |
| `src/tools/drawing_tools.py` | `_state`, `_atlas_rag`, `_output_dir`, `set_drawing_context()` | `from src.context import get_state_or_none, get_atlas_rag, get_output_dir` |
| **`src/tools/adapter_tools.py` (新)** | — | **`from src.context import get_state_or_none`** |

### 6.2.3 向后兼容

`src/context.py` 保留 `set_state()` / `set_atlas_rag()` / `set_output_dir()` 函数作为 deprecated wrappers，内部调用 `_ctx_xxx.set()`，发出 `DeprecationWarning`。

## 6.3 并行重写

审计回弹时多个失败章节可并行重写：

```python
# v8.1: _rewrite_task 包装函数确保 AgentContext 隔离
def _rewrite_task(state, ch_id, feedback, llm):
    with AgentContext(state=state):
        return rewrite_chapter(state, ch_id, feedback, llm)

if len(retry_list) > 1:
    with ThreadPoolExecutor(max_workers=3) as executor:
        for ch_id, feedback in retry_list:
            executor.submit(_rewrite_task, state, ch_id, feedback, llm)
```

## 6.4 配置与降级

### 6.4.1 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WRITER_WORKERS` | 4 | Writer Agent 并行章节数 (1=串行回退) |
| `DRAWING_WORKERS` | 3 | Drawing Agent 并行图数 (1=串行回退) |
| `PIPELINE_PARALLEL` | true | DAG 模式开关 (false=线性模式) |

### 6.4.2 降级策略

| 风险 | 降级措施 |
|------|----------|
| vLLM 并发 OOM | `WRITER_WORKERS=1` 回退串行 |
| matplotlib 线程安全 | 已用 Agg 后端 + `plt.close("all")` |
| ContextVar 继承问题 | 每个任务函数自建 `AgentContext`，不依赖继承 |
| DAG 调度异常 | `PIPELINE_PARALLEL=false` 一键回退线性模式 |
| Dict 写入竞态 | 各章 tag 不同，无实际竞态；Pipeline 内 `_chart_paths` 使用 `threading.Lock` 保护 |

---

# 7 LLM 韧性与上下文管理 (v8.1 新增)

## 7.1 LLMClient 韧性层

### 7.1.1 设计目标

本地 vLLM 在高并发场景下（Writer 4 线程 + Drawing 3 线程同时请求）可能出现推理超时或临时不可用。LLMClient 韧性层确保单次失败不中断整个流水线。

### 7.1.2 架构

**文件**: `src/agents/base.py` — `LLMClient` 类

```python
class LLMClient:
    def __init__(self, base_url, model, timeout=120, max_retries=2):
        self.client = OpenAI(base_url=base_url, api_key="not-needed", timeout=timeout)
        self.max_retries = max_retries

    def chat(self, messages, tools=None, max_tokens=4096, temperature=0.3):
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
                return response.choices[0].message
            except Exception as e:
                if attempt < self.max_retries:
                    wait = 2 ** attempt  # 指数退避: 1s, 2s
                    time.sleep(wait)
                else:
                    raise
```

### 7.1.3 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `LLM_TIMEOUT` | 120 | 单次 LLM 调用超时（秒），httpx 级别 |
| `LLM_MAX_RETRIES` | 2 | 失败后重试次数，指数退避 (1s, 2s) |

### 7.1.4 行为矩阵

| 场景 | 行为 |
|------|------|
| 正常响应 | 直接返回，无额外开销 |
| 首次超时 | 等待 1s → 重试 |
| 二次超时 | 等待 2s → 重试 |
| 三次失败 | 抛出异常，由上层 Agent/Pipeline 处理 |
| vLLM 进程崩溃 | 超时后重试，若仍不可用则抛出异常 |

## 7.2 消息窗口管理

### 7.2.1 设计目标

Agent 的 Tool-calling 循环中，每轮对话累积 assistant + tool_calls + tool_result 消息。当工具返回大量数据（如完整的措施列表 JSON）时，上下文迅速膨胀超过模型窗口限制 (32K-128K tokens)。

### 7.2.2 三层策略

| 层级 | 方式 | 延迟 | 信息保留度 | 启用条件 |
|------|------|------|-----------|---------|
| **L1: 结构化摘要** | 纯 Python 提取工具名、数值、错误 | 0ms | 中 | 默认开启 |
| **L2: LLM 摘要** | 一次轻量 LLM 调用 (max_tokens=256) | ~2-5s | 高 | `CONTEXT_SUMMARIZE_LLM=true` |
| **L3: 硬截断兜底** | 字符上限 48K | 0ms | 兜底 | 始终生效 |

### 7.2.3 结构化摘要 (L1)

**文件**: `src/agents/base.py` — `_extract_structured_summary()`

从被丢弃的消息中**零 LLM 开销**提取：

| 提取项 | 来源 | 示例输出 |
|--------|------|----------|
| 工具调用统计 | assistant.tool_calls | `已调用工具: calc_lookup×3, rag_search×2` |
| 关键数值 | tool result JSON (number 类型字段) | `关键数值: c_grand_total=1234567, ew_dig=5000` |
| 错误信息 | tool result `{"error": ...}` | `出现错误(1个): State 未初始化` |
| 中间结论 | assistant.content (截取前 100 字) | `中间结论: 土方平衡计算完成，净挖方量...` |

**输出格式**:
```
[历史摘要 (15条消息)] 已调用工具: calc_lookup×3, rag_search×2; 关键数值: c_grand_total=1234567; 中间结论: 造价汇总已完成...
```

### 7.2.4 可选 LLM 摘要 (L2)

**文件**: `src/agents/base.py` — `_llm_summarize_dropped()`

当 `CONTEXT_SUMMARIZE_LLM=true` 时：
1. 收集被丢弃消息的文本（截断到 4000 字符以控制成本）
2. 用一次轻量 LLM 调用（system: "精简摘要助手"，max_tokens=256，temperature=0.1）生成自然语言摘要
3. 失败时自动 fallback 到 L1 结构化摘要

**成本控制**:
- 输入截断 4000 字符 ≈ 2K-4K tokens
- 输出限制 256 tokens
- 单次摘要调用成本 < 主 Agent 单轮调用的 5%

### 7.2.5 硬截断机制 (L3)

**文件**: `src/agents/base.py` — `_trim_messages()`

```
触发条件: _estimate_message_chars(messages) > 48000
策略:
  1. 始终保留 messages[0] (system prompt) + messages[1] (user message)
  2. 从最新消息往前保留，直到 head + tail ≤ 48K - 800 (摘要预算)
  3. 对丢弃的中间消息生成 L2/L1 摘要
  4. 拼接: head + [摘要消息] + tail
```

### 7.2.6 工具结果截断

**文件**: `src/agents/base.py` — `ToolCallingAgent.TOOL_RESULT_MAX_CHARS = 8000`

单个工具返回值超过 8000 字符时，截断并追加 `... [截断: 原始 N 字符]`。此机制在消息窗口管理之前生效，防止单个工具结果直接撑爆上下文。

### 7.2.7 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `CONTEXT_SUMMARIZE_LLM` | false | 是否启用 LLM 摘要压缩 |
| `CONTEXT_SUMMARY_MAX_TOKENS` | 256 | LLM 摘要最大输出 token |

---

# 8 前端详细规格

（技术栈 / 双端口架构 / 用户端功能 / 管理端功能与 v5 一致。详见 v5 PRD 第 6 节。）

**v8 变更**：
- 进度看板显示 DAG 拓扑视图（并行步骤同层显示）
- SSE 事件增加 `parallel_group` 字段标识并行步骤组

---

# 9 后端 API 详细规格

（架构 / API 模块 / 核心端点 / 数据库 Schema 与 v5 一致。详见 v5 PRD 第 7 节。）

---

# 10 报告模板与渲染规格

（三阶段渲染引擎 / 标签语法 / 循环表格 / 措施图后插入 / 图表生成 / 完整性检查与 v5 一致。详见 v5 PRD 第 8 节。）

**v8 变更**：
- `_generate_charts()` 和 `_generate_measure_maps()` 并行执行时，通过 `threading.Lock` 保护共享的 `_chart_paths` 字典

---

# 11 部署规格

（AutoDL 一键部署 / 手动部署 / Docker 部署 / CLI 模式与 v5 一致。详见 v5 PRD 第 9 节。）

### 11.1 v8.1 完整环境变量

| 变量 | 默认值 | 说明 | 引入版本 |
|------|--------|------|----------|
| `VLLM_URL` | 自动检测 | LLM API 地址 | v5 |
| `MODEL_NAME` | 自动检测 | 模型名称 | v5 |
| `MAX_TOKENS` | 4096 | 最大输出 token | v5 |
| `TEMPERATURE` | 0.3 | 生成温度 | v5 |
| `VL_URL` | 自动检测 | VL 模型 API 地址 | v5 |
| `VL_MODEL_NAME` | 自动检测 | VL 模型名称 | v5 |
| `WRITER_WORKERS` | 4 | Writer Agent 并行线程数 | v8.0 |
| `DRAWING_WORKERS` | 3 | Drawing Agent 并行线程数 | v8.0 |
| `PIPELINE_PARALLEL` | true | DAG 并行调度开关 | v8.0 |
| **`LLM_TIMEOUT`** | **120** | **单次 LLM 调用超时(秒)** | **v8.1** |
| **`LLM_MAX_RETRIES`** | **2** | **LLM 调用失败重试次数** | **v8.1** |
| **`ADAPTER_MAX_TURNS`** | **8** | **适配器 Agent 最大工具调用轮次** | **v8.1** |
| **`ADAPTER_MAX_CALLBACKS`** | **2** | **适配器最大修复循环次数** | **v8.1** |
| **`CONTEXT_SUMMARIZE_LLM`** | **false** | **是否启用 LLM 摘要压缩** | **v8.1** |
| **`CONTEXT_SUMMARY_MAX_TOKENS`** | **256** | **LLM 摘要最大输出 token** | **v8.1** |

**性能调优建议**：
- 4×A800 (72B): `WRITER_WORKERS=4`, `DRAWING_WORKERS=3`, `LLM_TIMEOUT=120`
- 2×GPU (7B 开发): `WRITER_WORKERS=2`, `DRAWING_WORKERS=2`, `LLM_TIMEOUT=60`
- OOM 时: `WRITER_WORKERS=1`, `DRAWING_WORKERS=1` (回退串行)
- 上下文溢出频繁时: `CONTEXT_SUMMARIZE_LLM=true` (启用 LLM 摘要)

---

# 12 非功能性需求

## 12.1 性能

| 指标 | v5 要求 | v8 要求 | **v8.1 备注** |
|------|---------|---------|---------------|
| 端到端生成时间 | ≤15 分钟 | ≤8 分钟 | 重试可能增加 1-5s |
| Writer 章节耗时 | ~8 分钟 (8章串行) | ~3 分钟 (7+1) | 无变化 |
| Drawing 耗时 | ~5 分钟 (逐图串行) | ~2 分钟 (全图并行) | 无变化 |
| API 响应时间 | ≤500ms | ≤500ms | 无变化 |
| SSE 延迟 | ≤2 秒 | ≤2 秒 | 无变化 |
| docx 渲染时间 | ≤30 秒 | ≤30 秒 | 无变化 |
| **LLM 单次调用上限** | **无限制** | **无限制** | **120s 超时 + 2次重试** |
| **消息窗口裁剪延迟** | **—** | **—** | **L1: 0ms; L2: 2-5s** |

## 12.2 可靠性

- **章节级重试**：每章最多重试 3 次，仅重写失败章节
- **Drawing Agent fallback**：LLM 绘图失败时回退到确定性 MeasureMapRenderer
- **DAG 失败传播**：上游步骤失败自动 skip 所有下游，不会阻塞
- **线性模式降级**：`PIPELINE_PARALLEL=false` 一键回退完全串行
- **审计日志持久化**：所有生成过程记录写入 SQLite
- **LLM 调用韧性 (v8.1)**：超时 + 重试 + 指数退避，覆盖全部 5 个 Agent
- **数据适配校验 (v8.1)**：Step 9.5 在写稿前检测并修复缺失数据
- **上下文窗口保护 (v8.1)**：工具结果截断 (8K) + 消息窗口裁剪 (48K) + 结构化摘要

## 12.3 安全性

（代码沙箱 / 文件隔离 / 输入校验 / CORS 与 v5 一致。）

## 12.4 可观测性

- **日志**：Python logging 模块 + DAG 调度器步骤级日志 `[DAG] 启动/完成/失败/跳过: step_name`
- **LLM 调用日志 (v8.1)**：`LLM 调用失败 (第N次), Xs 后重试: error`
- **消息裁剪日志 (v8.1)**：`消息窗口裁剪: 20 → 8 条, 52000 → 35000 字符`
- **适配器日志 (v8.1)**：`适配结果: pass, 修复 3 个标签`
- **进度推送**：DAG 模式下每个步骤状态变更都推送 SSE 事件
- **审计报告**：逐章评分 + 问题清单 + 修改建议

---

# 13 已知架构债务 (v8.1 记录)

以下问题已识别但尚未修复，按优先级排列：

## 13.1 P1-1: GlobalState 无序列化/快照机制

- **位置**: `src/state.py:47-72`
- **现状**: GlobalState 是纯 dataclass + 嵌套 dict，没有 `serialize()` / `deserialize()` 方法
- **影响**: Pipeline 中间步骤崩溃后必须从头重跑，无断点恢复能力
- **建议**: 添加基于 JSON 的序列化方法 + 每步完成后自动 checkpoint

## 13.2 P1-2: DAG 并行步骤 GlobalState 竞态条件

- **位置**: `src/dag_scheduler.py:169`, `src/context.py`
- **现状**: DAGScheduler 自身有锁保护步骤状态，但 `step.func()` 执行时无锁保护 GlobalState
- **当前缓解**: 并行组的读写集合设计为不相交（见 6.1.4），ContextVar 隔离引用
- **残余风险**: 若未来新增步骤打破读写不相交假设，会引入竞态
- **建议**: 为 GlobalState 各分区添加 `threading.RLock`，或在 DAGScheduler 中声明步骤的读写集合并自动校验

## 13.3 P1-3: 工具错误返回无统一 Schema

- **位置**: `src/tools/` 下全部 6 个工具文件
- **现状**: 4 种不同的错误格式: `{"error": ...}`, `{"success": false, "error": ...}`, `{"pass": false, "errors": [...]}`, `{"errors": [], "warnings": [...]}`
- **影响**: LLM 难以准确识别错误类型，增加 Agent 推理负担
- **建议**: 定义 `ToolResult` 基础类型: `{"success": bool, "data": Any, "error": str | None, "error_type": str | None}`

## 13.4 P1-4: Pipeline 步骤失败策略不明确

- **位置**: `src/pipeline.py` (线性 `_step()` 方法 / DAG `_skip_downstream()`)
- **现状**:
  - 线性模式: 任何步骤失败都 `raise`，直接中止整个管道
  - DAG 模式: 失败步骤的下游自动 skip，但无"关键/非关键"步骤分类
- **影响**: 图表生成失败（非关键）和土方计算失败（关键）得到相同处理
- **建议**: 将步骤分为 critical (失败中止) 和 non-critical (失败降级) 两类; 添加降级处理函数

---

# 14 实施计划

## 14.1 v8.0 已完成改造

| 文件 | 改造内容 | 改动量 |
|------|----------|--------|
| `src/context.py` (新建) | ContextVar + AgentContext | ~105 行 |
| `src/dag_scheduler.py` (新建) | DAG 调度器 | ~155 行 |
| `src/tools/writer_tools.py` | 状态解耦 | ~10 行 |
| `src/tools/auditor_tools.py` | 状态解耦 | ~10 行 |
| `src/tools/spatial_tools.py` | 状态解耦 | ~10 行 |
| `src/tools/drawing_tools.py` | 状态解耦 | ~10 行 |
| `src/agents/writer.py` | 状态解耦 + 7章并行 | ~60 行 |
| `src/agents/auditor.py` | 状态解耦 | ~10 行 |
| `src/agents/planner.py` | 状态解耦 | ~15 行 |
| `src/agents/drawing.py` | 状态解耦 + 全图并行 | ~70 行 |
| `src/pipeline.py` | 状态解耦 + DAG + 并行重写 | ~90 行 |
| `src/settings.py` | 3 个并行配置项 | ~5 行 |

## 14.2 v8.1 已完成改造

| 文件 | 改造内容 | 改动量 |
|------|----------|--------|
| **`src/tools/adapter_tools.py`** (新建) | REQUIRED_TAGS Schema + 6 个适配器工具 | ~250 行 |
| **`src/agents/adapter.py`** (新建) | run_adapter + _fallback_adapter + _parse_adapter_result | ~180 行 |
| `src/agents/base.py` | LLMClient 超时+重试 + _extract_structured_summary + _llm_summarize_dropped + _trim_messages 增强 + 工具结果截断 | ~130 行 |
| `src/pipeline.py` | _run_adapter + 线性/DAG 插入 9.5 + _rewrite_task AgentContext | ~35 行 |
| `src/settings.py` | 6 个新配置项 (LLM_TIMEOUT/LLM_MAX_RETRIES/ADAPTER_*/CONTEXT_*) | ~8 行 |

**v8.0 + v8.1 总计: 4 个新文件 + 11 个修改文件，约 1150 行变更**

## 14.3 验证方式

| 阶段 | 验证方法 | 预期结果 |
|------|----------|----------|
| 状态解耦 | 运行现有 tests/ 全部通过 | 接口不变，行为一致 |
| 并行执行 | `WRITER_WORKERS=1` vs `WRITER_WORKERS=4` 对比耗时 | 4 线程耗时约为 1 线程的 40% |
| DAG 调度 | `PIPELINE_PARALLEL=false` vs `true` 对比 | 输出 report.docx 内容一致，DAG 模式更快 |
| **LLM 韧性** | **模拟 vLLM 延迟 > 120s** | **自动重试 + 最终成功或明确报错** |
| **适配器** | **删除部分 Calc 数据后运行** | **适配器检测并回调修复** |
| **消息裁剪** | **构造 200 条消息的 Agent 会话** | **自动裁剪 + 摘要保留关键信息** |
| 端到端 | `python run_local.py` 完整运行 | output/ 下 report.docx + audit.json 正常 |

---

## 附录 A：拓扑图

完整架构拓扑图见 `topology_v8.1.mermaid`（Mermaid 源码）。

## 附录 B：术语表

| 缩写 | 全称 | 说明 |
|------|------|------|
| ContextVar | Context Variable | Python 3.7+ 线程/协程安全的上下文变量 |
| DAG | Directed Acyclic Graph | 有向无环图，用于表示步骤间依赖关系 |
| GIL | Global Interpreter Lock | Python 全局解释器锁 |
| RUSLE | Revised Universal Soil Loss Equation | 修正通用土壤流失方程 |
| RAG | Retrieval-Augmented Generation | 检索增强生成 |
| TplCtx | Template Context | 模板渲染上下文（229 个标签的字典） |
| VL | Vision-Language | 视觉语言模型 |
| GPTQ | GPT Quantization | 后训练量化方法 |
| vLLM | Virtual LLM | 高性能 LLM 推理框架 |
| SSE | Server-Sent Events | 服务端推送事件 |
| **LLMClient** | **LLM API Client** | **封装超时+重试的 OpenAI 兼容客户端** |

## 附录 C：关联文件

| 文件 | 说明 |
|------|------|
| `topology_v8.1.mermaid` | V8.1 架构拓扑图 |
| `src/context.py` | V8 新增: ContextVar 状态管理 |
| `src/dag_scheduler.py` | V8 新增: DAG 调度器 |
| `src/agents/base.py` | V8.1 改造: LLMClient 韧性层 + 消息窗口管理 + 结构化摘要 |
| `src/agents/adapter.py` | V8.1 新增: 数据适配器智能体 |
| `src/tools/adapter_tools.py` | V8.1 新增: 适配器 6 工具 + 必填标签 Schema |
| `src/pipeline.py` | V8.1 改造: DAG 模式 + 线性模式双轨 + 9.5 适配器 + AgentContext 修复 |
| `src/agents/writer.py` | V8 改造: 7 章并行 + 1 章串行 |
| `src/agents/drawing.py` | V8 改造: 全图并行 |
| `src/settings.py` | V8.1 改造: 6 个新配置项 |
| `autodl_start.py` | AutoDL 一键启动脚本 |
| `config/facts_v2.json` | 项目概况表 |
| `config/measures_v2.csv` | 已列措施清单 |
| `templates/template.docx` | 报告模板（229 标签位） |
