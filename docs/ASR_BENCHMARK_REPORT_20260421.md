# ASR Benchmark Report

更新日: 2026-04-21

このレポートは、2026-04-21 時点の ASR ベンチ結果を共有向けに整理したものです。
生データは `benchmarks/**/report.json` と `benchmark_runs/**/report.json` を参照してください。

## 1. 結論

- 最終文字起こしの総合本命は引き続き `parakeet_ja`
- 速度と VRAM 効率を優先するなら `reazon_zipformer`
- `reazon_nemo_v2` は長尺 6 本平均で `CER 26.76% / 40.62x` まで出ており、`faster_whisper` より速く精度も近い
- `qwen_asr_1_7b` は `qwen_asr 0.6B` より改善したが、長尺 6 本平均ではまだ上位群には届かない
- `Qwen true streaming` は短いデータでは有望だが、長尺 full-run はまだ安定していない

## 2. ベンチの充足状況

### 2.1 東大講義 6 本 long-form

充足済み:
- `parakeet_ja`
- `cohere_transcribe`
- `reazon_zipformer`
- `reazon_nemo_v2`
- `faster_whisper`
- `qwen_asr`
- `qwen_asr_1_7b`

追加実行結果:
- `reazon_nemo_v2`: [benchmark_runs/utokyo_matrix_nemo_20260421](../benchmark_runs/utokyo_matrix_nemo_20260421)
- `qwen_asr_1_7b`: [benchmark_runs/utokyo_matrix_qwen17_20260421](../benchmark_runs/utokyo_matrix_qwen17_20260421)

### 2.2 公開データセット

以下はすべて充足済みです。
- `JSUT 500`
- `ReazonSpeech test 500`
- `FLEURS ja 500`

追加実行結果:
- `reazon_nemo_v2`: [benchmark_runs/dataset_matrix_nemo_20260421](../benchmark_runs/dataset_matrix_nemo_20260421)
- `qwen_asr_1_7b`: [benchmark_runs/dataset_matrix_qwen17_20260421](../benchmark_runs/dataset_matrix_qwen17_20260421)

### 2.3 まだ残っている未充足項目

- seminar 実ファイルの `CER`
  - gold transcript がないため未評価
- `Qwen true streaming` の長尺 full-run
  - 短いデータでは結果あり
  - seminar / 講義の full-length 1 session は未安定

## 3. 主要結果

### 3.1 東大講義 6 本平均

| Model | CER | xRealtime | 評価 |
| --- | ---: | ---: | --- |
| `parakeet_ja` | `21.75%` | `144.16x` | 総合首位 |
| `reazon_nemo_v2` | `26.76%` | `40.62x` | 精度寄りの追加候補 |
| `reazon_zipformer` | `27.63%` | `286.13x` | 最速 |
| `faster_whisper` | `27.86%` | `19.43x` | 基準線 |
| `cohere_transcribe` | `29.46%` | `169.80x` | 速いが精度は少し落ちる |
| `qwen_asr_1_7b` | `33.35%` | `11.85x` | `0.6B` より改善 |
| `qwen_asr` | `42.23%` | `18.32x` | 長尺では弱い |

### 3.2 JSUT 500

| Model | CER | xRealtime |
| --- | ---: | ---: |
| `parakeet_ja` | `10.27%` | `73.20x` |
| `reazon_nemo_v2` | `10.72%` | `16.01x` |
| `qwen_asr_1_7b` | `10.82%` | `12.15x` |
| `cohere_transcribe` | `11.43%` | `38.66x` |
| `faster_whisper` | `12.13%` | `10.83x` |
| `reazon_zipformer` | `12.19%` | `148.04x` |
| `qwen_asr` | `13.09%` | `15.25x` |

### 3.3 ReazonSpeech test 500

| Model | CER | xRealtime |
| --- | ---: | ---: |
| `reazon_nemo_v2` | `8.87%` | `28.56x` |
| `cohere_transcribe` | `11.13%` | `61.86x` |
| `reazon_zipformer` | `12.71%` | `213.38x` |
| `parakeet_ja` | `14.58%` | `117.56x` |
| `qwen_asr_1_7b` | `28.06%` | `16.08x` |
| `faster_whisper` | `28.42%` | `15.44x` |
| `qwen_asr` | `31.74%` | `21.43x` |

### 3.4 FLEURS ja 500

| Model | CER | xRealtime |
| --- | ---: | ---: |
| `reazon_nemo_v2` | `9.74%` | `36.96x` |
| `parakeet_ja` | `10.05%` | `209.84x` |
| `cohere_transcribe` | `10.71%` | `74.45x` |
| `qwen_asr_1_7b` | `10.88%` | `18.44x` |
| `reazon_zipformer` | `12.89%` | `452.70x` |
| `faster_whisper` | `13.34%` | `23.17x` |
| `qwen_asr` | `13.57%` | `26.21x` |

## 4. 1時間音声の目安

長尺 6 本平均の `xRealtime` から換算した概算です。

| Model | xRealtime | 1時間音声の目安 |
| --- | ---: | ---: |
| `reazon_zipformer` | `286.13x` | 約 `13秒` |
| `cohere_transcribe` | `169.80x` | 約 `21秒` |
| `parakeet_ja` | `144.16x` | 約 `25秒` |
| `reazon_nemo_v2` | `40.62x` | 約 `1分29秒` |
| `faster_whisper` | `19.43x` | 約 `3分05秒` |
| `qwen_asr` | `18.32x` | 約 `3分17秒` |
| `qwen_asr_1_7b` | `11.85x` | 約 `5分04秒` |

## 5. seminar 実ファイルの所見

速度比較と transcript の目視確認までは完了しています。

- 出力: [/home/takemura-lab/Videos/seminar/runs/summary.md](/home/takemura-lab/Videos/seminar/runs/summary.md)
- `Reazon` が最速
- `Cohere` は transcript の見た目が比較的安定
- `Parakeet` は速度で劣るが、既存ベンチ全体では依然として本命

## 6. 運用上の同時処理

現状コードでは、`同時アップロード` はできても、`同時文字起こし実行` はほぼ想定されていません。

理由:
- worker は `limit=1` で 1 件ずつ処理
  - [app/services/worker.py](../app/services/worker.py)
- `pending` 取得に `FOR UPDATE SKIP LOCKED` がない
  - [app/services/transcription.py](../app/services/transcription.py)
  - [app/services/summarization.py](../app/services/summarization.py)
- 録音のリアルタイム文字起こしも `web` 側で同じ GPU 経路を使う
  - [app/routers/recording_ws.py](../app/routers/recording_ws.py)

16GB GPU のおおまかな同時実行目安:
- `reazon_zipformer`: 2 本の余地あり
- `faster_whisper medium`: 専用 GPU なら 2 本の余地あり
- `parakeet_ja`: 1 本
- `cohere_transcribe`: 1 本
- `reazon_nemo_v2`: 1 本
- `qwen_asr_1_7b`: 1 本

現実的な方針:
1. ジョブキューは複数積めるまま、まずは実行 1 本ずつ
2. 並列化するなら、先に `SKIP LOCKED` ベースの安全なワーカー取り出しへ変更
3. その上でモデルごとに worker 数を分ける

## 7. 参照

- 既存総合サマリ: [ASR_BENCHMARK_SUMMARY.md](./ASR_BENCHMARK_SUMMARY.md)
- モデル一覧: [ASR_VALIDATION_MODELS.md](./ASR_VALIDATION_MODELS.md)
- seminar 実測: [/home/takemura-lab/Videos/seminar/runs/summary.md](/home/takemura-lab/Videos/seminar/runs/summary.md)
