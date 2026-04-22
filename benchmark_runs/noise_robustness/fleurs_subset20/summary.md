# Noise Robustness Summary: FLEURS subset 20

対象:
- dataset: `FLEURS ja`
- sample count: `20`
- clean manifest: [manifest_clean.jsonl](/home/ykadono/dev/mojiokoshi/benchmark_runs/noise_robustness/fleurs_subset20/manifest_clean.jsonl:1)
- noisy manifest: [manifest_babble10_reverb.jsonl](/home/ykadono/dev/mojiokoshi/benchmark_runs/noise_robustness/fleurs_subset20/manifest_babble10_reverb.jsonl:1)

ノイズ条件:
- `clean`
- `babble10_reverb`
  - 4 本の別話者音声を混ぜた `speech babble`
  - `babble SNR = 10dB`
  - OpenRIR `SLR26` の simulated RIR を適用

モデル:
- `parakeet_ja`
- `cohere_transcribe`
- `faster_whisper`
- `reazon_zipformer`

結果:

| Model | Clean CER | Noisy CER | Delta | Clean xRealtime | Noisy xRealtime |
| --- | ---: | ---: | ---: | ---: | ---: |
| `parakeet_ja` | `10.20%` | `22.11%` | `+11.90pt` | `170.77x` | `162.21x` |
| `cohere_transcribe` | `13.78%` | `30.61%` | `+16.84pt` | `71.14x` | `53.55x` |
| `faster_whisper` | `14.71%` | `29.51%` | `+14.80pt` | `18.42x` | `18.92x` |
| `reazon_zipformer` | `14.03%` | `31.38%` | `+17.35pt` | `31.57x` | `211.00x` |

見立て:
- 20 件規模でも、`babble + reverb` は明確に効く。
- `white noise` 単体より、実運用寄りの `speech babble + reverb` の方が厳しい。
- この条件では、ノイズ下でも最良は `parakeet_ja`。
- `Cohere` は単発 1 本では良く見えたが、20 件 aggregate では `parakeet_ja` より落ち幅が大きい。
- `faster_whisper` は baseline より clean が弱いが、ノイズ下での落ち幅は `Cohere` や `Reazon` と同程度。
- `reazon_zipformer` の `xRealtime` はこの 20 件 run では大きく出ているが、`CER` ではノイズ下の悪化が大きいので、速度だけで選ばない方がよい。

参照:
- clean aggregate: [results_clean/summary.json](/home/ykadono/dev/mojiokoshi/benchmark_runs/noise_robustness/fleurs_subset20/results_clean/summary.json:1)
- noisy aggregate: [results_babble10_reverb/summary.json](/home/ykadono/dev/mojiokoshi/benchmark_runs/noise_robustness/fleurs_subset20/results_babble10_reverb/summary.json:1)
- 参考の単発 28 秒比較: [fleurs_28s/summary.md](/home/ykadono/dev/mojiokoshi/benchmark_runs/noise_robustness/fleurs_28s/summary.md:1)
