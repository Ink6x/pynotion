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

- [ ] django-ninja 部分導入(既存封筒 `{ok, data, error}` と整合)
- [ ] pydantic リクエストスキーマ
- [ ] OpenAPI / Swagger UI 自動生成
- [ ] `django-ratelimit` で書き込み系 API にレート制限

### K. Playwright E2E

- [ ] Playwright セットアップ + CI 組み込み
- [ ] ページ作成 → ブロック入力 → Markdown 自動変換フロー
- [ ] DnD 並べ替え / スラッシュコマンドフロー
- [ ] 検索 → ゴミ箱復元フロー

### J. パフォーマンス

- [ ] django-debug-toolbar 導入(dev)
- [ ] N+1 排除(`select_related` / `prefetch_related`、権限解決)
- [ ] ページツリーの Redis キャッシュ + 無効化
- [ ] locust 負荷試験、before/after を README に掲載

## Phase 3 — 難問を解いた証明

### E. ブロックのネスト

- [ ] `Block.parent` 自己参照 FK + マイグレーション
- [ ] `serialize_block` のツリー化
- [ ] Tab / Shift+Tab インデント(`editor.js`)
- [ ] toggle ブロック(開閉状態)
- [ ] 深さ制限・循環防止 + 階層を跨ぐ Enter 分割 / Backspace 結合

### C-3a. リアルタイム同期(ブロック粒度)

- [ ] Django Channels + Redis channel layer(ASGI 化)
- [ ] WebSocket セッション認証(viewer は受信のみ)
- [ ] `Block.version` 楽観ロック(version 不一致 → 409)
- [ ] ページ group へのブロック変更ブロードキャスト + クライアント反映
- [ ] 同位置同時挿入の client_id タイブレーク
- [ ] 切断・再接続時の状態同期
- [ ] プレゼンス表示(誰がページを見ているか)

### F. バージョン履歴

- [ ] `PageSnapshot` モデル(編集セッション境界で保存)
- [ ] スナップショット間の block 単位 diff 表示
- [ ] 復元(ブロック群の再構築)
- [ ] ストレージ肥大化対策(保持ポリシー)

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
