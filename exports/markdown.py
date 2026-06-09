"""ブロックツリー → Markdown 変換(純ドメイン層)。

``serialize_block_tree`` 形式のネスト JSON(各ノード = type/text/checked/collapsed +
children)を Markdown 文字列へ落とす。Django 非依存にして単体テストで固定する。

ネストは 2 スペースインデントで表現し、番号付きリストは兄弟内で連番を振る。
"""
from __future__ import annotations

_INDENT = "  "


def _heading(level: int, text: str) -> str:
    return f"{'#' * level} {text}"


def _render_node(node: dict, depth: int, sibling_number: int) -> list[str]:
    """1 ノードを Markdown 行(複数行になりうる)へ変換する。"""
    btype = node.get("type", "paragraph")
    text = node.get("text", "") or ""
    pad = _INDENT * depth

    if btype == "heading_1":
        line = _heading(1, text)
    elif btype == "heading_2":
        line = _heading(2, text)
    elif btype == "heading_3":
        line = _heading(3, text)
    elif btype == "to_do":
        mark = "x" if node.get("checked") else " "
        line = f"- [{mark}] {text}"
    elif btype == "bulleted_list_item":
        line = f"- {text}"
    elif btype == "numbered_list_item":
        line = f"{sibling_number}. {text}"
    elif btype == "quote":
        line = f"> {text}"
    elif btype == "toggle":
        line = f"- {text}"
    elif btype == "divider":
        line = "---"
    elif btype == "code":
        # コードブロックは囲み。インデント下でもそのまま出す。
        body = text.split("\n") if text else [""]
        lines = [f"{pad}```", *(f"{pad}{ln}" for ln in body), f"{pad}```"]
        return lines
    else:  # paragraph / 未知
        line = text

    return [f"{pad}{line}"]


def _walk(nodes: list[dict], depth: int) -> list[str]:
    lines: list[str] = []
    number = 0  # 番号付きリストの兄弟連番
    for node in nodes or []:
        if node.get("type") == "numbered_list_item":
            number += 1
        else:
            number = 0
        lines.extend(_render_node(node, depth, number))
        children = node.get("children") or []
        if children:
            lines.extend(_walk(children, depth + 1))
    return lines


def tree_to_markdown(tree: list[dict], *, title: str = "") -> str:
    """ブロックツリーを Markdown 文書へ変換する。

    ``title`` があれば先頭に H1 として付ける。
    """
    lines: list[str] = []
    if title:
        lines.append(_heading(1, title))
        lines.append("")
    lines.extend(_walk(tree, 0))
    # 末尾改行を 1 つにそろえる
    return "\n".join(lines).rstrip("\n") + "\n"
