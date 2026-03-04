#!/usr/bin/env python3
"""PDF → ChromaDB 语料构建脚本 (v1 + v2)。

用法:
    python scripts/build_rag.py            # 自动构建 v2 (降级 v1 如不可用)
    python scripts/build_rag.py --v2       # 仅构建 v2 索引
    python scripts/build_rag.py --legacy   # 仅构建 v1 索引

v2 流程:
    1. MinerU (magic-pdf) PDF→Markdown (不可用时降级 pdfplumber)
    2. 结构化分块 (src/chunker.py)
    3. BGE-M3 编码 → dense (ChromaDB v2) + sparse (pickle)
    4. 增量索引: 跳过未变化文件

v1 流程 (保留):
    1. pdfplumber 提取文本 + OCR 回退
    2. 固定 500 字符切分
    3. SentenceTransformer → ChromaDB v1
"""

import sys
import os
import re
import uuid
import hashlib
import json

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pdfplumber
from src.settings import (
    CORPUS_DIR, CHROMADB_DIR, DATA_DIR,
    RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP,
    RAG_V2_CHUNK_SIZE, RAG_V2_CHUNK_OVERLAP,
)


# ═══════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════

# 章节标题模式
CHAPTER_PATTERN = re.compile(
    r"^第[一二三四五六七八九十]+章|^\d+[\.\s]|^[一二三四五六七八九十]+[、.]"
)

# 文件 hash 缓存路径
HASH_CACHE_PATH = DATA_DIR / "rag_file_hashes.json"


def _file_hash(path: str) -> str:
    """计算文件 SHA256。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_hash_cache() -> dict:
    """加载文件 hash 缓存。"""
    if HASH_CACHE_PATH.exists():
        try:
            with open(HASH_CACHE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_hash_cache(cache: dict) -> None:
    """保存文件 hash 缓存。"""
    HASH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HASH_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def _detect_chapter(text: str) -> str | None:
    """从文本行检测章节编号。"""
    chapter_map = {
        "一": "1", "二": "2", "三": "3", "四": "4",
        "五": "5", "六": "6", "七": "7", "八": "8",
    }
    match = re.match(r"第([一二三四五六七八九十]+)章", text.strip())
    if match:
        return chapter_map.get(match.group(1), "0")
    match = re.match(r"^(\d+)[\.\s]", text.strip())
    if match:
        return match.group(1)
    return None


# ═══════════════════════════════════════════════════════════
# v1 构建 (保留)
# ═══════════════════════════════════════════════════════════

def _chunk_text(text: str, chunk_size: int = RAG_CHUNK_SIZE,
                overlap: int = RAG_CHUNK_OVERLAP) -> list[str]:
    """将长文本切分为固定大小的块。"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap
    return chunks


def _ocr_pdf(pdf_path: str) -> str:
    """OCR 回退: 当 pdfplumber 提取不到文本时，用 PaddleOCR 识别扫描件。"""
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        print("    [警告] PaddleOCR 未安装, 跳过 OCR")
        print("    安装: pip install paddleocr paddlepaddle-gpu -i https://pypi.tuna.tsinghua.edu.cn/simple")
        return ""

    # use_gpu=True 在 A800 上加速; 无 GPU 时自动降级 CPU
    ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    full_text = ""

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            try:
                img = page.to_image(resolution=300).original  # PIL Image
                result = ocr.ocr(np.array(img), cls=True)
                if result and result[0]:
                    page_lines = [line[1][0] for line in result[0]]
                    full_text += "\n".join(page_lines) + "\n"
            except Exception as e:
                print(f"    OCR 页 {i+1} 失败: {e}")
            if (i + 1) % 10 == 0 or i + 1 == total:
                print(f"      OCR 进度: {i+1}/{total}")

    return full_text


def process_pdf_v1(pdf_path: str, source_name: str) -> list[tuple[str, dict]]:
    """v1: 处理单个 PDF 文件，返回 [(text, metadata), ...]。"""
    print(f"  [v1] 处理: {source_name}")
    results = []
    current_chapter = "0"

    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"

        if not full_text.strip():
            print(f"    pdfplumber 未提取到文本, 尝试 OCR...")
            full_text = _ocr_pdf(pdf_path)
            if not full_text.strip():
                print(f"    OCR 也未提取到文本, 跳过")
                return results
            print(f"    OCR 成功: {len(full_text)} 字符")

        paragraphs = full_text.split("\n")
        current_section = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            ch = _detect_chapter(para)
            if ch:
                if current_section.strip():
                    chunks = _chunk_text(current_section)
                    for chunk in chunks:
                        results.append((chunk, {
                            "chapter_id": current_chapter,
                            "source_file": source_name,
                            "project_type": "房地产",
                        }))
                current_section = ""
                current_chapter = ch

            current_section += para + "\n"

        if current_section.strip():
            chunks = _chunk_text(current_section)
            for chunk in chunks:
                results.append((chunk, {
                    "chapter_id": current_chapter,
                    "source_file": source_name,
                    "project_type": "房地产",
                }))

    except Exception as e:
        print(f"    错误: {e}")

    print(f"    提取 {len(results)} 个文本块")
    return results


def build_v1(pdf_files: list[tuple[str, str]]) -> None:
    """构建 v1 索引。"""
    from src.rag import add_documents, get_count, COLLECTION_NAME

    print("\n" + "=" * 60)
    print("构建 v1 索引 (SentenceTransformer + ChromaDB)")
    print("=" * 60)

    all_docs = []
    for filename, source_name in pdf_files:
        pdf_path = CORPUS_DIR / filename
        if pdf_path.exists():
            docs = process_pdf_v1(str(pdf_path), source_name)
            all_docs.extend(docs)
        else:
            print(f"  跳过: {filename} (文件不存在)")

    if not all_docs:
        print("未提取到任何文档，退出。")
        return

    print(f"\n写入 ChromaDB v1 ({len(all_docs)} 个文本块)...")
    texts = [d[0] for d in all_docs]
    metadatas = [d[1] for d in all_docs]
    ids = [str(uuid.uuid4()) for _ in all_docs]

    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i + batch_size]
        batch_metas = metadatas[i:i + batch_size]
        batch_ids = ids[i:i + batch_size]
        add_documents(batch_texts, batch_metas, batch_ids)
        print(f"  已写入 {min(i + batch_size, len(texts))}/{len(texts)}")

    print(f"\nv1 完成! ChromaDB 中共 {get_count()} 条记录。")


# ═══════════════════════════════════════════════════════════
# v2 构建 — MinerU + 结构化分块 + BGE-M3
# ═══════════════════════════════════════════════════════════

def _pdf_to_markdown_mineru(pdf_path: str, output_dir: str) -> str | None:
    """用 MinerU (magic-pdf) 将 PDF 转为 Markdown。

    Returns:
        Markdown 文本, 不可用时返回 None。
    """
    try:
        from magic_pdf.pipe.UNIPipe import UNIPipe
        from magic_pdf.rw.DiskReaderWriter import DiskReaderWriter

        os.makedirs(output_dir, exist_ok=True)

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        # UNIPipe 解析
        image_writer = DiskReaderWriter(output_dir)
        pipe = UNIPipe(pdf_bytes, [], image_writer)
        pipe.pipe_classify()
        pipe.pipe_analyze()
        pipe.pipe_parse()

        md_content = pipe.pipe_mk_markdown(output_dir, drop_mode="none")
        if md_content and len(md_content.strip()) > 50:
            print(f"    MinerU 转换成功: {len(md_content)} 字符")
            return md_content

    except ImportError:
        pass
    except Exception as e:
        print(f"    MinerU 转换失败: {e}")

    # 尝试命令行方式
    try:
        import subprocess
        result = subprocess.run(
            ["magic-pdf", "-p", pdf_path, "-o", output_dir, "-m", "auto"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            # 查找生成的 md 文件
            import glob
            md_files = glob.glob(os.path.join(output_dir, "**/*.md"), recursive=True)
            if md_files:
                with open(md_files[0], "r", encoding="utf-8") as f:
                    md_content = f.read()
                if md_content.strip():
                    print(f"    MinerU CLI 转换成功: {len(md_content)} 字符")
                    return md_content
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception as e:
        print(f"    MinerU CLI 失败: {e}")

    return None


def _pdf_to_markdown_fallback(pdf_path: str) -> str:
    """pdfplumber 降级: PDF → 纯文本 (伪 Markdown 格式)。"""
    full_text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n\n"
    except Exception as e:
        print(f"    pdfplumber 失败: {e}")

    if not full_text.strip():
        full_text = _ocr_pdf(pdf_path)

    return full_text


def process_pdf_v2(pdf_path: str, source_name: str,
                   mineru_output_dir: str) -> list[dict]:
    """v2: PDF → Markdown → 结构化分块。

    Returns:
        chunker 格式: [{"text": str, "metadata": dict}, ...]
    """
    from src.chunker import chunk_markdown

    print(f"  [v2] 处理: {source_name}")

    # Step 1: MinerU 转换, 不可用则降级
    md_text = _pdf_to_markdown_mineru(
        pdf_path,
        os.path.join(mineru_output_dir, source_name),
    )
    if md_text is None:
        print(f"    MinerU 不可用, 降级 pdfplumber")
        md_text = _pdf_to_markdown_fallback(pdf_path)

    if not md_text.strip():
        print(f"    无法提取文本, 跳过")
        return []

    # Step 2: 结构化分块
    base_metadata = {
        "source_file": source_name,
        "project_type": "房地产",
    }

    # 尝试检测章节
    chapter_id = "0"
    ch = _detect_chapter(md_text[:200])
    if ch:
        chapter_id = ch
    base_metadata["chapter_id"] = chapter_id

    from src.settings import RAG_V2_CHUNK_SIZE, RAG_V2_CHUNK_OVERLAP
    chunks = chunk_markdown(
        md_text,
        metadata=base_metadata,
        max_size=RAG_V2_CHUNK_SIZE,
        overlap=RAG_V2_CHUNK_OVERLAP,
    )

    # 按章节检测更新每个 chunk 的 chapter_id
    current_chapter = chapter_id
    for c in chunks:
        heading = c["metadata"].get("heading", "")
        detected = _detect_chapter(heading) if heading else None
        if detected:
            current_chapter = detected
        c["metadata"]["chapter_id"] = current_chapter

    print(f"    结构化分块: {len(chunks)} 个 chunk")
    return chunks


def build_v2(pdf_files: list[tuple[str, str]]) -> None:
    """构建 v2 索引 (BGE-M3 dense + sparse)。"""
    from src.rag import add_documents_v2, get_count_v2

    print("\n" + "=" * 60)
    print("构建 v2 索引 (BGE-M3 + 结构化分块 + 稀疏索引)")
    print("=" * 60)

    # 增量索引: 检查文件 hash
    hash_cache = _load_hash_cache()
    mineru_dir = str(DATA_DIR / "mineru_output")
    os.makedirs(mineru_dir, exist_ok=True)

    all_chunks = []
    updated_hashes = {}

    for filename, source_name in pdf_files:
        pdf_path = CORPUS_DIR / filename
        if not pdf_path.exists():
            print(f"  跳过: {filename} (文件不存在)")
            continue

        # 增量检查
        file_h = _file_hash(str(pdf_path))
        cache_key = f"v2:{filename}"
        if hash_cache.get(cache_key) == file_h:
            print(f"  跳过: {filename} (未变化)")
            continue

        chunks = process_pdf_v2(str(pdf_path), source_name, mineru_dir)
        all_chunks.extend(chunks)
        updated_hashes[cache_key] = file_h

    if not all_chunks:
        print("无新增文档需要索引。")
        # 仍然更新 hash 缓存
        if updated_hashes:
            hash_cache.update(updated_hashes)
            _save_hash_cache(hash_cache)
        return

    # 分批写入 v2 索引
    print(f"\n写入 v2 索引 ({len(all_chunks)} 个 chunk)...")
    batch_size = 64
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        add_documents_v2(batch)
        print(f"  已写入 {min(i + batch_size, len(all_chunks))}/{len(all_chunks)}")

    # 更新 hash 缓存
    hash_cache.update(updated_hashes)
    _save_hash_cache(hash_cache)

    print(f"\nv2 完成! 索引中共 {get_count_v2()} 条记录。")
    print(f"存储路径: {CHROMADB_DIR}")


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("水土保持方案 RAG 语料构建")
    print("=" * 60)

    # PDF 文件列表
    pdf_files = [
        ("报批稿.pdf", "报批稿"),
        ("由禾水保.pdf", "由禾水保"),
        ("金石博雅园.pdf", "金石博雅园"),
        ("标准厂房.pdf", "标准厂房"),
    ]

    # 解析命令行参数
    mode = "auto"
    if "--legacy" in sys.argv:
        mode = "v1"
    elif "--v2" in sys.argv:
        mode = "v2"

    if mode == "v1":
        build_v1(pdf_files)
    elif mode == "v2":
        build_v2(pdf_files)
    else:
        # 自动: 尝试 v2, 失败则 v1
        try:
            build_v2(pdf_files)
        except Exception as e:
            print(f"\nv2 构建失败 ({e}), 降级到 v1...")
            build_v1(pdf_files)


if __name__ == "__main__":
    main()
