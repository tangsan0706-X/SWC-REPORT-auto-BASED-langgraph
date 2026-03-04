"""数据适配器智能体 — 在 assemble 之后校验数据完整性并回调修复。

位于 Step 9 (assemble) 和 Step 10 (writer) 之间，作为 Step 9.5。
发现必填指标缺失时，主动回调 Planner 或 Calculator 补充，然后 reassemble。

运行模式:
  - LLM 模式: ToolCallingAgent 分析缺失字段 → 调用回调工具 → 最多 2 轮修复
  - 非 LLM 模式: 纯 Python 硬逻辑检查 + 自动修复
"""

from __future__ import annotations

import json
import logging
import re

from src.agents.base import ToolCallingAgent, LLMClient
from src.context import AgentContext
from src.tools.adapter_tools import (
    ADAPTER_TOOLS,
    REQUIRED_TAGS,
    validate_completeness,
    validate_cross_refs,
    rerun_calculator,
    callback_planner,
    reassemble,
    get_fix_suggestion,
)
from src.state import GlobalState
from src.settings import ADAPTER_MAX_TURNS, ADAPTER_MAX_CALLBACKS

logger = logging.getLogger(__name__)

ADAPTER_SYSTEM_PROMPT = """你是数据适配器智能体，负责在报告撰写前校验所有数据完整性。

## 工作流程
1. 调用 validate_completeness 检查所有必填标签
2. 调用 validate_cross_refs 检查数值一致性
3. 如果发现缺失:
   a. 调用 get_fix_suggestion 获取修复建议
   b. 按建议顺序执行 callback_planner / rerun_calculator
   c. 每次修复后调用 reassemble 更新标签
   d. 再次 validate_completeness 确认修复
4. 最多执行 2 轮修复循环
5. 输出 JSON 校验报告

## 输出格式
你必须输出如下 JSON 格式的校验报告:
```json
{
  "status": "pass",
  "total_tags": 229,
  "valid_tags": 220,
  "fixed_tags": 9,
  "remaining_issues": [],
  "callbacks_made": [
    {"action": "rerun_calculator", "target": "cost", "success": true}
  ]
}
```

status 取值:
- "pass": 所有必填标签校验通过
- "pass_with_warnings": 有不可修复的缺失但不影响核心功能
- "fail": 存在严重数据缺失无法修复
"""


def run_adapter(state: GlobalState, llm: LLMClient | None = None) -> dict:
    """LLM 模式: Agent 自主校验 + 回调修复。"""
    agent = ToolCallingAgent(
        name="数据适配器",
        system_prompt=ADAPTER_SYSTEM_PROMPT,
        tools=ADAPTER_TOOLS,
        llm=llm,
        max_turns=ADAPTER_MAX_TURNS,
    )

    with AgentContext(state=state):
        result_text = agent.run("请检查并修复数据完整性。")
        return _parse_adapter_result(result_text, state)


def _fallback_adapter(state: GlobalState) -> dict:
    """非 LLM 模式: Python 硬逻辑检查 + 自动修复。"""
    callbacks_made: list[dict] = []
    initial_missing = 0

    for round_num in range(ADAPTER_MAX_CALLBACKS):
        # 1) 校验完整性
        result = validate_completeness()
        if "error" in result:
            return {"status": "fail", "error": result["error"]}

        summary = result["summary"]
        missing_count = summary["total_missing"]

        if round_num == 0:
            initial_missing = missing_count

        if missing_count == 0:
            break

        # 2) 收集缺失类别
        missing_cats = [
            cat for cat, info in result["categories"].items()
            if info["status"] == "missing"
        ]

        # 3) 获取修复建议
        suggestion = get_fix_suggestion(missing_cats)
        fix_actions = suggestion.get("fix_actions", [])

        if not fix_actions:
            # 没有可修复的动作
            break

        # 4) 按顺序执行修复动作
        for action in fix_actions:
            act = action["action"]
            target = action["target"]
            try:
                if act == "callback_planner":
                    res = callback_planner()
                elif act == "rerun_calculator":
                    res = rerun_calculator(target)
                elif act == "reassemble":
                    res = reassemble()
                else:
                    res = {"success": False, "error": f"未知动作: {act}"}

                success = res.get("success", False)
                callbacks_made.append({
                    "action": act,
                    "target": target,
                    "success": success,
                })
                if not success:
                    logger.warning(f"[适配器] 修复动作失败: {act}({target}): {res.get('error')}")
            except Exception as e:
                logger.error(f"[适配器] 修复动作异常: {act}({target}): {e}")
                callbacks_made.append({
                    "action": act,
                    "target": target,
                    "success": False,
                })

    # 5) 最终校验
    final_result = validate_completeness()
    cross_result = validate_cross_refs()

    if "error" in final_result:
        return {"status": "fail", "error": final_result["error"]}

    final_summary = final_result["summary"]
    final_missing = final_summary["total_missing"]
    fixed_count = max(0, initial_missing - final_missing)

    # 收集剩余问题
    remaining = []
    for cat, info in final_result["categories"].items():
        for tag_info in info.get("missing_tags", []):
            remaining.append(f"{cat}.{tag_info['tag']}")

    cross_errors = cross_result.get("errors", [])
    remaining.extend(cross_errors)

    # 判断状态
    if final_missing == 0 and not cross_errors:
        status = "pass"
    elif final_missing <= 3 and not cross_errors:
        status = "pass_with_warnings"
    else:
        status = "fail" if cross_errors else "pass_with_warnings"

    return {
        "status": status,
        "total_tags": final_summary["total_checked"],
        "valid_tags": final_summary["total_valid"],
        "fixed_tags": fixed_count,
        "remaining_issues": remaining,
        "callbacks_made": callbacks_made,
    }


def _parse_adapter_result(text: str, state: GlobalState) -> dict:
    """解析 Agent 输出，fallback 到硬逻辑。"""
    # 1) 尝试直接解析 JSON
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "status" in data:
            return data
    except json.JSONDecodeError:
        pass

    # 2) 尝试提取 JSON 代码块
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if isinstance(data, dict) and "status" in data:
                return data
        except json.JSONDecodeError:
            pass

    # 3) 尝试找 {...}
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            data = json.loads(brace_match.group())
            if isinstance(data, dict) and "status" in data:
                return data
        except json.JSONDecodeError:
            pass

    # 4) 解析失败，使用硬逻辑
    logger.warning("无法解析适配器输出，使用 fallback 逻辑")
    return _fallback_adapter(state)
