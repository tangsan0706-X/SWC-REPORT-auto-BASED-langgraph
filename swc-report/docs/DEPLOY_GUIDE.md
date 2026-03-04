# AutoDL 上机部署指南 (详细版)

> **系统**: 水土保持方案自动编制系统 v1.0
> **环境**: AutoDL 4×A800 (80GB) / Ubuntu / CUDA 12.x
> **模型**: Qwen2.5-72B-Instruct-GPTQ-Int8 + Qwen2.5-VL-72B-Instruct-GPTQ-Int8
> **模式**: CLI (命令行生成报告)

---

## 目录

1. [环境要求](#1-环境要求)
2. [上传数据盘](#2-上传数据盘)
3. [一键部署 (推荐)](#3-一键部署-推荐)
4. [手动部署 (逐步)](#4-手动部署-逐步)
5. [运行生成报告](#5-运行生成报告)
6. [输出文件说明](#6-输出文件说明)
7. [自定义项目数据](#7-自定义项目数据)
8. [常用命令速查](#8-常用命令速查)
9. [故障排查](#9-故障排查)
10. [架构概览](#10-架构概览)

---

## 1. 环境要求

### 硬件

| 项目 | 最低要求 | 推荐配置 |
|------|----------|----------|
| GPU | 4×48GB (RTX 6000 Ada) | 4×80GB (A800/A100) |
| 显存总计 | 192GB | 320GB |
| 内存 | 64GB | 128GB |
| 磁盘 | 200GB 可用空间 | 300GB+ |

> **显存分配**: GPU 0,1 → 文本模型 (~36GB×2)；GPU 2,3 → 视觉模型 (~36GB×2)

### 软件

| 项目 | 版本 |
|------|------|
| 操作系统 | Ubuntu 20.04+ |
| Python | 3.10+ |
| CUDA | 12.1+ |
| 驱动 | 535+ |

### 网络

| 目标 | 是否可达 | 用途 |
|------|----------|------|
| ModelScope (modelscope.cn) | 可达 | 下载 72B 模型 |
| 清华 PyPI 镜像 (pypi.tuna.tsinghua.edu.cn) | 可达 | pip 安装依赖 |
| HuggingFace 镜像 (hf-mirror.com) | 可达 | embedding 模型 |
| HuggingFace (huggingface.co) | **不可达** | 已用镜像替代 |
| GitHub (github.com) | **不可达** | 无需直连 |
| PyPI 国际源 (pypi.org) | **不可达** | 已用清华镜像替代 |

---

## 2. 上传数据盘

### 2.1 本地文件准备

你的本地数据盘目录结构 (`autodl-tmp/`):

```
autodl-tmp/
├── LLM/                              # 模型目录 (上机后自动下载, 不要从本地传)
│   ├── Qwen2.5-7B-Instruct/         # 7B 测试模型 (可选, 已有)
│   └── Qwen2.5-VL-7B-Instruct/      # 7B VL 模型 (可选, 已有)
├── SWC knowledge git/                # 知识库原始文件
│   ├── 报批稿.pdf
│   ├── 生产建设项目水土保持技术标准GB50433-2018.pdf
│   ├── 江苏省水土保持条例.txt
│   ├── 南通市水土保持规划（2016-2030）.pdf
│   └── ...
├── 水土保持措施典型设计图.dwg          # CAD 图纸
└── swc-report/                       # ★ 项目代码 (核心)
    ├── autodl_start.py               # 一键启动脚本
    ├── config/                       # 项目数据配置
    │   ├── facts_v2.json             # ★ 项目概况 (需修改)
    │   ├── measures_v2.csv           # 已有措施
    │   ├── measure_library.json      # 35种标准措施库
    │   ├── soil_map.json             # 土壤图
    │   ├── price_v2.csv              # 单价表
    │   ├── fee_rate_config.json      # 费率配置
    │   ├── legal_refs.json           # 法规引用
    │   └── drawing_standards.json    # 制图标准
    ├── corpus/                       # RAG 范文语料 (PDF)
    ├── templates/template.docx       # Word 模板
    ├── data/
    │   ├── atlas/                    # 制图标准知识库
    │   ├── input/                    # 输入文件 (岩土报告等)
    │   └── output/                   # ★ 生成结果
    ├── src/                          # 核心源码
    ├── scripts/                      # CLI 脚本
    ├── tests/                        # 测试
    ├── requirements.txt              # Python 依赖
    └── docs/                         # 文档
```

### 2.2 上传方法

**方法一: AutoDL 网页上传 (推荐)**

1. 登录 AutoDL 控制台 → 选择实例 → 点击「JupyterLab」
2. 左侧文件树导航到 `/root/autodl-tmp/`
3. 拖拽上传 `swc-report/` 和 `SWC knowledge git/` 目录

**方法二: scp 命令**

```bash
# 从本地 Windows (PowerShell):
scp -r "D:\autodl ub linux A800+4\root\autodl-tmp\swc-report" root@<实例IP>:/root/autodl-tmp/
scp -r "D:\autodl ub linux A800+4\root\autodl-tmp\SWC knowledge git" root@<实例IP>:/root/autodl-tmp/
```

**方法三: rsync (增量同步, 适合多次上传)**

```bash
rsync -avz --progress \
  "D:/autodl ub linux A800+4/root/autodl-tmp/swc-report/" \
  root@<实例IP>:/root/autodl-tmp/swc-report/
```

### 2.3 上传后验证

```bash
# SSH 登录后检查
ls /root/autodl-tmp/
# 应看到: LLM/  SWC knowledge git/  swc-report/

ls /root/autodl-tmp/swc-report/autodl_start.py
# 应看到文件存在

ls /root/autodl-tmp/swc-report/config/facts_v2.json
# 应看到文件存在
```

> **重要**: `LLM/` 目录下的 72B 模型 (~40GB×2) **不要从本地上传**, 太大了。
> 上机后由 `autodl_start.py` 从 ModelScope 自动下载, 速度 50-100MB/s。

---

## 3. 一键部署 (推荐)

### 3.1 一条命令搞定

```bash
cd /root/autodl-tmp/swc-report
python autodl_start.py --cli
```

这条命令会自动执行以下全部步骤:

```
[1/7] 设置中国镜像环境 (HF_ENDPOINT + 清华 PyPI)
[2/7] 环境检查 (Python版本 + GPU + 模型 + vLLM)
[3/7] 安装 Python 依赖 (requirements.txt → 清华镜像)
[4/7] 安装 vLLM 推理引擎
[5/7] 安装中文字体 + 预下载 embedding 模型
[6/7] 从 ModelScope 下载 72B 模型:
      - Qwen2.5-72B-Instruct-GPTQ-Int8      (~40GB, 10-30分钟)
      - Qwen2.5-VL-72B-Instruct-GPTQ-Int8   (~40GB, 10-30分钟)
[7/7] 启动双 vLLM 服务:
      - Text LLM → GPU 0,1 → port 8000
      - VL Model → GPU 2,3 → port 8001
      等待就绪后自动运行 17 步 Pipeline → 生成 report.docx
```

### 3.2 预计时间

| 阶段 | 首次运行 | 再次运行 (已缓存) |
|------|----------|-------------------|
| 依赖安装 | 5-10 分钟 | 跳过 |
| 模型下载 (文本 40GB) | 10-30 分钟 | 跳过 |
| 模型下载 (VL 40GB) | 10-30 分钟 | 跳过 |
| vLLM 启动 | 3-5 分钟 | 3-5 分钟 |
| Pipeline 生成报告 | 15-30 分钟 | 15-30 分钟 |
| **总计** | **~60-90 分钟** | **~20-35 分钟** |

### 3.3 观察输出

正常启动日志示例:

```
[10:00:00] [INFO] 水土保持方案自动编制系统 v1.0
[10:00:00] [INFO] 项目目录: /root/autodl-tmp/swc-report
[10:00:00] [INFO] ==================================================
[10:00:00] [INFO] 环境检查
[10:00:00] [INFO] ==================================================
[10:00:00] [INFO] Python 3.10.12
[10:00:01] [INFO] GPU: 4 张
[10:00:01] [INFO]   [0] NVIDIA A800-SXM4-80GB, 81920 MiB
[10:00:01] [INFO]   [1] NVIDIA A800-SXM4-80GB, 81920 MiB
[10:00:01] [INFO]   [2] NVIDIA A800-SXM4-80GB, 81920 MiB
[10:00:01] [INFO]   [3] NVIDIA A800-SXM4-80GB, 81920 MiB
[10:00:01] [INFO] 模型 [text] 不存在: ... (将自动下载)
[10:00:01] [INFO] 模型 [vl] 不存在: ... (将自动下载)
...
[10:05:00] [INFO] 下载模型 [text]: Qwen/Qwen2.5-72B-Instruct-GPTQ-Int8
[10:05:00] [INFO]   来源: https://modelscope.cn/models/Qwen/Qwen2.5-72B-Instruct-GPTQ-Int8
[10:05:00] [INFO]   (72B-INT8 约 40GB, 预计 10~30 分钟)
...
[10:25:00] [INFO] 模型 [text] 下载完成
...
[10:50:00] [INFO] 启动 vLLM [text]: Qwen2.5-72B-Instruct (port 8000, TP=2, GPU=0,1)
[10:50:00] [INFO] 等待 Text LLM (port 8000) 就绪...
[10:53:00] [INFO] Text LLM 就绪 (180s)
[10:53:00] [INFO] 启动 vLLM [vl]: Qwen2.5-VL-72B-Instruct (port 8001, TP=2, GPU=2,3)
[10:53:00] [INFO] 等待 VL Model (port 8001) 就绪...
[10:56:00] [INFO] VL Model 就绪 (180s)
[10:56:00] [INFO] 启动 Pipeline (CLI 模式)...
...
[11:20:00] [INFO] ==================================================
[11:20:00] [INFO] Pipeline 完成! 报告: /root/autodl-tmp/swc-report/data/output/report.docx
[11:20:00] [INFO] ==================================================
```

### 3.4 其他一键模式参数

```bash
# 仅安装依赖 + 下载模型 (不启动服务)
python autodl_start.py --install

# 仅检查环境
python autodl_start.py --check

# 不启动视觉模型 (省显存, 少下载 40GB, 仅需2卡)
python autodl_start.py --cli --no-vl

# vLLM 已经在跑了, 只跑 Pipeline
python autodl_start.py --cli-only

# 手动指定 GPU
python autodl_start.py --cli --gpu 0,1,2,3
```

---

## 4. 手动部署 (逐步)

如果一键模式出问题, 或者你想分步控制, 可以手动部署。

### 4.1 安装依赖

```bash
cd /root/autodl-tmp/swc-report

# 安装 Python 核心依赖 (清华镜像)
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 安装 vLLM 推理引擎
pip install vllm -i https://pypi.tuna.tsinghua.edu.cn/simple

# 安装中文字体 (图表需要)
apt-get update -qq && apt-get install -y -qq fonts-wqy-zenhei fonts-noto-cjk
rm -rf ~/.cache/matplotlib   # 清理字体缓存
```

### 4.2 下载模型

```bash
# 安装 ModelScope SDK
pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple

# 下载文本模型 (必须, ~40GB)
modelscope download --model Qwen/Qwen2.5-72B-Instruct-GPTQ-Int8 \
  --local_dir /root/autodl-tmp/LLM/Qwen2.5-72B-Instruct-GPTQ-Int8

# 下载视觉模型 (推荐, ~40GB, Drawing Agent 验证需要)
modelscope download --model Qwen/Qwen2.5-VL-72B-Instruct-GPTQ-Int8 \
  --local_dir /root/autodl-tmp/LLM/Qwen2.5-VL-72B-Instruct-GPTQ-Int8
```

> ModelScope 支持断点续传, 如果中途断了重新运行同样的命令即可。

### 4.3 验证模型文件

```bash
# 文本模型
ls /root/autodl-tmp/LLM/Qwen2.5-72B-Instruct-GPTQ-Int8/*.safetensors | wc -l
# 应看到 10+ 个文件

# 视觉模型
ls /root/autodl-tmp/LLM/Qwen2.5-VL-72B-Instruct-GPTQ-Int8/*.safetensors | wc -l
# 应看到 10+ 个文件
```

### 4.4 预下载 embedding 模型

```bash
# 设置 HuggingFace 中国镜像
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/root/autodl-tmp/LLM/huggingface

# 预下载 RAG 用的 embedding 模型 (~500MB)
python -c "
from sentence_transformers import SentenceTransformer
SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
print('embedding 模型下载完成')
"
```

### 4.5 启动 vLLM (终端 1)

**方式 A: 双模型同时启动 (推荐)**

```bash
cd /root/autodl-tmp/swc-report
bash scripts/start_vllm_all.sh
```

**方式 B: 分别启动**

```bash
# 终端 1: 文本模型 (GPU 0,1)
cd /root/autodl-tmp/swc-report
CUDA_VISIBLE_DEVICES=0,1 bash scripts/start_vllm.sh 72b-int8

# 终端 2: 视觉模型 (GPU 2,3)
cd /root/autodl-tmp/swc-report
CUDA_VISIBLE_DEVICES=2,3 PORT=8001 bash scripts/start_vllm.sh vl
```

### 4.6 验证 vLLM 就绪

等待看到 `INFO: Uvicorn running on http://0.0.0.0:8000`, 然后:

```bash
# 检查文本模型
curl -s http://localhost:8000/v1/models | python -m json.tool
# 应看到: "id": "Qwen2.5-72B-Instruct"

# 检查视觉模型
curl -s http://localhost:8001/v1/models | python -m json.tool
# 应看到: "id": "Qwen2.5-VL-72B-Instruct"
```

### 4.7 运行 Pipeline (终端 2)

```bash
cd /root/autodl-tmp/swc-report
python scripts/run.py -v
```

---

## 5. 运行生成报告

### 5.1 默认运行

```bash
cd /root/autodl-tmp/swc-report
python scripts/run.py -v
```

使用 `config/facts_v2.json` 中的项目数据, 输出到 `data/output/` 目录。

### 5.2 指定输入/输出

```bash
# 指定项目概况文件 + 输出目录
python scripts/run.py \
  --facts config/facts_v2.json \
  --measures config/measures_v2.csv \
  --output data/output/my_run/ \
  -v
```

### 5.3 仅计算引擎 (不用 LLM)

```bash
# 不调用 LLM, 仅运行计算引擎 + 默认措施 + 占位文本
# 用于快速验证系统是否能跑通
python scripts/run.py --no-llm -v
```

### 5.4 指定 vLLM 地址

```bash
# 如果 vLLM 不在默认端口
python scripts/run.py --vllm-url http://localhost:8000/v1 --model Qwen2.5-72B-Instruct -v
```

### 5.5 构建 RAG + 运行

```bash
# 先构建 RAG 范文语料库, 再运行 Pipeline
python scripts/run.py --build-rag -v
```

---

## 6. 输出文件说明

报告生成后, 输出目录结构:

```
data/output/
├── report.docx            # ★ 最终报告 (Word 文档)
├── draft.docx             # 初稿 (审计前)
├── audit.json             # 审计结果 (各章评分)
├── tpl_ctx.json           # 模板上下文 (229 个标签)
├── erosion_chart.png      # 水土流失预测图
├── investment_pie.png     # 投资构成饼图
├── benefit_bar.png        # 效益对比柱状图
├── zone_pie.png           # 分区面积饼图
└── measure_maps/          # 措施图 (Drawing Agent 生成)
    ├── zone_建构筑物区.png
    ├── zone_道路广场区.png
    ├── zone_绿化工程区.png
    ├── layout_总布置.png
    ├── detail_排水沟.png
    └── cross_section_排水沟.png
```

### 如何取回报告

```bash
# 方法一: scp 下载到本地
scp root@<实例IP>:/root/autodl-tmp/swc-report/data/output/report.docx .

# 方法二: AutoDL JupyterLab 下载
# 打开 JupyterLab → 导航到 data/output/ → 右键 report.docx → Download
```

---

## 7. 自定义项目数据

### 7.1 修改项目概况

编辑 `config/facts_v2.json`:

```json
{
  "project_name": "你的项目名称",
  "investor": "建设单位名称",
  "location": {
    "province": "省份",
    "city": "城市",
    "district": "区县",
    "address": "详细地址",
    "longitude": 120.89,
    "latitude": 32.01
  },
  "project_nature": "新建",           // 新建 | 改扩建
  "project_type": "房地产",           // 房地产 | 工业 | 道路 | 市政
  "approval_level": "市级",           // 市级 | 省级 | 部级
  "total_investment_万元": 180000,
  "civil_investment_万元": 95000,
  "construction_area_m2": 152000,
  "land_area_hm2": 7.9368,
  "earthwork": {
    "excavation_m3": 135000,          // 挖方量
    "fill_m3": 110000,                // 填方量
    "topsoil_strip_m3": 15000,        // 表土剥离量
    "topsoil_backfill_m3": 15000      // 表土回覆量
  },
  "schedule": {
    "start_date": "2023-08-01",       // 开工日期
    "end_date": "2025-08-01",         // 竣工日期
    "plan_submit_date": "2024-03-01", // 方案报批日期
    "construction_period_months": 24  // 建设工期(月)
  },
  "zones": [                          // 防治分区 (按实际填写)
    {
      "name": "建(构)筑物区",
      "area_hm2": 3.67,
      "excavation_m3": 85000,
      "fill_m3": 72000,
      "description": "包括1#~12#住宅楼、地下车库等"
    },
    // ... 更多分区
  ],
  "prevention_level": "一级",         // 一级 | 二级 | 三级
  "landscape_type": "平原沙土区",      // 参考当地水土保持规划
  "soil_erosion_type": "水力侵蚀",    // 水力侵蚀 | 风力侵蚀
  "allowable_erosion_modulus": 500,    // 容许土壤流失量 (t/km²·a)
  "prevention_targets": {              // 防治目标值 (%)
    "水土流失治理度": 95,
    "土壤流失控制比": 1,
    "渣土防护率": 95,
    "表土保护率": 97,
    "林草植被恢复率": 97,
    "林草覆盖率": 27
  }
}
```

### 7.2 更换范文语料

将 PDF 范文放入 `corpus/` 目录, 然后重建 RAG:

```bash
python scripts/build_rag.py
```

### 7.3 更换 Word 模板

替换 `templates/template.docx`, 模板标签参考 `data/output/tpl_ctx.json` 中的 229 个键名。

---

## 8. 常用命令速查

### 启动/停止

| 操作 | 命令 |
|------|------|
| 一键启动 (CLI) | `python autodl_start.py --cli` |
| 一键启动 (仅安装) | `python autodl_start.py --install` |
| 检查环境 | `python autodl_start.py --check` |
| 手动启动双 vLLM | `bash scripts/start_vllm_all.sh` |
| 手动启动文本 vLLM | `CUDA_VISIBLE_DEVICES=0,1 bash scripts/start_vllm.sh 72b-int8` |
| 手动启动 VL vLLM | `CUDA_VISIBLE_DEVICES=2,3 PORT=8001 bash scripts/start_vllm.sh vl` |
| 停止 vLLM | `pkill -f vllm` 或 `Ctrl+C` |

### 生成报告

| 操作 | 命令 |
|------|------|
| CLI 生成报告 | `python scripts/run.py -v` |
| 仅计算引擎 | `python scripts/run.py --no-llm` |
| 指定输出目录 | `python scripts/run.py --output data/output/test1/ -v` |
| 构建 RAG + 运行 | `python scripts/run.py --build-rag -v` |

### 检查/调试

| 操作 | 命令 |
|------|------|
| 检查 vLLM 文本模型 | `curl http://localhost:8000/v1/models` |
| 检查 vLLM VL 模型 | `curl http://localhost:8001/v1/models` |
| 查看 vLLM 日志 | `tail -f data/vllm_text.log` |
| 查看 VL 日志 | `tail -f data/vllm_vl.log` |
| 跑测试 | `python -m pytest tests/ -v` |
| 构建 RAG 语料 | `python scripts/build_rag.py` |
| 查看 GPU | `nvidia-smi` |
| 查看 GPU 实时 | `watch -n 1 nvidia-smi` |
| 查看磁盘 | `df -h /root/autodl-tmp` |

### 模型管理

| 操作 | 命令 |
|------|------|
| 下载文本模型 | `modelscope download --model Qwen/Qwen2.5-72B-Instruct-GPTQ-Int8 --local_dir /root/autodl-tmp/LLM/Qwen2.5-72B-Instruct-GPTQ-Int8` |
| 下载 VL 模型 | `modelscope download --model Qwen/Qwen2.5-VL-72B-Instruct-GPTQ-Int8 --local_dir /root/autodl-tmp/LLM/Qwen2.5-VL-72B-Instruct-GPTQ-Int8` |
| 检查模型大小 | `du -sh /root/autodl-tmp/LLM/*/` |

---

## 9. 故障排查

### 9.1 模型下载失败

**症状**: `modelscope download` 卡住或超时

```bash
# 方法一: 重试 (支持断点续传)
modelscope download --model Qwen/Qwen2.5-72B-Instruct-GPTQ-Int8 \
  --local_dir /root/autodl-tmp/LLM/Qwen2.5-72B-Instruct-GPTQ-Int8

# 方法二: 开学术加速后重试
source /etc/network_turbo
modelscope download --model Qwen/Qwen2.5-72B-Instruct-GPTQ-Int8 \
  --local_dir /root/autodl-tmp/LLM/Qwen2.5-72B-Instruct-GPTQ-Int8
```

### 9.2 vLLM 启动 OOM

**症状**: `torch.cuda.OutOfMemoryError`

```bash
# 方法一: 降低 GPU 利用率 (默认 0.90)
GPU_UTIL=0.80 bash scripts/start_vllm.sh 72b-int8

# 方法二: 减小 max-model-len (默认 32768)
# 编辑 autodl_start.py 中 MODELS.text.max_len = 16384

# 方法三: 不启动 VL 模型, 只用文本模型 (2卡即可)
python autodl_start.py --cli --no-vl

# 方法四: 先清理 GPU 显存
nvidia-smi | grep python
kill -9 <PIDs>
```

### 9.3 vLLM 启动超时

**症状**: `等待 Text LLM (port 8000) 就绪...` 超过 5 分钟

```bash
# 检查 vLLM 日志
tail -100 data/vllm_text.log

# 常见原因:
# 1. 模型文件损坏 → 删除后重新下载
# 2. CUDA 版本不匹配 → pip install vllm --upgrade
# 3. 显存不足 → 参考 9.2
```

### 9.4 pip install 失败

**症状**: 包安装报错

```bash
# 开启学术加速 (加速国际源访问)
source /etc/network_turbo

# 使用清华镜像重试
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# vLLM 版本冲突
pip install vllm --upgrade -i https://pypi.tuna.tsinghua.edu.cn/simple
# 或指定版本
pip install vllm==0.6.0 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 9.5 Pipeline 报错

**症状**: `Pipeline 失败 (exit code 1)`

```bash
# 开启详细日志重跑
python scripts/run.py -v 2>&1 | tee pipeline.log

# 常见错误及解决:
# 1. "Connection refused" → vLLM 未启动, 先启动 vLLM
# 2. "Model not found"   → 模型名不匹配, 用 curl 检查 /v1/models
# 3. "facts 文件不存在"  → 检查 config/facts_v2.json 路径
# 4. "template 不存在"   → 检查 templates/template.docx
```

### 9.6 图表中文乱码

**症状**: matplotlib 图表显示方块

```bash
# 安装中文字体
apt-get update && apt-get install -y fonts-wqy-zenhei fonts-noto-cjk

# 清理 matplotlib 缓存
rm -rf ~/.cache/matplotlib

# 验证
python -c "
import matplotlib.font_manager as fm
fonts = [f.name for f in fm.fontManager.ttflist if 'Hei' in f.name or 'CJK' in f.name]
print(f'中文字体: {fonts[:5]}')
"
```

### 9.7 embedding 模型下载失败

**症状**: `embedding 模型预下载失败 (RAG 首次查询时会重试)`

```bash
# 手动下载
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/root/autodl-tmp/LLM/huggingface
python -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
print('OK')
"

# 如果镜像也不行, RAG 会自动降级到 ChromaDB 默认 embedding
# 不影响报告生成, 只是 RAG 检索质量略低
```

### 9.8 VL 模型未启动 (非致命)

**症状**: `VL 模型启动失败, 将使用 fallback 验证`

```
这不是致命错误。
- Drawing Agent 的图片验证会降级为文件大小检查 (>10KB 即通过)
- 措施图仍然会生成, 只是缺少 VL 质量评分
- 如果不需要 Drawing Agent 的 VL 验证, 可以用 --no-vl 参数
```

---

## 10. 架构概览

### 10.1 系统架构

```
┌─────────────────────────────────────────────────────┐
│                 CLI 入口: scripts/run.py             │
│                         ↓                            │
│              Pipeline (17 步流水线)                    │
│                         ↓                            │
│    ┌────────┬──────────┬──────────┬─────────┐       │
│    │Planner │  Writer  │ Drawing  │ Auditor │       │
│    │(6工具) │ (4工具)  │ (4工具)  │ (3工具) │       │
│    └────┬───┴────┬─────┴────┬─────┴────┬────┘       │
│         └────────┴──────────┴──────────┘             │
│                         ↓                            │
│    ┌────────────────────────────────────────┐        │
│    │        vLLM OpenAI-compatible API      │        │
│    │  Text: localhost:8000 (GPU 0,1, TP=2)  │        │
│    │  VL:   localhost:8001 (GPU 2,3, TP=2)  │        │
│    └────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────┘
```

### 10.2 17 步 Pipeline

| 步骤 | 名称 | 说明 | 需要 LLM |
|------|------|------|----------|
| 1 | load_config | 加载项目配置 (facts_v2.json) | - |
| 2 | preprocess | 数据预处理 + RAG 初始化 | - |
| 3 | spatial_analysis | GIS 空间分析 (子进程隔离) | VL |
| 4 | calc_earthwork | 土石方计算 | - |
| 5 | calc_erosion | 水土流失预测 | - |
| 6 | run_planner | 措施规划师 Agent (6 工具) | Text |
| 7 | calc_cost | 投资估算 | - |
| 8 | calc_benefit | 效益分析 | - |
| 9 | assemble | 229 标签装配 | - |
| 10 | run_writer | 撰稿 Agent (4 工具) | Text |
| 11 | generate_charts | 4 张数据图表 | - |
| 12 | generate_measure_maps | 措施图 (Drawing Agent → fallback) | Text+VL |
| 13 | render_draft | docxtpl 模板渲染 (初稿) | - |
| 14 | run_auditor | 审计 Agent (3 工具) | Text |
| 15 | retry_if_needed | 不合格章节重写 (最多3轮) | Text |
| 16 | final_render | 最终渲染 (图表+措施图插入) | - |
| 17 | package_output | 打包输出 | - |

### 10.3 模型量化说明

| 模型 | 量化 | 显存 | max-model-len | 用途 |
|------|------|------|---------------|------|
| Qwen2.5-72B-Instruct-GPTQ-Int8 | INT8 | ~36GB×2 | 32768 | 文本: 规划/写作/审计 |
| Qwen2.5-VL-72B-Instruct-GPTQ-Int8 | INT8 | ~36GB×2 | 16384 | 视觉: 空间分析/图片验证 |

> INT8 vs FP16: INT8 显存减半 (72B→~72GB vs ~144GB), 质量损失 <1%, 推理速度略快。

---

## 附录 A: 完整复制粘贴版

### 首次部署 (一键)

```bash
# === SSH 登录 AutoDL 后 ===
cd /root/autodl-tmp/swc-report
python autodl_start.py --cli
# 等待完成, 报告在 data/output/report.docx
```

### 首次部署 (手动)

```bash
# === SSH 登录 AutoDL 后 ===

# 1. 环境
cd /root/autodl-tmp/swc-report
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/root/autodl-tmp/LLM/huggingface
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install vllm -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 下载模型
modelscope download --model Qwen/Qwen2.5-72B-Instruct-GPTQ-Int8 \
  --local_dir /root/autodl-tmp/LLM/Qwen2.5-72B-Instruct-GPTQ-Int8
modelscope download --model Qwen/Qwen2.5-VL-72B-Instruct-GPTQ-Int8 \
  --local_dir /root/autodl-tmp/LLM/Qwen2.5-VL-72B-Instruct-GPTQ-Int8

# 3. embedding 模型
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

# 4. 安装中文字体
apt-get update -qq && apt-get install -y -qq fonts-wqy-zenhei fonts-noto-cjk
rm -rf ~/.cache/matplotlib

# 5. 启动 vLLM (后台)
bash scripts/start_vllm_all.sh &

# 6. 等 vLLM 就绪 (出现 Uvicorn running)
sleep 180
curl -s http://localhost:8000/v1/models
curl -s http://localhost:8001/v1/models

# 7. 生成报告
python scripts/run.py -v
```

### 再次运行 (模型已下载)

```bash
cd /root/autodl-tmp/swc-report
python autodl_start.py --cli
# 跳过下载, 直接启动 vLLM + Pipeline
```
