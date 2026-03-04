#!/bin/bash
# 一键启动双模型: 文本(72B-INT8) + 视觉(72B-VL-INT8)
#
# GPU 分配:
#   GPU 0,1 → 72B-INT8 文本模型 (端口 8000)
#   GPU 2,3 → 72B-VL-INT8 视觉模型 (端口 8001)
#
# 用法:
#   bash scripts/start_vllm_all.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================="
echo "  双模型启动: 文本 + 视觉"
echo "  GPU 0,1 → 72B-INT8  (端口 8000)"
echo "  GPU 2,3 → 72B-VL-INT8 (端口 8001)"
echo "============================================="

# 启动文本模型 (后台)
echo ""
echo "[1/2] 启动文本模型 (GPU 0,1, 端口 8000)..."
CUDA_VISIBLE_DEVICES=0,1 TP_SIZE=2 PORT=8000 \
    bash "$SCRIPT_DIR/start_vllm.sh" 72b-int8 &
TEXT_PID=$!

# 等待一下避免日志混杂
sleep 3

# 启动视觉模型 (后台)
echo ""
echo "[2/2] 启动视觉模型 (GPU 2,3, 端口 8001)..."
CUDA_VISIBLE_DEVICES=2,3 TP_SIZE=2 PORT=8001 \
    bash "$SCRIPT_DIR/start_vllm.sh" vl &
VL_PID=$!

echo ""
echo "============================================="
echo "  文本模型 PID: $TEXT_PID (端口 8000)"
echo "  视觉模型 PID: $VL_PID (端口 8001)"
echo ""
echo "  检查状态:"
echo "    curl http://localhost:8000/v1/models"
echo "    curl http://localhost:8001/v1/models"
echo ""
echo "  停止: kill $TEXT_PID $VL_PID"
echo "============================================="

# 等待任一子进程退出
wait -n
echo "[警告] 有模型进程退出，停止全部..."
kill $TEXT_PID $VL_PID 2>/dev/null
wait
