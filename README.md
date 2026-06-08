# pynotion

![CI](https://github.com/Ink6x/pynotion/actions/workflows/ci.yml/badge.svg)

Notion を Python (Django) で再現する「車輪の再発明」プロジェクト。

サーバーは Django、フロントは Vanilla JS(フレームワークなし)の
contenteditable ベース自作ブロックエディタ。デザインは
[DESIGN.md](./DESIGN.md)(Notion 日本語版のデザイン仕様)に準拠した
ダーク基調(`#191918`)+ ライトテーマ切替対応。

マルチユーザー対応(セッション認証 + 継承付き RBAC 共有)。複数ユーザーの
同時編集は Django Channels(WebSocket)でリアルタイムに同期する。
開発は SQLite、本番は Docker + PostgreSQL + Redis 構成(ASGI 配信)。

## セットアップ (開発)

```bash
python -m venv .venv

# Windows
.venv\Scripts\pip install -e ".[dev]"
# macOS / Linux
.venv/bin/pip install -e ".[dev]"

python manage.py migrate
python manage.py runserver
```

http://127.0.0.1:8000 を開き、サインアップしてから利用する。
環境変数なしで起動できる(設定は `config.settings.dev`)。

## セットアップ (Docker)

```bash
docker compose up --build
```

web (gunicorn) / PostgreSQL 16 / Redis 7 が起動し、
http://localhost:8000 で利用できる。死活監視は `GET /healthz`
(DB / Redis の疎通を JSON で返す)。

本番相当の設定 (`config.settings.prod`) では
`DJANGO_SECRET_KEY` / `DJANGO_ALLOWED_HOSTS` / `DATABASE_URL` が必須
(未設定なら起動失敗)。`manage.py check --deploy` を警告ゼロで通過する。
詳細は [.env.example](./.env.example) を参照。

## 機能

| 機能 | 説明 |
|------|------|
| 認証 | サインアップ / ログイン / ログアウト(セッション認証、カスタムユーザー) |
| 共有 / RBAC | ページ単位の共有(閲覧者 / コメント可 / 編集者 / フルアクセス)。親ページの共有は子へ継承 |
| 階層ページ | サイドバーのページツリー、無限ネスト、展開状態の記憶 |
| ブロックエディタ | 段落 / 見出し1-3 / ToDo / 箇条書き / 番号付き / 引用 / 区切り線 / コード / トグル |
| ブロックのネスト | `Tab` / `Shift+Tab` でインデント、トグルの開閉。最大 5 階層、循環・ページ跨ぎを防止 |
| リアルタイム同期 | 同じページを開いている他ユーザーへブロック変更を WebSocket で即時反映(Channels)。`Block.version` の楽観ロックで競合を 409 検出。プレゼンス表示(誰が閲覧中か) |
| スラッシュコマンド | `/` でブロックタイプメニュー(インクリメンタル絞り込み) |
| Markdown 風入力 | `# ` `## ` `- ` `1. ` `[] ` `> ` ` ``` ` `---` で自動変換 |
| ブロック操作 | Enter で分割、行頭 Backspace で結合、⠿ ハンドルのドラッグ並べ替え |
| ページアイコン | 絵文字ピッカー、タイトルのインライン編集(自動保存) |
| 検索 | `Ctrl+K` でページ横断検索(タイトル + 本文)。PostgreSQL では pg_trgm + SearchVector のハイブリッド全文検索(曖昧一致・スニペット)、SQLite では部分一致フォールバック |
| ゴミ箱 | ソフトデリート、復元、完全削除 |
| API ドキュメント | django-ninja による OpenAPI / Swagger UI 自動生成(`/api/docs`)。書き込み系はレート制限付き |
| テーマ | ダーク / ライト切替(永続化) |
| 日本語 IME | 変換中のキー操作を奪わない composition 対応 |

## キーボードショートカット

| キー | 動作 |
|------|------|
| `Ctrl+K` / `Cmd+K` | 検索 |
| `Enter` | ブロック分割(コード内は改行) |
| `Shift+Enter` | ブロック内改行 |
| `Tab` / `Shift+Tab` | ブロックのインデント / アウトデント(ネスト) |
| 行頭 `Backspace` | タイプ解除 → 前ブロックと結合 |
| `↑` / `↓` | ブロック間のキャレット移動 |
| `/` | スラッシュコマンドメニュー |
| `Esc` | メニュー / モーダルを閉じる |

## アーキテクチャ

```
config/
  settings/       base / dev / prod の 3 層 (django-environ)
  asgi.py         ProtocolTypeRouter (HTTP=Django / WebSocket=Channels)
  views.py        /healthz (DB / Redis 疎通)
  logging.py      構造化ログ (1 行 1 JSON)
accounts/         カスタムユーザー + サインアップ / ログイン / ログアウト
pages/
  models.py       Page / Block / PageShare (UUID PK、ソフトデリート、
                  fractional indexing、RBAC ロール解決)
  permissions.py  ロール検査ヘルパー (認可の一元化)
  ordering.py     並び順キー生成 (rocicorp/fractional-indexing の midpoint 移植)
  search.py       全文検索 (PostgreSQL=pg_trgm+SearchVector / SQLite=icontains)
  cache.py        ページツリーの Redis キャッシュ (世代カウンタで無効化)
  api.py          django-ninja API (/api/ 全体、OpenAPI 自動生成、レート制限)
  schemas.py      pydantic リクエストスキーマ (書き込み系の型付け)
  http.py         {ok, data, error} レスポンス封筒 + 401/403/404/409/429 変換
  serializers.py  JSON シリアライザ (ツリー構築 / 共有)
  consumers.py    WebSocket Consumer (購読・ブロードキャスト転送・プレゼンス)
  routing.py      WebSocket ルーティング (ws/pages/<id>/)
  realtime.py     REST 書き込み後のブロードキャストヘルパー (group_send)
static/
  css/tokens.css  DESIGN.md のデザイントークン (CSS Custom Properties)
  css/*.css       アプリシェル / サイドバー / エディタ / 認証画面
  js/api.js       CSRF 対応 fetch ラッパー (X-Client-Id 付与)
  js/realtime.js  WebSocket クライアント (購読・再接続・プレゼンス反映)
  js/editor.js    ブロックエディタ (分割・結合・自動保存・DnD・ネスト・リモート反映)
  js/slashmenu.js スラッシュコマンド
  js/sidebar.js   ページツリー
  js/modals.js    検索 / ゴミ箱 / 共有モーダル
  js/app.js       初期化・ページ表示・テーマ・リアルタイム購読
templates/        base.html / app.html / accounts/
Dockerfile        マルチステージ (非 root、ビルド時 collectstatic)
docker-compose.yml  web / postgres / redis
e2e/              Playwright E2E (pytest-playwright + live_server、testpaths 外)
locustfile.py     locust 負荷試験シナリオ
.github/workflows/ci.yml  ruff → pytest (SQLite, カバレッジ 90% ゲート)
                          → pytest (PostgreSQL, 全文検索) → E2E → docker build
```

### 設計メモ

- **並び順**: ブロック/ページの順序は fractional indexing
  (辞書順比較可能な文字列キー)。並べ替え時に他の行を更新しない。
  ブロックの並び順は `(page, parent)` 単位で採番するため、別階層へ移動しても
  既存の兄弟キーに影響しない
- **ブロックのネスト**: `Block.parent` 自己参照 FK による再帰構造。サーバは
  循環・最大深さ(5)・ページ跨ぎを境界で検証し、ツリー取得はページの
  全ブロックを 1 クエリで取り出してメモリ上で組む(N+1 なし、テストで固定)。
  エディタ側はツリーを「depth 付きの一次元リスト」へ平坦化して扱い、
  分割・結合・矢印移動は視覚順のまま動かしつつ `Tab`/`Shift+Tab` で親を
  付け替える(Notion と同じ視覚モデル)
- **リアルタイム同期**: Django Channels で `ws/pages/<id>/` を購読。**REST を
  信頼できる単一の源 (source of truth)** とし、書き込みは従来どおり django-ninja
  API が処理(認可・レート制限・楽観ロックを一元化)、成功後に Channels で
  ページ group へブロードキャストする。WebSocket 側は受信とプレゼンスに専念し、
  認可を二重実装しない(= WebSocket 経由の不正書き込み口を作らない)。viewer は
  受信専用。`Block.version` の楽観ロックで競合を 409 検出。`X-Client-Id` で自己
  エコーを除去し、同位置同時挿入は fractional indexing のキーで構造的に解決する。
  チャネルレイヤは dev/テストがインメモリ、本番は Redis(複数ワーカー間配信)
- **ゴミ箱**: `is_deleted` + `deleted_at` のソフトデリート。子孫へカスケードし、
  復元は「同時に削除されたもの」だけを対象にする
- **API**: django-ninja で `/api/` を提供。全レスポンスを `{ok, data, error}`
  封筒で統一(renderer + 例外ハンドラ)。未認証 401 / 権限不足 403 /
  アクセス権なし 404(存在を漏らさない)/ レート超過 429。
  書き込みは pydantic スキーマで型付けし、OpenAPI / Swagger UI を
  `/api/docs` に自動生成。DRF 全面移行はせず既存の軽量封筒設計を尊重した
- **RBAC**: `Page.effective_role(user)` が自身 + 祖先チェーンの共有を
  1 クエリで照合 (クエリ数はテストで固定)。子ページの owner は親を継承

## 開発計画

ポートフォリオ強化のロードマップ(認証/RBAC → PostgreSQL/全文検索 →
リアルタイム共同編集 → データベースビュー)は
[docs/plan/](./docs/plan/README.md) で管理している。

## テスト

```bash
pytest --cov=pages --cov=config --cov=accounts --cov-report=term-missing
```

158 件 / カバレッジ 96%(CI は SQLite で 90% ゲート、別途 PostgreSQL ジョブで
全文検索パスを実 DB 検証)。SQLite→PostgreSQL のデータ移行手順は
[docs/postgres-migration.md](./docs/postgres-migration.md) を参照。

### E2E (Playwright)

contenteditable の自作エディタはユニットで担保しづらいため、実ブラウザで
主要フロー(サインアップ → ページ作成 → ブロック入力 → Markdown 自動変換 →
スラッシュコマンド → DnD 並べ替え → 検索 → ゴミ箱復元)を E2E 化した。
CI では専用ジョブで実行し、カバレッジゲートとは分離している。

```bash
python -m playwright install chromium
pytest e2e/ -o addopts=""     # testpaths 外。明示指定で実行
```

## パフォーマンス

- **ページツリーの Redis キャッシュ**: ツリー取得をユーザー単位でキャッシュし、
  ページの作成/改名/移動/削除/共有変更で**世代カウンタ**を進めて一括無効化する
  (ブロック本文の編集では無効化しないため編集中もヒットし続ける)。

  | ツリー取得 (50 ページ) | レイテンシ | DB クエリ数 |
  |---|---|---|
  | キャッシュミス | 3.4 ms | 5 (うちツリー構築 3) |
  | キャッシュヒット | 1.1 ms | 2 (認証のみ、ツリー構築 0) |

  *ローカル SQLite・テストクライアントでの計測。ツリー構築用の DB クエリが 3→0、
  レイテンシ約 3 倍改善。本番 (PostgreSQL + Redis) では DB 往復削減の効果がより大きい。*

- **N+1 の回帰防止**: ページ詳細取得のクエリ数がブロック数に依存しないことを
  テストで固定 (1 件でも 40 件でも同数 = N+1 なし)。
- **クエリ計測**: `DEBUG_TOOLBAR=1 python manage.py runserver` で
  django-debug-toolbar を有効化。
- **負荷試験**: [locustfile.py](./locustfile.py) にセッション認証込みのシナリオ。
  ```bash
  LOCUST_USER=alice LOCUST_PASS=secret \
    locust -f locustfile.py --host http://127.0.0.1:8000 \
           --users 50 --spawn-rate 10 --run-time 1m --headless
  ```

## ライセンス

MIT
