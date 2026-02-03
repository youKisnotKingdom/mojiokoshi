# Phase 4: サマライズ機能

## 目標
文字起こし結果のLLMによるサマライズ実装

## タスク一覧

### 4.1 サマライズモデル設計
- [ ] `app/models/summary.py` 作成
- [ ] Summaryモデル定義
  - `id`: 主キー
  - `transcription_id`: 文字起こしジョブ（外部キー）
  - `user_id`: 実行ユーザー（外部キー）
  - `status`: ステータス（pending/processing/completed/failed）
  - `prompt_template_id`: 使用プロンプトテンプレート（外部キー、nullable）
  - `custom_prompt`: カスタムプロンプト（nullable）
  - `result_text`: サマライズ結果
  - `model_name`: 使用モデル名
  - `token_usage`: トークン使用量（JSON）
  - `error_message`: エラーメッセージ
  - `created_at`: 作成日時
  - `completed_at`: 完了日時
- [ ] マイグレーション作成・実行

### 4.2 プロンプトテンプレートモデル
- [ ] `app/models/prompt_template.py` 作成
- [ ] PromptTemplateモデル定義
  - `id`: 主キー
  - `name`: テンプレート名
  - `description`: 説明
  - `template`: プロンプトテンプレート本文
  - `is_default`: デフォルトフラグ
  - `is_system`: システム定義フラグ（削除不可）
  - `created_by`: 作成ユーザー（外部キー）
  - `created_at`: 作成日時
  - `updated_at`: 更新日時
- [ ] マイグレーション作成・実行
- [ ] 初期プロンプトテンプレートのシード

### 4.3 LLM API設定
- [ ] `app/config.py` に LLM設定追加
  - `LLM_API_BASE_URL`: APIベースURL（設定可能）
  - `LLM_API_KEY`: APIキー
  - `LLM_MODEL_NAME`: 使用モデル名
  - `LLM_MAX_TOKENS`: 最大トークン数
  - `LLM_TEMPERATURE`: 温度パラメータ

### 4.4 LLMクライアントサービス
- [ ] `app/services/llm_client.py` 作成
- [ ] OpenAI互換APIクライアント
- [ ] リクエスト送信関数
- [ ] ストリーミング対応（オプション）
- [ ] エラーハンドリング
- [ ] リトライ機能
- [ ] レート制限対応

### 4.5 サマライズサービス
- [ ] `app/services/summarization.py` 作成
- [ ] プロンプト生成関数
- [ ] テキスト分割関数（長文対応）
- [ ] サマライズ実行関数
- [ ] 結果保存関数

### 4.6 サマライズ非同期タスク
- [ ] `app/tasks/summarization.py` 作成
- [ ] サマライズタスク定義
- [ ] 進捗更新機能
- [ ] エラーハンドリング

### 4.7 サマライズルーター
- [ ] `app/routers/summary.py` 作成
- [ ] `POST /summary/` - サマライズ開始
- [ ] `GET /summary/{id}` - サマライズ結果取得
- [ ] `GET /summary/{id}/status` - ステータス取得
- [ ] `DELETE /summary/{id}` - サマライズ削除

### 4.8 プロンプトテンプレートルーター
- [ ] `app/routers/prompt_templates.py` 作成
- [ ] `GET /prompt-templates/` - テンプレート一覧
- [ ] `POST /prompt-templates/` - テンプレート作成
- [ ] `GET /prompt-templates/{id}` - テンプレート詳細
- [ ] `PUT /prompt-templates/{id}` - テンプレート更新
- [ ] `DELETE /prompt-templates/{id}` - テンプレート削除

### 4.9 サマライズUI
- [ ] `templates/summary/create.html` 作成
- [ ] プロンプトテンプレート選択UI
- [ ] カスタムプロンプト入力
- [ ] サマライズ実行ボタン
- [ ] 進捗表示

### 4.10 プロンプトテンプレート管理UI
- [ ] `templates/prompt_templates/list.html` 作成
- [ ] `templates/prompt_templates/edit.html` 作成
- [ ] テンプレート一覧表示
- [ ] テンプレート編集フォーム

### 4.11 スキーマ定義
- [ ] `app/schemas/summary.py` 作成
- [ ] `app/schemas/prompt_template.py` 作成

## 完了条件
- [ ] 文字起こし結果からサマライズを実行できる
- [ ] サマライズ結果が表示される
- [ ] プロンプトテンプレートを選択できる
- [ ] カスタムプロンプトを使用できる
- [ ] プロンプトテンプレートを管理できる
- [ ] 外部LLM APIのエンドポイントを設定できる
- [ ] エラー時に適切なメッセージが表示される

## 初期プロンプトテンプレート例

### 議事録サマライズ
```
以下の文字起こしテキストを議事録形式でまとめてください。

【出力形式】
- 日時・参加者（わかる場合）
- 議題
- 主な議論内容
- 決定事項
- 次回アクション

【文字起こしテキスト】
{text}
```

### 要点抽出
```
以下の文字起こしテキストから重要なポイントを箇条書きで抽出してください。

【文字起こしテキスト】
{text}
```

### 一般的な要約
```
以下の文字起こしテキストを簡潔に要約してください。

【文字起こしテキスト】
{text}
```

## 依存パッケージ追加
```
openai
httpx
tiktoken  # トークン数計算用
```

## LLM API設定例（.env）
```
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-xxxxx
LLM_MODEL_NAME=gpt-4o
LLM_MAX_TOKENS=4096
LLM_TEMPERATURE=0.7
```
