"""一键启动 Web 服务 (双端口)。

本机开发:
    python run_server.py          # 用户端 :8080 + 管理端 :8081
    python run_server.py --dev    # 同上, 带热重载

单端口模式 (兼容):
    python run_server.py --single # 仅启动 :8080 (包含全部路由)

生产模式 (前端已构建):
    cd web && npm run build       # 构建前端到 web/dist/
    python run_server.py          # 用户端 :8080 托管前端, 管理端 :8081
"""

import subprocess
import sys
import os

# ── 项目根目录 ──
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

# ── 检查并安装后端依赖 ──
REQUIRED = ["fastapi", "uvicorn", "multipart"]
INSTALL_MAP = {"multipart": "python-multipart"}

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

# ── 启动 ──
import uvicorn

if "--single" in sys.argv:
    # 单端口兼容模式
    print("=" * 50)
    print("  水土保持方案自动生成系统 — Web 服务 (单端口)")
    print("  后端: http://localhost:8080")
    print("  前端: http://localhost:5173 (npm run dev)")
    print("=" * 50)

    uvicorn.run(
        "server.app:app",
        host="0.0.0.0",
        port=8080,
        reload="--dev" in sys.argv,
        log_level="info",
    )
else:
    # 双端口模式
    import asyncio

    print("=" * 50)
    print("  水土保持方案自动生成系统 — Web 服务 (双端口)")
    print("  用户端: http://localhost:8080  (报告生成/项目数据)")
    print("  管理端: http://localhost:8081  (知识库/LLM设置)")
    print("  前端:   http://localhost:5173  (npm run dev)")
    print("=" * 50)

    is_dev = "--dev" in sys.argv

    async def main():
        user_config = uvicorn.Config(
            "server.app:user_app",
            host="0.0.0.0",
            port=8080,
            reload=is_dev,
            log_level="info",
        )
        admin_config = uvicorn.Config(
            "server.app:admin_app",
            host="0.0.0.0",
            port=8081,
            reload=is_dev,
            log_level="info",
        )

        user_server = uvicorn.Server(user_config)
        admin_server = uvicorn.Server(admin_config)

        await asyncio.gather(
            user_server.serve(),
            admin_server.serve(),
        )

    asyncio.run(main())
