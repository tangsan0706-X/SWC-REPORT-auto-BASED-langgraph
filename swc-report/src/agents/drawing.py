"""Drawing Agent (绘图智能体) — LLM 语义规划 + 确定性渲染引擎。

工作流:
  1. 为每种图类型创建独立 Agent 实例
  2. Agent 调用 get_project_data → get_style_reference → submit_drawing_plan → verify_image
  3. LLM 只输出 DrawingPlan JSON，渲染引擎负责 PNG + DXF
  4. 产出 < 2 张图则整体回退到 MeasureMapRenderer
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _is_valid_image(path: Path) -> bool:
    """检查 PNG 图片是否有实际内容（非全白/全黑）。"""
    try:
        with open(path, "rb") as f:
            header = f.read(8)
            if header[:4] != b"\x89PNG":
                return False
            # 文件 > 5KB 基本都有内容
            if path.stat().st_size > 5120:
                return True
            # 小文件进一步检查: 用 matplotlib 读取检查像素方差
            try:
                import matplotlib.pyplot as plt
                img = plt.imread(str(path))
                plt.close("all")
                if img.std() < 0.01:
                    return False
            except Exception:
                pass
        return True
    except Exception:
        return False

# ── System Prompt ────────────────────────────────────────────

DRAWING_SYSTEM_PROMPT = """你是专业的水土保持措施图绘制工程师。
你的任务是输出 DrawingPlan JSON 描述"画什么、放哪里"，渲染引擎会自动生成 PNG + DXF。

## 工作流程
1. 调用 get_project_data 获取项目分区、措施、空间布局
2. 调用 get_style_reference 获取 SL73_6-2015 制图规范和内置样式
3. 编写 DrawingPlan JSON (不要写 Python 代码!)
4. 调用 submit_drawing_plan 提交 JSON，渲染引擎自动生成 PNG + DXF
5. 调用 verify_image 验证图片质量
6. 不合格则修改 JSON 重试

## DrawingPlan JSON 格式
```json
{
  "map_type": "measure_layout",
  "title": "XX项目 水土保持措施总体布置图",
  "zones": [
    {"name": "分区名称", "emphasis": "normal"}
  ],
  "measures": [
    {
      "name": "排水沟C20(40×40)",
      "zone": "建(构)筑物区",
      "position": "south",
      "direction": "east-west",
      "coverage": "edge"
    }
  ],
  "sections": [
    {"structure": "排水沟C20(40×40)", "annotation_notes": ["排水坡度 i=0.3%"]}
  ],
  "layout_hints": {
    "drainage_direction": "south",
    "main_road_orientation": "north-south"
  }
}
```

## 字段词汇表 (只能用这些值)
- **position** (10个): north / south / east / west / center / northeast / northwest / southeast / southwest / perimeter
- **direction** (5个): north-south / east-west / clockwise / along-road / along-boundary
- **coverage** (3个): full / partial / edge
- **emphasis** (2个): normal / highlight

## 各图类型必填字段
| map_type | zones | measures | sections |
|----------|-------|----------|----------|
| zone_boundary | 必填 | 不需要 | 不需要 |
| measure_layout | 必填 | 必填 | 不需要 |
| zone_detail | 必填(1个) | 必填 | 不需要 |
| typical_section | 不需要 | 不需要 | 必填 |

## 重要规则
- 只输出 JSON，不要写 Python 代码
- **绝对不要输出任何坐标数字**。坐标计算由几何引擎自动完成。
- zone 和 measure 的 name 必须使用 get_project_data 返回的真实名称
- 每个措施必须指定所属 zone (使用真实分区名)
- position 描述措施在分区内的**语义相对位置** (排水沟通常在 south, 绿化在 center 等)
- direction 描述措施的朝向/走向 (不是坐标角度)
- 你的职责是**选择合适的放置策略**，渲染引擎负责将策略转换为精确坐标
"""

# ── 每种图的 user prompt 模板 ────────────────────────────────

_PROMPTS = {
    "zone_boundary": """请为「水土保持防治分区图」(zone_boundary_map.png) 生成 DrawingPlan JSON。

要求:
- map_type: "zone_boundary"
- zones: 包含所有分区，重点分区设 emphasis="highlight"
- title: "{project_name} 水土保持防治分区图"

请先调用 get_project_data 获取所有分区名称和面积。""",

    "measure_layout": """请为「水土保持措施总体布置图」(measure_layout_map.png) 生成 DrawingPlan JSON。

要求:
- map_type: "measure_layout"
- zones: 包含所有分区
- measures: 包含所有措施，每个指定 zone/position/direction/coverage
  - 排水沟: 通常 position="south" 或 "perimeter", direction="east-west"
  - 截水沟: 通常 position="north", direction="east-west"
  - 绿化: 通常 position="center", coverage="full"
  - 沉沙池: 通常在排水沟下游 position="southeast"
- title: "{project_name} 水土保持措施总体布置图"

请先调用 get_project_data 获取所有分区和措施。""",

    "zone_detail": """请为分区「{zone_name}」的措施详图 (zone_detail_{zone_key}.png) 生成 DrawingPlan JSON。

要求:
- map_type: "zone_detail"
- zones: 只包含 "{zone_name}" (emphasis="highlight")
- measures: 该分区内的所有措施，精确指定 position/direction/coverage
- title: "{project_name} {zone_name}措施详图"

请先调用 get_project_data(zone_name="{zone_name}") 获取该分区数据。""",

    "typical_section": """请为「{measure_name}」的典型工程断面图 (typical_section_{section_key}.png) 生成 DrawingPlan JSON。

要求:
- map_type: "typical_section"
- sections: [{{"structure": "{measure_name}", "annotation_notes": [相关工程参数注释]}}]
- title: "{measure_name} 典型断面图"

请先调用 get_style_reference(map_type="typical_section", measure_names=["{measure_name}"]) 获取断面参数。""",
}


def run_drawing_agent(state, llm=None, output_dir: Path | None = None) -> dict[str, Path]:
    """生成措施图 — LLM 模式用 Drawing Agent，失败回退到 MeasureMapRenderer。

    Returns:
        {tag_name: Path} 映射，如 {"zone_boundary_map": Path("...png")}
    """
    from src.agents.base import ToolCallingAgent, LLMClient
    from src.context import AgentContext
    from src.tools.drawing_tools import DRAWING_TOOLS
    from src.atlas_rag import AtlasRAG
    from src.settings import OUTPUT_DIR

    out_dir = output_dir or OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # 初始化工具上下文
    atlas_rag = AtlasRAG()

    if llm is None:
        llm = LLMClient()

    meta = state.Static.meta
    project_name = meta.get("project_name", "项目")
    zones = state.ETL.zones
    measures = state.Measures

    results: dict[str, Path] = {}

    # 收集所有绘图任务 (map_type, prompt, filename)
    tasks: list[tuple[str, str, str]] = []

    # 1. 分区图
    tasks.append((
        "zone_boundary",
        _PROMPTS["zone_boundary"].format(project_name=project_name),
        "zone_boundary_map.png",
    ))

    # 2. 总布置图
    tasks.append((
        "measure_layout",
        _PROMPTS["measure_layout"].format(project_name=project_name),
        "measure_layout_map.png",
    ))

    # 3. 各分区详图
    for zone in zones:
        zone_name = zone.get("name", "")
        zone_key = zone_name.replace("(", "").replace(")", "").replace("（", "").replace("）", "")
        tasks.append((
            "zone_detail",
            _PROMPTS["zone_detail"].format(
                zone_name=zone_name, zone_key=zone_key, project_name=project_name,
            ),
            f"zone_detail_{zone_key}.png",
        ))

    # 4. 典型断面图 (选取有断面模板的措施)
    from src.measure_symbols import SECTION_TEMPLATES
    drawn_sections = set()
    for m in measures:
        mname = m.get("措施名称", m.get("name", ""))
        if mname in SECTION_TEMPLATES and mname not in drawn_sections:
            section_key = mname.replace("(", "").replace(")", "").replace("（", "").replace("）", "")
            section_key = section_key.replace(" ", "_")
            tasks.append((
                "typical_section",
                _PROMPTS["typical_section"].format(
                    measure_name=mname, section_key=section_key, project_name=project_name,
                ),
                f"typical_section_{section_key}.png",
            ))
            drawn_sections.add(mname)

    # 并行执行所有绘图任务
    from src.settings import DRAWING_PARALLEL_WORKERS
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _draw_single_task(map_type, prompt, filename):
        """线程安全的单图生成任务。"""
        with AgentContext(state=state, atlas_rag=atlas_rag, output_dir=out_dir):
            tag = filename.replace(".png", "")
            try:
                output_path = out_dir / filename
                if output_path.exists():
                    output_path.unlink()

                agent = ToolCallingAgent(
                    name=f"Drawing-{map_type}",
                    system_prompt=DRAWING_SYSTEM_PROMPT,
                    tools=DRAWING_TOOLS,
                    llm=llm,
                    max_turns=8,
                )
                agent.run(prompt)

                if output_path.exists() and output_path.stat().st_size > 1024:
                    # 额外检查: 图片不是全白/全黑空图
                    if _is_valid_image(output_path):
                        logger.info(f"  [{map_type}] 成功: {filename} ({output_path.stat().st_size // 1024}KB)")
                        return tag, output_path, None
                    else:
                        logger.warning(f"  [{map_type}] 图片内容无效(空白): {filename}")
                        return tag, None, "图片为空白"
                else:
                    logger.warning(f"  [{map_type}] 输出文件无效: {filename}")
                    return tag, None, "输出文件无效"
            except Exception as e:
                logger.warning(f"  [{map_type}] Agent 失败: {e}")
                return tag, None, str(e)

    with ThreadPoolExecutor(max_workers=DRAWING_PARALLEL_WORKERS) as executor:
        futures = {
            executor.submit(_draw_single_task, mt, pr, fn): fn
            for mt, pr, fn in tasks
        }
        for future in as_completed(futures):
            tag, path, err = future.result()
            if path is not None:
                results[tag] = path

    logger.info(f"Drawing Agent 完成: {len(results)} 张图")

    # 产出 < 2 张 → 回退
    if len(results) < 2:
        logger.warning(f"Drawing Agent 仅生成 {len(results)} 张图，回退到 MeasureMapRenderer")
        raise RuntimeError(f"Drawing Agent 产出不足 ({len(results)} 张)，触发回退")

    return results
