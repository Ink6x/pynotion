# タスクリスト

進捗管理はこのファイルのチェックボックスで行う。
完了したら `[x]` にし、[README.md](./README.md) のダッシュボードも更新する。

## Phase 1 — 実用アプリ化

### A. 認証・マルチユーザー・RBAC

- [x] `authenticated_client` フィクスチャ整備(既存テストの移行準備)
- [x] `accounts` アプリ作成、カスタムユーザー(`AUTH_USER_MODEL`)
- [x] サインアップ / ログイン / ログアウト(セッション認証)
- [x] `Page.owner` 追加 + データマイグレーション
- [x] `PageShare(page, user, role)` モデル(viewer / commenter / editor / full_access)
- [x] `Page.effective_role(user)` — 祖先チェーンを N+1 なしで解決
- [x] `@require_role` デコレータ + `PermissionError → 403`(`http.py` 拡張)
- [x] 全 API エンドポイントへ認可チェック適用
- [x] ページ移動・ソフトデリートと権限の整合テスト
- [x] 共有 UI(共有モーダル・ロール選択)
- [x] 既存テストの認証対応 + 認可テスト追加(カバレッジ 90% 以上維持)

### I. Docker・CI/CD・本番安全化

- [x] `settings` を `base / dev / prod` に分割(`django-environ`)
- [x] prod: `DEBUG=False`・SECRET_KEY 必須化・`SECURE_*`・`ALLOWED_HOSTS`
- [x] `manage.py check --deploy` 通過
- [x] マルチステージ Dockerfile + docker-compose(web / postgres / redis)
- [x] WhiteNoise による静的配信
- [x] `/healthz` ヘルスチェック(DB / Redis 疎通)
- [x] GitHub Actions: ruff → pytest(カバレッジゲート)→ Docker build
- [x] 構造化ログ(JSON)
- [x] README 更新(起動手順・バッジ)

## Phase 2 — 設計力・スケール基礎

### B. PostgreSQL 移行 + 全文検索

- [x] `dj-database-url` + 環境変数化(SQLite はローカル温存)
- [x] SQLite → PostgreSQL データ移行手順の確立([docs/postgres-migration.md](../postgres-migration.md))
- [x] `pg_trgm` 拡張 + トライグラム検索(日本語)
- [x] `SearchVector` + `GinIndex`(英数字)とのハイブリッド
- [x] `SearchHeadline` スニペット / `SearchRank` 関連度順
- [x] 検索 API の置換(`api_pages.py` の icontains 廃止)+ テスト
- [x] CI に PostgreSQL ジョブを追加(pg_trgm 検索パスを実検証)

### H. API 体系化

- [x] django-ninja 導入(`/api/` 全体、既存封筒 `{ok, data, error}`・URL・ステータス互換)
- [x] pydantic リクエストスキーマ(`pages/schemas.py`)
- [x] OpenAPI / Swagger UI 自動生成(`/api/docs`、`/api/openapi.json`)
- [x] `django-ratelimit` で書き込み系 API にレート制限(超過→封筒 429)

### K. Playwright E2E

- [x] Playwright セットアップ(pytest-playwright + live_server)+ CI 専用ジョブ
- [x] サインアップ → ページ作成 → ブロック入力 → Markdown 自動変換フロー
- [x] DnD 並べ替え / スラッシュコマンドフロー
- [x] 検索 → ゴミ箱復元フロー
- [x] (E2E が検出) `window.Editor`/`window.SlashMenu` 未公開でエディタが
      初期化されない実バグを修正

### J. パフォーマンス

- [x] django-debug-toolbar 導入(dev、`DEBUG_TOOLBAR=1` で有効化)
- [x] N+1 排除 + クエリ数回帰テスト(`django_assert_num_queries` 相当の比較で固定)
- [x] ページツリーの Redis キャッシュ + 世代カウンタによる無効化
- [x] locust 負荷試験シナリオ(`locustfile.py`)+ キャッシュ before/after を README に掲載

## Phase 3 — 難問を解いた証明

### E. ブロックのネスト

- [x] `Block.parent` 自己参照 FK + マイグレーション(position を (page, parent) スコープ化)
- [x] `serialize_block` のツリー化(`serialize_block_tree`、ツリー取得は N+1 なし)
- [x] Tab / Shift+Tab インデント(`editor.js`、フラット配列 + depth モデル)
- [x] toggle ブロック(`collapsed` 開閉状態、子孫の表示制御)
- [x] 深さ制限(`MAX_BLOCK_DEPTH=5`)・循環防止・ページ跨ぎ防止 + 階層を跨ぐ
      Enter 分割(親を継承)/ Backspace 結合(子を持つブロックは巻き添え防止)

### C-3a. リアルタイム同期(ブロック粒度)

- [x] Django Channels + Redis channel layer(ASGI 化、dev/テストはインメモリ層)
- [x] WebSocket セッション認証(`AuthMiddlewareStack`、未認証/権限なしは reject、
      viewer は受信のみ)
- [x] `Block.version` 楽観ロック(version 不一致 → 409)
- [x] ページ group へのブロック変更ブロードキャスト + クライアント反映
      (REST を source of truth に固定、書き込み成功後に `group_send`)
- [x] 同位置同時挿入の client_id タイブレーク(fractional indexing + `X-Client-Id`
      による自己エコー除去)
- [x] 切断・再接続時の状態同期(指数バックオフ再接続 + 再接続時に再取得)
- [x] プレゼンス表示(誰がページを見ているか)

### F. バージョン履歴

- [x] `PageSnapshot` モデル(編集セッション境界で保存。`history.maybe_capture` の
      時間スロットリングで連続編集をまとめる)
- [x] block 単位 diff(`history.diff_trees`、追加/削除/変更。詳細 API が現在状態との
      差分=復元プレビューを返す)
- [x] 復元(`history.restore`、トランザクション内でブロックツリーを再構築。
      ネスト保持。復元前に現状も履歴へ)
- [x] ストレージ肥大化対策(ページごと最新 `RETENTION` 件のみ保持)
- [x] 履歴モーダル UI(`🕘 履歴` ボタン、一覧・復元)

## Phase 4 — 最高難度と運用の完成

### C-3b. 文字単位の競合解決(CRDT)

- [ ] Yjs / y-py のスパイク検証(統合可否の見極め)
- [ ] ブロックテキストの Yjs ドキュメント化
- [ ] デバウンス + スナップショット永続化
- [ ] IME 変換中のリモート更新適用制御
- [ ] リモートカーソル表示

### D. データベースビュー

- [ ] `Database` / `DatabaseRow` / `PropertySchema` モデル
- [ ] JSONB プロパティ値 + GinIndex
- [ ] 型ごとのバリデーション(text / number / select / date / checkbox / relation)
- [ ] `DatabaseView`(filters / sorts / group_by)— 宣言的 JSON → `Q` 動的変換(演算子ホワイトリスト)
- [ ] table view UI
- [ ] board view UI(グループ間 DnD — fractional indexing 再利用)
- [ ] プロパティ型変更時の値マイグレーション

### G. 非同期エクスポート / Webhook

- [ ] RQ セットアップ(Redis 共有)
- [ ] Markdown エクスポート(ブロックツリー → md)
- [ ] PDF エクスポート(WeasyPrint)+ 進捗通知
- [ ] Webhook 登録 + HMAC 署名付き配信
- [ ] 指数バックオフ・リトライ・冪等性

### 運用仕上げ

- [ ] Sentry 統合(DSN は環境変数)
- [ ] 負荷試験の数値を README に反映
- [ ] デモ環境デプロイ + スクリーンショット / GIF を README に
