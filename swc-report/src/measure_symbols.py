"""水土保持措施符号/样式定义 — 用于措施图渲染。

纯黑白方案: 通过线型/填充图案/标记形状/灰度区分措施类型。

提供:
  - MEASURE_STYLES: 35 种措施的绘图样式 (灰度/线型/填充/标记)
  - SECTION_TEMPLATES: 典型工程断面参数 (排水沟/挡墙等)
  - ZONE_COLORS: 分区底色 (灰度)
  - MAP_DEFAULTS: 地图默认参数 (DPI/字体/比例尺样式)
"""

from __future__ import annotations

# ── 措施绘图样式 ────────────────────────────────────────────────
# type: "line" — 线状措施 (排水沟/截水沟/拦挡)
# type: "fill" — 面状措施 (绿化/覆盖/铺装)
# type: "point" — 点状措施 (沉沙池/冲洗平台)
#
# 纯黑白: 颜色仅用黑/深灰/浅灰, 区分靠 linestyle/hatch/marker

MEASURE_STYLES: dict[str, dict] = {
    # ── 工程措施 (ENG) ──
    "排水沟C20(40×40)":   {"type": "line",  "color": "#000000", "linewidth": 2.0, "linestyle": "-",  "label": "排水沟(40×40)",   "hatch": None, "color_professional": "#1E90FF"},
    "排水沟C20(60×60)":   {"type": "line",  "color": "#000000", "linewidth": 2.8, "linestyle": "-",  "label": "排水沟(60×60)",   "hatch": None, "color_professional": "#1E90FF"},
    "截水沟C20(30×30)":   {"type": "line",  "color": "#000000", "linewidth": 1.8, "linestyle": "--", "label": "截水沟(30×30)",   "hatch": None, "color_professional": "#4169E1"},
    "截水沟C20(40×40)":   {"type": "line",  "color": "#000000", "linewidth": 2.2, "linestyle": "--", "label": "截水沟(40×40)",   "hatch": None, "color_professional": "#4169E1"},
    "沉沙池(2×2×1.5m)":   {"type": "point", "color": "#000000", "marker": "s", "size": 80,  "label": "沉沙池(小)", "color_professional": "#4682B4"},
    "沉沙池(3×3×2m)":     {"type": "point", "color": "#000000", "marker": "s", "size": 120, "label": "沉沙池(大)", "color_professional": "#4682B4"},
    "透水砖铺装":         {"type": "fill",  "color": "#999999", "alpha": 0.25, "hatch": "...", "label": "透水砖铺装", "color_professional": "#808080"},
    "碎石盲沟":           {"type": "line",  "color": "#666666", "linewidth": 1.5, "linestyle": ":",  "label": "碎石盲沟",   "hatch": None, "color_professional": "#5F9EA0"},
    "HDPE防渗膜":         {"type": "fill",  "color": "#AAAAAA", "alpha": 0.3,  "hatch": "///", "label": "HDPE防渗膜", "color_professional": "#708090"},
    "场地平整":           {"type": "fill",  "color": "#D0D0D0", "alpha": 0.15, "hatch": None, "label": "场地平整", "color_professional": "#A0A0A0"},
    "表土剥离":           {"type": "fill",  "color": "#888888", "alpha": 0.25, "hatch": "xxx", "label": "表土剥离", "color_professional": "#8B7355"},
    "表土回覆":           {"type": "fill",  "color": "#999999", "alpha": 0.25, "hatch": "ooo", "label": "表土回覆", "color_professional": "#8B7355"},
    "急流槽C20":          {"type": "line",  "color": "#000000", "linewidth": 2.5, "linestyle": "-.", "label": "急流槽",     "hatch": None, "color_professional": "#0000CD"},
    "浆砌石挡墙":         {"type": "line",  "color": "#000000", "linewidth": 3.0, "linestyle": "-",  "label": "浆砌石挡墙", "marker": "^", "color_professional": "#CD5C5C"},
    "车辆冲洗平台":       {"type": "point", "color": "#000000", "marker": "D", "size": 100, "label": "车辆冲洗平台", "color_professional": "#808080"},

    # ── 植物措施 (VEG) ──
    "撒播草籽(混播)":     {"type": "fill",  "color": "#BBBBBB", "alpha": 0.2,  "hatch": "...", "label": "撒播草籽", "color_professional": "#32CD32"},
    "综合绿化(乔灌草)":   {"type": "fill",  "color": "#888888", "alpha": 0.3,  "hatch": "///", "label": "综合绿化", "color_professional": "#228B22"},
    "屋顶绿化":           {"type": "fill",  "color": "#999999", "alpha": 0.25, "hatch": "\\\\\\", "label": "屋顶绿化", "color_professional": "#228B22"},
    "行道树种植":         {"type": "point", "color": "#000000", "marker": "^", "size": 60,  "label": "行道树", "color_professional": "#006400"},
    "建筑物周边绿化":     {"type": "fill",  "color": "#AAAAAA", "alpha": 0.25, "hatch": "|||", "label": "周边绿化", "color_professional": "#228B22"},
    "栽植乔木":           {"type": "point", "color": "#000000", "marker": "^", "size": 70,  "label": "乔木", "color_professional": "#006400"},
    "栽植灌木":           {"type": "point", "color": "#666666", "marker": "o", "size": 40,  "label": "灌木", "color_professional": "#2E8B57"},
    "铺设草皮":           {"type": "fill",  "color": "#CCCCCC", "alpha": 0.2,  "hatch": "---", "label": "草皮", "color_professional": "#7CFC00"},
    "藤蔓绿化":           {"type": "line",  "color": "#444444", "linewidth": 1.5, "linestyle": ":",  "label": "藤蔓绿化", "hatch": None, "color_professional": "#6B8E23"},
    "液力喷播":           {"type": "fill",  "color": "#BBBBBB", "alpha": 0.2,  "hatch": "+++", "label": "液力喷播", "color_professional": "#3CB371"},

    # ── 临时措施 (TMP) ──
    "密目安全网覆盖(6针)": {"type": "fill",  "color": "#AAAAAA", "alpha": 0.2, "hatch": "xxx", "label": "密目安全网", "color_professional": "#FF8C00"},
    "临时排水沟(土质)":    {"type": "line",  "color": "#444444", "linewidth": 1.5, "linestyle": "--", "label": "临时排水沟",  "hatch": None, "color_professional": "#FFA500"},
    "临时沉沙池(简易)":    {"type": "point", "color": "#444444", "marker": "s", "size": 60,  "label": "临时沉沙池", "color_professional": "#FF7F50"},
    "施工围挡(彩钢板)":    {"type": "line",  "color": "#333333", "linewidth": 2.5, "linestyle": "-",  "label": "施工围挡",  "hatch": None, "color_professional": "#FF6347"},
    "临时硬化(碎石)":      {"type": "fill",  "color": "#CCCCCC", "alpha": 0.25, "hatch": "...", "label": "临时硬化", "color_professional": "#DEB887"},
    "彩条布覆盖":          {"type": "fill",  "color": "#BBBBBB", "alpha": 0.2,  "hatch": "\\\\\\", "label": "彩条布覆盖", "color_professional": "#FFD700"},
    "临时拦挡(编织袋装土)": {"type": "line",  "color": "#333333", "linewidth": 2.0, "linestyle": "--", "label": "临时拦挡",  "hatch": None, "color_professional": "#FF6347"},
    "洒水降尘":            {"type": "point", "color": "#666666", "marker": "*", "size": 50,  "label": "洒水降尘", "color_professional": "#87CEEB"},
    "防尘网覆盖":          {"type": "fill",  "color": "#CCCCCC", "alpha": 0.2, "hatch": "|||", "label": "防尘网", "color_professional": "#BDB76B"},
    "临时苫盖(篷布)":      {"type": "fill",  "color": "#BBBBBB", "alpha": 0.2, "hatch": "---", "label": "临时苫盖", "color_professional": "#DAA520"},
    "车辆冲洗平台(临时)":  {"type": "point", "color": "#444444", "marker": "D", "size": 80,  "label": "冲洗平台(临时)", "color_professional": "#808080"},
    "临时拆除":            {"type": "fill",  "color": "#D0D0D0", "alpha": 0.15, "hatch": None, "label": "临时拆除", "color_professional": "#C0C0C0"},
}


def get_style(measure_name: str, professional: bool = True) -> dict:
    """获取措施绘图样式。

    Args:
        measure_name: 措施名称
        professional: True=使用专业彩色, False=灰度配色

    Returns:
        样式字典 (type, color, linewidth, ...)
    """
    style = None
    if measure_name in MEASURE_STYLES:
        style = MEASURE_STYLES[measure_name]
    else:
        # 按关键词模糊匹配
        for key, s in MEASURE_STYLES.items():
            if key in measure_name or measure_name in key:
                style = s
                break
    if style is None:
        # 默认样式: professional 时尝试从 MEASURE_COLORS_PROFESSIONAL 获取颜色
        fallback_color = "#999999"
        if professional:
            pc = get_measure_color(measure_name)
            if pc:
                fallback_color = pc
        return {"type": "fill", "color": fallback_color, "alpha": 0.35,
                "hatch": None, "label": measure_name[:8]}

    if professional and "color_professional" in style:
        style = {**style, "color": style["color_professional"]}
        # professional 模式下填充措施提升 alpha, 去掉 hatch
        if style.get("type") == "fill":
            style["alpha"] = max(style.get("alpha", 0.3), 0.35)
            style["hatch"] = None
    return style


# ── 典型工程断面参数 ────────────────────────────────────────────
SECTION_TEMPLATES: dict[str, dict] = {
    "排水沟C20(40×40)": {
        "shape": "rectangular_channel",
        "width": 0.4, "depth": 0.4,
        "wall_thickness": 0.08, "floor_thickness": 0.08,
        "material": "C20混凝土",
        "slope_ratio": "1:0",
        "description": "C20现浇混凝土矩形排水沟，内径40cm×40cm",
    },
    "排水沟C20(60×60)": {
        "shape": "rectangular_channel",
        "width": 0.6, "depth": 0.6,
        "wall_thickness": 0.10, "floor_thickness": 0.10,
        "material": "C20混凝土",
        "slope_ratio": "1:0",
        "description": "C20现浇混凝土矩形排水沟，内径60cm×60cm",
    },
    "截水沟C20(30×30)": {
        "shape": "rectangular_channel",
        "width": 0.3, "depth": 0.3,
        "wall_thickness": 0.08, "floor_thickness": 0.08,
        "material": "C20混凝土",
        "slope_ratio": "1:0",
        "description": "C20现浇混凝土截水沟，内径30cm×30cm",
    },
    "截水沟C20(40×40)": {
        "shape": "rectangular_channel",
        "width": 0.4, "depth": 0.4,
        "wall_thickness": 0.08, "floor_thickness": 0.08,
        "material": "C20混凝土",
        "slope_ratio": "1:0",
        "description": "C20现浇混凝土截水沟，内径40cm×40cm",
    },
    "M7.5浆砌石挡土墙": {
        "shape": "gravity_wall",
        "height": 2.0, "top_width": 0.5, "bottom_width": 1.2,
        "material": "M7.5浆砌石",
        "batter_front": "1:0.2", "batter_back": "1:0.1",
        "foundation_depth": 0.5,
        "description": "M7.5浆砌石重力式挡土墙，高2.0m",
    },
    "沉沙池(2×2×1.5m)": {
        "shape": "sedimentation_tank",
        "length": 2.0, "width": 2.0, "depth": 1.5,
        "wall_thickness": 0.24, "floor_thickness": 0.15,
        "material": "MU10砖+M5砂浆",
        "description": "砖砌沉沙池，内径2m×2m×1.5m",
    },
    "沉沙池(3×3×2m)": {
        "shape": "sedimentation_tank",
        "length": 3.0, "width": 3.0, "depth": 2.0,
        "wall_thickness": 0.24, "floor_thickness": 0.20,
        "material": "C20混凝土",
        "description": "混凝土沉沙池，内径3m×3m×2m",
    },
    "急流槽C20": {
        "shape": "chute",
        "width": 0.4, "depth": 0.3,
        "wall_thickness": 0.08, "floor_thickness": 0.10,
        "slope_gradient": "30%",
        "material": "C20混凝土",
        "description": "C20混凝土急流槽，宽40cm深30cm",
    },
    # ── 新增模板 ──
    "排水沟(40×40)": {
        "shape": "rectangular_channel",
        "width": 0.4, "depth": 0.4,
        "wall_thickness": 0.08, "floor_thickness": 0.08,
        "material": "混凝土",
        "slope_ratio": "1:0",
        "description": "矩形排水沟，内径40cm×40cm",
    },
    "排水沟(60×60)": {
        "shape": "rectangular_channel",
        "width": 0.6, "depth": 0.6,
        "wall_thickness": 0.10, "floor_thickness": 0.10,
        "material": "混凝土",
        "slope_ratio": "1:0",
        "description": "矩形排水沟，内径60cm×60cm",
    },
    "截水沟(30×30)": {
        "shape": "rectangular_channel",
        "width": 0.3, "depth": 0.3,
        "wall_thickness": 0.08, "floor_thickness": 0.08,
        "material": "混凝土",
        "slope_ratio": "1:0",
        "description": "矩形截水沟，内径30cm×30cm",
    },
    "截水沟(40×40)": {
        "shape": "rectangular_channel",
        "width": 0.4, "depth": 0.4,
        "wall_thickness": 0.08, "floor_thickness": 0.08,
        "material": "混凝土",
        "slope_ratio": "1:0",
        "description": "矩形截水沟，内径40cm×40cm",
    },
    "临时排水沟(土质)": {
        "shape": "trapezoidal_channel",
        "top_width": 0.5, "bottom_width": 0.3, "depth": 0.3,
        "material": "土质",
        "description": "土质临时排水沟，梯形断面，上口宽50cm底宽30cm深30cm",
    },
    "浆砌石挡墙": {
        "shape": "gravity_wall",
        "height": 2.0, "top_width": 0.5, "bottom_width": 1.2,
        "material": "M7.5浆砌石",
        "batter_front": "1:0.2", "batter_back": "1:0.1",
        "foundation_depth": 0.5,
        "description": "M7.5浆砌石重力式挡墙，高2.0m",
    },
    "透水砖铺装": {
        "shape": "pavement_section",
        "layers": [
            {"name": "透水砖", "thickness": 0.06, "hatch": "///"},
            {"name": "中砂找平层", "thickness": 0.03, "hatch": "..."},
            {"name": "碎石垫层", "thickness": 0.15, "hatch": "ooo"},
            {"name": "素土夯实", "thickness": 0.20, "hatch": "xxx"},
        ],
        "total_width": 1.0,
        "material": "透水砖+碎石",
        "description": "透水砖铺装结构，总厚约44cm",
    },
    "车辆冲洗平台": {
        "shape": "wash_platform",
        "length": 6.0, "width": 4.0, "depth": 0.3,
        "slab_thickness": 0.20,
        "material": "C20混凝土",
        "description": "车辆冲洗平台，6m×4m，C20混凝土基础",
    },
}


# ── 分区底色 (灰度, 通过灰度深浅区分) ──────────────────────────
ZONE_COLORS: dict[str, str] = {
    "建(构)筑物区":     "#E0E0E0",
    "道路广场区":       "#C8C8C8",
    "绿化工程区":       "#F0F0F0",
    "施工生产生活区":   "#B8B8B8",
    "临时堆土区":       "#D8D8D8",
}

# ── 分区底色 (彩色专业版, 参考报批稿标准) ─────────────────────────
ZONE_COLORS_PROFESSIONAL: dict[str, str] = {
    "建(构)筑物区":     "#D0D0D0",   # 建筑灰
    "道路广场区":       "#F0F0F0",   # 道路白
    "绿化工程区":       "#90EE90",   # 浅绿
    "施工生产生活区":   "#87CEEB",   # 天蓝
    "临时堆土区":       "#DEB887",   # 棕色
}

# ── 边界线颜色 ────────────────────────────────────────────────
BOUNDARY_COLORS: dict[str, str] = {
    "project_boundary":  "#FF0000",   # 项目红线
    "zone_boundary":     "#333333",   # 分区边界线
    "site_boundary":     "#FF69B4",   # 防治责任范围线(粉)
}

# ── 措施彩色覆盖 (专业模式下使用) ──────────────────────────────
MEASURE_COLORS_PROFESSIONAL: dict[str, str] = {
    # 工程措施
    "排水沟":     "#1E90FF",   # 蓝色系 (水利)
    "截水沟":     "#4169E1",
    "急流槽":     "#0000CD",
    "沉沙池":     "#4682B4",
    "碎石盲沟":   "#5F9EA0",
    "挡墙":       "#CD5C5C",   # 红色系 (结构)
    "挡土墙":     "#CD5C5C",
    "冲洗平台":   "#808080",
    # 植物措施
    "绿化":       "#228B22",   # 绿色系
    "草籽":       "#32CD32",
    "乔木":       "#006400",
    "灌木":       "#2E8B57",
    "草皮":       "#7CFC00",
    "藤蔓":       "#6B8E23",
    "液力喷播":   "#3CB371",
    # 临时措施
    "安全网":     "#FF8C00",   # 橙色系 (临时)
    "临时排水":   "#FFA500",
    "临时沉沙":   "#FF7F50",
    "围挡":       "#FF6347",
    "彩条布":     "#FFD700",
    "苫盖":       "#DAA520",
    "防尘网":     "#BDB76B",
}


def get_zone_color(zone_name: str, professional: bool = True) -> str:
    """获取分区底色，未知分区返回浅灰。

    Args:
        zone_name: 分区名称
        professional: True=使用彩色专业配色, False=灰度配色
    """
    colors = ZONE_COLORS_PROFESSIONAL if professional else ZONE_COLORS
    for key, color in colors.items():
        if key in zone_name or zone_name in key:
            return color
    return "#F5F5F5"


def get_measure_color(measure_name: str) -> str | None:
    """获取措施的专业彩色。返回 None 表示无覆盖 (使用原灰度)。"""
    for keyword, color in MEASURE_COLORS_PROFESSIONAL.items():
        if keyword in measure_name:
            return color
    return None


# ── 图例分类 (专业模式) ──────────────────────────────────────────
LEGEND_CATEGORIES: list[dict] = [
    {"title": "边界线", "items": [
        {"label": "项目用地红线", "type": "line", "color": "#FF0000", "linestyle": "--"},
        {"label": "防治责任范围线", "type": "line", "color": "#FF69B4", "linestyle": "-."},
    ]},
    # "分区填充" 由渲染器根据实际分区动态生成
    {"title": "分区填充", "items": []},
    {"title": "工程措施", "items": []},
    {"title": "植物措施", "items": []},
    {"title": "临时措施", "items": []},
]

# 措施名称关键词 → 分类
MEASURE_CATEGORY_MAP: dict[str, str] = {
    "排水沟": "工程措施", "截水沟": "工程措施", "沉沙池": "工程措施",
    "急流槽": "工程措施", "挡墙": "工程措施", "挡土墙": "工程措施",
    "碎石盲沟": "工程措施", "冲洗平台": "工程措施", "车辆冲洗": "工程措施",
    "HDPE": "工程措施", "防渗膜": "工程措施", "透水": "工程措施",
    "场地平整": "工程措施", "表土": "工程措施",
    "绿化": "植物措施", "草籽": "植物措施", "乔木": "植物措施",
    "灌木": "植物措施", "草皮": "植物措施", "藤蔓": "植物措施",
    "液力喷播": "植物措施", "屋顶绿化": "植物措施", "行道树": "植物措施",
    "临时排水": "临时措施", "临时沉沙": "临时措施", "围挡": "临时措施",
    "安全网": "临时措施", "密目": "临时措施", "彩条布": "临时措施",
    "苫盖": "临时措施", "防尘网": "临时措施", "临时拦挡": "临时措施",
    "洒水": "临时措施", "临时硬化": "临时措施", "临时拆除": "临时措施",
}


def get_measure_category(measure_name: str) -> str:
    """获取措施的分类 (工程/植物/临时)。"""
    for keyword, category in MEASURE_CATEGORY_MAP.items():
        if keyword in measure_name:
            return category
    return "工程措施"


# ── 分区工程填充图案 (hatch patterns) ────────────────────────────
ZONE_HATCHES: dict[str, str] = {
    "建(构)筑物区":     "///",
    "道路广场区":       "...",
    "绿化工程区":       "\\\\\\",
    "施工生产生活区":   "xxx",
    "临时堆土区":       "---",
}


def get_zone_hatch(zone_name: str) -> str | None:
    """获取分区的工程填充图案。返回 None 表示无匹配。"""
    for key, hatch in ZONE_HATCHES.items():
        if key in zone_name or zone_name in key:
            return hatch
    return None


# ── 断面模板模糊匹配函数 ────────────────────────────────────────
import re as _re


def match_section_template(measure_name: str) -> tuple[str, dict] | None:
    """多级模糊匹配断面模板。

    Level 1: 精确匹配
    Level 2: 模板键 ⊂ 措施名 或 措施名 ⊂ 模板键
    Level 3: 去除 C20/C25 等材料标号后再比较
    Level 4: 提取尺寸 (WxH regex) 匹配模板参数
    Level 5: 参数化生成 — 从措施名提取"排水沟/截水沟"类型 + 尺寸，动态创建模板

    Returns:
        (template_key, template_dict) 或 None
    """
    # Level 1: 精确匹配
    if measure_name in SECTION_TEMPLATES:
        return (measure_name, SECTION_TEMPLATES[measure_name])

    # Level 2: 包含匹配
    for tmpl_key, tmpl in SECTION_TEMPLATES.items():
        if tmpl_key in measure_name or measure_name in tmpl_key:
            return (tmpl_key, tmpl)

    # Level 3: 去除材料标号后再比较
    stripped = _re.sub(r'[CM]\d+\.?\d*', '', measure_name).strip()
    if stripped != measure_name:
        for tmpl_key, tmpl in SECTION_TEMPLATES.items():
            tmpl_stripped = _re.sub(r'[CM]\d+\.?\d*', '', tmpl_key).strip()
            if tmpl_stripped in stripped or stripped in tmpl_stripped:
                return (tmpl_key, tmpl)

    # Level 4: 提取尺寸 (WxH) 匹配模板参数
    size_match = _re.search(r'(\d+)\s*[×xX*]\s*(\d+)', measure_name)
    if size_match:
        w_cm = int(size_match.group(1))
        h_cm = int(size_match.group(2))
        w_m = w_cm / 100.0
        h_m = h_cm / 100.0
        for tmpl_key, tmpl in SECTION_TEMPLATES.items():
            tw = tmpl.get("width", tmpl.get("top_width", 0))
            td = tmpl.get("depth", tmpl.get("height", 0))
            if abs(tw - w_m) < 0.01 and abs(td - h_m) < 0.01:
                return (tmpl_key, tmpl)

    # Level 5: 参数化生成
    for type_kw, shape in [("排水沟", "rectangular_channel"),
                           ("截水沟", "rectangular_channel"),
                           ("急流槽", "chute")]:
        if type_kw in measure_name:
            if size_match:
                w_m = int(size_match.group(1)) / 100.0
                h_m = int(size_match.group(2)) / 100.0
                gen_key = f"{type_kw}({size_match.group(1)}×{size_match.group(2)})"
                gen_tmpl = {
                    "shape": shape,
                    "width": w_m, "depth": h_m,
                    "wall_thickness": 0.08, "floor_thickness": 0.08,
                    "material": "混凝土",
                    "description": f"{type_kw}，内径{w_m*100:.0f}cm×{h_m*100:.0f}cm",
                }
                return (gen_key, gen_tmpl)
            # 无尺寸时返回同类型默认模板
            for tmpl_key, tmpl in SECTION_TEMPLATES.items():
                if type_kw in tmpl_key:
                    return (tmpl_key, tmpl)

    # 浆砌石挡墙/挡土墙
    if "挡墙" in measure_name or "挡土墙" in measure_name:
        for tmpl_key, tmpl in SECTION_TEMPLATES.items():
            if "挡" in tmpl_key and tmpl.get("shape") == "gravity_wall":
                return (tmpl_key, tmpl)

    # 透水砖/铺装
    if "透水" in measure_name or "铺装" in measure_name:
        for tmpl_key, tmpl in SECTION_TEMPLATES.items():
            if tmpl.get("shape") == "pavement_section":
                return (tmpl_key, tmpl)

    # 冲洗平台
    if "冲洗" in measure_name:
        for tmpl_key, tmpl in SECTION_TEMPLATES.items():
            if tmpl.get("shape") == "wash_platform":
                return (tmpl_key, tmpl)

    # 临时排水沟
    if "临时排水" in measure_name:
        for tmpl_key, tmpl in SECTION_TEMPLATES.items():
            if tmpl.get("shape") == "trapezoidal_channel":
                return (tmpl_key, tmpl)

    return None


# ── Z-Order 渲染层次 ────────────────────────────────────────────
ZORDER = {
    "cad_background": 1,
    "zone_fill": 2,
    "zone_boundary": 3,
    "measure_area": 4,
    "measure_line": 5,
    "measure_point": 6,
    "measure_overlay": 7,
    "flow_arrows": 8,
    "labels": 9,
    "decorations": 10,
    "legend": 11,
    "title_block": 12,
}


# ── 地图默认参数 ────────────────────────────────────────────────
MAP_DEFAULTS = {
    "dpi": 300,
    "figsize_single": (12, 10),
    "figsize_detail": (10, 8),
    "figsize_section": (10, 5),
    "title_fontsize": 14,
    "label_fontsize": 9,
    "legend_fontsize": 8,
    "north_arrow": True,
    "scale_bar": True,
    "border_color": "#000000",
    "border_linewidth": 1.5,
    "grid_alpha": 0.15,
}
