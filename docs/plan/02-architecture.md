# アーキテクチャ設計 — 目標構成と設計判断

現状(`README.md` のアーキテクチャ節)からの差分として、追加機能ごとの
概要設計と主要な設計判断を記録する。

## 目標構成(Phase 4 完了時)

```
                        ┌─ GitHub Actions (ruff / pytest / E2E / Docker build)
                        │
ブラウザ ── HTTP ──→ Django (WSGI/ASGI)
   │                    ├─ pages/        ページ・ブロック・共有・履歴
   │                    ├─ databases/    DB ビュー (スキーマレスプロパティ)
   │                    ├─ accounts/     認証・ユーザー
   │                    └─ exports/      非同期エクスポート・Webhook
   │
   └── WebSocket ──→ Django Channels ──→ Redis (channel layer / cache / RQ)
                                              │
                                         PostgreSQL (JSONB / pg_trgm / GIN)
```

## A. 認証・マルチユーザー・RBAC

- `Page.owner = ForeignKey(User)`。`AUTH_USER_MODEL` でカスタムユーザーに
  差し替え可能にしておく
- 共有モデル: `PageShare(page, user, role)`、
  `role ∈ {viewer, commenter, editor, full_access}`
- 権限はページ階層を継承(親で editor なら子も editor)。
  `Page.effective_role(user)` が祖先チェーンを辿って最大権限を解決
- API には `@require_role("editor")` デコレータを新設し、
  `PermissionError → 403` を `http.py` で一元変換(既存 `ValueError → 400` と同パターン)
- 認証方式はセッション認証(SPA + CSRF cookie 構成と相性が良く、
  `api.js` は既に `X-CSRFToken` 送出済み)

**難所**: 階層継承の権限解決を N+1 なしで行う祖先チェーン取得。
ページ移動・ソフトデリートと権限の整合。

## B. PostgreSQL 移行 + 全文検索

- `DATABASES` を `dj-database-url` + 環境変数化(SQLite はローカル用に温存)
- 日本語検索: `to_tsvector` は日本語非対応のため、
  **pg_trgm トライグラム検索を主軸**にし、英数字は `SearchVector` 併用の
  ハイブリッド。形態素解析を入れないトレードオフを意図的に選ぶ
- `SearchHeadline` でスニペット/ハイライト、`SearchRank` で関連度順

## C. リアルタイム共同編集(段階設計)

### C-3a: ブロック粒度(楽観ロック + ブロードキャスト)

- Django Channels + Redis channel layer。ページ単位の group (`page_<uuid>`)
- `Block.version`(整数)を追加し、PATCH 時に version 照合(楽観ロック)
- 並べ替えは fractional indexing なのでキー衝突が構造的に起きない
  (同位置同時挿入のみ client_id でタイブレーク)
- WebSocket 認証はセッション。viewer は受信のみ

### C-3b: 文字粒度(CRDT)

- **自前 OT は実装しない**。Yjs(クライアント)+ **pycrdt**(サーバ)を採用。
  「車輪の再発明をどこで止めるか」の判断自体をアピール材料にする
- **サーバ側バインディングは y-py ではなく pycrdt**。y-py は 2023 年で更新停止、
  後継で保守が続く pycrdt(Jupyter コラボレーション基盤で実績)を選定した
  (Phase 4-A スパイクで導入可否と収束性を検証済み)
- 永続化はデバウンス + スナップショット方式
- IME: 既存 `editor.js` の `isComposing` 対応を、リモート更新の適用タイミング
  制御へ拡張する

#### 4-A スパイクの結論(2026-06-09)— **GO**

- pycrdt 0.13 は Windows / Python 3.11 にホイール提供あり。Django 非依存の純
  ドメイン層 `pages/crdt.py`(`BlockDoc`)に実装し、収束性を単体テストで固定
  (`pages/tests/test_crdt_spike.py`、並行編集の収束・可換・冪等・削除複製)
- **同期は Yjs 標準プロトコル(state vector 交換)に従う**。新規 peer を独立に
  初期化すると内部 item id が分岐しデルタをマージできない(落とし穴をテストで固定)。
  必ず空ドキュメントへ権威ドキュメントの更新ストリームを当てて同期する
- **「REST=source of truth」との両立方針**(下記の判断記録 #7):
  - *構造操作*(ブロックの作成 / 移動 / 削除)は従来どおり REST + `Block.version`
    楽観ロックを source of truth とする
  - *テキスト編集*のみ CRDT 化。編集中はライブな `BlockDoc` がマージ権威、
    デバウンスして CRDT → text を投影し `Block.text` 行へ書き戻す。`Block.text`
    が耐久的な source of truth であり続ける(CRDT は「編集中のマージ層」)
  - WS 経由のテキスト更新は接続時の `effective_role`(>= editor)で認可。
    認可境界は WS 接続時のまま、二重実装はしない

#### 4-D サーバ実装(2026-06-09)

- **ライブ状態は Django cache**(`crdt:block:<id>`、プレゼンスと同じ層)。最初の
  アクセスで `Block.text` から種を作る(**サーバが唯一の種まき手**。クライアントは空
  ドキュメント + state vector で同期し、独立初期化の発散を避ける)。
- **WS プロトコル**: `crdt_sync`(クライアントの state vector → 不足分の更新を返す。
  読み取りなので viewer も可)/ `crdt_update`(更新をライブ状態へマージ + 購読者へ
  中継。editor 以上のみ)。バイナリ更新は base64 で JSON に載せる。
- **永続化**: `maybe_flush` の時間スロットリングで `Block.text` へ投影し version を
  進める(REST 読み取りと整合)。切断時に編集ブロックを確実にフラッシュ。
- **多ワーカー**: cache の RMW はプレゼンス同様に競合しうるが、各更新は全クライアントへ
  ブロードキャストされ各自のローカル doc が収束するため、サーバ cache の取りこぼしは
  新規参加者の初期同期がわずかに古い程度に留まる割り切り。
- **ブラウザ Yjs バインディング(4-D-2)は別途**: E2E が WS 非対応のため手動検証になり、
  既存 E2E 保護下のエディタを壊すリスクがあるため、サーバ engine と分離した。
  サーバ側は pycrdt-as-client(`test_crdt_collab.py`)で収束・永続化を完全にテスト済み。

## D. データベースビュー(table / board)

- `Database`(≒特別な Page)+ `DatabaseRow`(1 行 = 1 サブページ)
- プロパティ定義: `PropertySchema(database, key, type, config)`、
  `type ∈ {text, number, select, multi_select, date, checkbox, relation}`
- 値の格納: **JSONB(`JSONField`)+ GinIndex**。
  EAV テーブル方式とのトレードオフ(クエリ性能 vs スキーマ進化)は
  設計ドキュメントで比較した上で JSONB を選択
- ビュー: `DatabaseView(database, type, filters, sorts, group_by)`。
  フィルタ/ソートは JSON で宣言的に保持し、サーバ側で `Q` オブジェクトへ
  動的変換(ORM 経由で SQL インジェクションを担保)

## E. ブロックのネスト

- `Block.parent = ForeignKey("self", null=True)` を追加。
  `position` は同一 parent 内の fractional indexing
- Page ツリーで確立した自己参照 + fractional indexing の設計を横展開
- `serialize_block` をツリー化(`serialize_tree` と同じ手法を再利用)
- Tab / Shift+Tab のインデント、再帰の深さ制限と循環防止

## F. バージョン履歴

- `PageSnapshot(page, created_at, author, content_json)`
- 編集セッション境界でブロックツリー全体を JSON スナップショット
- スナップショット間の block 単位 diff 表示、復元 = ブロック群の再構築
- C-3b 導入後は CRDT 更新ログ自体が履歴になる統合も検討

## G. 非同期処理(エクスポート / Webhook)

- タスクキューは **RQ**(Celery より軽量。ポートフォリオの読みやすさを優先した
  選定理由を語れるようにする)。Redis は Channels と共有
- エクスポート: ブロックツリー → Markdown(純 Python)/ PDF(WeasyPrint)
- Webhook: ページ更新イベントを **HMAC 署名付き POST**、
  失敗時は指数バックオフでリトライ。冪等性を担保

## H. API 体系化

- **DRF 全面移行はしない**。既存の `{ok, data, error}` 封筒と関数ベース API を
  尊重し、**django-ninja を部分導入**して OpenAPI / Swagger UI を自動生成
- リクエストスキーマは pydantic で型安全に
- レート制限: `django-ratelimit` で書き込み系 API に絞って適用

## I. Docker・CI/CD・本番運用

- マルチステージ Dockerfile + docker-compose(web / postgres / redis)
- `settings.py` を `base / dev / prod` に分割、`django-environ`
- prod: `DEBUG=False`、SECRET_KEY 必須化、`SECURE_*` / HSTS / `ALLOWED_HOSTS`
  厳格化、`manage.py check --deploy` 通過
- WhiteNoise、`/healthz`(DB / Redis 疎通)、構造化ログ(JSON)+ Sentry
- GitHub Actions: ruff → pytest(カバレッジ閾値ゲート)→ E2E → Docker build

## J. パフォーマンス

- django-debug-toolbar(dev)でクエリ計測、N+1 排除
  (`select_related` / `prefetch_related`、権限解決の祖先取得)
- ページツリーの Redis キャッシュ + 更新時無効化
- locust で負荷試験し、before/after を README に数値で掲載

## K. E2E テスト(Playwright)

- 主要フロー: ページ作成 → ブロック入力 → Markdown 自動変換 →
  DnD 並べ替え → 検索 → ゴミ箱復元
- contenteditable のキャレット操作・非同期保存の待機が難所
- CI に組み込み

## 設計判断の記録

| # | 判断 | 理由 | 日付 |
|---|---|---|---|
| 1 | DRF 全面移行せず django-ninja 部分導入 | 既存封筒設計の尊重、移行コスト回避 | 2026-06-07 |
| 2 | 日本語全文検索は pg_trgm 主軸(形態素解析なし) | 運用部品を増やさず実用精度を確保 | 2026-06-07 |
| 3 | 文字粒度競合解決は自前 OT でなく Yjs/y-py | バグリスクと工数。再発明の止めどころ | 2026-06-07 |
| 4 | DB ビューのプロパティは EAV でなく JSONB | スキーマ進化の容易さ、GIN で検索担保 | 2026-06-07 |
| 5 | タスクキューは Celery でなく RQ | 軽量・コードの読みやすさ優先 | 2026-06-07 |
| 6 | CRDT サーバ側は y-py でなく pycrdt | y-py は更新停止。pycrdt は保守継続・Yjs 互換 | 2026-06-09 |
| 7 | テキストのみ CRDT 化、構造操作は REST 楽観ロック維持 | 競合は文字編集に集中。`Block.text` を耐久 source に保ち統合を最小化 | 2026-06-09 |
