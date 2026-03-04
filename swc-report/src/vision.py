"""视觉模型 (VL) 文档处理模块。

使用 Qwen2.5-VL 多模态模型:
1. 从上传的项目文档 (JPG/PNG/BMP/PDF) 中提取结构化项目信息
2. 从施工图纸/现场照片生成项目现场描述 (site_desc)

VL 模型通过 vLLM OpenAI-compatible API 部署在端口 8001。
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

import src.settings as settings

logger = logging.getLogger(__name__)


def _get_vl_client() -> OpenAI:
    """创建 VL 模型客户端。"""
    return OpenAI(base_url=settings.VL_URL, api_key="not-needed")


MAX_IMAGE_LONG_SIDE = 1344  # 最长边限制
MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2MB
VL_PATCH_SIZE = 28  # Qwen VL 的 patch size，尺寸必须是其倍数


def _encode_image(file_path: Path) -> tuple[str, str]:
    """读取图片文件，返回 (base64_data, mime_type)。

    自动处理:
    - 缩小大图 (最长边 1344px)
    - 尺寸对齐 VL patch size (28 的倍数，避免 GGML 张量断言错误)
    - 转为 JPEG 统一格式
    """
    try:
        from PIL import Image
        import io
        img = Image.open(file_path)
        w, h = img.size
        # 缩放到最长边不超过限制
        scale = min(MAX_IMAGE_LONG_SIDE / max(w, h), 1.0)
        new_w = int(w * scale)
        new_h = int(h * scale)
        # 对齐 patch size (28 的倍数)
        new_w = max(VL_PATCH_SIZE, new_w // VL_PATCH_SIZE * VL_PATCH_SIZE)
        new_h = max(VL_PATCH_SIZE, new_h // VL_PATCH_SIZE * VL_PATCH_SIZE)
        if new_w != w or new_h != h:
            img = img.resize((new_w, new_h), Image.LANCZOS)
            logger.info(f"缩放图片 {file_path.name}: {w}x{h} → {new_w}x{new_h}")
        # 统一输出 JPEG
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        quality = 85
        img.save(buf, format="JPEG", quality=quality)
        while buf.tell() > MAX_IMAGE_BYTES and quality > 30:
            quality -= 15
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"
    except ImportError:
        logger.warning("Pillow 未安装，无法处理图片")
    except Exception as e:
        logger.warning(f"图片处理失败 ({file_path.name}): {e}")
    # 回退: 直接读取原始文件
    data = file_path.read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    mime, _ = mimetypes.guess_type(str(file_path))
    if not mime:
        mime = "image/jpeg"
    return b64, mime


def _is_image(file_path: Path) -> bool:
    """判断是否为可处理的图片文件。"""
    return file_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}


def _is_cad(file_path: Path) -> bool:
    """判断是否为 CAD 文件。"""
    return file_path.suffix.lower() in {".dwg", ".dxf"}


def _is_gis(file_path: Path) -> bool:
    """判断是否为 GIS 矢量文件。"""
    return file_path.suffix.lower() in {".shp", ".geojson", ".gpkg"}


def _is_pdf(file_path: Path) -> bool:
    return file_path.suffix.lower() == ".pdf"


def _pdf_to_images(pdf_path: Path, max_pages: int = 5) -> list[Path]:
    """将 PDF 前几页转为图片 (需要 pdf2image/Pillow)。"""
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(str(pdf_path), first_page=1, last_page=max_pages, dpi=200)
        result = []
        for i, img in enumerate(images):
            out = pdf_path.parent / f"_pdf_page_{pdf_path.stem}_{i}.png"
            img.save(str(out), "PNG")
            result.append(out)
        return result
    except ImportError:
        logger.warning("pdf2image 未安装，跳过 PDF 处理。pip install pdf2image")
        return []
    except Exception as e:
        logger.warning(f"PDF 转图失败 ({pdf_path.name}): {e}")
        return []


def _is_ollama() -> bool:
    """判断 VL 后端是否为 Ollama (端口 11434)。"""
    return "11434" in settings.VL_URL


def _call_vl(images: list[Path], prompt: str, max_tokens: int | None = None) -> str:
    """调用 VL 模型，发送图片 + 文本 prompt，返回模型输出。

    自动适配 Ollama 原生 API 和 vLLM OpenAI-compatible API。
    """
    image_b64s = []
    for img_path in images:
        b64, mime = _encode_image(img_path)
        image_b64s.append((b64, mime))

    if _is_ollama():
        return _call_vl_ollama(image_b64s, prompt)
    else:
        return _call_vl_openai(image_b64s, prompt, max_tokens)


def _call_vl_ollama(image_b64s: list[tuple[str, str]], prompt: str) -> str:
    """通过 Ollama 原生 API 调用 VL 模型 (支持 images 字段)。"""
    import requests

    # Ollama 原生 API: /api/chat，images 是 base64 列表
    base_url = settings.VL_URL.replace("/v1", "")  # http://localhost:11434
    logger.info(f"Ollama VL 调用: {len(image_b64s)} 张图片, model={settings.VL_MODEL_NAME}")
    resp = requests.post(
        f"{base_url}/api/chat",
        json={
            "model": settings.VL_MODEL_NAME,
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [b64 for b64, _ in image_b64s],
            }],
            "stream": False,
        },
        timeout=600,  # CPU 模式下需要更长超时
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("message", {}).get("content", "")


def _call_vl_openai(image_b64s: list[tuple[str, str]], prompt: str,
                     max_tokens: int | None = None) -> str:
    """通过 OpenAI-compatible API (vLLM) 调用 VL 模型。"""
    client = _get_vl_client()
    content: list[dict[str, Any]] = []

    for b64, mime in image_b64s:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })

    content.append({"type": "text", "text": prompt})

    response = client.chat.completions.create(
        model=settings.VL_MODEL_NAME,
        messages=[{"role": "user", "content": content}],
        max_tokens=max_tokens or settings.VL_MAX_TOKENS,
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


# ── 公开 API ──────────────────────────────────────────────

EXTRACT_PROMPT = """你是一个水土保持方案报告编制助手。请从以下项目文档图片中提取结构化信息。

需要提取的字段 (尽可能提取，没有找到的留空字符串或null):
{
  "project_name": "项目名称",
  "investor": "建设单位/投资方",
  "location": {
    "province": "省份",
    "city": "城市",
    "district": "区县",
    "address": "详细地址"
  },
  "project_nature": "新建/改建/扩建",
  "project_type": "房地产/市政道路/工业厂房等",
  "total_investment_万元": 数字或null,
  "civil_investment_万元": 数字或null,
  "construction_area_m2": 数字或null,
  "land_area_hm2": 数字或null,
  "earthwork": {
    "excavation_m3": 数字或null,
    "fill_m3": 数字或null
  },
  "schedule": {
    "start_date": "YYYY-MM-DD或空",
    "end_date": "YYYY-MM-DD或空",
    "construction_period_months": 数字或null
  }
}

请仅输出 JSON，不要输出其他内容。如果某个字段在图片中没有找到，请设为 null。"""

SITE_DESC_PROMPT = """你是一个水土保持方案报告编制助手。请根据以下项目图纸/现场照片，撰写"项目区自然概况"描述段落。

要求:
1. 描述项目所在地的地形地貌特征
2. 描述周边环境和用地情况
3. 如果能看到施工现场，描述施工现状
4. 使用专业的水土保持报告语言风格
5. 字数 200-500 字

请直接输出描述文本，不要添加标题或额外说明。"""


def _prioritize_files(file_paths: list[Path], max_count: int = 8) -> list[Path]:
    """智能筛选最有价值的文档文件用于 VL 分析。

    优先级: 立项文件 > 用地/规划许可 > 蓝图/总图 > 施工许可 > 土方合同 > 其他
    排除: 三轴试验 BMP 等技术测试图 (信息价值低)
    """
    # 排除列表 — 这些文件对提取项目基本信息没有价值
    skip_keywords = {"三轴", "固结", "剪切", "波速", "水质", "柱状图",
                     "剖面图", "勘探点平面", "统计表", "图例"}

    # 优先级关键词 (越靠前越重要)
    priority_keywords = [
        ("立项", 10), ("批复", 10), ("可研", 10),
        ("规划许可", 9), ("不动产", 9), ("用地", 8),
        ("蓝图", 7), ("总图", 7), ("平面图", 7),
        ("施工许可", 6),
        ("土方", 5), ("土石方", 5),
        ("水保", 4), ("水土保持", 4),
    ]

    scored: list[tuple[int, Path]] = []
    for fp in file_paths:
        if not (_is_image(fp) or _is_pdf(fp) or _is_cad(fp)):
            continue
        name = fp.name
        # 跳过无价值文件
        if any(kw in name for kw in skip_keywords):
            continue
        score = 0
        for kw, s in priority_keywords:
            if kw in name:
                score = max(score, s)
                break
        scored.append((score, fp))

    scored.sort(key=lambda x: -x[0])
    return [fp for _, fp in scored[:max_count]]


def extract_project_info(file_paths: list[Path],
                         on_progress: Any | None = None) -> dict:
    """从项目文档中提取结构化项目信息。

    Args:
        file_paths: 上传的文档文件路径列表 (JPG/PNG/BMP/PDF)
        on_progress: 可选的进度回调

    Returns:
        提取到的 facts 字段 dict (可直接 merge 到表单)
    """
    # 智能筛选最有价值的文件 (Ollama CPU 模式下限制为 3 张以避免超时)
    max_imgs = 3 if _is_ollama() else 8
    selected = _prioritize_files(file_paths, max_count=max_imgs)
    images_to_process: list[Path] = []
    temp_files: list[Path] = []

    for fp in selected:
        if _is_image(fp):
            images_to_process.append(fp)
        elif _is_pdf(fp):
            pdf_imgs = _pdf_to_images(fp, max_pages=3)
            images_to_process.extend(pdf_imgs)
            temp_files.extend(pdf_imgs)
        elif _is_cad(fp):
            cad_png = _cad_to_image(fp)
            if cad_png:
                images_to_process.append(cad_png)
                temp_files.append(cad_png)

    if not images_to_process:
        logger.warning("没有可处理的图片文件")
        return {}

    logger.info(f"VL 提取: 从 {len(file_paths)} 个文件中选择了 {len(images_to_process)} 张图片")

    if on_progress:
        on_progress({"step": "vl_extract", "status": "running",
                      "message": f"正在分析 {len(images_to_process)} 张文档图片..."})

    try:
        raw = _call_vl(images_to_process, EXTRACT_PROMPT)
        # 解析 JSON
        result = _parse_json(raw)
    except Exception as e:
        logger.error(f"VL 提取失败: {e}")
        result = {}
    finally:
        # 清理临时 PDF 转图文件
        for tmp in temp_files:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    if on_progress:
        on_progress({"step": "vl_extract", "status": "done"})

    return result


def generate_site_description(file_paths: list[Path],
                              on_progress: Any | None = None) -> str:
    """从图纸/照片生成项目现场描述。

    Args:
        file_paths: 图纸/照片文件路径列表
        on_progress: 可选的进度回调

    Returns:
        生成的现场描述文本
    """
    images_to_process: list[Path] = []
    temp_files: list[Path] = []

    for fp in file_paths:
        if _is_image(fp):
            images_to_process.append(fp)
        elif _is_pdf(fp):
            pdf_imgs = _pdf_to_images(fp, max_pages=2)
            images_to_process.extend(pdf_imgs)
            temp_files.extend(pdf_imgs)
        elif _is_cad(fp):
            cad_png = _cad_to_image(fp)
            if cad_png:
                images_to_process.append(cad_png)
                temp_files.append(cad_png)

    if not images_to_process:
        logger.warning("没有可处理的图片文件")
        return ""

    if len(images_to_process) > 6:
        images_to_process = images_to_process[:6]

    if on_progress:
        on_progress({"step": "vl_site_desc", "status": "running",
                      "message": f"正在根据 {len(images_to_process)} 张图片生成现场描述..."})

    try:
        text = _call_vl(images_to_process, SITE_DESC_PROMPT)
    except Exception as e:
        logger.error(f"VL 生成现场描述失败: {e}")
        text = ""
    finally:
        for tmp in temp_files:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    if on_progress:
        on_progress({"step": "vl_site_desc", "status": "done"})

    return text.strip()


def classify_documents(file_paths: list[Path]) -> dict[str, list[Path]]:
    """按文件名和目录名对文档进行分类。

    Returns:
        {
            "立项文件": [...],
            "施工许可证": [...],
            "图纸": [...],
            "土方文件": [...],
            "岩土报告": [...],
            "用地文件": [...],
            "其他": [...],
        }
    """
    categories = {
        "立项文件": [],
        "施工许可证": [],
        "施工组织设计": [],
        "水保报告书": [],
        "图纸": [],
        "CAD图纸": [],
        "GIS数据": [],
        "土方文件": [],
        "岩土报告": [],
        "用地文件": [],
        "用地规划许可": [],
        "其他": [],
    }

    keywords = {
        "立项": "立项文件",
        "批复": "立项文件",
        "可研": "立项文件",
        "施工许可": "施工许可证",
        "施工组织": "施工组织设计",
        "水保": "水保报告书",
        "水土保持": "水保报告书",
        "总图": "图纸",
        "蓝图": "图纸",
        "平面图": "图纸",
        "图纸": "图纸",
        "土方": "土方文件",
        "土石方": "土方文件",
        "建筑垃圾": "土方文件",
        "岩土": "岩土报告",
        "勘察": "岩土报告",
        "勘探": "岩土报告",
        "不动产": "用地文件",
        "用地": "用地文件",
        "规划许可": "用地规划许可",
    }

    for fp in file_paths:
        # CAD / GIS 文件按扩展名优先归类
        if _is_cad(fp):
            categories["CAD图纸"].append(fp)
            continue
        if _is_gis(fp):
            categories["GIS数据"].append(fp)
            continue

        name = fp.name
        parent = fp.parent.name
        matched = False
        for kw, cat in keywords.items():
            if kw in name or kw in parent:
                categories[cat].append(fp)
                matched = True
                break
        if not matched:
            categories["其他"].append(fp)

    return {k: v for k, v in categories.items() if v}


def _cad_to_image(file_path: Path) -> Path | None:
    """将 CAD 文件转换为 PNG 图片 (用于 VL 分析)。"""
    try:
        from src.cad import convert_cad_to_png
        png = convert_cad_to_png(file_path)
        if png and png.exists():
            logger.info(f"CAD → PNG: {file_path.name} → {png.name}")
            return png
    except ImportError:
        logger.warning("CAD 模块不可用 (缺少 ezdxf)")
    except Exception as e:
        logger.warning(f"CAD 转换失败 ({file_path.name}): {e}")
    return None


def _parse_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON。"""
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试从 markdown 代码块中提取
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 尝试提取第一个 { ... } 块
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    logger.warning(f"无法解析 VL 输出为 JSON: {text[:200]}")
    return {}
