"""主流水线编排 — 18 步完整流程。

1.   load_config          → State.Static
2.   preprocess           → State.ETL
3.   spatial_analysis     → State.ETL.spatial_layout / gis_gdf
4.   calc_earthwork       → State.Calc.earthwork
5.   calc_erosion         → State.Calc.erosion_df
6.   run_planner_agent    → State.Measures (含空间布置)
7.   calc_cost            → State.Calc.cost_summary
8.   calc_benefit         → State.Calc.benefit
9.   assemble             → State.TplCtx
9.5  data_adapter         → 校验 + 回调修复 + reassemble
10.  run_writer_agent     → State.Draft
11.  generate_charts      → PNG files
12.  generate_measure_maps → 措施图 PNG files
13.  render_docx          → draft.docx
14.  run_auditor_agent    → State.Flags
15.  (retry if needed)    → 回到10仅重写失败章节
16.  final_render         → report.docx
17.  package_output       → output/ 下 docx + audit.json
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from pathlib import Path
from datetime import datetime
from typing import Any, Callable

from src.state import GlobalState, init_state
from src.settings import OUTPUT_DIR

logger = logging.getLogger(__name__)


class Pipeline:
    """水土保持方案生成流水线。"""

    def __init__(self, facts_path: Path, measures_path: Path,
                 output_dir: Path | None = None, use_llm: bool = True,
                 on_progress: Callable[[dict[str, Any]], None] | None = None):
        self.facts_path = facts_path
        self.measures_path = measures_path
        self.output_dir = output_dir or OUTPUT_DIR
        self.use_llm = use_llm
        self.on_progress = on_progress
        self.state: GlobalState | None = None
        self._llm = None
        self._chart_paths: dict = {}
        self._audit_result: dict = {}
        self._map_lock = threading.Lock()

    def _get_llm(self):
        """延迟初始化 LLM 客户端。"""
        if self._llm is None and self.use_llm:
            from src.agents.base import LLMClient
            self._llm = LLMClient()
        return self._llm

    def run(self) -> Path:
        """执行完整流水线。根据配置选择 DAG 或线性模式。"""
        from src.settings import PIPELINE_PARALLEL_STEPS
        if PIPELINE_PARALLEL_STEPS:
            return self.run_dag()
        return self._run_linear()

    def _run_linear(self) -> Path:
        """线性模式 — 17 步顺序执行（保留向后兼容）。"""
        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info("水土保持方案自动生成系统 — 开始执行 (线性模式)")
        logger.info("=" * 60)

        # Step 1: 加载配置
        self._step("1/18 加载配置", self._load_config)

        # Step 2: 预处理
        self._step("2/18 预处理", self._preprocess)

        # Step 3: 空间分析 (CAD/GIS)
        self._step("3/18 空间分析", self._spatial_analysis)

        # Step 4: 土方平衡
        self._step("4/18 土方平衡计算", self._calc_earthwork)

        # Step 5: 侵蚀预测
        self._step("5/18 侵蚀预测计算", self._calc_erosion)

        # Step 6: 措施规划
        self._step("6/18 措施规划", self._run_planner)

        # Step 7: 造价估算
        self._step("7/18 造价估算", self._calc_cost)

        # Step 8: 效益分析
        self._step("8/18 效益分析", self._calc_benefit)

        # Step 9: 状态装配
        self._step("9/18 状态装配(229标签)", self._assemble)

        # Step 9.5: 数据适配校验
        self._step("9.5/18 数据适配校验", self._run_adapter)

        # Step 10: 撰稿
        self._step("10/18 报告撰写", self._run_writer)

        # Step 11: 图表生成
        self._step("11/18 图表生成", self._generate_charts)

        # Step 12: 措施图生成
        self._step("12/18 措施图生成", self._generate_measure_maps)

        # Step 13: 初次渲染
        self._step("13/18 初次渲染", self._render_draft)

        # Step 14: 审计
        self._step("14/18 质量审计", self._run_auditor)

        # Step 15: 重试
        self._step("15/18 审计回弹重写", self._retry_if_needed)

        # Step 16: 最终渲染
        self._step("16/18 最终渲染", self._final_render)

        # Step 17: 打包输出
        output_path = self._step("17/18 打包输出", self._package_output)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"完成! 总耗时: {elapsed:.1f}秒")
        logger.info(f"输出目录: {self.output_dir}")

        return output_path

    def run_dag(self) -> Path:
        """DAG 模式 — 利用步骤间并行性加速执行。"""
        from src.dag_scheduler import DAGScheduler

        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info("水土保持方案自动生成系统 — 开始执行 (DAG 模式)")
        logger.info("=" * 60)

        dag = DAGScheduler()
        dag.add_step("1_load_config",   self._load_config)
        dag.add_step("2_preprocess",    self._preprocess,           ["1_load_config"])
        dag.add_step("3_spatial",       self._spatial_analysis,     ["2_preprocess"])
        dag.add_step("4_earthwork",     self._calc_earthwork,       ["2_preprocess"])
        dag.add_step("5_erosion",       self._calc_erosion,         ["2_preprocess"])
        dag.add_step("6_planner",       self._run_planner,          ["3_spatial", "5_erosion"])
        dag.add_step("7_cost",          self._calc_cost,            ["6_planner", "4_earthwork"])
        dag.add_step("8_benefit",       self._calc_benefit,         ["7_cost"])
        dag.add_step("9_assemble",      self._assemble,             ["7_cost", "8_benefit"])
        dag.add_step("9.5_adapter",    self._run_adapter,          ["9_assemble"])
        dag.add_step("10_writer",       self._run_writer,           ["9.5_adapter"])
        dag.add_step("11_charts",       self._generate_charts,      ["9.5_adapter"])
        dag.add_step("12_drawings",     self._generate_measure_maps, ["9.5_adapter"])
        dag.add_step("13_render",       self._render_draft,         ["10_writer", "11_charts", "12_drawings"])
        dag.add_step("14_audit",        self._run_auditor,          ["13_render"])
        dag.add_step("15_retry",        self._retry_if_needed,      ["14_audit"])
        dag.add_step("16_final",        self._final_render,         ["15_retry"])
        dag.add_step("17_package",      self._package_output,       ["16_final"])

        dag.run(max_workers=4, on_progress=self._emit)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"完成! 总耗时: {elapsed:.1f}秒")
        logger.info(f"输出目录: {self.output_dir}")

        return self.output_dir / "report.docx"

    def _emit(self, event: dict[str, Any]):
        """发送进度事件。"""
        if self.on_progress:
            try:
                self.on_progress(event)
            except Exception:
                pass

    def _step(self, name: str, func, *args, **kwargs):
        """执行单步骤，带日志和进度回调。"""
        logger.info(f"[{name}]")
        self._emit({"step": name, "status": "running"})
        try:
            result = func(*args, **kwargs)
            self._emit({"step": name, "status": "done"})
            return result
        except Exception as e:
            logger.error(f"[{name}] 失败: {e}")
            self._emit({"step": name, "status": "error", "error": str(e)})
            raise

    # ── 各步骤实现 ──

    def _load_config(self):
        self.state = init_state(self.facts_path, self.measures_path)
        logger.info(f"  项目: {self.state.Static.meta['project_name']}")
        logger.info(f"  分区: {len(self.state.ETL.zones)} 个")
        logger.info(f"  已有措施: {len(self.state.Static.measures_existing)} 条")

    def _preprocess(self):
        # ETL 已在 init_state 中完成基础处理
        # 检查 RAG 是否就绪
        try:
            from src.rag import get_count
            count = get_count()
            self.state.ETL.rag_ready = count > 0
            logger.info(f"  RAG 语料: {count} 条")
        except RuntimeError as e:
            self.state.ETL.rag_ready = False
            logger.info(f"  RAG 未就绪: {e}")
        except Exception as e:
            self.state.ETL.rag_ready = False
            logger.info(f"  RAG 未就绪 ({type(e).__name__}: {e})")

    def _spatial_analysis(self):
        """分析 CAD/GIS 空间布局 (如有上传文件)。

        新流程:
          scan_gis → parse_dxf → render_dxf_layers()
                                      ↓
                              VLAnalyzer.analyze() Round 1+2
                                      ↓
                              CadFeatureAnalyzer.analyze()
                                      ↓
                              SiteModelBuilder
                                .from_ezdxf(cad_geometry, cad_site_features)
                                .from_gis(gis_gdf)
                                .from_meta(meta)
                                .from_vl(vl_result)
                                .build()
                                      ↓
                              state.ETL.site_model = site_model
        """
        from src.spatial_analyzer import (
            scan_gis_files, scan_cad_files, read_gis_file,
            convert_cad_to_png, analyze_spatial_layout,
            generate_default_spatial_layout,
        )

        # 检查上传目录
        upload_dir = self.output_dir.parent / "uploads"
        if not upload_dir.exists():
            upload_dir = self.output_dir  # fallback

        # 1. GIS 文件
        gis_files = scan_gis_files(upload_dir)
        gis_gdf = None
        if gis_files:
            gis_gdf = read_gis_file(gis_files[0])
            if gis_gdf is not None:
                self.state.ETL.gis_gdf = gis_gdf
                logger.info(f"  GIS: {gis_files[0].name} ({len(gis_gdf)} 要素)")

        # 2. CAD 文件 → 图片 + DXF 几何解析
        cad_files = scan_cad_files(upload_dir)
        cad_images = []
        for f in cad_files:
            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
                cad_images.append(f)
            elif f.suffix.lower() == ".dxf":
                png = convert_cad_to_png(f, self.output_dir / "cad_png")
                if png:
                    cad_images.append(png)
                # 解析 DXF 几何 (用于 CAD 底图叠加)
                self._parse_cad_geometry(f)
            elif f.suffix.lower() == ".dwg":
                png = convert_cad_to_png(f, self.output_dir / "cad_png")
                if png:
                    cad_images.append(png)
                # DWG → DXF → 解析几何
                from src.cad import convert_dwg_to_dxf
                dxf_path = convert_dwg_to_dxf(f, self.output_dir / "cad_dxf")
                if dxf_path:
                    self._parse_cad_geometry(dxf_path)
            else:
                png = convert_cad_to_png(f, self.output_dir / "cad_png")
                if png:
                    cad_images.append(png)
        if cad_images:
            logger.info(f"  CAD 图片: {len(cad_images)} 张")

        # 2.1 若 uploads 中未找到 DXF/DWG, 尝试额外目录
        if self.state.ETL.cad_geometry is None:
            from src.settings import BASE_DIR
            extra_dirs = [
                self.output_dir.parent / "cad_dxf",       # 历史转换目录
                BASE_DIR / "data" / "input",               # 项目原始数据
            ]
            for d in extra_dirs:
                if self.state.ETL.cad_geometry is not None:
                    break
                if not d.exists():
                    continue
                # 递归搜索 DXF/DWG
                for f in sorted(d.rglob("*")):
                    if self.state.ETL.cad_geometry is not None:
                        break
                    if f.suffix.lower() == ".dxf":
                        logger.info(f"  补充扫描发现 DXF: {f.name}")
                        png = convert_cad_to_png(f, self.output_dir / "cad_png")
                        if png and png not in cad_images:
                            cad_images.append(png)
                        self._parse_cad_geometry(f)
                    elif f.suffix.lower() == ".dwg":
                        logger.info(f"  补充扫描发现 DWG: {f.name}")
                        from src.cad import convert_dwg_to_dxf
                        dxf_path = convert_dwg_to_dxf(f, self.output_dir / "cad_dxf")
                        if dxf_path:
                            self._parse_cad_geometry(dxf_path)

        # 2.5. 分层渲染 DXF (供 VL 多轮分析)
        vl_layer_images = {}
        if self.state.ETL.cad_dxf_path:
            try:
                from src.cad import render_dxf_layers
                layer_dir = self.output_dir / "vl_layers"
                vl_layer_images = render_dxf_layers(
                    self.state.ETL.cad_dxf_path, layer_dir, dpi=300
                )
                self.state.ETL.vl_layer_images = vl_layer_images
                logger.info(f"  VL 分层渲染: {len(vl_layer_images)} 张 ({list(vl_layer_images.keys())})")
            except Exception as e:
                logger.warning(f"  VL 分层渲染失败: {e}")

        # 3. 图集索引 (在子进程中运行，防止 hnswlib 偶发 segfault 崩溃主进程)
        import subprocess, sys
        if True:
            try:
                project_root = Path(__file__).resolve().parent.parent
                result = subprocess.run(
                    [sys.executable, "-m", "src.atlas_rag"],
                    capture_output=True, text=True, timeout=300,
                    cwd=str(project_root),
                    env={**os.environ, "PYTHONPATH": str(project_root)},
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if line.startswith("ATLAS_INDEX_OK:"):
                            count = int(line.split(":")[1])
                            if count > 0:
                                logger.info(f"  图集索引: 新增 {count} 条")
                            else:
                                logger.info("  图集索引: 无新增 (已索引或无文件)")
                            break
                else:
                    # 子进程崩溃 (segfault rc=-11, 或异常 rc=1)
                    logger.warning(f"  图集索引子进程失败 (rc={result.returncode}), 跳过")
                    if result.stderr:
                        for line in result.stderr.strip().splitlines()[-3:]:
                            logger.debug(f"    {line}")
            except subprocess.TimeoutExpired:
                logger.warning("  图集索引超时 (300s), 跳过")
            except Exception as e:
                logger.info(f"  图集索引跳过: {e}")

        # 4. 综合空间分析 (保留旧流程兼容)
        if cad_images or gis_gdf is not None:
            layout = analyze_spatial_layout(
                cad_images=cad_images if self.use_llm else None,
                gis_gdf=gis_gdf,
                zones=self.state.ETL.zones,
            )
        else:
            layout = generate_default_spatial_layout(self.state.ETL.zones)
            logger.info("  无 CAD/GIS 文件，使用默认空间布局")

        self.state.ETL.spatial_layout = layout
        logger.info(f"  空间布局: {len(layout.get('zones', []))} 分区, "
                    f"{len(layout.get('buildings', []))} 建筑")

        # 5. CAD 特征分析 (智能措施布局)
        if self.state.ETL.cad_geometry:
            try:
                from src.cad_feature_analyzer import CadFeatureAnalyzer
                analyzer = CadFeatureAnalyzer(
                    self.state.ETL.cad_geometry,
                    self.state.ETL.spatial_layout,
                    project_meta=self.state.Static.meta,
                )
                self.state.ETL.cad_site_features = analyzer.analyze()
            except Exception as e:
                logger.warning(f"  CAD 特征分析失败: {e}")

        # 6. 多轮 VL 分析 (Round 1+2)
        vl_result = None
        if self.use_llm and vl_layer_images:
            try:
                from src.vl_analyzer import VLAnalyzer
                vl_analyzer = VLAnalyzer()
                structural_ctx = self._build_structural_context()
                vl_result = vl_analyzer.analyze(vl_layer_images, structural_ctx)
                logger.info(f"  VL 分析: {vl_result.round_count} 轮完成, "
                           f"errors={len(vl_result.errors)}")
            except Exception as e:
                logger.warning(f"  VL 分析失败: {e}")

        # 7. SiteModel 融合构建
        try:
            from src.site_model import SiteModelBuilder
            builder = SiteModelBuilder()
            builder.from_ezdxf(
                self.state.ETL.cad_geometry,
                self.state.ETL.cad_site_features,
            )
            builder.from_gis(self.state.ETL.gis_gdf)
            builder.from_meta(self.state.Static.meta)
            if vl_result is not None:
                builder.from_vl(vl_result)
            site_model = builder.build()
            self.state.ETL.site_model = site_model
            logger.info(f"  SiteModel: {len(site_model.zones)} zones, "
                       f"boundary={'yes' if site_model.boundary else 'no'}")
        except Exception as e:
            logger.warning(f"  SiteModel 构建失败: {e}")

    def _build_structural_context(self) -> dict:
        """构建 VL 分析所需的结构上下文。"""
        ctx = {
            "total_area_m2": 0,
            "zone_count": len(self.state.ETL.zones),
            "building_count": 0,
            "road_count": 0,
            "zones": [],
        }
        features = self.state.ETL.cad_site_features
        if features:
            ctx["building_count"] = len(getattr(features, 'building_footprints', []))
            ctx["road_count"] = len(getattr(features, 'road_edges', []))
            boundary = getattr(features, 'boundary_polyline', [])
            if boundary:
                from src.geo_utils import shoelace_area
                ctx["total_area_m2"] = shoelace_area(boundary)
        for z in self.state.ETL.zones:
            ctx["zones"].append({
                "name": z.get("name", ""),
                "area_m2": z.get("area_m2", z.get("area_hm2", 0) * 10000),
            })
        if ctx["total_area_m2"] == 0:
            ctx["total_area_m2"] = sum(z.get("area_m2", 0) for z in ctx["zones"])
        return ctx

    def _parse_cad_geometry(self, dxf_path: Path):
        """解析 DXF 几何并缓存到 State (仅在首次成功时设置)。"""
        if self.state.ETL.cad_geometry is not None:
            return  # 已解析过
        try:
            from src.cad_base_renderer import parse_dxf_geometry
            cad_geometry = parse_dxf_geometry(dxf_path)
            if cad_geometry:
                self.state.ETL.cad_geometry = cad_geometry
                self.state.ETL.cad_dxf_path = str(dxf_path)
                logger.info(f"  CAD 几何: {len(cad_geometry.entities)} 实体, "
                           f"bounds={tuple(round(b, 1) for b in cad_geometry.bounds)}")
        except Exception as e:
            logger.warning(f"  CAD 几何解析失败: {e}")

    def _calc_earthwork(self):
        from src.calculators.earthwork import calc_earthwork
        result = calc_earthwork(self.state)
        logger.info(f"  余方: {result['surplus_m3']}m³")

    def _calc_erosion(self):
        from src.calculators.erosion import calc_erosion
        result = calc_erosion(self.state)
        logger.info(f"  总预测: {result['total_pred']:.2f}t")
        logger.info(f"  新增: {result['total_new']:.2f}t")

    def _run_planner(self):
        if self.use_llm:
            from src.agents.planner import run_planner, _default_measures
            new = run_planner(self.state, self._get_llm())
            logger.info(f"  新增措施: {len(new)} 条")
            # 补充: LLM 7B 模型经常遗漏关键措施，用默认规则补齐缺失项
            existing_names = {m.get("措施名称", m.get("name", "")) for m in self.state.Measures}
            defaults = _default_measures()
            added = 0
            for m in defaults:
                if m["措施名称"] not in existing_names:
                    m["source"] = "default_supplement"
                    self.state.Measures.append(m)
                    existing_names.add(m["措施名称"])
                    added += 1
            if added:
                logger.info(f"  补充默认措施: {added} 条 (LLM 遗漏项)")
        else:
            # 使用默认规则
            from src.agents.planner import _default_measures
            new_measures = _default_measures()
            for m in new_measures:
                m["source"] = "planned"
                self.state.Measures.append(m)
            logger.info(f"  默认措施: {len(new_measures)} 条")

    def _calc_cost(self):
        from src.calculators.cost import calc_cost
        result = calc_cost(self.state)
        logger.info(f"  水保总投资: {result['c_grand_total']:.2f}万元")

    def _calc_benefit(self):
        from src.calculators.benefit import calc_benefit
        result = calc_benefit(self.state)
        all_met = result.get("all_met", False)
        logger.info(f"  六指标全部达标: {'是' if all_met else '否'}")

    def _assemble(self):
        from src.assembler import assemble
        ctx = assemble(self.state)
        logger.info(f"  标签数量: {len(ctx)}")
        none_count = sum(1 for v in ctx.values() if v is None or v == "")
        logger.info(f"  空值标签: {none_count}")

    def _run_adapter(self):
        """Step 9.5: 数据适配校验 + 回调修复。"""
        if self.use_llm:
            from src.agents.adapter import run_adapter
            result = run_adapter(self.state, self._get_llm())
        else:
            from src.agents.adapter import _fallback_adapter
            from src.context import AgentContext
            with AgentContext(state=self.state):
                result = _fallback_adapter(self.state)

        status = result.get("status", "unknown")
        fixed = result.get("fixed_tags", 0)
        remaining = len(result.get("remaining_issues", []))
        logger.info(f"  适配结果: {status}, 修复 {fixed} 个标签, 剩余问题 {remaining}")
        self.state.Flags["adapter_result"] = result

    def _run_writer(self):
        if self.use_llm:
            from src.agents.writer import run_writer
            results = run_writer(self.state, self._get_llm())
            logger.info(f"  生成子段: {len(results)}")
            # 重新装配: 将 Draft 章节文本合并到 TplCtx
            from src.assembler import assemble
            assemble(self.state)
        else:
            self._generate_placeholder_text()

    def _generate_placeholder_text(self):
        """不使用 LLM 时生成占位文本。"""
        from src.agents.writer import CHAPTER_CONFIGS
        meta = self.state.Static.meta
        for ch_id, config in CHAPTER_CONFIGS.items():
            for tag in config["tags"]:
                self.state.Draft[tag] = (
                    f"本节为 {meta['project_name']} 的{config['name']}内容。"
                    f"（自动生成占位文本，实际运行时由 LLM 生成。）"
                )
        # 重新装配
        from src.assembler import assemble
        assemble(self.state)

    def _generate_charts(self):
        from src.charts import generate_all_charts
        chart_paths = generate_all_charts(self.state, self.output_dir)
        with self._map_lock:
            self._chart_paths.update(chart_paths)
        logger.info(f"  图表: {len(chart_paths)} 张")

    def _generate_measure_maps(self):
        """渲染措施图 — PlacementEngine + Drawing Agent + MeasureMapRenderer 互补。

        新流程:
          PlacementEngine(site_model) → resolve_all()
          → Drawing Agent (LLM)
          → MeasureMapRenderer (fallback)
          → VL Sanity Check (Round 3+4)

        回退: site_model 为 None 时回退到旧 MeasurePlacementResolver。
        """
        # 1. 用 PlacementEngine 预计算措施布置
        placement_engine = None
        if self.state.ETL.site_model is not None:
            try:
                from src.placement_engine import PlacementEngine
                placement_engine = PlacementEngine(self.state.ETL.site_model)
                placement_engine.resolve_all(self.state.Measures)
                adj = placement_engine.optimize_batch()
                summary_line = placement_engine.get_placement_summary().split(chr(10))[0]
                logger.info(f"  PlacementEngine: {summary_line} (碰撞优化 {adj} 次)")
            except Exception as e:
                logger.warning(f"  PlacementEngine 失败: {e}")
                placement_engine = None

        # 2. Drawing Agent (LLM)
        agent_maps: dict[str, Path] = {}
        if self.use_llm:
            try:
                from src.agents.drawing import run_drawing_agent
                maps = run_drawing_agent(self.state, self._get_llm(), self.output_dir)
                # 过滤: 只将 PNG 文件计入
                agent_maps = {
                    k: v for k, v in maps.items()
                    if str(v).lower().endswith(".png")
                }
                dxf_count = len(maps) - len(agent_maps)
                logger.info(f"  Drawing Agent: {len(agent_maps)} PNG + {dxf_count} DXF")
            except Exception as e:
                logger.warning(f"  Drawing Agent 失败: {e}")

        # 3. MeasureMapRenderer 补齐缺失图
        from src.measure_map import MeasureMapRenderer

        renderer = MeasureMapRenderer(
            zones=self.state.ETL.zones,
            measures=self.state.Measures,
            spatial_layout=self.state.ETL.spatial_layout,
            gis_gdf=self.state.ETL.gis_gdf,
            output_dir=self.output_dir,
            cad_geometry=self.state.ETL.cad_geometry,
            cad_dxf_path=self.state.ETL.cad_dxf_path,
            cad_site_features=self.state.ETL.cad_site_features,
            placement_engine=placement_engine,
        )

        fallback_maps = renderer.render_all(skip_tags=set(agent_maps.keys()))

        # 合并: Agent 优先，Fallback 补缺
        combined = {}
        combined.update(fallback_maps)   # 先放 fallback (仅补缺)
        combined.update(agent_maps)      # Agent 覆盖同名 tag

        supplemented = len(combined) - len(agent_maps)
        with self._map_lock:
            self._chart_paths.update(combined)

        if agent_maps:
            logger.info(f"  措施图合计: {len(combined)} 张 (Agent {len(agent_maps)} + 补齐 {supplemented})")
        else:
            logger.info(f"  措施图 (Fallback): {len(fallback_maps)} 张")

        # 4. VL Sanity Check (Round 3+4)
        if self.use_llm and placement_engine is not None:
            self._vl_sanity_check(combined, placement_engine)

    def _vl_sanity_check(self, map_paths: dict, placement_engine):
        """VL Sanity Check — Round 3 布局审查 + Round 4 最终审查 + Round 5 对比审查。"""
        try:
            from src.vl_analyzer import VLAnalyzer
            vl = VLAnalyzer()
        except Exception as e:
            logger.warning(f"  VL Sanity Check 跳过: {e}")
            return

        self.state.Flags.setdefault("vl_sanity", {})

        # Round 3: 措施布局审查 (找 measure_layout 图)
        layout_map = None
        for key in ("measure_layout_map", "measure_layout"):
            if key in map_paths:
                layout_map = map_paths[key]
                break

        if layout_map and Path(layout_map).exists():
            summary = placement_engine.get_placement_summary()
            r3 = vl.sanity_check_layout(Path(layout_map), summary)

            self.state.Flags["vl_sanity"]["round3_score"] = r3.overall_score
            self.state.Flags["vl_sanity"]["round3_issues"] = r3.issues

            if r3.overall_score >= 70:
                logger.info(f"  VL Round 3 通过: score={r3.overall_score}")
            else:
                logger.info(f"  VL Round 3 未通过: score={r3.overall_score}, issues={r3.issues}")

        # Round 4: 最终审查
        final_map = None
        for key in ("measure_layout_map", "measure_layout"):
            if key in map_paths:
                final_map = map_paths[key]
                break

        if final_map and Path(final_map).exists():
            r4 = vl.sanity_check_final(Path(final_map))
            self.state.Flags["vl_sanity"]["round4_score"] = r4.overall_score
            self.state.Flags["vl_sanity"]["round4_ready"] = r4.submission_ready
            self.state.Flags["vl_sanity"]["round4_issues"] = r4.critical_issues

            if r4.submission_ready:
                logger.info(f"  VL Round 4 报批就绪: score={r4.overall_score}")
            else:
                logger.info(f"  VL Round 4 需改进: score={r4.overall_score}, "
                           f"issues={r4.critical_issues}")

        # Round 5: 对比审查 — 将生成图与原始 CAD 图对比
        original_cad = None
        vl_images = getattr(self.state.ETL, 'vl_layer_images', {})
        if isinstance(vl_images, dict):
            original_cad = vl_images.get("full")
        if original_cad and not Path(original_cad).exists():
            original_cad = None

        generated = {k: v for k, v in map_paths.items()
                     if v and Path(v).exists()}
        if generated:
            r5 = vl.sanity_check_comparative(generated, original_cad)
            self.state.Flags["vl_sanity"]["round5_comparative"] = {
                k: {kk: vv for kk, vv in v.items() if kk != "raw_response"}
                for k, v in r5.items()
            }
            # 汇总: 所有图的平均分
            scores = [v.get("score", 0) for v in r5.values() if isinstance(v.get("score"), (int, float))]
            avg = sum(scores) / len(scores) if scores else 0
            eng_count = sum(1 for v in r5.values() if v.get("is_engineering_quality"))
            self.state.Flags["vl_sanity"]["round5_avg_score"] = round(avg, 1)
            self.state.Flags["vl_sanity"]["round5_engineering_count"] = f"{eng_count}/{len(r5)}"
            logger.info(f"  VL Round 5 对比审查: 均分={avg:.1f}/10, "
                       f"工程质量={eng_count}/{len(r5)}")

    def _render_draft(self):
        from src.renderer import render_docx
        draft_path = self.output_dir / "draft.docx"
        render_docx(self.state, draft_path, self._chart_paths)

    def _run_auditor(self):
        if self.use_llm:
            from src.agents.auditor import run_auditor
            self._audit_result = run_auditor(self.state, self._get_llm())
            logger.info(f"  审计总分: {self._audit_result.get('total_score', 0)}")
        else:
            # 跳过 LLM 审计，使用 fallback
            from src.agents.auditor import _fallback_audit
            from src.context import AgentContext
            with AgentContext(state=self.state):
                self._audit_result = _fallback_audit(self.state)
            logger.info(f"  审计总分(fallback): {self._audit_result.get('total_score', 0)}")

    def _retry_if_needed(self):
        from src.settings import AUDITOR_PASS_SCORE, AUDITOR_FAIL_SCORE

        MAX_RETRIES = 3
        for attempt in range(MAX_RETRIES):
            score = self._audit_result.get("total_score", 0)
            if score >= AUDITOR_PASS_SCORE:
                logger.info(f"  审计通过 (第{attempt}轮)，无需重试")
                return

            if score < AUDITOR_FAIL_SCORE:
                logger.info("  分数过低，强制通过并标记需人工复核")
                self.state.Flags["needs_human_review"] = True
                return

            # 分级回退: 根据 failure_details 决定回退策略
            failure_details = self._audit_result.get("failure_details", [])
            actions = set()
            for fd in failure_details:
                action = fd.get("suggested_action", "retry_writer")
                actions.add(action)
                logger.info(
                    "  失败项: %s [%s] source=%s → %s",
                    fd.get("chapter", "?"), fd.get("severity", "?"),
                    fd.get("failure_source", "?"), action,
                )

            reran_something = False

            # 策略1: 重跑计算引擎
            if "rerun_calc" in actions:
                logger.info(f"  分级回退: 重跑计算引擎 (第{attempt + 1}轮)")
                try:
                    self._run_calculations()
                    reran_something = True
                except Exception as e:
                    logger.warning(f"  重跑计算失败: {e}")

            # 策略2: 重跑图纸渲染
            if "rerun_render" in actions:
                logger.info(f"  分级回退: 重跑图纸渲染 (第{attempt + 1}轮)")
                try:
                    self._generate_measure_maps()
                    reran_something = True
                except Exception as e:
                    logger.warning(f"  重跑渲染失败: {e}")

            # 策略3: 回弹撰稿 (默认/最常见)
            if "retry_writer" in actions or not reran_something:
                from src.agents.auditor import get_retry_chapters
                retry_list = get_retry_chapters(self.state, self._audit_result)
                if not retry_list:
                    logger.info("  无可重试章节或已达最大重试次数")
                    return

                logger.info(f"  重写 {len(retry_list)} 个章节 (第{attempt + 1}轮)")
                if self.use_llm:
                    from src.agents.writer import rewrite_chapter
                    from src.context import AgentContext

                    def _rewrite_task(state, ch_id, feedback, llm):
                        with AgentContext(state=state):
                            return rewrite_chapter(state, ch_id, feedback, llm)

                    if len(retry_list) > 1:
                        from concurrent.futures import ThreadPoolExecutor, as_completed
                        with ThreadPoolExecutor(max_workers=3) as executor:
                            futures = {
                                executor.submit(
                                    _rewrite_task, self.state, ch_id, feedback, self._get_llm(),
                                ): ch_id
                                for ch_id, feedback in retry_list
                            }
                            for future in as_completed(futures):
                                ch_id = futures[future]
                                try:
                                    future.result()
                                    logger.info(f"    重写完成: {ch_id}")
                                except Exception as e:
                                    logger.error(f"    重写失败: {ch_id}: {e}")
                    else:
                        for ch_id, feedback in retry_list:
                            logger.info(f"    重写: {ch_id}")
                            with AgentContext(state=self.state):
                                rewrite_chapter(self.state, ch_id, feedback, self._get_llm())

            # 重新装配
            from src.assembler import assemble
            assemble(self.state)

            # 重新审计
            self._run_auditor()

    def _final_render(self):
        from src.renderer import render_docx, check_completeness
        report_path = self.output_dir / "report.docx"
        render_docx(self.state, report_path, self._chart_paths)

        # 完整性检查
        check = check_completeness(report_path)
        if check["pass"]:
            logger.info("  完整性检查通过")
        else:
            logger.warning(f"  完整性问题: {check['issues']}")
            # 记录到审计日志并标记需人工复核
            self.state.Flags["audit_log"].append({
                "timestamp": datetime.now().isoformat(),
                "step": "completeness_check",
                "issues": check["issues"],
            })
            self.state.Flags["needs_human_review"] = True

    def _package_output(self) -> Path:
        """打包输出文件。"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 保存审计日志
        audit_path = self.output_dir / "audit.json"
        with open(audit_path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "project": self.state.Static.meta["project_name"],
                "final_score": self.state.Flags.get("final_score", 0),
                "audit_log": self.state.Flags.get("audit_log", []),
                "scores": self.state.Flags.get("scores", {}),
                "needs_human_review": self.state.Flags.get("needs_human_review", False),
            }, f, ensure_ascii=False, indent=2)

        # 保存 TplCtx (调试用)
        ctx_path = self.output_dir / "tpl_ctx.json"
        with open(ctx_path, "w", encoding="utf-8") as f:
            # 过滤不可序列化的值
            serializable = {}
            for k, v in self.state.TplCtx.items():
                if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                    serializable[k] = v
                else:
                    serializable[k] = str(v)
            json.dump(serializable, f, ensure_ascii=False, indent=2)

        logger.info(f"  输出: {self.output_dir}")
        return self.output_dir / "report.docx"
