"""CAD 文件处理模块。

支持 DWG/DXF 格式:
1. DXF: 使用 ezdxf 读取 + matplotlib 渲染为 PNG
2. DWG: 使用 ODA File Converter 转 DXF 后渲染; 或 LibreCAD 直接转 PNG

转换后的 PNG 可送入 VL 视觉模型进行智能分析。
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# 输出图片参数
CAD_PNG_DPI = 200
CAD_PNG_MAX_SIZE = 4096  # 最大像素尺寸


def _find_oda_converter() -> str | None:
    """查找 ODA File Converter 可执行文件路径。"""
    # 1. 系统 PATH
    for name in ["ODAFileConverter", "TeighaFileConverter"]:
        found = shutil.which(name)
        if found:
            return found

    # 2. 常见安装路径 (Windows + Linux)
    candidates = [
        # Windows
        "D:/ODAFILECONVERTER/ODAFileConverter.exe",
        "C:/Program Files/ODA/ODAFileConverter.exe",
        "C:/Program Files (x86)/ODA/ODAFileConverter.exe",
        # Linux
        "/usr/bin/ODAFileConverter",
        "/usr/local/bin/ODAFileConverter",
        "/opt/ODAFileConverter/ODAFileConverter",
    ]
    for path in candidates:
        if Path(path).exists():
            return path

    return None


def is_cad_file(file_path: Path) -> bool:
    """判断是否为 CAD 格式文件。"""
    return file_path.suffix.lower() in {".dwg", ".dxf"}


def convert_cad_to_png(file_path: Path, output_dir: Path | None = None) -> Path | None:
    """将 CAD 文件 (DWG/DXF) 转换为 PNG 图片。

    转换策略:
    1. DXF → ezdxf + matplotlib 直接渲染
    2. DWG → ODA File Converter 转 DXF → ezdxf 渲染
    3. DWG (fallback) → LibreCAD CLI 直接导出 PNG

    Args:
        file_path: CAD 文件路径
        output_dir: PNG 输出目录 (默认与源文件同目录)

    Returns:
        生成的 PNG 文件路径, 或 None (转换失败)
    """
    file_path = Path(file_path)
    if not file_path.exists():
        logger.error(f"CAD 文件不存在: {file_path}")
        return None

    if output_dir is None:
        output_dir = file_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    out_png = output_dir / f"{file_path.stem}_cad.png"

    suffix = file_path.suffix.lower()

    if suffix == ".dxf":
        return _render_dxf_to_png(file_path, out_png)
    elif suffix == ".dwg":
        return _convert_dwg_to_png(file_path, out_png)
    else:
        logger.warning(f"不支持的 CAD 格式: {suffix}")
        return None


def _render_dxf_to_png(dxf_path: Path, out_png: Path) -> Path | None:
    """使用 ezdxf + matplotlib 将 DXF 渲染为 PNG。"""
    try:
        import ezdxf
        from ezdxf.addons.drawing import RenderContext, Frontend
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    except ImportError:
        logger.error("ezdxf 未安装。请运行: pip install ezdxf[draw]")
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.error("matplotlib 未安装")
        return None

    try:
        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()

        # 检查是否有实体
        entity_count = len(list(msp))
        if entity_count == 0:
            logger.warning(f"DXF 文件无实体: {dxf_path.name}")
            return None

        logger.info(f"DXF 读取成功: {dxf_path.name}, {entity_count} 个实体")

        # 使用 ezdxf 内置的 matplotlib 后端渲染
        fig = plt.figure(dpi=CAD_PNG_DPI)
        ax = fig.add_axes([0, 0, 1, 1])

        ctx = RenderContext(doc)
        out = MatplotlibBackend(ax)
        Frontend(ctx, out).draw_layout(msp)

        ax.set_aspect("equal")
        ax.autoscale()
        ax.axis("off")

        fig.savefig(str(out_png), dpi=CAD_PNG_DPI, bbox_inches="tight",
                    pad_inches=0.1, facecolor="white")
        plt.close(fig)

        logger.info(f"DXF → PNG 成功: {out_png.name} ({out_png.stat().st_size // 1024} KB)")
        return out_png

    except Exception as e:
        logger.error(f"DXF 渲染失败 ({dxf_path.name}): {e}")
        return None


def _convert_dwg_to_png(dwg_path: Path, out_png: Path) -> Path | None:
    """将 DWG 转换为 PNG。

    尝试策略:
    1. ODA File Converter → DXF → ezdxf 渲染
    2. LibreCAD 直接导出
    3. dwg2dxf 命令行工具
    """
    # 策略1: ODA File Converter
    oda_result = _dwg_via_oda(dwg_path, out_png)
    if oda_result:
        return oda_result

    # 策略2: LibreCAD
    libre_result = _dwg_via_librecad(dwg_path, out_png)
    if libre_result:
        return libre_result

    # 策略3: 尝试系统上的 dwg2dxf 或 TeighaFileConverter
    cli_result = _dwg_via_cli_tools(dwg_path, out_png)
    if cli_result:
        return cli_result

    logger.error(
        f"DWG 转换失败 ({dwg_path.name}): 未找到可用的转换工具。\n"
        "请安装以下任一工具:\n"
        "  1. ODA File Converter: https://www.opendesign.com/guestfiles/oda_file_converter\n"
        "  2. LibreCAD: apt install librecad\n"
        "  3. QCAD: https://qcad.org/"
    )
    return None


def _dwg_via_oda(dwg_path: Path, out_png: Path) -> Path | None:
    """通过 ODA File Converter 将 DWG → DXF → PNG。"""
    oda_bin = _find_oda_converter()
    if not oda_bin:
        return None

    logger.info(f"使用 ODA File Converter: {oda_bin}")

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_in = Path(tmp_dir) / "input"
            tmp_out = Path(tmp_dir) / "output"
            tmp_in.mkdir()
            tmp_out.mkdir()

            # 复制 DWG 到临时输入目录
            shutil.copy2(dwg_path, tmp_in / dwg_path.name)

            # ODA 命令: ODAFileConverter <input_dir> <output_dir> <version> <type> <recurse> <audit>
            # ACAD2018 格式, DXF ASCII 输出
            cmd = [
                oda_bin,
                str(tmp_in), str(tmp_out),
                "ACAD2018", "DXF", "0", "1",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                logger.warning(f"ODA 转换失败: {result.stderr}")
                return None

            # 查找输出的 DXF
            dxf_files = list(tmp_out.glob("*.dxf"))
            if not dxf_files:
                logger.warning("ODA 转换后未找到 DXF 文件")
                return None

            # 渲染 DXF → PNG
            return _render_dxf_to_png(dxf_files[0], out_png)

    except subprocess.TimeoutExpired:
        logger.error("ODA 转换超时 (120s)")
        return None
    except Exception as e:
        logger.error(f"ODA 转换异常: {e}")
        return None


def _dwg_via_librecad(dwg_path: Path, out_png: Path) -> Path | None:
    """通过 LibreCAD 将 DWG 导出为 PNG (需要 X11 或 xvfb)。"""
    librecad = shutil.which("librecad")
    if not librecad:
        return None

    try:
        # LibreCAD 命令行导出 (需要 xvfb-run 在无头模式)
        xvfb = shutil.which("xvfb-run")
        cmd = []
        if xvfb:
            cmd = [xvfb, "--auto-servernum", "--server-args=-screen 0 1280x1024x24"]
        cmd.extend([librecad, str(dwg_path), "-o", str(out_png)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if out_png.exists() and out_png.stat().st_size > 1000:
            logger.info(f"LibreCAD DWG → PNG 成功: {out_png.name}")
            return out_png
    except Exception as e:
        logger.warning(f"LibreCAD 转换失败: {e}")

    return None


def _dwg_via_cli_tools(dwg_path: Path, out_png: Path) -> Path | None:
    """尝试其他命令行工具转换 DWG。"""
    # dwg2dxf (GNU LibreDWG 工具)
    dwg2dxf = shutil.which("dwg2dxf")
    if dwg2dxf:
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_dxf = Path(tmp_dir) / f"{dwg_path.stem}.dxf"
                result = subprocess.run(
                    [dwg2dxf, "-o", str(tmp_dxf), str(dwg_path)],
                    capture_output=True, text=True, timeout=60,
                )
                if tmp_dxf.exists():
                    return _render_dxf_to_png(tmp_dxf, out_png)
        except Exception as e:
            logger.warning(f"dwg2dxf 转换失败: {e}")

    return None


def convert_dwg_to_dxf(dwg_path: Path, output_dir: Path | None = None) -> Path | None:
    """将 DWG 转换为 DXF 并保留中间文件 (供几何解析使用)。

    与 convert_cad_to_png 不同，此函数只做 DWG→DXF 转换，
    不渲染 PNG。输出的 DXF 文件保留在 output_dir 中。

    Args:
        dwg_path: DWG 文件路径
        output_dir: DXF 输出目录 (默认与源文件同目录)

    Returns:
        生成的 DXF 文件路径, 或 None (转换失败)
    """
    dwg_path = Path(dwg_path)
    if not dwg_path.exists():
        logger.error(f"DWG 文件不存在: {dwg_path}")
        return None
    if dwg_path.suffix.lower() != ".dwg":
        logger.warning(f"非 DWG 文件: {dwg_path.suffix}")
        return None

    if output_dir is None:
        output_dir = dwg_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    out_dxf = output_dir / f"{dwg_path.stem}.dxf"

    # 已有 DXF 则直接返回
    if out_dxf.exists() and out_dxf.stat().st_size > 100:
        logger.info(f"DXF 已存在, 复用: {out_dxf.name}")
        return out_dxf

    oda_bin = _find_oda_converter()
    if not oda_bin:
        logger.warning("ODA File Converter 未找到, 无法转换 DWG→DXF")
        return None

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_in = Path(tmp_dir) / "input"
            tmp_out = Path(tmp_dir) / "output"
            tmp_in.mkdir()
            tmp_out.mkdir()

            shutil.copy2(dwg_path, tmp_in / dwg_path.name)

            cmd = [
                oda_bin,
                str(tmp_in), str(tmp_out),
                "ACAD2018", "DXF", "0", "1",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                logger.warning(f"ODA DWG→DXF 转换失败: {result.stderr}")
                return None

            dxf_files = list(tmp_out.glob("*.dxf"))
            if not dxf_files:
                logger.warning("ODA 转换后未找到 DXF 文件")
                return None

            # 复制到持久目录
            shutil.copy2(dxf_files[0], out_dxf)
            logger.info(f"DWG→DXF 成功: {out_dxf.name} ({out_dxf.stat().st_size // 1024} KB)")
            return out_dxf

    except subprocess.TimeoutExpired:
        logger.error("ODA DWG→DXF 转换超时 (120s)")
        return None
    except Exception as e:
        logger.error(f"DWG→DXF 转换异常: {e}")
        return None


def render_dxf_layers(dxf_path: str, output_dir: Path, dpi: int = 300) -> dict[str, Path]:
    """按类别分层渲染为多张 PNG，供 VL 分轮分析。

    返回: {"full": Path, "building_road": Path, "boundary_text": Path,
           "contour": Path, "greenery": Path}

    层分组规则 (按 DXF layer 名称关键词):
    - building_road: "建筑","road","bldg","道路","building"
    - boundary_text: "boundary","红线","用地","text","标注","annotation"
    - contour: "等高","contour","elev"
    - greenery: "绿","green","veg"

    渲染方式: 每组高亮 + 其余灰化为背景。
    """
    try:
        import ezdxf
    except ImportError:
        logger.error("ezdxf 未安装")
        return {}

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.error("matplotlib 未安装")
        return {}

    dxf_path = Path(dxf_path)
    if not dxf_path.exists():
        logger.error(f"DXF 文件不存在: {dxf_path}")
        return {}

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        doc = ezdxf.readfile(str(dxf_path))
    except Exception as e:
        logger.error(f"DXF 读取失败: {e}")
        return {}

    msp = doc.modelspace()
    entities = list(msp)
    if not entities:
        return {}

    # 分组规则
    layer_groups = {
        "building_road": ["建筑", "road", "bldg", "道路", "building", "楼", "房"],
        "boundary_text": ["boundary", "红线", "用地", "text", "标注", "annotation", "dim"],
        "contour": ["等高", "contour", "elev", "高程"],
        "greenery": ["绿", "green", "veg", "植", "grass", "tree"],
    }

    # 收集所有图层名
    all_layers = set()
    for ent in entities:
        try:
            all_layers.add(ent.dxf.layer.lower())
        except Exception:
            pass

    # 分类图层
    layer_to_group: dict[str, str] = {}
    for layer_name in all_layers:
        ln = layer_name.lower()
        for group_name, keywords in layer_groups.items():
            if any(kw.lower() in ln for kw in keywords):
                layer_to_group[layer_name] = group_name
                break

    results: dict[str, Path] = {}

    # 1. 渲染完整图 (full)
    full_path = output_dir / f"{dxf_path.stem}_full.png"
    try:
        from ezdxf.addons.drawing import RenderContext, Frontend
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

        fig = plt.figure(dpi=dpi)
        ax = fig.add_axes([0, 0, 1, 1])
        ctx = RenderContext(doc)
        out = MatplotlibBackend(ax)
        Frontend(ctx, out).draw_layout(msp)
        ax.set_aspect("equal")
        ax.autoscale()
        ax.axis("off")
        fig.savefig(str(full_path), dpi=dpi, bbox_inches="tight",
                    pad_inches=0.1, facecolor="white")
        plt.close(fig)
        results["full"] = full_path
        logger.info(f"分层渲染 full: {full_path.name}")
    except Exception as e:
        logger.warning(f"全图渲染失败: {e}")
        # 回退: 尝试简化渲染
        try:
            fig, ax = plt.subplots(1, 1, figsize=(20, 16), dpi=dpi)
            for ent in entities:
                _plot_entity_simple(ax, ent, color="black", alpha=1.0)
            ax.set_aspect("equal")
            ax.autoscale()
            ax.axis("off")
            fig.savefig(str(full_path), dpi=dpi, bbox_inches="tight",
                        facecolor="white")
            plt.close(fig)
            results["full"] = full_path
        except Exception as e2:
            logger.warning(f"简化全图渲染也失败: {e2}")

    # 2. 按分组渲染高亮图
    for group_name in layer_groups:
        group_layers = {ln for ln, gn in layer_to_group.items() if gn == group_name}
        if not group_layers:
            continue

        out_path = output_dir / f"{dxf_path.stem}_{group_name}.png"
        try:
            fig, ax = plt.subplots(1, 1, figsize=(20, 16), dpi=dpi)

            # 背景: 所有实体灰色
            for ent in entities:
                _plot_entity_simple(ax, ent, color="#cccccc", alpha=0.3)

            # 高亮: 目标图层实体
            for ent in entities:
                try:
                    ent_layer = ent.dxf.layer.lower()
                except Exception:
                    continue
                if ent_layer in group_layers:
                    _plot_entity_simple(ax, ent, color="red", alpha=1.0, linewidth=1.5)

            ax.set_aspect("equal")
            ax.autoscale()
            ax.axis("off")
            fig.savefig(str(out_path), dpi=dpi, bbox_inches="tight",
                        facecolor="white")
            plt.close(fig)
            results[group_name] = out_path
            logger.info(f"分层渲染 {group_name}: {out_path.name} ({len(group_layers)} layers)")
        except Exception as e:
            logger.warning(f"分层渲染 {group_name} 失败: {e}")

    return results


def _plot_entity_simple(ax, entity, color: str = "black", alpha: float = 1.0,
                         linewidth: float = 0.5):
    """简化实体绘制 (LINE, POLYLINE, LWPOLYLINE, CIRCLE, ARC)。"""
    dxftype = entity.dxftype()
    try:
        if dxftype == "LINE":
            start = entity.dxf.start
            end = entity.dxf.end
            ax.plot([start.x, end.x], [start.y, end.y],
                    color=color, alpha=alpha, linewidth=linewidth)
        elif dxftype in ("LWPOLYLINE", "POLYLINE"):
            pts = list(entity.get_points(format="xy"))
            if pts:
                xs, ys = zip(*pts)
                if entity.closed:
                    xs = list(xs) + [xs[0]]
                    ys = list(ys) + [ys[0]]
                ax.plot(xs, ys, color=color, alpha=alpha, linewidth=linewidth)
        elif dxftype == "CIRCLE":
            import numpy as np
            cx, cy = entity.dxf.center.x, entity.dxf.center.y
            r = entity.dxf.radius
            theta = np.linspace(0, 2 * 3.14159, 64)
            ax.plot(cx + r * np.cos(theta), cy + r * np.sin(theta),
                    color=color, alpha=alpha, linewidth=linewidth)
        elif dxftype == "ARC":
            import numpy as np
            cx, cy = entity.dxf.center.x, entity.dxf.center.y
            r = entity.dxf.radius
            a1 = entity.dxf.start_angle * 3.14159 / 180
            a2 = entity.dxf.end_angle * 3.14159 / 180
            if a2 < a1:
                a2 += 2 * 3.14159
            theta = np.linspace(a1, a2, 32)
            ax.plot(cx + r * np.cos(theta), cy + r * np.sin(theta),
                    color=color, alpha=alpha, linewidth=linewidth)
    except Exception:
        pass  # 跳过无法绘制的实体


def batch_convert_cad(file_paths: list[Path],
                      output_dir: Path | None = None) -> list[dict]:
    """批量转换 CAD 文件, 返回转换结果列表。

    Args:
        file_paths: CAD 文件路径列表
        output_dir: PNG 输出目录

    Returns:
        [{"source": "xxx.dwg", "png": Path|None, "status": "ok"|"error", "message": str}, ...]
    """
    results = []
    for fp in file_paths:
        if not is_cad_file(fp):
            continue
        try:
            png = convert_cad_to_png(fp, output_dir)
            if png:
                results.append({
                    "source": fp.name,
                    "png": png,
                    "status": "ok",
                    "message": f"转换成功: {png.name}",
                })
            else:
                results.append({
                    "source": fp.name,
                    "png": None,
                    "status": "error",
                    "message": "转换失败: 未找到可用的 CAD 转换工具",
                })
        except Exception as e:
            results.append({
                "source": fp.name,
                "png": None,
                "status": "error",
                "message": f"转换异常: {e}",
            })
    return results
