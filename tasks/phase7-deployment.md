# Phase 7: Docker化・デプロイ

## 目標
オンプレミス環境向けのコンテナ化と構成

## 前提
- インターネット接続なしのオンプレミス環境で動作
- Dockerイメージは事前にビルドし、オフライン環境にインポート
- LLMサーバーはローカルネットワーク内の別サーバー

## タスク一覧

### 7.1 本番用Dockerfile作成
- [ ] `Dockerfile` 作成
- [ ] マルチステージビルド
- [ ] Python依存関係インストール
- [ ] 静的ファイルコピー
- [ ] 非rootユーザー設定
- [ ] ヘルスチェック設定

### 7.2 GPU対応Dockerfile
- [ ] `Dockerfile.gpu` 作成
- [ ] NVIDIA CUDA ベースイメージ
- [ ] PyTorch GPU版インストール
- [ ] Whisper/qwen-asr インストール
- [ ] cuDNN設定

### 7.3 オフラインビルド対応
- [ ] 依存パッケージのダウンロード（requirements.txt）
  ```bash
  pip download -r requirements.txt -d ./packages
  ```
- [ ] Dockerfile でローカルパッケージからインストール
- [ ] Whisper/faster-whisper モデルの事前ダウンロード
- [ ] Dockerイメージのエクスポート手順
  ```bash
  docker save mojiokoshi:latest | gzip > mojiokoshi.tar.gz
  ```
- [ ] Dockerイメージのインポート手順
  ```bash
  docker load < mojiokoshi.tar.gz
  ```
- [ ] オフラインデプロイ用スクリプト作成

### 7.4 Docker Compose構成
- [ ] `docker-compose.yml` 作成（本番用）
- [ ] サービス定義
  - `app`: FastAPIアプリケーション
  - `worker`: Celeryワーカー（GPU対応）
  - `scheduler`: Celery Beat / スケジューラ
  - `db`: PostgreSQL
  - `redis`: Redis（タスクキュー）
  - `nginx`: リバースプロキシ（オプション）

### 7.5 GPU設定
- [ ] NVIDIA Container Toolkit 対応設定
- [ ] docker-compose での GPU割り当て
- [ ] GPU メモリ制限設定
- [ ] 複数GPU対応（オプション）

### 7.6 環境変数・シークレット管理
- [ ] `.env.example` 作成
- [ ] `.env.production` テンプレート
- [ ] Docker secrets 対応（オプション）
- [ ] 必須環境変数
  ```
  # Database
  DATABASE_URL

  # Redis
  REDIS_URL

  # Security
  SECRET_KEY

  # LLM API（ローカルネットワーク内サーバー）
  LLM_API_BASE_URL=http://192.168.x.x:8000/v1
  LLM_API_KEY=             # 不要な場合は空
  LLM_MODEL_NAME=mistral-7b
  LLM_TIMEOUT=120

  # Storage
  UPLOAD_DIR

  # Cleanup
  AUDIO_RETENTION_DAYS
  ```

### 7.7 ボリューム設定
- [ ] PostgreSQLデータ永続化
- [ ] Redisデータ永続化
- [ ] アップロードファイル永続化
- [ ] ログファイル永続化

### 7.8 ネットワーク設定
- [ ] 内部ネットワーク定義
- [ ] 外部公開ポート設定
- [ ] サービス間通信設定

### 7.9 Nginx設定（オプション）
- [ ] `docker/nginx/nginx.conf` 作成
- [ ] リバースプロキシ設定
- [ ] 静的ファイル配信
- [ ] アップロードサイズ制限設定
- [ ] タイムアウト設定
- [ ] SSL/TLS設定（オプション）

### 7.10 ヘルスチェック設定
- [ ] FastAPI ヘルスチェックエンドポイント
- [ ] PostgreSQL 接続チェック
- [ ] Redis 接続チェック
- [ ] Worker ステータスチェック
- [ ] Docker HEALTHCHECK 設定

### 7.11 ログ設定
- [ ] アプリケーションログ設定
- [ ] JSON形式ログ出力
- [ ] ログローテーション
- [ ] ログレベル設定

### 7.12 起動スクリプト
- [ ] `scripts/start.sh` - アプリケーション起動
- [ ] `scripts/start-worker.sh` - ワーカー起動
- [ ] `scripts/start-scheduler.sh` - スケジューラ起動
- [ ] `scripts/init-db.sh` - DB初期化

### 7.13 マイグレーション自動実行
- [ ] 起動時マイグレーション実行
- [ ] マイグレーション失敗時の処理
- [ ] ロールバック手順

### 7.14 バックアップ設定
- [ ] PostgreSQLバックアップスクリプト
- [ ] アップロードファイルバックアップ
- [ ] バックアップスケジュール

### 7.15 監視設定（オプション）
- [ ] Prometheus メトリクスエンドポイント
- [ ] Grafanaダッシュボード設定
- [ ] アラート設定
- [ ] LLMサーバー接続状態監視

## 完了条件
- [ ] `docker-compose up` で全サービスが起動する
- [ ] GPUがワーカーで認識される
- [ ] アプリケーションにアクセスできる
- [ ] 文字起こしがGPUで実行される
- [ ] データが永続化される
- [ ] コンテナ再起動後もデータが維持される
- [ ] **オフライン環境でDockerイメージをインポート・起動できる**
- [ ] **ローカルネットワーク内のLLMサーバーに接続できる**

## ディレクトリ構造

```
mojiokoshi/
├── docker/
│   ├── nginx/
│   │   └── nginx.conf
│   └── postgres/
│       └── init.sql
├── scripts/
│   ├── start.sh
│   ├── start-worker.sh
│   ├── start-scheduler.sh
│   └── init-db.sh
├── Dockerfile
├── Dockerfile.gpu
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
└── .env.production.example
```

## docker-compose.yml 構成例

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/mojiokoshi
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    volumes:
      - uploads:/app/uploads
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  worker:
    build:
      dockerfile: Dockerfile.gpu
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/mojiokoshi
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    volumes:
      - uploads:/app/uploads

  scheduler:
    build: .
    command: python -m app.scheduler
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/mojiokoshi
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis

  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=mojiokoshi
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  uploads:
  postgres_data:
  redis_data:
```

## GPU設定メモ

### NVIDIA Container Toolkit インストール
```bash
# Ubuntu
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### GPU確認
```bash
docker run --rm --gpus all nvidia/cuda:11.8-base nvidia-smi
```
