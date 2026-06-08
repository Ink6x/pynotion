"""locust 負荷試験シナリオ。

セッション認証 + CSRF を踏んだ上で、ページツリー取得 (キャッシュ対象の読み取り)
を主軸に、検索・ページ作成 (書き込み = キャッシュ無効化) を混ぜる。

使い方:
    # 別ターミナルでアプリを起動 (本番相当なら Redis キャッシュを推奨)
    python manage.py runserver

    # 既存ユーザーの認証情報を渡して負荷をかける
    LOCUST_USER=alice LOCUST_PASS=secret \\
        locust -f locustfile.py --host http://127.0.0.1:8000 \\
               --users 50 --spawn-rate 10 --run-time 1m --headless

ツリー取得はキャッシュヒット時に DB を引かないため、書き込み比率を上げると
無効化が増えてヒット率が下がる。READ/WRITE 比でキャッシュ効果を観測できる。
"""
import os
import re

from locust import HttpUser, between, task

_CSRF_RE = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')


class PynotionUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        """ログインページから CSRF を取得してセッションを確立する。"""
        username = os.environ.get("LOCUST_USER", "alice")
        password = os.environ.get("LOCUST_PASS", "test-pass-alice")
        res = self.client.get("/accounts/login/")
        match = _CSRF_RE.search(res.text)
        token = match.group(1) if match else ""
        self.client.post(
            "/accounts/login/",
            {"username": username, "password": password, "csrfmiddlewaretoken": token},
            headers={"Referer": self.client.base_url},
        )

    @task(10)
    def list_tree(self) -> None:
        """ページツリー取得 (Redis キャッシュ対象)。"""
        self.client.get("/api/pages/")

    @task(3)
    def search(self) -> None:
        self.client.get("/api/search/", params={"q": "メモ"})

    @task(1)
    def create_page(self) -> None:
        """ページ作成 (ツリーキャッシュを無効化する書き込み)。"""
        token = self.client.cookies.get("csrftoken", "")
        self.client.post(
            "/api/pages/",
            json={"title": "負荷試験ページ"},
            headers={"X-CSRFToken": token},
        )
