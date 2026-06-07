"""構造化ログ — 1 行 1 JSON のフォーマッタ。

外部依存を増やさないため標準 logging のみで実装する。
ログ集約基盤 (CloudWatch / Loki 等) でのパースを想定。
"""
import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
