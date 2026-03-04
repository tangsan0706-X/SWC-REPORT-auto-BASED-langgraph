"""稀疏向量索引 — BGE-M3 lexical_weights 轻量检索。

使用 pickle 持久化到磁盘。
提供 add / search / save / load 接口。
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SparseIndex:
    """内存中的稀疏向量索引，支持 pickle 持久化。"""

    def __init__(self, index_path: str | Path | None = None):
        self.index_path = Path(index_path) if index_path else None
        # doc_id → {"sparse_vec": dict, "metadata": dict, "text": str}
        self._store: dict[str, dict[str, Any]] = {}
        if self.index_path and self.index_path.exists():
            self.load()

    def add(self, doc_id: str, sparse_vec: dict[str, float],
            metadata: dict | None = None, text: str = "") -> None:
        """添加一条文档的稀疏向量。

        Args:
            doc_id: 文档唯一 ID。
            sparse_vec: {token_id_str: weight, ...} 或 {token: weight, ...}。
            metadata: 附加元数据。
            text: 原始文本 (用于返回结果)。
        """
        self._store[doc_id] = {
            "sparse_vec": sparse_vec,
            "metadata": metadata or {},
            "text": text,
        }

    def add_batch(self, doc_ids: list[str],
                  sparse_vecs: list[dict[str, float]],
                  metadatas: list[dict] | None = None,
                  texts: list[str] | None = None) -> None:
        """批量添加。"""
        metadatas = metadatas or [{} for _ in doc_ids]
        texts = texts or ["" for _ in doc_ids]
        for did, sv, meta, txt in zip(doc_ids, sparse_vecs, metadatas, texts):
            self.add(did, sv, meta, txt)

    def search(self, query_sparse: dict[str, float],
               top_k: int = 10,
               where: dict | None = None) -> list[dict[str, Any]]:
        """稀疏向量检索 (点积相似度)。

        Args:
            query_sparse: 查询的稀疏向量。
            top_k: 返回条数。
            where: 元数据过滤条件 (简单 key=value 匹配)。

        Returns:
            [{"doc_id": str, "text": str, "metadata": dict, "score": float}, ...]
        """
        if not self._store or not query_sparse:
            return []

        results: list[tuple[str, float]] = []
        for doc_id, entry in self._store.items():
            # 元数据过滤
            if where:
                meta = entry.get("metadata", {})
                if not all(meta.get(k) == v for k, v in where.items()):
                    continue

            # 计算点积
            doc_vec = entry["sparse_vec"]
            score = 0.0
            for token, weight in query_sparse.items():
                if token in doc_vec:
                    score += weight * doc_vec[token]

            if score > 0:
                results.append((doc_id, score))

        results.sort(key=lambda x: x[1], reverse=True)
        top = results[:top_k]

        return [
            {
                "doc_id": did,
                "text": self._store[did]["text"],
                "metadata": self._store[did]["metadata"],
                "score": sc,
            }
            for did, sc in top
        ]

    def save(self, path: str | Path | None = None) -> None:
        """持久化到磁盘。"""
        save_path = Path(path) if path else self.index_path
        if save_path is None:
            raise ValueError("未指定保存路径")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            pickle.dump(self._store, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("稀疏索引已保存: %s (%d 条)", save_path, len(self._store))

    def load(self, path: str | Path | None = None) -> None:
        """从磁盘加载。"""
        load_path = Path(path) if path else self.index_path
        if load_path is None or not load_path.exists():
            return
        try:
            with open(load_path, "rb") as f:
                self._store = pickle.load(f)
            logger.info("稀疏索引已加载: %s (%d 条)", load_path, len(self._store))
        except Exception as e:
            logger.warning("稀疏索引加载失败: %s", e)
            self._store = {}

    def count(self) -> int:
        return len(self._store)

    def clear(self) -> None:
        self._store.clear()
