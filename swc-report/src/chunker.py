"""结构化分块器 — 按 Markdown 标题 / 表格 / 段落切分。

输入: Markdown 文本 + 元数据
输出: list[{"text": str, "metadata": dict}]

规则:
  - 按 ## / ### 标题切分，保留标题作为 chunk 前缀
  - 表格整体作为独立 chunk (不拆分行)
  - 段落级完整性: 不在句子中间截断
  - 最大 chunk 800 字符, overlap 100 字符 (仅段落型 chunk)
"""

from __future__ import annotations

import re
from typing import Any


# ── 正则 ──────────────────────────────────────────────────
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|.+\|$")
_SENTENCE_END_RE = re.compile(r"[。！？；\.\!\?\;]\s*")


def chunk_markdown(
    text: str,
    metadata: dict[str, Any] | None = None,
    max_size: int = 800,
    overlap: int = 100,
) -> list[dict[str, Any]]:
    """将 Markdown 文本切分为结构化 chunk。

    Args:
        text: Markdown 文本。
        metadata: 附加到每个 chunk 的元数据 (source_file / chapter_id 等)。
        max_size: 单个 chunk 最大字符数。
        overlap: 段落型 chunk 的重叠字符数。

    Returns:
        [{"text": str, "metadata": dict}, ...]
    """
    metadata = metadata or {}
    sections = _split_by_headings(text)
    chunks: list[dict[str, Any]] = []

    for heading, body in sections:
        prefix = f"{heading}\n" if heading else ""
        blocks = _split_tables_and_paragraphs(body)

        for block_type, block_text in blocks:
            if block_type == "table":
                # 表格整体作为独立 chunk
                chunk_text = prefix + block_text.strip()
                if chunk_text:
                    chunks.append({
                        "text": chunk_text[:max_size * 2],  # 表格允许稍大
                        "metadata": {**metadata, "chunk_type": "table",
                                     "heading": heading},
                    })
            else:
                # 段落型: 按 max_size 切分, 保留句子完整性
                para_text = block_text.strip()
                if not para_text:
                    continue
                for sub in _split_paragraph(para_text, max_size, overlap):
                    chunk_text = prefix + sub
                    chunks.append({
                        "text": chunk_text,
                        "metadata": {**metadata, "chunk_type": "paragraph",
                                     "heading": heading},
                    })

    # 去空
    chunks = [c for c in chunks if c["text"].strip()]
    # 编号
    for i, c in enumerate(chunks):
        c["metadata"]["chunk_index"] = i
    return chunks


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    """按 Markdown 标题 (## / ###) 切分, 返回 [(heading, body), ...]。

    一级标题 (#) 也参与切分, 但保留其文本。
    """
    parts: list[tuple[str, str]] = []
    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        return [("", text)]

    # 标题前的内容
    pre = text[:matches[0].start()].strip()
    if pre:
        parts.append(("", pre))

    for i, m in enumerate(matches):
        heading = m.group(0).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        parts.append((heading, body))

    return parts


def _split_tables_and_paragraphs(text: str) -> list[tuple[str, str]]:
    """将文本分离为表格块和段落块。

    返回 [("table", ...), ("paragraph", ...), ...] 交替块。
    """
    lines = text.split("\n")
    blocks: list[tuple[str, str]] = []
    current_type = "paragraph"
    current_lines: list[str] = []

    for line in lines:
        is_table_line = bool(_TABLE_ROW_RE.match(line.strip()))
        # 分隔行 (|---|---|) 也属于表格
        if not is_table_line and re.match(r"^\|[\s\-:]+\|$", line.strip()):
            is_table_line = True

        line_type = "table" if is_table_line else "paragraph"

        if line_type != current_type and current_lines:
            blocks.append((current_type, "\n".join(current_lines)))
            current_lines = []
            current_type = line_type

        current_lines.append(line)

    if current_lines:
        blocks.append((current_type, "\n".join(current_lines)))

    return blocks


def _split_paragraph(text: str, max_size: int, overlap: int) -> list[str]:
    """将段落文本按 max_size 切分, 尽量在句子边界切断。"""
    if len(text) <= max_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + max_size
        if end >= len(text):
            chunk = text[start:]
            if chunk.strip():
                chunks.append(chunk.strip())
            break

        # 在 [start+max_size*0.6, start+max_size] 区间内寻找最后一个句子结束符
        search_start = start + int(max_size * 0.6)
        segment = text[search_start:end]
        last_sent = None
        for m in _SENTENCE_END_RE.finditer(segment):
            last_sent = m

        if last_sent is not None:
            cut = search_start + last_sent.end()
        else:
            # 退而求其次: 找最后一个换行
            nl_pos = text.rfind("\n", start, end)
            cut = nl_pos + 1 if nl_pos > start else end

        chunk = text[start:cut].strip()
        if chunk:
            chunks.append(chunk)
        start = max(cut - overlap, start + 1)  # 避免死循环

    return chunks
