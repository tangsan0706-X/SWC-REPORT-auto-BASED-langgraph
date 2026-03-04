"""Reciprocal Rank Fusion (RRF) — 混合检索结果融合。

score = Σ 1 / (k + rank)  , k = 60

输入: dense results + sparse results
输出: 合并去重后按 RRF score 排序的候选列表
"""

from __future__ import annotations

from typing import Any


def rrf_fuse(
    dense_results: list[dict[str, Any]],
    sparse_results: list[dict[str, Any]],
    k: int = 60,
) -> list[dict[str, Any]]:
    """RRF 融合两路检索结果。

    每个 result 需包含 "doc_id" 和 "text" 字段。

    Returns:
        合并去重后按 RRF score 降序排列的列表，附加 "rrf_score" 字段。
    """
    scores: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}

    for rank, item in enumerate(dense_results, start=1):
        did = item.get("doc_id", item.get("text", "")[:64])
        scores[did] = scores.get(did, 0.0) + 1.0 / (k + rank)
        if did not in items:
            items[did] = item

    for rank, item in enumerate(sparse_results, start=1):
        did = item.get("doc_id", item.get("text", "")[:64])
        scores[did] = scores.get(did, 0.0) + 1.0 / (k + rank)
        if did not in items:
            items[did] = item

    # 按 RRF 分数降序排列
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    results = []
    for did, score in ranked:
        entry = items[did].copy()
        entry["rrf_score"] = score
        results.append(entry)

    return results
