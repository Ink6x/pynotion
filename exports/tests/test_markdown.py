"""ブロックツリー → Markdown 変換の単体テスト(Django 非依存)。"""
import pytest

from exports.markdown import tree_to_markdown

pytestmark = pytest.mark.unit


def _node(type, text="", children=None, checked=False):
    return {"type": type, "text": text, "checked": checked, "children": children or []}


def test_headings():
    tree = [
        _node("heading_1", "見出し1"),
        _node("heading_2", "見出し2"),
        _node("heading_3", "見出し3"),
    ]
    assert tree_to_markdown(tree) == "# 見出し1\n## 見出し2\n### 見出し3\n"


def test_paragraph_and_quote_and_divider():
    tree = [_node("paragraph", "段落"), _node("quote", "引用"), _node("divider")]
    assert tree_to_markdown(tree) == "段落\n> 引用\n---\n"


def test_todo_checked_and_unchecked():
    tree = [
        _node("to_do", "やること", checked=False),
        _node("to_do", "おわった", checked=True),
    ]
    assert tree_to_markdown(tree) == "- [ ] やること\n- [x] おわった\n"


def test_bulleted_and_numbered_lists():
    tree = [
        _node("bulleted_list_item", "りんご"),
        _node("numbered_list_item", "一番目"),
        _node("numbered_list_item", "二番目"),
        _node("numbered_list_item", "三番目"),
    ]
    md = tree_to_markdown(tree)
    assert md == "- りんご\n1. 一番目\n2. 二番目\n3. 三番目\n"


def test_numbered_list_resets_after_interruption():
    tree = [
        _node("numbered_list_item", "A"),
        _node("paragraph", "区切り"),
        _node("numbered_list_item", "B"),
    ]
    md = tree_to_markdown(tree)
    assert "1. A" in md
    assert "区切り" in md
    assert "1. B" in md  # 中断後は連番がリセットされる


def test_code_block_fenced():
    tree = [_node("code", "print('hi')\nx = 1")]
    assert tree_to_markdown(tree) == "```\nprint('hi')\nx = 1\n```\n"


def test_nested_children_indented():
    tree = [
        _node("bulleted_list_item", "親", children=[_node("bulleted_list_item", "子")]),
    ]
    assert tree_to_markdown(tree) == "- 親\n  - 子\n"


def test_title_prepended_as_h1():
    tree = [_node("paragraph", "本文")]
    assert tree_to_markdown(tree, title="ページ名") == "# ページ名\n\n本文\n"


def test_toggle_renders_as_bullet_with_children():
    tree = [_node("toggle", "トグル", children=[_node("paragraph", "中身")])]
    assert tree_to_markdown(tree) == "- トグル\n  中身\n"


def test_empty_tree():
    assert tree_to_markdown([]) == "\n"
    assert tree_to_markdown([], title="のみ") == "# のみ\n"
