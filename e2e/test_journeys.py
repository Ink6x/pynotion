"""主要ユーザーフローの E2E。

contenteditable の自作エディタはユニットテストで担保しづらいため、
実ブラウザで「作成 → 入力 → 変換 → 並べ替え → 検索 → ゴミ箱復元」を通す。
"""
import pytest
from playwright.sync_api import expect

from e2e.conftest import create_page_with_first_block

pytestmark = pytest.mark.e2e


def test_markdown_autoformat_to_heading(app):
    """段落で `# ` を入力すると見出し1へ自動変換される。"""
    block = create_page_with_first_block(app)
    block.click()
    # "# " で heading_1 に変換され、続けて本文を入力
    app.keyboard.type("# ")
    app.keyboard.type("E2E 見出し")

    heading = app.locator("#editor .block.type-heading_1")
    expect(heading).to_have_count(1)
    expect(heading.locator(".block-content")).to_have_text("E2E 見出し")


def test_slash_command_changes_block_type(app):
    """`/` でスラッシュメニューを開き、見出し2を選んでブロック型を変える。"""
    block = create_page_with_first_block(app)
    block.click()
    app.keyboard.type("/")

    menu = app.locator(".slash-menu")
    expect(menu).to_be_visible()
    menu.locator(".menu-item", has_text="見出し2").click()

    expect(app.locator("#editor .block.type-heading_2")).to_have_count(1)


def test_block_reorder_via_drag_and_drop(app):
    """ハンドルのドラッグで 2 つのブロックの順序が入れ替わる。"""
    block = create_page_with_first_block(app)
    block.click()
    app.keyboard.type("最初")
    app.keyboard.press("Enter")  # 2 つ目のブロックへ分割 (非同期)

    rows = app.locator("#editor .block")
    # 分割は API 往復を伴う非同期処理。2 つ目のブロックが生成・フォーカスされて
    # から入力する (生成前に打つと 1 つ目へ混入する)。
    expect(rows).to_have_count(2)
    app.keyboard.type("次")

    expect(rows.nth(0).locator(".block-content")).to_have_text("最初")
    expect(rows.nth(1).locator(".block-content")).to_have_text("次")

    # HTML5 DnD を合成イベントで発火 (1 つ目を 2 つ目の下へ)
    app.evaluate(
        """() => {
          const blocks = document.querySelectorAll('#editor .block');
          const first = blocks[0], second = blocks[1];
          const handle = first.querySelector('.block-handle');
          const dt = new DataTransfer();
          // clientY は読み取り専用なのでコンストラクタの init で渡す。
          const fire = (el, type, clientY) =>
            el.dispatchEvent(new DragEvent(type, {
              bubbles: true, cancelable: true, dataTransfer: dt, clientY,
            }));
          const rect = second.getBoundingClientRect();
          const belowMid = rect.top + rect.height * 0.75;  // 2 つ目の下半分 = 直後へ
          fire(handle, 'dragstart', 0);
          fire(second, 'dragover', belowMid);
          fire(second, 'drop', belowMid);
          fire(handle, 'dragend', 0);
        }"""
    )

    # 並べ替え後は「次」「最初」の順
    expect(app.locator("#editor .block").nth(0).locator(".block-content")).to_have_text("次")
    expect(app.locator("#editor .block").nth(1).locator(".block-content")).to_have_text("最初")


def test_search_then_trash_and_restore(app):
    """検索でページを開き、ゴミ箱へ移動して復元する。"""
    create_page_with_first_block(app)

    # タイトルを入力 (自動保存はデバウンス。サイドバーへ反映されるまで待つ)
    title = app.locator("#page-title")
    title.click()
    app.keyboard.type("E2E 議事録")
    expect(app.locator("#page-tree .tree-title", has_text="E2E 議事録")).to_be_visible()

    # 検索 (Ctrl+K) で開く
    app.keyboard.press("Control+k")
    search_input = app.locator(".modal .search-input")
    expect(search_input).to_be_visible()
    search_input.fill("議事録")
    result = app.locator(".search-results .menu-item", has_text="E2E 議事録")
    expect(result).to_be_visible()
    result.click()
    expect(app.locator("#page-title")).to_have_text("E2E 議事録")

    # サイドバーの 🗑 でゴミ箱へ移動
    row = app.locator("#page-tree .tree-row", has_text="E2E 議事録")
    row.hover()
    row.locator("button[title='ゴミ箱へ移動']").click()
    expect(app.locator("#page-tree .tree-title", has_text="E2E 議事録")).to_have_count(0)

    # ゴミ箱を開いて復元
    app.click("#trash-button")
    trash_row = app.locator(".trash-row", has_text="E2E 議事録")
    expect(trash_row).to_be_visible()
    trash_row.locator("button", has_text="復元").click()

    # 復元後はサイドバーに再表示される
    expect(app.locator("#page-tree .tree-title", has_text="E2E 議事録")).to_be_visible()
