"""E2E (Playwright) 共通フィクスチャ。

`pytest-playwright` の `page` と `pytest-django` の `live_server` を組み合わせ、
実ブラウザから実アプリ (セッション認証 + CSRF + 自作 contenteditable エディタ) を
操作する。通常のユニットスイートとは分離し (testpaths 外)、専用 CI ジョブで実行する。
"""
import os

# pytest-playwright はセッション初期にイベントループを起動するため、テスト DB の
# セットアップ (同期 DB 操作) が Django の async-unsafe ガードに掛かる。実際の
# DB アクセスは live_server の別スレッドで行われガードの懸念は当たらないため、
# E2E ではこのガードを解除する (テストハーネス専用。アプリ本体には影響しない)。
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

import pytest  # noqa: E402

# E2E はブラウザ越しに別スレッドの DB を触るため transactional_db が必要。
# live_server がそれを内包する。各テストに付与する。
pytestmark = pytest.mark.e2e


@pytest.fixture
def app(live_server, page):
    """サインアップ済みの状態でアプリのトップを開いた `page` を返す。

    `live_server` を `page` より先に要求するのが重要: 先にテスト DB を構築して
    おかないと、Playwright のイベントループ起動後に DB セットアップが走り
    Django の async-unsafe ガードに掛かる。
    """
    base = live_server.url
    username = "e2e_user"
    password = "e2e-pass-9281xZ"

    page.goto(f"{base}/accounts/signup/")
    page.fill("input[name=username]", username)
    page.fill("input[name=password1]", password)
    page.fill("input[name=password2]", password)
    page.click("button[type=submit]")

    # サインアップ成功で "/" にリダイレクトされ、アプリシェルが出る
    page.wait_for_selector("#new-root-page")
    return page


def create_page_with_first_block(page):
    """ルートにページを作成し、最初のブロックが描画されるまで待つ。"""
    page.click("#new-root-page")
    page.wait_for_selector("#editor .block .block-content")
    return page.query_selector("#editor .block .block-content")
