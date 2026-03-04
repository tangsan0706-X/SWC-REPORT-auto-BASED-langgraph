"""撰稿智能体 Agent — 逐章生成报告文本。

生成顺序: Ch2→3→4→5→6→7→8→Ch1
每章调用 generate_chapter():
  - 裁剪该章相关 State 子集（控制 token）
  - 获取 RAG context
  - 获取 prev_summary
  - 调用 LLM 生成
  - 自查数字引用
输出: 章节文本写入 State.Draft
"""

from __future__ import annotations

import json
import logging
import re

from src.agents.base import ToolCallingAgent, LLMClient
from src.context import AgentContext
from src.tools.writer_tools import WRITER_TOOLS
from src.state import GlobalState

logger = logging.getLogger(__name__)

# ── LLM 输出清洗 ─────────────────────────────────────────────

# 需要整行删除的 LLM 元文本模式（匹配行首）
_META_LINE_PATTERNS = [
    re.compile(r"^请允许我.*", re.MULTILINE),
    re.compile(r"^让我.*(?:编写|撰写|开始|根据|查询|使用).*", re.MULTILINE),
    re.compile(r"^我(?:将|来|会|需要).*(?:编写|撰写|开始|查询).*", re.MULTILINE),
    re.compile(r"^(?:由于|鉴于)\s*(?:RAG|语料|范文|数据|信息).*", re.MULTILINE),
    re.compile(r"^在当前情况下.*", re.MULTILINE),
    re.compile(r"^以上内容(?:基于|为|是).*(?:编写|生成|示例).*", re.MULTILINE),
    re.compile(r"^请(?:注意|使用|根据).*(?:实际|self_checker|调整|完善).*", re.MULTILINE),
    re.compile(r"^(?:注[：:]|备注[：:]).*(?:示例|占位|调整|生成).*", re.MULTILINE),
    re.compile(r"^以下(?:是|为).*(?:章节|内容|文本).*[：:]?\s*$", re.MULTILINE),
    re.compile(r"^(?:好的|当然|没问题).*(?:编写|撰写|开始).*", re.MULTILINE),
    re.compile(r"^我们将基于.*", re.MULTILINE),
    re.compile(r"^(?:上述|以上).*(?:数据|描述).*(?:示例|需依据|请根据).*", re.MULTILINE),
    re.compile(r"^请根据实际.*(?:调整|完善|修改).*", re.MULTILINE),
    re.compile(r"^以上信息.*(?:工具|获取|确认|查询).*", re.MULTILINE),
    re.compile(r"^(?:通过|经过).*(?:工具|查询|获取).*(?:确认|无误|验证).*", re.MULTILINE),
    re.compile(r"^(?:现在|接下来|下面).*(?:使用|调用|通过)\s*(?:calc_lookup|rag_search|self_checker|prev_chapter).*", re.MULTILINE),
]

# 内联工具引用清洗（括号内提及工具名）
_INLINE_TOOL_RE = re.compile(r"[（(](?:具体|详细)?(?:数值|数据|信息)?(?:由|通过|使用)\s*(?:calc_lookup|rag_search|self_checker|prev_chapter)\s*(?:工具)?(?:获取|查询|确认|计算)[）)]")
# 裸露的工具调用文本，如 calc_lookup('xxx') 或 calc_lookup("xxx")
_RAW_TOOL_CALL_RE = re.compile(r"(?:calc_lookup|rag_search|self_checker|prev_chapter)\s*\(['\"][^'\"]*['\"]\)")

# 需要删除的 Markdown 格式标记
_MD_HEADER_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)
# 匹配残留的 tag 名称行，如 "chapter1_brief" 单独成行
_TAG_LINE_RE = re.compile(r"^chapter\d+_\w+\s*$", re.MULTILINE)


def _sanitize_text(text: str) -> str:
    """清洗 LLM 输出：移除元文本、Markdown 标记、残留标签行。"""
    if not text:
        return text

    # 1. 移除 LLM 元文本行
    for pat in _META_LINE_PATTERNS:
        text = pat.sub("", text)

    # 2. 移除 Markdown 标题行（### xxx）
    text = _MD_HEADER_RE.sub("", text)

    # 3. 移除残留 tag 名称行
    text = _TAG_LINE_RE.sub("", text)

    # 4. 移除内联工具引用（括号内提及工具名）
    text = _INLINE_TOOL_RE.sub("", text)
    # 4b. 移除裸露的工具调用文本 calc_lookup('xxx')
    text = _RAW_TOOL_CALL_RE.sub("", text)

    # 5. 移除 Markdown 粗体/斜体标记（保留内部文字）
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)

    # 6. 移除 ``` 代码块标记（LLM 有时包裹输出）
    text = re.sub(r"^```\w*\s*$", "", text, flags=re.MULTILINE)

    # 7. 压缩连续空行为最多2个
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()

WRITER_SYSTEM_PROMPT = """你是一位专业的水土保持方案报告书撰稿工程师。你的任务是按照《生产建设项目水土保持方案编制技术规范》(GB/T 51240-2018) 编写报告各章节。

## 写作要求
1. 使用正式的技术文本风格，避免口语化
2. 数字引用必须精确，使用 calc_lookup 工具获取计算结果
3. 使用 rag_search 工具检索范文参考
4. 每章完成后用 self_checker 工具检查数字一致性
5. 使用 prev_chapter 工具获取前序章节上下文

## 输出格式（严格遵守）
- 使用 ===TAG_NAME=== 作为每个子段的分隔标记
- 标记之间直接写正文内容，不要添加任何章节标题或 Markdown 标记（模板已有标题）
- 段落之间空一行

## 禁止事项（违反将导致输出无效）
- 禁止输出任何自我描述，如"请允许我…"、"让我来…"、"我将…"
- 禁止输出任何元说明，如"以下是…内容"、"以上内容基于…"
- 禁止输出 Markdown 标题（#、##、###）
- 禁止输出免责声明、注意事项、备注说明
- 禁止使用 ``` 代码块包裹输出
- 禁止输出 Markdown 粗体(**)或斜体(*)标记
- 禁止输出任何关于工具调用的说明（如"以上信息通过xx工具获取"）
- 直接输出纯正文，不要有任何前言和后语
"""

# 各章节的写作指导和所需 State 数据
CHAPTER_CONFIGS = {
    "chapter2": {
        "name": "项目概况",
        "tags": ["chapter2_composition", "chapter2_construction_org",
                 "chapter2_relocation", "chapter2_natural"],
        "guidance": """请编写第2章 项目概况，包含以下子段:
1. chapter2_composition: 项目组成描述（建筑面积、主要建筑物、配套设施）
2. chapter2_construction_org: 施工组织描述（施工时序、交通组织）
3. chapter2_relocation: 拆迁安置描述（如无可写"本项目不涉及拆迁安置"）
4. chapter2_natural: 自然概况（气候、土壤、植被、水文）

请用 calc_lookup 查询项目基本信息。""",
    },
    "chapter3": {
        "name": "水土保持评价",
        "tags": ["chapter3_site_eval", "chapter3_layout_eval",
                 "chapter3_measures_definition"],
        "guidance": """请编写第3章 水土保持评价，包含:
1. chapter3_site_eval: 项目选址评价（地形、用地条件）
2. chapter3_layout_eval: 总平面布置水土保持评价
3. chapter3_measures_definition: 主体工程中具有水土保持功能的措施界定

请用 calc_lookup 查询分区面积和已有措施信息。""",
    },
    "chapter4": {
        "name": "水土流失分析与预测",
        "tags": ["chapter4_status", "chapter4_factors", "chapter4_prediction_text",
                 "chapter4_hazard", "chapter4_guidance"],
        "guidance": """请编写第4章 水土流失分析与预测，包含:
1. chapter4_status: 扰动土地现状分析
2. chapter4_factors: 预测因子说明（侵蚀模数来源、面积、时段）
3. chapter4_prediction_text: 预测计算过程及结果文字描述
4. chapter4_hazard: 水土流失危害分析
5. chapter4_guidance: 防治指导意见

请用 calc_lookup 查询侵蚀预测数据。关键数据:
- erosion_df.total_pred: 总预测流失量
- erosion_df.total_new: 新增流失量
- erosion_df.total_bg: 背景流失量""",
    },
    "chapter5": {
        "name": "水土保持措施",
        "tags": ["chapter5_zone_division", "chapter5_layout",
                 "chapter5_measures_detail", "chapter5_construction_req"],
        "guidance": """请编写第5章 水土保持措施，包含:
1. chapter5_zone_division: 防治分区划分说明
2. chapter5_layout: 措施总体布局
3. chapter5_measures_detail: 各分区措施详细设计描述
4. chapter5_construction_req: 施工要求

请用 calc_lookup 查询分区和措施信息。""",
    },
    "chapter6": {
        "name": "水土保持监测",
        "tags": ["chapter6_content_method", "chapter6_monitoring_points",
                 "chapter6_implementation"],
        "guidance": """请编写第6章 水土保持监测，包含:
1. chapter6_content_method: 监测内容与方法
2. chapter6_monitoring_points: 监测点位布设
3. chapter6_implementation: 监测实施方案""",
    },
    "chapter7": {
        "name": "投资估算与效益分析",
        "tags": ["chapter7_principles", "chapter7_basis",
                 "chapter7_method", "chapter7_benefit"],
        "guidance": """请编写第7章 投资估算与效益分析，包含:
1. chapter7_principles: 编制原则
2. chapter7_basis: 编制依据
3. chapter7_method: 编制方法（六层费率叠加说明）
4. chapter7_benefit: 效益分析文字（六项指标达标分析）

请用 calc_lookup 查询造价和效益数据。关键数据:
- cost_summary.c_grand_total: 水保总投资
- benefit.indicators: 六项指标""",
    },
    "chapter8": {
        "name": "实施保障措施",
        "tags": ["chapter8_1_组织管理", "chapter8_2_后续设计", "chapter8_3_水土保持监测",
                 "chapter8_4_水土保持监理", "chapter8_5_水土保持施工", "chapter8_6_水土保持设施验收"],
        "guidance": """请编写第8章 实施保障措施，包含6个子段:
1. chapter8_1_组织管理: 组织管理保障措施
2. chapter8_2_后续设计: 后续设计工作要求
3. chapter8_3_水土保持监测: 监测保障要求
4. chapter8_4_水土保持监理: 监理保障要求
5. chapter8_5_水土保持施工: 施工管理要求
6. chapter8_6_水土保持设施验收: 验收保障要求""",
    },
    "chapter1": {
        "name": "综合说明",
        "tags": ["chapter1_brief", "chapter1_legal_basis", "chapter1_evaluation",
                 "chapter1_prediction_summary", "chapter1_measures_summary",
                 "chapter1_monitoring_summary", "chapter1_conclusion"],
        "guidance": """请编写第1章 综合说明（最后写，因为需要引用前面章节内容），包含:
1. chapter1_brief: 项目概况简述
2. chapter1_legal_basis: 编制依据（法律法规清单）
3. chapter1_evaluation: 水保评价概述
4. chapter1_prediction_summary: 水土流失预测结论概述
5. chapter1_measures_summary: 防治措施概述
6. chapter1_monitoring_summary: 监测概述
7. chapter1_conclusion: 综合结论

请用 calc_lookup 查询总投资、流失量等关键数据。用 prev_chapter 获取前面章节摘要。""",
    },
}

# 生成顺序
CHAPTER_ORDER = ["chapter2", "chapter3", "chapter4", "chapter5",
                 "chapter6", "chapter7", "chapter8", "chapter1"]

# chapter2-8 互相无依赖，可并行; chapter1 依赖前序章节 Draft，必须串行
PARALLEL_CHAPTERS = ["chapter2", "chapter3", "chapter4", "chapter5",
                     "chapter6", "chapter7", "chapter8"]
SERIAL_CHAPTERS = ["chapter1"]


def _generate_chapter_task(state, chapter_id, config, llm):
    """线程安全的单章生成任务。"""
    with AgentContext(state=state):
        try:
            chapter_texts = generate_chapter(state, chapter_id, config, llm)
            return chapter_id, chapter_texts, None
        except Exception as e:
            logger.error(f"  生成 {chapter_id} 失败: {e}")
            placeholder = {tag: f"[{chapter_id} 生成失败: {str(e)}]" for tag in config["tags"]}
            return chapter_id, placeholder, e


def run_writer(state: GlobalState, llm: LLMClient | None = None,
               max_workers: int | None = None) -> dict[str, str]:
    """运行撰稿智能体。chapter2-8 并行，chapter1 串行。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from src.settings import WRITER_PARALLEL_WORKERS

    if max_workers is None:
        max_workers = WRITER_PARALLEL_WORKERS

    results = {}

    # Phase 1: chapter2-8 并行
    if max_workers > 1:
        logger.info(f"撰稿: 并行模式 (workers={max_workers}), "
                    f"{len(PARALLEL_CHAPTERS)} 章并行")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _generate_chapter_task, state, ch, CHAPTER_CONFIGS[ch], llm,
                ): ch
                for ch in PARALLEL_CHAPTERS
            }
            for future in as_completed(futures):
                ch_id, texts, err = future.result()
                config = CHAPTER_CONFIGS[ch_id]
                for tag, text in texts.items():
                    state.Draft[tag] = text
                    results[tag] = text
                if err is None:
                    logger.info(f"  完成: {ch_id} ({len(texts)} 个子段)")
    else:
        # 串行回退 (WRITER_WORKERS=1)
        with AgentContext(state=state):
            for chapter_id in PARALLEL_CHAPTERS:
                config = CHAPTER_CONFIGS[chapter_id]
                logger.info(f"撰稿: {chapter_id} - {config['name']}")
                try:
                    chapter_texts = generate_chapter(state, chapter_id, config, llm)
                    for tag, text in chapter_texts.items():
                        state.Draft[tag] = text
                        results[tag] = text
                    logger.info(f"  完成: {len(chapter_texts)} 个子段")
                except Exception as e:
                    logger.error(f"  生成 {chapter_id} 失败: {e}")
                    for tag in config["tags"]:
                        state.Draft[tag] = f"[{chapter_id} 生成失败: {str(e)}]"
                        results[tag] = state.Draft[tag]

    # Phase 2: chapter1 串行 (依赖前序章节 Draft)
    with AgentContext(state=state):
        for chapter_id in SERIAL_CHAPTERS:
            config = CHAPTER_CONFIGS[chapter_id]
            logger.info(f"撰稿: {chapter_id} - {config['name']} (串行)")
            try:
                chapter_texts = generate_chapter(state, chapter_id, config, llm)
                for tag, text in chapter_texts.items():
                    state.Draft[tag] = text
                    results[tag] = text
                logger.info(f"  完成: {len(chapter_texts)} 个子段")
            except Exception as e:
                logger.error(f"  生成 {chapter_id} 失败: {e}")
                for tag in config["tags"]:
                    state.Draft[tag] = f"[{chapter_id} 生成失败: {str(e)}]"
                    results[tag] = state.Draft[tag]

    return results


def _build_data_context(state: GlobalState, chapter_id: str) -> str:
    """为指定章节构建项目数据摘要，直接嵌入 user message。

    这样 LLM 不需要调 calc_lookup 就能获取正确数据，
    大幅提升 7B 模型的数据准确性。
    """
    meta = state.Static.meta
    calc = state.Calc
    parts = []

    # ── 基础信息（所有章节共享）──
    zones = state.ETL.zones or []
    zone_lines = [f"  - {z['name']}: {z.get('area_hm2', '?')} hm²" for z in zones]
    parts.append(f"""【项目基础信息】
项目名称: {meta['project_name']}
建设单位: {meta.get('construction_unit', '')}
城市: {meta['location']['city']}
项目性质: {meta.get('project_nature', '新建')}
总投资: {meta.get('total_investment', '')} 万元
土建投资: {meta.get('civil_investment', '')} 万元
总面积: {meta['land_area_hm2']} hm²
工期: {meta['schedule']['start_date']} ~ {meta['schedule']['end_date']}（{meta['schedule'].get('duration_months', 24)}个月）
防治标准: {meta.get('prevention_standard', '一级')}
绿化率: {meta.get('greening_rate', '')}%

【防治分区】（共{len(zones)}个分区）
{chr(10).join(zone_lines)}
总面积: {meta['land_area_hm2']} hm²""")

    # ── 章节专属数据 ──
    if chapter_id in ("chapter3", "chapter5"):
        # 分区 + 措施信息
        measures = state.Measures or []
        existing = [m for m in measures if m.get("source") == "existing"]
        planned = [m for m in measures if m.get("source") == "planned"]
        ex_lines = [f"  - {m.get('措施名称', m.get('name',''))}({m.get('单位', m.get('unit',''))}) × {m.get('数量', m.get('qty',''))}，位于{m.get('分区', m.get('zone',''))}" for m in existing]
        pl_lines = [f"  - {m.get('措施名称', m.get('name',''))}({m.get('单位', m.get('unit',''))}) × {m.get('数量', m.get('qty',''))}，位于{m.get('分区', m.get('zone',''))}" for m in planned]
        parts.append(f"""
【已有水保措施】（主体工程中具有水保功能的）
{chr(10).join(ex_lines) if ex_lines else '  无'}

【新增水保措施】（本方案新增的）
{chr(10).join(pl_lines) if pl_lines else '  无'}""")

    if chapter_id == "chapter4":
        # 侵蚀预测数据
        erosion = calc.erosion_df or {}
        ew = calc.earthwork or {}
        parts.append(f"""
【土方工程量】
挖方: {ew.get('dig', '')} m³，填方: {ew.get('fill', '')} m³
剥离表土: {ew.get('strip', '')} m³，余方外运: {ew.get('surplus', '')} m³

【侵蚀预测结果】
总预测流失量: {erosion.get('total_pred', '')} t
背景流失量: {erosion.get('total_bg', '')} t
新增流失量: {erosion.get('total_new', '')} t
施工期（S1）预测: {erosion.get('s1_pred', erosion.get('ep_s1_pred', ''))} t
施工期（S2）预测: {erosion.get('s2_pred', erosion.get('ep_s2_pred', ''))} t
自然恢复期（S3）预测: {erosion.get('s3_pred', erosion.get('ep_s3_pred', ''))} t

【各分区侵蚀量】""")
        matrix = erosion.get("matrix", {})
        for z in zones:
            zn = z["name"]
            zd = matrix.get(zn, {})
            parts.append(f"  - {zn}: 预测 {zd.get('total', '?')} t")

    if chapter_id == "chapter5":
        # 分区措施详细布局
        measures = state.Measures or []
        for z in zones:
            zn = z["name"]
            zm = [m for m in measures if m.get("分区", m.get("zone")) == zn]
            if zm:
                ml = [f"    · {m.get('措施名称', m.get('name',''))}({m.get('类型', m.get('type',''))}) {m.get('数量', m.get('qty',''))}{m.get('单位', m.get('unit',''))}" for m in zm]
                parts.append(f"\n【{zn}的措施】\n{chr(10).join(ml)}")

    if chapter_id == "chapter7":
        # 造价和效益数据
        cost = calc.cost_summary or {}
        benefit = calc.benefit or {}
        indicators = benefit.get("indicators", {})
        parts.append(f"""
【造价汇总】（单位: 万元）
工程措施费: {cost.get('c1_total', '')}（已有{cost.get('c1_exist', '')}＋新增{cost.get('c1_new', '')}）
植物措施费: {cost.get('c2_total', '')}（已有{cost.get('c2_exist', '')}＋新增{cost.get('c2_new', '')}）
临时措施费: {cost.get('c3_total', '')}
独立费用: {cost.get('c4_total', '')}
基本投资合计: {cost.get('c1234_total', '')}
预备费: {cost.get('c_contingency', '')}
水保补偿费: {cost.get('c_compensation', '')}
水保总投资: {cost.get('c_grand_total', '')} 万元

【六项指标达标分析】""")
        for key in ["治理度", "控制比", "渣土防护率", "表土保护率", "植被恢复率", "覆盖率"]:
            t_val = indicators.get(f"t_{key}", state.TplCtx.get(f"t_{key}", ""))
            r_val = indicators.get(f"r_{key}", state.TplCtx.get(f"r_{key}", ""))
            ok_val = indicators.get(f"ok_{key}", state.TplCtx.get(f"ok_{key}", ""))
            parts.append(f"  - {key}: 目标值{t_val}%，实际{r_val}%，{ok_val}")

    if chapter_id == "chapter1":
        # 综合说明需要全部关键数据
        cost = calc.cost_summary or {}
        erosion = calc.erosion_df or {}
        parts.append(f"""
【关键汇总数据】
水保总投资: {cost.get('c_grand_total', '')} 万元
总预测流失量: {erosion.get('total_pred', '')} t
新增流失量: {erosion.get('total_new', '')} t
已有措施: {len([m for m in (state.Measures or []) if m.get('source')=='existing'])} 项
新增措施: {len([m for m in (state.Measures or []) if m.get('source')=='planned'])} 项""")

    return chr(10).join(parts)


def generate_chapter(state: GlobalState, chapter_id: str,
                     config: dict, llm: LLMClient | None = None) -> dict[str, str]:
    """生成单个章节。"""
    agent = ToolCallingAgent(
        name=f"撰稿-{chapter_id}",
        system_prompt=WRITER_SYSTEM_PROMPT,
        tools=WRITER_TOOLS,
        llm=llm,
        max_turns=10,
    )

    # 构建 context — 直接注入项目数据，不依赖 LLM 自行查询
    data_context = _build_data_context(state, chapter_id)

    user_msg = f"""请编写报告的 {config['name']} 章节。

{data_context}

写作要求:
{config['guidance']}

输出格式（必须严格遵守，否则输出无效）:
请按以下格式输出，每个子段用 ===TAG_NAME=== 标记开头，标记后紧跟正文内容:

{chr(10).join(f'==={tag}===' for tag in config['tags'])}

规则:
1. 每个子段至少200字
2. 上面提供的数字是精确计算结果，必须原样引用，严禁编造或修改
3. ===TAG=== 标记后直接写正文，不要加任何标题或说明
4. 不要在第一个 ===TAG=== 之前写任何内容
5. 不要输出 Markdown 标记（#号标题等）
6. 分区名称必须使用上面提供的真实分区名，不要自行编造
"""

    result_text = agent.run(user_msg)

    # 解析分段输出
    return _parse_chapter_output(result_text, config["tags"])


def _parse_chapter_output(text: str, tags: list[str]) -> dict[str, str]:
    """解析 Agent 输出，按标签分段。

    解析策略（优先级从高到低）:
      1. ===TAG=== 标记分割
      2. ### TAG markdown 标题分割（LLM 常见替代格式）
      3. TAG 关键词行分割
    每段文本经过 _sanitize_text() 清洗。
    """
    result = {}

    # ── 策略1: ===TAG=== 标记 ──
    found_marker = any(f"==={tag}===" in text for tag in tags)
    if found_marker:
        result = _split_by_markers(text, tags, "==={}===")
        if _is_good_parse(result, tags):
            return {k: _sanitize_text(v) for k, v in result.items()}

    # ── 策略2: ### TAG markdown 标题 ──
    found_md = any(re.search(rf"^#{{1,4}}\s*{re.escape(tag)}", text, re.MULTILINE) for tag in tags)
    if found_md:
        result = _split_by_md_headers(text, tags)
        if _is_good_parse(result, tags):
            return {k: _sanitize_text(v) for k, v in result.items()}

    # ── 策略3: 按 TAG 关键词行分割 ──
    found_kw = any(re.search(rf"^\s*{re.escape(tag)}\s*$", text, re.MULTILINE) for tag in tags)
    if found_kw:
        result = _split_by_keyword_lines(text, tags)
        if _is_good_parse(result, tags):
            return {k: _sanitize_text(v) for k, v in result.items()}

    # ── Fallback: 整体清洗后尝试按数字编号(1. 2. 3.)分割 ──
    cleaned = _sanitize_text(text)
    if cleaned:
        result = _split_by_numbered_sections(cleaned, tags)
        if _is_good_parse(result, tags):
            return result

    # ── 最终 Fallback: 全文作为第一个 tag，其余标记待完善 ──
    logger.warning(f"无法按标签解析输出，使用整体清洗文本")
    cleaned = _sanitize_text(text) if text else ""
    result = {}
    for i, tag in enumerate(tags):
        if i == 0 and cleaned:
            result[tag] = cleaned
        else:
            result[tag] = f"[{tag} 待完善]"
    return result


def _split_by_markers(text: str, tags: list[str], fmt: str) -> dict[str, str]:
    """按指定格式的标记分割文本。"""
    result = {}
    for i, tag in enumerate(tags):
        marker = fmt.format(tag)
        start = text.find(marker)
        if start != -1:
            start += len(marker)
            end = len(text)
            for next_tag in tags[i + 1:]:
                next_marker = fmt.format(next_tag)
                next_pos = text.find(next_marker, start)
                if next_pos != -1:
                    end = next_pos
                    break
            result[tag] = text[start:end].strip()
        else:
            result[tag] = ""
    return result


def _split_by_md_headers(text: str, tags: list[str]) -> dict[str, str]:
    """按 Markdown 标题行分割（### tag_name）。"""
    result = {}
    for i, tag in enumerate(tags):
        pat = re.compile(rf"^#{{1,4}}\s*{re.escape(tag)}\s*$", re.MULTILINE)
        m = pat.search(text)
        if m:
            start = m.end()
            end = len(text)
            for next_tag in tags[i + 1:]:
                next_pat = re.compile(rf"^#{{1,4}}\s*{re.escape(next_tag)}\s*$", re.MULTILINE)
                nm = next_pat.search(text, start)
                if nm:
                    end = nm.start()
                    break
            result[tag] = text[start:end].strip()
        else:
            result[tag] = ""
    return result


def _split_by_keyword_lines(text: str, tags: list[str]) -> dict[str, str]:
    """按 tag 名称独占一行的方式分割。"""
    result = {}
    for i, tag in enumerate(tags):
        pat = re.compile(rf"^\s*{re.escape(tag)}\s*$", re.MULTILINE)
        m = pat.search(text)
        if m:
            start = m.end()
            end = len(text)
            for next_tag in tags[i + 1:]:
                next_pat = re.compile(rf"^\s*{re.escape(next_tag)}\s*$", re.MULTILINE)
                nm = next_pat.search(text, start)
                if nm:
                    end = nm.start()
                    break
            result[tag] = text[start:end].strip()
        else:
            result[tag] = ""
    return result


def _split_by_numbered_sections(text: str, tags: list[str]) -> dict[str, str]:
    """按数字编号（1. 2. 3.）分割文本到各 tag。"""
    result = {}
    sections = re.split(r"\n(?=\d+[.、]\s)", text)
    for i, tag in enumerate(tags):
        if i < len(sections):
            # 去掉行首的编号
            chunk = re.sub(r"^\d+[.、]\s*", "", sections[i].strip())
            result[tag] = chunk
        else:
            result[tag] = ""
    return result


def _is_good_parse(result: dict[str, str], tags: list[str]) -> bool:
    """判断解析结果是否合理：至少一半以上 tag 有非空内容。"""
    non_empty = sum(1 for t in tags if result.get(t, "").strip())
    return non_empty >= max(1, len(tags) // 2)


def rewrite_chapter(state: GlobalState, chapter_id: str,
                    feedback: str, llm: LLMClient | None = None) -> dict[str, str]:
    """重写指定章节（审计回弹时调用）。"""
    config = CHAPTER_CONFIGS.get(chapter_id)
    if not config:
        return {}

    agent = ToolCallingAgent(
        name=f"重写-{chapter_id}",
        system_prompt=WRITER_SYSTEM_PROMPT,
        tools=WRITER_TOOLS,
        llm=llm,
        max_turns=6,
    )

    # 获取原文
    original_texts = {tag: state.Draft.get(tag, "") for tag in config["tags"]}

    user_msg = f"""请重写 {config['name']} 章节。

审计反馈:
{feedback}

原文:
{json.dumps(original_texts, ensure_ascii=False, indent=2)}

要求: 根据审计反馈修改原文，修正数值错误，补充不足内容。

输出格式（严格遵守）:
{chr(10).join(f'==={tag}===' for tag in config['tags'])}

规则: 每个 ===TAG=== 后直接写正文，不要加标题、说明、前言或免责声明。
"""

    with AgentContext(state=state):
        result_text = agent.run(user_msg)
        chapter_texts = _parse_chapter_output(result_text, config["tags"])

        for tag, text in chapter_texts.items():
            state.Draft[tag] = text

    return chapter_texts
