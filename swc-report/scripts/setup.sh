#!/bin/bash
# ── 水土保持方案自动生成系统 — AutoDL Linux 一键部署 ──
# 适用: AutoDL A800×4 / Ubuntu + vLLM + Qwen2.5-72B
#
# 用法:
#   bash scripts/setup.sh              # 完整部署
#   bash scripts/setup.sh --skip-vllm  # 跳过 vLLM 安装(已有)

set -e

PROJECT_DIR="/root/autodl-tmp/swc-report"
SKIP_VLLM=false
[[ "$1" == "--skip-vllm" ]] && SKIP_VLLM=true

echo "============================================="
echo "  水土保持方案自动生成系统 — 环境部署"
echo "============================================="

cd "$PROJECT_DIR"

# ── 1. Python 核心依赖 ──
echo ""
echo "[1/4] 安装 Python 依赖..."
pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo "  核心依赖安装完成"

# ── 2. vLLM (可选) ──
echo ""
echo "[2/4] vLLM 检查..."
if $SKIP_VLLM; then
    echo "  跳过 vLLM 安装"
elif python -c "import vllm" 2>/dev/null; then
    echo "  vLLM 已安装"
else
    echo "  安装 vLLM..."
    pip install -q vllm -i https://pypi.tuna.tsinghua.edu.cn/simple
fi

# ── 3. RAG 语料 ──
echo ""
echo "[3/4] RAG 语料检查..."
RAG_COUNT=$(python -c "
import sys; sys.path.insert(0, '$PROJECT_DIR')
from src.rag import get_count
print(get_count())
" 2>/dev/null || echo "0")

if [[ "$RAG_COUNT" -gt 0 ]]; then
    echo "  RAG 语料: $RAG_COUNT 条"
else
    echo "  RAG 为空，构建语料..."
    python scripts/build_rag.py || echo "  [警告] RAG 构建失败，将使用无 RAG 模式"
fi

# ── 4. 快速验证 (--no-llm) ──
echo ""
echo "[4/4] 快速验证..."
python scripts/run.py --no-llm --output data/output/verify/ 2>&1 | tail -5

echo ""
echo "============================================="
echo "  部署完成!"
echo ""
echo "  使用步骤:"
echo ""
echo "  # 1. 启动 vLLM (72B 4卡并行)"
echo "  bash scripts/start_vllm.sh 72b"
echo ""
echo "  # 2. 新终端，等 vLLM 就绪后运行"
echo "  python scripts/run.py -v"
echo ""
echo "  # 也可以直接指定 vLLM 地址和模型"
echo "  python scripts/run.py --vllm-url http://localhost:8000/v1 \\"
echo "    --model Qwen2.5-72B-Instruct -v"
echo ""
echo "  # 跑测试"
echo "  python -m pytest tests/ -v"
echo "============================================="
