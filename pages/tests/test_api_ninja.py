"""django-ninja 導入 (Phase 2-H) 固有の検証。

既存エンドポイントの外形互換 (URL・封筒・ステータス) は test_api / test_shares /
test_permissions が担保する。ここでは ninja で新たに得られた機能を検証する:
- OpenAPI スキーマ / Swagger UI の自動生成
- 書き込み系 API のレート制限 (429)
"""
import pytest
from django.test import Client
from django.test.utils import override_settings

from pages.tests.helpers import post_json

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class TestOpenAPI:
    def test_schema_is_generated(self, authenticated_client: Client) -> None:
        res = authenticated_client.get("/api/openapi.json")
        assert res.status_code == 200
        schema = res.json()
        assert schema["info"]["title"] == "pynotion API"
        # 書き込み系オペレーションが文書化されている
        assert "/api/pages/" in schema["paths"]
        assert "post" in schema["paths"]["/api/pages/"]

    def test_swagger_ui_available(self, authenticated_client: Client) -> None:
        res = authenticated_client.get("/api/docs")
        assert res.status_code == 200


class TestWriteRateLimit:
    @override_settings(WRITE_RATELIMIT="1/m")
    def test_exceeding_limit_returns_429(self, authenticated_client: Client, user) -> None:
        first = post_json(authenticated_client, "/api/pages/", {"title": "1つ目"})
        assert first.status_code == 201

        second = post_json(authenticated_client, "/api/pages/", {"title": "2つ目"})
        assert second.status_code == 429
        assert second.json()["ok"] is False

    @override_settings(WRITE_RATELIMIT="100/m")
    def test_reads_are_not_rate_limited(self, authenticated_client: Client, user) -> None:
        # 読み取りは制限対象外 (何度呼んでも 200)
        for _ in range(5):
            res = authenticated_client.get("/api/pages/")
            assert res.status_code == 200
