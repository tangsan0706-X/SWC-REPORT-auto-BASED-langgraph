"""RAG 管理 — ChromaDB 查询接口 (v1 + v2 混合检索)。

负责:
  - 初始化 ChromaDB 客户端
  - search() 统一查询接口 (自动选择 v1/v2)
  - v2: BGE-M3 dense+sparse → RRF → Reranker
  - 被 tools 模块调用
"""

from __future__ import annotations

import logging
import platform
from typing import Any

import chromadb
from src.settings import (
    CHROMADB_DIR, RAG_TOP_K, EMBEDDING_MODEL,
    RAG_DENSE_TOP_K, RAG_SPARSE_TOP_K, RAG_RERANK_TOP_K,
    RAG_COLLECTION_V2, EMBEDDING_MODEL_V2, EMBEDDING_DEVICE,
    SPARSE_INDEX_PATH,
)

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None
_collection = None

_EF_NOT_INIT = object()  # 哨兵: 区分"未初始化"和"初始化结果为 None"
_ef = _EF_NOT_INIT

COLLECTION_NAME = "swc_corpus"

# ── v2 全局状态 ──────────────────────────────────────────
_bge_m3_model = None
_bge_m3_init_attempted = False
_collection_v2 = None
_sparse_idx = None


# ═══════════════════════════════════════════════════════════
# v1 Embedding (保留兼容)
# ═══════════════════════════════════════════════════════════

def _ollama_embed(texts: list[str]) -> list[list[float]]:
    """直接调用 Ollama /api/embed 获取向量 (绕过 ChromaDB 的 embedding wrapper)。"""
    import requests
    from src.settings import VLLM_URL, VLLM_MODEL_NAME
    ollama_url = VLLM_URL.replace("/v1", "")  # http://localhost:11434
    resp = requests.post(
        f"{ollama_url}/api/embed",
        json={"model": VLLM_MODEL_NAME, "input": texts},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


def _get_ef():
    """获取 embedding function (延迟初始化)。

    三级回退:
      1. SentenceTransformerEmbeddingFunction (需 torch, 仅 Linux)
      2. Ollama 直接 API (Windows/Linux 均可, 需本地 Ollama)
      3. None — 放弃, 调用方需处理
    """
    global _ef
    if _ef is not _EF_NOT_INIT:
        return _ef

    # Tier 1: SentenceTransformer (仅 Linux, Windows DLL 崩溃)
    if platform.system() != "Windows":
        try:
            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )
            _ef = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
            _ef(["test"])
            logger.info("Embedding: SentenceTransformer (%s)", EMBEDDING_MODEL)
            return _ef
        except Exception as e:
            logger.debug("SentenceTransformer 不可用: %s", e)

    # Tier 2: Ollama 直接 API — 返回 "ollama" 标记, 查询时用 _ollama_embed()
    try:
        _ollama_embed(["test"])
        _ef = "ollama"
        from src.settings import VLLM_MODEL_NAME
        logger.info("Embedding: Ollama direct API (%s)", VLLM_MODEL_NAME)
        return _ef
    except Exception as e:
        logger.debug("Ollama Embedding 不可用: %s", e)

    # Tier 3: 全部失败
    _ef = None
    logger.warning("无可用 embedding function, RAG 功能不可用")
    return None


def _get_collection():
    """延迟初始化 ChromaDB 客户端和 collection (不传 embedding_function)。"""
    global _client, _collection
    if _collection is None:
        ef = _get_ef()
        if ef is None:
            raise RuntimeError("无可用 embedding function")
        _client = chromadb.PersistentClient(path=str(CHROMADB_DIR))
        if ef == "ollama":
            # Ollama 模式: 不绑定 embedding_function, 手动传 embeddings
            try:
                _collection = _client.get_collection(COLLECTION_NAME)
            except Exception:
                _collection = _client.get_or_create_collection(
                    name=COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
        else:
            # SentenceTransformer 模式
            try:
                _collection = _client.get_collection(
                    COLLECTION_NAME, embedding_function=ef)
            except Exception:
                _collection = _client.get_or_create_collection(
                    name=COLLECTION_NAME,
                    embedding_function=ef,
                    metadata={"hnsw:space": "cosine"},
                )
    return _collection


# ═══════════════════════════════════════════════════════════
# v2: BGE-M3 Embedding + Sparse
# ═══════════════════════════════════════════════════════════

def _get_bge_m3():
    """延迟初始化 BGE-M3 模型 (单例)。"""
    global _bge_m3_model, _bge_m3_init_attempted
    if _bge_m3_init_attempted:
        return _bge_m3_model

    _bge_m3_init_attempted = True
    try:
        from FlagEmbedding import BGEM3FlagModel
        _bge_m3_model = BGEM3FlagModel(
            EMBEDDING_MODEL_V2,
            device=EMBEDDING_DEVICE,
            use_fp16=True,
        )
        logger.info("BGE-M3 已加载: %s → %s", EMBEDDING_MODEL_V2, EMBEDDING_DEVICE)
    except Exception as e:
        logger.warning("BGE-M3 加载失败: %s", e)
        _bge_m3_model = None

    return _bge_m3_model


def _embed_v2(texts: list[str]) -> dict[str, Any]:
    """BGE-M3 编码, 返回 {"dense": list[list[float]], "sparse": list[dict]}。"""
    model = _get_bge_m3()
    if model is None:
        raise RuntimeError("BGE-M3 模型不可用")

    output = model.encode(
        texts,
        batch_size=32,
        max_length=512,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )

    # dense: numpy array → list
    dense_vecs = output["dense"].tolist()

    # sparse: list of dicts {token_id: weight}
    sparse_vecs = []
    for sv in output["lexical_weights"]:
        # 确保 key 是 str (pickle 兼容)
        sparse_vecs.append({str(k): float(v) for k, v in sv.items()})

    return {"dense": dense_vecs, "sparse": sparse_vecs}


def _get_collection_v2():
    """获取 v2 ChromaDB collection (1024d, cosine)。不存在则返回 None。"""
    global _collection_v2, _client
    if _collection_v2 is not None:
        return _collection_v2

    try:
        if _client is None:
            _client = chromadb.PersistentClient(path=str(CHROMADB_DIR))
        _collection_v2 = _client.get_collection(RAG_COLLECTION_V2)
        logger.info("v2 collection 已加载: %s (%d 条)",
                     RAG_COLLECTION_V2, _collection_v2.count())
        return _collection_v2
    except Exception:
        # collection 不存在 → 尚未构建 v2 索引
        return None


def _get_sparse_index():
    """获取稀疏索引实例 (延迟加载)。"""
    global _sparse_idx
    if _sparse_idx is not None:
        return _sparse_idx

    from src.sparse_index import SparseIndex
    _sparse_idx = SparseIndex(SPARSE_INDEX_PATH)
    return _sparse_idx


def _v2_available() -> bool:
    """检查 v2 检索链路是否可用。"""
    col = _get_collection_v2()
    if col is None or col.count() == 0:
        return False
    si = _get_sparse_index()
    if si.count() == 0:
        return False
    if _get_bge_m3() is None:
        return False
    return True


# ═══════════════════════════════════════════════════════════
# v2 检索
# ═══════════════════════════════════════════════════════════

def _search_v2(query: str, chapter_id: str | None = None,
               top_k: int = RAG_RERANK_TOP_K) -> list[str]:
    """v2 混合检索: dense(ChromaDB) + sparse → RRF → Reranker。"""
    from src.fusion import rrf_fuse
    from src.reranker import rerank

    # 1. 编码 query
    q_out = _embed_v2([query])
    q_dense = q_out["dense"][0]
    q_sparse = q_out["sparse"][0]

    # 2. 元数据过滤
    where_filter = None
    if chapter_id:
        ch_num = "".join(filter(str.isdigit, chapter_id))
        if ch_num:
            where_filter = {"chapter_id": ch_num}

    # 3. Dense 检索 (ChromaDB v2)
    col = _get_collection_v2()
    dense_results = []
    if col and col.count() > 0:
        try:
            n = min(RAG_DENSE_TOP_K, col.count())
            res = col.query(
                query_embeddings=[q_dense],
                n_results=n,
                where=where_filter if where_filter else None,
            )
            docs = res.get("documents", [[]])[0]
            ids = res.get("ids", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            for d, did, m in zip(docs, ids, metas):
                dense_results.append({
                    "doc_id": did, "text": d, "metadata": m or {},
                })
        except Exception as e:
            logger.warning("v2 dense 检索失败: %s", e)

    # 4. Sparse 检索
    si = _get_sparse_index()
    sparse_where = {"chapter_id": where_filter["chapter_id"]} if where_filter else None
    sparse_results = si.search(q_sparse, top_k=RAG_SPARSE_TOP_K, where=sparse_where)

    # 5. RRF 融合
    fused = rrf_fuse(dense_results, sparse_results)
    if not fused:
        return ["未找到相关语料 (v2)。"]

    # 6. Rerank
    reranked = rerank(query, fused[:RAG_DENSE_TOP_K + RAG_SPARSE_TOP_K], top_k=top_k)

    return [item["text"] for item in reranked] if reranked else ["未找到相关语料。"]


# ═══════════════════════════════════════════════════════════
# 统一公开接口
# ═══════════════════════════════════════════════════════════

def search(query: str, chapter_id: str | None = None,
           top_k: int = RAG_TOP_K) -> list[str]:
    """从 RAG 检索与 query 相关的文本块。自动选择 v1/v2。"""
    # 优先 v2
    if _v2_available():
        try:
            return _search_v2(query, chapter_id, top_k=top_k)
        except Exception as e:
            logger.warning("v2 检索失败, 降级 v1: %s", e)

    # v1 回退
    return _search_v1(query, chapter_id, top_k)


def _search_v1(query: str, chapter_id: str | None = None,
               top_k: int = RAG_TOP_K) -> list[str]:
    """v1 检索 (Ollama 模式用 embeddings 查询, 其他用 query_texts)。"""
    col = _get_collection()

    if col.count() == 0:
        return ["RAG 语料库为空，请先运行 build_rag.py 构建语料。"]

    where_filter = None
    if chapter_id:
        ch_num = "".join(filter(str.isdigit, chapter_id))
        if ch_num:
            where_filter = {"chapter_id": ch_num}

    try:
        n = min(top_k, col.count())
        if _ef == "ollama":
            q_vec = _ollama_embed([query])
            results = col.query(
                query_embeddings=q_vec,
                n_results=n,
                where=where_filter if where_filter else None,
            )
        else:
            results = col.query(
                query_texts=[query],
                n_results=n,
                where=where_filter if where_filter else None,
            )
        docs = results.get("documents", [[]])[0]
        return docs if docs else ["未找到相关语料。"]
    except Exception as e:
        return [f"RAG 检索错误: {str(e)}"]


def add_documents(texts: list[str], metadatas: list[dict] | None = None,
                  ids: list[str] | None = None) -> None:
    """向 ChromaDB v1 collection 添加文档。"""
    col = _get_collection()
    if ids is None:
        import uuid
        ids = [str(uuid.uuid4()) for _ in texts]
    if _ef == "ollama":
        vecs = _ollama_embed(texts)
        col.add(embeddings=vecs, documents=texts, metadatas=metadatas, ids=ids)
    else:
        col.add(documents=texts, metadatas=metadatas, ids=ids)


def add_documents_v2(chunks: list[dict[str, Any]]) -> None:
    """向 v2 索引添加文档 (接受 chunker 输出)。

    Args:
        chunks: [{"text": str, "metadata": dict}, ...] — chunker.chunk_markdown() 的输出。
    """
    import uuid

    if not chunks:
        return

    texts = [c["text"] for c in chunks]
    metadatas = [c.get("metadata", {}) for c in chunks]
    ids = [str(uuid.uuid4()) for _ in chunks]

    # 1. BGE-M3 编码
    enc = _embed_v2(texts)

    # 2. Dense → ChromaDB v2
    global _client, _collection_v2
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMADB_DIR))

    if _collection_v2 is None:
        _collection_v2 = _client.get_or_create_collection(
            name=RAG_COLLECTION_V2,
            metadata={"hnsw:space": "cosine"},
        )

    # 分批写入 (ChromaDB 限制每批 ~5000)
    batch = 100
    for i in range(0, len(texts), batch):
        _collection_v2.add(
            embeddings=enc["dense"][i:i + batch],
            documents=texts[i:i + batch],
            metadatas=metadatas[i:i + batch],
            ids=ids[i:i + batch],
        )

    # 3. Sparse → SparseIndex
    si = _get_sparse_index()
    si.add_batch(ids, enc["sparse"], metadatas, texts)
    si.save()

    logger.info("v2 索引新增 %d 条 (dense + sparse)", len(chunks))


def get_count() -> int:
    """返回语料库中的文档数量 (优先 v2)。"""
    v2 = _get_collection_v2()
    if v2 is not None and v2.count() > 0:
        return v2.count()
    col = _get_collection()
    return col.count()


def get_count_v2() -> int:
    """仅返回 v2 collection 文档数量。"""
    v2 = _get_collection_v2()
    return v2.count() if v2 else 0
