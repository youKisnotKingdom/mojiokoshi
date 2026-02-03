# Phase 6: 自動廃棄機能

## 目標
音声ファイルの自動削除機能の実装

## タスク一覧

### 6.1 廃棄設定モデル設計
- [ ] `app/models/settings.py` 作成
- [ ] SystemSettingsモデル（シングルトン的）
  - `id`: 主キー
  - `audio_retention_days`: 音声ファイル保持日数（デフォルト30）
  - `auto_cleanup_enabled`: 自動削除有効フラグ
  - `cleanup_time`: 削除実行時刻（例: "03:00"）
  - `updated_at`: 更新日時
  - `updated_by`: 更新ユーザー（外部キー）
- [ ] マイグレーション作成・実行
- [ ] 初期設定シード

### 6.2 廃棄ログモデル
- [ ] CleanupLogモデル定義
  - `id`: 主キー
  - `executed_at`: 実行日時
  - `files_deleted`: 削除ファイル数
  - `bytes_freed`: 解放容量
  - `deleted_file_ids`: 削除ファイルID一覧（JSON）
  - `status`: ステータス（success/partial/failed）
  - `error_message`: エラーメッセージ
- [ ] マイグレーション作成・実行

### 6.3 設定サービス
- [ ] `app/services/settings.py` 作成
- [ ] 設定取得関数
- [ ] 設定更新関数
- [ ] 設定検証関数

### 6.4 廃棄サービス
- [ ] `app/services/cleanup.py` 作成
- [ ] 期限切れファイル検出関数
- [ ] ファイル削除関数
- [ ] 廃棄実行関数（トランザクション管理）
- [ ] 廃棄ログ記録関数
- [ ] 容量計算関数

### 6.5 スケジューラ設定
- [ ] `app/scheduler.py` 作成
- [ ] APScheduler または Celery Beat 設定
- [ ] 定期実行タスク登録
- [ ] 実行時刻設定

### 6.6 廃棄タスク
- [ ] `app/tasks/cleanup.py` 作成
- [ ] 自動廃棄タスク定義
- [ ] 手動廃棄タスク定義
- [ ] エラーハンドリング
- [ ] 通知機能（オプション）

### 6.7 管理画面: 廃棄設定
- [ ] `templates/admin/settings/cleanup.html` 作成
- [ ] 保持日数設定フォーム
- [ ] 自動削除ON/OFF切り替え
- [ ] 実行時刻設定
- [ ] 即時実行ボタン（手動トリガー）

### 6.8 管理画面: 廃棄ログ
- [ ] `templates/admin/cleanup/logs.html` 作成
- [ ] ログ一覧表示
- [ ] 削除詳細表示
- [ ] 統計表示
  - 総削除ファイル数
  - 総解放容量
  - 最終実行日時

### 6.9 廃棄関連ルーター
- [ ] `app/routers/admin/settings.py` 作成
- [ ] `GET /admin/settings/cleanup` - 設定画面
- [ ] `PUT /admin/settings/cleanup` - 設定更新
- [ ] `POST /admin/cleanup/execute` - 手動実行
- [ ] `GET /admin/cleanup/logs` - ログ一覧
- [ ] `GET /admin/cleanup/preview` - 削除対象プレビュー

### 6.10 削除対象プレビュー機能
- [ ] 削除予定ファイル一覧表示
- [ ] 個別の削除除外設定（オプション）
- [ ] 削除予定容量表示

### 6.11 通知機能（オプション）
- [ ] 廃棄完了通知
- [ ] エラー通知
- [ ] メール/Webhook対応

### 6.12 スキーマ定義
- [ ] `app/schemas/settings.py` 作成
- [ ] `app/schemas/cleanup.py` 作成

## 完了条件
- [ ] 管理画面で廃棄設定を変更できる
- [ ] 保持日数を超えた音声ファイルが自動削除される
- [ ] 文字起こしデータとサマライズは削除されない
- [ ] 廃棄ログが記録される
- [ ] 手動で即時削除を実行できる
- [ ] 削除対象をプレビューできる
- [ ] スケジューラが正しく動作する

## 廃棄ロジック

```python
# 削除対象の判定
def get_files_to_delete():
    settings = get_cleanup_settings()
    cutoff_date = datetime.now() - timedelta(days=settings.audio_retention_days)

    return AudioFile.query.filter(
        AudioFile.created_at < cutoff_date,
        AudioFile.deleted_at.is_(None)
    ).all()

# 廃棄実行
def execute_cleanup():
    files = get_files_to_delete()
    deleted_count = 0
    freed_bytes = 0

    for file in files:
        try:
            # 物理ファイル削除
            os.remove(file.file_path)
            # DBレコード更新（論理削除）
            file.deleted_at = datetime.now()
            deleted_count += 1
            freed_bytes += file.file_size
        except Exception as e:
            log_error(file, e)

    # ログ記録
    create_cleanup_log(deleted_count, freed_bytes)
```

## スケジューラ設定例

### APScheduler
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

scheduler.add_job(
    cleanup_task,
    CronTrigger(hour=3, minute=0),  # 毎日3:00に実行
    id="audio_cleanup",
    replace_existing=True
)
```

### Celery Beat
```python
CELERY_BEAT_SCHEDULE = {
    'cleanup-audio-files': {
        'task': 'app.tasks.cleanup.auto_cleanup',
        'schedule': crontab(hour=3, minute=0),
    },
}
```

## 依存パッケージ追加
```
apscheduler  # または celery[redis]
```
