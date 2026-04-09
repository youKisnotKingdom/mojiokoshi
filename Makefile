.PHONY: test test-cov lint migrate build export load up down

# ============================================================
# テスト
# ============================================================

# Run tests with SQLite in-memory (no DB required)
test:
	SECRET_KEY=test-secret-key-not-for-production pytest tests/ -v

# Run tests with coverage report
test-cov:
	SECRET_KEY=test-secret-key-not-for-production pytest tests/ --cov=app --cov-report=term-missing -v

# Run tests against PostgreSQL (Docker must be running)
test-pg:
	SECRET_KEY=test-secret-key-not-for-production \
	TEST_DATABASE_URL=postgresql://mojiokoshi:mojiokoshi@localhost:5432/mojiokoshi_test \
	pytest tests/ -v

# ============================================================
# DB マイグレーション
# ============================================================

migrate:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

migrate-history:
	alembic history

# ============================================================
# コード品質
# ============================================================

lint:
	ruff check app/ tests/

# ============================================================
# Docker - ビルド・起動・停止
# ============================================================

# イメージをビルド（インターネット接続が必要）
build:
	docker compose build

# アプリを起動（.env ファイルが必要）
up:
	docker compose up -d

# アプリを停止
down:
	docker compose down

# ログを確認
logs:
	docker compose logs -f

# ============================================================
# Docker - エアギャップ（インターネット切断）環境向け
# ============================================================

# イメージを tar ファイルに書き出す（インターネット接続環境で実行）
# 出力: mojiokoshi-images.tar
export: build
	docker save mojiokoshi:latest postgres:15-alpine -o mojiokoshi-images.tar
	@echo ""
	@echo "エクスポート完了: mojiokoshi-images.tar"
	@echo "このファイルをオンプレミスサーバーに転送して 'make load' を実行してください。"

# tar ファイルからイメージを読み込む（オンプレミスサーバーで実行）
load:
	docker load -i mojiokoshi-images.tar
	@echo "イメージのロード完了。'make up' でアプリを起動できます。"
