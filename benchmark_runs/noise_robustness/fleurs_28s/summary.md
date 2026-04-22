# Noise Robustness Check

対象:
- dataset: `FLEURS ja`
- sample id: `fleurs_ja_test-00152-9518252661993015549`
- audio: [clean.wav](/home/ykadono/dev/mojiokoshi/benchmark_runs/noise_robustness/fleurs_28s/clean.wav)
- reference: [reference.txt](/home/ykadono/dev/mojiokoshi/benchmark_runs/noise_robustness/fleurs_28s/reference.txt)

条件:
- artificial white noise
- `SNR 20dB / 10dB / 5dB`
- models: `parakeet_ja`, `cohere_transcribe`
- additional realistic conditions
  - `babble10`: 別話者 4 本を混ぜた speech babble, `10dB`
  - `babble10+reverb`: 上記 babble + OpenRIR `SLR26` の simulated RIR

結果:

| Model | Condition | CER | xRealtime |
|---|---:|---:|---:|
| Parakeet | clean | 5.05% | 41.95x |
| Parakeet | 20dB | 5.05% | 52.25x |
| Parakeet | 10dB | 6.06% | 36.53x |
| Parakeet | 5dB | 6.06% | 33.25x |
| Cohere | clean | 5.05% | 29.15x |
| Cohere | 20dB | 5.05% | 34.63x |
| Cohere | 10dB | 6.06% | 33.07x |
| Cohere | 5dB | 6.06% | 40.60x |
| Parakeet | babble10 | 5.05% | 37.25x |
| Parakeet | babble10+reverb | 8.08% | 37.66x |
| Cohere | babble10 | 5.05% | 38.67x |
| Cohere | babble10+reverb | 5.05% | 40.70x |

観察:
- `20dB` では両モデルとも clean と同じ transcript だった。
- `10dB` と `5dB` では、両モデルとも `ペリー氏` が `ケリー氏` に崩れた。
- この 28 秒サンプルでは、ノイズで全文が崩れるというより、固有名詞の先頭音が落ちる形だった。
- 速度はこのサンプルでは大きく悪化していない。
- `babble10` 単体では、両モデルとも clean と同じ transcript だった。
- `babble10+reverb` では、`Parakeet` は `見極めし -> 見極め`、`進むべき道 -> 自分にすべき道` に崩れ、`CER 8.08%` まで悪化した。
- このサンプルでは、ホワイトノイズ単独よりも `reverb` の方が効いている。

Transcript diff:

- Parakeet clean
  - `ペリー氏はテキサスに戻って、今夜のコーカスの結果を見極めし、この選挙戦で自分が進むべき道があるかどうかを判断すると述べましたが、後に選挙戦に残り、1月21日のサウスカロライナ州の予備選に出馬すると述べました。`
- Parakeet 10dB / 5dB
  - `ケリー氏はテキサスに戻って、今夜のコーカスの結果を見極めし、この選挙戦で自分が進むべき道があるかどうかを判断すると述べましたが、後に選挙戦に残り、1月21日のサウスカロライナ州の予備選に出馬すると述べました。`
- Cohere clean
  - `ペリー氏はテキサスに戻って「今夜のコーカスの結果を見極めし、この選挙戦で自分が進むべき道があるかどうかを判断する」と述べましたが、後に選挙戦に残り1月21日のサウスカロライナ州の予備選に出馬すると述べました。`
- Cohere 10dB / 5dB
  - `ケリー氏はテキサスに戻って「今夜のコーカスの結果を見極めし、この選挙戦で自分が進むべき道があるかどうかを判断する」と述べましたが、後に選挙戦に残り1月21日のサウスカロライナ州の予備選に出馬すると述べました。`
- Parakeet babble10+reverb
  - `ペリー氏はテキサスに戻って、今夜のコーカスの結果を見極め、この選挙戦で自分にすべき道があるかどうかを判断すると述べましたが、後に選挙戦に残り、1月21日のサウスカロライナ州の予備選に出馬すると述べました。`

参考:
- MUSAN corpus: https://openslr.org/17/
- OpenRIR / simulated RIRs: https://openslr.org/26/
- Room impulse response and noise database: https://openslr.org/28/
- NeMo augmentation docs: https://docs.nvidia.com/nemo/speech/nightly/asr/configs.html
