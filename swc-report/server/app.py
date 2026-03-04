"""FastAPI 应用入口。

双端口架构:
  - user_app (port 8080): pipelines, config, vision, system/health + system/presets
  - admin_app (port 8081): knowledge, system/settings
  - app: 兼容旧的单端口模式 (包含全部路由)
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 确保项目根目录在 path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from server.services.storage import init_db
from server.api import pipelines, config, system, vision, knowledge


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动时初始化 DB。"""
    db_path = _PROJECT_ROOT / "data" / "server.db"
    init_db(db_path)
    yield


def _add_cors(app: FastAPI) -> None:
    """为 app 添加 CORS 中间件。"""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ═══════════════════════════════════════════════════════════════
# User App (port 8080) — 用户端: 报告生成 / 项目数据 / 上传
# ═══════════════════════════════════════════════════════════════

user_app = FastAPI(
    title="水保方案 - 用户端",
    version="1.0.0",
    lifespan=lifespan,
)
_add_cors(user_app)

user_app.include_router(pipelines.router)
user_app.include_router(config.router)
user_app.include_router(vision.router)
user_app.include_router(system.user_router)  # /api/system/health + /api/system/presets


@user_app.get("/api")
async def user_api_root():
    return {"message": "水保方案 - 用户端 API", "version": "1.0.0", "port": 8080}


# 静态文件: 前端构建产物 (仅用户端挂载)
_DIST_DIR = _PROJECT_ROOT / "web" / "dist"
if _DIST_DIR.exists():
    user_app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="static")


# ═══════════════════════════════════════════════════════════════
# Admin App (port 8081) — 管理端: 知识库 / LLM 设置
# ═══════════════════════════════════════════════════════════════

admin_app = FastAPI(
    title="水保方案 - 管理端",
    version="1.0.0",
    lifespan=lifespan,
)
_add_cors(admin_app)

admin_app.include_router(knowledge.router)
admin_app.include_router(system.admin_router)  # /api/system/settings (GET/PUT)


@admin_app.get("/api")
async def admin_api_root():
    return {"message": "水保方案 - 管理端 API", "version": "1.0.0", "port": 8081}


# ═══════════════════════════════════════════════════════════════
# 兼容: 单端口 app (Docker / 测试 / 旧启动方式)
# ═══════════════════════════════════════════════════════════════

app = FastAPI(
    title="水土保持方案自动生成系统",
    version="1.0.0",
    lifespan=lifespan,
)
_add_cors(app)

app.include_router(pipelines.router)
app.include_router(config.router)
app.include_router(system.user_router)
app.include_router(system.admin_router)
app.include_router(vision.router)
app.include_router(knowledge.router)

if _DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="static")


@app.get("/api")
async def api_root():
    return {"message": "水土保持方案自动生成系统 API", "version": "1.0.0"}
