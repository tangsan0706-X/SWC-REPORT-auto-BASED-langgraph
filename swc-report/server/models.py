"""Pydantic 数据模型。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class RunStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    error = "error"


# ── Request ──────────────────────────────────────────────────

class CreateRunRequest(BaseModel):
    use_llm: bool = True
    facts: dict | None = None       # 内联 facts JSON (优先级高于服务端文件)
    measures: list[dict] | None = None  # 内联 measures (优先级高于服务端文件)


class UpdateSettingsRequest(BaseModel):
    vllm_url: str | None = None
    model_name: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None


# ── Response ─────────────────────────────────────────────────

class RunSummary(BaseModel):
    id: str
    status: RunStatus
    created_at: str
    finished_at: str | None = None
    project_name: str = ""
    total_score: float = 0
    use_llm: bool = True
    error_message: str | None = None


class RunDetail(RunSummary):
    output_dir: str | None = None
    steps: list[dict[str, Any]] = []


class SettingsResponse(BaseModel):
    vllm_url: str
    model_name: str
    max_tokens: int
    temperature: float


class HealthResponse(BaseModel):
    status: str  # "ok" | "error"
    llm_reachable: bool
    llm_models: list[str] = []
    message: str = ""


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []


# ── Knowledge ────────────────────────────────────────────────

class FileInfo(BaseModel):
    name: str
    size_kb: float
    modified: str          # ISO datetime
    file_type: str = ""    # 文件扩展名


class GenerateStatus(BaseModel):
    status: str            # idle / running / done / error
    message: str = ""
    updated_at: str = ""


class ReindexStatus(BaseModel):
    status: str            # idle / running / done / error
    message: str = ""
