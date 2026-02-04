# Phase 5: 一覧・管理画面

## 目標
データの閲覧・管理インターフェースの実装

## タスク一覧

### 5.1 ダッシュボードルーター
- [ ] `app/routers/dashboard.py` 作成
- [ ] `GET /dashboard/` - ダッシュボードトップ
- [ ] `GET /dashboard/jobs` - ジョブ一覧
- [ ] `GET /dashboard/jobs/{id}` - ジョブ詳細

### 5.2 ダッシュボードサービス
- [ ] `app/services/dashboard.py` 作成
- [ ] ジョブ一覧取得（フィルタ・ソート対応）
- [ ] ジョブ詳細取得
- [ ] 統計情報取得
- [ ] 検索機能

### 5.3 ダッシュボードトップ画面
- [ ] `templates/dashboard/index.html` 作成
- [ ] 最近のジョブ一覧
- [ ] 統計サマリー
  - 総ジョブ数
  - 今月のジョブ数
  - 処理中ジョブ数
  - 総文字起こし時間
- [ ] クイックアクション（新規アップロードへのリンク）

### 5.4 ジョブ一覧画面
- [ ] `templates/dashboard/jobs/list.html` 作成
- [ ] テーブル形式での一覧表示
  - ファイル名
  - ステータス
  - アップロード日時
  - 文字起こし状況
  - サマライズ状況
- [ ] ページネーション（HTMX対応）
- [ ] ソート機能（日付、ファイル名、ステータス）
- [ ] フィルタ機能
  - ステータスフィルタ
  - 日付範囲フィルタ
  - キーワード検索

### 5.5 ジョブ詳細画面
- [ ] `templates/dashboard/jobs/detail.html` 作成
- [ ] タブ形式の情報表示
  - **音声タブ**: 音声プレーヤー、ファイル情報
  - **文字起こしタブ**: 文字起こし結果表示
  - **サマライズタブ**: サマライズ結果表示
- [ ] 各タブのHTMX遅延読み込み

### 5.6 音声プレーヤーコンポーネント
- [ ] `templates/components/audio_player.html` 作成
- [ ] HTML5 audio要素
- [ ] 再生/一時停止
- [ ] シークバー
- [ ] 音量調整
- [ ] 再生速度調整
- [ ] ファイル情報表示（長さ、サイズ、フォーマット）

### 5.7 文字起こし結果表示コンポーネント
- [ ] `templates/components/transcription_view.html` 作成
- [ ] テキスト表示
- [ ] タイムスタンプ付きセグメント表示（オプション）
- [ ] コピーボタン
- [ ] テキスト検索（ブラウザ内）
- [ ] 音声との同期再生（オプション）

### 5.8 サマライズ結果表示コンポーネント
- [ ] `templates/components/summary_view.html` 作成
- [ ] サマライズテキスト表示
- [ ] 使用プロンプト表示
- [ ] コピーボタン
- [ ] 再サマライズボタン

### 5.9 検索機能
- [ ] 全文検索機能
  - ファイル名検索
  - 文字起こし内容検索
  - サマライズ内容検索
- [ ] 検索結果ハイライト
- [ ] `templates/dashboard/search.html` 作成

### 5.10 エクスポート機能
- [ ] `app/services/export.py` 作成
- [ ] テキストエクスポート（.txt）
- [ ] JSONエクスポート
- [ ] SRTエクスポート（字幕形式）
- [ ] Markdownエクスポート
- [ ] `GET /dashboard/jobs/{id}/export` エンドポイント

### 5.11 一括操作機能
- [ ] 複数選択UI
- [ ] 一括削除
- [ ] 一括エクスポート
- [ ] 一括サマライズ

### 5.12 レスポンシブデザイン
- [ ] モバイル対応レイアウト
- [ ] テーブルのスクロール対応
- [ ] タブのアコーディオン変換（小画面時）

## 完了条件
- [ ] ダッシュボードトップで統計が表示される
- [ ] ジョブ一覧が表示される
- [ ] ページネーションが動作する
- [ ] フィルタ・ソートが動作する
- [ ] ジョブ詳細で音声が再生できる
- [ ] 文字起こし結果が表示される
- [ ] サマライズ結果が表示される
- [ ] エクスポートが動作する

## 画面遷移図

```
ダッシュボードトップ
    │
    ├── ジョブ一覧
    │       │
    │       └── ジョブ詳細
    │               ├── 音声タブ
    │               ├── 文字起こしタブ
    │               └── サマライズタブ
    │
    ├── 新規アップロード → Phase 3 画面
    │
    └── 検索結果
            │
            └── ジョブ詳細
```

## HTMX パターン例

### ページネーション
```html
<div id="job-list">
  <!-- ジョブ一覧 -->
</div>

<button hx-get="/dashboard/jobs?page=2"
        hx-target="#job-list"
        hx-swap="innerHTML">
  次のページ
</button>
```

### タブ切り替え
```html
<div role="tablist">
  <button hx-get="/dashboard/jobs/1/audio"
          hx-target="#tab-content"
          role="tab">音声</button>
  <button hx-get="/dashboard/jobs/1/transcription"
          hx-target="#tab-content"
          role="tab">文字起こし</button>
  <button hx-get="/dashboard/jobs/1/summary"
          hx-target="#tab-content"
          role="tab">サマライズ</button>
</div>

<div id="tab-content">
  <!-- タブ内容 -->
</div>
```
