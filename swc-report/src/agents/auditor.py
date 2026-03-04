"""审计智能体 Agent — 审查方案报告质量。

评分维度: 数值40% + 文本30% + 结构20% + 完整性10%
重试策略: ≥80 通过 / 60-79 回弹撰稿 / <60 强制通过
每章最多 3 次重试
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from src.agents.base import ToolCallingAgent, LLMClient
from src.context import AgentContext
from src.tools.auditor_tools import AUDITOR_TOOLS
from src.state import GlobalState
from src.settings import AUDITOR_PASS_SCORE, AUDITOR_FAIL_SCORE, AUDITOR_MAX_RETRY

logger = logging.getLogger(__name__)

AUDITOR_SYSTEM_PROMPT = """你是一位严格的水土保持方案审计专家。你的任务是审查方案报告的质量，确保:
1. 数值计算正确，引用一致（权重40%）
2. 文本质量达标，无幻觉数据（权重30%）
3. 报告结构完整，符合规范（权重20%）
4. 所有章节和表格非空（权重10%）

## 审查流程
1. 先用 numeric_validator 工具检查数值一致性
2. 再用 text_validator 逐章检查文本质量
3. 最后用 rag_comparator 对比范文结构

## 输出格式
你必须输出 JSON 格式的审计报告:
```json
{
  "total_score": 85,
  "dimensions": {
    "numeric": {"score": 90, "issues": []},
    "text": {"score": 80, "issues": ["第4章文本较短"]},
    "structure": {"score": 85, "issues": []},
    "completeness": {"score": 90, "issues": []}
  },
  "chapter_scores": {
    "chapter1": 85,
    "chapter2": 90
  },
  "failed_chapters": ["chapter4"],
  "failure_details": [
    {
      "chapter": "chapter4",
      "severity": "major",
      "failure_source": "writer",
      "description": "第4章预测计算过程描述不够详细",
      "suggested_action": "retry_writer"
    }
  ],
  "feedback": {
    "chapter4": "请补充侵蚀模数来源和计算公式"
  }
}
```

## failure_source 取值
- "feature_extract": CAD/GIS特征提取问题 → suggested_action: "rerun_feature_extract"
- "planner": 措施规划不合理 → suggested_action: "rerun_planner"
- "calc": 数值计算错误 → suggested_action: "rerun_calc"
- "writer": 文本质量问题 → suggested_action: "retry_writer"
- "render": 图纸/排版问题 → suggested_action: "rerun_render"

## severity 取值
- "critical": 必须修改 (影响方案通过)
- "major": 重要 (显著影响质量)
- "minor": 次要 (可接受但建议改进)
"""


def run_auditor(state: GlobalState, llm: LLMClient | None = None) -> dict:
    """运行审计智能体。"""
    agent = ToolCallingAgent(
        name="审计智能体",
        system_prompt=AUDITOR_SYSTEM_PROMPT,
        tools=AUDITOR_TOOLS,
        llm=llm,
        max_turns=8,
    )

    # 构建审计输入
    draft_summary = {}
    for key, text in state.Draft.items():
        draft_summary[key] = f"({len(text)}字)" if text else "(空)"

    user_msg = f"""请审查以下水土保持方案报告:

## 章节状态
{json.dumps(draft_summary, ensure_ascii=False, indent=2)}

## 审查要求
1. 使用 numeric_validator 检查所有数值
2. 对每个章节使用 text_validator
3. 使用 rag_comparator 对比结构
4. 给出总分和各维度评分

请开始审查。"""

    with AgentContext(state=state):
        result_text = agent.run(user_msg)
        # _parse_audit_result 的 fallback 路径会直接调用工具函数，需要上下文
        audit_result = _parse_audit_result(result_text, state)

    # 写入 Flags
    state.Flags["final_score"] = audit_result.get("total_score", 0)
    state.Flags["audit_log"].append({
        "timestamp": datetime.now().isoformat(),
        "score": audit_result.get("total_score", 0),
        "result": audit_result,
    })

    # 更新各章节分数
    for ch, score in audit_result.get("chapter_scores", {}).items():
        state.Flags["scores"][ch] = score

    logger.info(f"审计完成: 总分 {audit_result.get('total_score', 0)}")
    return audit_result


def _parse_audit_result(text: str, state: GlobalState) -> dict:
    """解析审计 Agent 的输出。"""
    # 尝试直接解析 JSON
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "total_score" in data:
            return data
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 代码块
    import re
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # 尝试找 {...}
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            data = json.loads(brace_match.group())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # 解析失败，使用硬校验结果生成
    logger.warning("无法解析审计输出，使用 fallback 评分")
    return _fallback_audit(state)


def _fallback_audit(state: GlobalState) -> dict:
    """当 LLM 输出无法解析时，用 Python 硬逻辑评分。"""
    from src.tools.auditor_tools import numeric_validator, text_validator, rag_comparator

    # 数值校验
    num_result = numeric_validator("all")
    num_score = 100 if num_result["pass"] else max(60, 100 - len(num_result["errors"]) * 10)

    # 文本校验
    text_scores = {}
    failed_chapters = []
    feedback = {}
    for ch_num in range(1, 9):
        ch_id = f"ch{ch_num}"
        tv = text_validator(ch_id)
        ch_score = 100 if tv["pass"] else max(50, 100 - len(tv["errors"]) * 20 - len(tv["warnings"]) * 5)
        text_scores[f"chapter{ch_num}"] = ch_score
        if ch_score < AUDITOR_PASS_SCORE:
            failed_chapters.append(f"chapter{ch_num}")
            issues = tv["errors"] + tv["warnings"]
            feedback[f"chapter{ch_num}"] = "; ".join(issues) if issues else "文本质量需提升"

    text_avg = sum(text_scores.values()) / max(len(text_scores), 1)

    # 结构校验
    struct_result = rag_comparator()
    struct_score = struct_result.get("similarity_score", 80)

    # 完整性
    total_tags = len(state.Draft)
    non_empty = sum(1 for v in state.Draft.values() if v and len(v) > 10)
    completeness = round(non_empty / max(total_tags, 1) * 100, 1)

    # 加权总分
    total_score = round(
        num_score * 0.4 + text_avg * 0.3 + struct_score * 0.2 + completeness * 0.1
    )

    # 构建 failure_details (分级回退信息)
    failure_details = []
    for ch in failed_chapters:
        ch_score = text_scores.get(ch, 0)
        severity = "critical" if ch_score < 50 else "major" if ch_score < 70 else "minor"
        fb_text = feedback.get(ch, "")

        # 推断 failure_source
        if num_score < 70 and ("数值" in fb_text or "计算" in fb_text):
            source, action = "calc", "rerun_calc"
        elif "图" in fb_text or "渲染" in fb_text or "措施图" in fb_text:
            source, action = "render", "rerun_render"
        else:
            source, action = "writer", "retry_writer"

        failure_details.append({
            "chapter": ch,
            "severity": severity,
            "failure_source": source,
            "description": fb_text,
            "suggested_action": action,
        })

    return {
        "total_score": total_score,
        "dimensions": {
            "numeric": {"score": num_score, "issues": num_result.get("errors", [])},
            "text": {"score": round(text_avg), "issues": []},
            "structure": {"score": round(struct_score), "issues": struct_result.get("issues", [])},
            "completeness": {"score": round(completeness), "issues": []},
        },
        "chapter_scores": text_scores,
        "failed_chapters": failed_chapters,
        "failure_details": failure_details,
        "feedback": feedback,
    }


def get_retry_chapters(state: GlobalState, audit_result: dict) -> list[tuple[str, str]]:
    """获取需要重试的章节列表。

    返回: [(chapter_id, feedback), ...]
    """
    failed = audit_result.get("failed_chapters", [])
    feedbacks = audit_result.get("feedback", {})
    retry_list = []

    for ch in failed:
        retry_count = state.Flags["retry_count"].get(ch, 0)
        if retry_count < AUDITOR_MAX_RETRY:
            fb = feedbacks.get(ch, "请提升文本质量")
            retry_list.append((ch, fb))
            state.Flags["retry_count"][ch] = retry_count + 1

    return retry_list
