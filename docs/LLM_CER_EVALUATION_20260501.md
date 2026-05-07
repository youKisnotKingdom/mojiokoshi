# LLM 文字起こし補正 CER 評価

更新日: 2026-05-01

## 結論

先行研究では、LLM を ASR 後段補正に使うことで CER/WER が改善する例があります。
ただし、今回のアプリで使っている **1-best の文字起こしテキストだけをゼロショットで整形する構成** では、少なくとも FLEURS 日本語テストケースでは CER 改善は確認できませんでした。

今回の実測では、句読点や文の切れ目は整いますが、内容 CER は横ばいまたは悪化しました。
したがって、現状のチャンク精緻化は **読みやすさ改善機能** として扱い、**CER 改善を狙う機能** としてはまだ採用しないほうが安全です。

## 先行研究メモ

- Interspeech 2024 の 1-best 仮説を使う LLM ASR error correction 研究では、事前学習済み多言語 LLM を fine-tune し、1-best ASR 出力だけでも ASR 結果が改善すると報告されています。
- 同論文の表では、日本語の CER が複数 ASR で改善しています。例: Whisper v3 は `11.72% -> 7.87%`、OWSM v3.1 は `10.18% -> 9.34%`。
- 日本語 ASR-LLM の multi-pass augmented generative error correction 研究では、N-best や複数システム仮説、複数 LLM 補正結果を組み合わせる方向が検証されています。
- IBM の conservative data filtering 研究は、日本語 ASR error correction で過補正が問題になることを前提に、補正対象を保守的に絞る重要性を示しています。

参考:

- Investigating ASR Error Correction with Large Language Model and Multilingual 1-best Hypotheses: https://www.isca-archive.org/interspeech_2024/li24h_interspeech.html
- 同 PDF の CER 表: https://www.isca-archive.org/interspeech_2024/li24h_interspeech.pdf
- Benchmarking Japanese Speech Recognition on ASR-LLM Setups with Multi-Pass Augmented Generative Error Correction: https://arxiv.org/abs/2408.16180
- Robust ASR Error Correction with Conservative Data Filtering: https://research.ibm.com/publications/robust-asr-error-correction-with-conservative-data-filtering
- Fewer Hallucinations, More Verification: A Three-Stage LLM-Based Framework for ASR Error Correction: https://arxiv.org/abs/2505.24347

## ローカル評価

### 入力

既存の ASR ノイズロバストネス評価で使った FLEURS 日本語 20 件を使用しました。

| 条件 | 入力 |
| --- | --- |
| clean | `benchmark_runs/noise_robustness/fleurs_subset20/results_clean/parakeet_ja/predictions.jsonl` |
| babble10_reverb | `benchmark_runs/noise_robustness/fleurs_subset20/results_babble10_reverb/parakeet_ja/predictions.jsonl` |

ASR は `Parakeet JA` の既存出力です。
LLM 補正は `qwen3.5-35b-awq-a5000-14`、temperature `0`、アプリ本体のチャンク精緻化プロンプト `app_chunk` で実行しました。

実行コマンド:

```bash
.venv/bin/python scripts/evaluate_llm_cer.py \
  --predictions clean=benchmark_runs/noise_robustness/fleurs_subset20/results_clean/parakeet_ja/predictions.jsonl \
  --predictions babble10_reverb=benchmark_runs/noise_robustness/fleurs_subset20/results_babble10_reverb/parakeet_ja/predictions.jsonl \
  --output-dir benchmark_runs/llm_cer_eval_20260501_parakeet_fleurs20_app_chunk \
  --run-llm \
  --force \
  --temperature 0 \
  --max-tokens 2000
```

結果ファイル:

- `benchmark_runs/llm_cer_eval_20260501_parakeet_fleurs20_app_chunk/summary.md`
- `benchmark_runs/llm_cer_eval_20260501_parakeet_fleurs20_app_chunk/summary.json`
- `benchmark_runs/llm_cer_eval_20260501_parakeet_fleurs20_app_chunk/cases.jsonl`
- `benchmark_runs/llm_cer_eval_20260501_parakeet_fleurs20_app_chunk/corrected/*.txt`

### 指標

| 指標 | 内容 |
| --- | --- |
| strict CER | 句読点・空白も含めた文字単位 CER |
| content CER | Unicode 正規化後、空白と句読点を除いた CER |

LLM 補正は句読点を追加するため、strict CER は読みやすくなるほど悪化しやすいです。
内容の置換・脱落・追加を見る主指標としては content CER を使います。

### 結果

| group | items | strict raw | strict corrected | strict rel. reduction | content raw | content corrected | content rel. reduction | improved | worse |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| babble10_reverb | 20 | 22.11% | 26.53% | -20.00% | 19.01% | 19.71% | -3.64% | 0 | 2 |
| clean | 20 | 10.20% | 13.86% | -35.83% | 7.52% | 7.52% | 0.00% | 0 | 0 |

LLM 呼び出し時間は 40 件合計で約 27 秒でした。
1 件あたり平均は clean が約 `0.67s`、babble10_reverb が約 `0.70s` です。

## 解釈

今回の結果では、アプリ本体のチャンク精緻化プロンプトは CER 改善には効いていません。
主な理由は次の通りです。

- LLM は音声を聞いていないため、ASR が落とした語や誤った固有名詞を安定して復元できない
- FLEURS の正解は句読点が少ないため、読みやすい整形は strict CER では不利になる
- content CER でも、ラテン語・略語・固有名詞まわりで表記を変えると悪化する
- 1-best だけでは、N-best や音響信頼度から「どこを直すべきか」を判断できない

特に noisy 条件では、ASR の崩れたラテン語風表記を LLM が日本語カナ寄りに整えてしまい、参照テキストからは遠ざかるケースがありました。
これは読み物としては自然でも、CER では悪化です。

## 次の評価方針

CER 改善を本当に狙うなら、次の順で試します。

1. 現状の app_chunk 補正は、CER 改善ではなく読みやすさ改善として分けて評価する
2. 補正前後で content 差分が大きい場合は、補正を採用しない guard を入れる
3. 用語集・固有名詞リストを与えた条件で再評価する
4. N-best、ASR confidence、または音声入力モデルを使う構成を PoC する
5. セミナー音声については、gold transcript を作って同じ `scripts/evaluate_llm_cer.py` で測る

現時点の採用判断は、**LLM補正はユーザー表示用の整形には使えるが、CERを下げる根拠としては不足** です。

## 長尺: 東大講義系データ

東大講義系の長尺データでも確認しました。
対象は `benchmark_runs/utokyo_matrix_aligned_20260427/*/parakeet_ja` の既存 ASR 出力と `benchmark_data/reference_gold/*.txt` です。

各ファイルは 74 分から 110 分程度、参照テキストは約 2.7 万字から 4.3 万字です。

重要な前提として、長尺の評価は実運用と同じチャンク境界で行う必要があります。
先に試した `--pair` + `--chunk-chars 5000` は、ASR 後の全文を文字数で分割して LLM に渡す方法です。
これはアプリ本体の「音声をチャンクに分けて ASR し、その ASR チャンクを精緻化する」条件とは異なるため、採用判断には使いません。

実運用相当のテキスト LLM 補正評価では、既存ベンチの `summary.json` に入っている `chunks` をそのまま LLM 補正単位として使います。
評価スクリプトにはこの用途の `--chunk-report` を追加しています。

LLM API 復旧後に回すコマンド:

```bash
.venv/bin/python scripts/evaluate_llm_cer.py \
  --chunk-report BmtnWaUvX_0 benchmark_data/reference_gold/BmtnWaUvX_0.txt benchmark_runs/utokyo_matrix_aligned_20260427/BmtnWaUvX_0/parakeet_ja/summary.json \
  --chunk-report Uw6rKydVzX4 benchmark_data/reference_gold/Uw6rKydVzX4.txt benchmark_runs/utokyo_matrix_aligned_20260427/Uw6rKydVzX4/parakeet_ja/summary.json \
  --chunk-report WSiPUcXNzHU benchmark_data/reference_gold/WSiPUcXNzHU.txt benchmark_runs/utokyo_matrix_aligned_20260427/WSiPUcXNzHU/parakeet_ja/summary.json \
  --chunk-report e73XbWLt5w0 benchmark_data/reference_gold/e73XbWLt5w0.txt benchmark_runs/utokyo_matrix_aligned_20260427/e73XbWLt5w0/parakeet_ja/summary.json \
  --chunk-report jkUMzOFAVV4 benchmark_data/reference_gold/jkUMzOFAVV4.txt benchmark_runs/utokyo_matrix_aligned_20260427/jkUMzOFAVV4/parakeet_ja/summary.json \
  --chunk-report ztkteH9oQJ4 benchmark_data/reference_gold/ztkteH9oQJ4.txt benchmark_runs/utokyo_matrix_aligned_20260427/ztkteH9oQJ4/parakeet_ja/summary.json \
  --output-dir benchmark_runs/llm_cer_eval_20260501_utokyo_chunk_report_app_chunk \
  --run-llm \
  --force \
  --temperature 0 \
  --max-tokens 7000 \
  --context-chars 1000 \
  --retries 3
```

この条件では `--chunk-chars` は使いません。
`summary.json` の ASR チャンクを入力単位にするため、音声分割後の実運用に近い評価になります。

現在は LLM API が `Connection refused` になっているため、上記の本評価は未完了です。
`--run-llm` なしの dry run では、少なくとも `BmtnWaUvX_0` の `summary.json` チャンクを読み込めることと、raw CER が既存の全文 transcript と一致することを確認しています。

### 参考: 文字数チャンクの暫定結果

下表は `--pair` + `--chunk-chars 5000` で取得した途中結果です。
実運用チャンクではないため、採用判断には使いません。
LLM サーバーが 3 本目で接続不能になったため、LLM 補正後 CER は 2 本分だけ取得できています。

| id | 長さ | raw strict | raw content | corrected strict | corrected content |
| --- | ---: | ---: | ---: | ---: | ---: |
| `BmtnWaUvX_0` | 109.5 分 | 22.55% | 20.56% | 26.68% | 20.62% |
| `Uw6rKydVzX4` | 74.4 分 | 22.35% | 20.60% | 26.22% | 20.91% |
| `WSiPUcXNzHU` | 90.0 分 | 28.35% | 25.72% | - | - |
| `e73XbWLt5w0` | 82.2 分 | 24.14% | 22.45% | - | - |
| `jkUMzOFAVV4` | 108.1 分 | 16.06% | 13.41% | - | - |
| `ztkteH9oQJ4` | 103.8 分 | 17.07% | 14.69% | - | - |

暫定的に取得できた 2 本では、短文 FLEURS と同じ傾向です。
句読点や段落は整うため strict CER は悪化し、句読点を除いた content CER でも改善は確認できませんでした。

| id | content CER 変化 |
| --- | ---: |
| `BmtnWaUvX_0` | `20.56% -> 20.62%` |
| `Uw6rKydVzX4` | `20.60% -> 20.91%` |

### 長尺で見えた追加リスク

- LLM 補正後の出力が ASR 生出力より長くなりやすい
- 長尺では実ASRチャンクでも 1 本あたり複数回の LLM 呼び出しが必要
- 今回は 3 本目で `Server disconnected without sending a response` のあと、API が `Connection refused` になった
- そのため、長尺の全件補正は API サーバーへの負荷と失敗時再開を前提に設計する必要がある

長尺でも、現時点では **CER改善目的でLLM補正を全面適用する根拠はまだない** という判断です。
実運用で入れるなら、表示用の整形結果として生ASRとは別に保持し、CERや内容一致を悪化させた場合に生ASRへ戻せる構成が必要です。

### 音声入力モデルを評価する場合

音声を聞けるモデルを評価する場合も、同じ考え方です。
全文音声を一括で投げるのではなく、実運用と同じ音声チャンクを入力単位にします。

- 同じ音声チャンク長、サンプリングレート、前処理で分割する
- 各チャンクごとに音声入力モデルへ投げる
- 必要なら ASR 生テキストも同時に渡して「音声 + 1-best ASR」の補正として評価する
- チャンク出力を連結し、全文の strict CER / content CER を計算する
- 同じ gold transcript に対して Parakeet 生出力、テキストLLM補正、音声入力モデル補正を横並びにする

## 代替 Gemma の性能メモ

`192.168.86.24:8000` の `google/gemma-4-E4B-it` でも一時評価しました。
このモデルは `/v1/models` 上の `max_model_len` が `1536` です。

短文 FLEURS 10 件では、アプリ本体の `app_chunk` プロンプトで補正は完走しました。

| 条件 | 値 |
| --- | ---: |
| 件数 | 10 |
| LLM呼び出し合計 | 27.38 秒 |
| 1件平均 | 2.74 秒 |
| 1件p50 | 3.19 秒 |
| 1件最大 | 3.85 秒 |
| 平均prompt tokens | 366.6 |
| 平均completion tokens | 35.8 |
| content CER | `2.24% -> 2.24%` |

結果ファイル:

- `benchmark_runs/llm_cer_eval_20260501_gemma_fleurs10_app_chunk/summary.md`
- `benchmark_runs/llm_cer_eval_20260501_gemma_fleurs10_app_chunk/cases.jsonl`

一方で、長尺の実ASRチャンクにはコンテキストが足りません。
`BmtnWaUvX_0` の実ASRチャンク1本を投げると、チャンク本文 1,816 文字、プロンプト 2,128 文字で、`input 1153 + output 384 = 1537` となり `max_model_len=1536` を超えて `400 BadRequest` になりました。

東大講義系データの実ASRチャンクは 115 個あり、現在の一時設定 `LLM_CHUNK_REFINEMENT_MAX_INPUT_CHARS=900` を超えるものが 114 個です。
そのため、この代替Gemmaを使う間は、長尺チャンクの大半は精緻化をスキップして生テキストを保持する挙動になります。

代替Gemmaは短文・短い音声の疎通確認には使えますが、300秒チャンクの長尺精緻化を実運用条件で評価するには小さすぎます。
長尺精緻化を評価するなら、元の大きいLLMを復旧するか、音声/ASRチャンク秒数を大きく短縮してから別条件として測る必要があります。

## 復旧後 Qwen 35B の性能メモ

2026-05-07 に `192.168.86.14:7801` の `qwen3.5-35b-awq-a5000-14` を再測定しました。
`/v1/models` と短い `/v1/chat/completions` は正常応答し、短文ベンチも完走しました。

短文 FLEURS 10 件:

| 条件 | 値 |
| --- | ---: |
| 件数 | 10 |
| LLM呼び出し合計 | 15.25 秒 |
| 1件平均 | 1.53 秒 |
| 1件p50 | 0.70 秒 |
| 1件最大 | 9.30 秒 |
| 平均prompt tokens | 343.5 |
| 平均completion tokens | 35.7 |
| content CER | `2.24% -> 2.24%` |

結果ファイル:

- `benchmark_runs/llm_cer_eval_20260507_qwen14_fleurs10_app_chunk/summary.md`
- `benchmark_runs/llm_cer_eval_20260507_qwen14_fleurs10_app_chunk/cases.jsonl`

Gemma でコンテキスト不足になった `BmtnWaUvX_0` の実ASRチャンク1本は、Qwen 35B では正常終了しました。

| 項目 | 値 |
| --- | ---: |
| チャンク本文 | 1,816 文字 |
| プロンプト全体 | 2,128 文字 |
| prompt tokens | 1,139 |
| completion tokens | 1,009 |
| total tokens | 2,148 |
| elapsed | 9.77 秒 |
| finish_reason | `stop` |

この単発結果を見る限り、Qwen 35B 側は実ASRチャンク1本のコンテキスト容量は足りています。

ただし、代表長尺1本 `BmtnWaUvX_0` を `--chunk-report` で実ASRチャンク単位に連続処理したところ、chunk 3 で `Server disconnected without sending a response` が発生し、その後 `.14` は `Connection refused` になりました。
30 秒ほど再試行しても `/v1/models` は復帰しませんでした。

したがって、復旧後の Qwen 35B は **短文と単発長尺チャンクの性能は良いが、長尺連続処理ではまだサーバー安定性に問題がある** という評価です。
実運用長尺を回すには、LLMサーバー側の再起動監視、またはチャンク間の待機・max_tokens削減・再開可能な評価ランナーが必要です。
