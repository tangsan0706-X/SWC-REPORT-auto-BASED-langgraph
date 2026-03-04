"""多轮 VL 分析引擎 — 4 轮 VL 调用，分层分析 CAD 图纸。

Round 1: 全局场景理解 (full.png) — 验证 ezdxf 提取的结构信息
Round 2: 分区验证 (building_road.png + boundary_text.png) — 逐个验证已知分区
Round 3: 措施布局审查 (measure_maps) — 在 pipeline 中调用 (Phase 7)
Round 4: 最终报批审查 (final_map) — 在 pipeline 中调用 (Phase 7)

错误处理:
- 每轮独立 try/except，失败不阻塞后续轮次
- JSON 解析失败: 正则提取 {...} 再尝试
- VL 完全不可用: 返回空 VLResult
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# VLResult 数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class VLResult:
    """VL 分析结果。"""
    global_scene: dict = field(default_factory=dict)        # Round 1
    zone_validation: dict = field(default_factory=dict)     # Round 2
    raw_responses: List[str] = field(default_factory=list)  # 调试用
    round_count: int = 0
    errors: List[str] = field(default_factory=list)         # 解析失败记录


@dataclass
class VLSanityResult:
    """VL 审查结果 (Round 3 or 4)。"""
    overall_score: int = 0
    issues: List[str] = field(default_factory=list)
    layout_quality: str = ""
    overlaps_detected: bool = False
    missing_measures: List[str] = field(default_factory=list)
    submission_ready: bool = False
    strengths: List[str] = field(default_factory=list)
    deficiencies: List[str] = field(default_factory=list)
    critical_issues: List[str] = field(default_factory=list)
    raw_response: str = ""


# ═══════════════════════════════════════════════════════════════
# VL Prompts
# ═══════════════════════════════════════════════════════════════

ROUND1_PROMPT_TEMPLATE = """你是一位经验丰富的水土保持方案设计工程师。请分析这张工程总平面图。

已从 CAD 文件中提取的结构信息:
- 项目总面积: {total_area_m2:.0f} m²
- 分区数量: {zone_count} 个
- 已识别建筑: {building_count} 个
- 已识别道路: {road_count} 条

请验证上述信息并补充分析，以 JSON 格式输出 (只输出 JSON):
{{
  "scene_type": "住宅小区/工业园区/市政道路/商业综合体/其他",
  "description": "简要场景描述",
  "terrain_direction": "排水方向，如 NW→SE",
  "vegetation_coverage": "高/中/低/无",
  "water_features": "是否可见水体或排水设施",
  "boundary_visible": true/false,
  "building_count_verify": 预估建筑数量,
  "road_count_verify": 预估道路数量,
  "missing_zones": ["可能遗漏的分区名称"]
}}"""

ROUND2_PROMPT_TEMPLATE = """你是一位水土保持方案设计工程师。请验证以下分区是否在图中可见。

已知分区:
{zone_list}

请对每个分区验证，以 JSON 格式输出 (只输出 JSON):
{{
  "{first_zone}": {{
    "exists": true/false,
    "location_description": "在图纸中的大致位置描述",
    "features_visible": ["可见的要素列表"],
    "suggested_measures": ["建议的水保措施"],
    "boundary_quality": "清晰/模糊/不可见"
  }},
  ...
}}"""

ROUND3_PROMPT_TEMPLATE = """你是一位水土保持方案审查专家。请审查这张水保措施布置图的质量。

已布置的措施摘要:
{placement_summary}

请评审并以 JSON 格式输出 (只输出 JSON):
{{
  "overall_score": 0到100的分数,
  "layout_quality": "优秀/良好/一般/较差",
  "overlaps_detected": true/false,
  "issues": ["发现的问题列表"],
  "missing_measures": ["可能缺失的措施"],
  "suggestions": ["改进建议"]
}}"""

ROUND4_PROMPT_TEMPLATE = """你是一位水土保持方案报批审查专家。请审查这张总平面措施布置图是否达到报批稿标准。

请以 JSON 格式输出 (只输出 JSON):
{{
  "submission_ready": true/false,
  "score": 0到100的分数,
  "strengths": ["图纸优点"],
  "deficiencies": ["不足之处"],
  "critical_issues": ["必须修改的关键问题"]
}}"""

COMPARATIVE_CHECK_PROMPT = """你是水土保持工程审图专家。请对比审查这两张图。

第一张是原始 CAD 总平面图（设计院提供的施工图）。
第二张是系统自动生成的水保措施布置图。

请逐项评判生成图的质量，以 JSON 格式输出 (只输出 JSON):
{{
  "is_engineering_quality": true/false,
  "has_base_map": true/false,
  "has_real_boundaries": true/false,
  "measures_properly_placed": true/false,
  "boundary_shape_match": true/false,
  "road_network_visible": true/false,
  "building_footprints_visible": true/false,
  "legend_consistent": true/false,
  "issues": ["具体问题描述"],
  "score": 1到10的整数评分
}}"""

SINGLE_MAP_CHECK_PROMPT = """你是水土保持工程审图专家。请审查这张 [{map_type}] 图纸：

1. 分区边界是否与实际场地形状吻合？（不应是简单矩形，除非场地本身是矩形）
2. 措施是否沿道路、边界等合理位置布置？（不应是随机色块）
3. 建筑、道路、绿地等底图元素是否可见？
4. 图例与图中实际元素是否一致？
5. 整体像一张工程图还是示意图？

请以 JSON 格式输出 (只输出 JSON):
{{
  "is_engineering_quality": true/false,
  "has_base_map": true/false,
  "has_real_boundaries": true/false,
  "measures_properly_placed": true/false,
  "issues": ["具体问题描述"],
  "score": 1到10的整数评分
}}"""


# ═══════════════════════════════════════════════════════════════
# VLAnalyzer — 多轮 VL 分析引擎
# ═══════════════════════════════════════════════════════════════

class VLAnalyzer:
    """多轮 VL 分析引擎。

    Round 1+2 在 _spatial_analysis 阶段执行。
    Round 3+4 在 _generate_measure_maps 阶段执行 (VL Sanity Check)。
    """

    def analyze(
        self,
        layer_images: Dict[str, Path],
        structural_context: dict,
    ) -> VLResult:
        """执行 Round 1+2 VL 分析。

        Args:
            layer_images: {"full": Path, "building_road": Path, "boundary_text": Path, ...}
            structural_context: ezdxf 已提取的结构信息
                {"total_area_m2": ..., "zone_count": ..., "building_count": ...,
                 "road_count": ..., "zones": [{"name": ..., "area_m2": ...}]}

        Returns:
            VLResult
        """
        result = VLResult()

        # Round 1: 全局场景理解
        full_img = layer_images.get("full")
        if full_img and full_img.exists():
            try:
                r1 = self._round1_global(full_img, structural_context)
                result.global_scene = r1
                result.round_count += 1
                logger.info(f"VL Round 1: scene_type={r1.get('scene_type', 'unknown')}")
            except Exception as e:
                result.errors.append(f"Round 1 failed: {e}")
                logger.warning(f"VL Round 1 失败: {e}")

        # Round 2: 分区验证
        detail_imgs = []
        for key in ("building_road", "boundary_text", "full"):
            img = layer_images.get(key)
            if img and img.exists():
                detail_imgs.append(img)
        if detail_imgs:
            try:
                zones_info = structural_context.get("zones", [])
                r2 = self._round2_zone_validation(detail_imgs[:2], zones_info)
                result.zone_validation = r2
                result.round_count += 1
                logger.info(f"VL Round 2: validated {len(r2)} zones")
            except Exception as e:
                result.errors.append(f"Round 2 failed: {e}")
                logger.warning(f"VL Round 2 失败: {e}")

        return result

    def sanity_check_layout(
        self,
        map_image: Path,
        placement_summary: str,
    ) -> VLSanityResult:
        """Round 3: 措施布局审查。"""
        result = VLSanityResult()
        if not map_image or not map_image.exists():
            return result

        try:
            prompt = ROUND3_PROMPT_TEMPLATE.format(placement_summary=placement_summary)
            raw = _call_vl_safe([map_image], prompt)
            result.raw_response = raw
            parsed = _parse_json_safe(raw)
            if parsed:
                result.overall_score = parsed.get("overall_score", 0)
                result.layout_quality = parsed.get("layout_quality", "")
                result.overlaps_detected = parsed.get("overlaps_detected", False)
                result.issues = parsed.get("issues", [])
                result.missing_measures = parsed.get("missing_measures", [])
            logger.info(f"VL Round 3: score={result.overall_score}")
        except Exception as e:
            logger.warning(f"VL Round 3 失败: {e}")

        return result

    def sanity_check_comparative(
        self,
        generated_images: Dict[str, Path],
        original_cad_image: Optional[Path] = None,
    ) -> Dict[str, dict]:
        """对比审查: 将生成图与原始 CAD 图同时发给 VL 评判。

        Args:
            generated_images: {"zone_boundary": Path, "measure_layout": Path, ...}
            original_cad_image: 原始 CAD 高清渲染图 (可选)

        Returns:
            {map_type: {"score": int, "issues": [...], ...}}
        """
        results = {}
        for map_type, img_path in generated_images.items():
            if not img_path or not Path(img_path).exists():
                continue
            try:
                if original_cad_image and Path(original_cad_image).exists():
                    # 对比模式: 原始 CAD + 生成图
                    images = [Path(original_cad_image), Path(img_path)]
                    raw = _call_vl_safe(images, COMPARATIVE_CHECK_PROMPT)
                else:
                    # 单图模式
                    images = [Path(img_path)]
                    prompt = SINGLE_MAP_CHECK_PROMPT.replace("{map_type}", map_type)
                    raw = _call_vl_safe(images, prompt)

                parsed = _parse_json_safe(raw) or {}
                parsed["raw_response"] = raw
                results[map_type] = parsed
                score = parsed.get("score", 0)
                eng = parsed.get("is_engineering_quality", False)
                logger.info(
                    "VL 对比审查 [%s]: score=%s, engineering=%s", map_type, score, eng
                )
            except Exception as e:
                logger.warning("VL 对比审查 [%s] 失败: %s", map_type, e)
                results[map_type] = {"error": str(e)}
        return results

    def sanity_check_final(self, map_image: Path) -> VLSanityResult:
        """Round 4: 最终报批审查。"""
        result = VLSanityResult()
        if not map_image or not map_image.exists():
            return result

        try:
            raw = _call_vl_safe([map_image], ROUND4_PROMPT_TEMPLATE)
            result.raw_response = raw
            parsed = _parse_json_safe(raw)
            if parsed:
                result.overall_score = parsed.get("score", 0)
                result.submission_ready = parsed.get("submission_ready", False)
                result.strengths = parsed.get("strengths", [])
                result.deficiencies = parsed.get("deficiencies", [])
                result.critical_issues = parsed.get("critical_issues", [])
            logger.info(f"VL Round 4: score={result.overall_score}, ready={result.submission_ready}")
        except Exception as e:
            logger.warning(f"VL Round 4 失败: {e}")

        return result

    # ── 内部方法 ──────────────────────────────────────────────

    def _round1_global(self, image: Path, ctx: dict) -> dict:
        """Round 1: 全局场景理解。"""
        prompt = ROUND1_PROMPT_TEMPLATE.format(
            total_area_m2=ctx.get("total_area_m2", 0),
            zone_count=ctx.get("zone_count", 0),
            building_count=ctx.get("building_count", 0),
            road_count=ctx.get("road_count", 0),
        )
        raw = _call_vl_safe([image], prompt)
        return _parse_json_safe(raw) or {}

    def _round2_zone_validation(self, images: List[Path], zones: List[dict]) -> dict:
        """Round 2: 分区验证。"""
        if not zones:
            return {}

        zone_list = "\n".join(
            f"  - {z['name']}: {z.get('area_m2', 0):.0f} m²" for z in zones
        )
        first_zone = zones[0]["name"] if zones else "分区1"

        prompt = ROUND2_PROMPT_TEMPLATE.format(
            zone_list=zone_list,
            first_zone=first_zone,
        )
        raw = _call_vl_safe(images, prompt)
        return _parse_json_safe(raw) or {}


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _call_vl_safe(images: List[Path], prompt: str) -> str:
    """安全调用 VL 模型，返回原始文本。"""
    try:
        from src.vision import _call_vl
        return _call_vl(images, prompt)
    except ImportError:
        logger.warning("vision 模块不可用")
        return ""
    except Exception as e:
        logger.warning(f"VL 调用失败: {e}")
        return ""


def _parse_json_safe(text: str) -> Optional[dict]:
    """多级 JSON 解析回退。"""
    if not text:
        return None

    # Level 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Level 2: 从 markdown 代码块中提取
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Level 3: 正则提取 {...}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.debug(f"VL JSON 解析失败: {text[:200]}")
    return None
