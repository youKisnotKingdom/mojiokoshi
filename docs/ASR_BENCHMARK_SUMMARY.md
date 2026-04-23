# ASR Benchmark Summary

更新日: 2026-04-21

このファイルは、これまでに回した ASR ベンチマークの要点をためておくサマリです。
生の結果は `benchmarks/**/report.json` にあります。

注意:
- `CER` は低いほど良いです。
- `xRealtime` は高いほど速いです。
- データセットごとに難しさが違うので、`CER` は横断比較せず同一データセット内で比較します。

## 現時点の結論

- 最終文字起こしを 1 モデルで選ぶなら、現時点の本命は `parakeet_ja`
- 速度と軽さを優先するなら `reazon_zipformer`
- 真のストリーミング品質では `Qwen/Qwen3-ASR-0.6B` + `qwen-asr[vllm]` が最有力
- ただし `Qwen true streaming` は VRAM 消費が重く、16GB GPU での 2 モデル常駐は慎重に見るべき

## 1時間音声の概算処理時間

`xRealtime` から `3600 / xRealtime` で換算した目安です。
実際には初回ロードや I/O が少し乗りますが、モデルの速さ感を見るにはこれで十分です。

## 本番運用メモ

`Parakeet` を本番 batch engine とする場合、この 4060 Ti 16GB では次が実用的です。

- 基本構成: `worker=1`, `chunk=300秒`
- 混雑時の上限: `worker=2`
- 攻めた構成: `worker=3`, `chunk=120秒`, 他 GPU プロセス停止

chunk 長の目安:
- `120秒`: worker 数を増やしやすいが、CER は `300秒` より少し落ちる
- `300秒`: 精度と安定性のバランスが最良
- `600秒`: このマシンでは OOM

詳細な運用実測は [ASR_OPERATIONS_RUNTIME_20260422.md](/home/ykadono/dev/mojiokoshi/docs/ASR_OPERATIONS_RUNTIME_20260422.md:1) を参照。

### 最終文字起こし

| Model | 基準 | xRealtime | 1時間音声の目安 |
| --- | --- | ---: | ---: |
| `reazon_zipformer` | 東大講義 6 本平均 | `286.13x` | 約 `13秒` |
| `cohere_transcribe` | 東大講義 6 本平均 | `169.80x` | 約 `21秒` |
| `parakeet_ja` | 東大講義 6 本平均 | `144.16x` | 約 `25秒` |
| `reazon_nemo_v2` | 東大講義 6 本平均 | `40.62x` | 約 `1分29秒` |
| `faster_whisper` | 東大講義 6 本平均 | `19.43x` | 約 `3分05秒` |
| `qwen_asr` | 東大講義 6 本平均 | `18.32x` | 約 `3分17秒` |
| `qwen_asr_1_7b` | 東大講義 6 本平均 | `11.85x` | 約 `5分04秒` |

### Qwen true streaming

`JSUT 20` の真のストリーミング結果からの換算です。
短発話ベースなので、長尺自発音声では少し遅く見る方が安全です。

| Feed/Decode | xRealtime | 1時間音声の目安 |
| --- | ---: | ---: |
| `0.5s` | `3.99x` | 約 `15分02秒` |
| `1.0s` | `5.62x` | 約 `10分41秒` |
| `2.0s` | `7.17x` | 約 `8分22秒` |

## 最終文字起こし

### 東大講義 6 本平均

`BmtnWaUvX_0` は `full_bmtn_*`、残り 5 本は `benchmarks/utokyo_matrix/*` から集計。

| Model | CER | xRealtime | 備考 |
| --- | ---: | ---: | --- |
| `parakeet_ja` | `21.75%` | `144.16x` | 総合首位 |
| `reazon_zipformer` | `27.63%` | `286.13x` | 最速 |
| `faster_whisper` | `27.86%` | `19.43x` | 基準線 |
| `cohere_transcribe` | `29.46%` | `169.80x` | 速いが精度は少し落ちる |
| `qwen_asr` | `42.23%` | `18.32x` | 長尺では弱い |

補足:
- `reazon_nemo_v2` は 6 本平均で `CER 26.76% / 40.62x`
- `qwen_asr_1_7b` は 6 本平均で `CER 33.35% / 11.85x`

代表結果:
- [Parakeet / Bmtn](/home/ykadono/dev/mojiokoshi/benchmarks/full_bmtn_300_parakeet_ja/parakeet_ja/report.json:1)
- [Reazon Zipformer / Bmtn](/home/ykadono/dev/mojiokoshi/benchmarks/full_bmtn_120_reazon_zipformer/reazon_zipformer/report.json:1)
- [Faster Whisper / Bmtn](/home/ykadono/dev/mojiokoshi/benchmarks/full_bmtn_300_faster_whisper/faster_whisper/report.json:1)

### JSUT 500

| Model | CER | xRealtime | GPU Load |
| --- | ---: | ---: | ---: |
| `parakeet_ja` | `10.27%` | `73.20x` | `9412MB` |
| `reazon_nemo_v2` | `10.72%` | `16.01x` | `9320MB` |
| `qwen_asr_1_7b` | `10.82%` | `12.15x` | `9042MB` |
| `cohere_transcribe` | `11.43%` | `38.66x` | `8506MB` |
| `faster_whisper` | `12.13%` | `10.83x` | `6480MB` |
| `reazon_zipformer` | `12.19%` | `148.04x` | `4938MB` |
| `reazon_hubert_k2` | `12.27%` | `261.20x` | `4940MB` |
| `qwen_asr` | `13.09%` | `15.25x` | `6362MB` |

### ReazonSpeech test 500

| Model | CER | xRealtime | GPU Load |
| --- | ---: | ---: | ---: |
| `reazon_nemo_v2` | `8.87%` | `28.56x` | `11713MB` |
| `cohere_transcribe` | `11.13%` | `61.86x` | `8506MB` |
| `reazon_zipformer` | `12.71%` | `213.38x` | `4938MB` |
| `parakeet_ja` | `14.58%` | `117.56x` | `9412MB` |
| `qwen_asr_1_7b` | `28.06%` | `16.08x` | `9042MB` |
| `faster_whisper` | `28.42%` | `15.44x` | `6480MB` |
| `qwen_asr` | `31.74%` | `21.43x` | `6362MB` |

### FLEURS ja 500

| Model | CER | xRealtime | GPU Load |
| --- | ---: | ---: | ---: |
| `reazon_nemo_v2` | `9.74%` | `36.96x` | `11713MB` |
| `parakeet_ja` | `10.05%` | `209.84x` | `9412MB` |
| `cohere_transcribe` | `10.71%` | `74.45x` | `8506MB` |
| `qwen_asr_1_7b` | `10.88%` | `18.44x` | `14749MB` |
| `reazon_zipformer` | `12.89%` | `452.70x` | `4938MB` |
| `faster_whisper` | `13.34%` | `23.17x` | `6480MB` |
| `qwen_asr` | `13.57%` | `26.21x` | `6362MB` |

## 擬似ストリーミング

今のアプリに近い条件です。固定長チャンクを順次処理して連結します。

### 2 秒 chunk

- `JSUT 20`: `Qwen 0.6B` が `CER 16.29%` で最良
- `FLEURS 20`: `Qwen 0.6B 29.17%` と `Reazon zipformer 29.85%` が近い
- `ReazonSpeech 20`: `Reazon zipformer 36.02%` が最良

### 10 秒 chunk

10 秒 chunk は「最初の表示」ではなく「上書き確定」向けです。

| Dataset | Best CER | 2nd |
| --- | --- | --- |
| `FLEURS 20` | `qwen_asr 16.16%` | `parakeet_ja 16.24%` |
| `ReazonSpeech 20` | `reazon_zipformer 15.61%` | `parakeet_ja 17.32%` |

代表結果:
- [Qwen / FLEURS 10s](/home/ykadono/dev/mojiokoshi/benchmarks/streaming_fleurs20_chunk10/qwen_asr/report.json:1)
- [Parakeet / FLEURS 10s](/home/ykadono/dev/mojiokoshi/benchmarks/streaming_fleurs20_chunk10/parakeet_ja/report.json:1)
- [Reazon Zipformer / ReazonSpeech 10s](/home/ykadono/dev/mojiokoshi/benchmarks/streaming_reazonspeech20_chunk10/reazon_zipformer/report.json:1)

実装判断:
- 1 モデルで `partial + overwrite` をやるなら `reazon_zipformer`
- `10秒` 確定寄りなら `parakeet_ja` も強い

## Qwen true streaming

`qwen-asr[vllm]` を使った真のストリーミングです。

### JSUT 20

| Feed/Decode | CER | xRealtime | First Partial |
| --- | ---: | ---: | ---: |
| `0.5s` | `10.49%` | `3.99x` | `0.68s` |
| `1.0s` | `10.71%` | `5.62x` | `1.21s` |
| `2.0s` | `10.71%` | `7.17x` | `2.22s` |

比較:
- 擬似ストリーミング `Qwen 2s` は `CER 16.29% / first_partial 2.46s`
- `Qwen true streaming` は、少なくとも `JSUT 20` では擬似ストリーミングより明確に良い

代表結果:
- [Qwen true / 0.5s](/home/ykadono/dev/mojiokoshi/benchmarks/qwen_true_stream_jsut20_05/report.json:1)
- [Qwen true / 1.0s](/home/ykadono/dev/mojiokoshi/benchmarks/qwen_true_stream_jsut20_10/report.json:1)
- [Qwen true / 2.0s](/home/ykadono/dev/mojiokoshi/benchmarks/qwen_true_stream_jsut20_20/report.json:1)

## Qwen true streaming のメモリ調整

注意:
- `gpu_memory_after_load_mb` は当該時点の GPU 総使用量です
- このマシンでは `worker` と `demo.checker` が常駐しており、ベースで約 `4435MB` 使っていました
- `gpu_delta_mb` はそのベース差分です

| Setting | GPU After Load | Delta | xRealtime | First Partial | 所見 |
| --- | ---: | ---: | ---: | ---: | --- |
| `util=0.7, max_model_len=8192` | `14430MB` | `+9995MB` | `1.13x` | `3.33s` | メモリ余裕は少ない |
| `util=0.5, max_model_len=8192` | `11240MB` | `+6805MB` | `1.12x` | `3.47s` | 7GB 級まで圧縮可能 |
| `enforce_eager` | `13996MB` | `-` | `2.82x` | `1.91s` | 少し減るが劇的ではない |
| `cpu_offload_gb=4` | `14370MB` | `-` | `0.83x` | `2.13s` | 遅くなりすぎる |

結論:
- 効いたのは `gpu_memory_utilization`
- `max_model_len` を下げるだけではほぼ効かない
- `cpu_offload` は長尺リアルタイム用途では厳しい

代表結果:
- [util=0.5](/home/ykadono/dev/mojiokoshi/benchmarks/qwen_memtest_util05/report.json:1)
- [util=0.7](/home/ykadono/dev/mojiokoshi/benchmarks/qwen_memtest_util07_1/report.json:1)
- [enforce_eager](/home/ykadono/dev/mojiokoshi/benchmarks/qwen_memtest_eager8192/report.json:1)
- [cpu_offload=4](/home/ykadono/dev/mojiokoshi/benchmarks/qwen_memtest_offload4/report.json:1)

## Seminar 実測

seminar の実ファイル 2 本で文字起こしを回した結果です。gold transcript がないため `CER` は未評価で、速度比較と transcript の目視確認用です。

| Audio | Model | xRealtime | Wall | Chunks |
| --- | --- | ---: | ---: | ---: |
| `2026-04-03 第8回勉強会` | `reazon_zipformer` | `239.73x` | `48.1s` | `97` |
| `2026-04-03 第8回勉強会` | `cohere_transcribe` | `180.89x` | `63.8s` | `39` |
| `2026-04-03 第8回勉強会` | `parakeet_ja` | `151.90x` | `76.0s` | `39` |
| `2026-04-16 第9回勉強会` | `reazon_zipformer` | `287.19x` | `31.8s` | `77` |
| `2026-04-16 第9回勉強会` | `cohere_transcribe` | `182.30x` | `50.0s` | `31` |
| `2026-04-16 第9回勉強会` | `parakeet_ja` | `154.47x` | `59.1s` | `31` |

実ファイルの transcript と集計:
- [/home/takemura-lab/Videos/seminar/runs/summary.md](/home/takemura-lab/Videos/seminar/runs/summary.md)
- [/home/takemura-lab/Videos/seminar/runs/parakeet_ja](/home/takemura-lab/Videos/seminar/runs/parakeet_ja)
- [/home/takemura-lab/Videos/seminar/runs/cohere_transcribe](/home/takemura-lab/Videos/seminar/runs/cohere_transcribe)
- [/home/takemura-lab/Videos/seminar/runs/reazon_zipformer](/home/takemura-lab/Videos/seminar/runs/reazon_zipformer)

## Noise Robustness

単発 28 秒サンプルだけだと弱いので、`FLEURS ja` の 20 件サブセットでも `babble + reverb` をかけて再評価した。

ノイズ条件:
- `babble10_reverb`
  - 4 本の別話者音声を混ぜた `speech babble`
  - `babble SNR = 10dB`
  - OpenRIR `SLR26` の simulated RIR を適用

### FLEURS subset 20: clean vs babble+reverb

| Model | Clean CER | Noisy CER | Delta |
| --- | ---: | ---: | ---: |
| `parakeet_ja` | `10.20%` | `22.11%` | `+11.90pt` |
| `cohere_transcribe` | `13.78%` | `30.61%` | `+16.84pt` |
| `faster_whisper` | `14.71%` | `29.51%` | `+14.80pt` |
| `reazon_zipformer` | `14.03%` | `31.38%` | `+17.35pt` |

結論:
- `white noise` 単体より、`speech babble + reverb` の方がはっきり効く。
- 20 件 aggregate でも、ノイズ下の最良は `parakeet_ja`。
- `Cohere` は単発サンプルでは良く見える区間もあるが、aggregate では `Parakeet` より落ち幅が大きい。

詳細:
- [FLEURS subset 20 noise summary](/home/ykadono/dev/mojiokoshi/benchmark_runs/noise_robustness/fleurs_subset20/summary.md:1)
- [28 秒単発の noise summary](/home/ykadono/dev/mojiokoshi/benchmark_runs/noise_robustness/fleurs_28s/summary.md:1)

## Qwen true streaming の現状

`qwen-asr[vllm]` の true streaming は短いデータでは動いていますが、長尺 1 本をそのまま流す構成はまだ安定していません。

- `JSUT 20` では良好
  - `0.5s`: `CER 10.49% / 3.99x / first_partial 0.68s`
  - `1.0s`: `CER 10.71% / 5.62x / first_partial 1.21s`
  - `2.0s`: `CER 10.71% / 7.17x / first_partial 2.22s`
- seminar の full-length 1 session は失敗
  - `reset=300s`: `decoder prompt > max_model_len`
  - `reset=60s`: 初期化は通るが結果生成まで到達せず
- seminar の `60秒 segment x 2本` smoke test は通過
  - `xRealtime 5.30x`
  - `first_partial 2.33s`
  - 代表結果: [qwen_true_stream_seminar_20260416_seg60_smoke/report.json](/home/ykadono/dev/mojiokoshi/benchmarks/qwen_true_stream_seminar_20260416_seg60_smoke/report.json:1)

現時点の判断:
- `Qwen true streaming` は PoC としては有望
- ただし seminar や講義の長尺 full-run をそのまま回す経路は未完成
- 実運用候補としては、まず `Parakeet / Cohere / Reazon` を優先する方が堅い

## 参照

- 生結果一覧: `python scripts/summarize_benchmark_reports.py`
- モデル候補一覧: [ASR_VALIDATION_MODELS.md](/home/ykadono/dev/mojiokoshi/docs/ASR_VALIDATION_MODELS.md:1)
