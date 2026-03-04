"""Agent 基础框架 — vLLM 客户端 + Tool-calling 循环。

提供:
  - LLMClient: OpenAI-compatible API 客户端（含超时 + 重试）
  - ToolCallingAgent: 通用 Agent 基类（含消息窗口管理 + 结构化摘要）
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from openai import OpenAI

from src.settings import (
    VLLM_URL, VLLM_MODEL_NAME, VLLM_MAX_TOKENS,
    VLLM_TEMPERATURE, AGENT_MAX_TURNS,
    LLM_TIMEOUT, LLM_MAX_RETRIES,
    CONTEXT_SUMMARIZE_LLM, CONTEXT_SUMMARY_MAX_TOKENS,
)

logger = logging.getLogger(__name__)


class LLMClient:
    """封装 OpenAI-compatible API 调用（指向 vLLM）。"""

    def __init__(self, base_url: str = VLLM_URL, model: str = VLLM_MODEL_NAME,
                 timeout: int = LLM_TIMEOUT, max_retries: int = LLM_MAX_RETRIES):
        self.client = OpenAI(
            base_url=base_url,
            api_key="not-needed",  # vLLM 不需要 key
            timeout=timeout,       # httpx 超时（秒）
        )
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int = VLLM_MAX_TOKENS,
             temperature: float = VLLM_TEMPERATURE) -> dict:
        """调用 LLM，返回 response message。含重试 + 指数退避。"""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": self.timeout,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
                return response.choices[0].message
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = 2 ** attempt  # 1s, 2s
                    logger.warning(f"LLM 调用失败 (第{attempt + 1}次), {wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    logger.error(f"LLM 调用失败 (已重试{self.max_retries}次): {e}")
        raise last_error


# ── 消息窗口管理 + 结构化摘要 ─────────────────────────────────

# 粗略估算: 1 个中文字符 ≈ 1.5 token, 1 个英文单词 ≈ 1.3 token
# 保守按 1 字符 = 1 token 估算消息长度
_MAX_CONTEXT_CHARS = 48000  # 约 48K 字符 ≈ 32K-48K tokens


def _estimate_message_chars(messages: list[dict]) -> int:
    """粗略估算消息列表的总字符数。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "") or ""
        total += len(content)
        # tool_calls 中的 arguments 也占 token
        for tc in msg.get("tool_calls", []):
            total += len(tc.get("function", {}).get("arguments", ""))
    return total


def _extract_structured_summary(dropped_messages: list[dict]) -> str:
    """从被丢弃的消息中提取结构化摘要（纯 Python，零 LLM 开销）。

    提取信息:
      - 调用了哪些工具、各调用几次
      - 工具返回的关键数值（从 JSON 结果中提取 number 类型字段）
      - 是否有错误发生
      - assistant 的关键结论片段
    """
    tool_calls_count: dict[str, int] = {}
    key_numbers: dict[str, Any] = {}
    errors: list[str] = []
    assistant_snippets: list[str] = []

    for msg in dropped_messages:
        role = msg.get("role", "")

        if role == "assistant":
            # 提取 tool_calls 名称
            for tc in msg.get("tool_calls", []):
                fname = tc.get("function", {}).get("name", "unknown")
                tool_calls_count[fname] = tool_calls_count.get(fname, 0) + 1
            # 提取 assistant 文本摘要（取前 100 字符）
            content = msg.get("content", "") or ""
            if content.strip():
                snippet = content.strip()[:100]
                if len(content.strip()) > 100:
                    snippet += "..."
                assistant_snippets.append(snippet)

        elif role == "tool":
            # 解析工具返回值，提取关键数值和错误
            content = msg.get("content", "") or ""
            try:
                data = json.loads(content) if content.startswith("{") else {}
            except (json.JSONDecodeError, ValueError):
                data = {}

            if isinstance(data, dict):
                if "error" in data:
                    errors.append(str(data["error"])[:80])
                # 提取顶层数值字段（最多 10 个，避免摘要过长）
                for k, v in data.items():
                    if isinstance(v, (int, float)) and len(key_numbers) < 10:
                        key_numbers[k] = v

    # 组装摘要文本
    parts = []
    if tool_calls_count:
        calls_str = ", ".join(f"{name}×{cnt}" for name, cnt in tool_calls_count.items())
        parts.append(f"已调用工具: {calls_str}")
    if key_numbers:
        nums_str = ", ".join(f"{k}={v}" for k, v in list(key_numbers.items())[:8])
        parts.append(f"关键数值: {nums_str}")
    if errors:
        parts.append(f"出现错误({len(errors)}个): {'; '.join(errors[:3])}")
    if assistant_snippets:
        parts.append(f"中间结论: {assistant_snippets[-1]}")

    if not parts:
        return f"已省略 {len(dropped_messages)} 条历史消息。"

    summary = "; ".join(parts)
    return f"[历史摘要 ({len(dropped_messages)}条消息)] {summary}"


def _llm_summarize_dropped(dropped_messages: list[dict], llm_client) -> str | None:
    """用一次轻量 LLM 调用压缩被丢弃的消息。

    仅在 CONTEXT_SUMMARIZE_LLM=true 时启用。
    失败时返回 None，由调用方 fallback 到结构化摘要。
    """
    if not CONTEXT_SUMMARIZE_LLM or llm_client is None:
        return None

    # 收集被丢弃消息的文本（截断到 4000 字符以控制摘要调用成本）
    text_parts = []
    char_count = 0
    for msg in dropped_messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        if content:
            line = f"[{role}] {content[:500]}"
            text_parts.append(line)
            char_count += len(line)
            if char_count > 4000:
                break
        for tc in msg.get("tool_calls", []):
            fname = tc.get("function", {}).get("name", "")
            text_parts.append(f"[tool_call] {fname}")

    dropped_text = "\n".join(text_parts)

    try:
        response = llm_client.chat(
            messages=[
                {"role": "system", "content": "你是一个精简摘要助手。用中文输出，不超过200字。"},
                {"role": "user", "content": f"请用一段话概括以下对话历史的关键信息（工具调用、数值结果、结论）：\n\n{dropped_text}"},
            ],
            tools=None,
            max_tokens=CONTEXT_SUMMARY_MAX_TOKENS,
            temperature=0.1,
        )
        summary = response.content if hasattr(response, "content") else str(response)
        if summary and len(summary.strip()) > 10:
            logger.info(f"LLM 摘要成功: {len(summary)} 字符")
            return f"[LLM摘要 ({len(dropped_messages)}条消息)] {summary.strip()}"
    except Exception as e:
        logger.warning(f"LLM 摘要失败，回退到结构化摘要: {e}")

    return None


def _trim_messages(messages: list[dict], max_chars: int = _MAX_CONTEXT_CHARS,
                   llm_client=None) -> list[dict]:
    """当消息总长度超过阈值时，保留 system + user + 最近 N 轮，丢弃中间的旧轮次。

    增强策略:
      - 始终保留 messages[0] (system prompt) 和 messages[1] (user message)
      - 从最新的消息往前保留，直到加上 system+user 仍不超过 max_chars
      - 对被丢弃的消息生成结构化摘要（提取工具名、数值、错误）
      - 可选: CONTEXT_SUMMARIZE_LLM=true 时用 LLM 生成更高质量的摘要
    """
    if len(messages) <= 3:
        return messages

    current_chars = _estimate_message_chars(messages)
    if current_chars <= max_chars:
        return messages

    # 头部: system + user（必须保留）
    head = messages[:2]
    head_chars = _estimate_message_chars(head)

    # 尾部: 从后往前保留
    tail: list[dict] = []
    tail_chars = 0
    budget = max_chars - head_chars - 800  # 800 留给摘要消息（比之前多，因为摘要更丰富）

    for msg in reversed(messages[2:]):
        msg_chars = _estimate_message_chars([msg])
        if tail_chars + msg_chars > budget:
            break
        tail.insert(0, msg)
        tail_chars += msg_chars

    # 如果尾部就是全部消息[2:]，不需要裁剪
    if len(tail) >= len(messages) - 2:
        return messages

    # 被丢弃的消息
    dropped_count = len(messages) - 2 - len(tail)
    dropped_messages = messages[2:2 + dropped_count]

    # 生成摘要: 优先 LLM 摘要 → 回退到结构化摘要
    summary_text = _llm_summarize_dropped(dropped_messages, llm_client)
    if summary_text is None:
        summary_text = _extract_structured_summary(dropped_messages)

    summary_msg = {
        "role": "user",
        "content": summary_text,
    }

    trimmed = head + [summary_msg] + tail
    logger.info(f"消息窗口裁剪: {len(messages)} → {len(trimmed)} 条, "
                f"{current_chars} → {_estimate_message_chars(trimmed)} 字符")
    return trimmed


class ToolCallingAgent:
    """通用 Tool-calling Agent 基类。

    实现 ReAct 循环:
      prompt → LLM → 解析 tool_calls → 执行 → 追加结果 → 再次调用 LLM

    增强:
      - 消息窗口管理: 超过 token 预算时自动裁剪旧轮次
      - 工具执行结果截断: 防止单个工具返回值过大
    """

    # 单个工具返回值最大字符数（超出截断）
    TOOL_RESULT_MAX_CHARS = 8000

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: list[tuple[Callable, dict]],
        llm: LLMClient | None = None,
        max_turns: int = AGENT_MAX_TURNS,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.llm = llm or LLMClient()
        self.max_turns = max_turns

        # 工具注册
        self.tool_schemas = [schema for _, schema in tools]
        self.tool_map: dict[str, Callable] = {}
        for func, schema in tools:
            fname = schema["function"]["name"]
            self.tool_map[fname] = func

    def run(self, user_message: str, context: dict | None = None) -> str:
        """执行 Agent，返回最终文本输出。"""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]

        for turn in range(self.max_turns):
            logger.info(f"[{self.name}] Turn {turn + 1}/{self.max_turns}")

            # 消息窗口管理: 裁剪过长的历史（传入 llm 用于可选的 LLM 摘要）
            messages = _trim_messages(messages, llm_client=self.llm)

            response = self.llm.chat(
                messages=messages,
                tools=self.tool_schemas if self.tool_schemas else None,
            )

            # 如果有 tool_calls，执行工具
            tool_calls = getattr(response, "tool_calls", None)
            if tool_calls:
                # 添加 assistant 消息
                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                })

                # 执行每个工具调用
                for tc in tool_calls:
                    func_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    logger.info(f"[{self.name}] Calling tool: {func_name}({args})")

                    if func_name in self.tool_map:
                        try:
                            result = self.tool_map[func_name](**args)
                            result_str = json.dumps(result, ensure_ascii=False, default=str)
                        except Exception as e:
                            logger.warning(f"[{self.name}] 工具 {func_name} 异常: {e}")
                            result_str = json.dumps({"error": str(e)}, ensure_ascii=False)
                    else:
                        result_str = json.dumps(
                            {"error": f"未知工具: {func_name}"},
                            ensure_ascii=False,
                        )

                    # 截断过长的工具返回值
                    if len(result_str) > self.TOOL_RESULT_MAX_CHARS:
                        truncated_len = len(result_str)
                        result_str = result_str[:self.TOOL_RESULT_MAX_CHARS] + \
                            f"\n... [截断: 原始 {truncated_len} 字符]"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })
            else:
                # 无 tool_calls，返回文本
                final = response.content or ""
                logger.info(f"[{self.name}] 完成, 输出长度: {len(final)}")
                return final

        # 超过最大轮次
        logger.warning(f"[{self.name}] 达到最大轮次限制 ({self.max_turns})")
        # 返回最后一次 assistant 的内容
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return ""
