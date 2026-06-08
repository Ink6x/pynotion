# SQLite → PostgreSQL データ移行手順

開発は SQLite ゼロ設定のまま、本番・全文検索検証は PostgreSQL を使う。
既存の SQLite データを PostgreSQL へ移す手順を記録する。

UUID 主キーと自然キーを使うため、`dumpdata` / `loaddata` でクリーンに移行できる。

## 前提

- PostgreSQL 16 が起動していること(`docker compose up postgres` でも可)
- `psycopg` が入っていること: `pip install -e ".[dev,prod]"`

## 手順

### 1. SQLite からデータをエクスポート

開発既定 (SQLite) で実行する。

```bash
python manage.py dumpdata \
  --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission \
  --indent 2 -o dump.json
```

`contenttypes` / `auth.permission` はマイグレーションで再生成されるため除外する
(重複インポートによる整合性エラーを避ける)。

### 2. PostgreSQL を指定してスキーマを作成

`DATABASE_URL` を渡すと dev 設定でも PostgreSQL へ切り替わる。
マイグレーション 0003 が `pg_trgm` 拡張と GIN トライグラムインデックスを作る。

```bash
export DATABASE_URL="postgres://pynotion:pynotion@localhost:5432/pynotion"
python manage.py migrate
```

> `CREATE EXTENSION pg_trgm` には拡張作成権限が必要。
> 公式 postgres イメージの `POSTGRES_USER` はスーパーユーザーなので問題ない。
> マネージド DB では事前に `CREATE EXTENSION` を DBA に依頼するか、
> `rds.extensions` 等で許可されているか確認する。

### 3. データをインポート

```bash
python manage.py loaddata dump.json
```

### 4. 検証

```bash
python manage.py shell -c "from pages.models import Page; print(Page.objects.count())"
# 全文検索が PostgreSQL 経路 (pg_trgm) で動くことを確認
python manage.py shell -c "from pages.search import search_pages; ..."
```

## 全文検索のバックエンド分岐

検索 (`pages/search.py`) は `connection.vendor` で実装を切り替える:

| バックエンド | 実装 |
|---|---|
| PostgreSQL | pg_trgm トライグラム類似 + SearchVector/SearchRank ハイブリッド、SearchHeadline スニペット |
| SQLite (開発・テスト既定) | `icontains` 部分一致フォールバック |

PostgreSQL 経路は CI の `test-postgres` ジョブ(実 PostgreSQL サービス)で検証している。
