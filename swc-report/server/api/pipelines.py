"""Pipeline 运行 API 端点。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

import src.settings as settings
from server.models import CreateRunRequest, RunSummary, RunDetail
from server.services import storage, runner

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


@router.post("", response_model=RunDetail)
async def create_run(req: CreateRunRequest):
    """创建并启动一次报告生成。"""
    run_id = storage.create_run(use_llm=req.use_llm)

    # 确定输入文件路径
    facts_path = settings.FACTS_PATH
    measures_path = settings.MEASURES_PATH

    # 如果请求中包含内联数据，写入临时文件
    output_dir = settings.OUTPUT_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    if req.facts:
        facts_path = output_dir / "facts_input.json"
        facts_path.write_text(json.dumps(req.facts, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    if req.measures:
        measures_path = output_dir / "measures_input.csv"
        import csv
        with open(measures_path, "w", encoding="utf-8", newline="") as f:
            if req.measures:
                writer = csv.DictWriter(f, fieldnames=req.measures[0].keys())
                writer.writeheader()
                writer.writerows(req.measures)

    # 启动后台任务
    runner.start_run(
        run_id=run_id,
        facts_path=facts_path,
        measures_path=measures_path,
        output_dir=output_dir,
        use_llm=req.use_llm,
    )

    return storage.get_run(run_id)


@router.get("", response_model=list[RunSummary])
async def list_runs():
    """获取运行历史列表。"""
    return storage.list_runs()


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: str):
    """获取运行详情。"""
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/{run_id}/progress")
async def stream_progress(run_id: str):
    """SSE 实时进度流。"""
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    async def event_generator():
        cursor = 0
        while True:
            events = runner.get_events(run_id, after=cursor)
            for evt in events:
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                cursor += 1
            if runner.is_finished(run_id):
                yield f"data: {json.dumps({'step': '__done__', 'status': 'finished'})}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{run_id}/result")
async def download_result(run_id: str):
    """下载 report.docx。"""
    run = storage.get_run(run_id)
    if not run or not run.output_dir:
        raise HTTPException(404, "Run not found or not finished")
    report_path = Path(run.output_dir) / "report.docx"
    if not report_path.exists():
        raise HTTPException(404, "Report file not found")
    return FileResponse(
        str(report_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="report.docx",
    )


@router.get("/{run_id}/draft")
async def download_draft(run_id: str):
    """下载 draft.docx。"""
    run = storage.get_run(run_id)
    if not run or not run.output_dir:
        raise HTTPException(404, "Run not found or not finished")
    draft_path = Path(run.output_dir) / "draft.docx"
    if not draft_path.exists():
        raise HTTPException(404, "Draft file not found")
    return FileResponse(
        str(draft_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="draft.docx",
    )


@router.get("/{run_id}/audit")
async def get_audit(run_id: str):
    """获取审计结果 JSON。"""
    run = storage.get_run(run_id)
    if not run or not run.output_dir:
        raise HTTPException(404, "Run not found or not finished")
    audit_path = Path(run.output_dir) / "audit.json"
    if not audit_path.exists():
        raise HTTPException(404, "Audit file not found")
    return json.loads(audit_path.read_text(encoding="utf-8"))


@router.get("/{run_id}/chapters")
async def get_chapters(run_id: str):
    """获取章节文本 (从 tpl_ctx.json 中提取 chapter* 字段用于预览)。"""
    run = storage.get_run(run_id)
    if not run or not run.output_dir:
        raise HTTPException(404, "Run not found or not finished")
    ctx_path = Path(run.output_dir) / "tpl_ctx.json"
    if not ctx_path.exists():
        raise HTTPException(404, "tpl_ctx.json not found")
    ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    # 按章节分组返回
    CHAPTER_CONFIGS = {
        "chapter1": {"name": "综合说明", "tags": ["chapter1_brief", "chapter1_legal_basis", "chapter1_evaluation", "chapter1_prediction_summary", "chapter1_measures_summary", "chapter1_monitoring_summary", "chapter1_conclusion"]},
        "chapter2": {"name": "项目概况", "tags": ["chapter2_composition", "chapter2_construction_org", "chapter2_relocation", "chapter2_natural"]},
        "chapter3": {"name": "水土保持评价", "tags": ["chapter3_site_eval", "chapter3_layout_eval", "chapter3_measures_definition"]},
        "chapter4": {"name": "水土流失分析与预测", "tags": ["chapter4_status", "chapter4_factors", "chapter4_prediction_text", "chapter4_hazard", "chapter4_guidance"]},
        "chapter5": {"name": "水土保持措施", "tags": ["chapter5_zone_division", "chapter5_layout", "chapter5_measures_detail", "chapter5_construction_req"]},
        "chapter6": {"name": "水土保持监测", "tags": ["chapter6_content_method", "chapter6_monitoring_points", "chapter6_implementation"]},
        "chapter7": {"name": "投资估算与效益分析", "tags": ["chapter7_principles", "chapter7_basis", "chapter7_method", "chapter7_benefit"]},
        "chapter8": {"name": "实施保障措施", "tags": ["chapter8_1_组织管理", "chapter8_2_后续设计", "chapter8_3_水土保持监测", "chapter8_4_水土保持监理", "chapter8_5_水土保持施工", "chapter8_6_水土保持设施验收"]},
    }
    TAG_LABELS = {
        "chapter1_brief": "编制目的", "chapter1_legal_basis": "编制依据",
        "chapter1_evaluation": "项目概况与评价", "chapter1_prediction_summary": "预测结论",
        "chapter1_measures_summary": "措施概要", "chapter1_monitoring_summary": "监测概要",
        "chapter1_conclusion": "结论与建议",
        "chapter2_composition": "项目组成", "chapter2_construction_org": "施工组织",
        "chapter2_relocation": "拆迁与安置", "chapter2_natural": "项目区自然概况",
        "chapter3_site_eval": "选址评价", "chapter3_layout_eval": "总体布局评价",
        "chapter3_measures_definition": "措施界定",
        "chapter4_status": "现状调查", "chapter4_factors": "影响因素分析",
        "chapter4_prediction_text": "预测结果", "chapter4_hazard": "危害分析",
        "chapter4_guidance": "防治措施方向",
        "chapter5_zone_division": "分区划分", "chapter5_layout": "措施总体布局",
        "chapter5_measures_detail": "分区措施设计", "chapter5_construction_req": "施工要求",
        "chapter6_content_method": "监测内容与方法", "chapter6_monitoring_points": "监测点位",
        "chapter6_implementation": "监测实施",
        "chapter7_principles": "估算原则", "chapter7_basis": "估算依据",
        "chapter7_method": "估算方法", "chapter7_benefit": "效益分析",
        "chapter8_1_组织管理": "组织管理", "chapter8_2_后续设计": "后续设计",
        "chapter8_3_水土保持监测": "水土保持监测", "chapter8_4_水土保持监理": "水土保持监理",
        "chapter8_5_水土保持施工": "水土保持施工", "chapter8_6_水土保持设施验收": "水土保持设施验收",
    }
    chapters = []
    for ch_id in ["chapter1", "chapter2", "chapter3", "chapter4", "chapter5", "chapter6", "chapter7", "chapter8"]:
        config = CHAPTER_CONFIGS[ch_id]
        sections = []
        for tag in config["tags"]:
            text = ctx.get(tag, "")
            sections.append({"tag": tag, "label": TAG_LABELS.get(tag, tag), "text": text or ""})
        chapters.append({"id": ch_id, "name": config["name"], "sections": sections})
    return chapters


@router.delete("/{run_id}")
async def delete_run(run_id: str):
    """删除运行记录。"""
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    # 清理输出文件
    if run.output_dir:
        import shutil
        output = Path(run.output_dir)
        if output.exists():
            shutil.rmtree(output, ignore_errors=True)
    runner.cleanup_events(run_id)
    storage.delete_run(run_id)
    return {"ok": True}
