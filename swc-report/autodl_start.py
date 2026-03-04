#!/usr/bin/env python3
"""AutoDL 一键启动脚本 — 水土保持方案自动编制系统 v1.0

用法:
    python autodl_start.py                 # 自动下载模型 + 安装依赖 + vLLM + Web UI
    python autodl_start.py --cli           # 自动下载模型 + vLLM + CLI 跑 pipeline
    python autodl_start.py --web-only      # 仅 Web UI (假设 vLLM 已启动)
    python autodl_start.py --cli-only      # 仅 CLI (假设 vLLM 已启动)
    python autodl_start.py --install       # 仅安装依赖 + 下载模型
    python autodl_start.py --check         # 仅检查环境

环境要求:
    - AutoDL A800×4 (或 A100×4, 80GB×4)
    - Python 3.10+
    - 模型自动从 ModelScope 下载
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent
LLM_BASE = Path("/root/autodl-tmp/LLM")

MODELS = {
    "text": {
        "name": "Qwen2.5-72B-Instruct",
        "path": LLM_BASE / "Qwen2.5-72B-Instruct-GPTQ-Int8",
        "modelscope_id": "Qwen/Qwen2.5-72B-Instruct-GPTQ-Int8",
        "port": 8000,
        "tp": 1,
        "max_len": 16384,
        "quant": "--quantization gptq",
        "gpus": "0",  # 2卡机: 每卡96GB, 单卡装72B-INT8
    },
    "vl": {
        "name": "Qwen2-VL-72B-Instruct-GPTQ-Int8",
        "path": LLM_BASE / "Qwen2-VL-72B-Instruct-GPTQ-Int8",
        "modelscope_id": "Qwen/Qwen2-VL-72B-Instruct-GPTQ-Int8",
        "port": 8001,
        "tp": 1,
        "max_len": 16384,
        "quant": "--quantization gptq",
        "gpus": "1",  # 2卡机: VL 用第二张卡
    },
}

# 子进程列表 (用于优雅退出)
_procs: list[subprocess.Popen] = []


# ── 工具函数 ──────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def run_cmd(cmd: str, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    """执行 shell 命令并返回结果。"""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          timeout=timeout, check=check, cwd=str(PROJECT_DIR))


def is_port_open(port: int) -> bool:
    """检查端口是否可连通 (HTTP)。"""
    import urllib.request
    try:
        urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=3)
        return True
    except Exception:
        return False


def wait_for_port(port: int, name: str, timeout: int = 300) -> bool:
    """等待服务启动。"""
    log(f"等待 {name} (port {port}) 就绪...")
    start = time.time()
    while time.time() - start < timeout:
        if is_port_open(port):
            elapsed = int(time.time() - start)
            log(f"{name} 就绪 ({elapsed}s)")
            return True
        time.sleep(5)
    log(f"{name} 启动超时 ({timeout}s)", "ERROR")
    return False


def graceful_exit(signum=None, frame=None):
    """优雅退出: 终止所有子进程。"""
    log("收到退出信号, 正在清理...")
    for p in _procs:
        try:
            p.terminate()
            p.wait(timeout=10)
        except Exception:
            p.kill()
    sys.exit(0)


# ── 模型下载 ──────────────────────────────────────────────────

def _ensure_modelscope():
    """确保 modelscope SDK 已安装。"""
    try:
        import modelscope
        return True
    except ImportError:
        log("安装 modelscope SDK...")
        result = run_cmd(
            f"{sys.executable} -m pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet",
            check=False, timeout=300,
        )
        if result.returncode != 0:
            log(f"modelscope 安装失败: {result.stderr[-300:]}", "ERROR")
            return False
        return True


def download_model(model_key: str) -> bool:
    """从 ModelScope 下载模型到本地。"""
    cfg = MODELS[model_key]
    dest = cfg["path"]
    ms_id = cfg["modelscope_id"]

    if dest.exists() and any(dest.iterdir()):
        # 检查是否有模型文件 (safetensors / bin)
        has_weights = (
            list(dest.glob("*.safetensors"))
            or list(dest.glob("*.bin"))
            or list(dest.glob("*.gguf"))
        )
        if has_weights:
            log(f"模型 [{model_key}] 已存在: {dest}")
            return True
        log(f"模型目录存在但无权重文件, 重新下载: {dest}", "WARN")

    if not _ensure_modelscope():
        return False

    log(f"下载模型 [{model_key}]: {ms_id}")
    log(f"  目标: {dest}")
    log(f"  来源: https://modelscope.cn/models/{ms_id}")
    log(f"  (72B-INT8 约 40GB, 预计 10~30 分钟)")

    dest.parent.mkdir(parents=True, exist_ok=True)

    # 用 modelscope Python API 下载 (支持断点续传)
    download_script = (
        f"from modelscope import snapshot_download; "
        f"snapshot_download('{ms_id}', local_dir='{dest}')"
    )
    cmd = [sys.executable, "-c", download_script]
    log(f"  snapshot_download('{ms_id}', local_dir='{dest}')")

    # 实时输出下载进度
    proc = subprocess.Popen(
        cmd, cwd=str(PROJECT_DIR),
        stdout=sys.stdout, stderr=sys.stderr,
    )
    proc.wait()

    if proc.returncode != 0:
        log(f"模型下载失败 (exit code {proc.returncode})", "ERROR")
        log("手动下载方法:")
        log(f"  pip install modelscope")
        log(f"  modelscope download --model {ms_id} --local_dir {dest}")
        return False

    log(f"模型 [{model_key}] 下载完成")
    return True


def download_all_models(with_vl: bool = True) -> bool:
    """下载所有需要的模型。"""
    # 文本模型 (必须)
    if not download_model("text"):
        return False

    # 视觉模型 (可选)
    if with_vl:
        if not download_model("vl"):
            log("VL 模型下载失败, 将跳过视觉验证功能", "WARN")

    return True


# ── 环境检查 ──────────────────────────────────────────────────

def check_python():
    v = sys.version_info
    if v < (3, 10):
        log(f"Python {v.major}.{v.minor} 不满足要求 (需 3.10+)", "ERROR")
        return False
    log(f"Python {v.major}.{v.minor}.{v.micro}")
    return True


def check_gpu():
    try:
        result = run_cmd("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader", check=False)
        if result.returncode != 0:
            log("nvidia-smi 失败, 无法检测 GPU", "WARN")
            return False
        gpus = result.stdout.strip().split("\n")
        log(f"GPU: {len(gpus)} 张")
        for i, g in enumerate(gpus):
            log(f"  [{i}] {g.strip()}")
        return len(gpus) >= 2
    except Exception as e:
        log(f"GPU 检测失败: {e}", "WARN")
        return False


def check_models():
    ok = True
    for key, cfg in MODELS.items():
        p = cfg["path"]
        if p.exists() and any(p.glob("*.safetensors")) or any(p.glob("*.bin") if p.exists() else []):
            size_gb = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / (1024**3)
            log(f"模型 [{key}] {cfg['name']}: {p} ({size_gb:.1f}GB)")
        else:
            log(f"模型 [{key}] 不存在: {p} (将自动下载)", "WARN")
            ok = False
    return ok


def check_vllm():
    try:
        result = run_cmd(f"{sys.executable} -c \"import vllm; print(vllm.__version__)\"", check=False)
        if result.returncode == 0:
            log(f"vLLM: {result.stdout.strip()}")
            return True
        log("vLLM 未安装", "WARN")
        return False
    except Exception:
        log("vLLM 检测失败", "WARN")
        return False


def check_env():
    """全面环境检查。"""
    log("=" * 50)
    log("环境检查")
    log("=" * 50)
    results = {
        "Python": check_python(),
        "GPU": check_gpu(),
        "Models": check_models(),
        "vLLM": check_vllm(),
        "Project": (PROJECT_DIR / "src" / "pipeline.py").exists(),
    }

    # 检查关键 Python 包
    missing = []
    for pkg in ["openai", "docxtpl", "docx", "chromadb", "matplotlib",
                "pandas", "numpy", "fastapi", "uvicorn"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        log(f"缺少 Python 包: {missing}", "WARN")
        results["Packages"] = False
    else:
        log("Python 依赖: OK")
        results["Packages"] = True

    # 检查中文字体
    try:
        import matplotlib.font_manager as fm
        cjk_fonts = [f.name for f in fm.fontManager.ttflist
                     if any(k in f.name for k in ("SimHei", "Hei", "WenQuanYi", "Noto Sans CJK"))]
        if cjk_fonts:
            log(f"中文字体: {list(set(cjk_fonts))[:3]}")
        else:
            log("缺少中文字体, 图表可能乱码", "WARN")
    except Exception:
        pass

    log("-" * 50)
    all_ok = all(results.values())
    for k, v in results.items():
        status = "OK" if v else "FAIL"
        log(f"  {k}: {status}")
    log("-" * 50)
    return all_ok


# ── 安装依赖 ──────────────────────────────────────────────────

def install_deps():
    """安装 Python 依赖。"""
    log("安装 Python 依赖...")
    req = PROJECT_DIR / "requirements.txt"
    if not req.exists():
        log("requirements.txt 不存在", "ERROR")
        return False

    # 清华镜像
    mirror = "-i https://pypi.tuna.tsinghua.edu.cn/simple"
    cmd = f"{sys.executable} -m pip install -r {req} {mirror} --quiet"
    log(f"  {cmd}")
    result = run_cmd(cmd, check=False, timeout=600)
    if result.returncode != 0:
        log(f"依赖安装失败:\n{result.stderr[-500:]}", "ERROR")
        return False

    # vLLM (如果缺失)
    try:
        import vllm
    except ImportError:
        log("安装 vLLM...")
        result = run_cmd(
            f"{sys.executable} -m pip install vllm {mirror} --quiet",
            check=False, timeout=600,
        )
        if result.returncode != 0:
            log("vLLM 安装失败, 请手动安装: pip install vllm", "WARN")

    # 中文字体 (如果缺失)
    try:
        import matplotlib.font_manager as fm
        has_cjk = any(
            any(k in f.name for k in ("SimHei", "Hei", "WenQuanYi", "Noto Sans CJK"))
            for f in fm.fontManager.ttflist
        )
        if not has_cjk:
            log("安装中文字体...")
            run_cmd(
                "apt-get update -qq && apt-get install -y -qq "
                "fonts-wqy-zenhei fonts-wqy-microhei fonts-noto-cjk 2>/dev/null || true",
                check=False, timeout=120,
            )
            # 清理 matplotlib 字体缓存
            cache_dir = Path.home() / ".cache" / "matplotlib"
            if cache_dir.exists():
                import shutil
                shutil.rmtree(cache_dir, ignore_errors=True)
                log("已清理 matplotlib 字体缓存, 下次运行自动重建")
    except Exception:
        pass

    # 预下载 embedding 模型 (RAG 需要, 走 HF_ENDPOINT 镜像)
    log("预下载 embedding 模型...")
    cmd = (
        f'{sys.executable} -c "'
        f"from sentence_transformers import SentenceTransformer; "
        f"SentenceTransformer("
        f"'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'"
        f')"'
    )
    result = run_cmd(cmd, check=False, timeout=300)
    if result.returncode == 0:
        log("embedding 模型就绪")
    else:
        log("embedding 模型预下载失败 (RAG 首次查询时会重试)", "WARN")

    log("依赖安装完成")
    return True


# ── 启动 vLLM ─────────────────────────────────────────────────

def start_vllm(model_key: str = "text", gpu_override: str | None = None) -> subprocess.Popen | None:
    """启动 vLLM 服务。

    Args:
        model_key: "text" 或 "vl"
        gpu_override: 手动指定 GPU (如 "0,1")，覆盖默认分配
    """
    cfg = MODELS[model_key]
    port = cfg["port"]

    # 已在运行
    if is_port_open(port):
        log(f"vLLM [{model_key}] 已在 port {port} 运行")
        return None

    # 检查模型
    if not cfg["path"].exists():
        log(f"模型不存在: {cfg['path']}", "ERROR")
        return None

    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", str(cfg["path"]),
        "--served-model-name", cfg["name"],
        "--tensor-parallel-size", str(cfg["tp"]),
        "--max-model-len", str(cfg["max_len"]),
        "--gpu-memory-utilization", "0.90",
        "--port", str(port),
        "--trust-remote-code",
        "--dtype", "auto",
        "--enforce-eager",
    ]
    if cfg["quant"]:
        cmd.extend(cfg["quant"].split())
    # 文本模型需要开启 tool calling 支持 (Agent 工具调用)
    if model_key == "text":
        cmd.extend(["--enable-auto-tool-choice", "--tool-call-parser", "hermes"])

    # GPU 分配: 手动指定 > 默认分配 (text→0,1  vl→2,3)
    gpu_ids = gpu_override or cfg.get("gpus", "")
    env = os.environ.copy()
    if gpu_ids:
        env["CUDA_VISIBLE_DEVICES"] = gpu_ids

    log(f"启动 vLLM [{model_key}]: {cfg['name']} (port {port}, TP={cfg['tp']}, GPU={gpu_ids or 'auto'})")

    # 日志文件
    log_file = PROJECT_DIR / "data" / f"vllm_{model_key}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_file, "w")

    proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env)
    _procs.append(proc)
    log(f"  PID={proc.pid}, 日志: {log_file}")
    return proc


def start_all_vllm(with_vl: bool = True, gpu_override: str | None = None) -> bool:
    """启动文本 + 视觉模型。

    Args:
        with_vl: 是否启动 VL 模型
        gpu_override: 手动 GPU 指定 (如 "0,1,2,3")，覆盖默认分配
    """
    # 文本模型 (必须)
    text_proc = start_vllm("text", gpu_override=gpu_override)
    if text_proc is not None:
        if not wait_for_port(MODELS["text"]["port"], "Text LLM", timeout=300):
            return False

    # 视觉模型 (可选)
    if with_vl and MODELS["vl"]["path"].exists():
        vl_proc = start_vllm("vl", gpu_override=gpu_override)
        if vl_proc is not None:
            if not wait_for_port(MODELS["vl"]["port"], "VL Model", timeout=300):
                log("VL 模型启动失败, 将使用 fallback 验证", "WARN")
    elif with_vl:
        log("VL 模型不存在, 跳过", "WARN")

    return True


# ── 启动 Web UI ───────────────────────────────────────────────

def start_web():
    """启动 FastAPI Web 服务。"""
    log("启动 Web UI (用户端 :8080 + 管理端 :8081)...")
    cmd = [sys.executable, str(PROJECT_DIR / "run_server.py")]
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_DIR))
    _procs.append(proc)
    log(f"Web UI PID={proc.pid}")
    log("")
    log("=" * 50)
    log("系统已启动!")
    log("  用户端:  http://localhost:8080  (报告生成)")
    log("  管理端:  http://localhost:8081  (知识库/设置)")
    log("  AutoDL:  查看「自定义服务」获取外网地址")
    log("  停止:    Ctrl+C")
    log("=" * 50)
    return proc


# ── 运行 CLI Pipeline ────────────────────────────────────────

def run_cli(verbose: bool = True):
    """运行 CLI Pipeline。"""
    log("启动 Pipeline (CLI 模式)...")
    cmd = [sys.executable, str(PROJECT_DIR / "scripts" / "run.py")]
    if verbose:
        cmd.append("-v")

    log(f"  命令: {' '.join(cmd)}")
    log("-" * 50)

    result = subprocess.run(cmd, cwd=str(PROJECT_DIR))

    if result.returncode == 0:
        output = PROJECT_DIR / "data" / "output" / "report.docx"
        log("")
        log("=" * 50)
        log(f"Pipeline 完成! 报告: {output}")
        log("=" * 50)
    else:
        log(f"Pipeline 失败 (exit code {result.returncode})", "ERROR")

    return result.returncode


# ── 主入口 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="水土保持方案自动编制系统 — AutoDL 一键启动",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python autodl_start.py              # 全自动: 下载模型 + 安装依赖 + vLLM + Web UI
  python autodl_start.py --cli        # 全自动: 下载模型 + vLLM + CLI Pipeline
  python autodl_start.py --web-only   # 仅 Web (vLLM 已启动)
  python autodl_start.py --check      # 环境检查
  python autodl_start.py --install    # 安装依赖 + 下载模型
  python autodl_start.py --no-vl      # 不用视觉模型 (省显存, 少下载 40GB)
        """,
    )
    parser.add_argument("--cli", action="store_true", help="CLI 模式 (启动 vLLM + 跑 Pipeline)")
    parser.add_argument("--web-only", action="store_true", help="仅启动 Web UI (假设 vLLM 已运行)")
    parser.add_argument("--cli-only", action="store_true", help="仅跑 CLI (假设 vLLM 已运行)")
    parser.add_argument("--install", action="store_true", help="仅安装依赖 + 下载模型")
    parser.add_argument("--check", action="store_true", help="仅检查环境")
    parser.add_argument("--no-vl", action="store_true", help="不启动视觉模型 (仅2卡机器时使用, 4卡请勿加此参数)")
    parser.add_argument("--gpu", type=str, default=None, help="指定 GPU (如 0,1)")
    args = parser.parse_args()

    # HuggingFace 中国镜像 (AutoDL 无法直连海外)
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HOME", str(LLM_BASE / "huggingface"))

    # 注册信号处理
    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    # GPU 选择
    if args.gpu:
        log(f"手动指定 GPU: {args.gpu} (覆盖默认分配)")

    log("水土保持方案自动编制系统 v1.0")
    log(f"项目目录: {PROJECT_DIR}")

    # ── 仅检查 ──
    if args.check:
        check_env()
        sys.exit(0)

    # ── 仅 Web ──
    if args.web_only:
        web = start_web()
        web.wait()
        return

    # ── 仅 CLI ──
    if args.cli_only:
        sys.exit(run_cli())

    # ── 仅安装 ──
    if args.install:
        install_deps()
        download_all_models(with_vl=not args.no_vl)
        check_env()
        return

    # ── 完整模式: 检查 → 安装 → 下载模型 → vLLM → Web/CLI ──
    check_env()

    # 安装依赖 (缺啥装啥)
    missing_pkgs = []
    for pkg in ["openai", "docxtpl", "docx", "chromadb", "matplotlib",
                "pandas", "numpy", "fastapi", "uvicorn", "vllm"]:
        try:
            __import__(pkg)
        except ImportError:
            missing_pkgs.append(pkg)
    if missing_pkgs:
        log(f"缺少依赖: {missing_pkgs}, 自动安装...")
        install_deps()

    # 下载模型 (没有才下载)
    if not MODELS["text"]["path"].exists():
        log("文本模型不存在, 开始下载...")
        if not download_model("text"):
            log("文本模型下载失败, 无法继续", "ERROR")
            sys.exit(1)

    if not args.no_vl and not MODELS["vl"]["path"].exists():
        log("视觉模型不存在, 开始下载...")
        download_model("vl")  # VL 是可选的, 失败不阻塞

    # 启动 vLLM
    if not start_all_vllm(with_vl=not args.no_vl, gpu_override=args.gpu):
        log("vLLM 启动失败", "ERROR")
        graceful_exit()
        return

    if args.cli:
        # CLI 模式
        code = run_cli()
        graceful_exit()
        sys.exit(code)
    else:
        # Web 模式 (默认)
        web = start_web()
        try:
            web.wait()
        except KeyboardInterrupt:
            graceful_exit()


if __name__ == "__main__":
    main()
