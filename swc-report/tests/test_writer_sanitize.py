"""撰稿智能体输出清洗与解析测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.writer import _sanitize_text, _parse_chapter_output


def test_sanitize_removes_meta_text():
    """测试: 移除 LLM 元文本。"""
    dirty = """请允许我直接基于提供的信息编写项目概况章节，以确保内容的连贯性和准确性。

本项目位于江苏省南通市如东县，为新建住宅小区项目。

以上内容基于一般的技术规范和标准编写，请根据实际项目情况进行调整和完善。"""

    clean = _sanitize_text(dirty)
    assert "请允许我" not in clean
    assert "以上内容基于" not in clean
    assert "本项目位于江苏省南通市如东县" in clean
    print(f"  清洗后: {clean[:80]}...")


def test_sanitize_removes_markdown_headers():
    """测试: 移除 Markdown 标题。"""
    dirty = """### chapter1_brief

本项目概况简述内容。

### chapter1_legal_basis

编制依据内容。"""

    clean = _sanitize_text(dirty)
    assert "### chapter1_brief" not in clean
    assert "### chapter1_legal_basis" not in clean
    assert "本项目概况简述内容" in clean
    assert "编制依据内容" in clean


def test_sanitize_removes_tag_lines():
    """测试: 移除残留 tag 名称行。"""
    dirty = """chapter1_brief

本项目概况简述内容。

chapter1_legal_basis

编制依据内容。"""

    clean = _sanitize_text(dirty)
    assert "\nchapter1_brief\n" not in clean
    assert "\nchapter1_legal_basis\n" not in clean


def test_parse_with_markers():
    """测试: 标准 ===TAG=== 标记解析。"""
    text = """===tag_a===
内容A段落。

===tag_b===
内容B段落。

===tag_c===
内容C段落。"""

    result = _parse_chapter_output(text, ["tag_a", "tag_b", "tag_c"])
    assert "内容A段落" in result["tag_a"]
    assert "内容B段落" in result["tag_b"]
    assert "内容C段落" in result["tag_c"]


def test_parse_with_meta_text_before_markers():
    """测试: 第一个标记前有元文本时正确解析。"""
    text = """请允许我直接基于提供的信息编写项目概况章节。

===tag_a===
内容A段落。

===tag_b===
内容B段落。"""

    result = _parse_chapter_output(text, ["tag_a", "tag_b"])
    assert "请允许我" not in result["tag_a"]
    assert "内容A段落" in result["tag_a"]
    assert "内容B段落" in result["tag_b"]


def test_parse_with_md_headers():
    """测试: LLM 使用 Markdown 标题代替 ===TAG=== 时能正确解析。"""
    text = """### chapter1_brief

本项目为住宅小区项目，位于南通市。

### chapter1_legal_basis

中华人民共和国水土保持法。

### chapter1_conclusion

项目可行。"""

    tags = ["chapter1_brief", "chapter1_legal_basis", "chapter1_conclusion"]
    result = _parse_chapter_output(text, tags)
    assert "住宅小区" in result["chapter1_brief"]
    assert "水土保持法" in result["chapter1_legal_basis"]
    assert "可行" in result["chapter1_conclusion"]
    # 确保 markdown headers 被清洗
    for v in result.values():
        assert "###" not in v


def test_parse_preserves_numbers():
    """测试: 清洗不会破坏正文中的数字。"""
    text = """===chapter7_benefit===
本项目水土保持总投资283.76万元，其中方案新增投资198.50万元。
六项指标均满足一级防治标准要求，水土流失治理度达到97.2%。"""

    result = _parse_chapter_output(text, ["chapter7_benefit"])
    assert "283.76" in result["chapter7_benefit"]
    assert "198.50" in result["chapter7_benefit"]
    assert "97.2%" in result["chapter7_benefit"]


def test_sanitize_removes_tool_meta():
    """测试: 移除工具调用相关的元文本（整行和内联）。"""
    dirty = """南通市地处江苏省东部沿海地区，属亚热带季风气候类型。

以上信息均通过calc_lookup工具获取并确认无误。"""

    clean = _sanitize_text(dirty)
    assert "以上信息均通过" not in clean
    assert "南通市地处江苏省" in clean

    # 内联工具引用
    dirty2 = "项目投资估算为3679万元（具体数值由calc_lookup获取），其中水保投资2800万元。"
    clean2 = _sanitize_text(dirty2)
    assert "calc_lookup" not in clean2
    assert "3679万元" in clean2
    assert "2800万元" in clean2


def test_sanitize_removes_markdown_bold():
    """测试: 移除 Markdown 粗体/斜体标记但保留文字。"""
    dirty = """1. **土壤侵蚀量监测**：通过设置不同类型的测点。

2. *水土保持措施*效果评估。"""

    clean = _sanitize_text(dirty)
    assert "**" not in clean
    assert "*水土保持措施*" not in clean
    assert "土壤侵蚀量监测" in clean
    assert "水土保持措施" in clean


def test_assembler_clean_chapter():
    """测试: assembler 的二次清洗。"""
    from src.assembler import _clean_chapter_text

    dirty = """===chapter1_brief===
### chapter1_brief
请允许我编写本章。

本项目位于江苏省。

tr for row in land_use_table
tr endfor

以上信息均通过calc_lookup工具获取并确认无误。

**重要内容**需要保留。

chapter1_brief"""

    clean = _clean_chapter_text(dirty)
    assert "===chapter1_brief===" not in clean
    assert "### chapter1_brief" not in clean
    assert "请允许我" not in clean
    assert "tr for row in" not in clean
    assert "\nchapter1_brief\n" not in clean
    assert "以上信息均通过" not in clean
    assert "**" not in clean
    assert "重要内容" in clean
    assert "本项目位于江苏省" in clean


if __name__ == "__main__":
    test_sanitize_removes_meta_text()
    print("PASSED: test_sanitize_removes_meta_text")

    test_sanitize_removes_markdown_headers()
    print("PASSED: test_sanitize_removes_markdown_headers")

    test_sanitize_removes_tag_lines()
    print("PASSED: test_sanitize_removes_tag_lines")

    test_parse_with_markers()
    print("PASSED: test_parse_with_markers")

    test_parse_with_meta_text_before_markers()
    print("PASSED: test_parse_with_meta_text_before_markers")

    test_parse_with_md_headers()
    print("PASSED: test_parse_with_md_headers")

    test_parse_preserves_numbers()
    print("PASSED: test_parse_preserves_numbers")

    test_sanitize_removes_tool_meta()
    print("PASSED: test_sanitize_removes_tool_meta")

    test_sanitize_removes_markdown_bold()
    print("PASSED: test_sanitize_removes_markdown_bold")

    test_assembler_clean_chapter()
    print("PASSED: test_assembler_clean_chapter")

    print("\nAll tests passed!")
