# Phase 4: サマライズ機能

## 目標
文字起こし結果のLLMによるサマライズ実装

## 前提
- LLMはローカルネットワーク内の別サーバーでホスト（インターネット接続なし）
- OpenAI互換APIを提供するサーバー（vLLM, Ollama, llama.cpp, LocalAI 等）を想定
- APIエンドポイント（IP/ポート）は設定画面で変更可能

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
  - `LLM_API_BASE_URL`: APIベースURL（ローカルネットワーク内サーバー）
  - `LLM_API_KEY`: APIキー（不要な場合は空文字）
  - `LLM_MODEL_NAME`: 使用モデル名
  - `LLM_MAX_TOKENS`: 最大トークン数
  - `LLM_TEMPERATURE`: 温度パラメータ
  - `LLM_TIMEOUT`: 接続タイムアウト（秒）
- [ ] `app/models/settings.py` にLLM設定モデル追加（DB保存用）
- [ ] 管理画面からLLM設定を変更可能に

### 4.4 LLM接続テスト
- [ ] `app/services/llm_client.py` に接続テスト機能追加
- [ ] 管理画面に接続テストボタン
- [ ] 接続状態表示（成功/失敗/モデル情報）

### 4.5 LLMクライアントサービス
- [ ] `app/services/llm_client.py` 作成
- [ ] OpenAI互換APIクライアント（httpx使用）
- [ ] リクエスト送信関数
- [ ] ストリーミング対応（オプション）
- [ ] エラーハンドリング
  - 接続エラー（サーバーダウン）
  - タイムアウト
  - モデル不存在
- [ ] リトライ機能（ネットワーク一時障害対応）
- [ ] 対応サーバー例:
  - vLLM (`http://192.168.x.x:8000/v1`)
  - Ollama (`http://192.168.x.x:11434/v1`)
  - llama.cpp (`http://192.168.x.x:8080/v1`)
  - LocalAI (`http://192.168.x.x:8080/v1`)

### 4.6 サマライズサービス
- [ ] `app/services/summarization.py` 作成
- [ ] プロンプト生成関数
- [ ] テキスト分割関数（長文対応）
- [ ] サマライズ実行関数
- [ ] 結果保存関数

### 4.7 サマライズ非同期タスク
- [ ] `app/tasks/summarization.py` 作成
- [ ] サマライズタスク定義
- [ ] 進捗更新機能
- [ ] エラーハンドリング

### 4.8 サマライズルーター
- [ ] `app/routers/summary.py` 作成
- [ ] `POST /summary/` - サマライズ開始
- [ ] `GET /summary/{id}` - サマライズ結果取得
- [ ] `GET /summary/{id}/status` - ステータス取得
- [ ] `DELETE /summary/{id}` - サマライズ削除

### 4.9 プロンプトテンプレートルーター
- [ ] `app/routers/prompt_templates.py` 作成
- [ ] `GET /prompt-templates/` - テンプレート一覧
- [ ] `POST /prompt-templates/` - テンプレート作成
- [ ] `GET /prompt-templates/{id}` - テンプレート詳細
- [ ] `PUT /prompt-templates/{id}` - テンプレート更新
- [ ] `DELETE /prompt-templates/{id}` - テンプレート削除

### 4.10 サマライズUI
- [ ] `templates/summary/create.html` 作成
- [ ] プロンプトテンプレート選択UI
- [ ] カスタムプロンプト入力
- [ ] サマライズ実行ボタン
- [ ] 進捗表示

### 4.11 プロンプトテンプレート管理UI
- [ ] `templates/prompt_templates/list.html` 作成
- [ ] `templates/prompt_templates/edit.html` 作成
- [ ] テンプレート一覧表示
- [ ] テンプレート編集フォーム

### 4.12 LLM設定管理UI（管理者専用）
- [ ] `templates/admin/llm_settings.html` 作成
- [ ] APIエンドポイント設定フォーム
- [ ] APIキー設定（オプション）
- [ ] モデル名設定
- [ ] パラメータ設定（max_tokens, temperature）
- [ ] 接続テストボタン・結果表示

### 4.13 スキーマ定義
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

### vLLM サーバーの場合
```
LLM_API_BASE_URL=http://192.168.1.100:8000/v1
LLM_API_KEY=
LLM_MODEL_NAME=mistral-7b-instruct
LLM_MAX_TOKENS=4096
LLM_TEMPERATURE=0.7
LLM_TIMEOUT=120
```

### Ollama サーバーの場合
```
LLM_API_BASE_URL=http://192.168.1.100:11434/v1
LLM_API_KEY=
LLM_MODEL_NAME=llama3
LLM_MAX_TOKENS=4096
LLM_TEMPERATURE=0.7
LLM_TIMEOUT=120
```

### llama.cpp サーバーの場合
```
LLM_API_BASE_URL=http://192.168.1.100:8080/v1
LLM_API_KEY=
LLM_MODEL_NAME=default
LLM_MAX_TOKENS=4096
LLM_TEMPERATURE=0.7
LLM_TIMEOUT=120
```

## アーキテクチャ図

```
┌─────────────────────────────────────────────────────────────────┐
│                 オンプレミスネットワーク                          │
│                                                                 │
│  ┌─────────────────────┐         ┌─────────────────────────┐   │
│  │   文字起こしサーバー    │         │    LLMサーバー           │   │
│  │   (本アプリ)          │         │    (vLLM/Ollama等)      │   │
│  │                     │  HTTP   │                         │   │
│  │   FastAPI           │ ──────> │   OpenAI互換API         │   │
│  │   + Whisper/GPU     │         │   + LLM/GPU             │   │
│  │   + PostgreSQL      │         │                         │   │
│  │                     │         │   例: 192.168.1.100:8000 │   │
│  └─────────────────────┘         └─────────────────────────┘   │
│           │                                                     │
│           │ HTTP                                                │
│           ▼                                                     │
│  ┌─────────────────────┐                                       │
│  │   クライアントPC      │                                       │
│  │   (ブラウザ)         │                                       │
│  └─────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────┘
```
