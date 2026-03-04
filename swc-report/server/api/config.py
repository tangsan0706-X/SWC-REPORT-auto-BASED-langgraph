"""项目配置 API 端点。"""

from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, HTTPException, UploadFile, File

import src.settings as settings
from server.models import ValidateResponse

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/facts")
async def get_facts():
    """获取当前 facts.json。"""
    if not settings.FACTS_PATH.exists():
        raise HTTPException(404, "facts.json not found")
    return json.loads(settings.FACTS_PATH.read_text(encoding="utf-8"))


@router.put("/facts")
async def update_facts(data: dict):
    """更新 facts.json。"""
    settings.FACTS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True}


@router.get("/measures")
async def get_measures():
    """获取当前 measures.csv 为 JSON 数组。"""
    if not settings.MEASURES_PATH.exists():
        raise HTTPException(404, "measures.csv not found")
    with open(settings.MEASURES_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


@router.put("/measures")
async def update_measures(data: list[dict]):
    """更新 measures.csv。"""
    if not data:
        raise HTTPException(400, "Empty measures data")
    with open(settings.MEASURES_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    return {"ok": True}


@router.post("/upload/facts")
async def upload_facts(file: UploadFile = File(...)):
    """上传 facts.json 文件。"""
    content = await file.read()
    try:
        data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"Invalid JSON: {e}")
    settings.FACTS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True, "data": data}


@router.post("/upload/measures")
async def upload_measures(file: UploadFile = File(...)):
    """上传 measures.csv 文件。"""
    content = await file.read()
    try:
        text = content.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        raise HTTPException(400, f"Invalid CSV: {e}")
    # 覆盖保存
    with open(settings.MEASURES_PATH, "w", encoding="utf-8", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    return {"ok": True, "count": len(rows)}


@router.post("/validate", response_model=ValidateResponse)
async def validate_config(data: dict):
    """校验 facts 配置完整性。"""
    errors = []
    warnings = []

    required_fields = [
        "project_name", "investor", "location", "project_nature",
        "total_investment_万元", "land_area_hm2", "earthwork",
        "schedule", "zones", "prevention_level",
    ]
    for field in required_fields:
        if field not in data:
            errors.append(f"缺少必填字段: {field}")

    # 校验 zones
    zones = data.get("zones", [])
    if not zones:
        errors.append("至少需要 1 个防治分区 (zones)")
    for i, z in enumerate(zones):
        if "name" not in z:
            errors.append(f"zones[{i}] 缺少 name")
        if "area_hm2" not in z:
            errors.append(f"zones[{i}] 缺少 area_hm2")

    # 校验 earthwork
    ew = data.get("earthwork", {})
    if ew and not ew.get("excavation_m3"):
        warnings.append("earthwork.excavation_m3 为 0 或缺失")

    # 校验 schedule
    sch = data.get("schedule", {})
    if sch and not sch.get("start_date"):
        errors.append("schedule.start_date 缺失")

    return ValidateResponse(valid=len(errors) == 0, errors=errors, warnings=warnings)
