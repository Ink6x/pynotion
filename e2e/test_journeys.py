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


def test_tab_indents_block_under_previous(app):
    """2 つ目のブロックで Tab を押すと 1 つ目の子としてインデントされる。"""
    block = create_page_with_first_block(app)
    block.click()
    app.keyboard.type("親")
    app.keyboard.press("Enter")

    rows = app.locator("#editor .block")
    expect(rows).to_have_count(2)
    app.keyboard.type("子")
    # 2 つ目で Tab → インデント (API 往復 + 再描画を伴う)
    app.keyboard.press("Tab")

    # 子ブロックの depth が 1 になり、左インデントが付く
    child = app.locator("#editor .block", has_text="子")
    expect(child).to_have_css("margin-left", "24px")


def test_toggle_collapse_hides_children(app):
    """toggle を折りたたむと配下の子ブロックが非表示になる。"""
    block = create_page_with_first_block(app)
    block.click()
    # 1 つ目を toggle 化
    app.keyboard.type("/")
    menu = app.locator(".slash-menu")
    expect(menu).to_be_visible()
    menu.locator(".menu-item", has_text="トグル").click()
    expect(app.locator("#editor .block.type-toggle")).to_have_count(1)
    app.keyboard.type("トグル親")

    # 子を作ってインデント
    app.keyboard.press("Enter")
    expect(app.locator("#editor .block")).to_have_count(2)
    app.keyboard.type("中身")
    app.keyboard.press("Tab")
    expect(app.locator("#editor .block", has_text="中身")).to_have_css("margin-left", "24px")

    # キャレットを折りたたむ
    app.locator(".block-toggle-caret").click()
    expect(app.locator("#editor .block", has_text="中身")).to_have_count(0)
    # 再度展開すると現れる
    app.locator(".block-toggle-caret").click()
    expect(app.locator("#editor .block", has_text="中身")).to_have_count(1)


def test_version_history_restore(app):
    """編集で履歴が残り、履歴モーダルから編集前の状態へ復元できる。

    スナップショットは「編集セッションの境界」= 最初の編集の直前に撮られるため、
    高速な 1 セッションでは編集前(空)の状態が 1 件残る。復元するとその状態へ戻る。
    """
    block = create_page_with_first_block(app)
    block.click()
    app.keyboard.type("あとで消える内容")
    # デバウンス保存とスナップショット作成を待つ
    app.wait_for_timeout(600)
    expect(app.locator("#editor .block-content").first).to_have_text("あとで消える内容")

    # confirm を自動承認しておく
    app.on("dialog", lambda d: d.accept())

    # 履歴を開く (最初の編集の直前=空の状態が 1 件残っている)
    app.locator("#history-button").click()
    modal = app.locator(".modal")
    expect(modal).to_be_visible()
    expect(app.locator(".history-row").first).to_be_visible()

    # 復元 → 編集前(空)の状態に戻る
    app.locator(".history-row .trash-action").first.click()
    expect(app.locator("#editor .block-content").first).to_have_text("")


def test_database_table_add_column_row_and_edit(app):
    """ページをデータベース化し、列・行を追加してセルを編集、リロードで永続化を確認。"""
    create_page_with_first_block(app)

    # データベース化 → テーブルが描画される
    app.click("#database-button")
    app.wait_for_selector(".db-table")

    # text 列「タイトル」を追加
    app.click(".db-add-col")
    pop = app.locator(".db-add-col-pop")
    expect(pop).to_be_visible()
    pop.locator(".db-col-name-input").fill("タイトル")
    pop.locator(".db-col-type-input").select_option("text")
    pop.locator(".db-col-create").click()
    expect(app.locator(".db-col-name", has_text="タイトル")).to_have_count(1)

    # 行を追加
    app.click(".db-add-row")
    expect(app.locator(".db-row")).to_have_count(1)

    # セルへ入力し Enter (blur) で保存
    cell = app.locator(".db-row .db-input").first
    cell.click()
    cell.fill("設計タスク")
    app.keyboard.press("Enter")
    # 保存 (PATCH) の完了を待ってからリロード
    app.wait_for_timeout(500)

    # リロードしても値が残っている = サーバへ永続化された
    app.reload()
    app.wait_for_selector(".db-table")
    expect(app.locator(".db-row .db-input").first).to_have_value("設計タスク")


def test_database_board_drag_card_between_lanes(app):
    """ボードビューでカードをレーン間ドラッグするとグループ値が変わり永続化される。"""
    create_page_with_first_block(app)
    app.click("#database-button")
    app.wait_for_selector(".db-table")

    # select 列「状態」(Todo / Done) を追加
    app.click(".db-add-col")
    cpop = app.locator(".db-add-col-pop")
    cpop.locator(".db-col-name-input").fill("状態")
    cpop.locator(".db-col-type-input").select_option("select")
    cpop.locator(".db-col-options-input").fill("Todo, Done")
    cpop.locator(".db-col-create").click()
    expect(app.locator(".db-col-name", has_text="状態")).to_have_count(1)

    # 行を 1 つ追加 (状態は未設定)
    app.click(".db-add-row")
    expect(app.locator(".db-row")).to_have_count(1)

    # ボードビューを追加 (group_by=状態)
    app.click(".db-add-view")
    vpop = app.locator(".db-add-view-pop")
    vpop.locator(".db-view-type-input").select_option("board")
    vpop.locator(".db-view-group-input").select_option(label="状態")
    vpop.locator(".db-view-create").click()

    # ボードが描画され、Todo / Done / 未設定 の 3 レーンが出る
    app.wait_for_selector(".db-board")
    expect(app.locator(".db-lane")).to_have_count(3)
    # カードは未設定レーンに 1 枚
    expect(app.locator(".db-lane-header", has_text="未設定 (1)")).to_be_visible()

    # 未設定のカードを Todo レーンへ DnD (合成イベント)
    app.evaluate(
        """() => {
          const card = document.querySelector('.db-lane .db-card');
          let target = null;
          document.querySelectorAll('.db-lane').forEach((l) => {
            if (l.querySelector('.db-lane-header').textContent.startsWith('Todo')) target = l;
          });
          const dt = new DataTransfer();
          const fire = (el, type) =>
            el.dispatchEvent(
              new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt })
            );
          fire(card, 'dragstart');
          fire(target, 'dragover');
          fire(target, 'drop');
        }"""
    )

    # Todo レーンが 1 枚、未設定が 0 枚になる (グループ値が更新された)
    expect(app.locator(".db-lane-header", has_text="Todo (1)")).to_be_visible()
    expect(app.locator(".db-lane-header", has_text="未設定 (0)")).to_be_visible()

    # リロードして永続化を確認。リロード後は既定ビュー(テーブル)が出るので、
    # 状態セルが Todo になっていること = DnD のグループ変更が保存されたこと。
    app.reload()
    app.wait_for_selector(".db-table")
    expect(app.locator(".db-row .db-select")).to_have_value("Todo")


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
