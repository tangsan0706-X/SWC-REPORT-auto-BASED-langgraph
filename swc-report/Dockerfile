# ── Stage 1: 前端构建 ──
FROM node:20-slim AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install --registry=https://registry.npmmirror.com
COPY web/ .
RUN npm run build

# ── Stage 2: Python 后端 ──
FROM python:3.11-slim

WORKDIR /app

# 系统依赖 (中文字体 + lxml + poppler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    libxml2 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv 2>/dev/null || true

# Python 依赖 (清华镜像)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# 项目文件
COPY config/ config/
COPY corpus/ corpus/
COPY templates/ templates/
COPY src/ src/
COPY server/ server/
COPY scripts/ scripts/
COPY run_server.py .
COPY autodl_start.py .

# 前端构建产物
COPY --from=frontend /web/dist web/dist/

# 创建数据目录
RUN mkdir -p data/output data/chromadb data/input data/atlas data/atlas_db

# 默认环境变量 (Linux: 使用 host 网络, vLLM 在宿主机上)
ENV VLLM_URL=http://localhost:8000/v1 \
    VL_URL=http://localhost:8001/v1 \
    MODEL_NAME=Qwen2.5-72B-Instruct \
    VL_MODEL_NAME=Qwen2.5-VL-72B-Instruct \
    MAX_TOKENS=4096 \
    TEMPERATURE=0.3 \
    HF_ENDPOINT=https://hf-mirror.com \
    HF_HOME=/app/data/huggingface \
    PYTHONUNBUFFERED=1

EXPOSE 8080 8081

ENTRYPOINT ["python", "run_server.py"]
