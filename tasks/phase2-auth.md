# Phase 2: 認証・ユーザー管理

## 目標
ログイン機能と権限管理の実装

## タスク一覧

### 2.1 ユーザーモデル設計
- [ ] `app/models/user.py` 作成
- [ ] Userモデル定義
  - `id`: 主キー（UUID or 連番）
  - `user_id`: 6桁数字（ユニーク、ログイン用）
  - `password_hash`: パスワードハッシュ
  - `role`: ロール（admin / user）
  - `display_name`: 表示名
  - `is_active`: アクティブフラグ
  - `created_at`: 作成日時
  - `updated_at`: 更新日時
  - `last_login_at`: 最終ログイン日時
- [ ] マイグレーション作成・実行

### 2.2 認証スキーマ定義
- [ ] `app/schemas/user.py` 作成
- [ ] `UserCreate` スキーマ
- [ ] `UserUpdate` スキーマ
- [ ] `UserResponse` スキーマ
- [ ] `LoginRequest` スキーマ
- [ ] `TokenResponse` スキーマ

### 2.3 認証サービス実装
- [ ] `app/services/auth.py` 作成
- [ ] パスワードハッシュ化関数
- [ ] パスワード検証関数
- [ ] JWTトークン生成関数
- [ ] JWTトークン検証関数
- [ ] セッション管理（Cookieベース）

### 2.4 認証ルーター実装
- [ ] `app/routers/auth.py` 作成
- [ ] `POST /auth/login` - ログイン
- [ ] `POST /auth/logout` - ログアウト
- [ ] `GET /auth/me` - 現在のユーザー情報取得

### 2.5 認証ミドルウェア・依存関係
- [ ] `app/dependencies.py` 作成
- [ ] `get_current_user` 依存関係
- [ ] `get_current_active_user` 依存関係
- [ ] `require_admin` 依存関係（管理者権限チェック）

### 2.6 ログイン画面
- [ ] `templates/auth/login.html` 作成
- [ ] ログインフォーム（HTMX対応）
- [ ] エラーメッセージ表示
- [ ] ログイン成功時のリダイレクト

### 2.7 ユーザー管理サービス
- [ ] `app/services/user.py` 作成
- [ ] ユーザー作成関数
- [ ] ユーザー取得関数（ID、user_id）
- [ ] ユーザー一覧取得関数
- [ ] ユーザー更新関数
- [ ] ユーザー削除関数（論理削除）
- [ ] 6桁ID自動生成関数

### 2.8 管理者用ユーザー管理ルーター
- [ ] `app/routers/admin/users.py` 作成
- [ ] `GET /admin/users` - ユーザー一覧
- [ ] `POST /admin/users` - ユーザー作成
- [ ] `GET /admin/users/{id}` - ユーザー詳細
- [ ] `PUT /admin/users/{id}` - ユーザー更新
- [ ] `DELETE /admin/users/{id}` - ユーザー削除

### 2.9 管理者用ユーザー管理画面
- [ ] `templates/admin/users/list.html` 作成
- [ ] `templates/admin/users/create.html` 作成
- [ ] `templates/admin/users/edit.html` 作成
- [ ] HTMX部分更新対応

### 2.10 初期管理者作成
- [ ] `scripts/create_admin.py` 作成
- [ ] コマンドラインから初期管理者を作成可能に
- [ ] 環境変数からも設定可能に

## 完了条件
- [ ] ログイン画面が表示される
- [ ] 正しい認証情報でログインできる
- [ ] 不正な認証情報でエラーが表示される
- [ ] ログアウトできる
- [ ] 未認証状態で保護ページにアクセスするとログイン画面にリダイレクトされる
- [ ] 管理者がユーザーを作成・編集・削除できる
- [ ] 一般ユーザーは管理画面にアクセスできない

## セキュリティ考慮事項
- パスワードは bcrypt でハッシュ化
- セッションCookieは HttpOnly, Secure, SameSite=Lax
- CSRF対策
- ログイン試行回数制限（オプション）
