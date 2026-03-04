"""措施规划师 Agent — 决策新增水土保持措施。

输入: State.Static + ETL.zones + Calc.erosion_df + measures_existing
工具: 6 个 (4 planner_tools + 2 spatial_tools)
输出: JSON 数组写入 State.Measures（与已有措施合并）
"""

from __future__ import annotations

import json
import logging

from src.agents.base import ToolCallingAgent, LLMClient
from src.tools.planner_tools import PLANNER_TOOLS
from src.state import GlobalState

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """你是一位资深的水土保持措施规划师。你的任务是根据项目分区特征、水土流失预测结果和标准措施库，为每个防治分区规划新增的水土保持措施。

## 你的职责
1. 分析每个防治分区的特点和水土流失风险
2. 查询标准措施库，选择适合的措施
3. 估算工程量
4. 确保满足法规最低要求
5. 参考范文案例

## 输出格式
你必须输出一个 JSON 数组，每个元素代表一条新增措施:
```json
[
  {
    "措施名称": "排水沟C20(40×40)",
    "分区": "建(构)筑物区",
    "类型": "工程措施",
    "单位": "m",
    "数量": 230,
    "功能": "场地排水"
  }
]
```

## 约束
- 每个分区至少要有工程措施+植物措施+临时措施各1项
- 优先选择 priority=高 的措施
- 数量必须用 quantity_estimator 工具计算
- 不要重复已有措施

## 空间布置要求
在输出每条措施时，**必须**增加 "空间布置" 字段:
```json
{
  "措施名称": "排水沟C20(40×40)",
  "分区": "建(构)筑物区",
  "类型": "工程措施",
  "单位": "m", "数量": 230,
  "功能": "场地排水",
  "空间布置": {
    "position": "沿场地南侧道路两侧",
    "coverage": "从大门入口至东南角, 全长约230m",
    "direction": "西→东",
    "note": "与道路平行, 间距1.5m"
  }
}
```
请先调用 spatial_context_tool 了解场地空间布局，
再调用 atlas_reference_tool 查询标准图集中的布置规范。
根据空间信息决定每条措施的具体位置、走向和覆盖范围。
"""


def run_planner(state: GlobalState, llm: LLMClient | None = None) -> list[dict]:
    """运行措施规划师 Agent。"""
    from src.context import AgentContext
    from src.tools.spatial_tools import SPATIAL_TOOLS

    # 初始化图集 RAG
    atlas_rag = None
    try:
        from src.atlas_rag import AtlasRAG
        atlas = AtlasRAG()
        if atlas.is_available():
            atlas_rag = atlas
    except Exception:
        pass  # 图集 RAG 不可用，工具会使用内置规范回退

    all_tools = PLANNER_TOOLS + SPATIAL_TOOLS

    agent = ToolCallingAgent(
        name="措施规划师",
        system_prompt=PLANNER_SYSTEM_PROMPT,
        tools=all_tools,
        llm=llm,
        max_turns=10,
    )

    # 构建用户消息
    meta = state.Static.meta
    zones = state.ETL.zones
    erosion = state.Calc.erosion_df
    existing = state.Static.measures_existing

    user_msg = f"""请为以下项目规划新增水土保持措施:

## 项目信息
- 名称: {meta['project_name']}
- 城市: {meta['location']['city']}
- 总面积: {meta['land_area_hm2']} hm²
- 防治标准: {meta.get('prevention_level', '一级')}

## 防治分区
{json.dumps([{"name": z["name"], "area_hm2": z["area_hm2"]} for z in zones], ensure_ascii=False, indent=2)}

## 水土流失预测
- 总预测流失量: {erosion.get('total_pred', 0):.2f} t
- 新增流失量: {erosion.get('total_new', 0):.2f} t

## 已有措施
{json.dumps([{"name": m.get("措施名称", ""), "zone": m.get("分区", ""), "type": m.get("类型", "")} for m in existing], ensure_ascii=False, indent=2)}

请依次为每个分区查询措施库、估算工程量、检查合规性，然后输出完整的新增措施 JSON 数组。"""

    with AgentContext(state=state, atlas_rag=atlas_rag):
        result_text = agent.run(user_msg)

    # 解析 JSON 输出
    new_measures = _parse_measures(result_text)

    # 写入 State
    for m in new_measures:
        m["source"] = "planned"
        state.Measures.append(m)

    # 保存空间布置信息到 ETL.measure_layout (供措施图渲染使用)
    state.ETL.measure_layout = [
        m for m in new_measures if m.get("空间布置")
    ]

    logger.info(f"措施规划师完成: 新增 {len(new_measures)} 条措施, "
                f"含空间布置 {len(state.ETL.measure_layout)} 条")
    return new_measures


def _parse_measures(text: str) -> list[dict]:
    """从 Agent 输出文本中提取 JSON 数组。"""
    # 尝试直接解析
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 代码块
    import re
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    # 尝试找到 [...] 形式
    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        try:
            data = json.loads(bracket_match.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    logger.warning("⚠ Planner JSON 解析失败，降级到规则默认措施（输出质量可能降低）")
    logger.debug(f"Planner 原始输出前500字: {text[:500]}")
    # 记录到 State.Flags 供 Adapter / Audit 参考
    try:
        from src.context import get_state_or_none
        _st = get_state_or_none()
        if _st is not None:
            _st.Flags["planner_fallback"] = True
    except Exception:
        pass
    return _default_measures()


def _default_measures() -> list[dict]:
    """当 LLM 输出解析失败时，返回基于规则的默认措施。"""
    from src.tools.planner_tools import measure_library, quantity_estimator
    from src.context import get_state_or_none

    default = []

    # 优先从 State 动态读取分区（避免硬编码）
    _st = get_state_or_none()
    if _st is not None and _st.ETL.zones:
        zone_configs = [(z["name"], z.get("area_hm2", 1.0)) for z in _st.ETL.zones]
    else:
        zone_configs = [
            ("建(构)筑物区", 3.67),
            ("道路广场区", 2.10),
            ("绿化工程区", 1.17),
            ("施工生产生活区", 0.75),
            ("临时堆土区", 0.2468),
        ]

    for zone_name, area in zone_configs:
        # 查询高优先级措施
        candidates = measure_library(zone_name)
        for c in candidates:
            if c["priority"] == "高":
                est = quantity_estimator(c["name"], area, zone_name)
                default.append({
                    "措施名称": c["name"],
                    "分区": zone_name,
                    "类型": c["type"],
                    "单位": c["unit"],
                    "数量": est["quantity"],
                    "功能": c.get("description", "")[:20],
                })

    return default
