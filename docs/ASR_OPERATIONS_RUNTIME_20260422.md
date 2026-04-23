# ASR Operations Runtime Report

更新日: 2026-04-23

このレポートは、現行デプロイ構成での実運用挙動を整理したものです。  
対象は「複数ユーザーが同時にアップロードしたときに、DB・worker・モデル実行がどう振る舞うか」です。

関連ファイル:
- 管理画面: `/admin/operations`
- SQL claim 実測: [queue_claim_test_20260421.json](/home/ykadono/dev/mojiokoshi/benchmark_runs/queue_claim_test_20260421.json:1)
- stuck job 実測: [stale_job_recovery_test_20260422.json](/home/ykadono/dev/mojiokoshi/benchmark_runs/stale_job_recovery_test_20260422.json:1)
- Parakeet worker 実行実測:
  - [1job c1](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_1job_c1.json:1)
  - [2job c1](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_2job_c1.json:1)
  - [2job c2](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_2job_c2.json:1)
  - [5job c1](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_5job_c1.json:1)
  - [5job c2](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_5job_c2.json:1)
  - [5job scale1](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_5job_scale1_1worker.json:1)
  - [5job scale2](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_5job_scale2_2workers.json:1)
- モデル別待ち時間レポート: [ASR_OPERATIONS_CONCURRENCY_20260421.md](/home/ykadono/dev/mojiokoshi/docs/ASR_OPERATIONS_CONCURRENCY_20260421.md:1)

## 現行デプロイ構成

2026-04-22 時点の Docker 既定値は以下です。

- `DEFAULT_TRANSCRIPTION_ENGINE=parakeet_ja`
- `WORKER_WHISPER_DEVICE=cuda`
- `WORKER_TRANSCRIPTION_CONCURRENCY=1`
- `WORKER_SUMMARY_CONCURRENCY=1`
- `ENABLE_REALTIME_TRANSCRIPTION=false`
- `WEB_WHISPER_DEVICE=cpu`

つまり、本番相当構成は:

- batch 文字起こしエンジン: `Parakeet JA`
- 実行デバイス: `GPU (worker)`
- 同時文字起こし実行数: `1 worker process`
- リアルタイム録音 UI: `off` 前提
- `web` / `checker` は CPU のみ

補足:
- アプリ本体の batch worker は `Parakeet JA` と `faster-whisper` のみサポートします。
- `job.engine` が他モデルでも、現行 production worker は `Cohere` / `Qwen` / `vLLM` へは分岐しません。
- `vLLM` の request batching / continuous batching は現行アプリ本体には入っていません。

## 1. SQL claim の実測

`pending` ジョブ 2 件に対して、2 worker が同時に取りに行く再現試験を行いました。

結果:
- plain `SELECT ... LIMIT 1`
  - 両 worker が **同じ job** を取得
- `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1`
  - 両 worker が **別 job** を取得

要点:
- `SKIP LOCKED` は重複実行防止に効く
- 複数 worker 化するなら必須

## 2. worker 落下時の挙動

1 件の job を claim した直後に worker が落ちた、という状態を再現しました。

結果:
- 最初の claim: 成功
- stale timeout 超過後の recovery: 成功
- その後の再claim: 同じ job を再取得
- job status: `processing` へ再遷移

要点:
- `PROCESSING` に入ったまま timeout を超えた job は自動で `PENDING` に戻る
- worker / container が落ちても、timeout 後に再取得できる
- ただし timeout を短くしすぎると、正常に長く動いている job を誤回収する可能性がある

現状の実装では、`transcription=3600s`, `summary=1800s` を既定値にしています。

## 3. 現行 worker の実効スループット

30 秒の seminar 音声で実測しました。  
音声ファイル: `2026-04-16_seminar_sample_00m45s_30s.wav`

テスト時は background worker の干渉を避けるため、実行用 container 内で直接 job を作って処理しています。  
コードパス自体は本番 worker と同じ `Parakeet` 実装です。

### 単発 1 job

- 条件: `jobs=1`, `concurrency=1`
- 実測: `13.631秒`
- 30 秒音声に対して `2.20x realtime`

これは **cold start** を含む値です。  
`Parakeet` の model restore が支配的です。

### 2 job 直列

- 条件: `jobs=2`, `concurrency=1`
- 実測: `13.127秒`
- 60 秒分の音声に対して `4.57x realtime`

job ごとの終了時刻:
- 1 件目: 開始から約 `13.0秒`
- 2 件目: その後さらに約 `0.26秒`

要点:
- **最初の 1 件目だけが高コスト**
- 同一 process 内で model が warm になった後の短い job はかなり速い

### 2 job 並列設定

- 条件: `jobs=2`, `concurrency=2`
- 実測: `13.250秒`

job ごとの終了時刻:
- 2 件ともほぼ同時に `processing` へ遷移
- でも全体 wall time は `concurrency=1` とほぼ同じ

### 解釈

`concurrency=2` にしても、全体時間は:

- `c1`: `13.127秒`
- `c2`: `13.250秒`

で、**改善しませんでした**。

理由はコード上も自然で、現在の worker 実行は `asyncio.gather(...)` を使っていても、実際の文字起こしは同期的に `transcribe_batch_job_sync(...)` を回しています。  
そのため、同一 process 内では「設定上 2 件」でも、実効的にはほぼ逐次処理です。

要点:
- `WORKER_TRANSCRIPTION_CONCURRENCY=2` を上げても、今の実装では性能改善は期待しにくい
- 真面目に並列化するなら、別 process / 別 worker での実行が前提

## 3.5 5 job 同時投入の短い queue 実測

同じ 30 秒サンプルを 5 件同時投入し、短い job がどう待つかも確認しました。

### 5 job, concurrency=1

- 条件: `jobs=5`, `concurrency=1`
- 実測: `15.237秒`

挙動:
- 1 件目は cold start を含み約 `13.7秒`
- 残り 4 件は warm state で合計約 `1.5秒`

### 5 job, concurrency=2

- 条件: `jobs=5`, `concurrency=2`
- 実測: `14.884秒`

挙動:
- 最初の 2 件は同時に `processing` へ入る
- ただし全体時間は `concurrency=1` とほぼ同じ

要点:
- 短い job が大量に来ても、cold start さえ抜ければ queue はすぐ流れる
- ただし `concurrency=2` を上げても、同一 process 内では wall time はほぼ縮まらない

## 3.6 実 worker 2 本の queue drain 実測

同じ 30 秒サンプル 5 件を、今度は **実際の worker container** に流して比較しました。

### scale=1 worker

- 条件: `worker=1`, `jobs=5`
- 実測: `32.261秒`

挙動:
- 最初の 1 件が約 `27.1秒`
- 残り 4 件は合計約 `0.46秒`
- cold start が支配的

### scale=2 workers

- 条件: `worker=2`, `jobs=5`
- 実測: `16.588秒`

挙動:
- 最初の 2 件が別 worker に割り振られる
- 2 worker とも `Parakeet` を個別ロードする
- その後の残り 3 件は warm 状態で高速に完了

要点:
- `SKIP LOCKED` により、複数 worker でも job はきれいに分散した
- 同一 process の `concurrency=2` より、**別 worker 2 本** の方が明確に効く
- ただし GPU 上では `Parakeet` の cold start が **2 回** 走る
- worker を増やすと throughput は上がるが、GPU メモリと初期化コストはその分増える

## 4. 実運用で読むべき値

実運用では 2 種類の時間を分けて見る必要があります。

### cold start

- worker 再起動後の最初の job は、今回の host では約 `13.6秒` の初期化コストが乗る

### warm state

- 長い音声を継続的に処理する steady-state は、ベンチの `xRealtime` を使って見る方が正確
- `Parakeet` の長尺 benchmark は約 `144.16x realtime`
- 1 時間音声 1 本の概算は約 `25秒`

つまり:
- **最初の 1 本だけ少し重い**
- **連続投入時の本質的な throughput は benchmark 値に近い**

## 4.1 1時間音声での worker 数比較

長尺の実運用に近づけるため、`1時間音声` を `mono / 16kHz` に正規化し、`Parakeet` の production 経路と同じ chunking を通して worker 数を比較しました。

### chunk=300秒

- `1 worker / 1 job`: `25.623秒`
- `1 worker / 2 jobs`: `55.789秒`
- `2 workers / 2 jobs`: `53.719秒`
- `3 workers / 3 jobs`: OOM

要点:
- `300秒` では `1 worker` は安定
- `2 workers` までは通る
- `3 workers` はこの GPU では載らない

### chunk=120秒, 3 jobs 固定の公平比較

`worker=1/2/3` を同じ `1時間音声 3本` で揃えて比較しました。

- `1 worker / 3 jobs`: `77.943秒`
- `2 workers / 3 jobs`: `64.811秒`
- `3 workers / 3 jobs`: `61.247秒`

要点:
- `1 -> 2 workers` は意味がある
- `2 -> 3 workers` の改善はかなり小さい
- `3 workers` を通すには `chunk=120秒` まで短くする必要があった
- `4 workers / 4 jobs / chunk=120秒` は OOM

運用判断:
- **安全運用**: `worker=1`, `chunk=300`
- **実用上の上限**: `worker=2`
- **攻めた構成**: `worker=3`, `chunk=120`, 他の GPU プロセス停止

関連結果:
- [1hour / 1job / scale1 / chunk300](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_1hour_mono16_1job_scale1_chunked.json:1)
- [1hour / 2jobs / scale1 / chunk300](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_1hour_mono16_2job_scale1_chunked.json:1)
- [1hour / 2jobs / scale2 / chunk300](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_1hour_mono16_2job_scale2_chunked.json:1)
- [1hour / 3jobs / scale1 / chunk120](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_1hour_mono16_3job_scale1_chunk120.json:1)
- [1hour / 3jobs / scale2 / chunk120](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_1hour_mono16_3job_scale2_chunk120.json:1)
- [1hour / 3jobs / scale3 / chunk120](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_1hour_mono16_3job_scale3_chunk120.json:1)
- [1hour / 4jobs / scale4 / chunk120](/home/ykadono/dev/mojiokoshi/benchmark_runs/ops_worker_runtime_parakeet_1hour_mono16_4job_scale4_chunk120.json:1)

## 4.2 chunk 長と CER のトレードオフ

`Parakeet` について、東大講義 3 本 (`BmtnWaUvX_0`, `jkUMzOFAVV4`, `ztkteH9oQJ4`) を `chunk=60/120/300秒` で比較しました。

平均:

- `60秒`: `CER 20.58%`, `169.28x realtime`
- `120秒`: `CER 19.20%`, `186.37x realtime`
- `300秒`: `CER 18.56%`, `143.47x realtime`
- `600秒`: `BmtnWaUvX_0` 単体で **2 chunk 目に OOM**（CER 未完）

読み方:
- `300秒` が一番精度は良い
- ただし `120秒` は平均で `+0.64pt` の悪化に留まり、速度はむしろ良かった
- `60秒` まで刻むと劣化がはっきり見え始める
- `600秒` まで伸ばすと、この GPU では単独実行でも VRAM 余裕が足りず非現実的

したがって、`worker=3` を成立させるために `120秒` へ落とす判断はあり得るが、`60秒` まで短くする優先度は低い。
逆に `600秒` のように長くする方向は、精度上の利益があってもこのマシンでは採りにくい。

関連結果:
- [chunk sweep reports](/home/ykadono/dev/mojiokoshi/benchmark_runs/chunk_cer_sweep_20260423)

## 5. 実運用上の結論

現時点で言えること:

- 複数アップロード自体は受けられる
- `SKIP LOCKED` により、複数 worker 化の土台はできた
- 現行 batch 本番経路は `Parakeet JA / GPU / worker 1本`
- ただし 1 process 内の `concurrency` を上げても実効並列にはなりにくい
- worker が途中で落ちた job も、stale timeout 後に再取得できる

## 6. 次の実装優先順位

1. queue 長 / 待ち時間 / 処理時間の可視化
2. worker 数を増やしたときの GPU 使用量・安定性の継続観測
3. stuck job の管理画面 / 手動再投入導線
4. 必要なら `Cohere` を batch engine 候補として再計測

## 7. 推奨判断

現行の方向性は妥当です。

- 本番 batch engine: `Parakeet`
- `realtime` は分離し、当面 `off`
- queue の安全性は `SKIP LOCKED` で確保
- worker crash 後の stuck job は timeout ベースで自動回収

次に優先すべきなのは **運用の見える化** です。  
具体的には、queue の長さと待ち時間を UI や監視で見えるようにし、必要なら `worker=2` までを段階的に使うのがよいです。
