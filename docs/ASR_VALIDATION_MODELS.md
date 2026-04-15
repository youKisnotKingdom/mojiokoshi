# ASR Validation Models

アプリ本体へ組み込む前の比較検証用として、以下のモデルを候補にしています。

| Alias | Repo | 想定ランタイム | 備考 |
| --- | --- | --- | --- |
| `parakeet_ja` | `nvidia/parakeet-tdt_ctc-0.6b-ja` | NeMo | 日本語向けの 0.6B モデル |
| `cohere_transcribe` | `CohereLabs/cohere-transcribe-03-2026` | Transformers 系 | gated の可能性あり |
| `reazon_zipformer` | `reazon-research/japanese-zipformer-base-k2-rs35kh` | k2 / Zipformer | 日本語 Zipformer |
| `qwen_asr` | `Qwen/Qwen3-ASR-0.6B` | `qwen-asr` / vLLM | Qwen3-ASR 系の軽量側 |

`qwen_asr` は現時点ではアプリ本体の実装には接続しておらず、検証用 alias としてのみ扱います。
高精度側が必要になったら `Qwen/Qwen3-ASR-1.7B` を別 alias で追加してください。

取得コマンド:

```bash
python scripts/download_validation_models.py --list
python scripts/download_validation_models.py --only qwen_asr
```
