#!/bin/bash
# vLLM 启动脚本 — 支持不同模型规格
#
# 用法:
#   bash scripts/start_vllm.sh              # 默认 72b-int8 (全部4卡)
#   bash scripts/start_vllm.sh 7b           # 7B 单卡测试
#   bash scripts/start_vllm.sh 72b-int8     # 72B GPTQ-Int8
#   bash scripts/start_vllm.sh 72b          # 72B FP16 (需4×80GB)
#   bash scripts/start_vllm.sh vl           # 72B-VL-INT8 (视觉模型)
#
# 双模型模式 (推荐):
#   bash scripts/start_vllm_all.sh          # 同时启动文本+视觉模型
#
# 指定 GPU:
#   CUDA_VISIBLE_DEVICES=0,1 bash scripts/start_vllm.sh 72b-int8
#   CUDA_VISIBLE_DEVICES=2,3 bash scripts/start_vllm.sh vl

set -e

MODEL_SIZE="${1:-72b-int8}"
QUANT_ARGS=""
PORT="${PORT:-8000}"

case "$MODEL_SIZE" in
    7b|7B)
        MODEL_PATH="${MODEL_PATH:-/root/autodl-tmp/LLM/Qwen2.5-7B-Instruct}"
        MODEL_NAME="Qwen2.5-7B-Instruct"
        TP_SIZE=1
        MAX_LEN=16384
        GPU_UTIL="${GPU_UTIL:-0.85}"
        ;;
    72b|72B)
        MODEL_PATH="${MODEL_PATH:-/root/autodl-tmp/LLM/Qwen2.5-72B-Instruct}"
        MODEL_NAME="Qwen2.5-72B-Instruct"
        TP_SIZE="${TP_SIZE:-4}"
        MAX_LEN=16384
        GPU_UTIL="${GPU_UTIL:-0.90}"
        ;;
    72b-int8|72B-INT8)
        MODEL_PATH="${MODEL_PATH:-/root/autodl-tmp/LLM/Qwen2.5-72B-Instruct-GPTQ-Int8}"
        MODEL_NAME="Qwen2.5-72B-Instruct"
        TP_SIZE="${TP_SIZE:-2}"
        MAX_LEN=32768
        GPU_UTIL="${GPU_UTIL:-0.90}"
        QUANT_ARGS="--quantization gptq"
        ;;
    72b-awq|72B-AWQ)
        MODEL_PATH="${MODEL_PATH:-/root/autodl-tmp/LLM/Qwen2.5-72B-Instruct-AWQ}"
        MODEL_NAME="Qwen2.5-72B-Instruct"
        TP_SIZE="${TP_SIZE:-2}"
        MAX_LEN=32768
        GPU_UTIL="${GPU_UTIL:-0.90}"
        QUANT_ARGS="--quantization awq"
        ;;
    vl|VL|72b-vl)
        MODEL_PATH="${MODEL_PATH:-/root/autodl-tmp/LLM/Qwen2.5-VL-72B-Instruct-GPTQ-Int8}"
        MODEL_NAME="Qwen2.5-VL-72B-Instruct"
        TP_SIZE="${TP_SIZE:-2}"
        MAX_LEN=16384
        GPU_UTIL="${GPU_UTIL:-0.90}"
        QUANT_ARGS="--quantization gptq"
        PORT="${PORT:-8001}"
        ;;
    vl-7b|VL-7B)
        MODEL_PATH="${MODEL_PATH:-/root/autodl-tmp/LLM/Qwen2.5-VL-7B-Instruct}"
        MODEL_NAME="Qwen2.5-VL-7B-Instruct"
        TP_SIZE=1
        MAX_LEN=16384
        GPU_UTIL="${GPU_UTIL:-0.85}"
        PORT="${PORT:-8001}"
        ;;
    *)
        echo "未知模型规格: $MODEL_SIZE"
        echo "支持: 7b, 72b, 72b-int8, 72b-awq, vl, vl-7b"
        exit 1
        ;;
esac

echo "========================================="
echo "  启动 vLLM: $MODEL_NAME"
echo "  模型路径: $MODEL_PATH"
echo "  张量并行: $TP_SIZE GPU"
echo "  最大长度: $MAX_LEN"
echo "  量化方式: ${QUANT_ARGS:-无(FP16)}"
echo "  端口:     $PORT"
[ -n "$CUDA_VISIBLE_DEVICES" ] && echo "  GPU:      $CUDA_VISIBLE_DEVICES"
echo "========================================="

if [ ! -d "$MODEL_PATH" ]; then
    echo "[错误] 模型目录不存在: $MODEL_PATH"
    echo ""
    echo "请先下载模型，例如:"
    echo "  pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple"
    echo "  modelscope download --model Qwen/Qwen2.5-72B-Instruct-GPTQ-Int8 \\"
    echo "    --local_dir /root/autodl-tmp/LLM/Qwen2.5-72B-Instruct-GPTQ-Int8"
    echo ""
    echo "或使用一键脚本: python autodl_start.py --install"
    exit 1
fi

# 文本模型需要开启 tool calling (Agent 工具调用)
TOOL_ARGS=""
if [[ "$MODEL_SIZE" != vl* && "$MODEL_SIZE" != VL* ]]; then
    TOOL_ARGS="--enable-auto-tool-choice --tool-call-parser hermes"
fi

python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \
    --served-model-name "$MODEL_NAME" \
    --tensor-parallel-size "$TP_SIZE" \
    --max-model-len "$MAX_LEN" \
    --gpu-memory-utilization "$GPU_UTIL" \
    --port "$PORT" \
    --trust-remote-code \
    --dtype auto \
    --enforce-eager \
    $QUANT_ARGS \
    $TOOL_ARGS
