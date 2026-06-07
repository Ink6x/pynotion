# pynotion

![CI](https://github.com/Ink6x/pynotion/actions/workflows/ci.yml/badge.svg)

Notion を Python (Django) で再現する「車輪の再発明」プロジェクト。

サーバーは Django、フロントは Vanilla JS(フレームワークなし)の
contenteditable ベース自作ブロックエディタ。デザインは
[DESIGN.md](./DESIGN.md)(Notion 日本語版のデザイン仕様)に準拠した
ダーク基調(`#191918`)+ ライトテーマ切替対応。

マルチユーザー対応(セッション認証 + 継承付き RBAC 共有)。
開発は SQLite、本番は Docker + PostgreSQL + Redis 構成。

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
| ブロックエディタ | 段落 / 見出し1-3 / ToDo / 箇条書き / 番号付き / 引用 / 区切り線 / コード |
| スラッシュコマンド | `/` でブロックタイプメニュー(インクリメンタル絞り込み) |
| Markdown 風入力 | `# ` `## ` `- ` `1. ` `[] ` `> ` ` ``` ` `---` で自動変換 |
| ブロック操作 | Enter で分割、行頭 Backspace で結合、⠿ ハンドルのドラッグ並べ替え |
| ページアイコン | 絵文字ピッカー、タイトルのインライン編集(自動保存) |
| 検索 | `Ctrl+K` でページ横断検索(タイトル + 本文) |
| ゴミ箱 | ソフトデリート、復元、完全削除 |
| テーマ | ダーク / ライト切替(永続化) |
| 日本語 IME | 変換中のキー操作を奪わない composition 対応 |

## キーボードショートカット

| キー | 動作 |
|------|------|
| `Ctrl+K` / `Cmd+K` | 検索 |
| `Enter` | ブロック分割(コード内は改行) |
| `Shift+Enter` | ブロック内改行 |
| 行頭 `Backspace` | タイプ解除 → 前ブロックと結合 |
| `↑` / `↓` | ブロック間のキャレット移動 |
| `/` | スラッシュコマンドメニュー |
| `Esc` | メニュー / モーダルを閉じる |

## アーキテクチャ

```
config/
  settings/       base / dev / prod の 3 層 (django-environ)
  views.py        /healthz (DB / Redis 疎通)
  logging.py      構造化ログ (1 行 1 JSON)
accounts/         カスタムユーザー + サインアップ / ログイン / ログアウト
pages/
  models.py       Page / Block / PageShare (UUID PK、ソフトデリート、
                  fractional indexing、RBAC ロール解決)
  permissions.py  @require_role デコレータ (認可の一元化)
  ordering.py     並び順キー生成 (rocicorp/fractional-indexing の midpoint 移植)
  api_pages.py    ページ CRUD / 移動 / ゴミ箱 / 検索 API
  api_blocks.py   ブロック CRUD / 並べ替え API
  api_shares.py   共有管理 API (full_access 限定)
  http.py         {ok, data, error} レスポンス封筒 + 401/403/404 変換
  serializers.py  JSON シリアライザ (ツリー構築)
static/
  css/tokens.css  DESIGN.md のデザイントークン (CSS Custom Properties)
  css/*.css       アプリシェル / サイドバー / エディタ / 認証画面
  js/api.js       CSRF 対応 fetch ラッパー
  js/editor.js    ブロックエディタ (分割・結合・自動保存・DnD)
  js/slashmenu.js スラッシュコマンド
  js/sidebar.js   ページツリー
  js/modals.js    検索 / ゴミ箱 / 共有モーダル
  js/app.js       初期化・ページ表示・テーマ
templates/        base.html / app.html / accounts/
Dockerfile        マルチステージ (非 root、ビルド時 collectstatic)
docker-compose.yml  web / postgres / redis
.github/workflows/ci.yml  ruff → pytest (カバレッジ 90% ゲート) → docker build
```

### 設計メモ

- **並び順**: ブロック/ページの順序は fractional indexing
  (辞書順比較可能な文字列キー)。並べ替え時に他の行を更新しない
- **ゴミ箱**: `is_deleted` + `deleted_at` のソフトデリート。子孫へカスケードし、
  復元は「同時に削除されたもの」だけを対象にする
- **API**: 全レスポンスを `{ok, data, error}` 封筒で統一。
  未認証 401 / 権限不足 403 / アクセス権なしは 404 (存在を漏らさない)
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

114 件 / カバレッジ 97%(CI は 90% をゲートに ruff → pytest → docker build)。

## ライセンス

MIT
