"""GlobalState 数据结构 — 7 个分区，贯穿整个流水线。"""

from __future__ import annotations

import json
import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── 子分区数据类 ─────────────────────────────────────────────

@dataclass
class StaticData:
    """Static: 从配置文件加载的只读数据。"""
    meta: dict = field(default_factory=dict)           # facts_v2.json 全量
    soil_map: dict = field(default_factory=dict)       # soil_map.json
    price_table: list[dict] = field(default_factory=list)  # price_v2.csv → list[dict]
    fee_rate: dict = field(default_factory=dict)       # fee_rate_config.json
    legal_refs: dict = field(default_factory=dict)     # legal_refs.json
    measure_library: dict = field(default_factory=dict)  # measure_library.json
    measures_existing: list[dict] = field(default_factory=list)  # measures_v2.csv → list[dict]


@dataclass
class ETLData:
    """ETL: 预处理后的中间数据。"""
    zones: list[dict] = field(default_factory=list)    # facts.zones 的扩展版
    rag_ready: bool = False                            # RAG 是否就绪
    site_desc: str = ""                                # 场地描述（VL 或手写）
    spatial_layout: dict = field(default_factory=dict) # VL+GIS 空间分析结果
    gis_gdf: Any = None                                # GeoDataFrame (GIS 分区多边形)
    cad_geometry: Any = None                            # CadGeometry 对象 (DXF 解析结果)
    cad_dxf_path: str = ""                              # 源 DXF 文件路径
    cad_site_features: Any = None                       # CadSiteFeatures (场地特征分析结果)
    measure_layout: list = field(default_factory=list) # Planner 空间布置输出
    site_model: Any = None                              # SiteModel 实例 (融合场景模型)
    vl_layer_images: Any = None                         # 分层渲染图路径 dict


@dataclass
class CalcData:
    """Calc: 4 个计算引擎的输出。"""
    earthwork: dict = field(default_factory=dict)      # 土方平衡结果
    erosion_df: dict = field(default_factory=dict)     # 侵蚀预测矩阵
    cost_summary: dict = field(default_factory=dict)   # 造价汇总
    benefit: dict = field(default_factory=dict)        # 效益分析结果


@dataclass
class GlobalState:
    """
    全局状态机 — 流水线各步骤共享此对象。

    7 个分区:
      Static   — 配置文件加载的只读数据
      ETL      — 预处理中间数据
      Calc     — 计算引擎输出
      TplCtx   — 229 标签映射字典
      Draft    — 章节文本 {chapter_id: text}
      Measures — 已有 + 新增措施列表
      Flags    — 运行标记 (retry, score, log)
    """
    Static: StaticData = field(default_factory=StaticData)
    ETL: ETLData = field(default_factory=ETLData)
    Calc: CalcData = field(default_factory=CalcData)
    TplCtx: dict[str, Any] = field(default_factory=dict)
    Draft: dict[str, str] = field(default_factory=dict)
    Measures: list[dict] = field(default_factory=list)
    Flags: dict[str, Any] = field(default_factory=lambda: {
        "retry_count": {},   # {chapter_id: int}
        "scores": {},        # {chapter_id: float}
        "audit_log": [],     # [{chapter_id, score, feedback, timestamp}]
        "final_score": 0.0,
        "needs_human_review": False,  # 审计 <60 分时标记为需人工复核
    })


# ── 加载工具 ────────────────────────────────────────────────

def load_json(path: Path) -> dict | list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_csv(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def load_static(facts_path: Path, measures_path: Path) -> StaticData:
    """从配置文件加载 StaticData。"""
    from src.settings import (
        SOIL_MAP_PATH, PRICE_PATH, FEE_RATE_PATH,
        MEASURE_LIBRARY_PATH, LEGAL_REFS_PATH,
    )
    return StaticData(
        meta=load_json(facts_path),
        soil_map=load_json(SOIL_MAP_PATH),
        price_table=load_csv(PRICE_PATH),
        fee_rate=load_json(FEE_RATE_PATH),
        legal_refs=load_json(LEGAL_REFS_PATH),
        measure_library=load_json(MEASURE_LIBRARY_PATH),
        measures_existing=load_csv(measures_path),
    )


def init_state(facts_path: Path, measures_path: Path) -> GlobalState:
    """初始化完整的 GlobalState。"""
    state = GlobalState()
    state.Static = load_static(facts_path, measures_path)

    # 将 facts.zones 复制到 ETL.zones 并做初步扩展
    meta = state.Static.meta
    state.ETL.zones = []
    for z in meta.get("zones", []):
        zone = dict(z)
        # 计算分区周长估算值 (近似正方形)
        area_m2 = zone["area_hm2"] * 10000
        zone["area_m2"] = area_m2
        zone["perimeter_m"] = 4 * (area_m2 ** 0.5)
        state.ETL.zones.append(zone)

    # 将 existing measures 也放到 Measures 里（标记来源）
    for m in state.Static.measures_existing:
        measure = dict(m)
        measure["source"] = "existing"
        state.Measures.append(measure)

    return state
