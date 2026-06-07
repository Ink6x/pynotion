# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# builder: 依存パッケージを /install へ分離ビルド
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install ".[prod]"

# ---------------------------------------------------------------------------
# runtime: 最小イメージ + 非 root ユーザー
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

RUN useradd --create-home --uid 1000 app

WORKDIR /app
COPY --from=builder /install /usr/local
# --chown でコピーと所有権設定を 1 レイヤに収める (chown -R はレイヤ倍増)
COPY --chown=app:app . .

# collectstatic はビルド時に実行 (ダミー env は静的収集にのみ使用)
RUN DJANGO_SECRET_KEY=build-only-dummy-key-not-used-at-runtime-0123456789 \
    DJANGO_ALLOWED_HOSTS=localhost \
    DATABASE_URL=sqlite:///build-only.sqlite3 \
    python manage.py collectstatic --noinput \
    && rm -f build-only.sqlite3 \
    && chown -R app:app /app/staticfiles

USER app
EXPOSE 8000

# ワーカー数は環境変数で上書き可能 (目安: 2 * CPU + 1)
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --access-logfile -"]
