# Phase 3: 文字起こし機能

## 目標
音声ファイルのアップロードと文字起こし処理の実装

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

### 3.8 文字起こし画面
- [ ] `templates/transcription/upload.html` 作成
- [ ] ファイルアップロードフォーム
- [ ] ドラッグ&ドロップ対応
- [ ] アップロード進捗表示
- [ ] エンジン・モデル選択UI
- [ ] 言語選択UI

### 3.9 進捗表示機能
- [ ] `templates/transcription/progress.html` 作成
- [ ] HTMX ポーリングによる進捗更新
- [ ] プログレスバー表示
- [ ] ステータスメッセージ表示
- [ ] 完了時の自動遷移

### 3.10 スキーマ定義
- [ ] `app/schemas/audio.py` 作成
- [ ] `app/schemas/transcription.py` 作成
- [ ] アップロードレスポンス
- [ ] ジョブステータスレスポンス
- [ ] 結果レスポンス

## 完了条件
- [ ] 音声ファイルをアップロードできる
- [ ] アップロードしたファイルが正しく保存される
- [ ] 文字起こしジョブを開始できる
- [ ] ジョブの進捗が確認できる
- [ ] 文字起こし結果が表示される
- [ ] Whisperで文字起こしが実行される
- [ ] エラー時に適切なメッセージが表示される

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
openai-whisper
ffmpeg-python
torch
torchaudio
```
