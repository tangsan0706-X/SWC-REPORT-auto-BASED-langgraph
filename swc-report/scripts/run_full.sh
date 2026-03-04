#!/bin/bash
# ── 水土保持方案自动生成系统 — 全流程一键运行 ──
# 适用: AutoDL 环境, vLLM 已启动
#
# 用法:
#   bash scripts/run_full.sh               # 使用默认配置
#   bash scripts/run_full.sh --no-llm      # 不用 LLM
#   VLLM_URL=http://x:8000/v1 MODEL_NAME=Qwen2.5-72B-Instruct bash scripts/run_full.sh

set -e

PROJECT_DIR="/root/autodl-tmp/swc-report"
VLLM_URL="${VLLM_URL:-http://localhost:8000/v1}"
MODEL_NAME="${MODEL_NAME:-Qwen2.5-72B-Instruct}"

cd "$PROJECT_DIR"

EXTRA_ARGS=""
NO_LLM=false
for arg in "$@"; do
    if [[ "$arg" == "--no-llm" ]]; then
        NO_LLM=true
    fi
    EXTRA_ARGS="$EXTRA_ARGS $arg"
done

echo "============================================="
echo "  水土保持方案自动生成系统"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  模型: $MODEL_NAME"
echo "  API:  $VLLM_URL"
echo "============================================="

# ── 1. 环境检查 ──
echo ""
echo "[检查] Python 依赖..."
python -c "import docxtpl, chromadb, matplotlib, openai; print('  依赖正常')"

# ── 2. vLLM 健康检查 (仅 LLM 模式) ──
if ! $NO_LLM; then
    echo ""
    echo "[检查] vLLM 服务 ($VLLM_URL)..."
    for i in 1 2 3; do
        if curl -s "${VLLM_URL}/models" > /dev/null 2>&1; then
            echo "  vLLM 就绪"
            break
        fi
        if [[ $i -eq 3 ]]; then
            echo "  [错误] vLLM 服务未响应: $VLLM_URL"
            echo "  请先启动: bash scripts/start_vllm.sh 72b"
            exit 1
        fi
        echo "  等待 vLLM 启动... ($i/3)"
        sleep 10
    done
fi

# ── 3. RAG 检查 ──
echo ""
echo "[检查] RAG 语料..."
RAG_COUNT=$(python -c "
import sys; sys.path.insert(0, '$PROJECT_DIR')
from src.rag import get_count
print(get_count())
" 2>/dev/null || echo "0")

if [[ "$RAG_COUNT" -gt 0 ]]; then
    echo "  RAG 语料: $RAG_COUNT 条"
else
    echo "  RAG 为空，构建语料..."
    python scripts/build_rag.py 2>/dev/null || echo "  [警告] RAG 构建跳过"
fi

# ── 4. 运行主流水线 ──
OUTPUT_DIR="data/output/run_$(date '+%Y%m%d_%H%M%S')"
echo ""
echo "============================================="
echo "  开始生成报告..."
echo "  输出: $OUTPUT_DIR"
echo "============================================="

python scripts/run.py \
    --vllm-url "$VLLM_URL" \
    --model "$MODEL_NAME" \
    --output "$OUTPUT_DIR" \
    $EXTRA_ARGS -v

echo ""
echo "============================================="
echo "  完成! 报告位于: $OUTPUT_DIR/report.docx"
echo "============================================="
