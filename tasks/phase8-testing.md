# Phase 8: テスト・ドキュメント

## 目標
品質保証とドキュメント整備

## タスク一覧

### 8.1 テスト環境設定
- [ ] `pytest` 設定（`pytest.ini` または `pyproject.toml`）
- [ ] テスト用データベース設定
- [ ] テスト用fixtures作成
- [ ] テスト用環境変数
- [ ] CI/CD パイプライン設定（オプション）

### 8.2 ユニットテスト
- [ ] `tests/unit/` ディレクトリ作成
- [ ] 認証サービステスト
  - パスワードハッシュ化
  - トークン生成・検証
- [ ] ユーザーサービステスト
  - ユーザー作成
  - 6桁ID生成
- [ ] ストレージサービステスト
  - ファイル保存
  - ファイル削除
- [ ] 廃棄サービステスト
  - 期限切れ検出
  - 削除ロジック
- [ ] LLMクライアントテスト（モック）

### 8.3 統合テスト
- [ ] `tests/integration/` ディレクトリ作成
- [ ] データベース操作テスト
- [ ] 認証フローテスト
  - ログイン成功
  - ログイン失敗
  - セッション管理
- [ ] ファイルアップロードテスト
- [ ] 文字起こしフローテスト（モック）
- [ ] サマライズフローテスト（モック）

### 8.4 APIテスト
- [ ] `tests/api/` ディレクトリ作成
- [ ] TestClient使用
- [ ] 認証エンドポイントテスト
- [ ] ユーザー管理APIテスト
- [ ] 文字起こしAPIテスト
- [ ] サマライズAPIテスト
- [ ] 設定APIテスト

### 8.5 E2Eテスト（オプション）
- [ ] Playwright または Selenium 設定
- [ ] ログインフローテスト
- [ ] ファイルアップロードフローテスト
- [ ] 一覧画面テスト

### 8.6 テストデータ・Fixtures
- [ ] `tests/conftest.py` 作成
- [ ] テストユーザーfixture
- [ ] テスト音声ファイルfixture
- [ ] テストデータベースセットアップ
- [ ] モックサービス

### 8.7 カバレッジ設定
- [ ] pytest-cov 設定
- [ ] カバレッジレポート生成
- [ ] カバレッジ目標設定（例: 80%）

### 8.8 API仕様書
- [ ] OpenAPI（Swagger）自動生成確認
- [ ] エンドポイント説明追加
- [ ] リクエスト/レスポンス例追加
- [ ] 認証説明追加
- [ ] `/docs` エンドポイント有効化

### 8.9 README更新
- [ ] プロジェクト概要
- [ ] 機能一覧
- [ ] 技術スタック
- [ ] クイックスタート
- [ ] 開発環境構築手順
- [ ] 本番デプロイ手順
- [ ] 環境変数一覧
- [ ] ライセンス

### 8.10 ユーザーマニュアル
- [ ] `docs/user-manual.md` 作成
- [ ] ログイン方法
- [ ] ファイルアップロード方法
- [ ] 文字起こし実行方法
- [ ] サマライズ実行方法
- [ ] 結果の確認・エクスポート方法
- [ ] スクリーンショット添付

### 8.11 管理者マニュアル
- [ ] `docs/admin-manual.md` 作成
- [ ] ユーザー管理方法
- [ ] 廃棄設定方法
- [ ] プロンプトテンプレート管理
- [ ] システム設定

### 8.12 運用マニュアル
- [ ] `docs/operations.md` 作成
- [ ] インストール手順
- [ ] 起動・停止手順
- [ ] バックアップ・リストア手順
- [ ] ログ確認方法
- [ ] トラブルシューティング
- [ ] よくある問題と解決策

### 8.13 開発者ドキュメント
- [ ] `docs/development.md` 作成
- [ ] アーキテクチャ概要
- [ ] ディレクトリ構造説明
- [ ] 開発環境セットアップ
- [ ] コーディング規約
- [ ] テスト実行方法
- [ ] 新機能追加ガイド

### 8.14 CHANGELOG
- [ ] `CHANGELOG.md` 作成
- [ ] バージョン管理方針
- [ ] 変更履歴記録

## 完了条件
- [ ] ユニットテストが全てパスする
- [ ] 統合テストが全てパスする
- [ ] カバレッジが目標を達成している
- [ ] API仕様書が自動生成される
- [ ] READMEで基本的な使い方がわかる
- [ ] 各マニュアルが整備されている

## テスト構造

```
tests/
├── conftest.py           # 共通fixtures
├── unit/
│   ├── test_auth.py
│   ├── test_user.py
│   ├── test_storage.py
│   ├── test_cleanup.py
│   └── test_llm_client.py
├── integration/
│   ├── test_auth_flow.py
│   ├── test_upload_flow.py
│   └── test_transcription_flow.py
├── api/
│   ├── test_auth_api.py
│   ├── test_user_api.py
│   ├── test_transcription_api.py
│   └── test_summary_api.py
└── e2e/
    ├── test_login.py
    └── test_full_flow.py
```

## pytest設定例

```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --cov=app --cov-report=html --cov-report=term-missing
asyncio_mode = auto
```

## テスト実行コマンド

```bash
# 全テスト実行
pytest

# ユニットテストのみ
pytest tests/unit/

# カバレッジレポート生成
pytest --cov=app --cov-report=html

# 特定テスト実行
pytest tests/unit/test_auth.py -v

# 失敗時に停止
pytest -x
```

## ドキュメント構造

```
docs/
├── user-manual.md      # エンドユーザー向け
├── admin-manual.md     # 管理者向け
├── operations.md       # 運用者向け
└── development.md      # 開発者向け
```

## 依存パッケージ追加
```
# Testing
pytest
pytest-asyncio
pytest-cov
httpx  # TestClient用

# E2E (optional)
playwright

# Documentation
mkdocs  # (optional) ドキュメントサイト生成
```
