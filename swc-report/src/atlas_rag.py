"""图集库学习模块 — 标准图集 RAG 索引与查询。

功能:
  - 扫描 data/atlas/ 目录中的标准图集图片 (PNG/JPG/PDF)
  - 解析文本标准文件 (.md/.docx/.pdf) 分块索引
  - 使用 VL 模型提取绘图规范 (图例样式/标注格式/措施表示方法)
  - 存入 ChromaDB collection "atlas_conventions"
  - 按措施类型/图表类型查询绘图规范
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AtlasRAG:
    """标准图集 RAG — 索引和查询绘图规范。"""

    COLLECTION_NAME = "atlas_conventions"

    # VL 分析图集用的 prompt
    VL_ATLAS_PROMPT = """请详细分析这张水土保持措施图/标准图集，提取以下绘图规范信息：

1. **图例样式**: 每种措施用什么颜色、线型、填充、符号表示
2. **标注格式**: 尺寸标注的字体大小、箭头样式、单位
3. **颜色规范**: 不同分区/措施类型的配色方案
4. **比例尺**: 图纸比例和比例尺的表示方式
5. **措施表示方法**: 排水沟/挡墙/绿化等在图上如何表示
6. **布局规范**: 图框、标题栏、图例位置
7. **断面图规范**: 如有断面图，描述绘制方法

请用以下 JSON 格式输出 (只输出 JSON):
{
  "map_type": "措施总体布置图/分区详图/典型断面图",
  "legend_styles": [{"measure": "排水沟", "representation": "蓝色实线", "color": "#1E88E5"}],
  "annotation_format": {"font_size": "3.5mm", "arrow_style": "实心箭头"},
  "color_scheme": {"分区底色": "浅色填充", "措施线条": "深色"},
  "scale": "1:500",
  "section_conventions": {"wall_hatch": "斜线填充", "concrete_hatch": "点阵"},
  "layout_rules": {"legend_position": "右下角", "north_arrow": "左上角"},
  "notes": "其他绘图规范说明"
}"""

    def __init__(self, atlas_dir: Path | None = None, db_dir: Path | None = None):
        from src.settings import DATA_DIR
        self.atlas_dir = atlas_dir or (DATA_DIR / "atlas")
        self.db_dir = db_dir or (DATA_DIR / "atlas_db")
        self._collection = None
        self._use_v2 = False
        self._use_ollama = False

    def _get_collection(self):
        """延迟初始化 ChromaDB collection。

        优先使用 BGE-M3 (v2), 不可用时回退到 v1 embedding。
        """
        if self._collection is not None:
            return self._collection

        try:
            import chromadb
            self.db_dir.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(self.db_dir))

            # 优先 v2 (无需 embedding_function, 手动传 embeddings)
            try:
                from src.rag import _get_bge_m3
                if _get_bge_m3() is not None:
                    self._use_v2 = True
                    self._collection = client.get_or_create_collection(
                        name=self.COLLECTION_NAME,
                        metadata={"hnsw:space": "cosine"},
                    )
                    logger.info("图集 RAG: 使用 BGE-M3 (v2)")
                    return self._collection
            except Exception:
                pass

            # 回退 v1
            from src.rag import _get_ef
            ef = _get_ef()
            if ef is None:
                logger.warning("无可用 embedding function，图集 RAG 不可用")
                return None

            self._use_v2 = False
            if ef == "ollama":
                # Ollama 直接 API: 不绑定 embedding_function, 手动传 embeddings
                self._use_ollama = True
                self._collection = client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
            else:
                self._use_ollama = False
                self._collection = client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    embedding_function=ef,
                    metadata={"hnsw:space": "cosine"},
                )
            return self._collection
        except Exception as e:
            logger.error(f"图集 ChromaDB 初始化失败: {e}")
            return None

    def _col_add(self, col, documents, metadatas, ids):
        """向 collection 添加文档 (Ollama 模式手动传 embeddings)。"""
        if self._use_ollama or self._use_v2:
            from src.rag import _ollama_embed
            vecs = _ollama_embed(documents)
            col.add(embeddings=vecs, documents=documents, metadatas=metadatas, ids=ids)
        else:
            col.add(documents=documents, metadatas=metadatas, ids=ids)

    def _col_query(self, col, query_text, n_results, where=None):
        """查询 collection (Ollama 模式用 embeddings)。"""
        if self._use_ollama or self._use_v2:
            from src.rag import _ollama_embed
            q_vec = _ollama_embed([query_text])
            return col.query(query_embeddings=q_vec, n_results=n_results, where=where)
        return col.query(query_texts=[query_text], n_results=n_results, where=where)

    # ── 索引 ────────────────────────────────────────────────────

    def index_atlas(self, force: bool = False) -> int:
        """扫描 atlas_dir，索引图片(VL分析) + 文本文件(md/docx/pdf)，存入 ChromaDB。

        Args:
            force: True 则清空已有索引重建。

        Returns:
            新增文档数。
        """
        col = self._get_collection()
        if col is None:
            logger.warning("ChromaDB 不可用，跳过图集索引")
            return 0

        if not self.atlas_dir.exists():
            logger.info(f"图集目录不存在，跳过: {self.atlas_dir}")
            return 0

        # 已索引数量
        existing_count = col.count()
        if existing_count > 0 and not force:
            logger.info(f"图集已索引 ({existing_count} 条)，跳过。如需重建请传 force=True")
            return 0

        if force and existing_count > 0:
            # 清空重建
            col.delete(where={"source": "atlas"})

        # 分类扫描
        image_exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
        text_exts = {".md", ".txt"}
        docx_exts = {".docx"}
        pdf_exts = {".pdf"}
        cad_exts = {".dwg", ".dxf"}

        image_files, text_files, cad_files = [], [], []
        for f in sorted(self.atlas_dir.rglob("*")):
            ext = f.suffix.lower()
            if ext in image_exts:
                image_files.append(f)
            elif ext in text_exts | docx_exts | pdf_exts:
                text_files.append(f)
            elif ext in cad_exts:
                cad_files.append(f)

        total = len(image_files) + len(text_files) + len(cad_files)
        if total == 0:
            logger.info("图集目录为空，无文件可索引")
            return 0

        logger.info(f"开始索引图集: {len(image_files)} 图片 + {len(text_files)} 文本 + {len(cad_files)} CAD")

        added = 0

        # 1. 文本标准文件索引 (md/docx/pdf → 分块)
        for file_path in text_files:
            try:
                chunks = self._index_text_file(file_path)
                for chunk in chunks:
                    self._col_add(col,
                        documents=[chunk["text"]],
                        metadatas=[{
                            "source": "atlas",
                            "file_name": file_path.name,
                            "map_type": chunk.get("section", "制图标准"),
                            "chunk_index": chunk.get("index", 0),
                            "purpose": chunk.get("purpose", "其他"),
                        }],
                        ids=[str(uuid.uuid4())],
                    )
                    added += 1
                logger.info(f"  文本索引: {file_path.name} → {len(chunks)} 块")
            except Exception as e:
                logger.warning(f"  文本索引失败: {file_path.name} — {e}")

        # 2. 图片文件索引 (VL 分析)
        for file_path in image_files:
            try:
                convention = self._analyze_atlas_image(file_path)
                if convention:
                    doc_text = json.dumps(convention, ensure_ascii=False)
                    self._col_add(col,
                        documents=[doc_text],
                        metadatas=[{
                            "source": "atlas",
                            "file_name": file_path.name,
                            "map_type": convention.get("map_type", ""),
                        }],
                        ids=[str(uuid.uuid4())],
                    )
                    added += 1
                    logger.info(f"  图片索引: {file_path.name}")
            except Exception as e:
                logger.warning(f"  图片索引失败: {file_path.name} — {e}")

        # 3. CAD 文件 (DWG/DXF → 转 PNG → VL 分析)
        for file_path in cad_files:
            try:
                png = self._convert_cad_for_indexing(file_path)
                if png and png.exists():
                    convention = self._analyze_atlas_image(png)
                    if convention:
                        convention["cad_source"] = file_path.name
                        doc_text = json.dumps(convention, ensure_ascii=False)
                        self._col_add(col,
                            documents=[doc_text],
                            metadatas=[{
                                "source": "atlas",
                                "file_name": file_path.name,
                                "map_type": convention.get("map_type", "CAD图纸"),
                                "purpose": "制图标准",
                            }],
                            ids=[str(uuid.uuid4())],
                        )
                        added += 1
                        logger.info(f"  CAD索引: {file_path.name}")
                else:
                    # 无法转换，仅记录元数据
                    self._col_add(col,
                        documents=[json.dumps({
                            "map_type": "CAD设计图",
                            "file_name": file_path.name,
                            "notes": f"CAD 图纸: {file_path.stem}，包含水土保持措施典型设计",
                        }, ensure_ascii=False)],
                        metadatas=[{
                            "source": "atlas",
                            "file_name": file_path.name,
                            "map_type": "CAD设计图",
                            "purpose": "制图标准",
                        }],
                        ids=[str(uuid.uuid4())],
                    )
                    added += 1
                    logger.info(f"  CAD元数据: {file_path.name} (无法转换图片)")
            except Exception as e:
                logger.warning(f"  CAD索引失败: {file_path.name} — {e}")

        logger.info(f"图集索引完成: 新增 {added} 条")
        return added

    def _convert_cad_for_indexing(self, cad_path: Path) -> Path | None:
        """将 CAD 文件转为 PNG，用于 VL 分析。"""
        try:
            from src.spatial_analyzer import convert_cad_to_png
            png_dir = self.db_dir / "cad_png"
            png_dir.mkdir(parents=True, exist_ok=True)
            return convert_cad_to_png(cad_path, png_dir)
        except Exception as e:
            logger.debug(f"CAD 转 PNG 失败: {e}")
            return None

    # ── 文本标准文件索引 ──────────────────────────────────────

    # 文件用途分类关键词
    _PURPOSE_KEYWORDS = {
        "制图标准": ["SL73", "制图标准", "标准化图集"],
        "技术标准": ["GB", "GBT", "DB64", "技术标准", "防治标准", "技术规范"],
        "法规条例": ["条例", "管理办法", "规划"],
        "造价规定": ["概算", "估算", "编制规定"],
        "范文": ["报批稿", "盖章", "方案汇总", "报告书", "房地产开发项目",
                 "水土保持方案", "终版"],
        "数据参考": ["数据组成"],
    }

    def _classify_file_purpose(self, file_name: str) -> str:
        """根据文件名分类文件用途。"""
        for purpose, keywords in self._PURPOSE_KEYWORDS.items():
            for kw in keywords:
                if kw in file_name:
                    return purpose
        return "其他"

    def _index_text_file(self, file_path: Path) -> list[dict]:
        """解析文本类标准文件 (md/docx/pdf)，返回分块列表。

        优先使用 v2 结构化分块器 (src/chunker.py)。
        """
        ext = file_path.suffix.lower()

        if ext == ".md" or ext == ".txt":
            text = file_path.read_text(encoding="utf-8")
        elif ext == ".docx":
            text = self._extract_docx_text(file_path)
        elif ext == ".pdf":
            text = self._extract_pdf_text(file_path)
        else:
            return []

        if not text or len(text.strip()) < 20:
            return []

        purpose = self._classify_file_purpose(file_path.name)

        # 优先 v2 结构化分块
        try:
            from src.chunker import chunk_markdown
            raw_chunks = chunk_markdown(
                text,
                metadata={"source_file": file_path.stem},
            )
            chunks = []
            for rc in raw_chunks:
                chunks.append({
                    "text": rc["text"],
                    "section": rc["metadata"].get("heading", file_path.stem),
                    "index": rc["metadata"].get("chunk_index", 0),
                    "purpose": purpose,
                })
            return chunks
        except Exception:
            pass

        # 回退: 原有分块逻辑
        chunks = self._chunk_text(text, source_name=file_path.stem)
        for chunk in chunks:
            chunk["purpose"] = purpose
        return chunks

    @staticmethod
    def _extract_docx_text(file_path: Path) -> str:
        """用 python-docx 提取 .docx 文本。"""
        try:
            from docx import Document
            doc = Document(str(file_path))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paragraphs)
        except Exception as e:
            logger.warning(f"docx 解析失败: {file_path.name} — {e}")
            return ""

    @staticmethod
    def _extract_pdf_text(file_path: Path) -> str:
        """提取 PDF 文本内容。优先 PyPDF2 (轻量)，回退 pdfplumber。

        限制: 仅解析前 50 页，避免大 PDF 导致内存问题或 segfault。
        """
        MAX_PAGES = 50

        # 优先 PyPDF2 (更稳定、更轻量)
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(file_path))
            texts = []
            for i, page in enumerate(reader.pages):
                if i >= MAX_PAGES:
                    break
                page_text = page.extract_text()
                if page_text:
                    texts.append(page_text)
            if texts:
                return "\n\n".join(texts)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"PyPDF2 解析失败: {e}")

        # 回退 pdfplumber (更强但可能 segfault)
        try:
            import pdfplumber
            texts = []
            with pdfplumber.open(str(file_path)) as pdf:
                for i, page in enumerate(pdf.pages):
                    if i >= MAX_PAGES:
                        break
                    page_text = page.extract_text()
                    if page_text:
                        texts.append(page_text)
            if texts:
                return "\n\n".join(texts)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"pdfplumber 解析失败: {e}")

        logger.warning(f"PDF 文本提取失败 (无可用解析器): {file_path.name}")
        return ""

    def _chunk_text(self, text: str, chunk_size: int = 500,
                    overlap: int = 50, source_name: str = "") -> list[dict]:
        """将文本按章节/段落分块。

        优先按 markdown 标题 (# / ##) 分块，否则按固定长度。
        """
        import re

        # 尝试按 markdown 标题分块
        sections = re.split(r'\n(?=#{1,3}\s)', text)
        chunks = []

        if len(sections) > 1:
            # 有标题结构 → 按章节分块
            for sec in sections:
                sec = sec.strip()
                if not sec:
                    continue
                # 提取章节标题
                title_match = re.match(r'(#{1,3})\s+(.*?)(?:\n|$)', sec)
                section_title = title_match.group(2).strip() if title_match else ""
                # 如果段太长，再细分
                if len(sec) > chunk_size * 2:
                    sub_chunks = self._split_by_size(sec, chunk_size, overlap)
                    for i, sc in enumerate(sub_chunks):
                        chunks.append({
                            "text": sc,
                            "section": section_title,
                            "index": len(chunks),
                        })
                else:
                    chunks.append({
                        "text": sec,
                        "section": section_title,
                        "index": len(chunks),
                    })
        else:
            # 无标题结构 → 按固定长度分块
            sub_chunks = self._split_by_size(text, chunk_size, overlap)
            for i, sc in enumerate(sub_chunks):
                chunks.append({
                    "text": sc,
                    "section": source_name,
                    "index": i,
                })

        return chunks

    @staticmethod
    def _split_by_size(text: str, chunk_size: int, overlap: int) -> list[str]:
        """按固定长度分块，带重叠。"""
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk.strip())
            start = end - overlap
        return chunks

    def _analyze_atlas_image(self, image_path: Path) -> dict | None:
        """使用 VL 模型分析单张图集图片 (仅处理图片格式)。"""
        import base64

        suffix = image_path.suffix.lower()

        # PDF 不再由此方法处理 (已在 _index_text_file 中处理)
        if suffix == ".pdf":
            return None

        try:
            from openai import OpenAI
            from src.settings import VL_URL, VL_MODEL_NAME, VL_MAX_TOKENS
        except ImportError:
            logger.warning("OpenAI 客户端不可用")
            return None

        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "tif": "image/tiff", "tiff": "image/tiff"}
        mime = mime_map.get(suffix.lstrip("."), "image/png")

        client = OpenAI(base_url=VL_URL, api_key="not-needed")
        try:
            response = client.chat.completions.create(
                model=VL_MODEL_NAME,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.VL_ATLAS_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                }],
                max_tokens=VL_MAX_TOKENS,
                temperature=0.2,
            )
            text = response.choices[0].message.content or ""
            return self._parse_convention_json(text)
        except Exception as e:
            logger.error(f"VL 分析图集失败 ({image_path.name}): {e}")
            return None

    def _parse_convention_json(self, text: str) -> dict | None:
        """从 VL 输出解析绘图规范 JSON。"""
        import re
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

    # ── 查询 ────────────────────────────────────────────────────

    def query_conventions(self, measure_type: str, map_type: str = "layout") -> dict:
        """查询指定措施类型 + 地图类型的绘图规范。

        Args:
            measure_type: 措施类型，如 "排水沟"、"挡墙"
            map_type: 地图类型，"layout"(总布置)/detail"(详图)/"section"(断面)

        Returns:
            绘图规范字典，无结果时返回默认规范。
        """
        col = self._get_collection()
        if col is None or col.count() == 0:
            return self._default_conventions(measure_type, map_type)

        query = f"水土保持 {measure_type} {map_type} 绘图规范 图例"
        try:
            results = self._col_query(col, query,
                n_results=min(3, col.count()),
                where={"source": "atlas"},
            )
            docs = results.get("documents", [[]])[0]
            if docs:
                # 合并查到的规范
                merged = {}
                for doc in docs:
                    try:
                        conv = json.loads(doc)
                        merged.update(conv)
                    except json.JSONDecodeError:
                        pass
                if merged:
                    return merged
        except Exception as e:
            logger.warning(f"图集查询失败: {e}")

        return self._default_conventions(measure_type, map_type)

    def query_by_purpose(self, query: str, purpose: str, top_k: int = 3) -> list[str]:
        """按用途分类查询知识库内容。

        使用 reranker 提升结果质量 (v2 可用时)。

        Args:
            query: 查询文本
            purpose: 文件用途 (制图标准/范文/法规条例/技术标准/造价规定/数据参考)
            top_k: 返回条数
        """
        col = self._get_collection()
        if col is None or col.count() == 0:
            return []

        # 多取一些候选, 后续 rerank
        fetch_k = min(top_k * 3, col.count())

        try:
            results = self._col_query(col, query,
                n_results=fetch_k,
                where={"purpose": purpose},
            )
            docs = results.get("documents", [[]])[0]
        except Exception as e:
            logger.warning(f"分类查询失败 ({purpose}): {e}")
            # 回退到无过滤查询
            try:
                results = self._col_query(col, f"{purpose} {query}",
                    n_results=fetch_k,
                    where={"source": "atlas"},
                )
                docs = results.get("documents", [[]])[0]
            except Exception:
                return []

        if not docs:
            return []

        # 尝试 rerank 提升质量
        try:
            from src.reranker import rerank
            passages = [{"text": d, "metadata": {}} for d in docs]
            reranked = rerank(query, passages, top_k=top_k)
            return [r["text"] for r in reranked]
        except Exception:
            return docs[:top_k]

    def get_section_reference(self, structure_type: str) -> dict:
        """查询典型工程断面的参考图规范。"""
        return self.query_conventions(structure_type, map_type="section")

    @staticmethod
    def _default_conventions(measure_type: str, map_type: str) -> dict:
        """默认绘图规范 (当图集 RAG 无结果时)。"""
        return {
            "map_type": map_type,
            "measure_type": measure_type,
            "legend_styles": [],
            "annotation_format": {"font_size": "3.5mm", "arrow_style": "simple"},
            "color_scheme": {"zone_fill": "浅色半透明", "measure_line": "深色实线"},
            "scale": "1:500",
            "layout_rules": {
                "legend_position": "右下角",
                "north_arrow": "左上角",
                "title": "居中",
                "scale_bar": "右下角",
            },
            "notes": f"默认规范 ({measure_type}, {map_type})，未从图集匹配到具体规范。",
        }

    def is_available(self) -> bool:
        """检查图集 RAG 是否可用。"""
        col = self._get_collection()
        return col is not None and col.count() > 0


# ── 子进程入口 (防止 ChromaDB/hnswlib segfault 杀死主进程) ─────────
if __name__ == "__main__":
    import shutil
    import sys
    import tempfile

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # 抑制噪音日志
    for noisy in ("pdfminer", "chromadb", "httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from src.settings import DATA_DIR

    final_db = DATA_DIR / "atlas_db"
    # 先在临时目录索引，成功后才移到正式位置 (防止崩溃留下损坏数据库)
    tmp_db = Path(tempfile.mkdtemp(prefix="atlas_db_"))
    try:
        atlas = AtlasRAG(db_dir=tmp_db)
        count = atlas.index_atlas(force=True)
        if count > 0:
            # 索引成功，替换正式目录
            if final_db.exists():
                shutil.rmtree(final_db, ignore_errors=True)
            shutil.copytree(tmp_db, final_db)
            print(f"ATLAS_INDEX_OK:{count}")
        else:
            print("ATLAS_INDEX_OK:0")
        sys.exit(0)
    except Exception as e:
        print(f"ATLAS_INDEX_ERR:{e}", file=sys.stderr)
        sys.exit(1)
    finally:
        shutil.rmtree(tmp_db, ignore_errors=True)
