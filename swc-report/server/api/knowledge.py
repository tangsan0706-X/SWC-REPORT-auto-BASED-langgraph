"""知识库管理 API — 配置文件 / 知识文档 / 范文语料 / LLM 生成。"""

from __future__ import annotations

import csv
import io
import json
import logging
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File

import src.settings as settings
from server.models import FileInfo, GenerateStatus, ReindexStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# ── 白名单配置文件 ──────────────────────────────────────────
CONFIG_FILES: dict[str, str] = {
    "measure_library": "measure_library.json",
    "legal_refs": "legal_refs.json",
    "fee_rate_config": "fee_rate_config.json",
    "soil_map": "soil_map.json",
    "price_v2": "price_v2.csv",
}

# 允许上传到 atlas/ 的扩展名
ATLAS_ALLOWED_EXTS = {".md", ".docx", ".pdf", ".dwg", ".dxf", ".png", ".jpg", ".jpeg", ".txt"}

# ── 后台任务状态 ─────────────────────────────────────────────
_task_status: dict[str, dict] = {
    "generate": {"status": "idle", "message": "", "updated_at": ""},
    "atlas_reindex": {"status": "idle", "message": ""},
    "corpus_reindex": {"status": "idle", "message": ""},
}
_task_lock = threading.Lock()


def _file_info(path: Path) -> FileInfo:
    """构造文件信息。"""
    stat = path.stat()
    return FileInfo(
        name=path.name,
        size_kb=round(stat.st_size / 1024, 1),
        modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        file_type=path.suffix.lower(),
    )


def _safe_filename(name: str) -> str:
    """清理文件名，禁止路径遍历。"""
    cleaned = Path(name).name  # 只取文件名部分
    if not cleaned or cleaned.startswith("."):
        raise HTTPException(400, f"非法文件名: {name}")
    return cleaned


# ══════════════════════════════════════════════════════════════
# 1. 配置文件管理 (config/)
# ══════════════════════════════════════════════════════════════

@router.get("/config-files", response_model=list[FileInfo])
async def list_config_files():
    """列出白名单中的配置文件。"""
    result = []
    for key, filename in CONFIG_FILES.items():
        path = settings.CONFIG_DIR / filename
        if path.exists():
            result.append(_file_info(path))
    return result


@router.get("/config-files/{file_key}")
async def get_config_file(file_key: str):
    """读取配置文件内容。"""
    if file_key not in CONFIG_FILES:
        raise HTTPException(404, f"未知配置文件: {file_key}")
    path = settings.CONFIG_DIR / CONFIG_FILES[file_key]
    if not path.exists():
        raise HTTPException(404, f"文件不存在: {CONFIG_FILES[file_key]}")

    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return {"key": file_key, "filename": path.name, "content": json.loads(text)}
    elif path.suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        return {"key": file_key, "filename": path.name, "content": list(reader)}
    else:
        return {"key": file_key, "filename": path.name, "content": text}


@router.put("/config-files/{file_key}")
async def update_config_file(file_key: str, data: dict):
    """更新配置文件（自动备份 .bak）。"""
    if file_key not in CONFIG_FILES:
        raise HTTPException(404, f"未知配置文件: {file_key}")
    path = settings.CONFIG_DIR / CONFIG_FILES[file_key]

    # 备份
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)

    content = data.get("content")
    if content is None:
        raise HTTPException(400, "缺少 content 字段")

    if path.suffix == ".json":
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    elif path.suffix == ".csv":
        if not isinstance(content, list) or not content:
            raise HTTPException(400, "CSV 内容必须是非空数组")
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=content[0].keys())
            writer.writeheader()
            writer.writerows(content)
    else:
        path.write_text(str(content), encoding="utf-8")

    return {"ok": True, "message": f"已更新 {path.name}（备份 .bak）"}


# ══════════════════════════════════════════════════════════════
# 2. 知识文档管理 (data/atlas/)
# ══════════════════════════════════════════════════════════════

@router.get("/atlas", response_model=list[FileInfo])
async def list_atlas_files():
    """列出 atlas 目录所有文件。"""
    atlas_dir = settings.ATLAS_DIR
    if not atlas_dir.exists():
        return []
    result = []
    for f in sorted(atlas_dir.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            result.append(_file_info(f))
    return result


@router.post("/atlas/upload")
async def upload_atlas_file(file: UploadFile = File(...)):
    """上传文件到 atlas/。"""
    filename = _safe_filename(file.filename or "unknown")
    ext = Path(filename).suffix.lower()
    if ext not in ATLAS_ALLOWED_EXTS:
        raise HTTPException(400, f"不支持的文件类型: {ext}，允许: {', '.join(sorted(ATLAS_ALLOWED_EXTS))}")

    atlas_dir = settings.ATLAS_DIR
    atlas_dir.mkdir(parents=True, exist_ok=True)
    dest = atlas_dir / filename

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50MB
        raise HTTPException(400, "文件大小超过 50MB 限制")

    dest.write_bytes(content)
    return {"ok": True, "filename": filename, "size_kb": round(len(content) / 1024, 1)}


@router.delete("/atlas/{filename}")
async def delete_atlas_file(filename: str):
    """删除文件（移到 .trash/ 子目录）。"""
    filename = _safe_filename(filename)
    atlas_dir = settings.ATLAS_DIR
    src_path = atlas_dir / filename
    if not src_path.exists():
        raise HTTPException(404, f"文件不存在: {filename}")

    trash_dir = atlas_dir / ".trash"
    trash_dir.mkdir(exist_ok=True)
    dest = trash_dir / f"{filename}.{datetime.now().strftime('%Y%m%d%H%M%S')}"
    shutil.move(str(src_path), str(dest))
    return {"ok": True, "message": f"已移到回收站: {filename}"}


@router.post("/atlas/reindex", response_model=ReindexStatus)
async def reindex_atlas():
    """后台线程触发 atlas_rag 重建索引。"""
    with _task_lock:
        if _task_status["atlas_reindex"]["status"] == "running":
            raise HTTPException(409, "索引重建正在运行中")
        _task_status["atlas_reindex"] = {"status": "running", "message": "正在重建图集索引..."}

    def _run():
        try:
            from src.atlas_rag import AtlasRAG
            atlas = AtlasRAG()
            count = atlas.index_atlas(force=True)
            with _task_lock:
                _task_status["atlas_reindex"] = {
                    "status": "done",
                    "message": f"索引重建完成，共 {count} 条记录",
                }
        except Exception as e:
            logger.error(f"Atlas 索引重建失败: {e}")
            with _task_lock:
                _task_status["atlas_reindex"] = {
                    "status": "error",
                    "message": str(e),
                }

    threading.Thread(target=_run, daemon=True).start()
    return ReindexStatus(**_task_status["atlas_reindex"])


# ══════════════════════════════════════════════════════════════
# 3. 范文语料管理 (corpus/)
# ══════════════════════════════════════════════════════════════

@router.get("/corpus", response_model=list[FileInfo])
async def list_corpus_files():
    """列出 corpus 目录所有 PDF 文件。"""
    corpus_dir = settings.CORPUS_DIR
    if not corpus_dir.exists():
        return []
    result = []
    for f in sorted(corpus_dir.iterdir()):
        if f.is_file() and f.suffix.lower() == ".pdf":
            result.append(_file_info(f))
    return result


@router.post("/corpus/upload")
async def upload_corpus_file(file: UploadFile = File(...)):
    """上传 PDF 到 corpus/。"""
    filename = _safe_filename(file.filename or "unknown.pdf")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "仅支持 PDF 文件")

    corpus_dir = settings.CORPUS_DIR
    corpus_dir.mkdir(parents=True, exist_ok=True)
    dest = corpus_dir / filename

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50MB
        raise HTTPException(400, "文件大小超过 50MB 限制")

    dest.write_bytes(content)
    return {"ok": True, "filename": filename, "size_kb": round(len(content) / 1024, 1)}


@router.delete("/corpus/{filename}")
async def delete_corpus_file(filename: str):
    """删除 PDF（移到 .trash/）。"""
    filename = _safe_filename(filename)
    corpus_dir = settings.CORPUS_DIR
    src_path = corpus_dir / filename
    if not src_path.exists():
        raise HTTPException(404, f"文件不存在: {filename}")

    trash_dir = corpus_dir / ".trash"
    trash_dir.mkdir(exist_ok=True)
    dest = trash_dir / f"{filename}.{datetime.now().strftime('%Y%m%d%H%M%S')}"
    shutil.move(str(src_path), str(dest))
    return {"ok": True, "message": f"已移到回收站: {filename}"}


@router.post("/corpus/reindex", response_model=ReindexStatus)
async def reindex_corpus():
    """后台线程触发 corpus RAG 重建索引。"""
    with _task_lock:
        if _task_status["corpus_reindex"]["status"] == "running":
            raise HTTPException(409, "索引重建正在运行中")
        _task_status["corpus_reindex"] = {"status": "running", "message": "正在重建范文语料索引..."}

    def _run():
        try:
            import uuid
            from src.settings import CORPUS_DIR, CHROMADB_DIR
            from src.rag import add_documents, get_count
            from src.atlas_rag import AtlasRAG

            # 重用 AtlasRAG 的 PDF 解析能力
            atlas = AtlasRAG()
            all_texts = []
            all_metas = []

            for pdf_path in sorted(CORPUS_DIR.glob("*.pdf")):
                try:
                    text = atlas._extract_pdf_text(pdf_path)
                    if not text or len(text.strip()) < 20:
                        continue
                    chunks = atlas._chunk_text(text, source_name=pdf_path.stem)
                    for chunk in chunks:
                        all_texts.append(chunk["text"])
                        all_metas.append({
                            "source_file": pdf_path.name,
                            "chapter_id": "0",
                        })
                except Exception as e:
                    logger.warning(f"PDF 处理失败: {pdf_path.name} — {e}")

            if all_texts:
                # 分批写入
                batch_size = 100
                ids = [str(uuid.uuid4()) for _ in all_texts]
                for i in range(0, len(all_texts), batch_size):
                    add_documents(
                        all_texts[i:i + batch_size],
                        all_metas[i:i + batch_size],
                        ids[i:i + batch_size],
                    )

            total = get_count()
            with _task_lock:
                _task_status["corpus_reindex"] = {
                    "status": "done",
                    "message": f"语料索引完成，共 {total} 条记录",
                }
        except Exception as e:
            logger.error(f"Corpus 索引重建失败: {e}")
            with _task_lock:
                _task_status["corpus_reindex"] = {
                    "status": "error",
                    "message": str(e),
                }

    threading.Thread(target=_run, daemon=True).start()
    return ReindexStatus(**_task_status["corpus_reindex"])


# ══════════════════════════════════════════════════════════════
# 4. LLM 生成 measure_library.json
# ══════════════════════════════════════════════════════════════

GENERATE_SYSTEM_PROMPT = """你是水土保持专家。请根据以下知识库材料，生成标准措施库 JSON。

要求格式:
{
  "measures": [
    {
      "id": "ENG-001",
      "name": "挡土墙",
      "type": "工程措施|植物措施|临时措施",
      "applicable_zones": ["建(构)筑物区"],
      "unit": "m³",
      "quantity_coefficient": {"method": "area_ratio", "factor": 0.1},
      "priority": "高|中|低",
      "price_ref": 150,
      "description": "..."
    }
  ],
  "zone_minimum_requirements": {
    "建(构)筑物区": {"min_measures": 3, "required_types": ["工程措施", "植物措施"]},
    "道路广场区": {"min_measures": 2, "required_types": ["工程措施", "临时措施"]},
    "绿化区": {"min_measures": 2, "required_types": ["植物措施"]},
    "临时堆土区": {"min_measures": 2, "required_types": ["临时措施", "植物措施"]}
  }
}

请确保:
1. 每种措施有唯一 id (ENG-xxx 工程/PLT-xxx 植物/TMP-xxx 临时)
2. applicable_zones 覆盖常见分区
3. price_ref 为合理的单价参考值（元）
4. 至少包含 25 种常见措施

只输出 JSON，不要输出其他内容。"""


@router.post("/generate/measure-library")
async def generate_measure_library():
    """后台线程执行 LLM 生成 measure_library.json。"""
    with _task_lock:
        if _task_status["generate"]["status"] == "running":
            raise HTTPException(409, "生成任务正在运行中")
        now = datetime.now(timezone.utc).isoformat()
        _task_status["generate"] = {"status": "running", "message": "正在生成...", "updated_at": now}

    def _run():
        try:
            # 1. 备份
            lib_path = settings.MEASURE_LIBRARY_PATH
            if lib_path.exists():
                bak = lib_path.with_suffix(".json.bak")
                shutil.copy2(lib_path, bak)

            # 2. 收集知识库文本
            knowledge_texts = []

            # atlas 文本文件
            atlas_dir = settings.ATLAS_DIR
            if atlas_dir.exists():
                for f in sorted(atlas_dir.iterdir()):
                    ext = f.suffix.lower()
                    if ext == ".md" or ext == ".txt":
                        try:
                            text = f.read_text(encoding="utf-8")
                            if len(text) > 5000:
                                text = text[:5000] + "\n... (截断)"
                            knowledge_texts.append(f"## {f.name}\n{text}")
                        except Exception:
                            pass
                    elif ext == ".docx":
                        try:
                            from src.atlas_rag import AtlasRAG
                            text = AtlasRAG._extract_docx_text(f)
                            if text:
                                if len(text) > 5000:
                                    text = text[:5000] + "\n... (截断)"
                                knowledge_texts.append(f"## {f.name}\n{text}")
                        except Exception:
                            pass

            # 3. 法规引用
            legal_summary = ""
            if settings.LEGAL_REFS_PATH.exists():
                try:
                    legal_data = json.loads(settings.LEGAL_REFS_PATH.read_text(encoding="utf-8"))
                    legal_summary = json.dumps(legal_data, ensure_ascii=False, indent=2)
                    if len(legal_summary) > 3000:
                        legal_summary = legal_summary[:3000] + "\n... (截断)"
                except Exception:
                    pass

            # 4. 构造 prompt
            user_content = "知识库材料:\n" + "\n\n".join(knowledge_texts) if knowledge_texts else "（无知识库材料）"
            if legal_summary:
                user_content += f"\n\n法规引用:\n{legal_summary}"

            # 5. 调用 LLM
            from src.agents.base import LLMClient
            client = LLMClient()
            response = client.chat(
                messages=[
                    {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=8192,
                temperature=0.2,
            )

            # 6. 解析 JSON
            text = response.content or ""
            # 尝试提取 JSON
            import re
            json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 直接尝试整个输出
                json_str = text

            result = json.loads(json_str)

            # 7. 基本校验
            if "measures" not in result:
                raise ValueError("生成的 JSON 缺少 measures 字段")
            if not isinstance(result["measures"], list) or len(result["measures"]) < 5:
                raise ValueError(f"measures 数量不足: {len(result.get('measures', []))}")

            # 8. 写入
            lib_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

            now = datetime.now(timezone.utc).isoformat()
            with _task_lock:
                _task_status["generate"] = {
                    "status": "done",
                    "message": f"已生成 {len(result['measures'])} 种措施并覆盖写入",
                    "updated_at": now,
                }
        except json.JSONDecodeError as e:
            now = datetime.now(timezone.utc).isoformat()
            with _task_lock:
                _task_status["generate"] = {
                    "status": "error",
                    "message": f"LLM 输出不是有效 JSON: {e}",
                    "updated_at": now,
                }
        except Exception as e:
            logger.error(f"LLM 生成措施库失败: {e}")
            now = datetime.now(timezone.utc).isoformat()
            with _task_lock:
                _task_status["generate"] = {
                    "status": "error",
                    "message": str(e),
                    "updated_at": now,
                }

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "message": "生成任务已启动"}


@router.get("/generate/status", response_model=GenerateStatus)
async def get_generate_status():
    """查询后台生成任务状态。"""
    with _task_lock:
        return GenerateStatus(**_task_status["generate"])


# ── 重建索引状态查询 ─────────────────────────────────────────

@router.get("/atlas/reindex/status", response_model=ReindexStatus)
async def get_atlas_reindex_status():
    """查询 atlas 索引重建状态。"""
    with _task_lock:
        return ReindexStatus(**_task_status["atlas_reindex"])


@router.get("/corpus/reindex/status", response_model=ReindexStatus)
async def get_corpus_reindex_status():
    """查询 corpus 索引重建状态。"""
    with _task_lock:
        return ReindexStatus(**_task_status["corpus_reindex"])
