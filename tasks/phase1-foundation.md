# Phase 1: プロジェクト基盤構築

## 目標
開発環境とプロジェクト構造の整備

## タスク一覧

### 1.1 プロジェクト初期化
- [ ] `pyproject.toml` または `requirements.txt` の作成
- [ ] Python バージョン指定（3.11+推奨）
- [ ] 基本依存パッケージの定義
  - fastapi
  - uvicorn
  - sqlalchemy
  - psycopg2-binary
  - alembic（マイグレーション）
  - python-multipart（ファイルアップロード）
  - jinja2
  - python-jose（JWT）
  - passlib（パスワードハッシュ）
  - celery または arq（非同期タスク）
  - redis（タスクキュー用）

### 1.2 ディレクトリ構造の作成
- [ ] `app/` ディレクトリ作成
- [ ] `app/__init__.py` 作成
- [ ] `app/main.py` 作成（FastAPIエントリポイント）
- [ ] `app/config.py` 作成（環境変数・設定管理）
- [ ] `app/database.py` 作成（DB接続設定）
- [ ] `app/models/` ディレクトリ作成
- [ ] `app/schemas/` ディレクトリ作成
- [ ] `app/routers/` ディレクトリ作成
- [ ] `app/services/` ディレクトリ作成
- [ ] `app/tasks/` ディレクトリ作成（非同期タスク用）
- [ ] `app/templates/` ディレクトリ作成
- [ ] `static/` ディレクトリ作成
- [ ] `uploads/` ディレクトリ作成
- [ ] `tests/` ディレクトリ作成

### 1.3 FastAPI基本設定
- [ ] FastAPIアプリケーションインスタンス作成
- [ ] CORSミドルウェア設定
- [ ] 静的ファイル配信設定
- [ ] Jinja2テンプレート設定
- [ ] ヘルスチェックエンドポイント（`/health`）

### 1.4 データベース設定
- [ ] SQLAlchemy エンジン設定
- [ ] セッション管理設定
- [ ] Alembic初期化
- [ ] 基本マイグレーション作成

### 1.5 Tailwind CSS設定
- [ ] `package.json` 作成（Tailwindビルド用）
- [ ] Tailwind CSS インストール
  ```bash
  npm install -D tailwindcss
  npx tailwindcss init
  ```
- [ ] `tailwind.config.js` 作成
  - テンプレートパスの設定
  - カスタムカラー設定（オプション）
- [ ] `static/src/input.css` 作成（Tailwindディレクティブ）
  ```css
  @tailwind base;
  @tailwind components;
  @tailwind utilities;
  ```
- [ ] ビルドスクリプト設定（`package.json`）
  ```json
  "scripts": {
    "build:css": "tailwindcss -i ./static/src/input.css -o ./static/css/styles.css --minify",
    "watch:css": "tailwindcss -i ./static/src/input.css -o ./static/css/styles.css --watch"
  }
  ```
- [ ] `.gitignore` に `node_modules/` 追加

### 1.6 基本テンプレート構造
- [ ] `templates/base.html` 作成（共通レイアウト）
- [ ] ビルド済みTailwind CSS読み込み（`/static/css/styles.css`）
- [ ] HTMX読み込み（ローカルファイル `static/js/htmx.min.js`）
- [ ] `templates/index.html` 作成（トップページ）
- [ ] 共通コンポーネント用パーシャル（`templates/partials/`）

### 1.7 開発用Docker設定
- [ ] `docker-compose.dev.yml` 作成
- [ ] PostgreSQL コンテナ設定
- [ ] Redis コンテナ設定（タスクキュー用）
- [ ] ボリューム設定（データ永続化）
- [ ] 開発用環境変数ファイル（`.env.example`）

### 1.8 開発ツール設定
- [ ] `.gitignore` 作成
- [ ] `README.md` 更新（開発環境構築手順）
- [ ] フォーマッター設定（black, isort）
- [ ] リンター設定（ruff or flake8）

## 完了条件
- [ ] `docker-compose up` で開発環境が起動する
- [ ] `http://localhost:8000` でトップページが表示される
- [ ] `http://localhost:8000/health` でヘルスチェックが通る
- [ ] PostgreSQLに接続できる

## 参考コマンド

```bash
# 開発環境起動
docker-compose -f docker-compose.dev.yml up -d

# マイグレーション実行
alembic upgrade head

# 開発サーバー起動
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
