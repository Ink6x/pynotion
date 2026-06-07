"""構造化ログ (JSON フォーマッタ) のテスト。"""
import json
import logging

import pytest

from config.logging import JsonFormatter

pytestmark = pytest.mark.unit


class TestJsonFormatter:
    def _record(self, **kwargs) -> logging.LogRecord:
        defaults = {
            "name": "django.request",
            "level": logging.WARNING,
            "pathname": __file__,
            "lineno": 1,
            "msg": "問題が発生: %s",
            "args": ("詳細",),
            "exc_info": None,
        }
        return logging.LogRecord(**{**defaults, **kwargs})

    def test_formats_record_as_json(self) -> None:
        line = JsonFormatter().format(self._record())
        payload = json.loads(line)
        assert payload["level"] == "WARNING"
        assert payload["logger"] == "django.request"
        assert payload["message"] == "問題が発生: 詳細"
        assert "timestamp" in payload

    def test_includes_exception_info(self) -> None:
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys

            record = self._record(exc_info=sys.exc_info())
        payload = json.loads(JsonFormatter().format(record))
        assert "RuntimeError: boom" in payload["exc_info"]
