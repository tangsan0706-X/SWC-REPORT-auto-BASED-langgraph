"""系统管理 API 端点。

拆分为:
  - user_router: health_check, get_presets (用户端 8080)
  - admin_router: get_settings, update_settings (管理端 8081)
  - router: 保留兼容性 (包含全部端点)
"""

from __future__ import annotations

import urllib.request
import json
import platform

from fastapi import APIRouter

import src.settings as settings
from server.models import HealthResponse, SettingsResponse, UpdateSettingsRequest

# ── 用户端路由 (port 8080) ──
user_router = APIRouter(prefix="/api/system", tags=["system"])


@user_router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查 — 测试 LLM 是否可达。"""
    try:
        url = f"{settings.VLLM_URL}/models"
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        models = [m["id"] for m in data.get("data", [])]
        return HealthResponse(
            status="ok",
            llm_reachable=True,
            llm_models=models,
            message=f"LLM 在线 ({settings.VLLM_URL})，可用模型: {', '.join(models)}",
        )
    except Exception as e:
        return HealthResponse(
            status="error",
            llm_reachable=False,
            message=f"LLM 不可达 ({settings.VLLM_URL}): {e}",
        )


@user_router.get("/presets")
async def get_presets():
    """获取常用配置预设。"""
    return [
        {
            "name": "AutoDL 72B-INT8 (推荐)",
            "vllm_url": "http://localhost:8000/v1",
            "model_name": "Qwen2.5-72B-Instruct",
        },
        {
            "name": "AutoDL 72B-FP16",
            "vllm_url": "http://localhost:8000/v1",
            "model_name": "Qwen2.5-72B-Instruct",
        },
        {
            "name": "AutoDL 7B",
            "vllm_url": "http://localhost:8000/v1",
            "model_name": "Qwen2.5-7B-Instruct",
        },
        {
            "name": "本机 Ollama 7B",
            "vllm_url": "http://localhost:11434/v1",
            "model_name": "qwen2.5:7b",
        },
    ]


# ── 管理端路由 (port 8081) ──
admin_router = APIRouter(prefix="/api/system", tags=["system"])


@admin_router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """获取当前 LLM 设置。"""
    return SettingsResponse(
        vllm_url=settings.VLLM_URL,
        model_name=settings.VLLM_MODEL_NAME,
        max_tokens=settings.VLLM_MAX_TOKENS,
        temperature=settings.VLLM_TEMPERATURE,
    )


@admin_router.put("/settings", response_model=SettingsResponse)
async def update_settings(req: UpdateSettingsRequest):
    """更新 LLM 设置 (运行时生效)。"""
    if req.vllm_url is not None:
        settings.VLLM_URL = req.vllm_url
    if req.model_name is not None:
        settings.VLLM_MODEL_NAME = req.model_name
    if req.max_tokens is not None:
        settings.VLLM_MAX_TOKENS = req.max_tokens
    if req.temperature is not None:
        settings.VLLM_TEMPERATURE = req.temperature
    return SettingsResponse(
        vllm_url=settings.VLLM_URL,
        model_name=settings.VLLM_MODEL_NAME,
        max_tokens=settings.VLLM_MAX_TOKENS,
        temperature=settings.VLLM_TEMPERATURE,
    )


# ── 兼容: 旧的 router 别名 (指向 user_router, 供旧代码引用) ──
router = user_router
