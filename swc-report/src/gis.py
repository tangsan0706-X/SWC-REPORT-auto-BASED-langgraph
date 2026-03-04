"""GIS 文件处理模块。

支持 Shapefile (.shp) 和 GeoJSON (.geojson) 格式:
1. 读取矢量数据，计算各地块面积
2. 根据属性字段自动映射到防治分区
3. 与 facts.json 中的分区面积进行容差校验
4. 生成分区总览图 PNG (用于 VL 分析)

依赖: geopandas, shapely, matplotlib
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 面积校验容差 (%)
AREA_TOLERANCE_PERCENT = 5.0

# 分区名称关键词映射
ZONE_NAME_MAP = {
    "建筑": "建(构)筑物区",
    "构筑": "建(构)筑物区",
    "住宅": "建(构)筑物区",
    "厂房": "建(构)筑物区",
    "道路": "道路广场区",
    "广场": "道路广场区",
    "停车": "道路广场区",
    "绿化": "绿化工程区",
    "绿地": "绿化工程区",
    "景观": "绿化工程区",
    "临时": "施工生产生活区",
    "施工": "施工生产生活区",
    "生活": "施工生产生活区",
    "堆土": "临时堆土区",
    "堆放": "临时堆土区",
    "弃渣": "弃渣场",
    "弃土": "弃渣场",
    "取土": "取土场",
    "管线": "道路及管线工程区",
    "管网": "道路及管线工程区",
}


def is_gis_file(file_path: Path) -> bool:
    """判断是否为 GIS 矢量文件。"""
    return file_path.suffix.lower() in {".shp", ".geojson", ".gpkg"}


def extract_zones_from_shp(shp_path: Path) -> list[dict]:
    """从 Shapefile 中提取分区信息。

    自动检测属性字段，映射到水保防治分区名称，计算面积。

    Args:
        shp_path: Shapefile 路径 (.shp)

    Returns:
        [{"name": "建(构)筑物区", "area_hm2": 1.23, "area_m2": 12300.0,
          "original_name": "住宅用地", "geometry_type": "Polygon"}, ...]
    """
    try:
        import geopandas as gpd
    except ImportError:
        logger.error("geopandas 未安装。请运行: pip install geopandas")
        return []

    try:
        gdf = gpd.read_file(str(shp_path))
    except Exception as e:
        logger.error(f"读取 GIS 文件失败 ({shp_path.name}): {e}")
        return []

    if gdf.empty:
        logger.warning(f"GIS 文件无数据: {shp_path.name}")
        return []

    logger.info(f"GIS 读取成功: {shp_path.name}, {len(gdf)} 个要素, CRS={gdf.crs}")

    # 如果有投影坐标系，直接用；否则投影到合适的 UTM 区
    gdf_projected = _ensure_projected(gdf)

    # 计算面积 (m²)
    gdf_projected["_area_m2"] = gdf_projected.geometry.area

    # 检测分区名称字段
    name_col = _detect_name_column(gdf_projected)

    zones = []
    if name_col:
        # 按名称分组求和面积
        for name_val, group in gdf_projected.groupby(name_col):
            area_m2 = group["_area_m2"].sum()
            zone_name = _map_zone_name(str(name_val))
            zones.append({
                "name": zone_name,
                "area_hm2": round(area_m2 / 10000, 4),
                "area_m2": round(area_m2, 1),
                "original_name": str(name_val),
                "geometry_type": group.geometry.iloc[0].geom_type,
                "feature_count": len(group),
            })
    else:
        # 无分区名称字段 → 每个要素作为独立分区
        for idx, row in gdf_projected.iterrows():
            area_m2 = row["_area_m2"]
            zones.append({
                "name": f"分区{idx + 1}",
                "area_hm2": round(area_m2 / 10000, 4),
                "area_m2": round(area_m2, 1),
                "original_name": f"Feature_{idx}",
                "geometry_type": row.geometry.geom_type,
                "feature_count": 1,
            })

    # 按面积降序
    zones.sort(key=lambda z: z["area_hm2"], reverse=True)
    logger.info(f"GIS 提取分区: {len(zones)} 个, 总面积 {sum(z['area_hm2'] for z in zones):.4f} hm²")
    return zones


def validate_zones(gis_zones: list[dict],
                   facts_zones: list[dict],
                   tolerance_pct: float = AREA_TOLERANCE_PERCENT) -> dict:
    """校验 GIS 分区面积与 facts.json 的一致性。

    Args:
        gis_zones: extract_zones_from_shp() 的输出
        facts_zones: facts_v2.json 中的 zones 列表
        tolerance_pct: 面积容差百分比 (默认 5%)

    Returns:
        {
            "valid": bool,
            "total_area_gis_hm2": float,
            "total_area_facts_hm2": float,
            "total_diff_pct": float,
            "zone_checks": [{"name", "gis_hm2", "facts_hm2", "diff_pct", "match": bool}, ...],
            "unmatched_gis": [...],
            "unmatched_facts": [...],
            "messages": [str, ...],
        }
    """
    result = {
        "valid": True,
        "total_area_gis_hm2": 0.0,
        "total_area_facts_hm2": 0.0,
        "total_diff_pct": 0.0,
        "zone_checks": [],
        "unmatched_gis": [],
        "unmatched_facts": [],
        "messages": [],
    }

    # 建立 facts 分区索引
    facts_map = {}
    for fz in facts_zones:
        name = fz.get("name", "")
        area = fz.get("area_hm2", 0)
        facts_map[name] = area
        result["total_area_facts_hm2"] += area

    # GIS 总面积
    result["total_area_gis_hm2"] = sum(z["area_hm2"] for z in gis_zones)

    # 总面积偏差
    if result["total_area_facts_hm2"] > 0:
        result["total_diff_pct"] = round(
            abs(result["total_area_gis_hm2"] - result["total_area_facts_hm2"])
            / result["total_area_facts_hm2"] * 100, 2
        )
    else:
        result["total_diff_pct"] = 100.0

    # 逐分区匹配
    matched_facts = set()
    for gz in gis_zones:
        gis_name = gz["name"]
        gis_area = gz["area_hm2"]

        # 精确匹配或模糊匹配
        match_name = None
        for fn in facts_map:
            if fn == gis_name or _fuzzy_match(gis_name, fn):
                match_name = fn
                break

        if match_name:
            facts_area = facts_map[match_name]
            matched_facts.add(match_name)
            diff_pct = 0.0
            if facts_area > 0:
                diff_pct = round(abs(gis_area - facts_area) / facts_area * 100, 2)
            is_match = diff_pct <= tolerance_pct
            result["zone_checks"].append({
                "name": gis_name,
                "facts_name": match_name,
                "gis_hm2": gis_area,
                "facts_hm2": facts_area,
                "diff_pct": diff_pct,
                "match": is_match,
            })
            if not is_match:
                result["valid"] = False
                result["messages"].append(
                    f"分区 [{gis_name}] 面积偏差 {diff_pct:.1f}% "
                    f"(GIS={gis_area:.4f} vs facts={facts_area:.4f} hm²)"
                )
        else:
            result["unmatched_gis"].append({
                "name": gis_name,
                "area_hm2": gis_area,
            })

    # facts 中未匹配的分区
    for fn, fa in facts_map.items():
        if fn not in matched_facts:
            result["unmatched_facts"].append({
                "name": fn,
                "area_hm2": fa,
            })

    if result["unmatched_gis"]:
        result["messages"].append(
            f"GIS 中有 {len(result['unmatched_gis'])} 个分区未匹配: "
            + ", ".join(z["name"] for z in result["unmatched_gis"])
        )
    if result["unmatched_facts"]:
        result["messages"].append(
            f"facts 中有 {len(result['unmatched_facts'])} 个分区在 GIS 中未找到: "
            + ", ".join(z["name"] for z in result["unmatched_facts"])
        )

    # 总面积偏差检查
    if result["total_diff_pct"] > tolerance_pct:
        result["valid"] = False
        result["messages"].append(
            f"总面积偏差 {result['total_diff_pct']:.1f}% 超过容差 {tolerance_pct}%"
        )

    if result["valid"]:
        result["messages"].insert(0, "GIS 分区面积校验通过")

    return result


def render_zones_to_png(shp_path: Path, output_path: Path | None = None) -> Path | None:
    """将 GIS 分区渲染为带标注的 PNG 总览图。

    Args:
        shp_path: Shapefile 路径
        output_path: 输出 PNG 路径 (默认同目录)

    Returns:
        PNG 文件路径
    """
    try:
        import geopandas as gpd
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError:
        logger.error("geopandas 或 matplotlib 未安装")
        return None

    try:
        gdf = gpd.read_file(str(shp_path))
        if gdf.empty:
            return None

        # 配置中文字体
        _setup_chinese_font()

        fig, ax = plt.subplots(1, 1, figsize=(12, 10), dpi=150)

        name_col = _detect_name_column(gdf)
        if name_col:
            gdf.plot(ax=ax, column=name_col, legend=True, cmap="Set3",
                     edgecolor="black", linewidth=0.5)
            # 标注
            for idx, row in gdf.iterrows():
                centroid = row.geometry.centroid
                label = str(row[name_col])
                ax.annotate(label, xy=(centroid.x, centroid.y),
                           ha="center", va="center", fontsize=7,
                           bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7))
        else:
            gdf.plot(ax=ax, edgecolor="black", linewidth=0.5, facecolor="lightblue")

        ax.set_title("项目分区总览", fontsize=14)
        ax.set_aspect("equal")
        ax.axis("off")

        if output_path is None:
            output_path = shp_path.parent / f"{shp_path.stem}_zones.png"

        fig.savefig(str(output_path), dpi=150, bbox_inches="tight",
                    pad_inches=0.2, facecolor="white")
        plt.close(fig)
        logger.info(f"GIS → PNG 成功: {output_path.name}")
        return output_path

    except Exception as e:
        logger.error(f"GIS 渲染失败: {e}")
        return None


# ── 内部工具函数 ──────────────────────────────────────────

def _ensure_projected(gdf):
    """确保 GeoDataFrame 使用投影坐标系 (m 为单位)。"""
    try:
        import geopandas as gpd
    except ImportError:
        return gdf

    if gdf.crs is None:
        logger.warning("GIS 数据无 CRS 信息，假设为 WGS84")
        gdf = gdf.set_crs(epsg=4326)

    if gdf.crs.is_geographic:
        # 地理坐标系 → 投影到合适的 UTM 区
        centroid = gdf.geometry.unary_union.centroid
        utm_zone = int((centroid.x + 180) / 6) + 1
        hemisphere = "north" if centroid.y >= 0 else "south"
        # EPSG: 326xx (北半球) 或 327xx (南半球)
        epsg = (32600 if hemisphere == "north" else 32700) + utm_zone
        logger.info(f"投影到 UTM Zone {utm_zone}{hemisphere[0].upper()} (EPSG:{epsg})")
        gdf = gdf.to_crs(epsg=epsg)

    return gdf


def _detect_name_column(gdf) -> str | None:
    """自动检测分区名称字段。"""
    # 优先候选列名
    candidates = ["name", "名称", "分区", "zone", "zone_name", "用途", "类型",
                  "type", "landuse", "land_use", "category", "class", "NAME",
                  "ZONE", "LANDUSE", "fq_name", "fq_mc"]

    for col in candidates:
        if col in gdf.columns:
            # 确认有实际值
            non_null = gdf[col].dropna()
            if len(non_null) > 0:
                return col

    # 回退: 找第一个字符串类型列
    for col in gdf.columns:
        if col == "geometry":
            continue
        if gdf[col].dtype == "object":
            non_null = gdf[col].dropna()
            if len(non_null) > 0:
                return col

    return None


def _map_zone_name(original_name: str) -> str:
    """将原始地块名称映射到标准防治分区名称。"""
    for keyword, zone_name in ZONE_NAME_MAP.items():
        if keyword in original_name:
            return zone_name
    return original_name  # 无法匹配时保留原名


def _fuzzy_match(name_a: str, name_b: str) -> bool:
    """模糊匹配两个分区名称 (去括号、去空格后比较)。"""
    def normalize(s: str) -> str:
        return (s.replace("(", "（").replace(")", "）")
                 .replace(" ", "").replace("　", "").strip())
    return normalize(name_a) == normalize(name_b)


def _setup_chinese_font():
    """设置 matplotlib 中文字体。"""
    try:
        import matplotlib.pyplot as plt
        from matplotlib import font_manager

        font_names = ["SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC",
                      "Microsoft YaHei", "PingFang SC"]
        for name in font_names:
            fonts = font_manager.findSystemFonts()
            for f in fonts:
                try:
                    fp = font_manager.FontProperties(fname=f)
                    if name.lower() in fp.get_name().lower():
                        plt.rcParams["font.sans-serif"] = [name]
                        plt.rcParams["axes.unicode_minus"] = False
                        return
                except Exception:
                    continue
    except Exception:
        pass
