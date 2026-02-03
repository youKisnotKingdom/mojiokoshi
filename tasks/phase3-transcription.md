# Phase 3: 文字起こし機能

## 目標
音声ファイルのアップロード、ブラウザ録音、および文字起こし処理の実装
（ストリーミング文字起こし対応）

## タスク一覧

### 3.1 音声ファイルモデル設計
- [ ] `app/models/audio.py` 作成
- [ ] AudioFileモデル定義
  - `id`: 主キー
  - `user_id`: アップロードユーザー（外部キー）
  - `original_filename`: 元のファイル名
  - `stored_filename`: 保存ファイル名（UUID等）
  - `file_path`: ファイルパス
  - `file_size`: ファイルサイズ
  - `mime_type`: MIMEタイプ
  - `duration`: 音声長さ（秒）
  - `created_at`: アップロード日時
  - `expires_at`: 自動削除予定日時
  - `deleted_at`: 削除日時（論理削除用）

### 3.2 文字起こしジョブモデル設計
- [ ] `app/models/transcription.py` 作成
- [ ] TranscriptionJobモデル定義
  - `id`: 主キー
  - `audio_file_id`: 音声ファイル（外部キー）
  - `user_id`: 実行ユーザー（外部キー）
  - `status`: ステータス（pending/processing/completed/failed）
  - `engine`: 使用エンジン（whisper/qwen-asr）
  - `model_size`: モデルサイズ（tiny/base/small/medium/large）
  - `language`: 言語設定
  - `result_text`: 文字起こし結果
  - `result_segments`: セグメント情報（JSON）
  - `error_message`: エラーメッセージ
  - `started_at`: 処理開始日時
  - `completed_at`: 処理完了日時
  - `created_at`: ジョブ作成日時
- [ ] マイグレーション作成・実行

### 3.3 ファイルアップロードサービス
- [ ] `app/services/storage.py` 作成
- [ ] ファイル保存関数
- [ ] ファイル取得関数
- [ ] ファイル削除関数
- [ ] ファイルパス生成（日付ベースディレクトリ）
- [ ] MIMEタイプ検証

### 3.4 音声変換サービス
- [ ] `app/services/audio_converter.py` 作成
- [ ] ffmpeg による音声変換
- [ ] 対応フォーマット変換（→ WAV/MP3）
- [ ] 音声情報取得（長さ、サンプルレート等）
- [ ] ffmpeg インストール確認

### 3.5 文字起こしエンジン統合
- [ ] `app/services/transcription/` ディレクトリ作成
- [ ] `app/services/transcription/base.py` - 基底クラス
- [ ] `app/services/transcription/whisper.py` - Whisper実装
- [ ] `app/services/transcription/qwen_asr.py` - qwen-asr実装
- [ ] エンジン選択ファクトリ
- [ ] GPU利用設定

### 3.6 非同期タスク設定
- [ ] `app/worker.py` - Celery/ARQワーカー設定
- [ ] `app/tasks/transcription.py` - 文字起こしタスク
- [ ] タスク進捗更新機能
- [ ] タスク結果保存機能
- [ ] エラーハンドリング・リトライ設定

### 3.7 文字起こしルーター
- [ ] `app/routers/transcription.py` 作成
- [ ] `POST /transcription/upload` - ファイルアップロード
- [ ] `POST /transcription/{id}/start` - 文字起こし開始
- [ ] `GET /transcription/{id}/status` - ステータス取得
- [ ] `GET /transcription/{id}/result` - 結果取得
- [ ] `DELETE /transcription/{id}` - ジョブ削除

---

## ブラウザ録音機能

### 3.8 録音セッションモデル設計
- [ ] `app/models/recording.py` 作成
- [ ] RecordingSessionモデル定義
  - `id`: 主キー（UUID）
  - `user_id`: 録音ユーザー（外部キー）
  - `status`: ステータス（recording/paused/completed/failed）
  - `started_at`: 録音開始日時
  - `paused_at`: 一時停止日時（nullable）
  - `total_duration`: 合計録音時間（秒）
  - `chunk_count`: 受信チャンク数
  - `created_at`: セッション作成日時
- [ ] RecordingChunkモデル定義
  - `id`: 主キー
  - `session_id`: セッション（外部キー）
  - `chunk_index`: チャンク番号
  - `file_path`: チャンクファイルパス
  - `duration`: チャンク長（秒）
  - `received_at`: 受信日時
- [ ] マイグレーション作成・実行

### 3.9 録音チャンク受信サービス
- [ ] `app/services/recording.py` 作成
- [ ] セッション作成・管理
- [ ] チャンク保存機能
  - 定期的なチャンク受信（例: 30秒ごと）
  - チャンクファイルの連番保存
- [ ] チャンク結合機能（ffmpeg）
- [ ] セッション復旧機能
  - ブラウザ再接続時のセッション継続
- [ ] セッションタイムアウト処理

### 3.10 録音用WebSocket
- [ ] `app/routers/recording_ws.py` 作成
- [ ] WebSocket接続管理
- [ ] `ws://recording/start` - 録音セッション開始
- [ ] チャンクデータ受信ハンドラ
- [ ] 一時停止/再開シグナル処理
- [ ] 接続断時のセッション保持
- [ ] ハートビート実装（接続監視）

### 3.11 録音画面（フロントエンド）
- [ ] `templates/transcription/record.html` 作成
- [ ] `static/js/recorder.js` 作成
- [ ] MediaRecorder API 実装
  - マイク権限取得
  - 録音開始/停止
  - 一時停止/再開
- [ ] チャンク送信機能
  - 定期的なサーバー送信（30秒間隔など設定可能）
  - WebSocket経由での送信
- [ ] 録音時間表示（リアルタイム）
- [ ] 一時停止/再開ボタン
- [ ] 録音停止ボタン
- [ ] 接続状態インジケーター
- [ ] オフライン時のローカル保存（IndexedDB）
  - 再接続時に自動アップロード

### 3.12 録音復旧機能
- [ ] セッションID管理（localStorage）
- [ ] ブラウザ更新時の復旧フロー
  - 既存セッションの検出
  - 録音再開確認ダイアログ
- [ ] 未送信チャンクの再送信
- [ ] セッション終了処理

---

## ストリーミング文字起こし

### 3.13 ストリーミング文字起こしサービス
- [ ] `app/services/transcription/streaming.py` 作成
- [ ] faster-whisper 統合（ストリーミング対応）
- [ ] チャンク単位での文字起こし処理
- [ ] 部分結果の結合・整合
- [ ] VAD（Voice Activity Detection）統合
  - 無音区間のスキップ
  - 発話区間の検出

### 3.14 ストリーミング用WebSocket
- [ ] `app/routers/transcription_ws.py` 作成
- [ ] `ws://transcription/stream` - ストリーミング文字起こし
- [ ] 音声チャンク受信 → 文字起こし → 結果送信
- [ ] 部分結果のリアルタイム送信
- [ ] 最終結果の確定送信

### 3.15 ストリーミング文字起こし画面
- [ ] `templates/transcription/stream.html` 作成
- [ ] リアルタイム文字起こし表示エリア
  - 確定テキスト表示
  - 処理中テキスト表示（薄い色など）
- [ ] スクロール追従機能
- [ ] 録音と同時表示のレイアウト

---

### 3.16 ファイルアップロード画面
- [ ] `templates/transcription/upload.html` 作成
- [ ] ファイルアップロードフォーム
- [ ] ドラッグ&ドロップ対応
- [ ] アップロード進捗表示
- [ ] エンジン・モデル選択UI
- [ ] 言語選択UI

### 3.17 進捗表示機能（バッチ処理用）
- [ ] `templates/transcription/progress.html` 作成
- [ ] HTMX ポーリングによる進捗更新
- [ ] プログレスバー表示
- [ ] ステータスメッセージ表示
- [ ] 完了時の自動遷移

### 3.18 スキーマ定義
- [ ] `app/schemas/audio.py` 作成
- [ ] `app/schemas/transcription.py` 作成
- [ ] `app/schemas/recording.py` 作成
- [ ] アップロードレスポンス
- [ ] ジョブステータスレスポンス
- [ ] 結果レスポンス
- [ ] 録音セッションレスポンス
- [ ] WebSocketメッセージスキーマ

---

## 完了条件

### ファイルアップロード
- [ ] 音声ファイルをアップロードできる
- [ ] アップロードしたファイルが正しく保存される
- [ ] 文字起こしジョブを開始できる
- [ ] ジョブの進捗が確認できる
- [ ] 文字起こし結果が表示される
- [ ] Whisperで文字起こしが実行される
- [ ] エラー時に適切なメッセージが表示される

### ブラウザ録音
- [ ] 録音ボタンで録音を開始できる
- [ ] 録音時間がリアルタイムで表示される
- [ ] 一時停止/再開ができる
- [ ] 録音中のチャンクがサーバーに定期送信される
- [ ] ブラウザ更新後も録音セッションを復旧できる
- [ ] オフライン時もローカルに保存され、再接続時に送信される

### ストリーミング文字起こし
- [ ] 録音しながらリアルタイムで文字起こしが表示される
- [ ] 部分結果と確定結果が区別して表示される
- [ ] 録音完了後に最終結果が保存される

## 対応音声フォーマット
- MP3
- WAV
- M4A
- FLAC
- OGG
- WebM
- その他（ffmpegで変換可能なもの）

## GPU設定メモ
```python
# Whisper GPU設定例
import whisper
model = whisper.load_model("large", device="cuda")
```

## 依存パッケージ追加
```
# 文字起こしエンジン
openai-whisper
faster-whisper       # ストリーミング対応
torch
torchaudio

# 音声処理
ffmpeg-python
webrtcvad            # VAD (Voice Activity Detection)

# WebSocket
websockets

# その他
aiofiles             # 非同期ファイル操作
```

## アーキテクチャ図

```
┌─────────────────────────────────────────────────────────────────┐
│                        ブラウザ                                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ファイル     │  │ 録音ボタン  │  │ リアルタイム文字起こし  │ │
│  │アップロード │  │ (MediaRecorder)│  │      表示エリア        │ │
│  └──────┬──────┘  └──────┬──────┘  └───────────▲─────────────┘ │
│         │                │                     │               │
│         │ HTTP POST      │ WebSocket           │ WebSocket     │
│         │                │ (チャンク送信)       │ (結果受信)    │
└─────────┼────────────────┼─────────────────────┼───────────────┘
          │                │                     │
          ▼                ▼                     │
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI サーバー                            │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ Upload API  │  │Recording WS │  │ Transcription WS        │ │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘ │
│         │                │                     │               │
│         ▼                ▼                     │               │
│  ┌─────────────────────────────────────────────▼─────────────┐ │
│  │              Storage Service                              │ │
│  │    (ファイル保存 / チャンク管理 / 結合)                    │ │
│  └─────────────────────────┬─────────────────────────────────┘ │
│                            │                                   │
│                            ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │           Transcription Service                           │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │ │
│  │  │   Whisper   │  │  qwen-asr   │  │ faster-whisper  │   │ │
│  │  │  (バッチ)   │  │  (バッチ)   │  │ (ストリーミング)│   │ │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘   │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │  PostgreSQL   │
                    │   (メタ情報)   │
                    └───────────────┘
```
