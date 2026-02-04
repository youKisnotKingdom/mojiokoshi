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

---

## 開発環境セットアップ

### 必要なソフトウェア

| ソフトウェア | バージョン | 用途 |
|------------|----------|------|
| Python | 3.11+ | バックエンド |
| Node.js | 18+ | Tailwind CSSビルド |
| Docker | 20+ | PostgreSQL/Redis起動 |
| NVIDIA Driver | 535+ | GPU文字起こし（オプション） |
| CUDA | 12.0+ | faster-whisper用（オプション） |

### 初回セットアップ手順

```bash
# 1. リポジトリをクローン
git clone <repository>
cd mojiokoshi

# 2. Python仮想環境を作成
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 3. Python依存関係をインストール
pip install -r requirements.txt
pip install faster-whisper  # GPU使用時

# 4. Node依存関係をインストール
npm install

# 5. Tailwind CSSをビルド
npm run build:css

# 6. HTMXをダウンロード（オフライン用）
mkdir -p static/js
curl -o static/js/htmx.min.js https://unpkg.com/htmx.org@1.9.10/dist/htmx.min.js

# 7. 環境変数を設定
cp .env.example .env
# .envを編集してLLMサーバーのURLなどを設定

# 8. 開発用PostgreSQL/Redisを起動
docker-compose -f docker-compose.dev.yml up -d

# 9. データベースを初期化
python scripts/init_db.py

# 10. 管理者ユーザーを作成
python scripts/init_db.py --create-admin --admin-id 000001 --admin-password <password>
```

### 開発サーバー起動

```bash
# ターミナル1: Webサーバー
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# ターミナル2: バックグラウンドワーカー
source .venv/bin/activate
python -m app.services.worker

# ターミナル3: CSS監視（オプション）
npm run watch:css
```

### 開発用URL

| サービス | URL |
|---------|-----|
| Webアプリ | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |

---

## 本番環境デプロイ

### 起動シーケンス

```
docker-compose up -d
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  1. PostgreSQL起動                                            │
│     └─ ヘルスチェック: pg_isready                              │
│                                                               │
│  2. Redis起動                                                 │
│                                                               │
│  3. Web/Worker起動 (PostgreSQL ready後)                       │
│     └─ entrypoint.sh実行                                      │
│         ├─ データベース接続待機                                 │
│         ├─ テーブル作成 (init_db.py)                           │
│         ├─ 管理者作成 (環境変数指定時)                          │
│         └─ メインプロセス起動                                   │
│            ├─ Web: uvicorn app.main:app                       │
│            └─ Worker: python -m app.services.worker           │
└───────────────────────────────────────────────────────────────┘
```

### Docker Compose サービス詳細

```yaml
services:
  web:        # Webサーバー (ポート8000)
  worker:     # バックグラウンドワーカー (GPU使用)
  db:         # PostgreSQL (内部ポート5432)
  redis:      # Redis (内部ポート6379)
```

### 初回デプロイ手順

```bash
# 1. 環境変数ファイルを作成
cp .env.example .env

# 2. .envを編集
#    - SECRET_KEY: 安全なランダム文字列
#    - LLM_API_BASE_URL: LLMサーバーのURL
#    - WHISPER_DEVICE: cuda または cpu

# 3. ビルド＆起動
docker-compose up -d --build

# 4. ログを確認
docker-compose logs -f

# 5. 管理者を作成（初回のみ）
docker-compose exec web python scripts/init_db.py \
  --create-admin --admin-id 000001 --admin-password <password>
```

### サービス管理コマンド

```bash
# 起動
docker-compose up -d

# 停止
docker-compose down

# 再起動
docker-compose restart

# ログ確認
docker-compose logs -f web      # Webサーバー
docker-compose logs -f worker   # ワーカー

# シェルに入る
docker-compose exec web bash

# DBに接続
docker-compose exec db psql -U mojiokoshi
```

### GPU設定（NVIDIA）

1. NVIDIA Container Toolkitをインストール:
```bash
# Ubuntu
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

2. `docker-compose.yml`のworkerサービスでGPUセクションを有効化:
```yaml
worker:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

---

## LLMサーバー設定

### 対応サーバー

本システムはOpenAI互換APIを使用するため、以下のサーバーと連携可能:

| サーバー | 特徴 |
|---------|------|
| vLLM | 高速推論、本番向け |
| Ollama | 簡単セットアップ |
| llama.cpp | 軽量、CPU対応 |
| LocalAI | 多機能 |

### vLLM設定例

```bash
# vLLMサーバー起動（別マシン）
python -m vllm.entrypoints.openai.api_server \
  --model mistralai/Mistral-7B-Instruct-v0.2 \
  --host 0.0.0.0 \
  --port 8080
```

`.env`設定:
```
LLM_API_BASE_URL=http://192.168.1.100:8080/v1
LLM_MODEL_NAME=mistralai/Mistral-7B-Instruct-v0.2
```

### Ollama設定例

```bash
# Ollamaサーバー起動（別マシン）
OLLAMA_HOST=0.0.0.0 ollama serve
ollama pull mistral
```

`.env`設定:
```
LLM_API_BASE_URL=http://192.168.1.100:11434/v1
LLM_MODEL_NAME=mistral
```

---

## トラブルシューティング

### よくある問題

| 問題 | 原因 | 解決策 |
|-----|------|-------|
| DB接続エラー | PostgreSQL未起動 | `docker-compose up -d db` |
| 文字起こしが進まない | Worker未起動 | Workerプロセスを確認 |
| GPU認識しない | CUDA未設定 | NVIDIA Container Toolkit確認 |
| 要約エラー | LLM接続失敗 | LLMサーバーURL確認 |
| CSS反映されない | ビルド未実行 | `npm run build:css` |

### ログ確認

```bash
# 開発環境
tail -f uvicorn.log

# Docker環境
docker-compose logs -f web
docker-compose logs -f worker
```

### データベースリセット

```bash
# 開発環境
docker-compose -f docker-compose.dev.yml down -v
docker-compose -f docker-compose.dev.yml up -d
python scripts/init_db.py --create-admin

# 本番環境
docker-compose down -v  # ⚠️ データ全削除
docker-compose up -d --build
docker-compose exec web python scripts/init_db.py --create-admin
```
