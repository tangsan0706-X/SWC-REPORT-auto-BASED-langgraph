"""重排序器 — BGE-Reranker-v2-m3 封装。

单例模式加载到指定 GPU，提供 rerank() 接口。
模型不可用时降级为直接返回输入前 top_k。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_reranker = None
_init_attempted = False


def _get_reranker():
    """延迟初始化单例 reranker。"""
    global _reranker, _init_attempted
    if _init_attempted:
        return _reranker

    _init_attempted = True
    try:
        from FlagEmbedding import FlagReranker
        from src.settings import RERANKER_MODEL, RERANKER_DEVICE

        _reranker = FlagReranker(
            RERANKER_MODEL,
            device=RERANKER_DEVICE,
            use_fp16=True,
        )
        logger.info("Reranker 已加载: %s → %s", RERANKER_MODEL, RERANKER_DEVICE)
    except Exception as e:
        logger.warning("Reranker 加载失败, 将降级: %s", e)
        _reranker = None

    return _reranker


def rerank(
    query: str,
    passages: list[dict[str, Any]],
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """对候选段落重排序。

    Args:
        query: 查询文本。
        passages: [{"text": str, "metadata": dict, ...}, ...]
        top_k: 返回前 top_k 个。

    Returns:
        重排序后的前 top_k 个 passage，附加 "rerank_score" 字段。
    """
    if not passages:
        return []

    ranker = _get_reranker()
    if ranker is None:
        # 降级: 直接返回前 top_k
        for p in passages[:top_k]:
            p["rerank_score"] = 0.0
        return passages[:top_k]

    pairs = [[query, p["text"]] for p in passages]
    try:
        scores = ranker.compute_score(pairs, normalize=True)
        # compute_score 可能返回单个 float 或 list
        if isinstance(scores, (int, float)):
            scores = [scores]
    except Exception as e:
        logger.warning("Reranker 推理失败, 降级: %s", e)
        for p in passages[:top_k]:
            p["rerank_score"] = 0.0
        return passages[:top_k]

    for p, s in zip(passages, scores):
        p["rerank_score"] = float(s)

    ranked = sorted(passages, key=lambda x: x["rerank_score"], reverse=True)
    return ranked[:top_k]
