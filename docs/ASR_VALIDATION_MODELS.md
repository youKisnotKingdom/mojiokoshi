# ASR Validation Models

アプリ本体へ組み込む前の比較検証用として、以下のモデルを候補にしています。

| Alias | Repo | 想定ランタイム | 備考 |
| --- | --- | --- | --- |
| `parakeet_ja` | `nvidia/parakeet-tdt_ctc-0.6b-ja` | NeMo | 日本語向けの 0.6B モデル |
| `cohere_transcribe` | `CohereLabs/cohere-transcribe-03-2026` | Transformers 系 | gated の可能性あり |
| `reazon_zipformer` | `reazon-research/japanese-zipformer-base-k2-rs35kh` | k2 / Zipformer | 日本語 Zipformer |
| `reazon_hubert_k2` | `reazon-research/japanese-hubert-base-k2-rs35kh` | k2 / HuBERT | Reazon の追加比較候補 |
| `reazon_nemo_v2` | `reazon-research/reazonspeech-nemo-v2` | NeMo RNNT | Reazon の長音声向け候補 |
| `qwen_asr` | `Qwen/Qwen3-ASR-0.6B` | `qwen-asr` / vLLM | Qwen3-ASR 系の軽量側 |
| `qwen_asr_1_7b` | `Qwen/Qwen3-ASR-1.7B` | `qwen-asr` / vLLM | Qwen3-ASR 系の上位サイズ |
| `canary_1b_flash` | `nvidia/canary-1b-flash` | NeMo | 公開 checkpoint は `ja` 非対応 |

`qwen_asr` / `qwen_asr_1_7b` は現時点ではアプリ本体の実装には接続しておらず、
検証用 alias としてのみ扱います。

取得コマンド:

```bash
python scripts/download_validation_models.py --list
python scripts/download_validation_models.py --only qwen_asr
```

長尺ベンチマーク:

```bash
python scripts/benchmark_asr.py \
  --audio /path/to/meeting.mp3 \
  --models faster_whisper qwen_asr qwen_asr_1_7b parakeet_ja reazon_zipformer reazon_nemo_v2 cohere_transcribe \
  --language ja \
  --device cuda \
  --chunk-seconds 300
```

一括 runner:

```bash
python scripts/run_utokyo_benchmark_matrix.py --all
python scripts/run_eval_dataset_matrix.py --datasets jsut_basic5000_test reazonspeech_test fleurs_ja_test
```

出力される指標:
- `real_time_factor`: 1.0 未満なら音声長より速く処理
- `x_realtime`: 実時間比の処理速度
- `transcript.txt`: 連結した文字起こし結果
- `report.json`: チャンクごとの時間と全文結果

モデル別の前提:
- `qwen_asr` / `qwen_asr_1_7b`: `qwen-asr` パッケージが必要。長尺高速化には公式に vLLM と FlashAttention 2 が推奨されています。
- `cohere_transcribe`: `transformers`, `torch`, `soundfile`, `librosa`, `sentencepiece`, `protobuf` が必要です。
- `parakeet_ja`: `nemo_toolkit['asr']` が必要です。
- `reazon_zipformer` / `reazon_hubert_k2`: `transformers`, `torch`, `librosa`, `numpy` が必要です。
- `reazon_nemo_v2`: `reazonspeech-nemo-asr` と `nemo_toolkit['asr']` が必要です。ローカル `.nemo` checkpoint 直読みでオフライン比較できます。
- `canary_1b_flash`: 公開ローカル checkpoint は `en/de/es/fr` のみで、日本語比較対象には使えません。

結果サマリ:
- [ASR_BENCHMARK_SUMMARY.md](/home/ykadono/dev/mojiokoshi/docs/ASR_BENCHMARK_SUMMARY.md:1)
