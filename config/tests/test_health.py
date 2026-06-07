"""/healthz エンドポイントのテスト。"""
from unittest import mock

import pytest
from django.test import Client

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class TestHealthz:
    def test_healthz_returns_ok_without_auth(self, client: Client) -> None:
        res = client.get("/healthz")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["checks"]["db"] == "ok"

    def test_healthz_reports_db_failure_as_503(self, client: Client) -> None:
        with mock.patch(
            "config.views.connections", new_callable=mock.MagicMock
        ) as connections:
            connections.__getitem__.return_value.cursor.side_effect = Exception("db down")
            res = client.get("/healthz")
        assert res.status_code == 503
        assert res.json()["checks"]["db"] == "error"

    def test_healthz_skips_redis_when_not_configured(
        self, client: Client, settings
    ) -> None:
        settings.REDIS_URL = None
        res = client.get("/healthz")
        assert "redis" not in res.json()["checks"]

    def test_healthz_reports_redis_failure_as_503(
        self, client: Client, settings
    ) -> None:
        settings.REDIS_URL = "redis://localhost:1/0"  # 接続不能なポート
        res = client.get("/healthz")
        assert res.status_code == 503
        assert res.json()["checks"]["redis"] == "error"
