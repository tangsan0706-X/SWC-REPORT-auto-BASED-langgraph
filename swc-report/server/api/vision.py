"""视觉模型 (VL) 文档处理 API 端点。"""

import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

import src.settings as settings


class VLRequest(BaseModel):
    project_id: str | None = None
    file_names: list[str] | None = None

router = APIRouter(prefix="/api/vision", tags=["vision"])

# 上传文件存储目录
UPLOAD_DIR = settings.DATA_DIR / "uploads"


def _ensure_upload_dir(project_id: str | None = None) -> Path:
    """确保上传目录存在，返回目录路径。"""
    d = UPLOAD_DIR / (project_id or "default")
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/health")
async def vl_health():
    """检查 VL 模型是否可达。"""
    try:
        url = f"{settings.VL_URL}/models"
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        models = [m["id"] for m in data.get("data", [])]
        return {
            "status": "ok",
            "vl_reachable": True,
            "vl_models": models,
            "vl_url": settings.VL_URL,
        }
    except Exception as e:
        return {
            "status": "error",
            "vl_reachable": False,
            "message": f"VL 不可达 ({settings.VL_URL}): {e}",
        }


@router.post("/upload")
async def upload_documents(files: list[UploadFile] = File(...),
                           project_id: str | None = Query(None)):
    """上传项目文档文件。

    支持 JPG/PNG/BMP/PDF/DOC/DWG/DXF/SHP/GeoJSON 等格式。
    返回已上传文件列表和分类结果。
    """
    upload_dir = _ensure_upload_dir(project_id)
    saved_files: list[dict[str, str]] = []

    for f in files:
        if not f.filename:
            continue
        dest = upload_dir / f.filename
        with open(dest, "wb") as out:
            content = await f.read()
            out.write(content)
        saved_files.append({
            "name": f.filename,
            "path": str(dest),
            "size": len(content),
        })

    # 分类
    from src.vision import classify_documents
    all_paths = [Path(f["path"]) for f in saved_files]
    categories = classify_documents(all_paths)
    cat_result = {k: [p.name for p in v] for k, v in categories.items()}

    return {
        "uploaded": len(saved_files),
        "files": saved_files,
        "categories": cat_result,
    }


@router.post("/extract")
async def extract_info(req: VLRequest = VLRequest()):
    """使用 VL 模型从已上传文档中提取项目信息。"""
    upload_dir = _ensure_upload_dir(req.project_id)
    if not upload_dir.exists():
        raise HTTPException(404, f"上传目录不存在: {req.project_id}")

    if req.file_names:
        file_paths = [upload_dir / fn for fn in req.file_names if (upload_dir / fn).exists()]
    else:
        file_paths = _get_processable_files(upload_dir)

    if not file_paths:
        raise HTTPException(400, "没有可处理的文件")

    from src.vision import extract_project_info
    result = extract_project_info(file_paths)
    return {"extracted": result, "files_processed": len(file_paths)}


@router.post("/site-desc")
async def generate_site_desc(req: VLRequest = VLRequest()):
    """使用 VL 模型从图纸/照片生成项目现场描述。"""
    upload_dir = _ensure_upload_dir(req.project_id)
    if not upload_dir.exists():
        raise HTTPException(404, f"上传目录不存在: {req.project_id}")

    if req.file_names:
        file_paths = [upload_dir / fn for fn in req.file_names if (upload_dir / fn).exists()]
    else:
        file_paths = _get_processable_files(upload_dir)

    if not file_paths:
        raise HTTPException(400, "没有可处理的文件")

    from src.vision import generate_site_description
    text = generate_site_description(file_paths)
    return {"site_desc": text, "files_processed": len(file_paths)}


@router.get("/files")
async def list_uploaded_files(project_id: str | None = Query(None)):
    """列出已上传的文件。"""
    upload_dir = _ensure_upload_dir(project_id)
    if not upload_dir.exists():
        return {"files": [], "categories": {}}

    # Shapefile 辅助文件扩展名 (不在列表中显示，但保留在磁盘上)
    _shp_aux = {".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix"}

    files = []
    for f in sorted(upload_dir.iterdir()):
        if not f.is_file():
            continue
        if f.name.startswith("_pdf_page_"):
            continue
        if f.name.endswith("_cad.png"):
            continue
        if f.suffix.lower() in _shp_aux:
            continue
        files.append({
            "name": f.name,
            "size": f.stat().st_size,
            "type": f.suffix.lower(),
        })

    from src.vision import classify_documents
    all_paths = [upload_dir / fi["name"] for fi in files]
    categories = classify_documents(all_paths)
    cat_result = {k: [p.name for p in v] for k, v in categories.items()}

    return {"files": files, "categories": cat_result}


@router.delete("/files")
async def clear_uploaded_files(project_id: str | None = Query(None)):
    """清空上传文件。"""
    upload_dir = _ensure_upload_dir(project_id)
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)
    return {"ok": True}


@router.post("/load-sample")
async def load_sample_data(sample_name: str = "金石博雅园"):
    """加载内置样本数据 (复制到上传目录)。"""
    sample_dir = settings.INPUT_DIR / sample_name
    if not sample_dir.exists():
        raise HTTPException(404, f"样本数据不存在: {sample_name}")

    upload_dir = _ensure_upload_dir("sample")
    # 清空现有
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 递归复制所有可处理文件 (扁平化到上传目录)
    copied = 0
    for src_file in sample_dir.rglob("*"):
        if src_file.is_file() and src_file.suffix.lower() in {
            ".jpg", ".jpeg", ".png", ".bmp", ".pdf", ".doc", ".docx",
            ".dwg", ".dxf", ".shp", ".shx", ".dbf", ".prj", ".cpg",
            ".geojson", ".gpkg",
        }:
            # 加上父目录前缀避免重名
            prefix = src_file.parent.name
            dest_name = f"{prefix}_{src_file.name}" if prefix != sample_name else src_file.name
            dest = upload_dir / dest_name
            shutil.copy2(src_file, dest)
            copied += 1

    # 分类
    from src.vision import classify_documents
    all_paths = [f for f in upload_dir.iterdir() if f.is_file()]
    categories = classify_documents(all_paths)
    cat_result = {k: [p.name for p in v] for k, v in categories.items()}

    return {
        "sample": sample_name,
        "copied": copied,
        "categories": cat_result,
    }


@router.post("/cad-convert")
async def convert_cad_files(req: VLRequest = VLRequest()):
    """将 CAD 文件 (DWG/DXF) 转换为 PNG，可选送入 VL 分析。

    转换后的 PNG 会保存在上传目录中，并可在后续的 extract/site-desc 中使用。
    """
    upload_dir = _ensure_upload_dir(req.project_id)
    cad_exts = {".dwg", ".dxf"}

    if req.file_names:
        cad_files = [upload_dir / fn for fn in req.file_names
                     if (upload_dir / fn).exists() and Path(fn).suffix.lower() in cad_exts]
    else:
        cad_files = [f for f in sorted(upload_dir.iterdir())
                     if f.is_file() and f.suffix.lower() in cad_exts]

    if not cad_files:
        raise HTTPException(400, "没有可处理的 CAD 文件 (DWG/DXF)")

    from src.cad import batch_convert_cad
    results = batch_convert_cad(cad_files, output_dir=upload_dir)

    converted = []
    errors = []
    for r in results:
        if r["status"] == "ok":
            converted.append({
                "source": r["source"],
                "png": r["png"].name if r["png"] else None,
                "message": r["message"],
            })
        else:
            errors.append({"source": r["source"], "message": r["message"]})

    return {
        "converted": len(converted),
        "errors": len(errors),
        "results": converted,
        "error_details": errors,
    }


@router.post("/gis-validate")
async def validate_gis_zones(req: VLRequest = VLRequest()):
    """用 GIS 数据 (SHP/GeoJSON) 校验分区面积。

    将 GIS 中计算的分区面积与当前 facts.json 中的 zones 进行比对，
    检查面积偏差是否在容差范围内 (默认 5%)。
    """
    upload_dir = _ensure_upload_dir(req.project_id)
    gis_exts = {".shp", ".geojson", ".gpkg"}

    if req.file_names:
        gis_files = [upload_dir / fn for fn in req.file_names
                     if (upload_dir / fn).exists() and Path(fn).suffix.lower() in gis_exts]
    else:
        gis_files = [f for f in sorted(upload_dir.iterdir())
                     if f.is_file() and f.suffix.lower() in gis_exts]

    if not gis_files:
        raise HTTPException(400, "没有可处理的 GIS 文件 (SHP/GeoJSON)")

    from src.gis import extract_zones_from_shp, validate_zones, render_zones_to_png

    # 提取 GIS 分区
    gis_zones = extract_zones_from_shp(gis_files[0])
    if not gis_zones:
        raise HTTPException(400, "GIS 文件中未提取到有效分区数据")

    # 读取当前 facts 中的 zones
    facts_zones = []
    facts_path = settings.INPUT_DIR / "facts_v2.json"
    if facts_path.exists():
        import json as _json
        facts_data = _json.loads(facts_path.read_text(encoding="utf-8"))
        facts_zones = facts_data.get("zones", [])

    # 校验
    validation = validate_zones(gis_zones, facts_zones) if facts_zones else None

    # 生成分区图
    zone_png = render_zones_to_png(gis_files[0], upload_dir / "gis_zones.png")

    return {
        "gis_zones": gis_zones,
        "validation": validation,
        "zone_png": zone_png.name if zone_png else None,
        "gis_file": gis_files[0].name,
    }


@router.post("/gis-extract-zones")
async def extract_gis_zones(req: VLRequest = VLRequest()):
    """从 GIS 文件提取分区列表，可直接导入到表单中替换手动填写的分区。"""
    upload_dir = _ensure_upload_dir(req.project_id)
    gis_exts = {".shp", ".geojson", ".gpkg"}

    if req.file_names:
        gis_files = [upload_dir / fn for fn in req.file_names
                     if (upload_dir / fn).exists() and Path(fn).suffix.lower() in gis_exts]
    else:
        gis_files = [f for f in sorted(upload_dir.iterdir())
                     if f.is_file() and f.suffix.lower() in gis_exts]

    if not gis_files:
        raise HTTPException(400, "没有可处理的 GIS 文件 (SHP/GeoJSON)")

    from src.gis import extract_zones_from_shp
    gis_zones = extract_zones_from_shp(gis_files[0])

    # 转换为 facts.json 的 zones 格式
    facts_zones = []
    for gz in gis_zones:
        facts_zones.append({
            "name": gz["name"],
            "area_hm2": gz["area_hm2"],
            "excavation_m3": 0,
            "fill_m3": 0,
            "description": f"GIS导入 (原名: {gz['original_name']}, {gz['feature_count']}个要素)",
        })

    return {
        "zones": facts_zones,
        "total_area_hm2": round(sum(z["area_hm2"] for z in facts_zones), 4),
        "gis_file": gis_files[0].name,
    }


def _get_processable_files(directory: Path) -> list[Path]:
    """获取目录中可处理的文件 (图片 + PDF + CAD)。"""
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".pdf", ".dwg", ".dxf"}
    return [f for f in sorted(directory.iterdir())
            if f.is_file() and f.suffix.lower() in exts
            and not f.name.startswith("_pdf_page_")
            and not f.name.endswith("_cad.png")]
