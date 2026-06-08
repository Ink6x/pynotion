# 全文検索 (Phase 2-B) のための PostgreSQL 専用スキーマ。
#
# pg_trgm 拡張と、title / text への GIN トライグラムインデックスを作成する。
# これらは PostgreSQL 固有のため、SQLite (開発・テスト既定) では何もしない
# (vendor ガード)。インデックスをモデル Meta に宣言しないのは、makemigrations の
# 状態がバックエンド間で食い違わないようにするため — DB オブジェクトの作成は
# この RunPython のみが担う。
from django.db import migrations

_PG_FORWARD = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
    "CREATE INDEX IF NOT EXISTS pages_page_title_trgm "
    "ON pages_page USING gin (title gin_trgm_ops);",
    "CREATE INDEX IF NOT EXISTS pages_block_text_trgm "
    "ON pages_block USING gin (text gin_trgm_ops);",
]

_PG_REVERSE = [
    "DROP INDEX IF EXISTS pages_block_text_trgm;",
    "DROP INDEX IF EXISTS pages_page_title_trgm;",
    # pg_trgm 拡張は他で共有され得るため DROP しない。
]


def _run(statements):
    def inner(apps, schema_editor):
        if schema_editor.connection.vendor != "postgresql":
            return
        for sql in statements:
            schema_editor.execute(sql)

    return inner


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0002_page_owner_pageshare"),
    ]

    operations = [
        migrations.RunPython(_run(_PG_FORWARD), _run(_PG_REVERSE)),
    ]
