# Mojiokoshi システム概要

## システム構成図

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Docker Container                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│  │   Web Server    │  │     Worker      │  │     PostgreSQL      │ │
│  │   (FastAPI)     │  │  (Background)   │  │                     │ │
│  │                 │  │                 │  │  - users            │ │
│  │  - HTMX画面     │  │ - 文字起こし    │  │  - audio_files      │ │
│  │  - REST API     │  │ - 要約処理      │  │  - transcriptions   │ │
│  │  - WebSocket    │  │ - クリーンアップ │  │  - summaries        │ │
│  │                 │  │                 │  │                     │ │
│  └────────┬────────┘  └────────┬────────┘  └──────────┬──────────┘ │
│           │                    │                      │            │
│           └────────────────────┴──────────────────────┘            │
│                                │                                    │
│  ┌─────────────────────────────┴───────────────────────────────┐   │
│  │                    Shared Volume (uploads/)                  │   │
│  │   - 音声ファイル保存                                          │   │
│  │   - 録音チャンク一時保存                                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
          │                              │
          │ HTTP/WebSocket               │ HTTP (OpenAI互換)
          ▼                              ▼
    ┌───────────┐                ┌───────────────────┐
    │  ブラウザ  │                │  LLMサーバー       │
    │           │                │  (vLLM/Ollama等)   │
    └───────────┘                └───────────────────┘
```

## 主要コンポーネント

### 1. Web Server (`app/main.py`)
FastAPIベースのWebアプリケーション

| エンドポイント | 機能 |
|--------------|------|
| `/` | ホーム画面 |
| `/auth/*` | ログイン・ログアウト |
| `/transcription/*` | 文字起こし（アップロード・録音） |
| `/history` | 履歴一覧 |
| `/summary/*` | 要約機能 |
| `/admin/users/*` | ユーザー管理（管理者のみ） |
| `/ws/recording/{session_id}` | 録音WebSocket |

### 2. Background Worker (`app/services/worker.py`)
バックグラウンドで処理を実行

```
┌─────────────────────────────────────────────┐
│              Worker Loop (5秒間隔)           │
│                                             │
│  1. 文字起こしジョブをチェック → 処理         │
│  2. 要約ジョブをチェック → 処理              │
│  3. 1時間ごとにクリーンアップ実行            │
│                                             │
└─────────────────────────────────────────────┘
```

### 3. データモデル

```
User (ユーザー)
├── user_id: 6桁数字ID
├── password: ハッシュ化パスワード
├── role: admin / user
└── is_active: 有効フラグ

AudioFile (音声ファイル)
├── source: upload / recording
├── file_path: ファイルパス
├── expires_at: 有効期限
└── deleted_at: 削除日時（ソフトデリート）

TranscriptionJob (文字起こしジョブ)
├── status: pending → processing → completed/failed
├── engine: faster_whisper / whisper / qwen_asr
├── result_text: 文字起こし結果
└── result_segments: セグメント情報（JSON）

Summary (要約)
├── status: pending → processing → completed/failed
├── model_name: 使用LLMモデル
└── result_text: 要約結果
```

## 処理フロー

### 音声アップロード〜文字起こし

```
1. ユーザーがファイルをアップロード
   ↓
2. Web Server: ファイル保存 + AudioFile + TranscriptionJob作成
   ↓
3. Worker: pending状態のジョブを検出
   ↓
4. Worker: faster-whisperで文字起こし実行
   ↓
5. Worker: 結果をDBに保存、status=completed
   ↓
6. ユーザー: 画面をHTMXポーリングで更新、結果表示
```

### ブラウザ録音

```
1. ユーザーが録音開始ボタンをクリック
   ↓
2. Browser: MediaRecorder APIで録音開始
   ↓
3. Browser: 30秒ごとにチャンクをWebSocket経由で送信
   ↓
4. Web Server: チャンクを一時保存
   ↓
5. ユーザーが録音停止
   ↓
6. Web Server: チャンクをマージ → AudioFile作成
   ↓
7. 以降は通常の文字起こしフローと同じ
```

### 要約

```
1. 文字起こし完了後、「Summarize」ボタンをクリック
   ↓
2. Web Server: Summary作成（status=pending）
   ↓
3. Worker: pending状態の要約を検出
   ↓
4. Worker: LLM APIに文字起こしテキストを送信
   ↓
5. Worker: 結果をDBに保存、status=completed
```

### 自動クリーンアップ

```
Worker: 1時間ごとに実行
   ↓
1. expires_at < 現在時刻 のファイルを検索
   ↓
2. 物理ファイルを削除
   ↓
3. deleted_at を記録（ソフトデリート）
   ※ 文字起こし結果・要約は保持
```

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| フロントエンド | HTMX + Jinja2 + Tailwind CSS |
| バックエンド | FastAPI (Python 3.11) |
| データベース | PostgreSQL 15 |
| 文字起こし | faster-whisper (GPU/CUDA) |
| 要約 | OpenAI互換API (vLLM/Ollama/llama.cpp) |
| コンテナ | Docker + Docker Compose |

## 設定項目

| 環境変数 | 説明 | デフォルト |
|---------|------|----------|
| `SECRET_KEY` | セッション署名キー | - |
| `DATABASE_URL` | PostgreSQL接続URL | - |
| `LLM_API_BASE_URL` | LLMサーバーURL | - |
| `LLM_MODEL_NAME` | 使用モデル名 | default |
| `WHISPER_MODEL_SIZE` | Whisperモデルサイズ | large |
| `WHISPER_DEVICE` | 実行デバイス | cuda |
| `AUDIO_RETENTION_DAYS` | 音声保持日数 | 30 |

## ディレクトリ構造

```
mojiokoshi/
├── app/
│   ├── main.py              # FastAPIエントリーポイント
│   ├── config.py            # 設定
│   ├── database.py          # DB接続
│   ├── dependencies.py      # 認証依存関係
│   ├── models/              # SQLAlchemyモデル
│   ├── schemas/             # Pydanticスキーマ
│   ├── routers/             # APIルーター
│   │   ├── auth.py          # 認証
│   │   ├── users.py         # ユーザー管理
│   │   ├── transcription.py # 文字起こし
│   │   ├── recording_ws.py  # 録音WebSocket
│   │   ├── history.py       # 履歴
│   │   └── summary.py       # 要約
│   ├── services/            # ビジネスロジック
│   │   ├── auth.py          # 認証サービス
│   │   ├── storage.py       # ファイル保存
│   │   ├── transcription.py # 文字起こし処理
│   │   ├── summarization.py # 要約処理
│   │   ├── cleanup.py       # クリーンアップ
│   │   └── worker.py        # バックグラウンドワーカー
│   └── templates/           # Jinja2テンプレート
├── static/
│   ├── css/styles.css       # ビルド済みTailwind CSS
│   └── js/recorder.js       # 録音機能JavaScript
├── scripts/
│   ├── init_db.py           # DB初期化
│   ├── create_admin.py      # 管理者作成
│   └── entrypoint.sh        # Docker起動スクリプト
├── Dockerfile               # マルチステージビルド
├── docker-compose.yml       # 本番環境構成
└── docker-compose.dev.yml   # 開発環境構成
```
