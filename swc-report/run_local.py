"""本机一键运行 — PyCharm 右键 Run 即可。

自动处理:
  1. 检查并安装缺失依赖
  2. 检查 Ollama 是否在线
  3. 运行完整 pipeline
  4. 生成报告到 data/output/
"""

import subprocess
import sys
import os

# ── 项目根目录 ──
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

# ── 1. 检查并安装依赖 ──
REQUIRED = ["openai", "docxtpl", "docx", "chromadb", "matplotlib", "pandas", "numpy", "lxml"]
INSTALL_MAP = {"docx": "python-docx"}

missing = []
for pkg in REQUIRED:
    try:
        __import__(pkg)
    except ImportError:
        missing.append(INSTALL_MAP.get(pkg, pkg))

if missing:
    print(f"[安装缺失依赖] {', '.join(missing)}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing, "-q",
                           "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"])
    print("[依赖安装完成]\n")

# ── 2. 检查 Ollama ──
import urllib.request
import json

OLLAMA_URL = "http://localhost:11434/v1"
MODEL_NAME = "qwen3:8b"

try:
    resp = urllib.request.urlopen(f"{OLLAMA_URL}/models", timeout=3)
    models = json.loads(resp.read())
    model_ids = [m["id"] for m in models.get("data", [])]
    print(f"[Ollama] 在线，可用模型: {', '.join(model_ids)}")
    if MODEL_NAME not in model_ids:
        print(f"[警告] 模型 {MODEL_NAME} 不在列表中，尝试继续...")
except Exception:
    print("[错误] Ollama 未运行！请先启动 Ollama 桌面应用。")
    input("按回车退出...")
    sys.exit(1)

# ── 3. 运行 Pipeline ──
print("\n" + "=" * 50)
print("  水土保持方案自动生成系统 — 本机测试")
print("=" * 50 + "\n")

from datetime import datetime
from src.pipeline import Pipeline
import src.settings as settings
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")

# 通过环境变量传递，确保子进程也能正确读取
os.environ["VLLM_URL"] = OLLAMA_URL
os.environ["MODEL_NAME"] = MODEL_NAME
os.environ["LLM_TIMEOUT"] = "300"
os.environ["WRITER_WORKERS"] = "1"
os.environ["DRAWING_WORKERS"] = "1"
os.environ["PIPELINE_PARALLEL"] = "false"
settings.VLLM_URL = OLLAMA_URL
settings.VLLM_MODEL_NAME = MODEL_NAME

output_dir = settings.BASE_DIR / "data" / "output" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

pipeline = Pipeline(
    facts_path=settings.FACTS_PATH,
    measures_path=settings.MEASURES_PATH,
    output_dir=output_dir,
    use_llm=True,
)

try:
    report_path = pipeline.run()
    print(f"\n{'=' * 50}")
    print(f"  报告生成完毕: {report_path}")
    print(f"{'=' * 50}")
except Exception as e:
    print(f"\n[失败] {e}")
    import traceback
    traceback.print_exc()

input("\n按回车退出...")
