"""路径配置 & 模型配置。

Linux 运行时使用 /root/autodl-tmp/swc-report；
Windows 开发时自动回退到本文件所在的上级目录。
Docker 部署时使用 /app 目录。

所有 LLM 相关配置均支持环境变量覆盖：
  VLLM_URL       — LLM API 地址 (默认 http://localhost:8000/v1)
  MODEL_NAME     — 模型名称 (默认 Qwen2.5-72B-Instruct)
  MAX_TOKENS     — 最大输出 token (默认 4096)
  TEMPERATURE    — 生成温度 (默认 0.3)
"""

import os
import platform
from pathlib import Path

# ── 项目根目录 ───────────────────────────────────────────────
_DOCKER_BASE = Path("/app")
_LINUX_BASE = Path("/root/autodl-tmp/swc-report")
_LOCAL_BASE = Path(__file__).resolve().parent.parent  # src/../ = swc-report/

if _DOCKER_BASE.exists() and (_DOCKER_BASE / "src").exists():
    BASE_DIR = _DOCKER_BASE
elif platform.system() == "Linux" and _LINUX_BASE.exists():
    BASE_DIR = _LINUX_BASE
else:
    BASE_DIR = _LOCAL_BASE

# ── 子目录 ──────────────────────────────────────────────────
CONFIG_DIR = BASE_DIR / "config"
TEMPLATES_DIR = BASE_DIR / "templates"
CORPUS_DIR = BASE_DIR / "corpus"
DATA_DIR = BASE_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
CHROMADB_DIR = DATA_DIR / "chromadb"

# ── 配置文件路径 ─────────────────────────────────────────────
FACTS_PATH = CONFIG_DIR / "facts_v2.json"
MEASURES_PATH = CONFIG_DIR / "measures_v2.csv"
SOIL_MAP_PATH = CONFIG_DIR / "soil_map.json"
PRICE_PATH = CONFIG_DIR / "price_v2.csv"
FEE_RATE_PATH = CONFIG_DIR / "fee_rate_config.json"
MEASURE_LIBRARY_PATH = CONFIG_DIR / "measure_library.json"
LEGAL_REFS_PATH = CONFIG_DIR / "legal_refs.json"

# ── 模板 ────────────────────────────────────────────────────
TEMPLATE_DOCX = TEMPLATES_DIR / "template.docx"

# ── LLM 模型 (本地路径，仅 vLLM 启动时使用) ─────────────────
MODEL_PATH = Path(os.environ.get("MODEL_PATH", "/root/autodl-tmp/LLM/Qwen2.5-72B-Instruct-GPTQ-Int8"))
VL_MODEL_PATH = Path(os.environ.get("VL_MODEL_PATH", "/root/autodl-tmp/LLM/Qwen2.5-VL-72B-Instruct-GPTQ-Int8"))

# ── vLLM / OpenAI-compatible API (支持环境变量覆盖) ─────────
def _detect_llm_url() -> str:
    """自动检测 LLM API 地址: 优先环境变量 → Ollama(11434) → vLLM(8000)。"""
    env_url = os.environ.get("VLLM_URL")
    if env_url:
        return env_url
    import urllib.request
    for url in ("http://localhost:11434/v1", "http://localhost:8000/v1"):
        try:
            urllib.request.urlopen(f"{url}/models", timeout=2)
            return url
        except Exception:
            continue
    # 默认: Windows→Ollama, Linux→vLLM
    if platform.system() == "Windows":
        return "http://localhost:11434/v1"
    return "http://localhost:8000/v1"

def _detect_model_name() -> str:
    """自动检测模型名称: 环境变量 → Ollama 查询 → 硬编码默认。"""
    env_name = os.environ.get("MODEL_NAME")
    if env_name:
        return env_name
    # 尝试从 Ollama 获取实际可用的文本模型
    if platform.system() == "Windows":
        try:
            import urllib.request, json
            resp = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
            data = json.loads(resp.read())
            # 优先选非 VL 的 qwen 模型
            for m in data.get("models", []):
                name = m["name"]
                if "qwen" in name.lower() and "vl" not in name.lower():
                    return name
        except Exception:
            pass
        return "qwen3:8b"
    return "Qwen2.5-72B-Instruct"

VLLM_URL = _detect_llm_url()
VLLM_MODEL_NAME = _detect_model_name()
VLLM_MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))
VLLM_TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.3"))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))          # 单次 LLM 调用超时(秒)
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))    # LLM 调用失败重试次数

# ── 视觉模型 (VL) API ────────────────────────────────────
def _detect_vl_url() -> str:
    """自动检测 VL 模型 API 地址。Windows→Ollama(同端口), Linux→vLLM(8001)。"""
    env = os.environ.get("VL_URL")
    if env:
        return env
    if platform.system() == "Windows":
        return "http://localhost:11434/v1"  # Ollama 同端口，不同模型名
    return "http://localhost:8001/v1"       # vLLM 独立端口

def _detect_vl_model_name() -> str:
    env = os.environ.get("VL_MODEL_NAME")
    if env:
        return env
    if platform.system() == "Windows":
        return "qwen3-vl:8b"
    return "Qwen2-VL-72B-Instruct-GPTQ-Int8"

VL_URL = _detect_vl_url()
VL_MODEL_NAME = _detect_vl_model_name()
VL_MAX_TOKENS = int(os.environ.get("VL_MAX_TOKENS", "4096"))

# ── Agent 限制 ─────────────────────────────────────────────
AGENT_MAX_TURNS = 10          # 单次 Agent 最大工具调用轮次
WRITER_MAX_TOKENS = 4096      # 撰稿单章最大输出 token
AUDITOR_PASS_SCORE = 80       # 审计通过阈值
AUDITOR_FAIL_SCORE = 60       # 审计强制通过阈值
AUDITOR_MAX_RETRY = 3         # 每章最大重试次数
ADAPTER_MAX_TURNS = int(os.environ.get("ADAPTER_MAX_TURNS", "8"))
ADAPTER_MAX_CALLBACKS = int(os.environ.get("ADAPTER_MAX_CALLBACKS", "2"))
CONTEXT_SUMMARIZE_LLM = os.environ.get("CONTEXT_SUMMARIZE_LLM", "false").lower() == "true"
CONTEXT_SUMMARY_MAX_TOKENS = int(os.environ.get("CONTEXT_SUMMARY_MAX_TOKENS", "256"))

# ── 并行执行配置 ───────────────────────────────────────────
WRITER_PARALLEL_WORKERS = int(os.environ.get("WRITER_WORKERS", "4"))
DRAWING_PARALLEL_WORKERS = int(os.environ.get("DRAWING_WORKERS", "3"))
PIPELINE_PARALLEL_STEPS = os.environ.get("PIPELINE_PARALLEL", "true").lower() == "true"

# ── RAG 参数 (v1, 保留兼容) ────────────────────────────────
RAG_CHUNK_SIZE = 500          # 分块字符数
RAG_CHUNK_OVERLAP = 50        # 分块重叠字符数
RAG_TOP_K = 3                 # 默认检索条数
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# ── RAG v2 参数 ──────────────────────────────────────────
EMBEDDING_MODEL_V2 = "BAAI/bge-m3"          # 1024d dense + sparse
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
RAG_DENSE_TOP_K = 10                         # 稠密检索候选数
RAG_SPARSE_TOP_K = 10                        # 稀疏检索候选数
RAG_RERANK_TOP_K = 3                         # 重排序最终返回数
RAG_COLLECTION_V2 = "swc_corpus_v2"          # v2 ChromaDB collection
EMBEDDING_DEVICE = os.environ.get("EMBEDDING_DEVICE", "cuda:2")
RERANKER_DEVICE = os.environ.get("RERANKER_DEVICE", "cuda:2")
SPARSE_INDEX_PATH = DATA_DIR / "sparse_index.pkl"
RAG_V2_CHUNK_SIZE = 800                      # v2 分块最大字符数
RAG_V2_CHUNK_OVERLAP = 100                   # v2 分块重叠字符数

# ── 图集目录 (标准图集 RAG) ────────────────────────────────
ATLAS_DIR = DATA_DIR / "atlas"
ATLAS_DB_DIR = DATA_DIR / "atlas_db"

# ── 图表 ───────────────────────────────────────────────────
CHART_DPI = 300
CHART_FORMAT = "png"
