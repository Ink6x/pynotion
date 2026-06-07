# pynotion

Notion を Python (Django) で再現する「車輪の再発明」プロジェクト。

> デザインは [DESIGN.md](./DESIGN.md)(Notion 日本語版のデザイン仕様)に準拠。

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

## テスト

```bash
pytest --cov=pages
```

## 機能(実装予定)

- 階層ページ(サイドバーのページツリー、無限ネスト)
- ブロックエディタ(段落 / 見出し / ToDo / リスト / 引用 / 区切り線 / コード)
- スラッシュコマンド(`/`)
- ブロックのドラッグ並べ替え
- ページ横断検索(Ctrl+K)
- ゴミ箱(ソフトデリート & 復元)
- ダーク / ライトテーマ切替
