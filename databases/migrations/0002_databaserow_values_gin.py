# DatabaseRow.values(JSONB)への GIN インデックス — PostgreSQL 専用。
#
# スキーマレスなプロパティ値へのフィルタ(containment / キー存在)を高速化する。
# JSONB / GIN は PostgreSQL 固有のため SQLite(開発・テスト既定)では何もしない
# (vendor ガード)。pages の pg_trgm 移行と同じ作法で、モデル Meta には宣言せず
# この RunPython のみが DB オブジェクトを作る(makemigrations の状態をバックエンド間で揃える)。
from django.db import migrations

_PG_FORWARD = [
    "CREATE INDEX IF NOT EXISTS databases_row_values_gin "
    "ON databases_databaserow USING gin (values jsonb_path_ops);",
]

_PG_REVERSE = [
    "DROP INDEX IF EXISTS databases_row_values_gin;",
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
        ("databases", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_run(_PG_FORWARD), _run(_PG_REVERSE)),
    ]
