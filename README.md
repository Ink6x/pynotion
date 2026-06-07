# pynotion

Notion を Python (Django) で再現する「車輪の再発明」プロジェクト。

サーバーは Django + SQLite、フロントは Vanilla JS(フレームワークなし)の
contenteditable ベース自作ブロックエディタ。デザインは
[DESIGN.md](./DESIGN.md)(Notion 日本語版のデザイン仕様)に準拠した
ダーク基調(`#191918`)+ ライトテーマ切替対応。

## セットアップ

```bash
python -m venv .venv

# Windows
.venv\Scripts\pip install -e ".[dev]"
# macOS / Linux
.venv/bin/pip install -e ".[dev]"

python manage.py migrate
python manage.py runserver
```

http://127.0.0.1:8000 を開く。

## 機能

| 機能 | 説明 |
|------|------|
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
config/           Django 設定 (環境変数ベース)
pages/
  models.py       Page / Block (UUID PK、ソフトデリート、fractional indexing)
  ordering.py     並び順キー生成 (rocicorp/fractional-indexing の midpoint 移植)
  api_pages.py    ページ CRUD / 移動 / ゴミ箱 / 検索 API
  api_blocks.py   ブロック CRUD / 並べ替え API
  http.py         {ok, data, error} レスポンス封筒
  serializers.py  JSON シリアライザ (ツリー構築)
  tests/          pytest 46 件 (カバレッジ 96%)
static/
  css/tokens.css  DESIGN.md のデザイントークン (CSS Custom Properties)
  css/*.css       アプリシェル / サイドバー / エディタ
  js/api.js       CSRF 対応 fetch ラッパー
  js/editor.js    ブロックエディタ (分割・結合・自動保存・DnD)
  js/slashmenu.js スラッシュコマンド
  js/sidebar.js   ページツリー
  js/modals.js    検索 / ゴミ箱モーダル
  js/app.js       初期化・ページ表示・テーマ
templates/        base.html / app.html
```

### 設計メモ

- **並び順**: ブロック/ページの順序は fractional indexing
  (辞書順比較可能な文字列キー)。並べ替え時に他の行を更新しない
- **ゴミ箱**: `is_deleted` + `deleted_at` のソフトデリート。子孫へカスケードし、
  復元は「同時に削除されたもの」だけを対象にする
- **API**: 全レスポンスを `{ok, data, error}` 封筒で統一

## テスト

```bash
pytest --cov=pages --cov-report=term-missing
```

## ライセンス

MIT
